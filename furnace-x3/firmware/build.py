#!/usr/bin/env python3
"""Deterministic RV64IM firmware assembler; requires only Python 3."""

import argparse
import ast
import hashlib
import json
import operator
from pathlib import Path
import re
import struct


REGISTERS = {f"x{i}": i for i in range(32)}
REGISTERS.update(zip(
    "zero ra sp gp tp t0 t1 t2 s0 s1 a0 a1 a2 a3 a4 a5 a6 a7 "
    "s2 s3 s4 s5 s6 s7 s8 s9 s10 s11 t3 t4 t5 t6".split(),
    range(32),
))
REGISTERS["fp"] = 8
OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.LShift: operator.lshift, ast.RShift: operator.rshift,
    ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
}


def expression(text, symbols):
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in symbols:
            return symbols[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else (
                ~value if isinstance(node.op, ast.Invert) else value)
        raise ValueError(f"unsupported or unresolved expression: {text}")
    return visit(ast.parse(text, mode="eval").body)


def register(text):
    if text not in REGISTERS:
        raise ValueError(f"unknown register: {text}")
    return REGISTERS[text]


def signed_immediate(value, width):
    if not -(1 << (width - 1)) <= value < (1 << (width - 1)):
        raise ValueError(f"immediate {value} does not fit signed {width} bits")
    return value & ((1 << width) - 1)


def load_constant(rd, value):
    if not -(1 << 63) <= value < (1 << 64):
        raise ValueError("constant outside RV64 range")
    if value >= 1 << 63:
        value -= 1 << 64
    if -2048 <= value <= 2047:
        return [("addi", [rd, "zero", str(value)])]
    if -(1 << 31) <= value < (1 << 31):
        lo = ((value + 2048) & 4095) - 2048
        high = ((value - lo) >> 12) & 0xfffff
        result = [("lui", [rd, str(high)])]
        if lo:
            result.append(("addiw", [rd, rd, str(lo)]))
        return result
    lo = ((value + 2048) & 4095) - 2048
    result = load_constant(rd, (value - lo) >> 12)
    result.append(("slli", [rd, rd, "12"]))
    if lo:
        result.append(("addi", [rd, rd, str(lo)]))
    return result


def expand(op, args, symbols, labels_known):
    if op in ("li", "la"):
        value = expression(args[1], symbols) if labels_known or op == "li" else 0
        # All image labels fit the fixed, positive IMEM address range.
        if op == "la":
            lo = ((value + 2048) & 4095) - 2048
            return [("lui", [args[0], str(((value - lo) >> 12) & 0xfffff)]),
                    ("addi", [args[0], args[0], str(lo)])]
        return load_constant(args[0], value)
    if op == "mv":
        return [("addi", [args[0], args[1], "0"])]
    if op == "j":
        return [("jal", ["zero", args[0]])]
    if op == "call":
        return [("jal", ["ra", args[0]])]
    if op == "ret":
        return [("jalr", ["zero", "0(ra)"])]
    if op == "nop":
        return [("addi", ["zero", "zero", "0"])]
    return [(op, args)]


BRANCH = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}
INVERSE = {"beq": "bne", "bne": "beq", "blt": "bge", "bge": "blt",
           "bltu": "bgeu", "bgeu": "bltu"}
LOAD = {"lb": 0, "lh": 1, "lw": 2, "ld": 3, "lbu": 4, "lhu": 5, "lwu": 6}
STORE = {"sb": 0, "sh": 1, "sw": 2, "sd": 3}
R_ALU = {
    "add": (0x33, 0, 0), "sub": (0x33, 0, 0x20),
    "sll": (0x33, 1, 0), "slt": (0x33, 2, 0), "sltu": (0x33, 3, 0),
    "xor": (0x33, 4, 0), "srl": (0x33, 5, 0), "sra": (0x33, 5, 0x20),
    "or": (0x33, 6, 0), "and": (0x33, 7, 0),
    "addw": (0x3b, 0, 0), "subw": (0x3b, 0, 0x20),
    "sllw": (0x3b, 1, 0), "srlw": (0x3b, 5, 0), "sraw": (0x3b, 5, 0x20),
}
for _i, _name in enumerate("mul mulh mulhsu mulhu div divu rem remu".split()):
    R_ALU[_name] = (0x33, _i, 1)
