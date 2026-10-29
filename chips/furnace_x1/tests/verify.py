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
import lz4_cases


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


def lz4_probe(run, simulator="verilator", bound=131072):
    compact = simulator == "iverilog"
    cases, valid = lz4_cases.make_cases(bound, compact=compact)
    for label, frame, expected in valid:
        if ref.decode_lz4(frame) != expected:
            raise AssertionError(f"LZ4 independent reference: {label}")
    run.receipt["reference_liblz4"] = lz4_cases.library_check(valid)
    run.receipt["lz4_cases"] = [{k: v for k, v in case.items() if k not in ("frame", "expected")}
                                for case in cases]
    run.save()
    path = run.directory / "lz4-vectors.txt"
    lz4_cases.write_cases(path, cases)
    parameters = ([f"-Plz4_tb.MAX_DECODED_BYTES={bound}"] if compact
                  else [f"-GMAX_DECODED_BYTES={bound}"])
    command = compile_tb(run, "lz4", simulator, parameters)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path)], "lz4-sim-" + simulator,
                              timeout=600 if compact else 3600)
    reset_count = sum(bool(c["reset_after"]) for c in cases)
    expected = f"COUNTS lz4 cases={len(cases)} completed={len(cases)-reset_count} reset={reset_count}"
    if expected not in stdout:
        raise AssertionError("LZ4 comparison counters missing: " + stdout)
    run.receipt["coverage"]["lz4_valid_cases"] = len(valid)
    run.receipt["coverage"]["lz4_completed_cases"] = len(cases) - reset_count
    run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["behavior", "boundaries", "defects", "synthesis", "portable"])
    parser.add_argument("--probe", choices=["tensor", "lz4"])
    parser.add_argument("--lz4-bound", type=int, default=131072)
    parser.add_argument("--simulator", choices=["iverilog", "verilator"], default="verilator")
    parser.add_argument("--repair-of", help="retained receipt explaining the prior failure")
    args = parser.parse_args()
    if (args.suite is None) == (args.probe is None):
        parser.error("select exactly one of --suite or --probe")
    directory = fresh(args.suite or args.probe, preparation=bool(args.probe))
    run = Run(directory)
    if args.repair_of:
        run.receipt["repair_of"] = args.repair_of
        run.save()
    try:
        ref.selftest()
        run.versions(["python3", args.simulator] + (["vvp"] if args.simulator == "iverilog" else ["make", "g++"]))
        if args.probe == "tensor":
            tensor_probe(run, args.simulator, 8 if args.simulator == "iverilog" else 256)
        elif args.probe == "lz4":
            lz4_probe(run, args.simulator, args.lz4_bound)
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
