"""Preserved public X1/X2 ABI and exact frozen X3 physical port shape."""

import hashlib
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def header(path, module):
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(), flags=re.S)
    match = re.search(rf"\bmodule\s+{module}\b(.*?)\);", code, re.S)
    if not match:
        raise AssertionError(f"public module header missing: {path.name}")
    return match[1]


def ports(text):
    start = re.search(r"\b(?:input|output|inout)\b", text)
    if not start:
        raise AssertionError("ANSI ports absent")
    result, declaration = {}, None
    for token in text[start.start():].strip().rstrip(")").split(","):
        token = token.strip()
        match = re.fullmatch(r"(?:(input|output|inout)\s+)?(.*?)\b([A-Za-z_]\w*)", token)
        if not match:
            raise AssertionError(f"unrecognized public port: {token}")
        direction, qualifiers, name = match.groups()
        if direction:
            declaration = (direction, bool(re.search(r"\bsigned\b", qualifiers)),
                           tuple(re.findall(r"\[([^\]]+)\]", qualifiers)))
        elif qualifiers or declaration is None:
            raise AssertionError(f"unrecognized inherited declaration: {token}")
        if name in result:
            raise AssertionError(f"duplicate public port: {name}")
        result[name] = declaration
    return result


def main():
    experiment = Experiment("parent-and-x3-interface-compatibility")
    try:
        inventory = {}
        parent = ROOT / "furnace_x2_reference" / "rtl"
        files = sorted(parent.glob("*.sv"))
        if len(files) != 26:
            raise AssertionError("the supplied 26-module parent provenance is incomplete")
        for source in files:
            delivered = ROOT / "rtl" / source.name
            if not delivered.is_file():
                raise AssertionError(f"missing shipped parent module: {source.name}")
            inventory[source.name] = {
                "parent_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "delivered_sha256": hashlib.sha256(delivered.read_bytes()).hexdigest()}
        for module in ("furnace_x1_top", "furnace_x2_top"):
            original = header(parent / f"{module}.sv", module)
            delivered = header(ROOT / "rtl" / f"{module}.sv", module)
            if re.sub(r"\s+", "", original) != re.sub(r"\s+", "", delivered):
                raise AssertionError(f"changed preserved public parameter/port ABI: {module}")
        expected = ports(header(parent / "furnace_x2_top.sv", "furnace_x2_top"))
        for name, (direction, signed, dimensions) in list(expected.items()):
            if name.startswith("m_axi_"):
                if not dimensions or dimensions[0] != "3:0":
                    raise AssertionError(f"unexpected parent memory shape: {name}")
                dimensions = dimensions[1:]
                if name in ("m_axi_wdata", "m_axi_rdata"):
                    dimensions = ("511:0",)
                elif name == "m_axi_wstrb":
                    dimensions = ("63:0",)
                expected[name] = (direction, signed, dimensions)
        actual = ports(header(ROOT / "rtl" / "furnace_x3_top.sv", "furnace_x3_top"))
        if expected != actual:
            differences = {name: {"expected": expected.get(name), "actual": actual.get(name)}
                           for name in sorted(expected.keys() | actual.keys())
                           if expected.get(name) != actual.get(name)}
            raise AssertionError(f"frozen X3 public port mismatch: {differences}")
        (experiment.path / "interfaces.json").write_text(json.dumps({
            "parent_sources": inventory, "x3_ports": actual}, indent=2) + "\n")
        print(f"INTERFACE_COMPATIBILITY_PASS parent_modules={len(files)} x3_ports={len(actual)}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
