"""Compiled native DMA transactions, independent plans/data/guard comparisons."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def cases(maximum):
    source, destination = 0x80000000, 0x80200000
    rows = [(source, destination, n, 0, 0)
            for n in sorted({0, 1, maximum, *(v for v in (63, 64, 65, 1025)
                                            if v <= maximum)})]
    rows += [(source, destination, maximum + 1, 1, 0),
             (source + 1, destination, 1, 1, 0),
             (source, destination + 1, 1, 1, 0),
             (0x70000000, destination, 1, 1, 0),
             (source, 0x70000000, 1, 1, 0),
             (source, source, 1, 1, 0),
             (source, destination, 0, 0, 0),
             (0xffffffc0, destination, min(65, maximum), int(maximum >= 65), 0)]
    # Avoid an out-of-model but legal end-of-DDR copy in singleton tests.
    if maximum < 65:
        rows.pop()
    if maximum >= 65:
        rows += [(source + 0xfc0, destination + 0xf80, min(maximum, 4096), 0, 0)]
    rows += [(source, destination, min(maximum, 65), 2, fault)
             for fault in (1, 2, 4, 5, 6)]
    if maximum >= 65:
        rows += [(source, destination, 65, 2, 3)]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--maximum", type=int, default=4096)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    experiment = Experiment("dma-transactions", args.repair_of)
    obj = experiment.path / "compile-obj"
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        casefile = experiment.path / "cases.txt"
        casefile.write_text("".join(
            f"{src:08x} {dst:08x} {length} {code} {fault}\n"
            for src, dst, length, code, fault in cases(args.maximum)))
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "dma_tb", f"-GMAX_DMA_BYTES={args.maximum}",
                            "--Mdir", str(obj.relative_to(ROOT)), "-o", "dma-sim",
                            "rtl/furnace_dma512.sv", "tests/dma_tb.sv"], "compile")
        output = experiment.command([str((obj / "dma-sim").relative_to(ROOT)),
                                     f"+cases={casefile.relative_to(ROOT)}",
                                     f"+commands={len(cases(args.maximum))}",
                                     f"+seed={args.seed}"], "simulate")
        if "DMA_PASS " not in output:
            raise AssertionError("DMA comparisons missing")
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
