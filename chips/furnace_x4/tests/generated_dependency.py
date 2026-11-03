#!/usr/bin/env python3
"""Opt-in assignment-driven scheduling in disposable generated C++.

Only pure scalar ico regions are guarded. Local-variable live ranges are merged,
including read-only uses; unsupported regions and array aliases stay unconditional.
All generated translation units are audited before any rewrite. Every supported
writer notifies scalar dependents on a value change, including NBA writers;
initialization writers notify unconditionally, without reading uninitialized data.
Unclassifiable accesses exclude the field and all regions that depend on it.
No cached outputs, sequential scheduling changes, or model storage changes.
"""

from collections import defaultdict
import re

from generated_replay import statements
from generated_scalar import FUNCTION, scalar_fields


TOKEN = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'"
    r"|[A-Za-z_]\w*|(?:0[xX][0-9a-fA-F]+|\d+)[\w.]*"
    r"|>>=|<<=|->|::|\+\+|--|&&|\|\||==|!=|<=|>=|[-+*/%&|^]=|[^\s]", re.S)
PURE = {
    "if", "switch", "while", "for", "sizeof", "alignof",
    "CData", "SData", "IData", "QData",
    "VL_SHIFTL_III", "VL_SHIFTR_III", "VL_SHIFTRS_III",
    "VL_SHIFTRS_QQI", "VL_GTES_IQQ", "VL_LTES_III", "VL_LTS_IQQ",
}
LOCAL = re.compile(
    r"\b(?:CData|SData|IData|QData|VlWide<\d+>)\s*(?:/\*.*?\*/)?\s+(\w+)\s*;")
FIELD = re.compile(r"\bvlSelf->(\w+)")


def tokens(text):
    return [m for m in TOKEN.finditer(text)
            if not m[0].startswith(("//", "/*"))]


def audit(text, types):
    """Classify scalar writes; unfamiliar call/reference/update forms are unsafe."""
    ts = tokens(text)
    unsafe, writes = set(), []
    calls = []
    for i, t in enumerate(ts):
        word = t[0]
        if word == "(":
            previous = ts[i - 1][0] if i else ""
            callee = previous if re.fullmatch(r"[A-Za-z_]\w*", previous) else ""
            calls.append(callee)
        elif word == ")":
            if calls:
                calls.pop()
        if word != "vlSelf" or i + 2 >= len(ts) or ts[i + 1][0] != "->":
            continue
        field = ts[i + 2][0]
        if field not in types:
            continue
        following = ts[i + 3][0] if i + 3 < len(ts) else ""
        previous = ts[i - 1][0] if i else ""
        if any(call and call not in PURE for call in calls):
            unsafe.add(field)
        if following in ("[", ".", "->", "++", "--", "+=", "-=", "*=", "/=",
                         "%=", "&=", "|=", "^=", "<<=", ">>="):
            unsafe.add(field)
        if previous in ("++", "--") or (
                previous == "&" and (i < 2 or ts[i - 2][0] in ("(", ",", "=", "{"))):
            unsafe.add(field)
        if following != "=":
            continue
        # A standalone simple assignment, not a condition, chain or for header.
        if calls or previous not in ("", ";", "{", "}"):
            unsafe.add(field)
            continue
        end = i + 4
        nesting = 0
        while end < len(ts):
            item = ts[end][0]
            if item in ("(", "["):
                nesting += 1
            elif item in (")", "]"):
                nesting -= 1
            if item == ";" and nesting == 0:
                break
            if item in ("=", "++", "--") or nesting < 0:
                unsafe.add(field)
            end += 1
        if end == len(ts):
            unsafe.add(field)
        else:
            writes.append((t.start(), ts[end].end(), field))
    # Numeric scalars must never escape through an alias, even a const reference.
    for match in re.finditer(r"(?:auto|CData|SData|IData|QData)\s*(?:const\s*)?[&*]"
                             r"[^;]*;", text):
        unsafe.update(FIELD.findall(match[0]))
    return unsafe, writes


def regions(code, init):
    parts = list(statements(code))
    locals_ = set(LOCAL.findall(init))
    spans = {}
    for i, part in enumerate(parts):
        for name in set(re.findall(r"\b[A-Za-z_]\w*\b",
                                   FIELD.sub("", part))) & locals_:
            low, _ = spans.get(name, (i, i))
            spans[name] = (low, i)
    # A local initialized outside Body is recreated on every call; never skip
    # its writer while executing a later consumer with the initialization value.
    result, start = [], 0
    while start < len(parts):
        end = start
        while True:
            extended = max([end, *(high for low, high in spans.values()
                                   if low <= end and high >= start)])
            if extended == end:
                break
            end = extended
        result.append("".join(parts[start:end + 1]))
        start = end + 1
    return result, locals_


