#!/usr/bin/env python3
"""Bounded, identity-checked continuation; segment success is not boot acceptance."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from boot_checkpoint_probe import identity
from boot_scoring import score_boot
from verify import sources


def generated_identity(directory):
    # These are the generated model/layout files, not host endpoint object code.
    return {p.name: digest(p) for p in directory.iterdir()
            if p.name.startswith("Vfurnace_x4_top") and p.suffix in (".h", ".cpp")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--segment-cycles", type=int, default=40000000)
    parser.add_argument("--segments", type=int, default=2)
    parser.add_argument("--reuse-executable", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    if not 1 <= args.segments <= 4 or not 1 <= args.segment_cycles <= 40000000:
        parser.error("require 1..4 segments of at most 40000000 cycles")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-continuation-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_continuation_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "timed_out": False, "commands": [], "segments": [],
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()
                          if p.parent != ROOT / "tests" or p.name.startswith("boot")
                          or p.name in ("verify.py", "workload_model.py")},
        "scope": "Measured continuation; incomplete segments are not successful Linux boots.",
    }
    save(output, receipt)
    print(f"Continuation receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        previous_path = project_path(args.predecessor)
        previous = json.loads(previous_path.read_text())
        if previous["exit_code"] != 0:
            raise ValueError("predecessor diagnostic failed")
        state = project_path(args.state)
        matches = [s for s in previous["segments"] if s["state"] == str(args.state)]
        if len(matches) != 1 or identity(state) != matches[0]["identity"]:
            raise ValueError("checkpoint identity does not match predecessor receipt")
        prior = matches[0]
        receipt.update(predecessor=str(args.predecessor),
                       predecessor_sha256=digest(previous_path), seed=previous["seed"])
        # Host code may add completion/measurement orchestration, but the
        # serialized endpoint, reference models, observer and all RTL are exact.
        required = [p for p in previous["source_sha256"] if p.startswith("rtl/")]
        required += ["tests/" + name for name in (
            "boot_endpoint.cpp", "boot_execution_model.h", "boot_workload_model.h",
            "boot_checkpoint_state.h", "boot_observers.sv")]
        for name in required:
            if digest(ROOT / name) != previous["source_sha256"][name]:
                raise ValueError(f"checkpoint-incompatible source: {name}")
        build_path = project_path(Path(previous["software_build_receipt"]))
        if digest(build_path) != previous["software_build_receipt_sha256"]:
            raise ValueError("software build receipt changed")
        build = json.loads(build_path.read_text())
        if build["exit_code"]:
            raise ValueError("software build failed")
        for name, value in build["source_sha256"].items():
            if name.startswith("sw/") and digest(ROOT / name) != value:
                raise ValueError(f"software source changed: {name}")
        manifest_path = project_path(Path(previous["image_manifest"]))
        if digest(manifest_path) != previous["image_manifest_sha256"]:
            raise ValueError("image manifest changed")
        manifest = json.loads(manifest_path.read_text())
        if manifest["ram"] != {"base": 0x80000000, "bytes": 0x08000000}:
            raise ValueError("128-MiB RAM geometry required")
        lines, extents = [], []
        for image in manifest["images"]:
            path = manifest_path.parent / image["file"]
            path.resolve().relative_to(ROOT)
            if digest(path) != image["sha256"] or path.stat().st_size != image["bytes"]:
                raise ValueError("boot image identity mismatch")
            lo, hi = image["address"], image["address"] + image["bytes"]
            if not 0x80000000 <= lo < hi <= 0x88000000 or any(
                    lo < b and a < hi for a, b in extents):
                raise ValueError("image range or overlap")
            extents.append((lo, hi))
            lines.append(f'{lo} {image["bytes"]} {path.relative_to(ROOT)}\n')
        if len(lines) != 4 or {i["name"] for i in manifest["images"]} != {
                "firmware", "kernel", "initramfs", "dtb"}:
            raise ValueError("four named actual boot images required")
        (output / "image-index.txt").write_text("".join(lines))
        for key in ("software_build_receipt", "software_build_receipt_sha256",
                    "image_manifest", "image_manifest_sha256"):
            receipt[key] = previous[key]
        receipt["ram"] = manifest["ram"]
        compile_rows = [c for c in previous["commands"]
                        if c["argv"][0] == "verilator" and "--cc" in c["argv"]]
        if not compile_rows and "compilation" in previous:
            compile_rows = [previous["compilation"]]
        if len(compile_rows) != 1 or compile_rows[0]["exit_code"]:
            raise ValueError("predecessor compilation provenance missing")
        old_command = compile_rows[0]["argv"]
        old_obj = project_path(Path(old_command[old_command.index("--Mdir") + 1]))
        old_executable = old_obj / "Vfurnace_x4_top"
        old_identity = generated_identity(old_obj)
        if not old_identity:
            raise ValueError("missing predecessor generated model")
        old_executable_identity = digest(old_executable)
        if previous.get("executable_sha256", old_executable_identity) != old_executable_identity:
            raise ValueError("predecessor executable identity changed")
        receipt["predecessor_executable"] = {
            "path": str(old_executable.relative_to(ROOT)), "sha256": old_executable_identity,
            "generated_model_sha256": old_identity,
            "historical_hash_available": "executable_sha256" in previous,
        }
        for tool in ("python3", "verilator", "make", "g++"):
            run([tool, "--version"], output, tool + "-version", receipt)
        old_version = previous_path.parent / "verilator-version.stdout.txt"
        if old_version.read_bytes() != (output / "verilator-version.stdout.txt").read_bytes():
            raise ValueError("Verilator version changed across checkpoint")
        snapshots = output / f"sources-{uuid.uuid4().hex[:8]}"
        snapshots.mkdir()
        for path in (ROOT / "tests").glob("boot*"):
            if path.is_file():
                (snapshots / path.name).write_bytes(path.read_bytes())
        if args.reuse_executable:
            if "executable_sha256" not in previous or any(
                    previous["source_sha256"].get("tests/" + name) != digest(ROOT / "tests" / name)
                    for name in ("boot_checkpoint_endpoint.cpp", "boot_checkpoint_state.h",
                                 "boot_endpoint.cpp", "boot_execution_model.h",
                                 "boot_workload_model.h", "boot_observers.sv")):
                raise ValueError("reusable executable lacks exact source/hash provenance")
            obj = old_obj.relative_to(ROOT)
            receipt["compilation"] = compile_rows[0]
            receipt["reused_executable"] = True
        else:
            obj = relative / f"obj-{uuid.uuid4().hex[:8]}"
            command = list(old_command)
            command[command.index("--Mdir") + 1] = str(obj)
            command[-1] = str(Path(*([".."] * len(obj.parts))) / "tests/boot_checkpoint_endpoint.cpp")
            run(command, output, "compile", receipt)
        if generated_identity(ROOT / obj) != old_identity:
            raise ValueError("generated RTL/serialization layout differs from predecessor")
        executable = obj / "Vfurnace_x4_top"
        receipt["executable_sha256"] = digest(ROOT / executable)
        receipt["generated_model_sha256"] = old_identity
        storage = output / "checkpoint-images"
        storage.mkdir()
        for number in range(args.segments):
            for name, value in receipt["source_sha256"].items():
                if digest(ROOT / name) != value:
                    raise ValueError(f"source changed before restoration: {name}")
            for image in manifest["images"]:
                if digest(manifest_path.parent / image["file"]) != image["sha256"]:
                    raise ValueError("image changed before restoration")
            before = identity(state)
            if before != prior["identity"]:
                raise ValueError("checkpoint changed before restoration")
            if digest(ROOT / executable) != receipt["executable_sha256"]:
                raise ValueError("executable changed before restoration")
            folder = storage / f"segment-{number}-{uuid.uuid4().hex[:8]}"
            folder.mkdir()
            final = storage / f"state-{uuid.uuid4().hex[:8]}"
            end = prior["metrics"]["end_cycle"] + args.segment_cycles
            record = run([executable, relative / "image-index.txt", folder.relative_to(ROOT),
                          str(end), str(receipt["seed"]), state.relative_to(ROOT),
                          final.relative_to(ROOT), "-", "0"],
                         output, f"segment-{number}", receipt)
            if identity(state) != before:
                raise ValueError("restoration modified predecessor checkpoint")
            roundtrip = folder / f"roundtrip-{folder.name}"
            if identity(roundtrip) != before:
                raise ValueError("immediate restored state differs from predecessor")
            metrics_path = folder / "metrics.json"
            metrics = json.loads(metrics_path.read_text())
            if metrics["start_cycle"] != prior["metrics"]["end_cycle"] or (
                    metrics["context_time"] != metrics["end_cycle"] * 10):
                raise ValueError("cycle continuity violated")
            if metrics["retired"] <= prior["metrics"]["retired"]:
                raise ValueError("no instruction progress")
            measured_path = folder / "execution-measurements.json"
            measured = json.loads(measured_path.read_text())
            scored = {}
            if metrics["complete_boot"]:
                if metrics["outcome"] != "complete":
                    raise ValueError("inconsistent completion state")
                scored = score_boot(measured, (folder / "uart.txt").read_text())
            elif metrics["outcome"] != "continuation" or measured["simulation_exit"] != 1:
                raise ValueError("partial segment claimed successful boot")
            row = {
                "state": str(final.relative_to(ROOT)), "identity": identity(final),
                "restored_from": str(state.relative_to(ROOT)), "restored_identity": before,
                "metrics": metrics, "metrics_path": str(metrics_path.relative_to(ROOT)),
                "metrics_sha256": digest(metrics_path),
                "observations": measured, "measurements_sha256": digest(measured_path),
                "duration_s": record["duration_s"], "scored_coverage": scored,
            }
            receipt["segments"].append(row)
            save(output, receipt)
            state, prior = final, row
            if metrics["complete_boot"]:
                break
        elapsed = sum(s["duration_s"] for s in receipt["segments"])
        cycles = sum(s["metrics"]["end_cycle"] - s["metrics"]["start_cycle"]
                     for s in receipt["segments"])
        endpoint = receipt["segments"][-1]["metrics"]
        receipt["cost"] = {
            "measured_simulation_s": elapsed, "measured_cycles": cycles,
            "seconds_per_million_cycles": elapsed * 1e6 / cycles,
            "complete_boot": bool(endpoint["complete_boot"]),
            "three_seed_simulation_projection_s": elapsed / cycles * endpoint["end_cycle"] * 3,
            "projection_is_lower_bound": not bool(endpoint["complete_boot"]),
            "compilation_s": sum(c["duration_s"] for c in receipt["commands"]
                                 if c["stdout"] == "compile.stdout.txt"),
            "limitation": "No aggregate saving from sharding; projection excludes software build.",
        }
        for name, value in receipt["source_sha256"].items():
            if digest(ROOT / name) != value:
                raise ValueError(f"source changed during diagnostic: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
        for directory in output.glob("obj-*"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
    print(f"Continuation exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
