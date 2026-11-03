#!/usr/bin/env python3
"""Fail-closed, field-identified comparison of generated savable model state.

This is an execution-backend diagnostic, not a functional RTL oracle. A name
match alone never authorizes omission of a backend-only field. The only current
omission rule proves that every generated function overwrites the entire scalar
before its first read; split-function NBA temporaries remain unresolved.
"""

import hashlib
import json
import math
from pathlib import Path
import re
import struct


SCALAR_BYTES = {"CData": 1, "SData": 2, "IData": 4, "QData": 8, "bool": 1}
SERIALIZER = re.compile(r"void (\w+)::__Vserialize\(VerilatedSerialize& os\) \{")
FUNCTION = re.compile(
    r"(?m)^(?:(?:VL_INLINE_OPT|VL_ATTR_COLD) )*void (\w+)"
    r"\([^;{}]*\) \{")
REFERENCE = re.compile(r"\bvlSelf->(\w+)")
MAGIC = b"FURNACE-LOGICAL-STATE-1\n"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_cpp(text):
    """Keep offsets/newlines while removing comments and quoted literals."""
    token = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    return token.sub(lambda m: "".join("\n" if c == "\n" else " " for c in m[0]), text)


def closing(text, opening):
    depth = 1
    for offset in range(opening + 1, len(text)):
        depth += (text[offset] == "{") - (text[offset] == "}")
        if depth == 0:
            return offset
    raise ValueError("unclosed generated C++ block")


def type_shape(value):
    value = value.strip()
    unpacked = re.fullmatch(r"VlUnpacked<(.*),\s*(\d+)>", value)
    if unpacked:
        nested = type_shape(unpacked[1])
        return {**nested, "shape": [int(unpacked[2]), *nested["shape"]]}
    scalar = re.fullmatch(r"(CData|SData|IData|QData)/\*(\d+):0\*/", value)
    wide = re.fullmatch(r"VlWide<(\d+)>/\*(\d+):0\*/", value)
    if scalar:
        size = SCALAR_BYTES[scalar[1]]
        bits = int(scalar[2]) + 1
        if not 0 < bits <= size * 8:
            raise ValueError("scalar logical width exceeds storage")
        return {"bits": bits, "shape": [], "element_bytes": size, "words": 1}
    if wide:
        words, bits = int(wide[1]), int(wide[2]) + 1
        if words != (bits + 31) // 32:
            raise ValueError("wide logical width/storage mismatch")
        return {"bits": bits, "shape": [], "element_bytes": 4, "words": words}
    if value == "bool":
        return {"bits": 1, "shape": [], "element_bytes": 1, "words": 1}
    raise ValueError(f"unrecognized serialized field type: {value}")


