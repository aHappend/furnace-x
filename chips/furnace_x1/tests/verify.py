#!/usr/bin/env python3
"""FURNACE-X1 independent verification entrypoint.

Development is incremental: unimplemented admitted coverage fails explicitly.
No partial experiment is reported as acceptance of a mandatory suite.
"""

import argparse
from pathlib import Path
import random
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import ROOT, Run, fresh
import reference as ref
import lz4_cases
import crypto_reference
import crypto_cases
import interfaces
import soc_cases
import synthesis
import yosys_packed
import mutations


def tensor_vectors(path, count=256):
    rng = random.Random(2026)
    special = [0, 0x8000, 1, 0x8001, 0x7F, 0x80, 0x807F, 0x8080,
               0x3F80, 0xBF80, 0x3F81, 0x3F00, 0x7F7F, 0xFF7F,
               0x7F80, 0xFF80, 0x7FC0, 0x7F81, 0x3380, 0xB380]
    lines = []
    counts = {}
    results = 0
    for mode in range(3):
        accumulator = 0
        for index in range(count):
            first = index < 4 or index % 4 == 0
            last = index < 4 or index % 4 == 3 or index == count - 1
            if index < 32:
                weights = [((index + lane) & 15) if mode != 1
                           else special[(index + lane) % len(special)] for lane in range(8)]
                activations = [([0, 1, 0xFFFF, 0x7FFF, 0x8000, 255, 0xFF00, 17][lane])
                               if mode == 0 else special[(index * 3 + lane) % len(special)]
                               for lane in range(8)]
            else:
                weights = [rng.randrange(65536 if mode == 1 else 16) for _ in range(8)]
                activations = [rng.randrange(65536) for _ in range(8)]
            if index == 0 and mode != 0:
                weights = [0x3F80 if mode == 1 else 1] * 2 + [0] * 6
                activations = [0x3F80, 0x3380] + [0] * 6
            if first:
                accumulator = 0
            accumulator = ref.tensor(mode, weights, activations, accumulator)
            w = sum(x << ((16 if mode == 1 else 4) * lane) for lane, x in enumerate(weights))
            a = sum(x << (16 * lane) for lane, x in enumerate(activations))
            lines.append(f"{mode} {int(first)} {int(last)} {w:032x} {a:032x} {accumulator:016x}\n")
            results += last
        counts[str(mode)] = count
    path.write_text("".join(lines))
    return counts, results


def compile_tb(run, name, simulator="verilator", parameters=(), rtl=None, tb=None):
    rtl = rtl or sorted(ROOT.glob("rtl/*.sv"))
    tb = tb or ROOT / "tests" / f"{name}_tb.sv"
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


def tensor_probe(run, simulator="verilator", count=256, rtl=None):
    path = run.directory / "tensor-vectors.txt"
    counts, results = tensor_vectors(path, count)
    command = compile_tb(run, "tensor", simulator, rtl=rtl)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path)], "tensor-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    expected = f"COUNTS tensor vectors={sum(counts.values())} results={results}"
    if expected not in stdout:
        raise AssertionError("tensor comparison counters missing: " + stdout)
    run.receipt["coverage"]["tensor_vectors_per_mode"] = counts
    run.receipt["coverage"]["tensor_compared_results"] = results
    run.save()


def soc_probe(run, simulator="verilator", count=24, max_tile=32, depth=1, seed=17, rtl=None):
    path = run.directory / "soc-vectors.txt"
    records = soc_cases.generate(path, count, max_tile, depth, seed)
    run.receipt["soc_expected"] = records
    run.save()
    tb = run.directory / "soc_tb.sv"
    template = (ROOT / "tests/soc_tb.sv").read_text()
    tb.write_text(template.replace("/* PUBLIC_DECLARATIONS */", interfaces.declarations()).replace(
        "/* PUBLIC_RESET_EXPRESSION */", interfaces.reset_expression()))
    parameters = ([f"-Psoc_tb.MAX_TILE_BYTES={max_tile}", f"-Psoc_tb.RING_DEPTH={depth}"]
                  if simulator == "iverilog" else [
                      f"-GMAX_TILE_BYTES={max_tile}", f"-GRING_DEPTH={depth}"])
    command = compile_tb(run, "soc", simulator, parameters, tb=tb, rtl=rtl)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path)], "soc-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    if f"COUNTS soc completed={count} " not in stdout:
        raise AssertionError("SoC comparisons absent: " + stdout)
    run.receipt["coverage"]["soc_compared_descriptors"] = count
    run.save()


