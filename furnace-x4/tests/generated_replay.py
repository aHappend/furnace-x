#!/usr/bin/env python3
"""Memoize deterministic statement regions in disposable Verilator C++ only.

The key includes every referenced model field and initialized local variable,
including written fields. Reuse requires a proven model-state fixed point and
restores local post-region bytes. Guards have compile-time field sizes/offsets.
"""

import re
from pathlib import Path


FUNCTION = re.compile(
    r"VL_INLINE_OPT void (\w+___(?:ico|nba)_(?:sequent|comb)__TOP__\d+)"
    r"\(Vfurnace_x4_top___024root\* vlSelf\) \{(.*?)\n\}", re.S)
PURE_CALLS = {
    "if", "IData", "QData", "CData", "SData",
    "VL_ADD_W", "VL_SUB_W", "VL_ASSIGNSEL_WI", "VL_ASSIGNSEL_WW",
    "VL_CONCAT_WWW", "VL_EXTENDS_II", "VL_EXTENDS_QI",
    "VL_GTE_W", "VL_LT_W", "VL_GTES_III", "VL_GTES_IQQ", "VL_GTS_III",
    "VL_GTS_IQQ", "VL_LTES_III", "VL_LTES_IQQ", "VL_LTS_III", "VL_LTS_IQQ",
    "VL_MULS_III", "VL_MULS_QQQ", "VL_REDXOR_32",
    "VL_SHIFTL_III", "VL_SHIFTL_QQI", "VL_SHIFTL_WWI",
    "VL_SHIFTR_III", "VL_SHIFTR_QQI", "VL_SHIFTR_WWI",
    "VL_SHIFTRS_III", "VL_SHIFTRS_QQI", "VL_XOR_W",
}


def statements(code):
    """Split only at complete top-level statements, including an entire if/else."""
    start = depth = parentheses = brackets = 0
    for i, char in enumerate(code):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "(":
            parentheses += 1
        elif char == ")":
            parentheses -= 1
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets -= 1
        if min(depth, parentheses, brackets) < 0:
            raise ValueError("unbalanced generated statement")
        if depth or parentheses or brackets:
            continue
        if char == ";" or (char == "}" and not re.match(r"\s*else\b", code[i + 1:])):
            yield code[start:i + 1]
            start = i + 1
    if depth or parentheses or brackets or code[start:].strip():
        raise ValueError("incomplete generated statement")


def transform(text):
    rows = []

    def replace(match):
        body = match[2]
        if "// Body\n" not in body:
            return match[0]
        init, code = body.split("// Body\n", 1)
        if len(code) < 60000:
            return match[0]
        # Never memoize scheduler state, callbacks, loops, pointer escapes or an
        # unfamiliar operation. Entire model arrays are included, not one index.
        calls = set(re.findall(r"\b(\w+)\s*\(", code))
        if calls - PURE_CALLS or re.search(
                r'\b(?:vlSymsp|return|goto|while|for|throw|static|new|delete)\b|["\'#]|//|/\*',
                code) or re.search(r"\bvlSelf\b(?!->)", code):
            return match[0]
        locals_ = set(re.findall(
            r"\b(?:CData|SData|IData|QData|VlWide<\d+>)\s*(?:/\*.*?\*/)?\s+(\w+)\s*;",
            init))
        # Reject any unknown free identifier rather than assume it is immutable.
        without_fields = re.sub(r"vlSelf->\w+", "", code)
        identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", without_fields))
        constants = set(re.findall(r"extern const .*?\b(\w+);", text))
        if identifiers - locals_ - PURE_CALLS - constants - {"else", "U", "ULL"}:
            return match[0]
        chunks, pending = [], ""
        for statement in statements(code):
            pending += statement
            if len(pending) >= 60000:
                chunks.append(pending)
                pending = ""
        if pending:
            if chunks:
                chunks[-1] += pending
            else:
                chunks.append(pending)
        rendered, records = [], []
        for number, chunk in enumerate(chunks):
            fields = sorted(set(re.findall(r"vlSelf->\w+", chunk)))
            local_fields = sorted(set(re.findall(r"\b[A-Za-z_]\w*\b", chunk)) & locals_)
            fields += local_fields
            if not fields or len(fields) > 256:
                rendered.append(chunk)
                continue
            declarations = "\n".join(
                f"        decltype({name}) field_{index};"
                for index, name in enumerate(fields))
            checks = " &&\n            ".join(
                f"furnace_replay::same(before.field_{index}, {name})"
                for index, name in enumerate(fields))
            model_checks = " &&\n            ".join(
                f"furnace_replay::same(before.field_{index}, {name})"
                for index, name in enumerate(fields) if name.startswith("vlSelf->")) or "true"
            snapshots = "\n".join(
                f"        furnace_replay::copy(before.field_{index}, {name});"
                for index, name in enumerate(fields))
            restore_locals = "\n".join(
                f"        furnace_replay::copy({name}, after.field_{index});"
                for index, name in enumerate(fields) if not name.startswith("vlSelf->"))
            save_locals = "\n".join(
                f"        furnace_replay::copy(after.field_{index}, {name});"
                for index, name in enumerate(fields) if not name.startswith("vlSelf->"))
            rendered.append(
                "\n    {\n    struct Snapshot {\n" + declarations + "\n    };\n"
                "    static thread_local Snapshot before{}, after{};\n"
                "    static thread_local const void* owner = nullptr;\n"
                "    static thread_local bool fixed = false;\n"
                f'    static thread_local furnace_replay::Counter counter("{match[1]}", {number});\n'
                "    const bool consider = counter.consider();\n"
                "    if (consider && fixed && owner == vlSelf &&\n            " + checks + ") {\n"
                "        ++counter.hits;\n        counter.misses = 0;\n" + restore_locals + "\n"
                "    } else {\n        if (consider) {\n        owner = vlSelf;\n"
                + snapshots + "\n        }\n"
                + chunk + "\n        if (consider) {\n        fixed = " + model_checks + ";\n"
                + save_locals + "\n        counter.evaluated(fixed);\n        }\n    }\n    }\n")
            records.append({"region": number, "body_bytes": len(chunk), "fields": fields})
        if not records:
            return match[0]
        rows.append({"function": match[1], "regions": records})
        return (f"VL_INLINE_OPT void {match[1]}(Vfurnace_x4_top___024root* vlSelf) {{"
                + init + "// Body\n" + "".join(rendered) + "\n}")

    changed = FUNCTION.sub(replace, text)
    if rows:
        changed = '#include "generated_replay.h"\n' + changed
    return changed, rows


def optimize(directory, digest):
    (directory / "generated_replay.h").write_bytes(
        Path(__file__).with_name("generated_replay.h").read_bytes())
    records = []
    for path in sorted(directory.glob("Vfurnace_x4_top*DepSet*.cpp")):
        if "Slow" in path.name:
            continue
        changed, rows = transform(path.read_text())
        if rows:
            before = digest(path)
            path.write_text(changed)
            records.append({"file": path.name, "before_sha256": before,
                            "after_sha256": digest(path), "functions": rows})
    if not records:
        raise ValueError("no eligible generated statement regions")
    return records
