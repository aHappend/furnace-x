"""Instruction-level RV64IM/Zicsr interpreter with precise public-bus effects.

This is an architectural model, not a timing/FSM model. Device operations are
callbacks; all arithmetic is mathematical Python integer arithmetic. No RTL,
firmware assembler helpers or observed DUT values are imported.
"""

from cpu_reference import MASK, alu_result, m_result, signed


class BusFault(Exception):
    pass


class ArchitecturalTrap(Exception):
    def __init__(self, cause, value):
        self.cause, self.value = cause, value


class CPU:
    def __init__(self, bus):
        self.bus = bus
        self.x = [0] * 32
        self.pc = 0x10000
        self.csrs = {0x300: 0x1800, 0x301: 0x8000000000001100,
                     0x304: 0, 0x305: 0, 0x340: 0, 0x341: 0,
                     0x342: 0, 0x343: 0, 0xb00: 0, 0xb02: 0}
        self.waiting = False
        self.instructions = 0
        self.traps = []
        self.opcode_counts = {}

    def csr_read(self, address):
        if address == 0x344:
            return 0x800 if self.bus.external_irq() else 0
        if address in (0xc00, 0xc02):
            return self.csrs[address - 0x100]
        if address not in self.csrs:
            raise ArchitecturalTrap(2, self.instruction)
        return self.csrs[address]

    def csr_write(self, address, value):
        if address in (0xc00, 0xc02) or address not in (*self.csrs, 0x344):
            raise ArchitecturalTrap(2, self.instruction)
        if address == 0x305 and value & 3:
            raise ArchitecturalTrap(2, self.instruction)
        if address == 0x300:
            value = (value & 0x88) | 0x1800
        elif address == 0x304:
            value &= 0x800
        elif address == 0x341:
            value &= ~3
        elif address in (0x301, 0x344):
            return
        self.csrs[address] = value & MASK

    def trap(self, cause, value):
        self.traps.append((self.pc, cause, value))
        self.csrs[0x341] = self.pc & ~3
        self.csrs[0x342], self.csrs[0x343] = cause, value & MASK
        status = self.csrs[0x300]
        self.csrs[0x300] = (status & ~0x88) | ((status & 8) << 4) | 0x1800
        self.pc = self.csrs[0x305]
        self.waiting = False
        self.bus.trap_event()

    def load(self, address, size, instruction=False):
        if address % size:
            raise ArchitecturalTrap(0 if instruction else 4, address)
        try:
            return self.bus.read(address, size, instruction)
        except BusFault as error:
            self.bus.core_bus_error()
            raise ArchitecturalTrap(1 if instruction else 5, address) from error

    def store(self, address, size, value):
        if address % size:
            raise ArchitecturalTrap(6, address)
        try:
            self.bus.write(address, size, value & ((1 << (size * 8)) - 1))
        except BusFault as error:
            self.bus.core_bus_error()
            raise ArchitecturalTrap(7, address) from error

    def step(self):
        self.bus.tick()
        self.csrs[0xb00] = (self.csrs[0xb00] + 1) & MASK
        enabled = bool(self.csrs[0x304] & 0x800)
        external = self.bus.external_irq()
        if external and enabled and self.csrs[0x300] & 8:
            self.trap((1 << 63) | 11, 0)
            return
        if self.waiting:
            if not (external and enabled):
                return
            self.waiting = False
        try:
            self.instruction = self.load(self.pc, 4, True)
            self.execute(self.instruction)
            self.instructions += 1
        except ArchitecturalTrap as error:
            self.trap(error.cause, error.value)

    def execute(self, instruction):
        opcode = instruction & 127
        rd, funct3 = (instruction >> 7) & 31, (instruction >> 12) & 7
        rs1, rs2 = (instruction >> 15) & 31, (instruction >> 20) & 31
        funct7 = instruction >> 25
        a, b = self.x[rs1], self.x[rs2]
        imm_i = signed(instruction >> 20, 12)
        imm_s = signed(((instruction >> 25) << 5) | ((instruction >> 7) & 31), 12)
        imm_b = signed(((instruction >> 31) << 12) | (((instruction >> 7) & 1) << 11) |
                       (((instruction >> 25) & 63) << 5) | (((instruction >> 8) & 15) << 1), 13)
        imm_j = signed(((instruction >> 31) << 20) | (((instruction >> 12) & 255) << 12) |
                       (((instruction >> 20) & 1) << 11) | (((instruction >> 21) & 1023) << 1), 21)
        imm_u = signed(instruction & 0xfffff000, 32)
        next_pc = (self.pc + 4) & MASK
        result = None
        written_csr = None

        def illegal():
            raise ArchitecturalTrap(2, instruction)

        if opcode in (0x37, 0x17):
            result = imm_u + (self.pc if opcode == 0x17 else 0)
        elif opcode in (0x6f, 0x67):
            result = next_pc
            if opcode == 0x6f:
                next_pc = (self.pc + imm_j) & MASK
            else:
                if funct3 != 0:
                    illegal()
                next_pc = (a + imm_i) & MASK & ~1
            if next_pc & 3:
                raise ArchitecturalTrap(0, next_pc)
        elif opcode == 0x63:
            predicates = {0: a == b, 1: a != b, 4: signed(a) < signed(b),
                          5: signed(a) >= signed(b), 6: a < b, 7: a >= b}
            if funct3 not in predicates:
                illegal()
            if predicates[funct3]:
                next_pc = (self.pc + imm_b) & MASK
                if next_pc & 3:
                    raise ArchitecturalTrap(0, next_pc)
        elif opcode == 3:
            if funct3 == 7:
                illegal()
            size = 1 << (funct3 & 3)
            result = self.load((a + imm_i) & MASK, size)
            if funct3 < 4:
                result = signed(result, 8 * size)
        elif opcode == 0x23:
            if funct3 > 3:
                illegal()
            self.store((a + imm_s) & MASK, 1 << funct3, b)
        elif opcode in (0x13, 0x1b, 0x33, 0x3b):
            word = opcode in (0x1b, 0x3b)
            register = opcode in (0x33, 0x3b)
            if register and funct7 == 1:
                if word and funct3 in (1, 2, 3):
                    illegal()
                result = m_result(funct3, a, b, word)
            else:
                functions = {0: "add", 1: "sll", 2: "slt", 3: "sltu",
                             4: "xor", 5: "srl", 6: "or", 7: "and"}
                if register:
                    if funct7 == 32 and funct3 in (0, 5):
                        functions[funct3] = "sub" if funct3 == 0 else "sra"
                    elif funct7 != 0:
                        illegal()
                elif funct3 in (1, 5):
                    encoding = instruction >> (25 if word else 26)
                    if encoding == (32 if word else 16) and funct3 == 5:
                        functions[5] = "sra"
                    elif encoding != 0:
                        illegal()
                if word and funct3 not in (0, 1, 5):
                    illegal()
                result = alu_result(functions[funct3], a, b if register else imm_i & MASK, word)
        elif opcode == 0x0f:
            if funct3 not in (0, 1):
                illegal()
            if funct3 == 0 and ((instruction >> 28) or rs1 or rd):
                illegal()
            if funct3 == 1 and ((instruction >> 15) or rd):
                illegal()
        elif opcode == 0x73:
            if funct3 == 0:
                if instruction == 0x73:
                    raise ArchitecturalTrap(11, 0)
                if instruction == 0x100073:
                    raise ArchitecturalTrap(3, self.pc)
                if instruction == 0x30200073:
                    next_pc = self.csrs[0x341]
                    status = self.csrs[0x300]
                    self.csrs[0x300] = (status & ~8) | ((status >> 4) & 8) | 0x1880
                elif instruction == 0x10500073:
                    self.waiting = True
                else:
                    illegal()
            elif funct3 == 4:
                illegal()
            else:
                address = instruction >> 20
                result = self.csr_read(address)
                source = rs1 if funct3 & 4 else a
                operation = funct3 & 3
                write = operation == 1 or rs1 != 0
                if write:
                    value = source if operation == 1 else (
                        result | source if operation == 2 else result & ~source)
                    self.csr_write(address, value)
                    written_csr = address
        else:
            illegal()
        if result is not None and rd:
            self.x[rd] = result & MASK
        self.x[0] = 0
        self.pc = next_pc
        if written_csr != 0xb02:
            self.csrs[0xb02] = (self.csrs[0xb02] + 1) & MASK
        key = f"{opcode:02x}/{funct3}/{funct7 if opcode in (0x33, 0x3b) else 0}"
        self.opcode_counts[key] = self.opcode_counts.get(key, 0) + 1
