"""Architectural RV64I/Zicsr/trap signatures derived without DUT internals."""

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpu_reference import MASK, immediate, r_instruction, signed, store
from record import Experiment, ROOT
from rv64_reference import BusFault, CPU


def csr(rd, address, source=0, function=2):
    return address << 20 | source << 15 | function << 12 | rd << 7 | 0x73


class Program:
    def __init__(self):
        self.words, self.labels, self.fixups = {}, {}, []
        self.pc = 0x10000
        self.coverage = Counter()

    def emit(self, word):
        self.words[self.pc] = word
        self.pc += 4

    def mark(self, name):
        if name in self.labels:
            raise AssertionError(f"duplicate label {name}")
        self.labels[name] = self.pc

    def constant(self, rd, value):
        upper = (value + 0x800) >> 12
        self.emit((upper & 0xfffff) << 12 | rd << 7 | 0x37)
        self.emit(immediate(rd, rd, value & 4095))

    def target(self, rd, label):
        self.fixups.append(("constant", self.pc, rd, label))
        self.constant(rd, 0)

    def jump(self, rd, label):
        self.fixups.append(("jump", self.pc, rd, label))
        self.emit(0)

    def branch(self, function, rs1, rs2, label):
        self.fixups.append(("branch", self.pc, function, rs1, rs2, label))
        self.emit(0)

    def signature(self, rd=8, address=0x180):
        self.emit(store(rd, 5, address))

    def trap_case(self, name, instruction):
        self.coverage[name] += 1
        label = f"resume-{name}-{self.pc:x}"
        self.target(10, label)
        self.emit(csr(0, 0x340, 10, 1))
        self.emit(instruction)
        self.mark(label)
        self.signature()

    def resolve(self):
        for kind, address, *arguments in self.fixups:
            if kind == "constant":
                rd, label = arguments
                target = self.labels[label]
                self.words[address] = ((target + 0x800) >> 12) << 12 | rd << 7 | 0x37
                self.words[address + 4] = immediate(rd, rd, target & 4095)
                continue
            displacement = self.labels[arguments[-1]] - address
            if kind == "jump":
                rd = arguments[0]
                if displacement & 1 or not -(1 << 20) <= displacement < (1 << 20):
                    raise AssertionError("JAL displacement")
                value = displacement & ((1 << 21) - 1)
                self.words[address] = ((value >> 20) << 31 |
                                       ((value >> 1) & 1023) << 21 |
                                       ((value >> 11) & 1) << 20 |
                                       ((value >> 12) & 255) << 12 | rd << 7 | 0x6f)
            else:
                function, rs1, rs2, _ = arguments
                if displacement & 1 or not -4096 <= displacement < 4096:
                    raise AssertionError("branch displacement")
                value = displacement & 8191
                self.words[address] = ((value >> 12) << 31 |
                                       ((value >> 5) & 63) << 25 | rs2 << 20 |
                                       rs1 << 15 | function << 12 |
                                       ((value >> 1) & 15) << 8 |
                                       ((value >> 11) & 1) << 7 | 0x63)
        if max(self.words) >= 0x14000:
            raise AssertionError("ISA program exceeds public IMEM size")