def crypto_probe(run, simulator="verilator"):
    compact = simulator == "iverilog"
    expected = crypto_cases.generate(run.directory, compact)
    run.receipt["crypto_expected"] = expected
    run.save()
    for name in ("aes", "gcm"):
        command = compile_tb(run, name, simulator)
        _, stdout, _ = run.command([*command, "+vectors=" + str(run.directory / (name + "-vectors.txt"))],
                                  name + "-sim-" + simulator, timeout=600 if compact else 3600)
        wanted = (f"COUNTS aes compared={expected['aes_cases']}" if name == "aes" else
                  f"COUNTS gcm cases={expected['gcm_cases']} success={expected['successes']} failures={expected['failures']}")
        if wanted not in stdout:
            raise AssertionError(f"{name} comparisons absent: {stdout}")
    run.receipt["coverage"]["crypto"] = expected
    run.save()


def xbar_probe(run, simulator="verilator"):
    tb = run.directory / "xbar_tb.sv"
    tb.write_text((ROOT / "tests/xbar_tb.sv").read_text().replace(
        "/* PUBLIC_DECLARATIONS */", interfaces.crossbar_declarations()).replace(
            "/* PUBLIC_RESET_EXPRESSION */", interfaces.crossbar_reset_expression()))
    command = compile_tb(run, "xbar", simulator, tb=tb)
    _, stdout, _ = run.command(command, "xbar-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    if "COUNTS xbar reads=80 writes=80 " not in stdout:
        raise AssertionError("crossbar comparisons absent: " + stdout)
    run.receipt["coverage"]["xbar_read_transactions"] = 80
    run.receipt["coverage"]["xbar_write_transactions"] = 80
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
    parser.add_argument("--probe", choices=["tensor", "lz4", "soc", "synthesis", "frontends", "yosys-lowered", "crypto", "xbar", "mutation"])
    parser.add_argument("--mutant", choices=sorted(mutations.MUTANTS), default="sign")
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
        crypto_reference.selftest()
        if args.probe in ("synthesis", "frontends", "yosys-lowered") or args.suite == "synthesis":
            run.versions(["python3", "yosys"])
            if args.probe == "yosys-lowered":
                run.versions(["iverilog", "vvp"])
        else:
            run.versions(["python3", args.simulator] + (["vvp"] if args.simulator == "iverilog" else ["make", "g++"]))
        if args.probe == "tensor":
            tensor_probe(run, args.simulator, 8 if args.simulator == "iverilog" else 256)
        elif args.probe == "lz4":
            lz4_probe(run, args.simulator, args.lz4_bound)
        elif args.probe == "soc":
            soc_probe(run, args.simulator, count=4 if args.simulator == "iverilog" else 24)
        elif args.probe == "synthesis":
            synthesis.synthesize(run, 32, 1, "yosys-probe")
        elif args.probe == "frontends":
            run.command(["yosys", "-Q", "-T", "-p",
                         "help read_slang; help read_systemverilog; plugin -l"], "yosys-frontends")
            run.command(["python3", "-c",
                         "import shutil,json; print(json.dumps({x:shutil.which(x) for x in "
                         "['sv2v','slang','yosys-slang','yosys']}))"], "frontend-tools")
        elif args.probe == "yosys-lowered":
            rtl = yosys_packed.sources(run)
            soc_probe(run, "iverilog", count=4, rtl=rtl)
            synthesis.synthesize(run, 32, 1, "yosys-probe", rtl=rtl)
        elif args.probe == "crypto":
            crypto_probe(run, args.simulator)
        elif args.probe == "xbar":
            xbar_probe(run, args.simulator)
        elif args.probe == "mutation":
            run.receipt["mutation_receipt"] = mutations.execute(args.mutant, compile_tb, tensor_vectors)
            run.save()
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
