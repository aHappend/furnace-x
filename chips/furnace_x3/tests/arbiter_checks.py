"""Six continuously contending clients with independent read/write obligations."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    experiment = Experiment("six-client-memory-arbitration", args.repair_of)
    try:
        binary = experiment.path / "arbiter.vvp"
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "arbiter_tb",
                            "-o", str(binary.relative_to(ROOT)),
                            "rtl/furnace_x3_axi512_arb.sv", "tests/arbiter_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
                                     f"+seed={args.seed}"], "simulate")
        if "ARBITER_PASS clients=6 read_bursts=96 write_bursts=96 " not in output:
            raise AssertionError("independent arbitration comparisons absent")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