def build(seed):
    rng = random.Random(seed)
    p = Program()
    p.constant(5, 0x80000000)
    p.emit(immediate(5, 5, 32, 1))
    p.emit(immediate(5, 5, 32, 5))
    p.constant(6, 0x13c00)
    p.emit(csr(0, 0x305, 6, 1))
    operands = [0, MASK, 1 << 63, 0x80000000, 0x7fffffff,
                rng.getrandbits(64), rng.getrandbits(64)]
    initial = bytearray((i * 13 + (i >> 7) * 29 + seed) & 255 for i in range(65536))
    for index, value in enumerate(operands):
        initial[0x400 + 8 * index:0x408 + 8 * index] = value.to_bytes(8, "little")
        for function in (0, 2, 3, 4, 6, 7):
            for value_i in (-2048, -1, 0, 1, 2047):
                p.emit(immediate(6, 5, 0x400 + 8 * index, 3, 3))
                p.emit(immediate(8, 6, value_i, function))
                p.signature()
                p.coverage[f"immediate-{function}"] += 1
        for value_i in (-2048, -1, 0, 1, 2047):
            p.emit(immediate(6, 5, 0x400 + 8 * index, 3, 3))
            p.emit(immediate(8, 6, value_i, 0, 0x1b))
            p.signature()
            p.coverage["addiw"] += 1
        for word, shifts in ((False, (0, 1, 7, 31, 32, 63)),
                             (True, (0, 1, 7, 15, 31))):
            for function, arithmetic in ((1, False), (5, False), (5, True)):
                for shift in shifts:
                    p.emit(immediate(6, 5, 0x400 + 8 * index, 3, 3))
                    p.emit(immediate(8, 6, shift | (0x400 if arithmetic else 0),
                                     function, 0x1b if word else 0x13))
                    p.signature()
                    p.coverage[f"shift-immediate-{word}-{function}-{arithmetic}"] += 1
    for value in (0, 0x7ffff, 0x80000, 0xfffff):
        for opcode in (0x17, 0x37):
            p.emit(value << 12 | 8 << 7 | opcode)
            p.signature()
            p.coverage[f"upper-{opcode}"] += 1
    for left, right in ((1, 1), (1, 2), (-1, 0), (0, -1)):
        p.emit(immediate(6, 0, left))
        p.emit(immediate(7, 0, right))
        for function in (0, 1, 4, 5, 6, 7):
            name = f"branch-{p.pc:x}"
            p.branch(function, 6, 7, name + "-taken")
            p.emit(immediate(8, 0, 10))
            p.jump(0, name + "-join")
            p.mark(name + "-taken")
            p.emit(immediate(8, 0, 20))
            p.mark(name + "-join")
            p.signature()
            p.coverage[f"branch-{function}"] += 1
    p.emit(immediate(6, 0, 3))
    p.mark("backward-loop")
    p.emit(immediate(6, 6, -1))
    p.branch(1, 6, 0, "backward-loop")
    p.signature(6)
    p.jump(0, "backward-call")
    p.mark("function")
    p.emit(immediate(8, 0, 77))
    p.emit(immediate(1, 1, 1, 6))
    p.emit(immediate(0, 1, 0, 0, 0x67))
    p.mark("backward-call")
    p.jump(1, "function")
    p.signature(1)
    p.signature()
    p.coverage["jal-jalr-backward-bit0"] += 1
    for function in range(7):
        size = 1 << (function & 3)
        for offset in range(0, 16, size):
            p.emit(immediate(8, 5, 0x700 + offset, function, 3))
            p.signature()
            p.coverage[f"load-width-{function}"] += 1
    p.emit(immediate(7, 5, 0x408, 3, 3))
    for size in range(4):
        for offset in range(0, 16, 1 << size):
            p.emit(store(7, 5, 0x740 + offset, size))
            p.emit(immediate(8, 5, 0x740 + offset, size, 3))
            p.signature()
            p.coverage[f"store-width-{size}"] += 1
    for instruction in (immediate(0, 0, 123), r_instruction(0, 7, 7, 0),
                        r_instruction(0, 7, 7, 0, 1),
                        immediate(0, 5, 0x400, 3, 3), csr(0, 0x301)):
        p.emit(instruction)
        p.signature(0)
    for word in (False, True):
        for function in (range(8) if not word else (0, 4, 5, 6, 7)):
            for index in (2, 3):
                for divisor in (0, -1):
                    p.emit(immediate(6, 5, 0x400 + 8 * index, 3, 3))
                    p.emit(immediate(7, 0, divisor))
                    p.emit(r_instruction(8, 6, 7, function, 1, word))
                    p.signature()
                    p.coverage[f"fixed-m-latency-{word}-{function}"] += 1
    for function in (1, 2, 3, 5, 6, 7):
        p.emit(immediate(6, 0, 21))
        p.emit(csr(8, 0x340, 6 if function < 4 else 19, function))
        p.signature()
        p.emit(csr(8, 0x340))
        p.signature()
        p.coverage[f"csr-function-{function}"] += 1
    for address in (0x300, 0x301, 0x304, 0x341, 0x342, 0x343, 0x344):
        p.emit(immediate(6, 0, -1))
        p.emit(csr(8, address, 6, 1))
        p.signature()
        p.emit(csr(8, address))
        p.signature()
        p.emit(csr(0, address, 0, 1))
    p.emit(immediate(6, 0, 1000))
    p.emit(csr(0, 0xb02, 6, 1))
    for address in (0xb02, 0xc02):
        p.emit(csr(8, address))
        p.signature()
    p.emit(immediate(6, 0, 200))
    p.emit(csr(0, 0xb00, 6, 1))
    for address, output in ((0xb00, 0x1e0), (0xc00, 0x1e8)):
        p.emit(csr(8, address))
        p.signature(address=output)
    p.emit(0x0ff0000f)
    p.emit(0x0000100f)
    p.coverage["fence-fencei"] += 1
    p.emit(immediate(8, 0, 123))
    for size in (1, 2, 3):
        p.trap_case(f"load-misaligned-{size}",
                    immediate(8, 5, (1 << size) - 1, size, 3))
        p.trap_case(f"store-misaligned-{size}",
                    store(7, 5, (1 << size) - 1, size))
    for instruction in (0x73, 0x100073, 0xffffffff, 0,
                        immediate(8, 6, 32, 1, 0x1b),
                        r_instruction(8, 6, 7, 1, 1, True),
                        immediate(8, 6, 0x800, 1),
                        immediate(8, 5, 0, 7, 3), store(7, 5, 0, 4),
                        0x1000000f, 0x0001100f,
                        csr(8, 0x123), csr(8, 0xc00, 1, 5),
                        csr(8, 0xc02, 6, 1)):
        p.trap_case(f"illegal-or-system-{instruction:08x}", instruction)
    p.emit(immediate(6, 0, 1))
    p.trap_case("unsupported-mtvec-mode", csr(8, 0x305, 6, 1))
    p.trap_case("jal-misaligned", 0x002000ef)
    p.constant(6, 0x10002)
    p.trap_case("jalr-misaligned", immediate(1, 6, 0, 0, 0x67))
    p.emit(immediate(6, 0, 1))
    p.trap_case("branch-misaligned", 6 << 20 | 6 << 15 | 1 << 8 | 0x63)
    p.emit(6 << 20 | 6 << 15 | 1 << 12 | 1 << 8 | 0x63)
    p.constant(6, 0x8000f000)
    p.emit(immediate(6, 6, 32, 1))
    p.emit(immediate(6, 6, 32, 5))
    for size in range(4):
        p.trap_case(f"load-access-{size}", immediate(8, 6, 0, size, 3))
        p.trap_case(f"store-access-{size}", store(7, 6, 0, size))
    p.trap_case("fetch-access", immediate(0, 6, 0, 0, 0x67))
    p.emit(immediate(6, 0, 1))
    p.emit(immediate(6, 6, 32, 1))
    p.trap_case("untruncated-fetch-64bit", immediate(0, 6, 0, 0, 0x67))
    p.trap_case("untruncated-load-64bit", immediate(8, 6, 0, 3, 3))
    p.trap_case("untruncated-store-64bit", store(7, 6, 0, 3))
    p.constant(6, 0x800)
    p.emit(csr(0, 0x304, 6, 1))
    p.emit(csr(0, 0x300, 0, 1))
    p.emit(0x10500073)
    p.emit(store(0, 5, 0xe0))
    p.signature()
    p.emit(immediate(6, 0, 8))
    p.emit(csr(0, 0x300, 6, 1))
    p.target(10, "interrupt-resume")
    p.emit(csr(0, 0x340, 10, 1))
    p.emit(0x10500073)
    p.mark("interrupt-resume")
    p.signature()
    p.coverage["wfi-masked-wake-and-interrupt-mret"] += 1
    p.emit(csr(0, 0x300, 0, 1))
    p.emit(immediate(0, 0, 0))
    end_pc = p.pc
    if end_pc >= 0x13c00:
        raise AssertionError("main ISA test overlaps its trap handler")
    p.pc = 0x13c00
    for index, address in enumerate((0x342, 0x341, 0x343, 0x300, 0xb02)):
        p.emit(csr(20, address))
        p.emit(store(20, 5, 0x100 + 8 * index))
    p.emit(store(0, 5, 0xe0))
    p.emit(csr(20, 0x340))
    p.emit(csr(0, 0x341, 20, 1))
    p.emit(0x30200073)
    p.resolve()
    return p, initial, end_pc


