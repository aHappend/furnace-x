#!/usr/bin/env python3
"""Fresh-image bounded profile of the currently optimized generated model."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from verify import child_probe, software, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-of", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    started = time.monotonic()
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(min(
        float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-schedule-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_schedule_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "source_sha256": {
            str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "children": [], "repair_of": str(args.repair_of),
        "repair_receipt_sha256": digest(project_path(args.repair_of)),
        "scope": "Sampled generated-function cost; not boot acceptance or equal-work proof.",
    }
    save(output, receipt)
    print(f"Schedule profiling: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        run(["python3", "--version"], output, "python-version", receipt)
        build = software(output, receipt)
        child_root = output / f"profile-{uuid.uuid4().hex[:8]}"
        child_root.mkdir()
        record = run([
            "python3", "tests/boot_probe.py", "--build-receipt", build.relative_to(ROOT),
            "--compile-profile", "schedule-profile", "--cycles", "2000000",
            "--seed", "17", "--audit-state", "--output-root", child_root.relative_to(ROOT),
        ], output, "profile", receipt, timeout_s=1500, check=False)
        paths = list(child_root.glob("boot-*/receipt.json"))
        if len(paths) != 1:
            raise ValueError("missing unique profiling receipt")
        path = paths[0]
        child = json.loads(path.read_text())
        receipt["children"].append({"receipt": str(path.relative_to(ROOT)), "sha256": digest(path)})
        simulation = next(c for c in child["commands"] if c["stdout"] == "simulation.stdout.txt")
        if record["exit_code"] != 1 or simulation["exit_code"] != 1 or simulation["timed_out"]:
            raise ValueError("profile failed before its intended cycle boundary")
        if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                path.parent / "simulation-summary.txt").read_text():
            raise ValueError("profiling simulation has a semantic failure")
        observed = child["execution_observations"]
        if observed["cycles"] != 2000000 or observed["retired"] <= 0 or (
                observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
            raise ValueError("profiling simulation did not execute compared work")
        matches = re.findall(r"^SCHEDULE_PROFILE (\w+) calls=(\d+) samples=(\d+) ns=(\d+)$",
                             (path.parent / "simulation.stderr.txt").read_text(), re.MULTILINE)
        if not matches:
            raise ValueError("no measured function samples")
        rows = [{"function": name, "calls": int(calls), "samples": int(samples),
                 "sample_ns": int(ns), "estimated_ns": int(ns) * int(calls) / int(samples)}
                for name, calls, samples, ns in matches if int(samples)]
        receipt["profile"] = sorted(rows, key=lambda row: row["estimated_ns"], reverse=True)
        receipt["observed"] = observed
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"source changed during measurement: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError, StopIteration) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["duration_s"] = time.monotonic() - started
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Schedule profile exit={status}; {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
