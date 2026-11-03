"""Independent fixtures: FIPS-197 field arithmetic and SP800-38D GHASH."""

import random
import struct


def gf(a, b):
    value = 0
    for _ in range(8):
        if b & 1:
            value ^= a
        a = ((a << 1) ^ (0x11B if a & 128 else 0)) & 255
        b >>= 1
    return value


def substitution(a):
    inverse = 0
    if a:
        inverse = 1
        for _ in range(254):
            inverse = gf(inverse, a)
    return 0x63 ^ inverse ^ sum_rotate(inverse)


def sum_rotate(a):
    result = 0
    for bits in (1, 2, 3, 4):
        result ^= ((a << bits) | (a >> (8 - bits))) & 255
    return result


SBOX = tuple(substitution(a) for a in range(256))


def aes(key, block):
    words = [list(key[n:n + 4]) for n in range(0, 16, 4)]
    rc = 1
    for i in range(4, 44):
        t = words[i - 1][:]
        if i % 4 == 0:
            t = [SBOX[v] for v in t[1:] + t[:1]]
            t[0] ^= rc
            rc = gf(rc, 2)
        words.append([a ^ b for a, b in zip(words[i - 4], t)])
    state = list(block)
    for r in range(11):
        if r:
            state = [SBOX[state[4 * ((c + row) % 4) + row]]
                     for c in range(4) for row in range(4)]
            if r < 10:
                state = [
                    gf(state[4*c + row], 2) ^
                    gf(state[4*c + (row+1) % 4], 3) ^
                    state[4*c + (row+2) % 4] ^ state[4*c + (row+3) % 4]
                    for c in range(4) for row in range(4)
                ]
        state = [v ^ words[4*r + i//4][i % 4] for i, v in enumerate(state)]
    return bytes(state)


def gcm(key, nonce, aad, plaintext):
    initial = nonce + b"\0\0\0\1"
    counter = int.from_bytes(initial, "big")
    cipher = b"".join(bytes(a ^ b for a, b in zip(
        plaintext[n:n+16], aes(key, (counter + n//16 + 1).to_bytes(16, "big")),
    )) for n in range(0, len(plaintext), 16))
    h = int.from_bytes(aes(key, bytes(16)), "big")
    padded = lambda b: b + bytes(-len(b) % 16)
    authenticated = padded(aad) + padded(cipher) + struct.pack(
        ">QQ", len(aad) * 8, len(cipher) * 8,
    )
    accumulator = 0
    for n in range(0, len(authenticated), 16):
        x = accumulator ^ int.from_bytes(authenticated[n:n+16], "big")
        z, v = 0, h
        for bit in range(127, -1, -1):
            if (x >> bit) & 1:
                z ^= v
            v = (v >> 1) ^ (0xE1000000000000000000000000000000 if v & 1 else 0)
        accumulator = z
    tag = (accumulator ^ int.from_bytes(aes(key, initial), "big")).to_bytes(16, "big")
    return cipher, tag


def xxh32(data):
    mask = 0xFFFFFFFF
    primes = (0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1)
    p1, p2, p3, p4, p5 = primes
    rol = lambda x, k: ((x << k) | ((x & mask) >> (32-k))) & mask
    at = 0
    if len(data) >= 16:
        lanes = [(p1+p2) & mask, p2, 0, (-p1) & mask]
        while at + 16 <= len(data):
            lanes = [(rol((a + b*p2) & mask, 13) * p1) & mask
                     for a, b in zip(lanes, struct.unpack_from("<4I", data, at))]
            at += 16
        total = sum(rol(v, k) for v, k in zip(lanes, (1, 7, 12, 18)))
    else:
        total = p5
    total = (total + len(data)) & mask
    while at + 4 <= len(data):
        total = rol((total + int.from_bytes(data[at:at+4], "little")*p3) & mask, 17)*p4 & mask
        at += 4
    for b in data[at:]:
        total = rol((total + b*p5) & mask, 11)*p1 & mask
    total ^= total >> 15
    total = total*p2 & mask
    total ^= total >> 13
    total = total*p3 & mask
    return total ^ (total >> 16)


def known_answers():
    if aes(bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
           bytes.fromhex("00112233445566778899aabbccddeeff")) != bytes.fromhex(
               "69c4e0d86a7b0430d8cdb78070b4c55a"):
        raise ValueError("independent FIPS-197 AES known answer failed")
    if gcm(bytes(16), bytes(12), b"", bytes(16)) != (
        bytes.fromhex("0388dace60b6a392f328c2b971b2fe78"),
        bytes.fromhex("ab6e47d42cec13bdf53a67b21257bddf"),
    ):
        raise ValueError("independent NIST GCM known answer failed")
    if xxh32(b"") != 0x02CC5D05 or xxh32(b"abc") != 0x32D153FF:
        raise ValueError("independent XXH32 known answer failed")


FIXTURE_BASE = 0x80100000
RING_BASE = 0x86000000
FRAME_BASE = 0x86001000
PLAIN_BASE = 0x86003000
ACTIVATION_BASE = 0x86004000
RESULT_BASE = 0x86005000
COMPLETION_BASE = 0x86006000


def fixtures(seed):
    """Fixed 256-byte slots hold descriptor/frame/activation/expected result."""
    known_answers()
    rng = random.Random(seed)
    slots, expected = [], []
    weights = bytes.fromhex("21436587")
    for job in range(17):
        nonce = struct.pack(">III", seed, 0, job)
        flags = 0x300 if job in (0, 16) else 0x100
        aad = struct.pack("<10I", 1, flags, FRAME_BASE, 19, PLAIN_BASE,
                          ACTIVATION_BASE, RESULT_BASE, 4, 1, job) + nonce
        cipher, tag = gcm(bytes(16), nonce, aad, weights)
        if job == 16:
            tag = tag[:7] + bytes([tag[7] ^ 128]) + tag[8:]
        descriptor = aad + tag + struct.pack("<I", COMPLETION_BASE) + bytes(56)
        frame = bytes.fromhex("04224d186040") + bytes([xxh32(b"\x60\x40") >> 8 & 255])
        frame += struct.pack("<I", 0x80000004) + cipher + bytes(4)
        activations = [rng.randrange(-32768, 32768) for _ in range(8)]
        signed = [((weights[i//2] >> (4*(i % 2))) & 15) for i in range(8)]
        signed = [w-16 if w & 8 else w for w in signed]
        value = sum(a*w for a, w in zip(activations, signed))
        record = struct.pack("<qII", value, job, 0)
        slot = descriptor + frame + bytes(32-len(frame))
        slot += struct.pack("<8h", *activations) + record
        slots.append(slot + bytes(256-len(slot)))
        expected.append({"job": job, "result": value, "error": 4 if job == 16 else 0})
    return b"".join(slots), expected
