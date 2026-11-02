#!/usr/bin/env python3
"""Bounded public-pin adapter cycle-contract diagnostic on both simulators."""

import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--adapter", choices=("mmio", "cpu"), default="mmio")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"adapter-contract-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    top = "mmio_contract" if args.adapter == "mmio" else "cpu_adapter_contract"
    rtl = "furnace_x4_mmio_bridge" if args.adapter == "mmio" else "furnace_x4_cpu_axi512_bridge"
    sources = [
        f"rtl/{rtl}.sv", f"tests/{top}.sv",
        "tests/adapter_probe.py", "tests/boot_probe.py", "design/SPEC.md",
    ]
    receipt = {
        "schema": 1, "kind": "verifier-adapter-contract-preparation",
        "argv": ["python3", "tests/adapter_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT / name) for name in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": None, "timed_out": False, "commands": [],
        "tool_versions": {}, "simulator_outcomes": {},
        "adapter": args.adapter,
        "scope": "Adapter public-pin directed timing/stall/error comparisons; not full L1.",
    }
    if args.repair_of:
        receipt["repair_of"] = str(args.repair_of)
        receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
    save(output, receipt)
    print(f"Adapter diagnostic: {relative}/receipt.json", flush=True)
    status = 1
    try:
        for tool, option in (("iverilog", "-V"), ("vvp", "-V"),
                             ("verilator", "--version"), ("make", "--version")):
            result = subprocess.run(
                [tool, option], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            receipt["tool_versions"][tool] = {
                "argv": [tool, option], "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            }
            if result.returncode:
                raise RuntimeError(f"{tool} version query failed")
        for simulator in ("icarus", "verilator"):
            try:
                if simulator == "icarus":
                    run(["iverilog", "-g2012", "-Wall", "-s", top,
                         "-o", relative / "adapter.vvp", *sources[:2]],
                        output, "icarus-compile", receipt)
                    run(["vvp", relative / "adapter.vvp"],
                        output, "icarus-simulation", receipt)
                else:
                    run(["verilator", "--binary", "--timing", "--assert",
                         "-Wno-fatal", "--top-module", top,
                         "--Mdir", relative / "obj", *sources[:2]],
                        output, "verilator-compile", receipt)
                    run([relative / f"obj/V{top}"],
                        output, "verilator-simulation", receipt)
                receipt["simulator_outcomes"][simulator] = 0
            except RuntimeError as error:
                receipt["simulator_outcomes"][simulator] = 1
                receipt.setdefault("failures", []).append(str(error))
        status = int(any(receipt["simulator_outcomes"].values()))
    except (OSError, ValueError, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
        obj = output / "obj"
        if obj.is_dir():
            for path in obj.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
    print(f"Adapter diagnostic exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