def pure_region(code, locals_, types, unsafe):
    fields = set(FIELD.findall(code))
    if not fields or fields - types.keys() or fields & unsafe:
        return False
    calls = set(re.findall(r"\b(\w+)\s*\(", code))
    if calls - PURE or re.search(
            r"\b(?:return|goto|while|for|switch|throw|new|delete|static|volatile|"
            r"vlSymsp|reinterpret_cast|const_cast|asm)\b|[\"'#]|//|/\*", code):
        return False
    if re.search(r"\bvlSelf\b(?!->)|\+\+|--|(?<![=<>!])[-+*/%&|^]=", code):
        return False
    free = FIELD.sub("", code)
    free = re.sub(r"\b(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b", "", free)
    return not (set(re.findall(r"\b[A-Za-z_]\w*\b", free))
                - locals_ - PURE - {"else"})


def transform(sources, header):
    """Return rewritten files, sideband header, and the complete dependency audit."""
    types = scalar_fields(header)
    audits = {name: audit(text, types) for name, text in sources.items()}
    unsafe = set().union(*(row[0] for row in audits.values()))
    # Alternate member spelling or implicit member mutation is not guessed.
    for text in sources.values():
        unsafe.update(name for name in re.findall(r"(?<!vlSelf)->(\w+)\b", text)
                      if name in types)
    selected, functions = [], {}
    for filename, text in sources.items():
        for match in FUNCTION.finditer(text):
            if "// Body\n" not in match[2]:
                raise ValueError("missing generated Body marker")
            init, code = match[2].split("// Body\n", 1)
            chunks, locals_ = regions(code, init)
            entries = []
            for chunk in chunks:
                if pure_region(chunk, locals_, types, unsafe):
                    number = len(selected)
                    fields = sorted(set(FIELD.findall(chunk)))
                    entries.append((number, chunk))
                    selected.append({"region": number, "function": match[1],
                                     "fields": fields, "body_bytes": len(chunk)})
                else:
                    entries.append((None, chunk))
            functions[match[1]] = (init, entries)
    if not selected:
        raise ValueError("no safely schedulable dependency regions")
    dependencies = defaultdict(list)
    for row in selected:
        # Written fields are dependencies too: another writer may overwrite a
        # stable result (WAW), even if none of its original inputs changed.
        for field in row["fields"]:
            dependencies[field].append(row["region"])
    fields = sorted(dependencies)
    field_ids = {name: i for i, name in enumerate(fields)}
    public = set(re.findall(r"VL_(?:IN|OUT|INOUT)(?:8|16|64)?\((\w+),", header))
    changed, writer_counts = {}, {}
    for filename, text in sources.items():
        edits = []
        for start, end, field in audits[filename][1]:
            if field not in dependencies:
                continue
            original = text[start:end]
            notify = f"furnace_dependency::touch(vlSelf, {field_ids[field]});"
            # Slow files include constructor initialization. Never read old bytes.
            if "Slow" in filename:
                replacement = "{ " + original + " " + notify + " }"
            else:
                replacement = (
                    "{ const auto furnace_dependency_before = vlSelf->" + field
                    + "; " + original + "\nif (furnace_dependency_before != vlSelf->"
                    + field + ") " + notify + " }")
            edits.append((start, end, replacement))
            writer_counts[field] = writer_counts.get(field, 0) + 1
        for start, end, replacement in reversed(edits):
            text = text[:start] + replacement + text[end:]

        def guard(match):
            init, entries = functions[match[1]]
            # Re-split the instrumented body using original region boundaries by
            # applying exactly the same per-write edits within each original chunk.
            rendered = []
            for number, chunk in entries:
                _bad, assignments = audit(chunk, types)
                for start, end, field in reversed(assignments):
                    if field not in dependencies:
                        continue
                    original = chunk[start:end]
                    chunk = (chunk[:start] + "{ const auto furnace_dependency_before = vlSelf->"
                             + field + "; " + original
                             + "\nif (furnace_dependency_before != vlSelf->" + field + ") "
                             + f"furnace_dependency::touch(vlSelf, {field_ids[field]}); }}"
                             + chunk[end:])
                if number is not None:
                    chunk = (f"\nif (furnace_dependency::take(vlSelf, {number})) {{\n"
                             + chunk + "\n}\n")
                rendered.append(chunk)
            return (f"VL_INLINE_OPT void {match[1]}(Vfurnace_x4_top___024root* vlSelf) {{"
                    + init + "// Body\n" + "".join(rendered) + "\n}")

        text = FUNCTION.sub(guard, text)
        # Public references are written by the host, not generated assignments.
        # Poll only that boundary. Every reset transition invalidates all regions.
        entry = re.compile(r"(void \w+___eval\(Vfurnace_x4_top___024root\* vlSelf\) \{)")
        prologue = "\nfurnace_dependency::boundary(vlSelf, vlSelf->rst_n);\n"
        for field in fields:
            if field in public:
                prologue += (f"furnace_dependency::input(vlSelf, {field_ids[field]}, "
                             f"vlSelf->{field});\n")
        text, count = entry.subn(lambda m: m[0] + prologue, text)
        if text != sources[filename]:
            text = '#include "generated_dependency.h"\n' + text
        changed[filename] = text
        if count:
            writer_counts["_eval_entries"] = writer_counts.get("_eval_entries", 0) + count
    if writer_counts.get("_eval_entries") != 1:
        raise ValueError("dependency scheduling requires exactly one model eval boundary")
    header_text = runtime_header(selected, fields, dependencies)
    return changed, header_text, {
        "regions": selected, "watched_fields": fields, "writers": writer_counts,
        "excluded_fields": sorted(unsafe),
        "public_boundary_fields": sorted(public & dependencies.keys()),
        "unconditional_regions": sum(
            number is None for _init, entries in functions.values() for number, _ in entries),
    }


