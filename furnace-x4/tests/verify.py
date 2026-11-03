#!/usr/bin/env python3
"""Portable L1 entrypoint. A diagnostic pass never substitutes for suite coverage.

CPU-driven workloads, numerical/boundary checks and semantic mutants are wired.
Cache/controller, buffered-coherence and ordinary architectural fault checks keep
separate scope from full-top containment. Complete Linux execution is not established.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


SOURCE_DIRS = (
    "rtl", "tests", "design", "sw", "fpga",
    "furnace_x3_reference/rtl", "hammer_v4_reference/rtl",
)
SEEDS = (17, 89, 211)


def sources():
    return sorted(
        p for directory in SOURCE_DIRS for p in (ROOT / directory).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
        and not (directory == "sw" and "build" in p.relative_to(ROOT / "sw").parts)
    )


def child_probe(script, args, output, receipt, stem, *, on_receipt=None):
    child_root = output / f"{stem}-{uuid.uuid4().hex[:8]}"
    child_root.mkdir()
    record = run(["python3", f"tests/{script}", "--output-root",
                  child_root.relative_to(ROOT), *args], output, stem, receipt,
                 timeout_s=2700, check=False)
    found = list(child_root.glob("*/receipt.json"))
    if len(found) != 1:
        raise ValueError(f"{stem}: expected exactly one fresh child receipt")
    path = found[0]
    child = json.loads(path.read_text())
    receipt.setdefault("children", []).append({
        "receipt": str(path.relative_to(ROOT)), "sha256": digest(path),
    })
    save(output, receipt)
    for name, expected in child["source_sha256"].items():
        if digest(project_path(Path(name))) != expected:
            raise ValueError(f"{stem}: source changed during execution: {name}")
    if on_receipt is not None:
        on_receipt(child)
    if child["exit_code"] != 0 or record["exit_code"] != 0:
        raise ValueError(f"{stem}: child receipt records failure")
    return path, child


def adapters(output, receipt):
    rows = []
    for kind, marker in (("mmio", "MMIO_CONTRACT"), ("cpu", "CPU_ADAPTER_CONTRACT")):
        path, child = child_probe(
            "adapter_probe.py", ["--adapter", kind], output, receipt, f"adapter-{kind}",
        )
        for simulator in ("icarus", "verilator"):
            log = path.parent / f"{simulator}-simulation.stdout.txt"
            matches = re.findall(rf"^{marker} (.+)$", log.read_text(), re.MULTILINE)
            if len(matches) != 1:
                raise ValueError(f"{kind}/{simulator}: missing unique comparison summary")
            counters = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", matches[0])}
            if counters["comparisons"] <= 0 or counters["failures"] != 0:
                raise ValueError(f"{kind}/{simulator}: invalid comparison counters")
            rows.append({"scope": "leaf", "adapter": kind, "simulator": simulator,
                         "receipt": str(path.relative_to(ROOT)), **counters})
    return rows


def coverage_requirements(suite, seeds):
    if suite == "behavior":
        per_seed = {
            "lz4_aes_tensor_submissions": 16, "vision_audio_fusion_submissions": 16,
            "dma_taskgraph_submissions": 16, "mmio_compared": 256,
            "cpu_ddr_compared": 256, "fabric_ddr_compared": 256,
            "semaphore_positions": 16, "mailbox_positions": 4,
            "irq_source_positions": 16, "dirty_cpu_to_dma": 1,
            "dma_to_cached_cpu": 1, "partial_dirty_preserved": 1,
            "fence_i": 1, "sfence_vma": 1, "lr_sc_invalidation": 1,
            "amo_dma_exclusion": 1,
        }
    elif suite == "linux":
        per_seed = {
            "complete_boot": 1, "m_mode": 1, "s_mode": 1, "u_mode": 1,
            "sv39_walk": 1, "timer_irq": 1, "plic_claim_complete": 1,
            "permission_fault": 1, "cross_page_mapping": 1,
            "lz4_aes_tensor_submissions": 16, "vision_audio_fusion_submissions": 16,
            "dma_taskgraph_submissions": 16,
        }
    else:
        per_seed = {}
    return {f"seed{seed}.{name}": minimum for seed in seeds
            for name, minimum in per_seed.items()}


def write_coverage(output, required, measured):
    ledger = [
        {"bin": name, "required": minimum, "observed": measured.get(name, 0),
         "unit": "independently compared public events"}
        for name, minimum in required.items()
    ]
    (output / "coverage.json").write_text(json.dumps(ledger, indent=2) + "\n")
    return ledger


def assert_coverage(output, required, measured):
    ledger = write_coverage(output, required, measured)
    failed = [row for row in ledger if row["observed"] < row["required"]]
    if failed:
        raise ValueError("coverage assertion failed: " + "; ".join(
            f'{r["bin"]} observed={r["observed"]} required={r["required"]}'
            for r in failed
        ))


def software(output, receipt):
    # Each invocation builds from the pinned archives, not an earlier binary.
    path, _ = child_probe("software_build.py", [], output, receipt, "software")
    return path


def behavior(output, receipt, seeds):
    receipt["leaf_comparisons"] = adapters(output, receipt)
    child_probe("firmware_probe.py", [], output, receipt, "firmware")
    child_probe("numerical_probe.py", [], output, receipt, "numerical")
    child_probe("tensor_probe.py", [], output, receipt, "tensor")
    child_probe("stream_boundary_probe.py", [], output, receipt, "stream-boundary")
    child_probe("queue_boundary_probe.py", [], output, receipt, "queue-boundary")
    child_probe("tile_boundary_probe.py", [], output, receipt, "tile-boundary")
    child_probe("dma_boundary_probe.py", [], output, receipt, "dma-boundary")
    child_probe("top_configuration_probe.py", [], output, receipt, "top-configuration")
    child_probe("cache_fault_probe.py", [], output, receipt, "cache-fault")
    child_probe("cache_controller_probe.py", [], output, receipt, "cache-controller")
    child_probe("ordinary_fault_probe.py", [], output, receipt, "ordinary-fault")
    child_probe("coherence_fault_probe.py", [], output, receipt, "coherence-fault")
    child_probe("fulltop_fault_probe.py", [], output, receipt, "fulltop-fault")
    _, child = child_probe("integrated_probe.py", ["--seeds", ",".join(map(str, seeds))],
                           output, receipt, "integrated")
    _, leaf = child_probe("interrupt_probe.py", [], output, receipt, "interrupt")
    receipt["coverage_scopes"] = {"irq_source_positions": "leaf public aggregator source interface"}
    measured = dict(child["measurements"])
    measured.update(leaf["measurements"])
    assert_coverage(output, coverage_requirements("behavior", seeds), measured)


def linux_runs(output, receipt, seeds, build, *, cycles=None, audit=False,
               cache=None, stem="boot", profile="o3-pgo-fixedpoint", logical=False):
    """One local compilation, then disjoint processes with one inherited deadline."""
    measured = {}
    cache = output / f"boot-executable-{uuid.uuid4().hex[:8]}" if cache is None else cache
    common = [
        "--build-receipt", str(build.relative_to(ROOT)),
        "--compile-profile", profile,
        "--invocation-cache", str(cache.relative_to(ROOT)),
        *(["--audit-state"] if audit else []),
        *(["--logical-state"] if logical else []),
    ]
    child_probe("boot_probe.py", [*common, "--compile-only"],
                output, receipt, stem + "-compilation")
    manifest_path = cache / "executable.json"
    manifest_hash = digest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    receipt["boot_compilation_manifest"] = {
        "path": str(manifest_path.relative_to(ROOT)), "sha256": manifest_hash,
        "executable_sha256": manifest["sha256"],
    }
    save(output, receipt)

    def launch(seed):
        root = output / f"{stem}-{seed}-{uuid.uuid4().hex[:8]}"
        root.mkdir()
        launcher = {
            "schema": 1, "commands": [], "cwd": ".", "start_utc": now(),
            "source_sha256": receipt["source_sha256"], "seed": seed,
            "end_utc": None, "exit_code": None,
        }
        try:
            record = run([
                "python3", "tests/boot_probe.py", "--output-root", root.relative_to(ROOT),
                *common, "--seed", str(seed),
                *(["--cycles", str(cycles)] if cycles is not None else ["--until-complete"]),
            ], root, "launcher", launcher, timeout_s=2700, check=False)
            launcher["exit_code"] = record["exit_code"]
        finally:
            launcher["end_utc"] = now()
            if launcher["exit_code"] is None:
                launcher["exit_code"] = 1
            save(root, launcher)
        paths = list(root.glob("boot-*/receipt.json"))
        if len(paths) != 1:
            raise ValueError(f"seed{seed}: missing unique boot receipt")
        return seed, root, paths[0], json.loads(paths[0].read_text())

    failures, runs = [], []
    with ThreadPoolExecutor(max_workers=len(seeds)) as workers:
        futures = {workers.submit(launch, seed): seed for seed in seeds}
        for future in as_completed(futures):
            seed = futures[future]
            try:
                seed, root, path, child = future.result()
                for retained in (root / "receipt.json", path):
                    receipt.setdefault("children", []).append({
                        "receipt": str(retained.relative_to(ROOT)), "sha256": digest(retained),
                    })
                runs.append({"seed": seed, "receipt": str(path.relative_to(ROOT))})
                for name, expected in child["source_sha256"].items():
                    if digest(project_path(Path(name))) != expected:
                        raise ValueError(f"seed{seed}: source changed: {name}")
                reuse = child.get("executable_reuse", {})
                if reuse.get("compiled") is not False or (
                        child.get("executable_sha256") != manifest["sha256"]):
                    raise ValueError(f"seed{seed}: executable was not identically reused")
                measured.update({f"seed{seed}.{name}": value for name, value in
                                 child.get("execution_observations", {}).get("coverage", {}).items()
                                 if name != "complete_boot" or child["exit_code"] == 0})
                measured.update(child.get("measurements", {}))
                write_coverage(output, coverage_requirements("linux", seeds), measured)
                if child["exit_code"]:
                    failures.append(f"seed{seed}: boot exit={child['exit_code']}")
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                failures.append(f"seed{seed}: {error}")
            receipt["boot_runs"] = sorted(runs, key=lambda row: row["seed"])
            save(output, receipt)
    if digest(manifest_path) != manifest_hash:
        raise ValueError("invocation-local executable manifest changed during seed execution")
    if failures:
        raise ValueError("; ".join(failures))
    return measured


def linux(output, receipt, seeds):
    child_probe("boot_model_probe.py", [], output, receipt, "boot-oracle-unit")
    build = software(output, receipt)
    measured = linux_runs(output, receipt, seeds, build)
    assert_coverage(output, coverage_requirements("linux", seeds), measured)


def defects(output, receipt):
    child_probe("mutation_probe.py", [], output, receipt, "mutations")


def synthesis(output, receipt):
    child_probe("synthesis_probe.py", ["--frontend", "auto"],
                output, receipt, "synthesis")


def portability(output, receipt):
    clean = output / f"clean-{uuid.uuid4().hex[:8]}"
    clean.mkdir()
    for path in sources():
        destination = clean / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    copied = {str(p.relative_to(clean)): digest(p) for p in clean.rglob("*")
              if p.is_file()}
    if copied != receipt["source_sha256"]:
        raise ValueError("clean-directory source identity mismatch")
    child_receipt = {
        "schema": 1, "cwd": ".", "source_sha256": copied, "commands": [],
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700,
        "scope": "Fresh software build, compact dual-simulator adapter and real CPU heterogeneous transaction",
    }
    save(clean, child_receipt)
    try:
        run(["python3", "tests/software_build.py", "--output-root", "evidence",
             "--jobs", "2"], clean, "software-build", child_receipt, cwd=clean)
        run(["python3", "tests/adapter_probe.py", "--adapter", "mmio",
             "--output-root", "evidence"], clean, "rtl-startup", child_receipt, cwd=clean)
        run(["python3", "tests/integrated_probe.py", "--seeds", "17",
             "--stop-phase", "4", "--output-root", "evidence"],
            clean, "rtl-reproduction", child_receipt, timeout_s=2700, cwd=clean)
        integrated = list((clean/"evidence").glob("integrated-*/receipt.json"))
        if len(integrated) != 1:
            raise ValueError("clean reproduction missing unique integrated receipt")
        observed = json.loads(integrated[0].read_text())
        if observed["exit_code"] or len(observed["runs"]) != 1 or (
                observed["runs"][0]["observed"]["coverage"].get(
                    "lz4_aes_tensor_submissions", 0) < 1):
            raise ValueError("clean reproduction omitted actual heterogeneous comparison")
        for name, expected in copied.items():
            if digest(clean/name) != expected:
                raise ValueError(f"clean reproduction modified a delivered source: {name}")
        child_receipt["exit_code"] = 0
    finally:
        if child_receipt["exit_code"] is None:
            child_receipt["exit_code"] = 1
        child_receipt["end_utc"] = now()
        save(clean, child_receipt)
        receipt["clean_receipt"] = str((clean / "receipt.json").relative_to(ROOT))
        receipt["clean_receipt_sha256"] = digest(clean / "receipt.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=(
        "behavior", "linux", "defects", "synthesis", "portability",
    ))
    parser.add_argument("--seeds", default="17,89,211")
    parser.add_argument("--output-root", type=Path, default=Path("evidence"))
    args = parser.parse_args()
    try:
        seeds = tuple(int(seed) for seed in args.seeds.split(","))
        if seeds != SEEDS:
            raise ValueError("required seed sequence is 17,89,211")
        root = project_path(args.output_root)
    except ValueError as error:
        parser.error(str(error))
    inherited = float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf"))
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(min(inherited, time.monotonic() + 2700))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / f"{args.suite}-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "suite": args.suite,
        "argv": ["python3", "tests/verify.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "start_utc": now(), "end_utc": None, "timeout_s": 2700,
        "timed_out": False, "exit_code": None, "commands": [], "seeds": seeds,
    }
    save(output, receipt)
    if args.suite in ("behavior", "linux"):
        write_coverage(output, coverage_requirements(args.suite, seeds), {})
    print(f"L1 {args.suite}: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        if args.suite in ("behavior", "linux"):
            globals()[args.suite](output, receipt, seeds)
        else:
            globals()[args.suite](output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError(f"source changed during suite execution: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    return status


if __name__ == "__main__":
    sys.exit(main())