for _name, _func in (("mulw", 0), ("divw", 4), ("divuw", 5), ("remw", 6), ("remuw", 7)):
    R_ALU[_name] = (0x3b, _func, 1)
I_ALU = {"addi": (0x13, 0), "slti": (0x13, 2), "sltiu": (0x13, 3),
         "xori": (0x13, 4), "ori": (0x13, 6), "andi": (0x13, 7),
         "addiw": (0x1b, 0)}


def memory_operand(text, symbols):
    match = re.fullmatch(r"(.+)\((\w+)\)", text)
    if not match:
        raise ValueError(f"expected offset(register), got {text}")
    return signed_immediate(expression(match[1], symbols), 12), register(match[2])


def encode(op, args, pc, symbols):
    val = lambda text: expression(text, symbols)
    if op in R_ALU:
        opcode, func, high = R_ALU[op]
        return high << 25 | register(args[2]) << 20 | register(args[1]) << 15 | (
            func << 12) | register(args[0]) << 7 | opcode
    if op in I_ALU:
        opcode, func = I_ALU[op]
        return signed_immediate(val(args[2]), 12) << 20 | register(args[1]) << 15 | (
            func << 12) | register(args[0]) << 7 | opcode
    if op in ("slli", "srli", "srai", "slliw", "srliw", "sraiw"):
        word = op.endswith("w")
        shift = val(args[2])
        if not 0 <= shift < (32 if word else 64):
            raise ValueError("shift amount outside instruction width")
        func = 1 if op.startswith("sll") else 5
        high = 0x400 if op.startswith("sra") else 0
        return (high | shift) << 20 | register(args[1]) << 15 | func << 12 | (
            register(args[0]) << 7) | (0x1b if word else 0x13)
    if op in LOAD or op == "jalr":
        imm, base = memory_operand(args[1], symbols)
        return imm << 20 | base << 15 | (0 if op == "jalr" else LOAD[op]) << 12 | (
            register(args[0]) << 7) | (0x67 if op == "jalr" else 3)
    if op in STORE:
        imm, base = memory_operand(args[1], symbols)
        return (imm >> 5) << 25 | register(args[0]) << 20 | base << 15 | (
            STORE[op] << 12) | (imm & 31) << 7 | 0x23
    if op in ("lui", "auipc"):
        imm = val(args[1])
        if not 0 <= imm <= 0xfffff:
            raise ValueError("upper immediate outside 20 bits")
        return imm << 12 | register(args[0]) << 7 | (0x37 if op == "lui" else 0x17)
    if op == "jal":
        imm = signed_immediate(val(args[1]) - pc, 21)
        if imm & 1:
            raise ValueError("unaligned jump")
        return (imm >> 20) << 31 | ((imm >> 1) & 1023) << 21 | (
            (imm >> 11) & 1) << 20 | ((imm >> 12) & 255) << 12 | (
            register(args[0]) << 7) | 0x6f
    if op in BRANCH:
        imm = signed_immediate(val(args[2]) - pc, 13)
        if imm & 1:
            raise ValueError("unaligned branch")
        return (imm >> 12) << 31 | ((imm >> 5) & 63) << 25 | register(args[1]) << 20 | (
            register(args[0]) << 15) | BRANCH[op] << 12 | ((imm >> 1) & 15) << 8 | (
            (imm >> 11) & 1) << 7 | 0x63
    if op in ("csrrw", "csrrs", "csrrc", "csrrwi", "csrrsi", "csrrci"):
        immediate = op.endswith("i")
        func = {"csrrw": 1, "csrrs": 2, "csrrc": 3,
                "csrrwi": 5, "csrrsi": 6, "csrrci": 7}[op]
        csr = val(args[1])
        source = val(args[2]) if immediate else register(args[2])
        if not 0 <= csr < 4096 or not 0 <= source < 32:
            raise ValueError("CSR operand out of range")
        return csr << 20 | source << 15 | func << 12 | register(args[0]) << 7 | 0x73
    if op in ("wfi", "mret", "ecall", "ebreak", "fence", "fence.i"):
        return {"wfi": 0x10500073, "mret": 0x30200073, "ecall": 0x73,
                "ebreak": 0x100073, "fence": 0x0ff0000f, "fence.i": 0x100f}[op]
    raise ValueError(f"unsupported assembly instruction: {op}")


