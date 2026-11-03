#!/usr/bin/env python3
"""Independently exercise actual patched OpenSBI integer decode/byte-loop semantics."""

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"firmware-integer-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    sources = [
        ROOT / "sw/dist/opensbi-v0.2.tar.gz", ROOT / "sw/sources.json",
        ROOT / "sw/opensbi/rv64ima-v0.2.patch",
        ROOT / "tests/firmware_probe.py", ROOT / "tests/boot_probe.py",
        ROOT / "tests/firmware_integer.c",
        ROOT / "tests/firmware_riscv_asm.h",
        ROOT / "tests/firmware_sbi_unpriv.h",
    ]
    receipt = {
        "schema": 1, "kind": "verifier-firmware-integer-preparation",
        "argv": ["python3", "tests/firmware_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": None, "timed_out": False, "commands": [], "tool_versions": {},
        "scope": "Native host execution of actual OpenSBI C decoder and byte loops with explicit CSR/fetch/data primitive shims; not RV64 privilege or RTL evidence.",
    }
    save(output, receipt)
    print(f"Firmware integer diagnostic: {relative}/receipt.json", flush=True)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        lock = json.loads((ROOT / "sw/sources.json").read_text())
        firmware = next(s for s in lock["sources"] if s["name"] == "opensbi")
        archive = project_path(Path(firmware["archive"]))
        if digest(archive) != firmware["sha256"]:
            raise ValueError("pinned OpenSBI archive identity mismatch")
        for tool in ("python3", "gcc", "patch"):
            result = subprocess.run(
                [tool, "--version"], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            receipt["tool_versions"][tool] = {
                "argv": [tool, "--version"], "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            }
            if result.returncode:
                raise RuntimeError(f"{tool} version query failed")
        with tarfile.open(archive, "r:gz") as bundle:
            if any(not Path(member.name).parts or Path(member.name).parts[0] !=
                   firmware["archive_root"] for member in bundle.getmembers()):
                raise ValueError("archive root mismatch")
            bundle.extractall(output / "source", filter="data")
        tree = relative / "source" / firmware["archive_root"]
        target = ROOT / tree / "lib/sbi_misaligned_ldst.c"
        receipt["upstream_handler_sha256"] = digest(target)
        patch = ROOT / "sw/opensbi/rv64ima-v0.2.patch"
        # -d changes patch's working directory; --input is resolved there.
        patch_from_tree = Path(*([".."] * len(tree.parts))) / patch.relative_to(ROOT)
        run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-d", tree,
             "--input", patch_from_tree], output, "patch", receipt)
        receipt["patched_handler_sha256"] = digest(target)
        shim = output / "shim/sbi"
        shim.mkdir(parents=True)
        for source, destination in (
            ("firmware_riscv_asm.h", "riscv_asm.h"),
            ("firmware_sbi_unpriv.h", "sbi_unpriv.h"),
        ):
            shutil.copyfile(ROOT / "tests" / source, shim / destination)
        run([
            "gcc", "-std=c11", "-O2", "-D__riscv_xlen=64",
            "-I" + str(relative / "shim"), "-I" + str(tree / "include"),
            "tests/firmware_integer.c", tree / "lib/sbi_misaligned_ldst.c",
            "-o", relative / "firmware-integer",
        ], output, "compile", receipt)
        run([relative / "firmware-integer"], output, "simulation", receipt)
        status = 0
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Firmware integer exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
