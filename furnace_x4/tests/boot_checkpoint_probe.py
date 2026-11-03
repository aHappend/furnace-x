#!/usr/bin/env python3
"""Lossless five-million-cycle checkpoint diagnostic; never Linux acceptance."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import COMPILE_PROFILES, ROOT, digest, now, project_path, run, save
from verify import sources


def identity(directory):
    return {name: {"sha256": digest(directory / name),
                   "bytes": (directory / name).stat().st_size}
            for name in ("rtl-context.bin", "host.bin", "ram.bin")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"checkpoint-equivalence-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_checkpoint_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "timed_out": False, "commands": [], "seed": 17,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "tool_versions": {}, "checkpoint_links": [], "comparisons": [],
        "scope": "Continuation equivalence only; no boot, synthesis, timing or HIL acceptance",
        "excluded_nondeterministic_state": [
            "elapsed-time phase/retirement profiling", "host stream handles",
            "callbacks and DPI pointers (rebound to fresh objects)",
        ],
    }
    save(output, receipt)
    print(f"Checkpoint preparation receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        build_path = project_path(args.build_receipt)
        build = json.loads(build_path.read_text())
        if build["exit_code"] != 0:
            raise ValueError("software build was not successful")
        for name, expected in build["source_sha256"].items():
            if name.startswith("sw/") and digest(project_path(Path(name))) != expected:
                raise ValueError(f"software changed since build: {name}")
        images_path = build_path.parent / "system/images/images.json"
        manifest = json.loads(images_path.read_text())
        if manifest["ram"] != {"base": 0x80000000, "bytes": 0x08000000}:
            raise ValueError("128-MiB RAM geometry required")
        lines, extents = [], []
        for image in manifest["images"]:
            path = project_path(images_path.parent.relative_to(ROOT) / image["file"])
            if digest(path) != image["sha256"] or path.stat().st_size != image["bytes"]:
                raise ValueError("image identity mismatch")
            lo, hi = image["address"], image["address"] + image["bytes"]
            if not 0x80000000 <= lo < hi <= 0x88000000 or any(
                    lo < b and a < hi for a, b in extents):
                raise ValueError("image range or overlap")
            extents.append((lo, hi))
            lines.append(f'{lo} {image["bytes"]} {path.relative_to(ROOT)}\n')
        if len(lines) != 4 or {i["name"] for i in manifest["images"]} != {
                "firmware", "kernel", "initramfs", "dtb"}:
            raise ValueError("four actual boot images required")
        (output / "image-index.txt").write_text("".join(lines))
        receipt.update(software_build_receipt=str(args.build_receipt),
                       software_build_receipt_sha256=digest(build_path),
                       image_manifest=str(images_path.relative_to(ROOT)),
                       image_manifest_sha256=digest(images_path), ram=manifest["ram"])
        for tool in ("python3", "verilator", "make", "g++"):
            record = run([tool, "--version"], output, tool + "-version", receipt)
            receipt["tool_versions"][tool] = (output / record["stdout"]).read_text()
        snapshots = output / f"sources-{uuid.uuid4().hex[:8]}"
        snapshots.mkdir()
        for path in (ROOT / "tests").glob("boot*"):
            if path.is_file():
                (snapshots / path.name).write_bytes(path.read_bytes())
        profile = COMPILE_PROFILES["o3-split"]
        obj = relative / f"obj-{uuid.uuid4().hex[:8]}"
        cpp = Path(*([".."] * len(obj.parts))) / "tests/boot_checkpoint_endpoint.cpp"
        run(["verilator", "--cc", "--exe", "--build", "--savable",
             "-j", str(args.jobs), "--top-module", "furnace_x4_top", "--Mdir", obj,
             "--assert", "-Wno-fatal", *profile["verilator"], "-MAKEFLAGS",
             "OPT_FAST=-O3 OPT_SLOW=-O3 OPT_GLOBAL=-O3", "-CFLAGS", "-O3 -std=c++17",
             *[p.relative_to(ROOT) for p in sorted((ROOT / "rtl").glob("*.sv"))],
             "tests/boot_observers.sv", cpp], output, "compile", receipt)
        storage = output / "checkpoint-images"
        storage.mkdir()
        event = storage / f"pending-uart-{uuid.uuid4().hex[:8]}"
        executable = obj / "Vfurnace_x4_top"

        def segment(name, end, restore=None, cut=0, capture_event=False):
            folder = storage / f"{name}-{uuid.uuid4().hex[:8]}"
            folder.mkdir()
            final = storage / f"state-{uuid.uuid4().hex[:8]}"
            if restore:
                before = identity(restore)
                receipt["checkpoint_links"].append({
                    "restore": str(restore.relative_to(ROOT)), "identity": before,
                    "consumer": str(folder.relative_to(ROOT)),
                })
            command = run([
                executable, relative / "image-index.txt", folder.relative_to(ROOT),
                str(end), "17", restore.relative_to(ROOT) if restore else "-",
                final.relative_to(ROOT), event.relative_to(ROOT) if capture_event else "-",
                str(cut),
            ], output, name, receipt)
            metrics = json.loads((folder / "metrics.json").read_text())
            if metrics["outcome"] != "continuation" or metrics["complete_boot"]:
                raise ValueError("segment must not claim boot success")
            if restore:
                if identity(restore) != before:
                    raise ValueError("restore modified a retained checkpoint")
                roundtrip = folder / f"roundtrip-{folder.name}"
                compare(restore, roundtrip, name + "-immediate-roundtrip")
            row = {"name": name, "metrics": metrics,
                   "metrics_path": str((folder / "metrics.json").relative_to(ROOT)),
                   "metrics_sha256": digest(folder / "metrics.json"),
                   "state": str(final.relative_to(ROOT)), "identity": identity(final),
                   "duration_s": command["duration_s"]}
            receipt.setdefault("segments", []).append(row)
            save(output, receipt)
            return folder, final, metrics

        def compare(left, right, name):
            a, b = identity(left), identity(right)
            row = {"name": name, "left": str(left.relative_to(ROOT)),
                   "right": str(right.relative_to(ROOT)), "left_identity": a,
                   "right_identity": b, "identical": a == b}
            receipt["comparisons"].append(row)
            save(output, receipt)
            if a != b:
                raise ValueError(f"{name}: checkpoint logical state differs")

        baseline_folder, baseline, original = segment(
            "uninterrupted", 5000000, cut=2500000, capture_event=True)
        if not event.is_dir() or not 8 < original["event_cycle"] < 5000000:
            raise ValueError("no actual pending-DDR and active-UART checkpoint")
        first_folder, first, half = segment("first-half", 2500000)
        compare(baseline_folder / f"cut-{baseline_folder.name}", first, "first-2500000")
        split_folder, split, restored = segment("restored-second-half", 5000000, first)
        event_folder, event_final, active = segment("restored-pending-uart", 5000000, event)
        if restored["start_cycle"] != 2500000 or half["end_cycle"] != 2500000:
            raise ValueError("two exact 2.5-million-cycle segments required")
        if not active["restored_pending"] or not active["restored_uart_active"]:
            raise ValueError("restoration did not exercise pending DDR and active UART")
        if active["start_cycle"] != original["event_cycle"]:
            raise ValueError("active checkpoint cycle changed")
        for name, folder, state, observed in (
                ("two-segment-final", split_folder, split, restored),
                ("pending-uart-final", event_folder, event_final, active)):
            compare(baseline, state, name)
            if (baseline_folder / "uart.txt").read_bytes() != (folder / "uart.txt").read_bytes():
                raise ValueError(f"{name}: UART byte mismatch")
            for field in ("end_cycle", "context_time", "retired", "equal_comparisons",
                          "require_comparisons", "output_bytes_compared", "uart_bytes", "coverage"):
                if original[field] != observed[field]:
                    raise ValueError(f"{name}: {field} mismatch")
        if original["retired"] <= 0 or original["equal_comparisons"] <= 0 or original["uart_bytes"] <= 0:
            raise ValueError("empty equivalence witness")
        elapsed = (half["elapsed_ns"] + restored["elapsed_ns"]) / 1e9
        overhead = sum(v["save_ns"] + v["load_ns"] for v in (half, restored)) / 1e9
        receipt["cost"] = {
            "split_five_million_s": elapsed, "split_serialization_s": overhead,
            "uninterrupted_five_million_s": original["elapsed_ns"] / 1e9,
            "three_seeds_per_million_cycles_s": 3 * (elapsed - overhead) / 5,
            "three_seed_52_million_lower_bound_s": 3 * (elapsed - overhead) * 52 / 5,
            "complete_boot_projection": None,
            "limitation": "No complete-boot cycle count established; sharding does not reduce aggregate compute.",
        }
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError(f"source changed during diagnostic: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
        for folder in output.glob("obj-*"):
            for path in folder.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
    print(f"Checkpoint preparation exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
