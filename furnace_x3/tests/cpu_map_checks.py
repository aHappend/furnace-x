"""Real X3 CPU mapping faults: no truncated addresses or MMIO read side effects."""

import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_isa_checks import Program, csr
from cpu_reference import immediate, r_instruction, store
from record import Experiment, ROOT
from rv64_reference import CPU
from soc_reference import SoC


CASES = (
    ("instruction-mmio", 0x2420, "fetch", 1),
    ("imem-readonly", 0x10000, "store", 7),
    ("mmio-width-no-take", 0x2420, "load", 5),
    ("upper-load-no-ddr", 0x180000000, "load", 5),
    ("upper-store-no-ddr", 0x180000000, "store", 7),
    ("upper-fetch-no-truncation", 0x100010000, "fetch", 1),
    ("misaligned-load-no-take", 0x2421, "load", 4),
    ("misaligned-store-no-give", 0x2425, "store", 6),
    ("illegal-instruction", 0x2420, "illegal", 2),
    ("machine-ecall", 0x2420, "ecall", 11),
)


def image_for(address, operation):
    p = Program()
    p.constant(6, 0x10100)
    p.emit(csr(0, 0x305, 6, 1))
    if address >> 32:
        p.emit(immediate(5, 0, address >> 32))
        p.emit(immediate(5, 5, 32, 1))
        p.constant(7, address & 0xffffffff)
        p.emit(immediate(7, 7, 32, 1))
        p.emit(immediate(7, 7, 32, 5))
        p.emit(r_instruction(5, 5, 7, 6))
    else:
        p.constant(5, address)
    instruction = {"fetch": immediate(0, 5, 0, 0, 0x67),
                   "store": store(0, 5, 0, 2), "load": immediate(8, 5, 0, 3, 3),
                   "illegal": 0xffffffff, "ecall": 0x73}[operation]
    p.emit(instruction)
    p.emit(0x100073)
    p.pc = 0x10100
    p.constant(5, 0x2000)
    p.emit(store(0, 5, 4, 2))
    p.resolve()
    return b"".join(struct.pack("<I", p.words.get(pc, 0x13))
                    for pc in range(0x10000, max(p.words)+4, 4))


def main():
    experiment = Experiment("x3-cpu-memory-map-faults")
    try:
        memory = bytes((i*37+(i >> 8)*19)&255 for i in range(32768))
        memory_path = experiment.path / "memory.hex"
        memory_path.write_text("".join(f"{value:02x}\n" for value in memory))
        binary = experiment.path / "map.vvp"
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "x3_smoke_tb",
                            "-o", str(binary.relative_to(ROOT)), *sources,
                            "tests/x3_smoke_tb.sv"], "compile")
        coverage = {}
        for index, (name, address, operation, cause) in enumerate(CASES):
            image = image_for(address, operation)
            device = SoC(image, memory, (1, 1, 1, 1, 8), 1, 1, 1, 1)
            device.semaphores[2] = 1
            cpu = CPU(device)
            while device.run and device.time < 1000:
                cpu.step()
            if (device.run or len(cpu.traps) != 1 or cpu.traps[0][1] != cause or
                    device.semaphores[2] != 1 or device.ddr != memory):
                raise AssertionError(f"architectural mapping oracle: {name}/{cpu.traps}")
            trap_pc = cpu.traps[0][0]
            image_path = experiment.path / f"{name}.hex"
            words = struct.unpack(f"<{len(image)//4}I", image)
            image_path.write_text("".join(f"{word:08x}\n" for word in words))
            output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
                f"+image={image_path.relative_to(ROOT)}", f"+words={len(words)}",
                f"+memory={memory_path.relative_to(ROOT)}",
                f"+expected={memory_path.relative_to(ROOT)}", f"+probe_case={index+1}",
                f"+probe_cause={cause}", f"+probe_pc={trap_pc:016x}",
                f"+probe_error={device.errors & 8}"], name)
            if "X3_CPU_MAP_FAULT_PASS" not in output:
                raise AssertionError(f"mapping comparisons absent: {name}")
            coverage[name] = {"image_sha256": hashlib.sha256(image).hexdigest(),
                              "cause": cause, "pc": trap_pc, "retired": cpu.instructions,
                              "semaphore2": 1, "compared_external_transactions": 0}
            print(output.strip())
        (experiment.path / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        print(f"CPU_MAP_PASS cases={len(coverage)}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