def assemble(source, constants, base=0x10000):
    symbols = dict(constants)
    records = []
    pc = base
    for line_number, original in enumerate(source.splitlines(), 1):
        line = original.split("#", 1)[0].strip()
        if not line:
            continue
        if line.endswith(":"):
            label = line[:-1]
            if label in symbols:
                raise ValueError(f"duplicate symbol {label} at line {line_number}")
            symbols[label] = pc
            continue
        if line.startswith(".equ "):
            name, value = line[5:].split(",", 1)
            name = name.strip()
            if name in symbols:
                raise ValueError(f"duplicate constant {name}")
            symbols[name] = expression(value.strip(), symbols)
            continue
        pieces = line.split(None, 1)
        op = pieces[0]
        args = [item.strip() for item in pieces[1].split(",")] if len(pieces) > 1 else []
        expanded = expand(op, args, symbols, False)
        size = 8 if op in BRANCH else 4 * len(expanded)
        records.append((pc, line_number, op, args))
        pc += size
    if pc > base + 16384:
        raise ValueError(f"firmware exceeds 16 KiB IMEM: {pc-base} bytes")
    words = []
    listing = []
    for pc, line_number, op, args in records:
        if op in BRANCH:
            expanded = [(INVERSE[op], [args[0], args[1], str(pc + 8)]),
                        ("jal", ["zero", args[2]])]
        else:
            expanded = expand(op, args, symbols, True)
        for mnemonic, operands in expanded:
            try:
                word = encode(mnemonic, operands, pc, symbols)
            except (ValueError, KeyError, SyntaxError) as exc:
                raise ValueError(f"source line {line_number}: {exc}") from exc
            words.append(word)
            listing.append(f"{pc:08x} {word:08x} {mnemonic} {', '.join(operands)}")
            pc += 4
    return b"".join(struct.pack("<I", word) for word in words), symbols, listing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("firmware/scheduler.S"))
    parser.add_argument("--output", type=Path, default=Path("firmware/scheduler.hex"))
    parser.add_argument("--in-width", type=int, default=8)
    parser.add_argument("--in-height", type=int, default=8)
    parser.add_argument("--fft-n", type=int, choices=(8, 16, 32, 64), default=16)
    args = parser.parse_args()
    if not 1 <= args.in_width <= 64 or not 1 <= args.in_height <= 64:
        parser.error("image dimensions must be 1..64")
    constants = {"IN_WIDTH": args.in_width, "IN_HEIGHT": args.in_height, "FFT_N": args.fft_n}
    source = args.source.read_text(encoding="ascii")
    image, symbols, listing = assemble(source, constants)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(f"{word[0]:08x}" for word in struct.iter_unpack("<I", image)) + "\n",
                           encoding="ascii")
    args.output.with_suffix(".lst").write_text("\n".join(listing) + "\n", encoding="ascii")
    metadata = {"schema": 1, "isa": "RV64IM_Zicsr", "entry": 0x10000,
                "bytes": len(image), "constants": constants,
                "source_sha256": hashlib.sha256(source.encode("ascii")).hexdigest(),
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "symbols": {name: address for name, address in symbols.items()
                            if name not in constants}}
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                                              encoding="ascii")
    print(f"Built {len(image)} bytes of RV64IM firmware: {args.output.as_posix()}")


if __name__ == "__main__":
    main()
