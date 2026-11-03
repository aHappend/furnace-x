#!/usr/bin/env python3
"""Opt-in scalar replacement in disposable, callback-free ico functions.

Keep the original statement order and scalar storage types. Model scalars become
function-local values, with written fields committed before returning. No array
storage, expressions, scheduler calls or RTL sources are rewritten.
"""

from collections import Counter
import re


FUNCTION = re.compile(
    r"VL_INLINE_OPT void (\w+___ico_sequent__TOP__[012])"
    r"\(Vfurnace_x4_top___024root\* vlSelf\) \{(.*?)\n\}", re.S)
FIELD = re.compile(r"\bvlSelf->(\w+)")
PURE_CALLS = {
    "if", "VL_ADD_W", "VL_GTE_W", "VL_LT_W", "VL_SHIFTL_III",
    "VL_SHIFTL_WWI", "VL_ASSIGNSEL_WW", "VL_GTES_IQQ", "VL_LTES_III",
    "VL_LTS_IQQ", "VL_SHIFTRS_III", "VL_SHIFTRS_QQI", "VL_SHIFTR_III",
    "VL_SHIFTR_WWI", "VL_CONCAT_WWW",
}


def scalar_fields(header):
    fields = {name: kind for kind, name in re.findall(
        r"^\s*(CData|SData|IData|QData)/\*\d+:\d+\*/\s+(\w+);",
        header, re.MULTILINE)}
    for kind, name in re.findall(
            r"^\s*VL_(?:IN|OUT|INOUT)(8|16|64)?\((\w+),\d+,\d+\);",
            header, re.MULTILINE):
        fields[name] = {"8": "CData", "16": "SData", "": "IData", "64": "QData"}[kind]
    return fields


def transform(text, header):
    types = scalar_fields(header)
    rows = []

    def replace(match):
        if "// Body\n" not in match[2]:
            raise ValueError(f"missing generated body: {match[1]}")
        init, code = match[2].split("// Body\n", 1)
        calls = set(re.findall(r"\b(\w+)\s*\(", code))
        if calls - PURE_CALLS or re.search(
                r"\b(?:vlSymsp|return|goto|while|for|throw|static|new|delete|"
                r"reinterpret_cast|const_cast|volatile|asm)\b", code):
            raise ValueError(f"unrecognized ico side effect: {match[1]}")
        if re.search(r"\bvlSelf\b(?!->)", code):
            raise ValueError(f"escaping ico model pointer: {match[1]}")
        if "++" in code or "--" in code or re.search(r"(?<![=<>!])[-+*/%&|^]=", code):
            raise ValueError(f"unrecognized ico update operator: {match[1]}")
        for ampersand in re.finditer(r"(?<!&)&(?!&)", code):
            preceding = code[:ampersand.start()].rstrip()
            if not re.search(r"[\w)\]]$", preceding) or re.search(
                    r"\(\s*(?:CData|SData|IData|QData|\w+\s*\*)\s*\)$", preceding):
                raise ValueError(f"ico address-taking operation: {match[1]}")
        counts = Counter(FIELD.findall(code))
        written = set(re.findall(r"\bvlSelf->(\w+)\s*=(?!=)", code))
        selected = sorted(name for name, count in counts.items()
                          if name in types and (count > 1 or name in written))
        if not selected:
            raise ValueError(f"no scalar fields in profiled ico function: {match[1]}")
        names = {name: f"furnace_scalar_{index}" for index, name in enumerate(selected)}
        if any(name in text for name in names.values()):
            raise ValueError("scalar replacement name collision")
        for field in selected:
            if re.search(rf"\bvlSelf->{field}\s*(?:\[|\.|->)", code):
                raise ValueError(f"non-value scalar use: {field}")
        loads = "".join(f"    {types[name]} {names[name]} = vlSelf->{name};\n"
                        for name in selected)
        stores = "".join(f"    vlSelf->{name} = {names[name]};\n"
                         for name in selected if name in written)
        changed = FIELD.sub(lambda ref: names.get(ref[1], ref[0]), code)
        rows.append({
            "function": match[1], "body_bytes": len(code),
            "scalar_fields": {name: types[name] for name in selected},
            "written_fields": sorted(written.intersection(selected)),
            "replaced_references": sum(counts[name] for name in selected),
        })
        return (f"VL_INLINE_OPT void {match[1]}(Vfurnace_x4_top___024root* vlSelf) {{"
                + init + "// Body\n" + loads + changed + "\n" + stores + "\n}")

    return FUNCTION.sub(replace, text), rows


def optimize(directory, digest):
    header = (directory / "Vfurnace_x4_top___024root.h").read_text()
    changes = []
    for path in sorted(directory.glob("Vfurnace_x4_top*DepSet*.cpp")):
        original = path.read_text()
        changed, rows = transform(original, header)
        if rows:
            changes.append((path, original, changed, rows))
    if sum(len(item[3]) for item in changes) != 3:
        raise ValueError("expected exactly the three profiled ico functions")
    records = []
    for path, original, changed, rows in changes:
        before = digest(path)
        snapshot = path.with_suffix(".scalar-original")
        with snapshot.open("x") as stream:
            stream.write(original)
        path.write_text(changed)
        records.append({
            "file": path.name, "before_sha256": before,
            "after_sha256": digest(path), "original": snapshot.name, "functions": rows,
        })
    return records
