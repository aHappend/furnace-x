"""Execute the shipped real image in an independent RV64/device reference."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT
from rv64_reference import CPU
from soc_reference import SoC
from x3_checks import engine_memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("firmware-instruction-reference")
    try:
        image_path = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", "1",
                            "--in-height", "1", "--fft-n", "8",
                            "--output", str(image_path.relative_to(ROOT))], "firmware-build")
        image = b"".join(struct.pack("<I", int(word, 16))
                         for word in image_path.read_text().split())
        memory, expected = engine_memory(args.seed)
        device = SoC(image, memory, (1, 1, 1, 1, 8), 1, 1, 1, 1)
        struct.pack_into("<10I", device.dmem, 0, 0x80000000, 6, 0x80004000,
                         0x80005000, 0x80006000, 0x80007000, 0, 0, 0, 0)
        cpu = CPU(device)
        while device.run and device.time < 1000000:
            cpu.step()
        if device.run:
            raise AssertionError(f"reference firmware did not halt pc={cpu.pc:#x}")
        if device.mailboxes[0] != [0x58430006]:
            raise AssertionError(f"reference notification: {device.mailboxes[0]}")
        if device.ddr != expected:
            first = next(i for i, (a, b) in enumerate(zip(device.ddr, expected)) if a != b)
            raise AssertionError(f"reference memory offset={first:#x} "
                                 f"got={device.ddr[first]:02x} expected={expected[first]:02x}")
        if (device.dma_completions, device.descriptor_completions, device.frame_completions) != (2, 2, 1):
            raise AssertionError("reference missing device effects")
        if not cpu.traps or any(cause != (1 << 63) | 11 for _, cause, _ in cpu.traps):
            raise AssertionError(f"reference interrupt/synchronous traps: {cpu.traps}")
        (experiment.path / "architectural.json").write_text(json.dumps({
            "retired": cpu.instructions, "instruction_ticks": device.time,
            "interrupt_entries": len(cpu.traps), "traps": cpu.traps,
            "opcode_counts": cpu.opcode_counts,
            "compared_ddr_bytes": len(expected), "final_mailbox": device.mailboxes[0],
        }, indent=2) + "\n")
        print(f"FIRMWARE_REFERENCE_PASS retired={cpu.instructions} interrupts={len(cpu.traps)} "
              f"compared_bytes={len(expected)}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
