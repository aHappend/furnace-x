"""Compact real-firmware DMA/fork-join smoke, independent byte-memory expected values."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT
from lower_packed import lower


def graph_memory():
    memory = bytearray((i * 37 + 19) & 255 for i in range(32768))
    # Six nodes: DMA -> {semaphore barrier, DMA} -> barrier fork/join.
    # Dependencies are record indices, not the deliberately unrelated node IDs.
    nodes = [(1, 0, (0x80001000, 0x80002000, 1), -1, 2),
             (4, 1, (), 2, 3),
             (1, 1, (0x80002000, 0x80003000, 1), -1, -1),
             (4, 1, (), 3, -1),
             (4, (1 << 2) | (1 << 3), (), -1, -1),
             (4, 1 << 4, (), -1, -1)]
    for index, (opcode, deps, args, wait, post) in enumerate(nodes):
        record = struct.pack("<IIQ6I6I", opcode, 100 + index * 7, deps,
                             *(tuple(args) + (0,) * (6 - len(args))),
                             wait & 0xffffffff, post & 0xffffffff,
                             0x80000800 + index * 16, 0, 0, 0)
        assert len(record) == 64
        memory[index * 64:(index + 1) * 64] = record
    expected = memory.copy()
    expected[0x2000] = expected[0x1000]
    expected[0x3000] = expected[0x2000]
    for index in range(6):
        expected[0x800 + index * 16:0x810 + index * 16] = struct.pack(
            "<4I", 2, 0, 100 + index * 7, 0)
    return memory, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--lowered", action="store_true")
    args = parser.parse_args()
    experiment = Experiment("x3-firmware-smoke")
    try:
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        image = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", "1",
                            "--in-height", "1", "--fft-n", "8",
                            "--output", str(image.relative_to(ROOT))], "firmware-build")
        metadata = json.loads(image.with_suffix(".json").read_text())
        memory, expected = graph_memory()
        for name, data in (("memory", memory), ("expected", expected)):
            (experiment.path / f"{name}.hex").write_text(
                "".join(f"{value:02x}\n" for value in data))
        binary = experiment.path / "x3.vvp"
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        if args.lowered:
            lowered = experiment.path / "lowered"
            lowered.mkdir()
            mappings = []
            for name in sources:
                text, mapping = lower((ROOT / name).read_text(), name)
                (lowered / Path(name).name).write_text(text)
                mappings.append(mapping)
            (experiment.path / "lowering-map.json").write_text(
                json.dumps(mappings, indent=2) + "\n")
            sources = [str(p.relative_to(ROOT)) for p in sorted(lowered.glob("*.sv"))]
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "x3_smoke_tb",
                            "-o", str(binary.relative_to(ROOT)), *sources,
                            "tests/x3_smoke_tb.sv"], "compile")
        output = experiment.command([
            "vvp", str(binary.relative_to(ROOT)),
            f"+image={image.relative_to(ROOT)}", f"+words={metadata['bytes'] // 4}",
            f"+memory={(experiment.path / 'memory.hex').relative_to(ROOT)}",
            f"+expected={(experiment.path / 'expected.hex').relative_to(ROOT)}",
            f"+seed={args.seed}"], "simulate")
        if "X3_FIRMWARE_SMOKE_PASS" not in output:
            raise AssertionError("missing firmware comparisons")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