def runtime_header(selected, fields, dependencies):
    cases = []
    for i, field in enumerate(fields):
        body = " ".join(f"s.dirty[{region}] = true;" for region in dependencies[field])
        cases.append(f"case {i}: {body} break;")
    return r"""#ifndef FURNACE_GENERATED_DEPENDENCY_H
#define FURNACE_GENERATED_DEPENDENCY_H
#include <array>
#include <cstdint>
namespace furnace_dependency {
struct State {
    const void* owner = nullptr;
    bool reset_seen = false, reset = false;
    std::array<bool, """ + str(len(selected)) + r"""> dirty{};
    std::array<uint64_t, """ + str(len(fields)) + r"""> inputs{};
    std::array<bool, """ + str(len(fields)) + r"""> input_seen{};
};
inline thread_local State state;
inline State& bind(const void* owner) {
    if (state.owner != owner) {
        state = State{};
        state.owner = owner;
        state.dirty.fill(true);
    }
    return state;
}
inline void touch(const void* owner, unsigned field) {
    auto& s = bind(owner);
    switch (field) {
""" + "\n".join(cases) + r"""
    }
}
inline void boundary(const void* owner, bool reset) {
    auto& s = bind(owner);
    if (!s.reset_seen || s.reset != reset) s.dirty.fill(true);
    s.reset = reset;
    s.reset_seen = true;
}
inline void input(const void* owner, unsigned field, uint64_t value) {
    auto& s = bind(owner);
    if (!s.input_seen[field] || s.inputs[field] != value) touch(owner, field);
    s.inputs[field] = value;
    s.input_seen[field] = true;
}
inline bool take(const void* owner, unsigned region) {
    auto& s = bind(owner);
    const bool dirty = s.dirty[region];
    s.dirty[region] = false;
    return dirty;
}
}
#endif
"""


def optimize(directory, digest):
    header = (directory / "Vfurnace_x4_top___024root.h").read_text()
    paths = sorted(directory.glob("Vfurnace_x4_top___024root*.cpp"))
    originals = {path.name: path.read_text() for path in paths}
    changed, sideband, report = transform(originals, header)
    # Deserialization uses implicit members, not vlSelf. The experiment never
    # restores checkpoints, but a future caller must not inherit stale dirty bits.
    restore_entries = 0
    for name in changed:
        changed[name], count = re.subn(
            r"(void Vfurnace_x4_top___024root::__Vdeserialize\([^)]*\) \{)",
            lambda m: m[0] + "\nfurnace_dependency::invalidate(this);\n", changed[name])
        restore_entries += count
        if count and not changed[name].startswith('#include "generated_dependency.h"'):
            changed[name] = '#include "generated_dependency.h"\n' + changed[name]
    if "__Vdeserialize(" in "".join(originals.values()) and restore_entries != 1:
        raise ValueError("unrecognized generated deserialization entry")
    report["deserialization_invalidation_entries"] = restore_entries
    destination = directory / "generated_dependency.h"
    with destination.open("x") as stream:
        stream.write(sideband)
    report["header_sha256"] = digest(destination)
    report["files"] = []
    for path in paths:
        if originals[path.name] == changed[path.name]:
            continue
        before = digest(path)
        snapshot = path.with_suffix(".dependency-original")
        with snapshot.open("x") as stream:
            stream.write(originals[path.name])
        path.write_text(changed[path.name])
        report["files"].append({
            "file": path.name, "before_sha256": before, "after_sha256": digest(path),
            "original": snapshot.name,
        })
    return report
