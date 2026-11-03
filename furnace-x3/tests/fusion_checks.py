"""Arrival-ordered independent fusion queue scoreboard."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, choices=(1, 3, 16), default=3)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("fusion-ordering")
    obj = experiment.path / "compile-obj"
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "fusion_tb", f"-GDEPTH={args.depth}",
                            "--Mdir", str(obj.relative_to(ROOT)), "-o", "fusion-sim",
                            "rtl/furnace_fusion_buffer.sv", "tests/fusion_tb.sv"], "compile")
        output = experiment.command([str((obj / "fusion-sim").relative_to(ROOT)),
                                     f"+seed={args.seed}"], "simulate")
        if "FUSION_PASS " not in output:
            raise AssertionError("fusion comparisons missing")
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
