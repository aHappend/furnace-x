#!/usr/bin/env python3
"""FURNACE-X1 source-bound public-interface L1 verification.

Run each command from the project directory:
    python3 tests/verify.py --suite behavior
    python3 tests/verify.py --suite boundaries
    python3 tests/verify.py --suite defects
    python3 tests/verify.py --suite synthesis
    python3 tests/verify.py --suite portable

behavior: compact IEEE smoke; exact AES/GCM, LZ4 and tensor oracles;
          concurrent AXI scoreboards; three seeds at each admitted SoC geometry.
boundaries: all twenty top parameter tuples; CSR/ring event priorities; bus
            faults, reset epochs, singleton/64-KiB capacity, extended LZ4 history
            and explicit illegal-parameter diagnostics.
defects: six disposable, compiled RTL mutations must reach their named functional
         comparison, not merely fail compilation or time out.
synthesis: real memory-preserving Yosys at minimum, nonpower, default and maximum
           geometry, with literal engines, state, memories and outputs retained.
portable: copy only declared sources and execute a fresh relative-path process
          for all tensor modes, authentication rejection and real synthesis.

Dependencies: Python 3, Icarus/vvp, Verilator, make, g++ and Yosys. Optional
installed liblz4/cryptography independently cross-check the mandatory pure-Python
references; published known answers remain mandatory without either library.
Every invocation retains fresh source snapshots, exact subprocess logs, achieved
comparisons and failures. --probe is advisory preparation, never suite acceptance.
The shared runtime owns physical timing/hardware gates and the final report.
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
import soc_boundaries
import synthesis
import yosys_packed
import mutations
import suites


def tensor_vectors(path, count=256, coverage=None):
    rng = random.Random(2026)
    special = [0, 0x8000, 1, 0x8001, 0x7F, 0x80, 0x807F, 0x8080,
               0x3F80, 0xBF80, 0x3F81, 0x3F00, 0x7F7F, 0xFF7F,
               0x7F80, 0xFF80, 0x7FC0, 0x7F81, 0x3380, 0xB380]
    lines = []
    counts = {}
    results = 0
    codes = {0: set(), 2: set()}
    lane_distinct = set()
    directed = []
    for mode in range(3):
        accumulator = 0
        for index in range(count):
            first = index < 32 or index % 4 == 0
            last = index < 32 or index % 4 == 3 or index == count - 1
            if index < 32:
                weights = [((index + lane) & 15) if mode != 1 else 0x3F80 for lane in range(8)]
                activations = [([0, 1, 0xFFFF, 0x7FFF, 0x8000, 255, 0xFF00, 17][lane])
                               if mode == 0 else (special[index % len(special)] if lane == 0 else 0)
                               for lane in range(8)]
                if mode != 0:
                    weights = [0x3F80 if mode == 1 else 1] * 8
                    if index == 20:  # Negative zero products.
                        weights = [0xBF80 if mode == 1 else 15] * 8
                        activations = [0] * 8
                    elif index == 21:  # Exact cancellation.
                        activations = [0x3F80, 0xBF80] + [0] * 6
                    elif index == 22:  # Finite product overflow.
                        weights = [0x7F7F if mode == 1 else 7] + [0] * 7
                        activations = [0x7F7F] + [0] * 7
                    elif index == 23:  # Invalid infinity times zero.
                        weights = [0] * 8
                        activations = [0x7F80] + [0] * 7
                    elif index == 24:  # Opposite infinities in the reduction.
                        activations = [0x7F80, 0xFF80] + [0] * 6
                    elif index == 25:  # Tree association and intermediate ties.
                        activations = [0x4B80, 0x3F80, 0xCB80, 0x3F80] + [0] * 4
                    elif index == 26 and mode == 1:
                        weights = [1] + [0] * 7
                        activations = [0x3F80] + [0] * 7
                    elif index == 27 and mode == 1:
                        weights = [1] + [0] * 7
                        activations = [0x3700] + [0] * 7
                    elif index == 28 and mode == 1:
                        weights = [3] + [0] * 7
                        activations = [0x3700] + [0] * 7
            else:
                weights = [rng.randrange(65536 if mode == 1 else 16) for _ in range(8)]
                activations = [rng.randrange(65536) for _ in range(8)]
            if index == 0 and mode != 0:
                weights = [0x3F80 if mode == 1 else 1] * 2 + [0] * 6
                activations = [0x3F80, 0x3380] + [0] * 6
            if first:
                accumulator = 0
            accumulator = ref.tensor(mode, weights, activations, accumulator)
            if mode != 1:
                codes[mode].update(weights)
            if len(set(activations)) == 8:
                lane_distinct.add(mode)
            if mode != 0 and index in (0, 21, 22, 23, 24, 25, 26, 27, 28):
                directed.append(dict(mode=mode, index=index, expected=f"{accumulator:08x}"))
            w = sum(x << ((16 if mode == 1 else 4) * lane) for lane, x in enumerate(weights))
            a = sum(x << (16 * lane) for lane, x in enumerate(activations))
            lines.append(f"{mode} {int(first)} {int(last)} {w:032x} {a:032x} {accumulator:016x}\n")
            results += last
        counts[str(mode)] = count
    path.write_text("".join(lines))
    if coverage is not None:
        coverage.update(w4_codes={str(k): sorted(v) for k, v in codes.items()},
                        lane_distinct_modes=sorted(lane_distinct), directed_results=directed)
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
    exercised = {}
    counts, results = tensor_vectors(path, count, exercised)
    command = compile_tb(run, "tensor", simulator, rtl=rtl)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path)], "tensor-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    expected = f"COUNTS tensor vectors={sum(counts.values())} results={results}"
    if expected not in stdout:
        raise AssertionError("tensor comparison counters missing: " + stdout)
    run.receipt["coverage"]["tensor_vectors_per_mode"] = counts
    run.receipt["coverage"]["tensor_compared_results"] = results
    if count >= 256:
        if any(codes != list(range(16)) for codes in exercised["w4_codes"].values()):
            raise AssertionError("not every W4 code reached the tensor oracle")
        if exercised["lane_distinct_modes"] != [0, 1, 2]:
            raise AssertionError("lane-distinct activation coverage absent")
    run.receipt["coverage"]["tensor_transferred_categories"] = exercised
    run.save()


def soc_probe(run, simulator="verilator", count=24, max_tile=32, depth=1, seed=17, rtl=None,
              large=False):
    path = run.directory / "soc-vectors.txt"
    records = soc_cases.generate(path, count, max_tile, depth, seed, large=large)
    run.receipt["soc_expected"] = records
    run.save()
    tb = run.directory / "soc_tb.sv"
    template = (ROOT / "tests/soc_tb.sv").read_text()
    tb.write_text(template.replace("/* PUBLIC_DECLARATIONS */", interfaces.declarations()).replace(
        "/* PUBLIC_RESET_EXPRESSION */", interfaces.reset_expression()))
    parameters = ([f"-Psoc_tb.MAX_TILE_BYTES={max_tile}", f"-Psoc_tb.RING_DEPTH={depth}"]
                  if simulator == "iverilog" else [
                      f"-GMAX_TILE_BYTES={max_tile}", f"-GRING_DEPTH={depth}"])
    if large:
        if simulator != "verilator":
            raise ValueError("64-KiB integrated capacity runs use compiled simulation")
        parameters.append("-GREGION_BITS=17")
    command = compile_tb(run, "soc", simulator, parameters, tb=tb, rtl=rtl)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path), f"+seed={seed}"], "soc-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    if f"COUNTS soc completed={count} " not in stdout:
        raise AssertionError("SoC comparisons absent: " + stdout)
    run.receipt["coverage"]["soc_compared_descriptors"] = count
    run.save()


def soc_boundary_probe(run, simulator="verilator", max_tile=32, depth=1, compact=False):
    path = run.directory / "soc-boundary-vectors.txt"
    records, completed = soc_boundaries.generate(path, max_tile, depth, compact=compact)
    run.receipt["soc_boundaries"] = records
    run.save()
    tb = run.directory / "soc_tb.sv"
    tb.write_text((ROOT / "tests/soc_tb.sv").read_text().replace(
        "/* PUBLIC_DECLARATIONS */", interfaces.declarations()).replace(
        "/* PUBLIC_RESET_EXPRESSION */", interfaces.reset_expression()))
    parameters = ([f"-Psoc_tb.MAX_TILE_BYTES={max_tile}", f"-Psoc_tb.RING_DEPTH={depth}"]
                  if simulator == "iverilog" else [
                      f"-GMAX_TILE_BYTES={max_tile}", f"-GRING_DEPTH={depth}"])
    command = compile_tb(run, "soc", simulator, parameters, tb=tb)
    _, stdout, _ = run.command([*command, "+vectors=" + str(path)], "soc-boundary-sim",
                              timeout=600 if simulator == "iverilog" else 3600)
    if f"COUNTS soc completed={completed} " not in stdout:
        raise AssertionError("SoC boundary comparisons absent: " + stdout)
    run.receipt["coverage"]["soc_boundary_cases"] = len(records)
    run.save()


def crypto_probe(run, simulator="verilator", max_length=257):
    compact = simulator == "iverilog"
    expected = crypto_cases.generate(run.directory, compact, max_length)
    run.receipt["crypto_expected"] = expected
    run.save()
    for name in ("aes", "gcm"):
        parameters = ([] if name == "aes" else
                      [f"-Pgcm_tb.MAX_TILE_BYTES={max_length}"] if compact else
                      [f"-GMAX_TILE_BYTES={max_length}"])
        command = compile_tb(run, name, simulator, parameters)
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
    if "COUNTS xbar reads=184 writes=184 " not in stdout:
        raise AssertionError("crossbar comparisons absent: " + stdout)
    run.receipt["coverage"]["xbar_read_transactions"] = 184
    run.receipt["coverage"]["xbar_write_transactions"] = 184
    run.receipt["coverage"]["xbar_concurrent_targets_per_direction"] = 4
    run.save()


def csr_probe(run, simulator="iverilog"):
    tb = run.directory / "csr_tb.sv"
    tb.write_text((ROOT / "tests/csr_tb.sv").read_text().replace(
        "/* AXIL_DECLARATIONS */", interfaces.axil_declarations()).replace(
        "/* AXIL_OUTPUTS */", ",".join("s_axil_" + p for p in interfaces.AXIL_OUT)))
    command = compile_tb(run, "csr", simulator, tb=tb)
    _, stdout, _ = run.command(command, "csr-sim-" + simulator,
                              timeout=600 if simulator == "iverilog" else 3600)
    import re
    result = re.search(r"COUNTS csr comparisons=(\d+) set_clear=2 concurrent=1", stdout)
    if result is None or int(result[1]) < 60:
        raise AssertionError("CSR comparison counters missing: " + stdout)
    run.receipt["coverage"]["csr_comparisons"] = int(result[1])
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
    successes = {c["label"] for c in cases if c["status"] == 0 and not c["reset_after"]}
    errors = {c["label"] for c in cases if c["status"] != 0 and not c["reset_after"]}
    if not compact and bound >= 65536 and (len(successes) < 64 or len(errors) < 32):
        raise AssertionError("LZ4 valid/error category thresholds not met")
    run.receipt["coverage"]["lz4_distinct_success_categories"] = sorted(successes)
    run.receipt["coverage"]["lz4_distinct_error_categories"] = sorted(errors)
    run.receipt["coverage"]["lz4_valid_cases"] = sum(
        c["status"] == 0 and not c["reset_after"] for c in cases)
    run.receipt["coverage"]["lz4_completed_cases"] = len(cases) - reset_count
    run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["behavior", "boundaries", "defects", "synthesis", "portable"])
    parser.add_argument("--probe", choices=["tensor", "lz4", "soc", "soc-capacity", "soc-matrix-cell", "soc-boundaries", "synthesis", "frontends", "yosys-lowered", "crypto", "xbar", "csr", "ring", "parameters", "mutation", "portable-smoke"])
    parser.add_argument("--max-tile", type=int, default=32)
    parser.add_argument("--ring-depth", type=int, default=1)
    parser.add_argument("--mutant", choices=sorted(mutations.MUTANTS), default="sign")
    parser.add_argument("--lz4-bound", type=int, default=131072)
    parser.add_argument("--crypto-bound", type=int, default=257)
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
        if args.suite:
            suites.execute(args.suite, run, sys.modules[__name__])
            run.finish("passed")
            print(f"L1 COMPLETED {directory.relative_to(ROOT)}/receipt.json")
            return 0
        if args.probe in ("synthesis", "frontends", "yosys-lowered", "portable-smoke"):
            run.versions(["python3", "yosys"])
            if args.probe in ("yosys-lowered", "portable-smoke"):
                run.versions(["iverilog", "vvp"])
        elif args.probe in ("ring", "parameters"):
            run.versions(["python3", "iverilog", "vvp"])
        elif args.probe in ("mutation", "soc-capacity", "soc-matrix-cell"):
            run.versions(["python3", "verilator", "make", "g++"])
        else:
            run.versions(["python3", args.simulator] + (["vvp"] if args.simulator == "iverilog" else ["make", "g++"]))
        if args.probe == "tensor":
            tensor_probe(run, args.simulator, 8 if args.simulator == "iverilog" else 256)
        elif args.probe == "lz4":
            lz4_probe(run, args.simulator, args.lz4_bound)
        elif args.probe == "soc":
            soc_probe(run, args.simulator, count=5 if args.simulator == "iverilog" else 24,
                      max_tile=args.max_tile, depth=args.ring_depth)
        elif args.probe == "soc-boundaries":
            soc_boundary_probe(run, args.simulator, args.max_tile, args.ring_depth)
        elif args.probe == "soc-capacity":
            soc_probe(run, max_tile=65536, depth=16, count=1, large=True)
        elif args.probe == "soc-matrix-cell":
            suites.soc_matrix_cell(run, sys.modules[__name__], args.max_tile, args.ring_depth)
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
            soc_probe(run, "iverilog", count=5, rtl=rtl)
            synthesis.synthesize(run, args.max_tile, args.ring_depth, "yosys-probe", rtl=rtl)
        elif args.probe == "crypto":
            crypto_probe(run, args.simulator, args.crypto_bound)
        elif args.probe == "xbar":
            xbar_probe(run, args.simulator)
        elif args.probe == "csr":
            csr_probe(run, args.simulator)
        elif args.probe == "ring":
            suites.ring(run, sys.modules[__name__], args.ring_depth)
        elif args.probe == "parameters":
            suites.parameter_diagnostics(run, sys.modules[__name__])
        elif args.probe == "portable-smoke":
            suites.synthesis_matrix(run, sys.modules[__name__], configurations=((32, 1),))
        elif args.probe == "mutation":
            run.receipt["mutation_receipt"] = mutations.execute(args.mutant, compile_tb, tensor_vectors)
            run.save()
    except Exception as exc:
        run.finish("failed", exc)
        print(f"FAILED {directory.relative_to(ROOT)}/receipt.json: {exc}", file=sys.stderr)
        return 1
    run.finish("passed")
    print(f"PREPARATION ONLY {directory.relative_to(ROOT)}/receipt.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
