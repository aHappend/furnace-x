"""Independent integer/byte-level oracles; no DUT state or native FP arithmetic."""

import struct


MASK32 = (1 << 32) - 1
QNAN = 0x7FC00000


def signed(x, bits):
    return x - (1 << bits) if x & (1 << (bits - 1)) else x


def round_even(n, shift):
    if shift <= 0:
        return n << -shift
    q, r = divmod(n, 1 << shift)
    half = 1 << (shift - 1)
    return q + (r > half or (r == half and q & 1))


def fp_parts(x):
    sign, exponent, fraction = x >> 31, (x >> 23) & 255, x & 0x7FFFFF
    if exponent == 255:
        return sign, "nan" if fraction else "inf", 0, 0
    return sign, "finite", fraction | (0x800000 if exponent else 0), (
        exponent - 150 if exponent else -149
    )


def fp_pack(sign, magnitude, exponent):
    """Round exact magnitude * 2**exponent once to IEEE binary32."""
    if not magnitude:
        return sign << 31
    leading = magnitude.bit_length() - 1 + exponent
    quantum = max(-149, leading - 23)
    rounded = round_even(magnitude, quantum - exponent)
    if not rounded:
        return sign << 31
    leading = rounded.bit_length() - 1 + quantum
    if leading > 127:
        return (sign << 31) | 0x7F800000
    if leading < -126:
        return (sign << 31) | rounded
    significand = rounded << max(0, 24 - rounded.bit_length())
    significand >>= max(0, rounded.bit_length() - 24)
    return (sign << 31) | ((leading + 127) << 23) | (significand & 0x7FFFFF)


def fp_mul(a, b):
    sa, ka, ma, ea = fp_parts(a)
    sb, kb, mb, eb = fp_parts(b)
    if "nan" in (ka, kb):
        return QNAN
    if ka == "inf" or kb == "inf":
        if (ka == "finite" and not ma) or (kb == "finite" and not mb):
            return QNAN
        return ((sa ^ sb) << 31) | 0x7F800000
    return fp_pack(sa ^ sb, ma * mb, ea + eb)


def fp_add(a, b):
    sa, ka, ma, ea = fp_parts(a)
    sb, kb, mb, eb = fp_parts(b)
    if "nan" in (ka, kb) or (ka == kb == "inf" and sa != sb):
        return QNAN
    if ka == "inf":
        return (sa << 31) | 0x7F800000
    if kb == "inf":
        return (sb << 31) | 0x7F800000
    e = min(ea, eb)
    total = (-1 if sa else 1) * (ma << (ea - e))
    total += (-1 if sb else 1) * (mb << (eb - e))
    if total == 0:
        return (sa << 31) if not ma and not mb and sa == sb else 0
    return fp_pack(total < 0, abs(total), e)


def tensor(mode, weights, activations, accumulator=0):
    if mode == 0:
        total = sum(signed(w, 4) * signed(a, 16) for w, a in zip(weights, activations))
        return (accumulator + total) & ((1 << 64) - 1)
    products = []
    for w, a in zip(weights, activations):
        wf = w << 16 if mode == 1 else fp_pack(w >= 8, abs(signed(w, 4)), 0)
        products.append(fp_mul(wf, a << 16))
    while len(products) > 1:
        products = [fp_add(products[i], products[i + 1]) for i in range(0, len(products), 2)]
    return fp_add(accumulator, products[0])


def rol32(x, n):
    return ((x << n) | ((x & MASK32) >> (32 - n))) & MASK32


def xxh32(data):
    """XXH32 seed zero, direct published algorithm."""
    p1, p2, p3, p4, p5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1
    pos = 0
    if len(data) >= 16:
        v = [(p1 + p2) & MASK32, p2, 0, (-p1) & MASK32]
        while pos + 16 <= len(data):
            words = struct.unpack_from("<4I", data, pos)
            v = [(rol32((s + w * p2) & MASK32, 13) * p1) & MASK32
                 for s, w in zip(v, words)]
            pos += 16
        h = sum(rol32(s, n) for s, n in zip(v, (1, 7, 12, 18))) & MASK32
    else:
        h = p5
    h = (h + len(data)) & MASK32
    while pos + 4 <= len(data):
        h = (rol32((h + int.from_bytes(data[pos:pos + 4], "little") * p3) & MASK32, 17) * p4) & MASK32
        pos += 4
    for b in data[pos:]:
        h = (rol32((h + b * p5) & MASK32, 11) * p1) & MASK32
    h ^= h >> 15
    h = h * p2 & MASK32
    h ^= h >> 13
    h = h * p3 & MASK32
    return h ^ (h >> 16)


