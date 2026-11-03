"""Semaphore/IRQ/mailbox public-pin directed and queue-oracle checks."""

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
    experiment = Experiment("synchronization")
    try:
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        binary = experiment.path / "sync.vvp"
        experiment.command([
            "iverilog", "-g2012", "-Wall", "-s", "synchronization_tb",
            f"-Psynchronization_tb.DEPTH={args.depth}",
            "-o", str(binary.relative_to(ROOT)), "rtl/furnace_hw_semaphores.sv",
            "rtl/furnace_interrupt_aggregator.sv", "rtl/furnace_mailboxes.sv",
            "rtl/furnace_mailbox_fifo.sv", "tests/synchronization_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT)), f"+seed={args.seed}"],
                                    "simulate")
        if "SYNC_PASS " not in output:
            raise AssertionError("synchronization comparisons missing")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
