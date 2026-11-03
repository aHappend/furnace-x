"""Independent byte-oriented security/compression reference, not DUT evidence.

AES follows FIPS 197; GCM follows SP 800-38D. LZ4 decoding follows the
standard frame/block formats, rather than the parent implementation.
"""

import struct


MASK32 = (1 << 32) - 1
PRIMES = (2654435761, 2246822519, 3266489917, 668265263, 374761393)


def _rot(value, count):
    return ((value << count) | (value >> (32 - count))) & MASK32


def xxh32(data, seed=0):
    data = bytes(data)
    p1, p2, p3, p4, p5 = PRIMES

    def step(accumulator, word):
        return _rot((accumulator + word * p2) & MASK32, 13) * p1 & MASK32

    position = 0
    if len(data) >= 16:
        lanes = [(seed + p1 + p2) & MASK32, (seed + p2) & MASK32,
                 seed & MASK32, (seed - p1) & MASK32]
        while position + 16 <= len(data):
            for lane, word in enumerate(struct.unpack_from("<4I", data, position)):
                lanes[lane] = step(lanes[lane], word)
            position += 16
        result = sum(_rot(value, shift)
                     for value, shift in zip(lanes, (1, 7, 12, 18))) & MASK32
    else:
        result = (seed + p5) & MASK32
    result = (result + len(data)) & MASK32
    while position + 4 <= len(data):
        word = struct.unpack_from("<I", data, position)[0]
        result = _rot((result + word * p3) & MASK32, 17) * p4 & MASK32
        position += 4
    for byte in data[position:]:
        result = _rot((result + byte * p5) & MASK32, 11) * p1 & MASK32
    result ^= result >> 15
    result = result * p2 & MASK32
    result ^= result >> 13
    result = result * p3 & MASK32
    return result ^ (result >> 16)


def _gf8(a, b):
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = ((a << 1) ^ (0x11B if a & 128 else 0)) & 255
        b >>= 1
    return result


def _sbox(byte):
    inverse, base, exponent = 1, byte, 254
    while exponent:
        if exponent & 1:
            inverse = _gf8(inverse, base)
        base = _gf8(base, base)
        exponent >>= 1
    result = inverse ^ 0x63
    for shift in range(1, 5):
        result ^= ((inverse << shift) | (inverse >> (8 - shift))) & 255
    return result


SBOX = tuple(_sbox(byte) for byte in range(256))


