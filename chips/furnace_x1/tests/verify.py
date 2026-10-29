#!/usr/bin/env python3
"""FURNACE-X1 independent verification entrypoint.

Development is incremental: unimplemented admitted coverage fails explicitly.
No partial experiment is reported as acceptance of a mandatory suite.
"""

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import ROOT, Run, fresh
import reference as ref


def tensor_vectors(path, count=256):
    rng = random.Random(2026)
    special = [0, 0x8000, 1, 0x8001, 0x7F, 0x80, 0x807F, 0x8080,
               0x3F80, 0xBF80, 0x3F81, 0x3F00, 0x7F7F, 0xFF7F,
               0x7F80, 0xFF80, 0x7FC0, 0x7F81, 0x3380, 0xB380]
    lines = []
    counts = {}
    for mode in range(3):
        accumulator = 0
        for index in range(count):
            first = index % 4 == 0
            last = index % 4 == 3 or index == count - 1
            if index < 32:
                weights = [((index + lane) & 15) if mode != 1
                           else special[(index + lane) % len(special)] for lane in range(8)]
                activations = [([0, 1, 0xFFFF, 0x7FFF, 0x8000, 255, 0xFF00, 17][lane])
                               if mode == 0 else special[(index * 3 + lane) % len(special)]
                               for lane in range(8)]
            else:
                weights = [rng.randrange(65536 if mode == 1 else 16) for _ in range(8)]
                activations = [rng.randrange(65536) for _ in range(8)]
            if first:
                accumulator = 0
            accumulator = ref.tensor(mode, weights, activations, accumulator)
            w = sum(x << ((16 if mode == 1 else 4) * lane) for lane, x in enumerate(weights))
            a = sum(x << (16 * lane) for lane, x in enumerate(activations))
            lines.append(f"{mode} {int(first)} {int(last)} {w:032x} {a:032x} {accumulator:016x}\n")
        counts[str(mode)] = count
    path.write_text("".join(lines))
    return counts


def compile_tb(run, name, simulator="verilator", parameters=(), rtl=None):
    rtl = rtl or sorted(ROOT.glob("rtl/*.sv"))
    tb = ROOT / "tests" / f"{name}_tb.sv"
    if simulator == "iverilog":
        binary = run.directory / (name + ".vvp")
        run.command(["iverilog", "-g2012", "-Wall", "-s", name + "_tb",
                     *parameters, "-o", binary, *rtl, tb], name + "-compile-icarus")
        return ["vvp", binary]
    obj = run.directory / (name + "-obj")
    run.command(["verilator", "--binary", "--timing", "-Wno-fatal", "--top-module",
                 name + "_tb", "--Mdir", obj, "-j", "2", *parameters,
                 *rtl, tb], name + "-compile-verilator")
    return [obj / ("V" + name + "_tb")]


def tensor_probe(run, simulator="verilator", count=256):
    path = run.directory / "tensor-vectors.txt"
    counts = tensor_vectors(path, count)
    command = compile_tb(run, "tensor", simulator)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path)], "tensor-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    expected = f"COUNTS tensor vectors={sum(counts.values())} results={sum(counts.values()) // 4}"
    if expected not in stdout:
        raise AssertionError("tensor comparison counters missing: " + stdout)
    run.receipt["coverage"]["tensor_vectors_per_mode"] = counts
    run.receipt["coverage"]["tensor_compared_results"] = sum(counts.values()) // 4
    run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["behavior", "boundaries", "defects", "synthesis", "portable"])
    parser.add_argument("--probe", choices=["tensor"])
    parser.add_argument("--simulator", choices=["iverilog", "verilator"], default="verilator")
    args = parser.parse_args()
    if (args.suite is None) == (args.probe is None):
        parser.error("select exactly one of --suite or --probe")
    directory = fresh(args.suite or args.probe, preparation=bool(args.probe))
    run = Run(directory)
    try:
        ref.selftest()
        run.versions(["python3", args.simulator] + (["vvp"] if args.simulator == "iverilog" else ["make", "g++"]))
        if args.probe == "tensor":
            tensor_probe(run, args.simulator, 8 if args.simulator == "iverilog" else 256)
        else:
            raise NotImplementedError(f"{args.suite}: complete admitted suite not yet implemented")
    except Exception as exc:
        run.finish("failed", exc)
        print(f"FAILED {directory.relative_to(ROOT)}/receipt.json: {exc}", file=sys.stderr)
        return 1
    run.finish("passed")
    print(f"PREPARATION ONLY {directory.relative_to(ROOT)}/receipt.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
