#!/usr/bin/env python3
"""Compact dual-simulator buffered fabric-fault settlement and reset recovery."""

import argparse
import datetime
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"coherence-fault-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    inputs = ["rtl/furnace_x4_axi_geometry.sv", "rtl/furnace_x4_burst_store.sv",
              "rtl/furnace_x4_coherent_memory.sv", "tests/coherence_fault_contract.sv"]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/coherence_fault_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [],
        "source_sha256": {p: digest(ROOT / p) for p in [
            *inputs, "tests/coherence_fault_probe.py", "tests/boot_probe.py"]},
        "scope": "Public-pin coherent-memory leaf; not full-top cache-failure or Linux acceptance.",
    }
    if args.repair_of:
        receipt.update(repair_of=str(args.repair_of),
                       repair_receipt_sha256=digest(project_path(args.repair_of)))
    save(output, receipt)
    print(f"Coherence fault receipt: {relative}/receipt.json", flush=True)
    status = 1
    obj = relative / f"obj-{uuid.uuid4().hex[:8]}"
    try:
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, tool + "-version", receipt)
        run(["iverilog", "-g2012", "-Wall", "-s", "coherence_fault_contract",
             "-o", relative / "contract.vvp", *inputs], output, "icarus-compile", receipt)
        run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
             "--top-module", "coherence_fault_contract", "--Mdir", obj, *inputs],
            output, "verilator-compile", receipt)
        for simulator, command in (
                ("icarus", ["vvp", relative / "contract.vvp"]),
                ("verilator", [obj / "Vcoherence_fault_contract"])):
            result = run(command, output, simulator + "-simulation", receipt)
            text = (output / result["stdout"]).read_text()
            lines = re.findall(r"^COHERENCE_FAULT (.+)$", text, re.MULTILINE)
            if len(lines) != 1:
                raise ValueError("missing actual buffered-fault comparison summary")
            measured = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", lines[0])}
            if any(measured[name] != value for name, value in {
                    "fault_cases": 6, "cancel_cases": 1, "cpu_recoveries": 7,
                    "fabric_recoveries": 11, "ordinary_errors": 4,
                    "accepted_aw": 11, "accepted_ar": 18,
                    "accepted_w": 527, "retired_b": 10, "retired_r": 531,
                    "canceled_b": 1, "canceled_r": 3}.items()):
                raise ValueError(f"incomplete fault settlement/cancellation coverage: {measured}")
            if measured["comparisons"] <= 0:
                raise ValueError("no comparisons executed")
            receipt["runs"].append({"simulator": simulator, **measured})
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for path in (ROOT / obj).glob("*"):
            if path.suffix in (".o", ".a", ".gch"):
                path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Coherence fault exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
