#!/usr/bin/env python3
"""One bounded opt-in dependency-scheduling contract/equivalence experiment.

The mandatory strategy is never changed here. Prefixes are diagnostic failures
at an exact cycle boundary, not completed Linux boots. Any mismatch or measured
non-improvement rejects the candidate; complete scored three-seed execution and
independent evaluation are additionally required before promotion.
"""

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
from verify import SEEDS, sources


def contract(output, receipt):
    from generated_dependency import transform
    header = r"""
struct Vfurnace_x4_top___024root {
    VL_IN8(rst_n,0,0);
    VL_IN(input,31,0);
    VL_OUT(output,31,0);
    IData/*31:0*/ middle;
    IData/*31:0*/ alternate;
    IData/*31:0*/ feedback;
    IData/*31:0*/ unknown;
    IData/*31:0*/ index;
    IData/*31:0*/ array[4];
};
"""
    signature = ("VL_INLINE_OPT void model___ico_sequent__TOP__0"
                 "(Vfurnace_x4_top___024root* vlSelf) {\n"
                 "// Init\nIData/*31:0*/ local;\nlocal = 0;\n// Body\n")
    body = r"""
    local = vlSelf->input * 7U;
    if (vlSelf->input & 1U) {
        vlSelf->middle = local + 1U;
    } else {
        vlSelf->middle = local + 2U;
    }
    vlSelf->output = vlSelf->middle ^ local;
    vlSelf->alternate = vlSelf->input + 3U;
    vlSelf->output = vlSelf->output + vlSelf->alternate;
    vlSelf->feedback = (vlSelf->feedback < 9U) ? vlSelf->feedback + 1U : 9U;
    vlSelf->array[vlSelf->index & 3U] = vlSelf->input;
    vlSelf->output = vlSelf->output ^ vlSelf->array[(vlSelf->index + 1U) & 3U];
    escape(vlSelf->unknown);
"""
    tail = r"""
void model___nba_sequent__TOP__0(Vfurnace_x4_top___024root* vlSelf) {
    if (vlSelf->input & 2U) { vlSelf->middle = vlSelf->input ^ 0x55U; }
    if (vlSelf->input & 4U) { vlSelf->output = vlSelf->input + 19U; }
}
void model___eval(Vfurnace_x4_top___024root* vlSelf) {
    model___ico_sequent__TOP__0(vlSelf);
    model___nba_sequent__TOP__0(vlSelf);
    model___ico_sequent__TOP__0(vlSelf);
}
"""
    original = signature + body + "\n}\n" + tail
    init = r"""
void initialize(Vfurnace_x4_top___024root* vlSelf) {
    vlSelf->middle = 0;
    vlSelf->output = 0;
    vlSelf->feedback = 0;
}
"""
    transformed, sideband, report = transform(
        {"model.cpp": original, "model__Slow.cpp": init}, header)
    if not report["regions"] or report["unconditional_regions"] < 3 or (
            "unknown" not in report["excluded_fields"]):
        raise ValueError("dependency contract did not retain unsupported/alias regions")
    if report["writers"].get("middle", 0) < 3 or (
            report["writers"].get("output", 0) < 4):
        raise ValueError("dependency contract omitted conditional/multiple/init writers")
    local_regions = [row for row in report["regions"] if row["body_bytes"] >=
                     len("local = vlSelf->input * 7U;")]
    if not local_regions or "local" not in next(
            item for item in transformed["model.cpp"].split("// Body\n")[1:]
            if "local =" in item):
        raise ValueError("dependency contract lost local lifetime")
    (output / "generated_dependency.h").write_text(sideband)
    definitions = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
using CData = uint8_t;
using IData = uint32_t;
#define VL_IN8(name,hi,lo) CData name
#define VL_IN(name,hi,lo) IData name
#define VL_OUT(name,hi,lo) IData name
#define VL_INLINE_OPT
void escape(IData& value) { value ^= 0x31U; }
"""
    reference = original.replace("model___", "reference___")
    reference_init = init.replace("initialize", "reference_initialize")
    program = definitions + header + reference + reference_init + "\n" + (
        transformed["model.cpp"] + transformed["model__Slow.cpp"]) + r"""
