"""Host/CPU round-robin, byte strobes, request and response ownership."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def main():
    experiment = Experiment("host-cpu-mmio-arbitration")
    try:
        binary = experiment.path / "mmio.vvp"
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "mmio_arb_tb",
                            "-o", str(binary.relative_to(ROOT)),
                            "rtl/furnace_x3_mmio_arb.sv", "tests/mmio_arb_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT))], "simulate")
        if "MMIO_ARBITRATION_PASS" not in output:
            raise AssertionError("host/CPU fairness comparisons absent")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
