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


def known_answers():
    assert aes128(bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
                  bytes.fromhex("00112233445566778899aabbccddeeff")).hex() == (
        "69c4e0d86a7b0430d8cdb78070b4c55a")
    ciphertext, tag = gcm_encrypt(bytes(16), bytes(12), b"", bytes(16))
    assert ciphertext.hex() == "0388dace60b6a392f328c2b971b2fe78"
    assert tag.hex() == "ab6e47d42cec13bdf53a67b21257bddf"
    assert xxh32(b"") == 0x02cc5d05
    assert xxh32(b"abc") == 0x32d153ff
