#!/usr/bin/env python3
"""Source-bound noninterference proof for disposable evaluator memoization.

This is backend accounting, not an RTL oracle. Cache bytes need not equal across
backends: an exact fixed-point test must make every reachable cache state
observationally equivalent to executing the original generated function.
"""

import hashlib
import re


RULE = "closed-pure-evaluator-fixed-point-induction-v1"
CACHE_SHA256 = "1048d0ef8d2686f1e666330d6e499952789f248bb501e2ecd289e86cf292543e"
MEMBERS = {
    "owner": "rebind on owner change before any lookup",
    "fixed": "true only after F(snapshot) equals snapshot over the complete field set",
    "bytes": "complete pre-evaluation snapshot, compared byte-for-byte before reuse",
    "ranges": "complete field addresses/extents; sorted and coalesced only when contiguous",
    "calls": "unsigned diagnostic counter, never an evaluator input",
    "hits": "unsigned diagnostic counter, never an evaluator input",
}
PREFIX = (
    "    static thread_local furnace_generated::FixedPointCache cache;\n"
    "    if (cache.owner != vlSelf) {\n"
    "        const furnace_generated::Field fields[] = {\n"
)
SUFFIX = (
    "\n        };\n"
    "        cache.bind(vlSelf, fields);\n"
    "    }\n"
    "    if (cache.reuse()) return;\n"
)
TAIL = "\n    cache.fixed = cache.matches();"
INCLUDE = '#include "generated_eval_cache.h"\n'


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def project(text, constants=None):
    """Invert only the exact admitted wrapper; retain the complete original F."""
    from boot_logical_state import clean_cpp
    from generated_eval import FUNCTION, PURE_CALLS, transform

    constants = {} if constants is None else constants
    records = []

    def replace(match):
        body = match[2]
        if "furnace_generated::" not in body and "cache." not in body:
            return match[0]
        if body.count("// Body\n") != 1:
            raise ValueError("fixed-point evaluator has no unique body")
        init, code = body.split("// Body\n")
        if not code.startswith(PREFIX) or SUFFIX not in code or not code.endswith(TAIL):
            raise ValueError("unrecognized fixed-point wrapper")
        fields_text, computation = code[len(PREFIX):-len(TAIL)].split(SUFFIX, 1)
        fields = re.findall(r"        \{&vlSelf->(\w+), sizeof\(vlSelf->\1\)\},", fields_text)
        if fields_text != "\n".join(
                f"        {{&vlSelf->{name}, sizeof(vlSelf->{name})}}," for name in fields):
            raise ValueError("fixed-point range address/extent changed")
        pure = clean_cpp(computation)
        referenced = sorted(set(re.findall(r"\bvlSelf->(\w+)", pure)))
        if not fields or fields != referenced:
            raise ValueError("fixed-point cache omits, duplicates or introduces evaluator fields")
        calls = set(re.findall(r"\b(\w+)\s*\(", pure))
        if calls - PURE_CALLS or re.search(
                r"\b(?:vlSymsp|return|goto|while|for|throw|static|new|delete)\b", pure):
            raise ValueError("fixed-point evaluator has an unknown side effect")
        if re.search(r"\bvlSelf\b(?!->)", pure):
            raise ValueError("fixed-point evaluator model pointer escapes")
        # A local declaration is not persistent state. Unknown external symbols
        # (even call-free ones) would invalidate deterministic F(snapshot).
        local_init = clean_cpp(init)
        local_init = re.sub(r"\bif\s*\(false\s*&&\s*vlSelf\)\s*\{\s*\}", "", local_init)
        local_init = re.sub(
            r"\bV\w+__Syms\*\s+const\s+__restrict\s+vlSymsp\s+VL_ATTR_UNUSED\s*"
            r"=\s*vlSelf->vlSymsp\s*;", "", local_init)
        local_init = re.sub(r"\bVL_DEBUG_IF\s*\(\s*VL_DBG_MSGF\s*\(\s*\)\s*;\s*\);",
                            "", local_init)
        local_names = set(re.findall(
            r"\b(?:CData|SData|IData|QData|VlWide<\d+>)\s+(\w+)", local_init))
        allowed_init = re.compile(
            r"\s*(?:(?:CData|SData|IData|QData|VlWide<\d+>)\s+\w+\s*;"
            r"|\w+\s*=\s*(?:0|0U)\s*;"
            r"|VL_ZERO_W\(\d+,\s*\w+\)\s*;)")
        if allowed_init.sub("", local_init).strip():
            raise ValueError("fixed-point evaluator has a nonlocal or nonconstant initializer")
        symbols = set(re.findall(r"\b[A-Za-z_]\w*\b",
                                 re.sub(r"\bvlSelf->\w+", "", pure)))
        unknown = symbols - local_names - PURE_CALLS - {
            "else", "CData", "SData", "IData", "QData", "VlWide"}
        if unknown - constants.keys():
            raise ValueError("fixed-point evaluator has external mutable inputs: " +
                             ", ".join(sorted(unknown - constants.keys())))
        # All persistent references must use model members or literal constants.
        original = (f"VL_INLINE_OPT void {match[1]}(Vfurnace_x4_top___024root* vlSelf) {{"
                    + init + "// Body\n" + computation + "\n}")
        records.append({
            "function": match[1], "fields": fields, "original_sha256": digest(original),
            "transformed_sha256": digest(match[0]),
            "constants": {name: constants[name] for name in sorted(unknown)},
        })
        return original

    original = FUNCTION.sub(replace, text)
    if records:
        if not original.startswith(INCLUDE) or original.count(INCLUDE) != 1:
            raise ValueError("fixed-point cache header is missing or multiply included")
        original = original[len(INCLUDE):]
        if "furnace_generated" in original or re.search(r"\bcache\s*[.]", original):
            raise ValueError("fixed-point cache escapes the exact function-local wrapper")
        regenerated, _ = transform(original)
        if regenerated != text:
            raise ValueError("fixed-point transformation does not round-trip exactly")
    elif "furnace_generated" in text or "FixedPointCache" in text or INCLUDE in text:
        raise ValueError("unclassified fixed-point cache use")
    return original, records


