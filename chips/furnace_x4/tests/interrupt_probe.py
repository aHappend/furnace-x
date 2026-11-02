#!/usr/bin/env python3
"""Independent public-source IRQ positions; leaf coverage, not PLIC integration."""

import argparse
import datetime
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"interrupt-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    names = ("tests/interrupt_probe.py", "tests/interrupt_contract.sv",
             "tests/boot_probe.py", "rtl/furnace_interrupt_aggregator.sv")
    receipt = {
        "schema": 1, "argv": ["python3", "tests/interrupt_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {name: digest(ROOT/name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "measurements": {}, "runs": [],
        "scope": "leaf public-source IRQ set/mask/W1C/stall comparisons",
    }
    save(output, receipt)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        for tool, option in (("iverilog", "-V"), ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        rtl = ["rtl/furnace_interrupt_aggregator.sv", "tests/interrupt_contract.sv"]
        run(["iverilog", "-g2012", "-Wall", "-s", "interrupt_contract", "-o",
             relative/"interrupt.vvp", *rtl], output, "icarus-compile", receipt)
        run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
             "--top-module", "interrupt_contract", "--Mdir", relative/"obj", *rtl],
            output, "verilator-compile", receipt)
        for simulator, seed in (("icarus", 17),
                                *(("verilator", s) for s in (17, 89, 211))):
            command = (["vvp", relative/"interrupt.vvp"] if simulator == "icarus" else
                       [relative/"obj/Vinterrupt_contract"])
            stem = f"{simulator}-{seed}"
            run([*command, f"+seed={seed}"], output, stem, receipt)
            match = re.search(
                r"INTERRUPT_CONTRACT seed=(\d+) positions=(\d+) simultaneous=(\d+) "
                r"comparisons=(\d+) stalls=(\d+) failures=(\d+)",
                (output/f"{stem}.stdout.txt").read_text(),
            )
            if not match:
                raise ValueError(f"{stem}: missing IRQ comparison summary")
            observed_seed, positions, simultaneous, comparisons, stalls, failures = map(int, match.groups())
            if (observed_seed != seed or positions != 16 or simultaneous != 16 or
                    comparisons < 100 or stalls == 0 or failures):
                raise ValueError(f"{stem}: IRQ coverage assertion failed")
            receipt["runs"].append({
                "scope": "leaf", "simulator": simulator, "seed": seed,
                "positions": positions, "simultaneous": simultaneous,
                "comparisons": comparisons, "stalls": stalls,
            })
            if simulator == "verilator":
                receipt["measurements"][f"seed{seed}.irq_source_positions"] = positions
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        obj = output/"obj"
        if obj.is_dir():
            for path in obj.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Interrupt receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
