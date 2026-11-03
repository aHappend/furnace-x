#!/usr/bin/env python3
"""Source-bound public-pin boot diagnostic; not the mandatory Linux acceptance suite."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_scoring import score_boot
os.environ.setdefault("FURNACE_VERIFY_DEADLINE", str(time.monotonic() + 2700))

COMPILE_PROFILES = {
    "baseline": {
        "verilator": ["--output-split", "20000"],
        "optimization": "-O2",
    },
    "o3-split": {
        "verilator": ["-O3", "--output-split", "10000",
                      "--output-split-cfuncs", "10000"],
        "optimization": "-O3",
    },
    "o3-pgo": {
        "verilator": ["-O3", "--output-split", "10000",
                      "--output-split-cfuncs", "10000"],
        "optimization": "-O3",
        "pgo_training_cycles": 2000000,
    },
    "o3-pgo-fixedpoint": {
        "verilator": ["-O3", "--output-split", "10000",
                      "--output-split-cfuncs", "10000"],
        "optimization": "-O3",
        "pgo_training_cycles": 2000000,
        "generated_fixedpoint": True,
    },
    "o3-lto": {
        "verilator": ["-O3", "--output-split", "10000",
                      "--output-split-cfuncs", "10000"],
        "optimization": "-O3",
        "compiler_flags": ["-flto=2"],
        "linker_flags": ["-flto=2"],
    },
    "o3-small": {
        "verilator": ["-O3", "--output-split", "5000",
                      "--output-split-cfuncs", "1000",
                      "--gate-stmts", "1000", "--inline-mult", "0"],
        "optimization": "-O3",
    },
    "gprof": {
        "verilator": ["-O3", "--output-split", "10000",
                      "--output-split-cfuncs", "10000", "--prof-c", "--prof-cfuncs"],
        "optimization": "-O3",
    },
}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def project_path(value):
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"path must be project-relative: {value}")
    path = (ROOT / value).resolve()
    path.relative_to(ROOT)
    return path


def run(argv, output, stem, receipt, *, timeout_s=600, check=True, cwd=None):
    deadline = float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf"))
    remaining = deadline - time.monotonic()
    timeout_s = min(timeout_s, remaining)
    if timeout_s <= 0:
        raise RuntimeError("2700-second aggregate execution deadline exhausted")
    working = ROOT if cwd is None else Path(cwd).resolve()
    working.relative_to(ROOT)
    record = {
        "argv": [str(item) for item in argv], "cwd": str(working.relative_to(ROOT)),
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": timeout_s, "stdout": stem + ".stdout.txt",
        "stderr": stem + ".stderr.txt", "timed_out": False,
    }
    if any(row.get("stdout") == record["stdout"] for row in receipt["commands"]):
        raise ValueError(f"refusing to overwrite command logs: {stem}")
    receipt["commands"].append(record)
    save(output, receipt)
    with (output / record["stdout"]).open("w") as stdout, (
        output / record["stderr"]
    ).open("w") as stderr:
        child = None
        started = time.monotonic()
        try:
            child = subprocess.Popen(
                record["argv"], cwd=working, stdout=stdout, stderr=stderr,
                start_new_session=True,
            )
            while True:
                left = timeout_s - (time.monotonic() - started)
                try:
                    child.wait(timeout=max(0.001, min(25, left)))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started >= timeout_s:
                        record["timed_out"] = True
                        receipt["timed_out"] = True
                        break
                    print(f"Verification: {stem} running", flush=True)
        except OSError as error:
            record["launch_error"] = str(error)
            raise
        finally:
            if child is not None:
                # The process group is owned by this invocation, including make
                # workers and simulators spawned by nested Python entries.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                record["exit_code"] = child.returncode
            record["duration_s"] = time.monotonic() - started
            record["end_utc"] = now()
            save(output, receipt)
    if record["timed_out"]:
        raise RuntimeError(f"{stem} execution timeout; see {output.relative_to(ROOT)}")
    if check and record["exit_code"]:
        raise RuntimeError(f"{stem} exit={record['exit_code']}; see {output.relative_to(ROOT)}")
    return record


def save(output, receipt):
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--cycles", type=int, default=20000000)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--compile-profile", choices=COMPILE_PROFILES, default="baseline")
    parser.add_argument("--invocation-cache", type=Path,
                        help="Fresh cache under this invocation's output namespace")
    parser.add_argument("--audit-state", action="store_true",
                        help="Hash complete final RTL/reference/RAM state for equal-work comparison")
    parser.add_argument("--compile-only", action="store_true",
                        help="Prepare one invocation-local executable without a boot acceptance claim")
    parser.add_argument("--until-complete", action="store_true",
                        help="Run to scored completion, bounded by the inherited execution deadline")
    args = parser.parse_args()
    if args.until_complete:
        args.cycles = (1 << 63) - 1
    if args.cycles <= 8 or args.jobs < 1:
        parser.error("cycles must exceed reset duration; jobs must be positive")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    sources = sorted(
        path for directory in ("rtl", "sw", "design", "fpga", "tests")
        for path in (ROOT / directory).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and not (directory == "sw" and "build" in path.relative_to(ROOT / "sw").parts)
    )
    receipt = {
        "schema": 1, "kind": "verifier-public-pin-boot-preparation",
        "argv": ["python3", "tests/boot_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": None, "timed_out": False, "commands": [],
        "tool_versions": {}, "seed": args.seed, "cycles_limit": args.cycles,
        "compile_profile": args.compile_profile,
        "compile_configuration": COMPILE_PROFILES[args.compile_profile],
        "until_complete": args.until_complete,
        "scope": "Bounded public-pin boot diagnostic, not full behavior/Linux/defects/synthesis acceptance.",
    }
    save(output, receipt)
    for name in ("boot_probe.py", "boot_endpoint.cpp", "boot_execution_model.h",
                 "boot_workload_model.h", "boot_observers.sv", "boot_compilation.py",
                 "boot_checkpoint_state.h", "boot_scoring.py", "workload_model.py"):
        snapshot = output / "sources" / name
        snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_bytes((ROOT / "tests" / name).read_bytes())
    print(f"Boot preparation receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        if args.repair_of:
            original = project_path(args.repair_of)
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(original)
        build_path = project_path(args.build_receipt)
        build = json.loads(build_path.read_text())
        receipt["software_build_receipt"] = str(args.build_receipt)
        receipt["software_build_receipt_sha256"] = digest(build_path)
        if build["exit_code"] != 0:
            raise ValueError("software build did not complete successfully")
        for name, expected in build["source_sha256"].items():
            if name.startswith("sw/") and digest(project_path(Path(name))) != expected:
                raise ValueError(f"software changed since image build: {name}")
        images_path = build_path.parent / "system/images/images.json"
        images = json.loads(images_path.read_text())
        if images["ram"] != {"base": 0x80000000, "bytes": 0x08000000}:
            raise ValueError("boot RAM geometry mismatch")
        image_paths = []
        extents = []
        for image in images["images"]:
            path = project_path(images_path.parent.relative_to(ROOT) / image["file"])
            if digest(path) != image["sha256"] or path.stat().st_size != image["bytes"]:
                raise ValueError(f"boot image identity mismatch: {path.name}")
            low, high = image["address"], image["address"] + image["bytes"]
            if low < 0x80000000 or high > 0x88000000 or high <= low:
                raise ValueError("boot image outside RAM")
            if any(low < b and a < high for a, b in extents):
                raise ValueError("overlapping boot images")
            extents.append((low, high))
            image_paths.append(f'{low} {image["bytes"]} {path.relative_to(ROOT)}\n')
        if {image["name"] for image in images["images"]} != {
            "firmware", "kernel", "initramfs", "dtb"
        } or len(image_paths) != 4:
            raise ValueError("exactly four named boot images required")
        (output / "image-index.txt").write_text("".join(image_paths))
        receipt["image_manifest"] = str(images_path.relative_to(ROOT))
        receipt["image_manifest_sha256"] = digest(images_path)
        for tool in ("python3", "verilator", "make", "g++"):
            result = subprocess.run(
                [tool, "--version"], cwd=ROOT, text=True, capture_output=True, check=False,
            )
            receipt["tool_versions"][tool] = {
                "argv": [tool, "--version"], "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            }
            if result.returncode:
                raise RuntimeError(f"{tool} version query failed")
        from boot_compilation import build_pgo, compile_boot, reusable_boot
        if args.invocation_cache:
            cache = project_path(args.invocation_cache)
            # Child output roots and the cache share the Linux invocation root.
            cache.relative_to(project_path(args.output_root).parent)
            executable = reusable_boot(cache, output, receipt, args.jobs, args.compile_profile,
                                       audit=args.audit_state)
        elif "pgo_training_cycles" in COMPILE_PROFILES[args.compile_profile]:
            executable = build_pgo(output, receipt, args.jobs, relative / "image-index.txt",
                                   audit=args.audit_state, profile_name=args.compile_profile)
        else:
            executable = compile_boot(output, receipt, args.jobs, args.compile_profile,
                                      audit=args.audit_state)
        receipt["executable"] = str(executable)
        receipt["executable_sha256"] = digest(ROOT / executable)
        save(output, receipt)
        if args.compile_only:
            receipt["scope"] = "Compilation only; no complete-boot or workload acceptance."
            status = 0
            return 0
        simulation_argv = [
            executable, relative / "image-index.txt",
            relative / "uart.txt", str(args.cycles), str(args.seed),
            relative / "simulation-summary.txt",
            relative / "execution-measurements.json",
        ]
        if args.compile_profile == "gprof":
            simulation_argv = ["env", f"GMON_OUT_PREFIX={relative}/gmon", *simulation_argv]
        if args.audit_state:
            storage = output / "checkpoint-images"
            storage.mkdir()
            state = storage / f"final-{uuid.uuid4().hex[:8]}"
            simulation_argv = ["env", f"FURNACE_BOOT_AUDIT_DIR={state.relative_to(ROOT)}",
                               *simulation_argv]
        simulation = run(simulation_argv, output, "simulation", receipt, check=False)
        if args.audit_state:
            receipt["final_state"] = {
                name: {"sha256": digest(state / name), "bytes": (state / name).stat().st_size}
                for name in ("rtl-context.bin", "host.bin", "ram.bin")
            }
            # Retain exact identity, not a redundant 128-MiB weight/RAM dump.
            (state / "ram.bin").unlink()
        if args.compile_profile == "gprof":
            profiles = list(output.glob("gmon.*"))
            if len(profiles) != 1:
                raise ValueError("expected exactly one settled execution profile")
            receipt["execution_profile_sha256"] = digest(profiles[0])
            run(["gprof", "--version"], output, "gprof-version", receipt)
            run(["gprof", relative / "obj/Vfurnace_x4_top", profiles[0].relative_to(ROOT)],
                output, "execution-profile", receipt)
        if simulation["exit_code"]:
            raise RuntimeError(f"simulation exit={simulation['exit_code']}; see {relative}")
        measured = json.loads((output / "execution-measurements.json").read_text())
        if measured["simulation_exit"] != 0 or measured["retired"] <= 0:
            raise ValueError("missing actual instruction execution")
        scored = score_boot(measured, (output / "uart.txt").read_text())
        receipt["measurements"] = {f"seed{args.seed}.{name}": value
                                   for name, value in scored.items()}
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        measured_path = output / "execution-measurements.json"
        if measured_path.is_file():
            receipt["execution_measurements_sha256"] = digest(measured_path)
            receipt["execution_observations"] = json.loads(measured_path.read_text())
        receipt["end_utc"] = now()
        receipt["exit_code"] = status
        save(output, receipt)
        obj = output / "obj"
        if obj.is_dir():
            for path in obj.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
    print(f"Boot preparation exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
