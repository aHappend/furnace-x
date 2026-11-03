#!/usr/bin/env python3
"""One GCC PGO candidate, equal-work state comparison and measured seed overlap."""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from verify import sources


def state_identity(folder):
    identities = {
        name: {"sha256": digest(folder / name), "bytes": (folder / name).stat().st_size}
        for name in ("rtl-context.bin", "host.bin", "ram.bin")
    }
    (folder / "ram.bin").unlink()
    return identities


def parallel_worker(path):
    """Children inherit this worker's owned group for bounded runner cleanup."""
    plan = json.loads(path.read_text())
    output = path.parent
    receipt = plan["receipt"]
    children = []
    started = time.monotonic()
    status = 1
    try:
        for seed in (17, 89, 211):
            folder = output / f"seed{seed}-{uuid.uuid4().hex[:8]}"
            folder.mkdir()
            storage = folder / "checkpoint-images"
            storage.mkdir()
            state = storage / f"final-{uuid.uuid4().hex[:8]}"
            relative = folder.relative_to(ROOT)
            argv = [
                plan["executable"], plan["image_index"], str(relative / "uart.txt"),
                str(plan["cycles"]), str(seed), str(relative / "simulation-summary.txt"),
                str(relative / "execution-measurements.json"),
            ]
            record = {
                "argv": argv, "cwd": ".", "start_utc": now(), "end_utc": None,
                "timeout_s": 600, "timed_out": False, "exit_code": None,
                "stdout": str((folder / "simulation.stdout.txt").relative_to(output)),
                "stderr": str((folder / "simulation.stderr.txt").relative_to(output)),
                "seed": seed,
            }
            receipt["commands"].append(record)
            stdout = (output / record["stdout"]).open("x")
            stderr = (output / record["stderr"]).open("x")
            env = dict(os.environ, FURNACE_BOOT_AUDIT_DIR=str(state.relative_to(ROOT)))
            child = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
            children.append((child, record, folder, state, stdout, stderr, time.monotonic()))
        save(output, receipt)
        heartbeat = time.monotonic()
        while any(row[0].poll() is None for row in children):
            for child, record, *_rest, child_started in children:
                if child.poll() is None and time.monotonic() - child_started >= 600:
                    record["timed_out"] = True
                    raise RuntimeError(f"parallel seed{record['seed']} exceeded 600 seconds")
            if time.monotonic() - heartbeat >= 25:
                print("PGO concurrent RTL instances running", flush=True)
                heartbeat = time.monotonic()
            time.sleep(0.2)
        receipt["wall_s"] = time.monotonic() - started
        receipt["runs"] = []
        for child, record, folder, state, stdout, stderr, child_started in children:
            stdout.close()
            stderr.close()
            observed = json.loads((folder / "execution-measurements.json").read_text())
            if child.returncode != 1 or observed["simulation_exit"] != 1 or (
                    observed["cycles"] != plan["cycles"]):
                raise ValueError("parallel instance did not reach equal-work prefix")
            if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                    folder / "simulation-summary.txt").read_text():
                raise ValueError("parallel instance has an unexpected semantic failure")
            receipt["runs"].append({
                "seed": record["seed"], "observed": observed,
                "final_state": state_identity(state), "uart_sha256": digest(folder / "uart.txt"),
            })
        status = 0
    finally:
        for child, record, _folder, _state, stdout, stderr, child_started in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            record["exit_code"] = child.returncode
            record["end_utc"] = now()
            record["duration_s"] = time.monotonic() - child_started
            stdout.close()
            stderr.close()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    return status


