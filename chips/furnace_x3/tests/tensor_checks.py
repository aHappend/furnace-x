"""Independent exact INT4, BF16 and W4/BF16 tensor comparisons."""

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from numerical_reference import pack_lanes, tensor_vector
from record import Experiment, ROOT


def vectors(seed):
    rng = random.Random(seed)
    rows = []
    interesting = [0, 0x8000, 1, 0x8001, 0x7f, 0x80, 0x807f, 0x8080,
                   0x3f80, 0xbf80, 0x7f7f, 0xff7f, 0x7f80, 0xff80,
                   0x7fc0, 0x7f81]
    for mode in range(3):
        for tile in range(120):
            accumulator = 0
            n = 1 if tile < 20 else rng.randrange(1, 5)
            for index in range(n):
                if mode == 1:
                    weights = [rng.choice(interesting) if tile < 40 else rng.getrandbits(16)
                               for _ in range(8)]
                else:
                    weights = [rng.getrandbits(4) for _ in range(8)]
                activations = [
                    rng.getrandbits(16) if mode == 0 or tile >= 40 else rng.choice(interesting)
                    for _ in range(8)]
                accumulator = tensor_vector(mode, weights, activations, accumulator)
                rows.append((mode, int(index == 0), int(index == n - 1),
                             pack_lanes(weights, 16 if mode == 1 else 4),
                             pack_lanes(activations, 16), accumulator, 0,
                             int(index == n - 1)))
    # Protocol errors must produce explicit code6, not plausible arithmetic.
    rows += [(3, 1, 1, 0, 0, 0, 6, 1),
             (0, 0, 1, 0, 0, 0, 6, 1),
             (2, 1, 1, 1 << 32, 0, 0, 6, 1)]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("tensor-numerical")
    obj = experiment.path / "compile-obj"
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        trace = experiment.path / "tensor.trace"
        rows = vectors(args.seed)
        trace.write_text("".join(
            f"{mode} {first} {last} {w:032x} {a:032x} {expected:016x} {error} {valid}\n"
            for mode, first, last, w, a, expected, error, valid in rows))
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "tensor_tb", "--Mdir", str(obj.relative_to(ROOT)),
                            "-o", "tensor-sim", "rtl/furnace_tensor8.sv",
                            "rtl/furnace_fp32_mul4.sv", "rtl/furnace_fp32_add5.sv",
                            "rtl/furnace_fp32_round.sv", "tests/tensor_tb.sv"], "compile")
        output = experiment.command([str((obj / "tensor-sim").relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}",
                                     f"+rows={len(rows)}"], "simulate")
        if "TENSOR_PASS " not in output:
            raise AssertionError("tensor comparisons missing")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    finally:
        for pattern in ("*.o", "*.a", "*.gch"):
            for path in obj.glob(pattern):
                path.unlink()
    experiment.finish()


if __name__ == "__main__":
    main()