def declarations(text):
    fields = {}
    unsaved = {}
    for line in text.splitlines():
        line = line.strip()
        port = re.fullmatch(r"VL_(?:IN|OUT|INOUT)(8|16|64|W)?\((\w+),(\d+),0(?:,(\d+))?\);", line)
        if port:
            bits = int(port[3]) + 1
            width = port[1]
            storage = {"8": 1, "16": 2, "64": 8, None: 4, "W": 4}[width]
            words = int(port[4]) if width == "W" else 1
            if words != ((bits + 31) // 32 if width == "W" else 1) or bits > storage * words * 8:
                raise ValueError("port width/storage mismatch")
            fields[port[2]] = {"bits": bits, "shape": [], "element_bytes": storage, "words": words}
            continue
        data = re.fullmatch(r"((?:VlUnpacked<.*>|VlWide<\d+>/\*\d+:0\*/|"
                            r"(?:CData|SData|IData|QData)/\*\d+:0\*/|bool))\s+(\w+);", line)
        if data:
            if data[2] in fields:
                raise ValueError(f"duplicate declaration: {data[2]}")
            fields[data[2]] = type_shape(data[1])
            continue
        scheduler = re.fullmatch(r"(VlTriggerVec<\d+>|VlMTaskVertex)\s+(\w+);", line)
        if scheduler:
            unsaved[scheduler[2]] = scheduler[1]
    return fields, unsaved


def serializer_writes(body):
    """Parse every statement, retaining loop extents instead of a set of names."""
    body = re.sub(r"\s+", " ", clean_cpp(body)).strip()
    rows = []

    def parse(position, loops, nested):
        while position < len(body):
            while position < len(body) and body[position].isspace():
                position += 1
            if position == len(body):
                break
            if body[position] == "}":
                if not nested:
                    raise ValueError("unexpected serializer closing brace")
                return position + 1
            tail = body[position:]
            check = re.match(r"uint64_t __Vcheckval = (0x[0-9a-fA-F]+)ULL;", tail)
            loop = re.match(r"for \(int (\w+) = 0; \1 < (\d+); \+\+\1\) \{", tail)
            write = re.match(r"os\s*<<\s*([^;]+);", tail)
            if check and not loops:
                rows.append({"kind": "signature", "value": int(check[1], 16)})
                position += check.end()
            elif loop:
                if int(loop[2]) < 1 or any(name == loop[1] for name, _ in loops):
                    raise ValueError("invalid serializer loop")
                position = parse(position + loop.end(), [*loops, (loop[1], int(loop[2]))], True)
            elif write:
                expression = write[1].strip()
                if expression in ("__Vcheckval", "vlSymsp->_vm_contextp__", "__Vm_didInit"):
                    if loops:
                        raise ValueError("loop over serializer metadata")
                    rows.append({"kind": "context" if "contextp" in expression else
                                 "signature_write" if expression == "__Vcheckval" else "field",
                                 "name": expression, "loops": []})
                else:
                    match = re.fullmatch(r"(\w+)((?:\[\w+\])*)", expression)
                    if not match:
                        raise ValueError(f"unsupported serializer expression: {expression}")
                    indices = re.findall(r"\[(\w+)\]", match[2])
                    if indices != [name for name, _ in loops]:
                        raise ValueError("serializer indices do not cover loop dimensions in order")
                    rows.append({"kind": "field", "name": match[1],
                                 "loops": [size for _, size in loops]})
                position += write.end()
            else:
                raise ValueError("unaccounted serializer statement: " + tail[:120])
        if nested:
            raise ValueError("unclosed serializer loop")
        return position

    parse(0, [], False)
    if [r["kind"] for r in rows[:3]] != ["signature", "signature_write", "context"]:
        # Symbol tables have only __Vm_didInit, without a per-module signature.
        if rows != [{"kind": "field", "name": "__Vm_didInit", "loops": []}]:
            raise ValueError("unknown serializer metadata layout")
    return rows


def schema(directory):
    result = {"classes": {}, "generated_sha256": {}}
    for path in sorted(directory.glob("*.cpp")):
        original = path.read_text()
        stripped = clean_cpp(original)
        for match in SERIALIZER.finditer(stripped):
            name = match[1]
            if name in result["classes"]:
                raise ValueError(f"duplicate serializer: {name}")
            end = closing(stripped, match.end() - 1)
            writes = serializer_writes(original[match.end():end])
            header = directory / (name + ".h")
            declared, scheduler = declarations(header.read_text())
            fields = {}
            for row in writes:
                if row["kind"] != "field":
                    continue
                field = row["name"]
                if field in fields or field not in declared:
                    raise ValueError(f"duplicate or undeclared serialized field: {name}.{field}")
                spec = declared[field]
                expected = spec["shape"] + ([spec["words"]] if spec["words"] > 1 else [])
                if row["loops"] != expected:
                    raise ValueError(f"incomplete serialized array coverage: {name}.{field}")
                fields[field] = {
                    **spec, "bytes": math.prod(expected) * spec["element_bytes"],
                    "serializer_loops": row["loops"],
                }
            missing = declared.keys() - fields.keys()
            result["classes"][name] = {
                "fields": fields, "writes": writes,
                "unserialized_data": {key: declared[key] for key in sorted(missing)},
                "unserialized_scheduler": scheduler,
            }
            result["generated_sha256"][header.name] = sha256(header)
            result["generated_sha256"][path.name] = sha256(path)
    if not any(name.endswith("___024root") for name in result["classes"]):
        raise ValueError("missing complete RTL root serializer")
    return result


def flat_fields(model):
    return {f"{owner}.{name}": spec for owner, row in model["classes"].items()
            for name, spec in row["fields"].items()}


def scratch_proofs(directory, names):
    """Prove old values dead without assuming function ordering or a scheduler.

    This deliberately does NOT infer dominance from line order across functions,
    conditional stores, a __Vdly prefix, or a zero constructor/reset assignment.
    """
    wanted = {name.split(".", 1)[1]: name for name in names}
    uses = {name: [] for name in names}
    for path in sorted(directory.glob("*.cpp")):
        text = clean_cpp(path.read_text())
        for match in FUNCTION.finditer(text):
            if "___ctor_var_reset" in match[1]:
                continue
            end = closing(text, match.end() - 1)
            body = text[match.end():end]
            first = {}
            depth = 0
            cursor = 0
            for use in REFERENCE.finditer(body):
                depth += body[cursor:use.start()].count("{") - body[cursor:use.start()].count("}")
                cursor = use.start()
                field = use[1]
                if field not in wanted or field in first:
                    continue
                first[field] = True
                suffix = body[use.end():]
                assignment = re.match(r"\s*=(?!=)([^;]*);", suffix)
                # Calls, array selections and address escapes cannot establish
                # a complete, side-effect-free scalar definition.
                prior = body[:use.start()].rstrip()
                at_statement_start = not prior or prior[-1] in ";}"
                safe = bool(depth == 0 and at_statement_start and assignment and
                            not REFERENCE.search(assignment[1]) and
                            not re.search(r"[(){}\[\]&*]|\b(?:new|throw|return)\b", assignment[1]))
                if assignment and depth == 0 and at_statement_start:
                    # A copy from another field is also safe, unless it reads
                    # this field, calls a helper, or lets its address escape.
                    rhs = REFERENCE.sub("source_value", assignment[1])
                    safe = (not any(ref[1] == field for ref in REFERENCE.finditer(assignment[1]))
                            and not re.search(r"[(){}\[\]&*]|\b(?:new|throw|return)\b", rhs))
                uses[wanted[field]].append({
                    "file": path.name, "function": match[1],
                    "line": text.count("\n", 0, match.end() + use.start()) + 1,
                    "unconditional_scalar_definition": safe,
                })
    return {
        name: {"rule": "whole-scalar-definition-before-first-access-in-every-function",
               "uses": rows, "proven": bool(rows) and all(
                   row["unconditional_scalar_definition"] for row in rows)}
        for name, rows in uses.items()
    }


def accounting(left, right, left_directory, right_directory):
    """Account for the union. Unproved layout differences cannot be compared."""
    a, b = flat_fields(left), flat_fields(right)
    rows = {}
    backend_only = {"baseline": sorted(a.keys() - b.keys()),
                    "candidate": sorted(b.keys() - a.keys())}
    proofs = {
        "baseline": scratch_proofs(left_directory, backend_only["baseline"]),
        "candidate": scratch_proofs(right_directory, backend_only["candidate"]),
    }
    for name in sorted(a.keys() | b.keys()):
        if name in a and name in b:
            if a[name] != b[name]:
                raise ValueError(f"logical width/array/storage mismatch: {name}")
            rows[name] = {"disposition": "compare_exact", "baseline": name, "candidate": name}
        else:
            owner = "baseline" if name in a else "candidate"
            proof = proofs[owner][name]
            spec = a.get(name, b.get(name))
            proven = proof["proven"] and not spec["shape"] and spec["words"] == 1
            rows[name] = {
                "disposition": "dead_entry_value" if proven else "unresolved",
                "backend": owner, "proof": proof,
            }
    unsaved = {}
    for owner, model in (("baseline", left), ("candidate", right)):
        for cls, row in model["classes"].items():
            for kind in ("unserialized_data", "unserialized_scheduler"):
                for name, spec in row[kind].items():
                    unsaved[f"{owner}:{cls}.{name}"] = {"kind": kind, "type": spec,
                                                       "disposition": "unresolved"}
    return {
        "schema": 1, "fields": rows, "backend_only": backend_only, "unserialized": unsaved,
        "baseline": left, "candidate": right,
        "complete": not unsaved and all(row["disposition"] != "unresolved"
                                       for row in rows.values()),
        "sampling_boundary": (
            "After the last synchronous eval() returns and its native task join finishes; "
            "no extra eval, reset, PRNG draw, observer or scoreboard operation is inserted. "
            "Externally updated R/B valid inputs remain exactly as in the original host snapshot."),
    }


def validate_accounting(plan):
    a, b = flat_fields(plan["baseline"]), flat_fields(plan["candidate"])
    if set(plan["fields"]) != a.keys() | b.keys():
        raise ValueError("logical accounting omitted or introduced state")
    if plan["unserialized"]:
        raise ValueError("unserialized generated state lacks a settled-boundary proof")
    for name, row in plan["fields"].items():
        if name in a and name in b:
            if row != {"disposition": "compare_exact", "baseline": name, "candidate": name}:
                raise ValueError("incorrect logical field mapping: " + name)
            if a[name] != b[name]:
                raise ValueError("field shape/width mismatch: " + name)
        else:
            owner = "baseline" if name in a else "candidate"
            spec = a.get(name, b.get(name))
            proof = row.get("proof", {})
            if row.get("disposition") != "dead_entry_value" or row.get("backend") != owner or (
                    not proof.get("proven") or not proof.get("uses") or
                    proof.get("rule") != "whole-scalar-definition-before-first-access-in-every-function"
                    or not all(use["unconditional_scalar_definition"] for use in proof["uses"])
                    or spec["shape"] or spec["words"] != 1):
                raise ValueError("unproved backend-only state: " + name)
    if not plan["complete"]:
        raise ValueError("logical comparison preflight is incomplete")


def read_fields(path, expected):
    """A tagged capture includes every storage byte, including unused high bits."""
    fields = {}
    with path.open("rb") as stream:
        if stream.read(len(MAGIC)) != MAGIC:
            raise ValueError("invalid logical-state capture")
        while True:
            size = stream.read(4)
            if not size:
                break
            if len(size) != 4:
                raise ValueError("truncated logical-state name length")
            length = struct.unpack("<I", size)[0]
            if not 0 < length <= 4096:
                raise ValueError("invalid logical-state name length")
            name_bytes = stream.read(length)
            if len(name_bytes) != length:
                raise ValueError("truncated logical-state name")
            name = name_bytes.decode("ascii")
            size = stream.read(8)
            if len(size) != 8 or name not in expected or name in fields:
                raise ValueError("unknown, duplicate or truncated logical-state field: " + name)
            count = struct.unpack("<Q", size)[0]
            if count != expected[name]["bytes"]:
                raise ValueError("logical-state field size mismatch: " + name)
            value = stream.read(count)
            if len(value) != count:
                raise ValueError("truncated logical-state field: " + name)
            fields[name] = value
    if fields.keys() != expected.keys():
        raise ValueError("logical-state capture omitted fields")
    return fields


def compare_fields(plan, left, right):
    validate_accounting(plan)
    a, b = flat_fields(plan["baseline"]), flat_fields(plan["candidate"])
    if left.keys() != a.keys() or right.keys() != b.keys():
        raise ValueError("logical-state comparison omitted fields")
    for values, expected in ((left, a), (right, b)):
        if any(len(values[name]) != spec["bytes"] for name, spec in expected.items()):
            raise ValueError("logical-state comparison has incorrect field extents")
    compared = 0
    for name, row in plan["fields"].items():
        if row["disposition"] == "compare_exact":
            if left[name] != right[name]:
                raise ValueError("logical RTL state mismatch: " + name)
            compared += len(left[name])
    return {"exact_fields": sum(row["disposition"] == "compare_exact"
                               for row in plan["fields"].values()),
            "exact_storage_bytes": compared,
            "accounted_fields": len(plan["fields"]),
            "dead_entry_fields": sum(row["disposition"] == "dead_entry_value"
                                     for row in plan["fields"].values())}


def equivalent(plan, left, right, left_folder, right_folder):
    """The native path only: the existing same-layout raw comparator is unchanged."""
    for key in ("host.bin", "ram.bin", "context.bin"):
        if left["final_state"][key] != right["final_state"][key]:
            raise ValueError(f"equal-work exact state mismatch: {key}")
    if left["final_state"]["ram.bin"]["bytes"] != 128 * 1024 * 1024:
        raise ValueError("equal-work RAM capture is not the complete 128 MiB")
    if left["uart_sha256"] != right["uart_sha256"]:
        raise ValueError("equal-work UART mismatch")
    if left["observed"].keys() != right["observed"].keys():
        raise ValueError("equal-work observation field set mismatch")
    for key in left["observed"]:
        if key != "profile" and left["observed"][key] != right["observed"][key]:
            raise ValueError("equal-work observation mismatch: " + key)
    return compare_fields(
        plan,
        read_fields(left_folder / "logical-state.bin", flat_fields(plan["baseline"])),
        read_fields(right_folder / "logical-state.bin", flat_fields(plan["candidate"])))


def write_exporter(directory, model):
    """Generate an extra read-only capture; never change Verilator's serializers."""
    classes = model["classes"]
    root = next(name for name in classes if name.endswith("___024root"))
    syms = root.removesuffix("___024root") + "__Syms"
    lines = [
        '#include "' + syms + '.h"',
        '#include "' + root + '.h"',
        "#include <fstream>", "#include <stdexcept>",
        "inline void furnace_logical_capture(const std::string &path, "
        "Vfurnace_x4_top &dut) {",
        "    std::ofstream out(path, std::ios::binary);",
        '    if (!out) throw std::runtime_error("logical capture open failed");',
        '    out << "FURNACE-LOGICAL-STATE-1\\n";',
        "    auto field = [&](const char *name, const void *value, uint64_t bytes) {",
        "        uint32_t length = std::char_traits<char>::length(name);",
        "        for (unsigned i = 0; i < 4; ++i) out.put((length >> (8 * i)) & 255);",
        "        out.write(name, length);",
        "        for (unsigned i = 0; i < 8; ++i) out.put((bytes >> (8 * i)) & 255);",
        "        out.write(static_cast<const char *>(value), bytes);",
        "    };",
    ]
    for cls, row in classes.items():
        if cls == root:
            prefix = "dut.rootp->"
        elif cls == syms:
            prefix = "dut.rootp->vlSymsp->"
        elif row["fields"]:
            raise ValueError("unrecognized generated module instance: " + cls)
        else:
            continue
        for name, spec in row["fields"].items():
            expression = prefix + name
            lines += [
                f'    static_assert(sizeof({expression}) == {spec["bytes"]}, "field storage layout");',
                f'    field("{cls}.{name}", &{expression}, sizeof({expression}));',
            ]
    lines += ['    out.close();', '    if (!out) throw std::runtime_error("logical capture write failed");', "}"]
    (directory / "boot_logical_capture.h").write_text("\n".join(lines) + "\n")
    (directory / "logical-schema.json").write_text(json.dumps(model, indent=2) + "\n")