def equivalent(left, right):
    for key in ("final_state", "uart_sha256"):
        if left[key] != right[key]:
            raise ValueError(f"equal-work {key} mismatch")
    for key in left["observed"]:
        if key != "profile" and left["observed"][key] != right["observed"][key]:
            raise ValueError(f"equal-work observation mismatch: {key}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--cost-receipt", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return parallel_worker(project_path(args.worker))
    if not all((args.build_receipt, args.repair_of, args.cost_receipt)):
        parser.error("--build-receipt, --repair-of and --cost-receipt are required")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-pgo-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_pgo_probe.py", *sys.argv[1:]], "cwd": ".",
        "start_utc": now(), "end_utc": None, "exit_code": None, "timeout_s": 2700,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "children": [], "cycles_limit": 5000000,
        "scope": "PGO/equivalence/overlap measurements only; no complete-boot acceptance",
        "hypothesis": "GCC branch/block profiles improve measured generated RTL dispatch/evaluation.",
    }
    save(output, receipt)
    print(f"PGO preparation receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        for key in ("build_receipt", "repair_of", "cost_receipt"):
            path = project_path(getattr(args, key))
            receipt[key] = str(path.relative_to(ROOT))
            receipt[key + "_sha256"] = digest(path)
        for tool in ("python3", "verilator", "g++", "make"):
            record = run([tool, "--version"], output, tool + "-version", receipt)
            receipt.setdefault("tool_versions", {})[tool] = (output / record["stdout"]).read_text()

        def prefix(profile, seed, cache=None, repair=None):
            root = output / f"{profile}-seed{seed}-{uuid.uuid4().hex[:8]}"
            root.mkdir()
            command = [
                "python3", "tests/boot_probe.py", "--build-receipt", args.build_receipt,
                "--seed", str(seed), "--cycles", str(receipt["cycles_limit"]),
                "--compile-profile", profile, "--audit-state", "--output-root",
                root.relative_to(ROOT),
            ]
            if cache:
                command += ["--invocation-cache", cache.relative_to(ROOT)]
            if repair:
                command += ["--repair-of", repair]
            result = run(command, output, root.name, receipt, timeout_s=1500, check=False)
            found = list(root.glob("boot-*/receipt.json"))
            if len(found) != 1:
                raise ValueError("missing unique prefix receipt")
            path = found[0]
            child = json.loads(path.read_text())
            receipt["children"].append({
                "receipt": str(path.relative_to(ROOT)), "sha256": digest(path),
            })
            save(output, receipt)
            if result["exit_code"] != 1 or child["exit_code"] != 1 or (
                    child.get("diagnostic_error", "").split(";")[0] != "simulation exit=1"):
                raise ValueError("prefix failed before expected bounded cycle exhaustion")
            simulation = next(c for c in child["commands"] if c["stdout"] == "simulation.stdout.txt")
            if simulation["timed_out"]:
                raise ValueError("prefix timed out")
            if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                    path.parent / "simulation-summary.txt").read_text():
                raise ValueError("unexpected semantic failure")
            observed = child["execution_observations"]
            if observed["cycles"] != receipt["cycles_limit"] or (
                    observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
                raise ValueError("prefix lacks required compared execution")
            return path, child, {
                "seed": seed, "observed": observed, "final_state": child["final_state"],
                "uart_sha256": digest(path.parent / "uart.txt"), "duration_s": simulation["duration_s"],
            }

        baseline_path, baseline, before = prefix("o3-split", 17)
        cache = output / f"shared-executable-{uuid.uuid4().hex[:8]}"
        candidate_path, candidate, after = prefix(
            "o3-pgo", 17, cache, baseline_path.relative_to(ROOT))
        for key in ("source_sha256", "tool_versions", "image_manifest_sha256",
                    "software_build_receipt_sha256"):
            if baseline[key] != candidate[key]:
                raise ValueError(f"PGO input identity changed: {key}")
        equivalent(before, after)
        sequential = [after]
        for seed in (89, 211):
            _path, child, row = prefix("o3-pgo", seed, cache)
            if child["executable_reuse"]["compiled"] or (
                    child["executable_sha256"] != candidate["executable_sha256"]):
                raise ValueError("later seed did not reuse the identical compiled executable")
            sequential.append(row)
        manifest_path = cache / "executable.json"
        manifest = json.loads(manifest_path.read_text())
        if digest(project_path(Path(manifest["executable"]))) != manifest["sha256"]:
            raise ValueError("candidate executable changed")
        parallel = output / f"parallel-{uuid.uuid4().hex[:8]}"
        parallel.mkdir()
        plan = {
            "executable": manifest["executable"], "cycles": receipt["cycles_limit"],
            "image_index": str((candidate_path.parent / "image-index.txt").relative_to(ROOT)),
            "receipt": {
                "schema": 1, "argv": ["python3", "tests/boot_pgo_probe.py", "--worker",
                                      str((parallel / "plan.json").relative_to(ROOT))],
                "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
                "timeout_s": 600, "commands": [], "source_sha256": receipt["source_sha256"],
                "executable_sha256": manifest["sha256"],
                "tool_versions": candidate["tool_versions"],
                "image_manifest_sha256": candidate["image_manifest_sha256"],
            },
        }
        (parallel / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
        run(["python3", "tests/boot_pgo_probe.py", "--worker",
             (parallel / "plan.json").relative_to(ROOT)], output, "parallel", receipt)
        concurrent = json.loads((parallel / "receipt.json").read_text())
        receipt["children"].append({
            "receipt": str((parallel / "receipt.json").relative_to(ROOT)),
            "sha256": digest(parallel / "receipt.json"),
        })
        for left, right in zip(sequential, concurrent["runs"]):
            if left["seed"] != right["seed"]:
                raise ValueError("parallel seed ordering differs")
            equivalent(left, right)
        cost_path = project_path(args.cost_receipt).parent / "analysis.json"
        cost = json.loads(cost_path.read_text())
        receipt["cost_analysis_sha256"] = digest(cost_path)
        compilation = json.loads(project_path(Path(manifest["compilation_receipt"])).read_text())
        speedup = before["duration_s"] / after["duration_s"]
        overlap = sum(row["duration_s"] for row in sequential) / concurrent["wall_s"]
        receipt["comparison"] = {
            "equal_work_confirmed": True, "sequential": sequential,
            "baseline": before, "pgo_speedup": speedup, "concurrent_wall_s": concurrent["wall_s"],
            "measured_overlap_speedup": overlap, "one_compilation_for_three_seeds": True,
            "profile_compilation_and_training_s": sum(c["duration_s"] for c in compilation["commands"]),
            "historical_incomplete_single_seed_s":
                cost["measured_prefix_simulation_s_including_serialization"],
            "historical_cycles_from_reset": cost["cycles_from_reset"],
            "three_historical_prefix_projection_s":
                cost["three_seed_prefix_projection_s"] / speedup / overlap,
            "complete_three_seed_boot_cost_s": None, "aggregate_check_budget_s": 2700,
            "limitation": "Prefix ratios do not establish later boot/workload speed or complete execution cost.",
        }
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError(f"source changed during PGO diagnostic: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError, StopIteration) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"PGO preparation exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