int main() {
    Vfurnace_x4_top___024root actual{}, expected{}, other{}, other_expected{};
    uint32_t random = 17;
    uint64_t compared = 0;
    for (unsigned i = 0; i < 20000; ++i) {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        if (i % 7 == 0) actual.input = expected.input = random;
        if (i % 13 == 0) actual.output = expected.output = random ^ i;
        if (i % 17 == 0) actual.middle = expected.middle = random + i;
        actual.index = expected.index = i & 3U;
        actual.array[(i + 1) & 3U] = expected.array[(i + 1) & 3U] = random;
        actual.rst_n = expected.rst_n = (i % 19 > 2);
        if (i % 23 == 0) {
            initialize(&actual); reference_initialize(&expected);
        }
        // Repeated evaluation tests fixed points and intentionally nonconvergent
        // WAW regions without changing the model's original iteration count.
        for (unsigned j = 0; j < 3; ++j) {
            model___eval(&actual); reference___eval(&expected);
            assert(std::memcmp(&actual, &expected, sizeof(actual)) == 0);
            ++compared;
        }
        if (i % 29 == 0) {
            other.input = other_expected.input = random ^ 123U;
            model___eval(&other); reference___eval(&other_expected);
            assert(std::memcmp(&other, &other_expected, sizeof(other)) == 0);
            ++compared;
        }
    }
    std::cout << "DEPENDENCY full_state_comparisons=" << compared << "\n";
}
"""
    (output / "dependency-contract.cpp").write_text(program)
    run(["g++", "--version"], output, "compiler-version", receipt)
    run(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra",
         output.relative_to(ROOT) / "dependency-contract.cpp", "-o",
         output.relative_to(ROOT) / "dependency-contract"],
        output, "dependency-contract-build", receipt)
    run([output.relative_to(ROOT) / "dependency-contract"],
        output, "dependency-contract-run", receipt)
    receipt["contract"] = report
    receipt["contract"]["log"] = "dependency-contract-run.stdout.txt"
    save(output, receipt)


def measure(output, receipt, cycles):
    from boot_pgo_probe import equivalent
    from verify import assert_coverage, coverage_requirements, linux_runs, software
    started = time.monotonic()
    build = software(output, receipt)
    receipt["fresh_software_s"] = time.monotonic() - started
    pairs = {}
    caches = {}
    for profile in ("o3-pgo-fixedpoint", "dependency-candidate"):
        cache = output / f"{profile}-executable-{uuid.uuid4().hex[:8]}"
        caches[profile] = cache
        for seed in SEEDS:
            root = output / f"{profile}-seed{seed}-{uuid.uuid4().hex[:8]}"
            root.mkdir()
            started = time.monotonic()
            record = run([
                "python3", "tests/boot_probe.py", "--build-receipt", build.relative_to(ROOT),
                "--seed", str(seed), "--cycles", str(cycles), "--compile-profile", profile,
                "--invocation-cache", cache.relative_to(ROOT), "--audit-state",
                "--output-root", root.relative_to(ROOT),
            ], output, f"{profile}-seed{seed}", receipt, timeout_s=2700, check=False)
            found = list(root.glob("boot-*/receipt.json"))
            if len(found) != 1:
                raise ValueError("missing unique dependency comparison receipt")
            path = found[0]
            child = json.loads(path.read_text())
            receipt["children"].append({"receipt": str(path.relative_to(ROOT)),
                                        "sha256": digest(path)})
            save(output, receipt)
            simulation = next((row for row in child["commands"]
                               if row["stdout"] == "simulation.stdout.txt"), None)
            if simulation is None:
                raise ValueError("dependency pairing failed before simulation: " +
                                 child.get("diagnostic_error", str(record["exit_code"])))
            if record["exit_code"] != 1 or child["exit_code"] != 1 or (
                    simulation["exit_code"] != 1 or simulation["timed_out"]):
                raise ValueError("dependency pairing did not reach compared cycle boundary")
            summary = (path.parent / "simulation-summary.txt").read_text()
            if "FAIL: cycle budget exhausted without complete workload UART record" not in summary:
                raise ValueError("dependency pairing contains a semantic failure")
            observed = child["execution_observations"]
            if observed["cycles"] != cycles or observed["retired"] <= 0 or (
                    observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
                raise ValueError("dependency pairing lacks full compared execution")
            row = {
                "seed": seed, "observed": observed, "final_state": child["final_state"],
                "uart_sha256": digest(path.parent / "uart.txt"),
                "simulation_s": simulation["duration_s"],
                "total_child_s": time.monotonic() - started,
                "receipt": str(path.relative_to(ROOT)),
            }
            if profile == "o3-pgo-fixedpoint":
                pairs[seed] = (child, row)
            else:
                original, before = pairs[seed]
                for key in ("source_sha256", "tool_versions", "image_manifest_sha256",
                            "software_build_receipt_sha256"):
                    if original[key] != child[key]:
                        raise ValueError(f"dependency pairing input mismatch: {key}")
                equivalent(before, row)
                receipt.setdefault("equal_work", []).append({
                    "seed": seed, "baseline": before, "candidate": row,
                    "speedup": before["simulation_s"] / row["simulation_s"],
                })
            save(output, receipt)
    if any(row["speedup"] <= 1 for row in receipt["equal_work"]):
        raise ValueError("dependency candidate did not improve every measured seed")
    # This is still the same inherited aggregate deadline, not a new experiment.
    measured = linux_runs(output, receipt, SEEDS, build, audit=True,
                          cache=caches["dependency-candidate"], stem="complete-dependency",
                          profile="dependency-candidate")
    assert_coverage(output, coverage_requirements("linux", SEEDS), measured)
    receipt["complete_three_seed_feasibility"] = "scored complete within inherited deadline"
    receipt["requires_independent_evaluation"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-of", type=Path, action="append", required=True)
    parser.add_argument("--mode", choices=("contract", "measure"), default="contract")
    parser.add_argument("--cycles", type=int, default=5000000)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    if args.cycles <= 8:
        parser.error("prefix cycles must exceed reset duration")
    started = time.monotonic()
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(min(
        float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-dependency-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_dependency_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "source_sha256": {
            str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "children": [], "promoted": False,
        "complete_three_seed_feasibility": "not established",
        "scope": "Opt-in dependency-scheduling diagnostic, not mandatory acceptance.",
    }
    save(output, receipt)
    print(f"Dependency experiment: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        receipt["repair_of"] = [
            {"receipt": str(path), "sha256": digest(project_path(path))}
            for path in args.repair_of]
        for tool in ("python3", "verilator", "g++", "make"):
            record = run([tool, "--version"], output, tool + "-version", receipt)
            receipt.setdefault("tool_versions", {})[tool] = (output / record["stdout"]).read_text()
        contract(output, receipt)
        if args.mode == "measure":
            measure(output, receipt, args.cycles)
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"source changed during dependency experiment: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["duration_s"] = time.monotonic() - started
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Dependency exit={status}; {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
