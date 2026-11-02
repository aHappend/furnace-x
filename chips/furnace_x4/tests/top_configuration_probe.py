#!/usr/bin/env python3
"""Full integrated top parameter admission and bounded public-pin boot/reset."""

import argparse
import datetime
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


RANGES = {
    "MAX_TILE_BYTES": (1, 4096, 65536), "RING_DEPTH": (1, 3, 16),
    "IN_WIDTH": (1, 8, 64), "IN_HEIGHT": (1, 8, 64),
    "OUT_WIDTH": (1, 8, 64), "OUT_HEIGHT": (1, 8, 64),
    "FFT_N": (8, 16, 32, 64), "FUSION_DEPTH": (1, 3, 16),
    "MAILBOX_DEPTH": (1, 3, 16), "MAX_DMA_BYTES": (1, 1048576),
}
ILLEGAL = {
    "MAX_TILE_BYTES": (0, 65537), "RING_DEPTH": (0, 17),
    "IN_WIDTH": (0, 65), "IN_HEIGHT": (0, 65),
    "OUT_WIDTH": (0, 65), "OUT_HEIGHT": (0, 65),
    "FFT_N": (0, 7, 24, 65), "FUSION_DEPTH": (0, 17),
    "MAILBOX_DEPTH": (0, 17), "MAX_DMA_BYTES": (0, 1048577),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root)/f"top-configuration-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = [p.relative_to(ROOT) for p in sorted((ROOT/"rtl").glob("*.sv"))]
    names = [*rtl, Path("tests/top_configuration_contract.sv"),
             Path("tests/top_configuration_probe.py"), Path("tests/boot_probe.py")]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/top_configuration_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(name): digest(ROOT/name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [],
        "scope": "Full-top legal configurations execute real CPU boot fetch/reset. "
                 "Leaf numerical/queue/geometry suites separately exercise parameter-dependent behavior.",
    }
    if args.repair_of:
        receipt.update(repair_of=str(args.repair_of),
                       repair_receipt_sha256=digest(project_path(args.repair_of)))
    save(output, receipt)
    print(f"Configuration receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        for tool, option in (("python3", "--version"), ("iverilog", "-V"), ("vvp", "-V")):
            run([tool, option], output, f"{tool}-version", receipt)
        legal = [("default", {})]
        # One-dimensional endpoints avoid pretending to cover an enormous Cartesian product.
        for name, values in RANGES.items():
            legal.extend((f"{name}-{value}", {name: value}) for value in values)
        legal += [
            ("minimum-combined", {name: values[0] for name, values in RANGES.items()}),
            ("maximum-combined", {name: values[-1] for name, values in RANGES.items()}),
            ("nonsquare-odd", {"IN_WIDTH": 3, "IN_HEIGHT": 5, "OUT_WIDTH": 7,
                              "OUT_HEIGHT": 2, "RING_DEPTH": 3, "FUSION_DEPTH": 3,
                              "MAILBOX_DEPTH": 3}),
        ]
        rows = [("legal-"+name, values, True) for name, values in legal]
        rows += [(f"illegal-{name}-{value}", {name: value}, False)
                 for name, values in ILLEGAL.items() for value in values]
        for label, configuration, is_legal in rows:
            directory = output/f"{label}-{uuid.uuid4().hex[:8]}"
            directory.mkdir()
            executable = directory.relative_to(ROOT)/"top.vvp"
            run(["iverilog", "-g2012", "-Wall", "-s", "top_configuration_contract",
                 "-o", executable,
                 *[f"-Ptop_configuration_contract.{name}={value}"
                   for name, value in configuration.items()],
                 *rtl, "tests/top_configuration_contract.sv"],
                output, label+"-compile", receipt)
            result = run(["vvp", executable], output, label+"-simulation", receipt,
                         check=is_legal)
            text = (output/result["stdout"]).read_text() + (output/result["stderr"]).read_text()
            row = {"configuration": configuration, "legal": is_legal,
                   "scope": "full top bounded startup", "simulator": "icarus"}
            if is_legal:
                matches = re.findall(r"^TOP_CONFIGURATION (.+)$", text, re.MULTILINE)
                if len(matches) != 1:
                    raise ValueError(f"{label}: missing measured configuration comparisons")
                counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", matches[0])}
                if counts["comparisons"] <= 0 or counts["cycles"] > 500000 or (
                        counts["read_responses"] != 1 or counts["resets"] != 1 or
                        counts["stalled_headers"] != 15):
                    raise ValueError(f"{label}: missing measured startup/reset event")
                row.update(counts)
            elif result["exit_code"] == 0 or result["timed_out"] or "PARAMETER ERROR" not in text:
                raise ValueError(f"{label}: explicit parameter rejection required, not compile failure")
            else:
                row["explicit_parameter_rejection"] = True
            receipt["runs"].append(row)
            save(output, receipt)
        receipt["legal_rows"] = len(legal)
        receipt["illegal_rows"] = sum(len(v) for v in ILLEGAL.values())
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Configuration exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
