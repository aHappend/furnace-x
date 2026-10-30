"""Independent standard AES-128/GCM, XXH32 and raw LZ4-frame fixture construction."""

import struct


def gf8(a, b):
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = ((a << 1) ^ (0x11b if a & 128 else 0)) & 255
        b >>= 1
    return result


def substitute(value):
    inverse = 1
    if value == 0:
        inverse = 0
    else:
        for _ in range(254):
            inverse = gf8(inverse, value)
    rotate = lambda x, shift: ((x << shift) | (x >> (8 - shift))) & 255
    return inverse ^ rotate(inverse, 1) ^ rotate(inverse, 2) ^ rotate(inverse, 3) ^ (
        rotate(inverse, 4)) ^ 0x63


SBOX = tuple(substitute(value) for value in range(256))


def aes128(key, block):
    if len(key) != 16 or len(block) != 16:
        raise ValueError("AES-128 block/key size")
    keys = list(key)
    round_constant = 1
    while len(keys) < 176:
        word = keys[-4:]
        if len(keys) % 16 == 0:
            word = [SBOX[v] for v in word[1:] + word[:1]]
            word[0] ^= round_constant
            round_constant = gf8(round_constant, 2)
        keys += [keys[len(keys) - 16 + i] ^ word[i] for i in range(4)]
    state = [v ^ keys[i] for i, v in enumerate(block)]
    for round_index in range(1, 11):
        state = [SBOX[v] for v in state]
        state = [state[4 * ((col + row) % 4) + row] for col in range(4) for row in range(4)]
        if round_index != 10:
            mixed = []
            for col in range(4):
                a, b, c, d = state[col * 4:col * 4 + 4]
                mixed += [gf8(a, 2) ^ gf8(b, 3) ^ c ^ d,
                          a ^ gf8(b, 2) ^ gf8(c, 3) ^ d,
                          a ^ b ^ gf8(c, 2) ^ gf8(d, 3),
                          gf8(a, 3) ^ b ^ c ^ gf8(d, 2)]
            state = mixed
        state = [v ^ keys[16 * round_index + i] for i, v in enumerate(state)]
    return bytes(state)


def gf128(a, b):
    product = 0
    for bit in range(127, -1, -1):
        if (a >> bit) & 1:
            product ^= b
        b = (b >> 1) ^ (0xe1000000000000000000000000000000 if b & 1 else 0)
    return product


