"""Preserved 128-bit transactions: all quarters, original IDs, faults and AW/W order."""

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def commands(seed):
    rng = random.Random(seed)
    memory = bytearray((i*37+(i >> 8)*19+seed)&255 for i in range(4096))
    result = []

    def add(write, address, data=0, strobe=0, size=4, fault=0, invalid=False):
        response = 0
        if not invalid:
            offset = address-0x80000000
            if write:
                for byte in range(16):
                    if strobe >> byte & 1:
                        memory[offset+byte] = data >> (8*byte) & 255
            elif not fault:
                response = int.from_bytes(memory[offset:offset+16], "little")
        result.append((write, address, size, data, strobe, fault, int(invalid),
                       response, int(invalid or fault != 0)))

    for offset in range(0, 256, 16):
        address = 0x80000000+offset
        add(0, address)
        for strobe in (0, 0xffff, 0x5555, 0xaaaa, rng.getrandbits(16)):
            add(1, address, rng.getrandbits(128), strobe)
            add(0, address)
    for address in (0x10000, 0x7ffffff0, 0x80000001, 0x80000008):
        add(0, address, invalid=True)
        add(1, address, 1, 0xffff, invalid=True)
    for size in (0, 1, 2, 3, 5, 6, 7):
        add(0, 0x80000000, size=size, invalid=True)
        add(1, 0x80000000, 1, 0xffff, size=size, invalid=True)
    for fault in (6, 7, 9):
        add(0, 0x80000000, fault=fault, invalid=True)
        add(1, 0x80000000, 1, 0xffff, fault=fault, invalid=True)
    add(1, 0x80000000, 1, 0xffff, fault=8, invalid=True)
    for fault in (1, 2, 3):
        add(0, 0x80000000, fault=fault)
    for fault in (4, 5):
        add(1, 0x80000000, rng.getrandbits(128), 0xffff, fault=fault)
    add(0, 0x80000000)
    return result, memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("legacy-width-adapter")
    try:
        rows, expected = commands(args.seed)
        trace = experiment.path / "adapter.trace"
        trace.write_text("".join(
            f"{w} 0 {a:016x} {s} {d:032x} {st:04x} {f} {bad} {r:032x} {e}\n"
            for w, a, s, d, st, f, bad, r, e in rows))
        image = experiment.path / "expected.hex"
        image.write_text("".join(f"{value:02x}\n" for value in expected))
        binary = experiment.path / "adapter.vvp"
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "bridge_tb",
                            "-Pbridge_tb.ADAPTER=1", "-o", str(binary.relative_to(ROOT)),
                            "rtl/furnace_axi128_to512.sv", "tests/bridge_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}",
                                     f"+expected={image.relative_to(ROOT)}",
                                     f"+rows={len(rows)}", f"+seed={args.seed}"], "simulate")
        if f"BRIDGE_PASS rows={len(rows)} " not in output:
            raise AssertionError("legacy width/ID comparisons absent")
        print("ADAPTER_" + output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
