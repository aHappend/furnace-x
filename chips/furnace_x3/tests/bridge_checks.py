"""CPU-to-512-bit bridge byte-lane, backpressure and fault oracle."""

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def commands(seed):
    rng = random.Random(seed)
    memory = bytearray((i*37 + (i >> 8)*19 + seed) & 255 for i in range(4096))
    result = []

    def add(write, instruction, address, size, data=0, strobe=0, fault=0, invalid=False):
        offset = address-0x80000000
        response = 0
        if not invalid:
            if write:
                for byte in range(8):
                    if strobe >> byte & 1:
                        memory[offset+byte] = data >> (8*byte) & 255
            elif not fault:
                response = int.from_bytes(memory[offset:offset+(1 << size)], "little")
        result.append((write, instruction, address, size, data, strobe,
                       fault, int(invalid), response, int(invalid or fault != 0)))

    for size in range(4):
        for offset in range(0, 128, 1 << size):
            address = 0x80000000+offset
            add(0, 0, address, size)
            for strobe in (0, (1 << (1 << size))-1, rng.randrange(1 << (1 << size))):
                add(1, 0, address, size, rng.getrandbits(64), strobe)
                add(0, 0, address, size)
    for address in range(0x80000000, 0x80000040, 4):
        add(0, 1, address, 2)
    for size in range(4):
        for address in (0x10000, 0x7fffffc0, 0x180000000, 0xffffffff80000000):
            add(0, 0, address, size, invalid=True)
            add(1, 0, address, size, rng.getrandbits(64), (1 << (1 << size))-1,
                invalid=True)
        if size:
            add(0, 0, 0x80000001, size, invalid=True)
            add(1, 0, 0x80000001, size, 1, 1, invalid=True)
        if size != 2:
            add(0, 1, 0x80000000, size, invalid=True)
        add(1, 1, 0x80000000, size, 1, 1, invalid=True)
        if size < 3:
            add(1, 0, 0x80000000, size, 1, 1 << (1 << size), invalid=True)
    for fault in (1, 2, 3):
        add(0, 0, 0x80000000, 3, fault=fault)
    for fault in (4, 5):
        add(1, 0, 0x80000000, 3, rng.getrandbits(64), 255, fault=fault)
    add(0, 0, 0x80000000, 3)
    return result, memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("cpu-ddr-bridge")
    try:
        rows, expected = commands(args.seed)
        trace = experiment.path / "bridge.trace"
        trace.write_text("".join(
            f"{w} {i} {a:016x} {s} {d:016x} {st:02x} {f} {bad} {r:016x} {e}\n"
            for w, i, a, s, d, st, f, bad, r, e in rows))
        image = experiment.path / "expected.hex"
        image.write_text("".join(f"{value:02x}\n" for value in expected))
        binary = experiment.path / "bridge.vvp"
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "bridge_tb",
                            "-o", str(binary.relative_to(ROOT)),
                            "rtl/furnace_x3_cpu_axi_bridge.sv", "tests/bridge_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}",
                                     f"+expected={image.relative_to(ROOT)}",
                                     f"+rows={len(rows)}", f"+seed={args.seed}"], "simulate")
        if f"BRIDGE_PASS rows={len(rows)} " not in output:
            raise AssertionError("bridge comparisons missing")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
