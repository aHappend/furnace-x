#!/usr/bin/env python3
"""Paired generated-region memoization with fresh images and exact final state."""

import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from boot_pgo_probe import equivalent
from verify import SEEDS, child_probe, linux_runs, software, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-of", type=Path, required=True)
    parser.add_argument("--profile-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--measure-completion", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(min(
        float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-replay-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_replay_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "source_sha256": {
            str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "children": [], "cycles_limit": 5000000,
        "scope": "Equal-work diagnostic, not mandatory Linux acceptance.",
        "hypothesis": "Replay unchanged deterministic generated statement regions, "
                      "including local temporaries; preserve all RTL state and observers.",
    }
    save(output, receipt)
    print(f"Generated-region pairing: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        for key in ("repair_of", "profile_receipt"):
            path = project_path(getattr(args, key))
            receipt[key] = str(path.relative_to(ROOT))
            receipt[key + "_sha256"] = digest(path)
        run(["python3", "--version"], output, "python-version", receipt)
        child_probe("boot_model_probe.py", [], output, receipt, "oracle-unit")
        build = software(output, receipt)
        receipt["fresh_software_and_oracle_s"] = time.monotonic() - started

        def prefix(profile, stem):
            cache = output / f"{stem}-executable-{uuid.uuid4().hex[:8]}"
            error = None
            try:
                linux_runs(output, receipt, SEEDS, build, cycles=receipt["cycles_limit"],
                           audit=True, cache=cache, stem=stem, profile=profile)
            except ValueError as failure:
                error = str(failure)
            if set((error or "").split("; ")) != {
                    f"seed{seed}: boot exit=1" for seed in SEEDS}:
                raise ValueError(f"unexpected prefix outcome: {error}")
            return list(receipt["boot_runs"]), cache

        baseline, _ = prefix("o3-pgo-fixedpoint", "baseline")
        candidate, cache = prefix("o3-pgo-replay", "candidate")

        def observation(entry):
            path = project_path(Path(entry["receipt"]))
            child = json.loads(path.read_text())
            command = next(c for c in child["commands"] if c["stdout"] == "simulation.stdout.txt")
            if command["timed_out"] or command["exit_code"] != 1 or (
                    "FAIL: cycle budget exhausted without complete workload UART record" not in
                    (path.parent / "simulation-summary.txt").read_text()):
                raise ValueError("pair did not reach its compared cycle boundary")
            return child, {
                "seed": entry["seed"], "observed": child["execution_observations"],
                "final_state": child["final_state"], "uart_sha256": digest(path.parent / "uart.txt"),
                "simulation_s": command["duration_s"],
            }

        baseline_by_seed = {entry["seed"]: observation(entry) for entry in baseline}
        comparisons = []
        for entry in candidate:
            original, left = baseline_by_seed[entry["seed"]]
            child, right = observation(entry)
            for name in ("source_sha256", "tool_versions", "image_manifest_sha256",
                         "software_build_receipt_sha256"):
                if child[name] != original[name]:
                    raise ValueError(f"paired experiment input differs: {name}")
            equivalent(left, right)
            comparisons.append({
                "seed": entry["seed"], "baseline": left, "candidate": right,
                "speedup": left["simulation_s"] / right["simulation_s"],
            })
        receipt["equal_work"] = {
            "complete_state_uart_coverage_counters_equal": True,
            "comparisons": comparisons, "baseline_runs": baseline, "candidate_runs": candidate,
            "fresh_build_compile_training_overlap_and_serialization_s": time.monotonic() - started,
            "limitation": "Prefix equivalence is not complete Linux acceptance.",
        }
        receipt["complete_three_seed_feasibility"] = "not measured"
        save(output, receipt)
        if args.measure_completion:
            linux_runs(output, receipt, SEEDS, build, audit=True, cache=cache,
                       stem="completion", profile="o3-pgo-replay")
            receipt["complete_three_seed_feasibility"] = "all seeds scored complete"
            receipt["complete_build_execution_serialization_scoring_s"] = time.monotonic() - started
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
    print(f"Generated-region exit={status}; {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