def audited_sources(directory):
    """Return read-only projections and an inventory of every backend cache."""
    from boot_logical_state import clean_cpp

    paths = sorted(directory.glob("*.cpp"))
    constants = {}
    for path in paths:
        text = clean_cpp(path.read_text())
        for match in re.finditer(
                r"extern const VlWide<(\d+)>\s+(V\w+__ConstPool__\w+)\s*"
                r"=\s*\{\{([^{}]+)\}\};", text):
            words = re.findall(r"(?:0x[0-9a-fA-F]+|[0-9]+)U?", match[3])
            if len(words) != int(match[1]) or re.sub(
                    r"(?:0x[0-9a-fA-F]+|[0-9]+)U?|[\s,]", "", match[3]):
                raise ValueError("unclassified fixed-point constant initializer")
            if match[2] in constants:
                raise ValueError("multiply defined fixed-point constant")
            constants[match[2]] = {"file": path.name, "definition_sha256": digest(match[0])}
    projections, records = {}, {}
    for path in paths:
        original, functions = project(path.read_text(), constants)
        projections[path.name] = original
        if functions:
            records[path.name] = {
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "projected_sha256": digest(original), "functions": functions,
            }
    if not records:
        return projections, None
    header = directory / "generated_eval_cache.h"
    if not header.is_file() or hashlib.sha256(header.read_bytes()).hexdigest() != CACHE_SHA256:
        raise ValueError("fixed-point cache implementation differs from the audited source")
    proof = {
        "rule": RULE, "cache_sha256": CACHE_SHA256, "sources": records,
        "members": MEMBERS,
        "invariant": [
            "Default/rebound cache has fixed=false and cannot skip F.",
            "A miss saves all fields before F; fixed is set by exact post-F byte comparison.",
            "Thus fixed implies F(saved_bytes)=saved_bytes for closed deterministic F.",
            "A hit additionally proves current_bytes=saved_bytes, so skipping F changes no field.",
            "Other schedules may modify fields; exact comparison rejects every changed byte.",
            "Ranges never write model data; counters and destruction only emit diagnostics.",
        ],
        "pointer_scope": "Function-local TLS cache, exact non-escaping wrapper, live model fields only.",
    }
    return projections, proof