class TraceBus:
    def __init__(self, program, initial, seed):
        self.program = program
        self.memory = initial[:]
        self.rows = []
        self.random = random.Random(seed)
        self.irq = False
        self.bus_errors = 0
        self.branches = Counter()

    def tick(self):
        pass

    def external_irq(self):
        return self.irq

    def core_bus_error(self):
        pass

    def transaction(self, write, instruction, address, size, data=0, response=0, error=False):
        flag = int(write and address in (0x800001e0, 0x800001e8))
        self.rows.append(
            f"B {int(write)} {int(instruction)} {size.bit_length()-1} {address:016x} "
            f"{data:016x} {((1 << size)-1) if write else 0:02x} {response:016x} "
            f"{int(error)} {self.random.randrange(1, 6)} {flag}")
        if error:
            self.bus_errors += 1
            raise BusFault(f"deliberate access fault {address:x}")

    def read(self, address, size, instruction=False):
        if instruction:
            error = address not in self.program.words
            value = self.program.words.get(address, 0)
            self.transaction(False, True, address, size, response=value, error=error)
            if value == 0x10500073:
                self.irq = True
            return value
        offset = address - 0x80000000
        error = not 0 <= offset < 0xf000 or offset + size > 0xf000
        value = int.from_bytes(self.memory[offset:offset+size], "little") if not error else 0
        self.transaction(False, False, address, size, response=value, error=error)
        return value

    def write(self, address, size, value):
        offset = address - 0x80000000
        error = not 0 <= offset < 0xf000 or offset + size > 0xf000
        # Core request data may contain unstrobed upper bits. Compare those
        # independently using the architectural source register at the caller.
        self.transaction(True, False, address, size, data=self.cpu_store_value, error=error)
        self.memory[offset:offset+size] = value.to_bytes(size, "little")
        if offset == 0xe0:
            self.irq = False

    def trap_event(self):
        pc, cause, _ = self.cpu.traps[-1]
        self.rows.append(f"T {cause:016x} {pc:016x} {self.bus_errors}")


