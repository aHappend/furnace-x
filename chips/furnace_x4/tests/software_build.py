#!/usr/bin/env python3
"""Retain a source-bound software-build diagnostic without claiming RTL execution."""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import run


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    if (args.output_root.is_absolute() or ".." in args.output_root.parts
            or args.jobs < 1):
        parser.error("output root must be project-relative; jobs must be positive")
    if args.repair_of and not (ROOT / args.repair_of).is_file():
        parser.error("repair receipt must exist")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / args.output_root / f"software-build-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative_output = output.relative_to(ROOT)
    sources = sorted(
        path for directory in ("sw", "rtl", "design", "fpga", "tests")
        for path in (ROOT / directory).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and not (directory == "sw" and "build" in path.relative_to(ROOT / "sw").parts)
    )
    argv = [
        "python3", "sw/build_system.py", "--output",
        str(relative_output / "system"), "--jobs", str(args.jobs),
    ]
    receipt = {
        "schema": 1,
        "kind": "verifier-software-build-preparation",
        "argv": argv,
        "cwd": ".",
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
        "start_utc": now(),
        "end_utc": None,
        "timeout_s": None,
        "timed_out": False,
        "exit_code": None,
        "stdout": "build.stdout.txt",
        "stderr": "build.stderr.txt",
        "tool_versions": {},
        "commands": [],
        "scope": "Software build only; no simulation, Linux boot, or synthesis result.",
    }
    if args.repair_of:
        receipt["repair_of"] = str(args.repair_of)
        receipt["repair_receipt_sha256"] = sha256(ROOT / args.repair_of)
    receipt_path = output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Software build diagnostic: {relative_output}/receipt.json", flush=True)
    exit_code = 1
    try:
        with (output / "tool-versions.stdout.txt").open("w") as versions_out, (
            output / "tool-versions.stderr.txt"
        ).open("w") as versions_err:
            for tool in (
                "python3", "make", "riscv64-unknown-elf-gcc",
                "riscv64-linux-gnu-gcc", "dtc",
            ):
                version_argv = [tool, "--version"]
                result = subprocess.run(
                    version_argv, cwd=ROOT, text=True, capture_output=True, check=False,
                )
                versions_out.write(f"$ {' '.join(version_argv)}\n{result.stdout}")
                versions_err.write(f"$ {' '.join(version_argv)}\n{result.stderr}")
                receipt["tool_versions"][tool] = {
                    "argv": version_argv, "exit_code": result.returncode,
                    "stdout": result.stdout, "stderr": result.stderr,
                }
                if result.returncode:
                    raise RuntimeError(f"tool version query failed: {tool}")
        run(argv, output, "build", receipt)
        exit_code = 0
    except (OSError, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["end_utc"] = now()
        receipt["exit_code"] = exit_code
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Software build exit={exit_code}; receipt={relative_output}/receipt.json", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
