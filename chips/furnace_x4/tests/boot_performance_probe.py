#!/usr/bin/env python3
"""Compare retained equal-work boot diagnostics; never certify a partial boot."""

import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import COMPILE_PROFILES, ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--comparison-mode", choices=("legacy-o2", "compiler-profile"),
                        default="legacy-o2")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-performance-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_performance_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 600, "commands": [], "source_sha256": {
            name: digest(ROOT / name) for name in (
                "tests/boot_performance_probe.py", "tests/boot_probe.py",
            )
        },
        "scope": "Paired equal-work performance/equivalence diagnostic, not Linux acceptance",
        "retained_inputs": {},
    }
    save(output, receipt)
    status = 1
    try:
        run(["python3", "--version"], output, "python-version", receipt)
        paths = [project_path(args.before), project_path(args.after)]
        rows = []
        for path in paths:
            child = json.loads(path.read_text())
            retained = [path, *[path.parent / name for name in (
                "execution-measurements.json", "compile.stdout.txt",
                "simulation-summary.txt", "uart.txt",
            )]]
            receipt["retained_inputs"].update({
                str(p.relative_to(ROOT)): digest(p) for p in retained
            })
            simulation = next(r for r in child["commands"]
                              if r["stdout"] == "simulation.stdout.txt")
            if simulation["timed_out"] or simulation["exit_code"] != 1 or (
                    child["diagnostic_error"].split(";")[0] != "simulation exit=1"):
                raise ValueError("pair must contain settled cycle-exhaustion diagnostics")
            if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                    path.parent / "simulation-summary.txt").read_text():
                raise ValueError("pair contains an unexpected semantic failure")
            commands = (path.parent / "compile.stdout.txt").read_text().splitlines()
            compiler = [line for line in commands
                        if re.search(r"(?:g\+\+|c\+\+).* -c .*boot_endpoint\.cpp", line)]
            if len(compiler) != 1:
                raise ValueError("missing unique effective endpoint compiler invocation")
            flags = re.findall(r"(?<!\S)-O\S+", compiler[0])
            measured = json.loads((path.parent / "execution-measurements.json").read_text())
            profile = measured["profile"]
            elapsed = profile["elapsed_ns"]
            rows.append({
                "receipt": str(path.relative_to(ROOT)), "seed": child["seed"],
                "cycles_limit": child["cycles_limit"], "observed": measured,
                "simulation_duration_s": simulation["duration_s"],
                "elapsed_s": elapsed / 1e9, "endpoint_compiler": compiler[0],
                "endpoint_optimization_flags": flags,
                "compile_profile": child.get("compile_profile"),
                "compile_configuration": child.get("compile_configuration"),
                "sampled_phase_fraction_estimates": {
                    name: profile[name] * measured["cycles"] / profile["cycle_samples"] / elapsed
                    for name in ("drive_ns", "low_eval_ns", "endpoint_sample_ns",
                                 "high_eval_including_observers_ns")
                },
                "sampled_retire_fraction_estimate":
                    profile["retire_model_ns"] * measured["retired"] /
                    profile["retire_samples"] / elapsed,
            })
        before, after = [json.loads(p.read_text()) for p in paths]
        if after["repair_of"] != str(args.before) or (
                after["repair_receipt_sha256"] != digest(paths[0])):
            raise ValueError("after receipt is not linked to the before receipt")
        for name in ("seed", "cycles_limit", "image_manifest_sha256",
                     "software_build_receipt_sha256", "tool_versions"):
            if before[name] != after[name]:
                raise ValueError(f"changed experiment input: {name}")
        if before["source_sha256"].keys() != after["source_sha256"].keys():
            raise ValueError("paired source inventories differ")
        changed = {name for name in before["source_sha256"]
                   if before["source_sha256"][name] != after["source_sha256"].get(name)}
        expected_changed = ({"tests/boot_execution_model.h", "tests/boot_probe.py"}
                            if args.comparison_mode == "legacy-o2" else set())
        if changed != expected_changed:
            raise ValueError(f"unexpected paired source differences: {sorted(changed)}")
        snapshots = ["boot_endpoint.cpp", "boot_workload_model.h", "boot_observers.sv"]
        if args.comparison_mode == "compiler-profile":
            snapshots += ["boot_probe.py", "boot_execution_model.h"]
        for name in snapshots:
            if digest(paths[0].parent / "sources" / name) != digest(
                    paths[1].parent / "sources" / name):
                raise ValueError(f"paired source snapshot differs: {name}")
        for row in rows:
            if row["observed"]["equal_comparisons"] <= 0 or (
                    row["observed"]["require_comparisons"] <= 0):
                raise ValueError("missing retained comparisons")
        for name in rows[0]["observed"]:
            if name != "profile" and rows[0]["observed"][name] != rows[1]["observed"][name]:
                raise ValueError(f"changed measured behavior/comparison count: {name}")
        if digest(paths[0].parent / "uart.txt") != digest(paths[1].parent / "uart.txt"):
            raise ValueError("UART bytes changed")
        if args.comparison_mode == "legacy-o2":
            if rows[0]["endpoint_optimization_flags"][-1] != "-Os" or (
                    rows[1]["endpoint_optimization_flags"][-1] != "-O2"):
                raise ValueError("effective compiler flags did not change as intended")
        else:
            if before["compile_profile"] == after["compile_profile"]:
                raise ValueError("compiler-profile comparison requires distinct profiles")
            normalized = []
            for path, child, row in zip(paths, (before, after), rows):
                profile = COMPILE_PROFILES[child["compile_profile"]]
                if child["compile_configuration"] != profile:
                    raise ValueError("compile profile differs from its declared configuration")
                if row["endpoint_optimization_flags"][-1] != profile["optimization"]:
                    raise ValueError("effective endpoint optimization differs from declared profile")
                command = next(r for r in child["commands"]
                               if r["stdout"] == "compile.stdout.txt")["argv"].copy()
                for flag in profile["verilator"]:
                    command.remove(flag)
                for flag in (
                    f'OPT_FAST={profile["optimization"]} OPT_SLOW={profile["optimization"]} OPT_GLOBAL={profile["optimization"]}',
                    f'{profile["optimization"]} -std=c++17',
                ):
                    command.remove(flag)
                # Output namespaces and their relative C++ paths necessarily differ.
                command[command.index("--Mdir") + 1] = "<fresh-output>/obj"
                command[-1] = "<relative>/tests/boot_endpoint.cpp"
                normalized.append(command)
                generated = (path.parent / "compile.stdout.txt").read_text().splitlines()
                fast = [line for line in generated if " -c " in line and
                        "Vfurnace_x4_top" in line and "__Slow" not in line]
                if not fast or any(re.findall(r"(?<!\S)-O\S+", line)[-1] !=
                                   profile["optimization"] for line in fast):
                    raise ValueError("generated fast RTL compiler flags differ from profile")
            if normalized[0] != normalized[1]:
                raise ValueError("compile commands differ beyond explicitly declared optimization flags")
        receipt["comparison"] = {
            "runs": rows, "equal_work_confirmed": True,
            "comparison_mode": args.comparison_mode,
            "allowed_source_differences": sorted(expected_changed),
            "elapsed_speedup": rows[0]["elapsed_s"] / rows[1]["elapsed_s"],
            "limitations": "One paired seed on a shared host; sampled timing estimates are not a causal decomposition.",
            "linux_completion": False,
        }
        status = 0
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Boot performance receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
