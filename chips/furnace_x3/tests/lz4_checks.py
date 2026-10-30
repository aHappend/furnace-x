"""Independent raw/compressed LZ4 framing, checksums, history and malformed data."""

import argparse
from pathlib import Path
import random
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crypto_reference import FrameError, known_answers, lz4_decode, xxh32
from record import Experiment, ROOT


def frame(blocks, plaintext, flags=0x7c):
    header = bytes((flags, 0x40))
    if flags & 8:
        header += struct.pack("<Q", len(plaintext))
    result = bytearray(b"\x04\x22\x4d\x18" + header + bytes(((xxh32(header) >> 8) & 255,)))
    for raw, data in blocks:
        result += struct.pack("<I", len(data) | (0x80000000 if raw else 0)) + data
        if flags & 16:
            result += struct.pack("<I", xxh32(data))
    result += bytes(4)
    if flags & 4:
        result += struct.pack("<I", xxh32(plaintext))
    return bytes(result)


def fixtures(seed):
    rng = random.Random(seed)
    cases = []

    def add(name, encoded, declared, plain=None, last=None):
        error = 0
        try:
            decoded = lz4_decode(encoded, declared)
            if len(decoded) != declared:
                raise FrameError("declared decoded length")
        except FrameError as failure:
            decoded, error = b"", failure.code
        if plain is not None and (error or decoded != plain):
            raise AssertionError(f"independent known LZ4 block disagrees: {name}")
        if last is not None:
            error = 2
        cases.append((name, encoded, declared, decoded, error,
                      len(encoded)-1 if last is None else last))

    add("empty-frame", frame([], b""), 0, b"")
    for length in (1, 15, 16, 17, 255, 256, 511):
        plain = rng.randbytes(length)
        for flags in (0x60, 0x7c):
            add(f"raw-{length}-{flags}", frame([(True, plain)], plain, flags), length, plain)
    literal = rng.randbytes(37)
    block = bytes((0xf0, len(literal)-15)) + literal
    add("extended-final-literals", frame([(False, block)], literal), len(literal), literal)
    for prefix, offset, match_length in ((b"ABCD", 4, 20), (b"Q", 1, 260),
                                          (rng.randbytes(17), 13, 291)):
        output = bytearray(prefix)
        for _ in range(match_length):
            output.append(output[-offset])
        tail = rng.randbytes(5)
        plain = bytes(output) + tail
        literal_length = len(prefix)
        token = min(literal_length, 15) << 4 | min(match_length-4, 15)
        encoded = bytearray((token,))
        if literal_length >= 15:
            encoded.append(literal_length-15)
        encoded += prefix + struct.pack("<H", offset)
        remaining = match_length-4-15
        if remaining >= 0:
            while remaining >= 255:
                encoded.append(255)
                remaining -= 255
            encoded.append(remaining)
        encoded += bytes((0x50,)) + tail
        add(f"overlap-{offset}-{match_length}", frame([(False, encoded)], plain),
            len(plain), plain)
    prefix = b"abcdefghijklmnop"
    compressed = b"\x0f\x10\x00\x11\x50TAIL!"
    output = bytearray(prefix)
    for _ in range(36):
        output.append(output[-16])
    output += b"TAIL!"
    add("dependent-block-history", frame([(True, prefix), (False, compressed)], bytes(output), 0x5c),
        len(output), bytes(output))
    plain = rng.randbytes(65536)
    add("maximum-64k-block", frame([(True, plain)], plain), len(plain), plain)
    base = frame([(True, b"abcdefg")], b"abcdefg")
    for name, position in (("bad-magic", 0), ("bad-version", 4), ("bad-bd", 5),
                           ("bad-header-checksum", 14), ("bad-block-checksum", 25),
                           ("bad-content-checksum", len(base)-1)):
        changed = bytearray(base)
        changed[position] ^= 0x80
        add(name, bytes(changed), 7)
        if cases[-1][4] == 0:
            raise AssertionError(f"malformed fixture accidentally valid: {name}")
    for offset in (0, 9):
        encoded = b"\x10X" + struct.pack("<H", offset) + b"\x50abcde"
        add(f"bad-match-offset-{offset}", frame([(False, encoded)], b"X"*10), 10)
    add("independent-block-cannot-reference-previous", frame(
        [(True, prefix), (False, compressed)], bytes(output), 0x7c), len(output))
    add("too-few-final-literals", frame([(False, b"\x1fX\x01\x00\x01\x40abcd")],
                                        b"X"*21+b"abcd"), 25)
    add("unterminated-literal-extension", frame([(False, b"\xf0\xff")], b""), 100)
    add("short-declared-output", base, 6)
    add("long-declared-output", base, 8)
    add("trailing-frame-byte", base+b"\0", 7)
    add("early-stream-last", base, 7, last=3)
    add("missing-stream-last", base, 7, last=-1)
    if not any(row[4] == 3 for row in cases):
        raise AssertionError("match-offset error category untested")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    experiment = Experiment("lz4-framing-history", args.repair_of)
    obj = experiment.path / "compile-obj"
    try:
        known_answers()
        cases = fixtures(args.seed)
        trace = experiment.path / "lz4.trace"
        lines = []
        for _, encoded, declared, decoded, error, last in cases:
            lines.append(f"{len(encoded)} {declared} {len(decoded)} {error} {last}\n")
            lines += [f"{value:02x}\n" for value in encoded]
            lines += [f"{value:02x}\n" for value in decoded]
        trace.write_text("".join(lines))
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "lz4_tb", "--Mdir", str(obj.relative_to(ROOT)),
                            "-o", "lz4-sim", "rtl/furnace_lz4_frontend.sv",
                            "rtl/furnace_xxh32.sv", "tests/lz4_tb.sv"], "compile")
        result = experiment.command([str((obj / "lz4-sim").relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}", f"+cases={len(cases)}",
                                     f"+seed={args.seed}"], "simulate")
        if "LZ4_PASS " not in result:
            raise AssertionError("LZ4 comparison summary missing")
        print(result.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    finally:
        for pattern in ("*.o", "*.a", "*.gch"):
            for path in obj.glob(pattern):
                path.unlink()
    experiment.finish()


if __name__ == "__main__":
    main()
