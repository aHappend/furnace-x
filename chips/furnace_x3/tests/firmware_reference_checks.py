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
from matrix_checks import CELLS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--cell", choices=CELLS)
    args = parser.parse_args()
    experiment = Experiment("firmware-instruction-reference")
    try:
        tile, ring, fusion, mailbox, iw, ih, ow, oh, fft_n, max_dma = (
            CELLS[args.cell] if args.cell else (64, 1, 1, 1, 1, 1, 1, 1, 8, 1))
        graphs = max(2, ring+1, 2*fusion+1, 2*mailbox+1) if args.cell else 1
        image_path = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", str(iw),
                            "--in-height", str(ih), "--fft-n", str(fft_n),
                            "--output", str(image_path.relative_to(ROOT))], "firmware-build")
        image = b"".join(struct.pack("<I", int(word, 16))
                         for word in image_path.read_text().split())
        device = None
        results = []
        for graph in range(graphs):
            memory, expected = engine_memory(args.seed, (iw, ih, ow, oh, fft_n),
                ring, fusion, max_dma, graph, 131072 if args.cell else 32768, tile)
            if device is None:
                device = SoC(image, memory, (iw, ih, ow, oh, fft_n), ring, fusion, mailbox, max_dma)
            else:
                if device.events or device.legacy_busy or device.dma_busy:
                    raise AssertionError("reference reboot with unfinished obligations")
                device.ddr = bytearray(memory)
                device.run = True
            struct.pack_into("<10I", device.dmem, 0, 0x80000000, 6, 0x80004000,
                             0x80005000, 0x80006000, 0x80007000, 0, 0, 0, 0)
            cpu = CPU(device)
            limit = device.time + 2000000
            while device.run and device.time < limit:
                cpu.step()
            if device.run:
                raise AssertionError(f"reference firmware did not halt pc={cpu.pc:#x}")
            if device.mailboxes[0] != [0x58430006]:
                raise AssertionError(f"reference notification: {device.mailboxes[0]}")
            if device.ddr != expected:
                first = next(i for i, (a, b) in enumerate(zip(device.ddr, expected)) if a != b)
                raise AssertionError(f"reference graph={graph} memory offset={first:#x} "
                                     f"got={device.ddr[first]:02x} expected={expected[first]:02x}")
            if (device.dma_completions, device.descriptor_completions,
                    device.frame_completions) != (2*(graph+1), 2*(graph+1), graph+1):
                raise AssertionError("reference missing device effects")
            if not cpu.traps or any(cause != (1 << 63) | 11 for _, cause, _ in cpu.traps):
                raise AssertionError(f"reference interrupt/synchronous traps: {cpu.traps}")
            results.append({"graph": graph, "retired": cpu.instructions,
                            "interrupt_entries": len(cpu.traps), "traps": cpu.traps,
                            "opcode_counts": cpu.opcode_counts,
                            "compared_ddr_bytes": len(expected),
                            "final_mailbox": list(device.mailboxes[0])})
            device.mmio_read(0x2600)
            print(f"FIRMWARE_REFERENCE_GRAPH graph={graph} retired={cpu.instructions} "
                  f"interrupts={len(cpu.traps)} compared_bytes={len(expected)}", flush=True)
        (experiment.path / "architectural.json").write_text(json.dumps({
            "seed": args.seed, "cell": args.cell, "instruction_ticks": device.time,
            "graphs": results,
        }, indent=2) + "\n")
        print(f"FIRMWARE_REFERENCE_PASS graphs={len(results)} "
              f"retired={sum(r['retired'] for r in results)} "
              f"compared_bytes={sum(r['compared_ddr_bytes'] for r in results)}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
