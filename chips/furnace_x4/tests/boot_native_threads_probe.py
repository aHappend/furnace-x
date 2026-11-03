#!/usr/bin/env python3
"""Bounded native-thread/save-state compatibility diagnostic, not acceptance."""

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
from verify import sources


FIXTURE = """module native_thread_support(
    input wire clk, input wire rst_n,
    input wire [31:0] a, input wire [31:0] b,
    output reg [31:0] x, output reg [31:0] y
);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        x <= 0;
        y <= 0;
    end else begin
        x <= (x + a) ^ (a << 3);
        y <= (y + b) ^ (b << 5);
    end
end
endmodule
"""


def resources():
    result = {
        "online_cpus": os.cpu_count(),
        "affinity_cpus": sorted(os.sched_getaffinity(0)),
        "quota_note": "Only exposed cgroup files are reported; affinity is not a CPU quota.",
        "cgroup_files": {},
    }
    for name in (
        "/proc/self/cgroup",
        "/sys/fs/cgroup/cpu.max",
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us",
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us",
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us",
    ):
        path = Path(name)
        result["cgroup_files"][name] = (
            path.read_text().strip() if path.exists() else "not exposed"
        )
    print(json.dumps(result, indent=2))


def measure(output, receipt, cycles):
    from boot_pgo_probe import equivalent
    from verify import SEEDS, assert_coverage, coverage_requirements, linux_runs, software

    started = time.monotonic()
    build = software(output, receipt)
    receipt["fresh_software_s"] = time.monotonic() - started
    pairs = {}
    caches = {}
    mismatches = []
    for profile in ("o3-pgo-fixedpoint", "native-threads-candidate"):
        cache = output / f"{profile}-executable-{uuid.uuid4().hex[:8]}"
        caches[profile] = cache
        for seed in SEEDS:
            root = output / f"{profile}-seed{seed}-{uuid.uuid4().hex[:8]}"
            root.mkdir()
            record = run([
                "python3", "tests/boot_probe.py", "--build-receipt", build.relative_to(ROOT),
                "--seed", str(seed), "--cycles", str(cycles), "--compile-profile", profile,
                "--invocation-cache", cache.relative_to(ROOT), "--audit-state",
                "--output-root", root.relative_to(ROOT),
            ], output, f"{profile}-seed{seed}", receipt, timeout_s=2700, check=False)
            found = list(root.glob("boot-*/receipt.json"))
            if len(found) != 1:
                raise ValueError("missing unique native-thread comparison receipt")
            path = found[0]
            child = json.loads(path.read_text())
            receipt.setdefault("children", []).append({
                "receipt": str(path.relative_to(ROOT)), "sha256": digest(path)})
            save(output, receipt)
            simulation = next((row for row in child["commands"]
                               if row["stdout"] == "simulation.stdout.txt"), None)
            if simulation is None:
                raise ValueError("native-thread pairing failed before simulation: " +
                                 child.get("diagnostic_error", str(record["exit_code"])))
            if record["exit_code"] != 1 or child["exit_code"] != 1 or (
                    simulation["exit_code"] != 1 or simulation["timed_out"]):
                raise ValueError("native-thread pairing did not reach compared cycle boundary")
            if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                    path.parent / "simulation-summary.txt").read_text():
                raise ValueError("native-thread pairing contains a semantic failure")
            observed = child["execution_observations"]
            if observed["cycles"] != cycles or observed["retired"] <= 0 or (
                    observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
                raise ValueError("native-thread pairing lacks full compared execution")
            row = {
                "seed": seed, "observed": observed, "final_state": child["final_state"],
                "uart_sha256": digest(path.parent / "uart.txt"),
                "simulation_s": simulation["duration_s"], "receipt": str(path.relative_to(ROOT)),
            }
            if profile == "o3-pgo-fixedpoint":
                pairs[seed] = (child, row)
            else:
                original, before = pairs[seed]
                for key in ("source_sha256", "tool_versions", "image_manifest_sha256",
                            "software_build_receipt_sha256"):
                    if original[key] != child[key]:
                        raise ValueError(f"native-thread pairing input mismatch: {key}")
                comparison = {
                    "seed": seed, "baseline": before, "candidate": row,
                    "speedup": before["simulation_s"] / row["simulation_s"],
                }
                try:
                    equivalent(before, row)
                    comparison["full_equivalence"] = True
                except ValueError as error:
                    comparison["full_equivalence"] = False
                    comparison["mismatch"] = str(error)
                    mismatches.append(f"seed{seed}: {error}")
                receipt.setdefault("equal_work", []).append(comparison)
            save(output, receipt)
    if mismatches:
        raise ValueError("native-thread state comparison rejected: " + "; ".join(mismatches))
    receipt["paired_three_seed_equivalence"] = "exact full-state equality"
    if any(row["speedup"] <= 1 for row in receipt["equal_work"]):
        raise ValueError("native-thread candidate did not improve every measured seed")
    measured = linux_runs(output, receipt, SEEDS, build, audit=True,
                          cache=caches["native-threads-candidate"], stem="complete-native-threads",
                          profile="native-threads-candidate")
    assert_coverage(output, coverage_requirements("linux", SEEDS), measured)
    receipt["complete_three_seed_feasibility"] = "scored complete within inherited deadline"
    receipt["requires_independent_evaluation"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repair-of", type=Path, action="append")
    parser.add_argument("--mode", choices=("support", "measure"), default="support")
    parser.add_argument("--cycles", type=int, default=5000000)
    parser.add_argument("--experiment-origin", type=Path,
                        help="Retain the original support/setup experiment's aggregate deadline")
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    if args.resources:
        resources()
        return 0
    started = time.monotonic()
    deadline = min(float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700)
    origin = None
    if args.experiment_origin:
        origin_path = project_path(args.experiment_origin)
        origin = json.loads(origin_path.read_text())
        original_start = datetime.datetime.fromisoformat(origin["start_utc"])
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - original_start).total_seconds()
        deadline = min(deadline, started + 2700 - elapsed - 1)
    if args.cycles <= 8:
        parser.error("prefix cycles must exceed reset duration")
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(deadline)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-native-threads-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    receipt = {
        "schema": 1,
        "argv": ["python3", "tests/boot_native_threads_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "initial_remaining_s": deadline - started,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "promoted": False,
        "scope": "Native two-thread code-generation and complete-state audit compatibility only.",
        "complete_three_seed_feasibility": "not established",
        "paired_three_seed_equivalence": "not executed",
        "full_state_requirement": {
            "rtl_context": "VerilatedSave via --savable, including all RTL and context state",
            "host_reference": "checkpoint_host without field exclusions",
            "ram": "all 128 MiB",
            "observations": "UART, observers, coverage and every comparison counter unchanged",
        },
    }
    if origin is not None:
        receipt["experiment_origin"] = {
            "receipt": str(args.experiment_origin), "sha256": digest(origin_path),
            "start_utc": origin["start_utc"],
        }
    save(output, receipt)
    print(f"Native-thread support receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        receipt["repair_of"] = [
            {"receipt": str(path), "sha256": digest(project_path(path))}
            for path in (args.repair_of or [])
        ]
        for tool in ("python3", "verilator"):
            record = run([tool, "--version"], output, tool + "-version", receipt)
            receipt.setdefault("tool_versions", {})[tool] = (output / record["stdout"]).read_text()
        run(["python3", "tests/boot_native_threads_probe.py", "--resources"],
            output, "cpu-resources", receipt)
        receipt["resources"] = json.loads((output / "cpu-resources.stdout.txt").read_text())
        if len(receipt["resources"]["affinity_cpus"]) < 2:
            raise ValueError("two-thread candidate lacks two affinity-eligible CPUs")
        fixture = output / "native_thread_support.sv"
        fixture.write_text(FIXTURE)
        receipt["fixture_sha256"] = digest(fixture)
        save(output, receipt)
        base = ["verilator", "--cc", "--threads", "2",
                "--top-module", "native_thread_support", fixture.relative_to(ROOT)]
        run([*base, "--Mdir", relative / "obj-threads"],
            output, "native-two-thread-codegen", receipt)
        receipt["native_two_thread_codegen"] = "supported"
        result = run([*base, "--savable", "--Mdir", relative / "obj-savable-threads"],
                     output, "native-savable-two-thread-codegen", receipt, check=False)
        if result["exit_code"] != 0:
            diagnostic = (output / result["stderr"]).read_text()
            receipt["save_state_compatibility"] = "rejected by installed tool"
            receipt["tool_diagnostic"] = diagnostic.strip()
            raise ValueError(
                "native two-thread evaluation cannot use the existing complete RTL/context "
                "save-state comparison; see native-savable-two-thread-codegen.stderr.txt. "
                "No full-top candidate was built and no output-only substitute was used."
            )
        receipt["save_state_compatibility"] = "code generation accepted; paired comparison still required"
        if args.mode == "measure":
            measure(output, receipt, args.cycles)
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        changed = [name for name, expected in receipt["source_sha256"].items()
                   if not (ROOT / name).is_file() or digest(ROOT / name) != expected]
        receipt["source_binding_changes"] = changed
        if changed:
            status = 1
            receipt["source_binding_error"] = "inputs changed during diagnostic"
        receipt["duration_s"] = time.monotonic() - started
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Native-thread support exit={status}; {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
