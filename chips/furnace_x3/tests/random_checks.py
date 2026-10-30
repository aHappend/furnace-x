"""Verify identical independently predicted seeded stimuli in both simulators."""

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def mix(value):
    value = value or 0x6d2b79f5
    value ^= value << 13 & 0xffffffff
    value ^= value >> 17
    value ^= value << 5 & 0xffffffff
    return value & 0xffffffff


def main():
    experiment = Experiment("cross-simulator-seeded-stimulus")
    obj = experiment.path / "compile-obj"
    try:
        binary = experiment.path / "random.vvp"
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "random_tb",
                            "-o", str(binary.relative_to(ROOT)), "tests/random_tb.sv"],
                           "iverilog-compile")
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "random_tb", "--Mdir", str(obj.relative_to(ROOT)),
                            "-o", "random-sim", "tests/random_tb.sv"], "verilator-compile")
        results = []
        for seed in (17, 89, 2027):
            expected, state = [], seed
            for index in range(16):
                state = mix(state)
                expected.append(f"RNG_WORD {index} " + " ".join(
                    f"{mix((state+0x9e3779b9*stream)&0xffffffff):08x}" for stream in (1, 2, 3)))
            for simulator, command in (
                    ("icarus", ["vvp", str(binary.relative_to(ROOT))]),
                    ("verilator", [str((obj / "random-sim").relative_to(ROOT))])):
                output = experiment.command([*command, f"+seed={seed}"], f"{simulator}-{seed}")
                actual = re.findall(r"^RNG_WORD .*$", output, re.M)
                if actual != expected:
                    raise AssertionError(f"seeded stimulus differs: {simulator}/{seed}")
            results.append(tuple(expected))
        if len(set(results)) != 3:
            raise AssertionError("different seeds generated identical schedules")
        print("RANDOM_STIMULUS_PASS simulators=2 seeds=3 independently_compared_words=288")
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
