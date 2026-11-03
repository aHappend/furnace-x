#!/usr/bin/env python3
"""Exact public-interface tensor mode, pipeline, reset and protocol verification."""

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
from numerical_model import add, multiply, encode, known_answers


def fixtures(seed):
    rng = random.Random(seed)
    special = (0, 0x8000, 1, 0x8001, 0x7f, 0x80, 0x3f80, 0xbf80,
               0x7f7f, 0x7f80, 0xff80, 0x7fc0)
    rows = []

    def append(mode, first, last, weights, activations, accumulator=0, error=0):
        if error:
            expected = 0
        elif mode == 0:
            expected = (accumulator + sum(w*a for w, a in zip(weights, activations))) & ((1 << 64)-1)
        else:
            products = [multiply(w << 16 if mode == 1 else encode(int(w < 0), abs(w), 0),
                                 a << 16) for w, a in zip(weights, activations)]
            while len(products) > 1:
                products = [add(a, b) for a, b in zip(products[::2], products[1::2])]
            expected = add(accumulator, products[0])
        weight_bits = sum((w & (65535 if mode == 1 else 15)) << ((16 if mode == 1 else 4)*i)
                          for i, w in enumerate(weights))
        activation_bits = sum((a & 65535) << (16*i) for i, a in enumerate(activations))
        bits = (mode << 330) | (first << 329) | (last << 328) | (weight_bits << 200) | (
            activation_bits << 72) | (expected << 8) | error
        rows.append(bits)
        return expected

    # Compact prefix exercises all modes and separately rounded nontrivial sums.
    for mode in (0, 1, 2):
        append(mode, 1, 1, [-8,7,-1,1,2,3,4,5] if mode != 1 else [0x3f81]*8,
               [-32768,32767,-1,0,1,2,3,4] if mode == 0 else [0x3f81]*8)
    for mode in (0, 1, 2):
        accumulator = 0
        for vector in range(3):
            weights = [rng.randrange(-8, 8) if mode != 1 else rng.randrange(0x3e00, 0x4200)
                       for _ in range(8)]
            activations = [rng.randrange(-32768, 32768) if mode == 0 else
                           rng.randrange(0x3b00, 0x4300) for _ in range(8)]
            accumulator = append(mode, int(vector == 0), int(vector == 2),
                                 weights, activations, accumulator)
    append(3, 1, 1, [0]*8, [0]*8, error=6)
    append(0, 0, 1, [0]*8, [0]*8, error=6)
    append(0, 1, 0, [1]*8, [1]*8)
    append(0, 1, 1, [1]*8, [1]*8, error=6)
    append(1, 1, 0, [0x3f80]*8, [0x3f80]*8)
    append(2, 0, 1, [1]*8, [0x3f80]*8, error=6)
    append(0, 1, 1, [1]*8, [1]*8)
    rows.append(rows[-1] | (1 << 232))
    rows[-1] = (rows[-1] & ~((1 << 72)-1)) | 6
    for job in range(256):
        mode = job % 3
        accumulator = 0
        for vector in range(1 + job % 3):
            weights = [rng.randrange(-8, 8) if mode != 1 else (
                rng.choice(special) if job < 36 else rng.getrandbits(16)) for _ in range(8)]
            activations = [rng.randrange(-32768, 32768) if mode == 0 else (
                rng.choice(special) if job < 36 else rng.getrandbits(16)) for _ in range(8)]
            accumulator = append(mode, int(vector == 0), int(vector == job % 3),
                                 weights, activations, accumulator)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--mutation", choices=("tensor_rounding",))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"tensor-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    names = ("tests/tensor_probe.py", "tests/tensor_contract.sv", "tests/numerical_model.py",
             "tests/boot_probe.py", "rtl/furnace_tensor8.sv", "rtl/furnace_fp32_mul4.sv",
             "rtl/furnace_fp32_add5.sv", "rtl/furnace_fp32_round.sv")
    receipt = {
        "schema": 1, "argv": ["python3", "tests/tensor_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT / name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None, "timeout_s": 2700,
        "commands": [], "runs": [], "mutation": args.mutation, "mutant_detected": False,
        "scope": "Leaf tensor modes 0/1/2, protocol rejection, reset/stall and exact cycle comparisons",
    }
    save(output, receipt)
    status = 1
    try:
        receipt["oracle_known_answers"] = known_answers()
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        for seed in (17, 89, 211):
            vectors = fixtures(seed)
            path = output / f"vectors-{seed}.hex"
            path.write_text("".join(f"{row:083x}\n" for row in vectors))
            receipt.setdefault("fixtures", {})[path.name] = digest(path)
        rtl = list(names[4:])
        if args.mutation:
            original = (ROOT / rtl[-1]).read_text()
            before = "(significand[1] || significand[0] || significand[3])"
            if original.count(before) != 1:
                raise ValueError("rounding mutation site must be unique")
            copied = output / "furnace_fp32_round.sv"
            copied.write_text(original.replace(before, "1'b0", 1))
            rtl[-1] = str(copied.relative_to(ROOT))
            receipt["mutated_source_sha256"] = digest(copied)
        rtl.append("tests/tensor_contract.sv")
        if not args.mutation:
            run(["iverilog", "-g2012", "-Wall", "-s", "tensor_contract", "-o",
                 relative / "tensor.vvp", *rtl], output, "icarus-compile", receipt)
        run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
             "--top-module", "tensor_contract", "--Mdir", relative / "obj", *rtl],
            output, "verilator-compile", receipt)
        selection = (("verilator", 17, len(fixtures(17))),) if args.mutation else (
            ("icarus", 17, 20),
            *(("verilator", seed, len(fixtures(seed))) for seed in (17, 89, 211)))
        for simulator, seed, count in selection:
            argv = (["vvp", relative / "tensor.vvp"] if simulator == "icarus" else
                    [relative / "obj/Vtensor_contract"])
            stem = f"{simulator}-{seed}"
            result = run([*argv, f"+vectors={relative}/vectors-{seed}.hex", f"+count={count}"],
                         output, stem, receipt, check=not args.mutation)
            text = (output / f"{stem}.stdout.txt").read_text()
            if args.mutation:
                if result["exit_code"] == 0 or "MISMATCH independent balanced tensor numeric/protocol result" not in text:
                    raise ValueError("rounding mutant did not fail its intended semantic comparison")
                receipt["mutant_detected"] = True
                continue
            match = re.search(r"TENSOR_CONTRACT vectors=(\d+) results=(\d+) comparisons=(\d+) "
                              r"stalls=(\d+) resets=(\d+) failures=(\d+)", text)
            if not match:
                raise ValueError("missing tensor comparison summary")
            vectors, results, comparisons, stalls, resets, failures = map(int, match.groups())
            if vectors != count or results <= 0 or comparisons <= count*24 or (
                    stalls < results*3 or resets != 2 or failures):
                raise ValueError("tensor measured coverage/assertion failure")
            receipt["runs"].append({"scope": "leaf", "simulator": simulator, "seed": seed,
                                    "vectors": vectors, "results": results, "comparisons": comparisons,
                                    "stalls": stalls, "resets": resets, "failures": failures})
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"source changed during tensor verification: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        if (output / "obj").is_dir():
            for path in (output / "obj").iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Tensor preparation receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
