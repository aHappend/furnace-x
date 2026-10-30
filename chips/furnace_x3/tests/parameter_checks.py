"""Executable illegal-parameter diagnostics and conservative source invariants."""

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


INVALID = {
    "MAX_TILE_BYTES": (0, 65537), "RING_DEPTH": (0, 17), "FUSION_DEPTH": (0, 17),
    "MAILBOX_DEPTH": (0, 17), "MAX_DMA_BYTES": (0, 1048577),
    "IN_WIDTH": (0, 65), "IN_HEIGHT": (0, 65),
    "OUT_WIDTH": (0, 65), "OUT_HEIGHT": (0, 65),
    "FFT_N": (0, 7, 9, 15, 17, 31, 33, 63, 65),
}


def source_invariants():
    rows = []
    for path in sorted((ROOT / "rtl").glob("*.sv")):
        text = path.read_text()
        code = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', "", text, flags=re.S)
        if "/" in code or "%" in code:
            raise AssertionError(f"division/modulo token: {path.name}")
        for match in re.finditer(r"\balways\s*@\s*\([^)]*(?:posedge|negedge)[^)]*\)\s*begin", code):
            position, depth = match.end(), 1
            for token in re.finditer(r"\bbegin\b|\bend\b", code[position:]):
                depth += 1 if token[0] == "begin" else -1
                if depth == 0:
                    body = code[position:position + token.start()]
                    break
            else:
                raise AssertionError(f"unclosed sequential block: {path.name}")
            body = re.sub(r"\bfor\s*\([^)]*\)", "", body)
            if re.search(r"(?<![=<>!])=(?!=)", body):
                raise AssertionError(f"blocking state assignment in sequential block: {path.name}")
        rows.append({"source": str(path.relative_to(ROOT)), "division_modulo_tokens": 0,
                     "blocking_sequential_state_assignments": 0})
    return rows


def main():
    experiment = Experiment("parameter-diagnostics")
    try:
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        rows = source_invariants()
        (experiment.path / "source-invariants.json").write_text(json.dumps(rows, indent=2) + "\n")
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        diagnostics = []
        for parameter, values in INVALID.items():
            for value in values:
                name = f"{parameter.lower()}-{value}"
                binary = experiment.path / f"{name}.vvp"
                experiment.command(["iverilog", "-g2012", "-Wall", "-s", "furnace_x3_top",
                                    f"-Pfurnace_x3_top.{parameter}={value}",
                                    "-o", str(binary.relative_to(ROOT)), *sources], f"{name}-compile")
                try:
                    experiment.command(["vvp", str(binary.relative_to(ROOT))], f"{name}-reject")
                except RuntimeError:
                    record = experiment.data["commands"][-1]
                    output = (ROOT / record["stdout"]).read_text() + (
                        ROOT / record["stderr"]).read_text()
                    if record["timed_out"] or record["exit"] == 0 or "PARAMETER ERROR" not in output:
                        raise AssertionError(f"wrong parameter rejection: {name}")
                    diagnostics.append({"parameter": parameter, "value": value,
                                        "diagnostic": "PARAMETER ERROR", "execution": record})
                else:
                    raise AssertionError(f"illegal parameter accepted: {name}")
        (experiment.path / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
        print(f"PARAMETERS_PASS executable_rejections={len(diagnostics)} source_files={len(rows)}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