def validate(plan):
    """Require the same source-bound projection on every affected lifetime."""
    from boot_scheduler import validate_runtime

    for owner in ("baseline", "candidate"):
        expected = plan[owner].get("evaluation_cache")
        if plan.get("evaluation_caches", {}).get(owner) != expected:
            raise ValueError("fixed-point cache accounting omitted or changed")
        if expected is None:
            continue
        if expected.get("rule") != RULE or expected.get("cache_sha256") != CACHE_SHA256 or (
                expected.get("members") != MEMBERS or len(expected.get("invariant", [])) != 6 or
                not expected.get("sources")):
            raise ValueError("unproved fixed-point cache state")
        runtime = plan.get("evaluation_cache_runtime")
        validate_runtime(runtime)
        for name, row in expected["sources"].items():
            if row["source_sha256"] != plan[owner]["generated_sha256"].get(name):
                raise ValueError("fixed-point source identity changed")
        for row in plan["fields"].values():
            if row.get("backend") == owner and row.get("disposition") == "dead_entry_value":
                proof = row.get("proof", {})
                if proof.get("rule") == "structured-interprocedural-entry-value-deadness-v1" and (
                        proof.get("evaluation_cache") != expected):
                    raise ValueError("lifetime lacks complete fixed-point cache accounting")


def compiled_fixture(output, receipt):
    """Compare the real cache against direct evaluation; reject semantic mutants."""
    from boot_probe import ROOT, digest as file_digest, run, save

    original = (ROOT / "tests/generated_eval_cache.h").read_text()
    mutations = {
        "original": original,
        "stale-input": original.replace("fixed && matches()", "fixed"),
        "last-byte": original.replace(
            "std::memcmp(bytes.data() + offset, field.address, field.size)",
            "std::memcmp(bytes.data() + offset, field.address, field.size - 1)"),
        "owner": original.replace("if (owner != instance)", "if (owner == nullptr)"),
    }
    if len(set(mutations.values())) != len(mutations):
        raise ValueError("cache semantic mutant was not applied")
    for name, header in mutations.items():
        directory = output / ("cache-fixture-" + name)
        directory.mkdir()
        (directory / "generated_eval_cache.h").write_text(header)
        source = directory / "fixture.cpp"
        source.write_bytes((ROOT / "tests/generated_eval_cache_test.cpp").read_bytes())
        relative = directory.relative_to(ROOT)
        run(["g++", "-std=c++17", "-O2", relative / "fixture.cpp",
             "-o", relative / "fixture"], output, "cache-" + name + "-compile", receipt)
        result = run([relative / "fixture"], output, "cache-" + name + "-execute",
                     receipt, check=False)
        stdout, stderr = ((output / result[key]).read_text() for key in ("stdout", "stderr"))
        if name == "original":
            if result["exit_code"] != 0 or not re.search(
                    r"CACHE compared=8192 hits=[1-9]\d* misses=[1-9]\d* nonfixed=4096", stdout):
                raise ValueError("cache direct-evaluation fixture failed")
        elif result["exit_code"] != 1 or "CACHE_SEMANTIC_MISMATCH" not in stderr:
            raise ValueError("cache mutant did not fail its intended semantic comparison: " + name)
        receipt.setdefault("cache_semantic_fixtures", {})[name] = {
            "header_sha256": file_digest(directory / "generated_eval_cache.h"),
            "source_sha256": file_digest(source),
            "executable_sha256": file_digest(directory / "fixture"),
            "exit_code": result["exit_code"], "semantic_rejection": name != "original",
        }
        save(output, receipt)
