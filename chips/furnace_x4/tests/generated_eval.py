#!/usr/bin/env python3
"""Exact fixed-point reuse for large, side-effect-free generated AES schedules.

This changes disposable C++ only. A call may be reused only when its previous
complete read/write field set was a fixed point and those bytes remain identical.
Sequential updates, changed inputs and externally changed outputs force evaluation.
"""

import re
from pathlib import Path


FUNCTION = re.compile(
    r"VL_INLINE_OPT void (\w+___nba_sequent__TOP__\d+)"
    r"\(Vfurnace_x4_top___024root\* vlSelf\) \{(.*?)\n\}", re.S)
PURE_CALLS = {
    "if", "VL_ASSIGNSEL_WI", "VL_SHIFTL_III", "VL_SHIFTR_III",
    "VL_SHIFTR_WWI", "VL_XOR_W",
}


def transform(text):
    rows = []

    def replace(match):
        body = match[2]
        if "// Body\n" not in body:
            return match[0]
        init, code = body.split("// Body\n", 1)
        if len(code) < 500000 or "aes__DOT__" not in code:
            return match[0]
        fields = sorted(set(re.findall(r"vlSelf->(\w+)", code)))
        calls = set(re.findall(r"\b(\w+)\s*\(", code))
        # Fail closed on unfamiliar generated code, rather than silently dropping
        # instrumentation or allowing a hidden scheduler/DPI side effect.
        if not fields or calls - PURE_CALLS or re.search(
                r"\b(?:vlSymsp|return|goto|while|for|throw|static|new|delete)\b", code):
            raise ValueError(f"unrecognized pure evaluation body: {match[1]}")
        if re.search(r"\bvlSelf\b(?!->)", code):
            raise ValueError(f"escaping model pointer: {match[1]}")
        entries = "\n".join(f"        {{&vlSelf->{name}, sizeof(vlSelf->{name})}},"
                            for name in fields)
        before = (
            "    static thread_local furnace_generated::FixedPointCache cache;\n"
            "    if (cache.owner != vlSelf) {\n"
            "        const furnace_generated::Field fields[] = {\n"
            + entries + "\n        };\n"
            "        cache.bind(vlSelf, fields);\n"
            "    }\n"
            "    if (cache.reuse()) return;\n"
        )
        after = "\n    cache.fixed = cache.matches();"
        rows.append({"function": match[1], "fields": fields, "body_bytes": len(code)})
        return (f"VL_INLINE_OPT void {match[1]}(Vfurnace_x4_top___024root* vlSelf) {{"
                + init + "// Body\n" + before + code + after + "\n}")

    changed = FUNCTION.sub(replace, text)
    if rows:
        changed = '#include "generated_eval_cache.h"\n' + changed
    return changed, rows


def optimize(directory, digest):
    records = []
    (directory / "generated_eval_cache.h").write_bytes(
        Path(__file__).with_name("generated_eval_cache.h").read_bytes())
    for path in sorted(directory.glob("Vfurnace_x4_top*DepSet*.cpp")):
        text = path.read_text()
        changed, rows = transform(text)
        if not rows:
            continue
        before = digest(path)
        path.write_text(changed)
        records.append({
            "file": path.name, "before_sha256": before, "after_sha256": digest(path),
            "functions": rows,
        })
    if sum(len(row["functions"]) for row in records) != 3:
        raise ValueError("expected exactly three dominant pure generated AES schedules")
    return records
