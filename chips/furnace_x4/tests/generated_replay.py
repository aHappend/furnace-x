#!/usr/bin/env python3
"""Memoize deterministic statement regions in disposable Verilator C++ only.

The key includes every referenced model field and initialized local variable,
including written fields. A hit restores their exact post-region bytes. This
preserves repeated non-fixed-point mappings as well as local temporaries.
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
            entries = "\n".join(f"        {{&{name}, sizeof({name})}}," for name in fields)
            rendered.append(
                f"\n    static thread_local furnace_replay::Cache replay_{number};\n"
                "    {\n    const furnace_replay::Field fields[] = {\n"
                + entries + "\n    };\n"
                f"    if (!replay_{number}.reuse(vlSelf, fields)) {{\n"
                + chunk + f"\n        replay_{number}.capture();\n    }}\n    }}\n")
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
