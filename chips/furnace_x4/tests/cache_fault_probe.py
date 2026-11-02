#!/usr/bin/env python3
"""Public cache dirty-command3/refill errors; distinct from controller-boundary faults."""

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
    output = project_path(args.output_root)/f"cache-fault-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    names = ("rtl/hammer_v3_cache.sv", "tests/cache_fault_contract.sv",
             "tests/cache_fault_probe.py", "tests/boot_probe.py")
    receipt = {
        "schema": 1, "argv": ["python3", "tests/cache_fault_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT/name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [],
        "scope": "Leaf dirty_cache_leaf_endpoint_error, refill errors, reset/stall conservation. "
                 "Not full-top DRAIN, DWAIT or IWAIT fault evidence.",
    }
    if args.repair_of:
        receipt.update(repair_of=str(args.repair_of),
                       repair_receipt_sha256=digest(project_path(args.repair_of)))
    save(output, receipt)
    print(f"Cache fault receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        for lines in (1, 4, 16, 64):
            for readonly in (0, 1):
                label = f"lines{lines}-readonly{readonly}"
                directory = output/f"{label}-{uuid.uuid4().hex[:8]}"
                directory.mkdir()
                inputs = ["rtl/hammer_v3_cache.sv", "tests/cache_fault_contract.sv"]
                run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                     "--top-module", "cache_fault_contract", "--Mdir",
                     directory.relative_to(ROOT)/"obj", f"-GLINES={lines}",
                     f"-GREAD_ONLY={readonly}", *inputs], output, label+"-compile", receipt)
                if lines == 1:
                    run(["iverilog", "-g2012", "-Wall", "-s", "cache_fault_contract",
                         "-o", directory.relative_to(ROOT)/"cache.vvp",
                         f"-Pcache_fault_contract.LINES={lines}",
                         f"-Pcache_fault_contract.READ_ONLY={readonly}", *inputs],
                        output, label+"-icarus-compile", receipt)
                for simulator in (("icarus", "verilator") if lines == 1 else ("verilator",)):
                    argv = (["vvp", directory.relative_to(ROOT)/"cache.vvp"] if simulator == "icarus"
                            else [directory.relative_to(ROOT)/"obj/Vcache_fault_contract"])
                    stem = label+"-"+simulator
                    run(argv, output, stem, receipt)
                    text = (output/f"{stem}.stdout.txt").read_text()
                    matches = re.findall(r"^CACHE_FAULT (.+)$", text, re.MULTILINE)
                    if len(matches) != 1:
                        raise ValueError(f"{stem}: missing actual cache comparison summary")
                    counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", matches[0])}
                    if counts["lines"] != lines or counts["readonly"] != readonly or (
                            counts["accepted"] != counts["retired"]+counts["canceled"] or
                            counts["canceled"] != 2 or counts["comparisons"] <= 0 or
                            counts["stalls"] <= 0 or counts["resets"] != 3 or
                            counts["invalidated"] != 1 or counts["failed_reads"] != 1 or
                            (not readonly and (counts["failed_writes"] != 2 or
                                               counts["dirty_preserved"] != 1))):
                        raise ValueError(f"{stem}: incomplete measured fault coverage")
                    receipt["runs"].append({"scope": "leaf", "simulator": simulator, **counts})
                    save(output, receipt)
                for path in (directory/"obj").iterdir():
                    if path.suffix in (".o", ".a", ".gch"):
                        path.unlink()
        if len(receipt["runs"]) != 10:
            raise ValueError("cache fault matrix incomplete")
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for directory in output.glob("lines*-*/obj"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Cache fault exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
