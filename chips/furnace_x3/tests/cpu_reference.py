"""RV64 arithmetic oracle and instruction encodings, independent of RTL/assembler."""

MASK = (1 << 64) - 1


def signed(value, bits=64):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def r_instruction(rd, rs1, rs2, funct3, funct7=0, word=False):
    return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | (
        0x3b if word else 0x33)


def immediate(rd, rs1, value, funct3=0, opcode=0x13):
    return (value & 4095) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def store(rs2, rs1, offset=0, size=3):
    offset &= 4095
    return (offset >> 5) << 25 | rs2 << 20 | rs1 << 15 | size << 12 | (
        offset & 31) << 7 | 0x23


def m_result(op, a, b, word=False):
    bits = 32 if word else 64
    mask = (1 << bits) - 1
    a, b = a & mask, b & mask
    sa, sb = signed(a, bits), signed(b, bits)
    if op == 0:
        result = a * b
    elif op in (1, 2, 3):
        left = sa if op in (1, 2) else a
        right = sb if op == 1 else b
        result = (left * right) >> bits
    elif op in (4, 6):
        if b == 0:
            quotient, remainder = mask, a
        else:
            quotient = abs(sa) // abs(sb)
            if (sa < 0) != (sb < 0):
                quotient = -quotient
            remainder = sa - quotient * sb
        result = quotient if op == 4 else remainder
    elif op in (5, 7):
        result = (a // b if b else mask) if op == 5 else (a % b if b else a)
    else:
        raise ValueError(op)
    result &= mask
    return (signed(result, 32) if word else result) & MASK


def alu_result(op, a, b, word=False):
    bits = 32 if word else 64
    mask = (1 << bits) - 1
    a &= mask
    b &= mask
    shift = b & (bits - 1)
    result = {
        "add": lambda: a + b, "sub": lambda: a - b,
        "sll": lambda: a << shift, "srl": lambda: a >> shift,
        "sra": lambda: signed(a, bits) >> shift,
        "slt": lambda: int(signed(a, bits) < signed(b, bits)),
        "sltu": lambda: int(a < b), "xor": lambda: a ^ b,
        "or": lambda: a | b, "and": lambda: a & b,
    }[op]() & mask
    return (signed(result, 32) if word else result) & MASK
