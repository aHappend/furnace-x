#!/usr/bin/env python3
"""Measure the generated-evaluation repair, preserving prior equal-work witnesses."""

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
    parser.add_argument("--baseline-receipt", type=Path, required=True)
    parser.add_argument("--repair-of", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--measure-completion", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(min(
        float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-eval-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_eval_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "source_sha256": {
            str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "children": [],
        "scope": "Generated-evaluation equivalence and aggregate feasibility diagnostic.",
        "hypothesis": "Reuse fixed-point pure AES schedules, not RTL cycles or observer events.",
    }
    save(output, receipt)
    print(f"Generated-evaluation receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        for key in ("baseline_receipt", "repair_of"):
            path = project_path(getattr(args, key))
            receipt[key] = str(path.relative_to(ROOT))
            receipt[key + "_sha256"] = digest(path)
        baseline_path = project_path(args.baseline_receipt)
        baseline = json.loads(baseline_path.read_text())
        if baseline["exit_code"] or not baseline["comparison"]["equal_work_confirmed"]:
            raise ValueError("baseline lacks settled equal-work evidence")
        for row in baseline["children"]:
            path = project_path(Path(row["receipt"]))
            if digest(path) != row["sha256"]:
                raise ValueError("baseline child receipt changed")
        # Execution orchestration changes, but the simulated product and every
        # observer/reference/checkpoint field must remain byte-identical.
        for name, expected in baseline["source_sha256"].items():
            if name.startswith(("rtl/", "sw/")) or name in {
                    "tests/boot_endpoint.cpp", "tests/boot_observers.sv",
                    "tests/boot_execution_model.h", "tests/boot_workload_model.h",
                    "tests/boot_checkpoint_state.h", "tests/boot_scoring.py"}:
                if digest(ROOT / name) != expected:
                    raise ValueError(f"baseline semantic source changed: {name}")
        run(["python3", "--version"], output, "python-version", receipt)
        child_probe("boot_model_probe.py", [], output, receipt, "oracle-unit")
        build = software(output, receipt)
        build_finished = time.monotonic()
        receipt["fresh_software_and_oracle_s"] = build_finished - started
        cache = output / f"shared-executable-{uuid.uuid4().hex[:8]}"
        def prefix(profile, stem, local_cache):
            expected_error = None
            try:
                linux_runs(output, receipt, SEEDS, build, cycles=baseline["cycles_limit"],
                           audit=True, cache=local_cache, stem=stem, profile=profile)
            except ValueError as error:
                expected_error = str(error)
            if set((expected_error or "").split("; ")) != {
                    f"seed{seed}: boot exit=1" for seed in SEEDS}:
                raise ValueError(f"unexpected prefix outcome: {expected_error}")
            return list(receipt["boot_runs"])

        reference_runs = prefix("o3-pgo", "reference",
                                output / f"reference-executable-{uuid.uuid4().hex[:8]}")
        candidate_runs = prefix("o3-pgo-fixedpoint", "equal-work", cache)
        def observation(entry):
            path = project_path(Path(entry["receipt"]))
            child = json.loads(path.read_text())
            command = next(c for c in child["commands"] if c["stdout"] == "simulation.stdout.txt")
            if command["timed_out"] or command["exit_code"] != 1 or (
                    "FAIL: cycle budget exhausted without complete workload UART record" not in
                    (path.parent / "simulation-summary.txt").read_text()):
                raise ValueError("candidate failed before the equal-work boundary")
            for name in ("python3", "verilator", "g++", "make"):
                old = baseline["tool_versions"][name]
                if child["tool_versions"][name]["stdout"] != old:
                    raise ValueError(f"equal-work tool changed: {name}")
            return {
                "seed": entry["seed"], "observed": child["execution_observations"],
                "final_state": child["final_state"], "uart_sha256": digest(path.parent / "uart.txt"),
                "simulation_s": command["duration_s"],
            }
        reference_by_seed = {entry["seed"]: entry for entry in reference_runs}
        prior_by_seed = {entry["seed"]: observation(entry) for entry in reference_runs}
        rows = []
        for entry in candidate_runs:
            path = project_path(Path(entry["receipt"]))
            child = json.loads(path.read_text())
            original = json.loads(project_path(Path(
                reference_by_seed[entry["seed"]]["receipt"])).read_text())
            for name in ("image_manifest_sha256", "software_build_receipt_sha256",
                         "source_sha256", "tool_versions"):
                if child[name] != original[name]:
                    raise ValueError(f"paired experiment input differs: {name}")
            row = observation(entry)
            equivalent(prior_by_seed[entry["seed"]], row)
            rows.append(row)
        prefix_finished = time.monotonic()
        receipt["equal_work"] = {
            "complete_state_uart_coverage_counters_equal": True, "runs": rows,
            "reference_runs": reference_runs,
            "fresh_build_compile_training_overlap_and_serialization_s": prefix_finished - started,
            "incremental_simulation_speedups": {
                str(row["seed"]): prior_by_seed[row["seed"]]["simulation_s"] / row["simulation_s"]
                for row in rows},
            "limitation": "Prefix equivalence is not complete Linux acceptance.",
        }
        save(output, receipt)
        receipt["complete_three_seed_feasibility"] = "not measured"
        if args.measure_completion:
            # The same invocation-local model is reused. Each seed starts at reset,
            # not at a prefix checkpoint; all original comparisons remain enabled.
            linux_runs(output, receipt, SEEDS, build, audit=True, cache=cache,
                       stem="completion")
            receipt["complete_three_seed_feasibility"] = "all seeds scored complete"
            receipt["complete_build_execution_serialization_scoring_s"] = time.monotonic() - started
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
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
    print(f"Generated-evaluation exit={status}; {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
