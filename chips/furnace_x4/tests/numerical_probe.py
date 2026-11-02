#!/usr/bin/env python3
"""Exact independent FP32 leaf comparisons; not integrated tensor acceptance."""

import argparse
import datetime
import json
from pathlib import Path
import random
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from numerical_model import add, multiply, known_answers


def fixture(seed):
    special = (0, 0x80000000, 1, 0x80000001, 0x007FFFFF, 0x00800000,
               0x3F000000, 0x3F800000, 0x3F800001, 0x33800000, 0xBF800000,
               0x7F7FFFFF, 0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001)
    rng = random.Random(seed)
    pairs = [(a, b) for a in special for b in special]
    pairs.extend((rng.getrandbits(32), rng.getrandbits(32)) for _ in range(768))
    pairs.extend((rng.getrandbits(16) << 16, rng.getrandbits(16) << 16)
                 for _ in range(256))
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"numerical-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    names = (
        "tests/numerical_model.py", "tests/numerical_probe.py", "tests/fp_contract.sv",
        "tests/boot_probe.py", "rtl/furnace_fp32_mul4.sv", "rtl/furnace_fp32_add5.sv",
        "rtl/furnace_fp32_round.sv",
    )
    receipt = {
        "schema": 1, "argv": ["python3", "tests/numerical_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {name: digest(ROOT / name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [],
    }
    save(output, receipt)
    status = 1
    try:
        receipt["oracle_known_answers"] = known_answers()
        for tool, option in (("iverilog", "-V"), ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        for seed in (17, 89, 211):
            pairs = fixture(seed)
            path = output / f"vectors-{seed}.hex"
            path.write_text("".join(
                f"{a:08x}{b:08x}{multiply(a,b):08x}{add(a,b):08x}\n" for a, b in pairs
            ))
            receipt.setdefault("fixtures", {})[path.name] = digest(path)
        rtl = list(names[4:]) + ["tests/fp_contract.sv"]
        run(["iverilog", "-g2012", "-Wall", "-s", "fp_contract", "-o",
             relative / "fp.vvp", *rtl], output, "icarus-compile", receipt)
        run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
             "--top-module", "fp_contract", "--Mdir", relative / "obj", *rtl],
            output, "verilator-compile", receipt)
        for simulator, seed, count in (("icarus", 17, 64),
                                       *(("verilator", s, 1280) for s in (17, 89, 211))):
            argv = (["vvp", relative / "fp.vvp"] if simulator == "icarus" else
                    [relative / "obj/Vfp_contract"])
            stem = f"{simulator}-{seed}"
            run([*argv, f"+vectors={relative}/vectors-{seed}.hex", f"+count={count}"],
                output, stem, receipt)
            text = (output / f"{stem}.stdout.txt").read_text()
            match = re.search(r"FP_CONTRACT vectors=(\d+) comparisons=(\d+) stalls=(\d+) failures=(\d+)", text)
            if not match:
                raise ValueError(f"{stem}: comparison summary absent")
            vectors, comparisons, stalls, failures = map(int, match.groups())
            if vectors != count or comparisons < count * 2 or stalls == 0 or failures:
                raise ValueError(f"{stem}: numerical coverage assertion failed")
            receipt["runs"].append({"scope": "leaf", "simulator": simulator, "seed": seed,
                                    "vectors": vectors, "comparisons": comparisons,
                                    "stall_comparisons": stalls, "failures": failures})
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        obj = output / "obj"
        if obj.is_dir():
            for path in obj.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Numerical receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
