#!/usr/bin/env python3
"""Source-bound public-pin boot diagnostic; not the mandatory Linux acceptance suite."""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


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


def run(argv, output, stem, receipt):
    record = {
        "argv": [str(item) for item in argv], "cwd": ".",
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": None, "stdout": stem + ".stdout.txt",
        "stderr": stem + ".stderr.txt",
    }
    receipt["commands"].append(record)
    save(output, receipt)
    with (output / record["stdout"]).open("w") as stdout, (
        output / record["stderr"]
    ).open("w") as stderr:
        child = subprocess.Popen(record["argv"], cwd=ROOT, stdout=stdout, stderr=stderr)
        while child.poll() is None:
            time.sleep(1)
            if time.monotonic() - run.last_heartbeat >= 25:
                print(f"Boot preparation: {stem} running", flush=True)
                run.last_heartbeat = time.monotonic()
        record["exit_code"] = child.returncode
    record["end_utc"] = now()
    save(output, receipt)
    if record["exit_code"]:
        raise RuntimeError(f"{stem} exit={record['exit_code']}; see {output.relative_to(ROOT)}")


run.last_heartbeat = time.monotonic()


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
    args = parser.parse_args()
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
        "scope": "Bounded public-pin boot diagnostic, not full behavior/Linux/defects/synthesis acceptance.",
    }
    save(output, receipt)
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
        # Verilator resolves its C++ prerequisite relative to the generated makefile.
        # Supply a portable path from obj/ to the project test source.
        cpp_from_obj = Path(*([".."] * len((relative / "obj").parts))) / "tests/boot_endpoint.cpp"
        run([
            "verilator", "--cc", "--exe", "--build", "-j", str(args.jobs),
            "--top-module", "furnace_x4_top", "--Mdir", relative / "obj",
            "--assert", "-Wno-fatal", "--output-split", "20000",
            "-CFLAGS", "-O2 -std=c++17",
            *[str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))],
            cpp_from_obj,
        ], output, "compile", receipt)
        run([
            relative / "obj/Vfurnace_x4_top", relative / "image-index.txt",
            relative / "uart.txt", str(args.cycles), str(args.seed),
            relative / "simulation-summary.txt",
        ], output, "simulation", receipt)
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
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