def lz4_frame(blocks, decoded, *, independent=False, content_size=False,
              block_checksum=False, content_checksum=False):
    """blocks is a sequence of (raw, encoded_bytes)."""
    flags = 0x40 | (0x20 if independent else 0) | (8 if content_size else 0)
    flags |= (16 if block_checksum else 0) | (4 if content_checksum else 0)
    header = bytes((flags, 0x40))
    if content_size:
        header += struct.pack("<Q", len(decoded))
    out = b"\x04\x22\x4d\x18" + header + bytes(((xxh32(header) >> 8) & 255,))
    for raw, block in blocks:
        out += struct.pack("<I", len(block) | (0x80000000 if raw else 0)) + block
        if block_checksum:
            out += struct.pack("<I", xxh32(block))
    out += bytes(4)
    if content_checksum:
        out += struct.pack("<I", xxh32(decoded))
    return out


def literal_block(data):
    n = len(data)
    out = bytes((min(n, 15) << 4,))
    if n >= 15:
        n -= 15
        out += bytes([255]) * (n // 255) + bytes((n % 255,))
    return out + data


class LZ4Error(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def decode_lz4(frame):
    """Whole-frame byte algorithm, deliberately independent of streaming RTL."""
    pos = 0

    def get(n):
        nonlocal pos
        if pos + n > len(frame):
            raise LZ4Error(2, "truncated frame")
        value = frame[pos:pos + n]
        pos += n
        return value

    if get(4) != b"\x04\x22\x4d\x18":
        raise LZ4Error(2, "magic")
    flags, bd = get(2)
    if flags >> 6 != 1 or flags & 3 or bd != 0x40:
        raise LZ4Error(2, "unsupported flags")
    header = bytes((flags, bd))
    size = None
    if flags & 8:
        size_bytes = get(8)
        size = int.from_bytes(size_bytes, "little")
        header += size_bytes
    if get(1)[0] != (xxh32(header) >> 8) & 255:
        raise LZ4Error(2, "header checksum")
    output = bytearray()
    while True:
        word = int.from_bytes(get(4), "little")
        if word == 0:
            break
        n, raw = word & 0x7FFFFFFF, bool(word >> 31)
        if not 1 <= n <= 65536:
            raise LZ4Error(2, "block size")
        block = get(n)
        if flags & 16 and int.from_bytes(get(4), "little") != xxh32(block):
            raise LZ4Error(2, "block checksum")
        begin = len(output)
        history_begin = begin if flags & 32 else 0
        if raw:
            output.extend(block)
        else:
            cursor = 0
            last_match = None
            final_literals = None

            def extension(base):
                nonlocal cursor
                if base != 15:
                    return base
                length = 15
                while True:
                    if cursor >= len(block):
                        raise LZ4Error(2, "extension truncated")
                    b = block[cursor]
                    cursor += 1
                    length += b
                    if b != 255:
                        return length

            while cursor < len(block):
                token = block[cursor]
                cursor += 1
                literal_length = extension(token >> 4)
                if cursor + literal_length > len(block):
                    raise LZ4Error(2, "literal truncated")
                output.extend(block[cursor:cursor + literal_length])
                cursor += literal_length
                if cursor == len(block):
                    final_literals = literal_length
                    break
                if cursor + 2 > len(block):
                    raise LZ4Error(2, "offset truncated")
                offset = int.from_bytes(block[cursor:cursor + 2], "little")
                cursor += 2
                if not 1 <= offset <= min(65535, len(output) - history_begin):
                    raise LZ4Error(3, "offset outside valid history")
                match_length = extension(token & 15) + 4
                last_match = len(output)
                for _ in range(match_length):
                    output.append(output[-offset])
            if final_literals is None or (
                last_match is not None and (final_literals < 5 or len(output) - last_match < 12)
            ):
                raise LZ4Error(2, "terminal sequence")
        if len(output) - begin > 65536:
            raise LZ4Error(2, "decoded block size")
    if flags & 4 and int.from_bytes(get(4), "little") != xxh32(output):
        raise LZ4Error(2, "content checksum")
    if pos != len(frame) or (size is not None and size != len(output)):
        raise LZ4Error(2, "frame length")
    return bytes(output)


def selftest():
    assert xxh32(b"") == 0x02CC5D05
    assert xxh32(b"a") == 0x550D7456
    assert xxh32(b"abc") == 0x32D153FF
    assert fp_add(0x3F800000, 0x33800000) == 0x3F800000
    assert fp_add(0x3F800001, 0x33800000) == 0x3F800002
    assert fp_add(0x80000000, 0x80000000) == 0x80000000
    assert fp_add(0x3F800000, 0xBF800000) == 0
    assert fp_mul(1, 0x3F800000) == 1
    assert fp_mul(1, 0x3F000000) == 0
    assert fp_mul(3, 0x3F000000) == 2
    assert fp_mul(0, 0x7F800000) == QNAN
    assert fp_mul(0x7F7FFFFF, 0x40000000) == 0x7F800000
