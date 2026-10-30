"""Bounded public-bus arithmetic experiment; not the complete L1 acceptance suite."""

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_reference import MASK, alu_result, immediate, m_result, r_instruction, store
from record import Experiment, ROOT


def arithmetic_trace(seed):
    rng = random.Random(seed)
    rows = []
    counts = Counter()
    pc = 0x10000

    def transaction(write, instruction, size, address, data=0, strobes=0, response=0):
        rows.append((write, instruction, size, address, data, strobes, response,
                     rng.randrange(1, 6)))

    def fetch(instruction):
        nonlocal pc
        transaction(0, 1, 2, pc, response=instruction)
        pc += 4

    # Keep operand and signature addresses ordinary DDR; the core is tested
    # against its public bus, not product-internal register-file observations.
    fetch(0x800002b7)  # LUI x5,0x80000 sign-extends in RV64
    fetch(immediate(5, 5, 32, 1))  # SLLI x5,x5,32
    fetch(immediate(5, 5, 32, 5))  # SRLI x5,x5,32
    cases = [(0, 0), (1, 0), (MASK, 0), (1 << 63, MASK),
             (1 << 31, MASK), (0x80000000, 0xffffffff),
             (MASK, 1), (MASK, MASK), (1 << 63, 1 << 63),
             (0x7fffffffffffffff, 2)]
    cases += [(rng.getrandbits(64), rng.getrandbits(64)) for _ in range(32)]
    operations = [(f"m{op}", op, word) for word in (False, True)
                  for op in (range(8) if not word else (0, 4, 5, 6, 7))]
    operations += [(op, None, word) for word in (False, True)
                   for op in (("add", "sub", "sll", "srl", "sra") if word else
                              ("add", "sub", "sll", "srl", "sra", "slt",
                               "sltu", "xor", "or", "and"))]
    alu_encodings = {"add": (0, 0), "sub": (0, 32), "sll": (1, 0),
                     "srl": (5, 0), "sra": (5, 32), "slt": (2, 0),
                     "sltu": (3, 0), "xor": (4, 0), "or": (6, 0), "and": (7, 0)}
    for name, mop, word in operations:
        for a, b in cases:
            fetch(immediate(6, 5, 0, 3, 3))  # LD x6,0(x5)
            transaction(0, 0, 3, 0x80000000, response=a)
            fetch(immediate(7, 5, 8, 3, 3))
            transaction(0, 0, 3, 0x80000008, response=b)
            funct3, funct7 = (mop, 1) if mop is not None else alu_encodings[name]
            fetch(r_instruction(8, 6, 7, funct3, funct7, word))
            expected = m_result(mop, a, b, word) if mop is not None else (
                alu_result(name, a, b, word))
            fetch(store(8, 5, 16))
            transaction(1, 0, 3, 0x80000010, expected, 255)
            counts[f"{name}{'w' if word else ''}"] += 1
    # End after one ordinary instruction response, so halt is requested before
    # that instruction retires and no next instruction can be fetched.
    fetch(immediate(0, 0, 0))
    return rows, counts


def run(experiment, seed):
    rows, counts = arithmetic_trace(seed)
    trace = experiment.path / f"cpu-{seed}.trace"
    trace.write_text("".join(
        f"{w} {i} {s} {a:016x} {d:016x} {st:02x} {r:016x} {delay}\n"
        for w, i, s, a, d, st, r, delay in rows))
    binary = experiment.path / "cpu.vvp"
    experiment.command(["iverilog", "-g2012", "-Wall", "-s", "cpu_bus_tb",
                        "-o", str(binary.relative_to(ROOT)),
                        "rtl/furnace_rv64im_core.sv", "tests/cpu_bus_tb.sv"],
                       "cpu-compile")
    output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
                                 f"+trace={trace.relative_to(ROOT)}", f"+seed={seed}"],
                                f"cpu-run-{seed}")
    if f"transactions={len(rows)} " not in output or "CPU_ARITHMETIC_PASS" not in output:
        raise AssertionError("CPU comparison count/summary missing")
    (experiment.path / f"cpu-{seed}.coverage.json").write_text(
        json.dumps({"seed": seed, "compared_transactions": len(rows),
                    "arithmetic_signature_comparisons": dict(counts)}, indent=2) + "\n")
    return output.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("cpu-arithmetic")
    try:
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        print(run(experiment, args.seed))
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