def generate(seed):
    program, initial, end = build(seed)
    bus = TraceBus(program, initial, seed)
    cpu = CPU(bus)
    bus.cpu = cpu
    steps = 0
    while cpu.pc != end:
        instruction = program.words.get(cpu.pc, 0)
        rs2 = (instruction >> 20) & 31
        bus.cpu_store_value = cpu.x[rs2]
        old_pc = cpu.pc
        cpu.step()
        if (instruction & 127 == 0x73 and instruction >> 20 == 0xb00 and
                (instruction >> 12) & 7 in (1, 2, 3, 5, 6, 7) and
                ((instruction >> 12) & 3 == 1 or (instruction >> 15) & 31 != 0)):
            bus.rows.append(f"C {cpu.csrs[0xb00]:016x}")
        if instruction & 127 == 0x63:
            bus.branches[f"{(instruction >> 12) & 7}-{'taken' if cpu.pc != old_pc+4 else 'not-taken'}"] += 1
        steps += 1
        if steps > 10000:
            raise AssertionError(f"architectural test did not terminate pc={cpu.pc:x}")
    for function in (0, 1, 4, 5, 6, 7):
        for outcome in ("taken", "not-taken"):
            if not bus.branches[f"{function}-{outcome}"]:
                raise AssertionError(f"missing branch outcome {function}/{outcome}")
    causes = Counter(str(cause) for _, cause, _ in cpu.traps)
    for cause in (0, 1, 2, 3, 4, 5, 6, 7, 11, (1 << 63) | 11):
        if not causes[str(cause)]:
            raise AssertionError(f"missing trap cause {cause}")
    guarded, halt_cases = [], set()
    for row in bus.rows:
        if row.startswith("B "):
            fields = row.split()
            write, instruction = int(fields[1]), int(fields[2])
            fetched = int(fields[7], 16)
            label, phase = None, 1
            if instruction and "fetch" not in halt_cases:
                label = "fetch"
            elif not instruction and not write and "load" not in halt_cases:
                label = "load"
            elif not instruction and write and "store" not in halt_cases:
                label = "store"
            elif instruction and fetched & 127 in (0x33, 0x3b) and fetched >> 25 == 1:
                candidate = "m-word" if fetched & 127 == 0x3b else "m-64"
                if candidate not in halt_cases:
                    label, phase = candidate, 2
            if label is not None:
                guarded.append(f"H {phase}")
                halt_cases.add(label)
        guarded.append(row)
    if len(halt_cases) != 5:
        raise AssertionError(f"missing halt-drain phases {halt_cases}")
    return guarded, {"instructions": cpu.instructions, "steps": steps,
                      "trap_causes": dict(causes), "branch_outcomes": dict(bus.branches),
                      "halt_drain_cases": sorted(halt_cases),
                      "directed_cases": dict(program.coverage)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    experiment = Experiment("cpu-architectural-isa")
    try:
        rows, coverage = generate(args.seed)
        trace = experiment.path / "isa.trace"
        trace.write_text("\n".join(rows) + "\n")
        binary = experiment.path / "isa.vvp"
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "cpu_isa_tb",
                            "-o", str(binary.relative_to(ROOT)), "rtl/furnace_rv64im_core.sv",
                            "tests/cpu_isa_tb.sv"], "compile")
        output = experiment.command(["vvp", str(binary.relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}", f"+seed={args.seed}"],
                                    "simulate")
        if f"rows={len(rows)} " not in output or "CPU_ISA_PASS" not in output:
            raise AssertionError("architectural comparison coverage summary absent")
        (experiment.path / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