def aes128(key, block):
    if len(key) != 16 or len(block) != 16:
        raise ValueError("AES-128 requires a 16-byte key and block")
    expanded = list(key)
    rcon = 1
    while len(expanded) < 176:
        word = expanded[-4:]
        if len(expanded) % 16 == 0:
            word = [SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _gf8(rcon, 2)
        for value in word:
            expanded.append(expanded[-16] ^ value)
    state = [a ^ b for a, b in zip(block, expanded[:16])]
    for round_index in range(1, 11):
        state = [SBOX[state[4 * ((column + row) % 4) + row]]
                 for column in range(4) for row in range(4)]
        if round_index != 10:
            mixed = []
            for column in range(4):
                values = state[4 * column:4 * column + 4]
                for row in range(4):
                    mixed.append(_gf8(values[row], 2)
                                 ^ _gf8(values[(row + 1) % 4], 3)
                                 ^ values[(row + 2) % 4]
                                 ^ values[(row + 3) % 4])
            state = mixed
        state = [a ^ b for a, b in zip(
            state, expanded[16 * round_index:16 * (round_index + 1)])]
    return bytes(state)


def _ghash_multiply(a, b):
    result = 0
    for bit in range(127, -1, -1):
        if (a >> bit) & 1:
            result ^= b
        b = (b >> 1) ^ (0xE1000000000000000000000000000000 if b & 1 else 0)
    return result


def gcm_encrypt(key, nonce, plaintext, aad=b""):
    """Return ciphertext/tag for a 96-bit nonce and a full 128-bit tag."""
    if len(nonce) != 12:
        raise ValueError("the descriptor contract requires a 96-bit nonce")
    initial = nonce + b"\x00\x00\x00\x01"
    ciphertext = bytearray()
    for offset in range(0, len(plaintext), 16):
        counter = offset // 16 + 2
        if counter >= 1 << 32:
            raise ValueError("GCM counter exhausted")
        stream = aes128(key, nonce + counter.to_bytes(4, "big"))
        ciphertext.extend(a ^ b for a, b in zip(plaintext[offset:offset + 16], stream))
    authentication = (aad + bytes((-len(aad)) % 16)
                      + ciphertext + bytes((-len(ciphertext)) % 16)
                      + struct.pack(">QQ", 8 * len(aad), 8 * len(ciphertext)))
    h = int.from_bytes(aes128(key, bytes(16)), "big")
    accumulator = 0
    for offset in range(0, len(authentication), 16):
        accumulator = _ghash_multiply(
            accumulator ^ int.from_bytes(authentication[offset:offset + 16], "big"), h)
    tag = accumulator ^ int.from_bytes(aes128(key, initial), "big")
    return bytes(ciphertext), tag.to_bytes(16, "big")


def lz4_block(data, *, limit=65536, history=b""):
    """Decode literals and overlapping matches with bounded output."""
    data = bytes(data)
    output = bytearray(history[-65535:])
    start, position = len(output), 0

    def length(base):
        nonlocal position
        result = base
        if base == 15:
            while True:
                if position == len(data):
                    raise ValueError("truncated LZ4 length")
                extension = data[position]
                position += 1
                result += extension
                if extension != 255:
                    break
        return result

    while position < len(data):
        token = data[position]
        position += 1
        literals = length(token >> 4)
        if position + literals > len(data) or len(output) - start + literals > limit:
            raise ValueError("invalid LZ4 literals or output limit")
        output.extend(data[position:position + literals])
        position += literals
        if position == len(data):
            return bytes(output[start:])
        if position + 2 > len(data):
            raise ValueError("truncated LZ4 offset")
        offset = int.from_bytes(data[position:position + 2], "little")
        position += 2
        if not offset or offset > len(output):
            raise ValueError("invalid LZ4 match offset")
        count = length(token & 15) + 4
        if len(output) - start + count > limit:
            raise ValueError("LZ4 output limit")
        for _ in range(count):
            output.append(output[-offset])
    raise ValueError("LZ4 block lacks a final literal sequence")


def lz4_frame(data, *, limit=65536):
    """Decode one standard frame; reject dictionaries and trailing bytes."""
    data = bytes(data)
    position = 0

    def take(count):
        nonlocal position
        if position + count > len(data):
            raise ValueError("truncated LZ4 frame")
        result = data[position:position + count]
        position += count
        return result

    if take(4) != b"\x04\x22\x4d\x18":
        raise ValueError("LZ4 frame magic")
    flags, descriptor = take(2)
    if flags >> 6 != 1 or flags & 3 or descriptor & 0x8F:
        raise ValueError("unsupported LZ4 flags")
    block_code = descriptor >> 4
    if block_code not in (4, 5, 6, 7):
        raise ValueError("LZ4 block maximum")
    expected_size = int.from_bytes(take(8), "little") if flags & 8 else None
    header = data[4:position]
    if take(1)[0] != (xxh32(header) >> 8) & 255:
        raise ValueError("LZ4 header checksum")
    output = bytearray()
    while True:
        block_header = int.from_bytes(take(4), "little")
        if block_header == 0:
            break
        size = block_header & 0x7FFFFFFF
        if size == 0 or size > 1 << (8 + 2 * block_code):
            raise ValueError("LZ4 block size")
        block = take(size)
        if flags & 16 and int.from_bytes(take(4), "little") != xxh32(block):
            raise ValueError("LZ4 block checksum")
        remaining = limit - len(output)
        if block_header >> 31:
            decoded = block
        else:
            decoded = lz4_block(block, limit=remaining,
                               history=b"" if flags & 32 else output)
        if len(decoded) > remaining:
            raise ValueError("LZ4 frame output limit")
        output.extend(decoded)
    if flags & 4 and int.from_bytes(take(4), "little") != xxh32(output):
        raise ValueError("LZ4 content checksum")
    if expected_size is not None and expected_size != len(output):
        raise ValueError("LZ4 content size")
    if position != len(data):
        raise ValueError("trailing LZ4 frame data")
    return bytes(output)
