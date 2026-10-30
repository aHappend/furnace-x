#!/usr/bin/env python3
"""Portable, executing L1 acceptance; default: all four mandatory suites."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment


SUITES = ("behavior", "defects", "synthesis", "portability")
SEEDS = (17, 89, 2027)


def jobs(suite):
    if suite == "behavior":
        yield "seeded-stimulus", "random_checks.py", []
        yield "host-cpu-arbitration", "mmio_arb_checks.py", []
        yield "cpu-address-map", "cpu_map_checks.py", []
        yield "running-host-restrictions", "x3_checks.py", ["--host-running"]
        yield "icarus-autonomous-engine-smoke", "x3_checks.py", ["--engines", "--preflight"]
        yield "legal-one-byte-tiles", "x3_checks.py", ["--tile-bytes", "1"]
        for seed in SEEDS:
            suffix = ["--seed", str(seed)]
            for name in ("cpu", "cpu_isa", "bridge", "adapter", "arbiter", "tensor", "lz4"):
                yield f"{name}-seed{seed}", f"{name}_checks.py", suffix
            yield f"crypto-seed{seed}", "crypto_checks.py", suffix
            for maximum in (1, 4096, 1048576):
                yield f"dma-max{maximum}-seed{seed}", "dma_checks.py", [
                    *suffix, "--maximum", str(maximum)]
            for depth in (1, 3, 16):
                for name in ("synchronization", "fusion"):
                    yield f"{name}-depth{depth}-seed{seed}", f"{name}_checks.py", [
                        *suffix, "--depth", str(depth)]
            for geometry in ("singleton", "upsample", "downsample", "large"):
                yield f"frontend-{geometry}-seed{seed}", "frontend_checks.py", [
                    *suffix, "--geometry", geometry]
            yield f"graph-domains-seed{seed}", "graph_checks.py", suffix
        for maximum in (1, 65536):
            yield f"crypto-max{maximum}", "crypto_checks.py", ["--maximum", str(maximum)]
        for cell in ("C0", "C1", "C2", "C3", "C4"):
            yield f"firmware-matrix-{cell}", "matrix_checks.py", ["--cell", cell, "--all-seeds"]
        yield "preserved-public-interfaces", "compatibility_checks.py", []
        for seed in SEEDS:
            yield f"exact-pipeline-edges-seed{seed}", "pipeline_checks.py", ["--seed", str(seed)]
            yield f"legacy-stream-ownership-seed{seed}", "x3_checks.py", [
                "--legacy-streams", "--seed", str(seed)]
    elif suite == "defects":
        yield "ten-isolated-behavioral-mutants", "defect_checks.py", []
    elif suite == "synthesis":
        yield "parameter-diagnostics-and-source-invariants", "parameter_checks.py", []
        for top in ("furnace_x1_top", "furnace_x2_top"):
            yield top, "synthesis_checks.py", ["--top", top]
        for cell in ("C0", "C1", "C2", "C3", "C4"):
            yield f"complete-x3-{cell}", "synthesis_checks.py", ["--cell", cell]
    elif suite == "portability":
        yield "fresh-source-only-reproduction", "portability_checks.py", []
    else:
        raise ValueError(f"unknown mandatory suite: {suite}")


def run(suite):
    experiment = Experiment(f"portable-l1-{suite}")
    results = []
    try:
        for name, script, arguments in jobs(suite):
            command = ["python3", f"tests/{script}", *arguments]
            try:
                output = experiment.command(command, name,
                    timeout=43200 if name == "firmware-matrix-C4" else 7200)
            except (RuntimeError, OSError) as error:
                results.append({"name": name, "argv": command, "passed": False,
                                "error": str(error)})
                print(f"L1_CHECK_FAIL {suite}/{name}: {error}", flush=True)
            else:
                results.append({"name": name, "argv": command, "passed": True,
                    "receipts": re.findall(r"evidence/preparation/[^\s]+/receipt\.json", output)})
                print(f"L1_CHECK_PASS {suite}/{name}", flush=True)
            (experiment.path / "checks.json").write_text(json.dumps(results, indent=2) + "\n")
        failed = [result["name"] for result in results if not result["passed"]]
        if failed:
            raise RuntimeError(f"mandatory {suite} checks failed: {', '.join(failed)}")
    except Exception as error:
        experiment.finish(error)
        return False
    experiment.finish()
    print(f"L1_SUITE_PASS {suite} checks={len(results)}", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, action="append",
                        help="execute a mandatory suite; repeat to select several; default: all")
    args = parser.parse_args()
    selected = args.suite or SUITES
    outcomes = [run(suite) for suite in dict.fromkeys(selected)]
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