def gcm_encrypt(key, nonce, aad, plaintext):
    if len(nonce) != 12:
        raise ValueError("96-bit GCM nonce required")
    ciphertext = bytearray()
    for index in range(0, len(plaintext), 16):
        stream = aes128(key, nonce + struct.pack(">I", 2 + index // 16))
        ciphertext += bytes(a ^ b for a, b in zip(plaintext[index:index + 16], stream))
    h = int.from_bytes(aes128(key, bytes(16)), "big")
    y = 0
    for data in (aad, ciphertext):
        for index in range(0, len(data), 16):
            y = gf128(y ^ int.from_bytes(data[index:index + 16].ljust(16, b"\0"), "big"), h)
    y = gf128(y ^ ((len(aad) * 8) << 64 | len(ciphertext) * 8), h)
    tag = y ^ int.from_bytes(aes128(key, nonce + b"\0\0\0\1"), "big")
    return bytes(ciphertext), tag.to_bytes(16, "big")


def xxh32(data):
    primes = (2654435761, 2246822519, 3266489917, 668265263, 374761393)
    mask = 0xffffffff
    rotate = lambda value, n: ((value << n) | (value >> (32 - n))) & mask
    def consume(accumulator, word):
        return (rotate((accumulator + word * primes[1]) & mask, 13) * primes[0]) & mask
    position = 0
    if len(data) >= 16:
        accumulators = [(primes[0] + primes[1]) & mask, primes[1], 0, (-primes[0]) & mask]
        while position + 16 <= len(data):
            for lane, word in enumerate(struct.unpack_from("<4I", data, position)):
                accumulators[lane] = consume(accumulators[lane], word)
            position += 16
        digest = sum(rotate(v, n) for v, n in zip(accumulators, (1, 7, 12, 18))) & mask
    else:
        digest = primes[4]
    digest = (digest + len(data)) & mask
    while position + 4 <= len(data):
        word = struct.unpack_from("<I", data, position)[0]
        digest = rotate((digest + word * primes[2]) & mask, 17) * primes[3] & mask
        position += 4
    for value in data[position:]:
        digest = rotate((digest + value * primes[4]) & mask, 11) * primes[0] & mask
    digest ^= digest >> 15
    digest = digest * primes[1] & mask
    digest ^= digest >> 13
    digest = digest * primes[2] & mask
    return digest ^ (digest >> 16)


def raw_lz4_frame(data):
    header = b"\x60\x40"
    return b"\x04\x22\x4d\x18" + header + bytes([(xxh32(header) >> 8) & 255]) + (
        struct.pack("<I", 0x80000000 | len(data)) + data + bytes(4))


class FrameError(ValueError):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def lz4_decode(frame, maximum=131072):
    """Parse framing/checksums and decode sequences with a byte-history oracle."""
    cursor = 0

    def take(count):
        nonlocal cursor
        if cursor + count > len(frame):
            raise FrameError("truncated frame")
        data = frame[cursor:cursor + count]
        cursor += count
        return data

    if take(4) != b"\x04\x22\x4d\x18":
        raise FrameError("magic")
    flags, descriptor = take(2)
    if flags >> 6 != 1 or flags & 3 or descriptor != 0x40:
        raise FrameError("unsupported flags/descriptor")
    header = bytes((flags, descriptor))
    content_size = None
    if flags & 8:
        size = take(8)
        header += size
        content_size = int.from_bytes(size, "little")
    if take(1)[0] != ((xxh32(header) >> 8) & 255):
        raise FrameError("header checksum")
    output = bytearray()
    while True:
        length = int.from_bytes(take(4), "little")
        if length == 0:
            break
        raw = bool(length & 0x80000000)
        length &= 0x7fffffff
        if not 0 < length <= 65536:
            raise FrameError("block size")
        block = take(length)
        if flags & 16 and int.from_bytes(take(4), "little") != xxh32(block):
            raise FrameError("block checksum")
        start = len(output)
        if raw:
            output += block
        else:
            position, had_match, last_match = 0, False, 0
            while position < len(block):
                token = block[position]
                position += 1

                def extended(initial):
                    nonlocal position
                    result = initial
                    if initial == 15:
                        while True:
                            if position >= len(block):
                                raise FrameError("truncated length extension")
                            value = block[position]
                            position += 1
                            result += value
                            if value != 255:
                                break
                    return result

                literals = extended(token >> 4)
                if position + literals > len(block):
                    raise FrameError("literal overrun")
                output += block[position:position + literals]
                position += literals
                if position == len(block):
                    if had_match and (literals < 5 or len(output) - start - last_match < 12):
                        raise FrameError("final literal/match constraints")
                    break
                if position + 2 > len(block):
                    raise FrameError("truncated offset")
                offset = int.from_bytes(block[position:position + 2], "little")
                position += 2
                available = len(output) - start if flags & 32 else min(65536, len(output))
                if offset == 0 or offset > available:
                    raise FrameError("unavailable offset", 3)
                length = extended(token & 15) + 4
                last_match = len(output) - start
                had_match = True
                for _ in range(length):
                    output.append(output[-offset])
            else:
                raise FrameError("missing final sequence")
        if len(output) - start > 65536 or len(output) > maximum:
            raise FrameError("decoded/history limit")
    if flags & 4 and int.from_bytes(take(4), "little") != xxh32(output):
        raise FrameError("content checksum")
    if cursor != len(frame) or (content_size is not None and content_size != len(output)):
        raise FrameError("frame/content length")
    return bytes(output)


def gcm_decrypt(key, nonce, aad, ciphertext, tag):
    stream, _ = gcm_encrypt(key, nonce, aad, bytes(len(ciphertext)))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
    actual_ciphertext, actual_tag = gcm_encrypt(key, nonce, aad, plaintext)
    if actual_ciphertext != ciphertext or actual_tag != tag:
        raise ValueError("GCM authentication")
    return plaintext


def known_answers():
    assert aes128(bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
                  bytes.fromhex("00112233445566778899aabbccddeeff")).hex() == (
        "69c4e0d86a7b0430d8cdb78070b4c55a")
    ciphertext, tag = gcm_encrypt(bytes(16), bytes(12), b"", bytes(16))
    assert ciphertext.hex() == "0388dace60b6a392f328c2b971b2fe78"
    assert tag.hex() == "ab6e47d42cec13bdf53a67b21257bddf"
    assert xxh32(b"") == 0x02cc5d05
    assert xxh32(b"abc") == 0x32d153ff
