"""AES/GCM byte and polynomial oracle independent of pipelined implementation."""


def gf8_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = (a << 1) ^ (0x11B if a & 128 else 0)
    return p


def gf8_pow(a, power):
    result = 1
    while power:
        if power & 1:
            result = gf8_mul(result, a)
        a = gf8_mul(a, a)
        power >>= 1
    return result


def substitute(a):
    inv = gf8_pow(a, 254) if a else 0
    return inv ^ 0x63 ^ (
        ((inv << 1) | (inv >> 7)) & 255
    ) ^ (((inv << 2) | (inv >> 6)) & 255) ^ (
        ((inv << 3) | (inv >> 5)) & 255
    ) ^ (((inv << 4) | (inv >> 4)) & 255)


SBOX = tuple(substitute(x) for x in range(256))


def aes128(key, block):
    if len(key) != 16 or len(block) != 16:
        raise ValueError("AES-128 requires 16-byte key and block")
    expanded = list(key)
    rc = 1
    while len(expanded) < 176:
        temp = expanded[-4:]
        if len(expanded) % 16 == 0:
            temp = [SBOX[b] for b in temp[1:] + temp[:1]]
            temp[0] ^= rc
            rc = gf8_mul(rc, 2)
        for b in temp:
            expanded.append(expanded[-16] ^ b)
    state = [b ^ k for b, k in zip(block, expanded)]
    for round_index in range(1, 11):
        state = [SBOX[state[4 * ((col + row) % 4) + row]]
                 for col in range(4) for row in range(4)]
        if round_index != 10:
            mixed = []
            for col in range(4):
                a = state[4 * col:4 * col + 4]
                for row in range(4):
                    mixed.append(gf8_mul(2, a[row]) ^ gf8_mul(3, a[(row + 1) % 4])
                                 ^ a[(row + 2) % 4] ^ a[(row + 3) % 4])
            state = mixed
        state = [b ^ k for b, k in zip(state, expanded[16 * round_index:])]
    return bytes(state)


def gf128_mul(x, h):
    """Polynomial multiplication by a direct, full-width coefficient expansion."""
    # In the GCM representation the high bit is the coefficient of x**0.
    def reverse128(n):
        return int(f"{n:0128b}"[::-1], 2)

    a, b = reverse128(x), reverse128(h)
    product = 0
    for bit in range(128):
        if b & (1 << bit):
            product ^= a << bit
    polynomial = (1 << 128) | (1 << 7) | (1 << 2) | (1 << 1) | 1
    while product.bit_length() > 128:
        product ^= polynomial << (product.bit_length() - 129)
    return reverse128(product)


def ghash(h, aad, ciphertext):
    stream = aad + bytes((-len(aad)) % 16)
    stream += ciphertext + bytes((-len(ciphertext)) % 16)
    stream += (8 * len(aad)).to_bytes(8, "big") + (8 * len(ciphertext)).to_bytes(8, "big")
    value = 0
    for i in range(0, len(stream), 16):
        value = gf128_mul(value ^ int.from_bytes(stream[i:i + 16], "big"), h)
    return value


def encrypt_gcm(key, nonce, aad, plaintext):
    if len(nonce) != 12:
        raise ValueError("this product requires a 96-bit nonce")
    h = int.from_bytes(aes128(key, bytes(16)), "big")
    cipher = bytearray()
    for index in range(0, len(plaintext), 16):
        counter = 2 + index // 16
        if counter >= 1 << 32:
            raise ValueError("counter wrapped")
        stream = aes128(key, nonce + counter.to_bytes(4, "big"))
        cipher.extend(a ^ b for a, b in zip(plaintext[index:index + 16], stream))
    tag = int.from_bytes(aes128(key, nonce + b"\x00\x00\x00\x01"), "big")
    tag ^= ghash(h, aad, cipher)
    return bytes(cipher), tag.to_bytes(16, "big")


def selftest():
    # FIPS 197 appendix C.1 and SP 800-38A appendix F.1.1.
    aes_vectors = [
        ("000102030405060708090a0b0c0d0e0f", "00112233445566778899aabbccddeeff",
         "69c4e0d86a7b0430d8cdb78070b4c55a"),
        ("2b7e151628aed2a6abf7158809cf4f3c", "6bc1bee22e409f96e93d7e117393172a",
         "3ad77bb40d7a3660a89ecaf32466ef97"),
        ("2b7e151628aed2a6abf7158809cf4f3c", "ae2d8a571e03ac9c9eb76fac45af8e51",
         "f5d3d58503b9699de785895a96fdbaaf"),
        ("2b7e151628aed2a6abf7158809cf4f3c", "30c81c46a35ce411e5fbc1191a0a52ef",
         "43b1cd7f598ece23881b00e3ed030688"),
        ("2b7e151628aed2a6abf7158809cf4f3c", "f69f2445df4f9b17ad2b417be66c3710",
         "7b0c785e27e8ad3f8223207104725dd4"),
        ("00" * 16, "00" * 16, "66e94bd4ef8a2c3b884cfa59ca342b2e"),
        ("2b7e151628aed2a6abf7158809cf4f3c", "f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff",
         "ec8cdf7398607cb0f2d21675ea9ea1e4"),
        ("2b7e151628aed2a6abf7158809cf4f3c", "f0f1f2f3f4f5f6f7f8f9fafbfcfdff00",
         "362b7c3c6773516318a077d7fc5073ae"),
    ]
    for key, block, expected in aes_vectors:
        assert aes128(bytes.fromhex(key), bytes.fromhex(block)) == bytes.fromhex(expected)
    # McGrew/Viega GCM specification test cases 1, 2 and 4 (96-bit IV).
    vectors = [
        ("00" * 16, "00" * 12, "", "", "", "58e2fccefa7e3061367f1d57a4e7455a"),
        ("00" * 16, "00" * 12, "", "00" * 16,
         "0388dace60b6a392f328c2b971b2fe78", "ab6e47d42cec13bdf53a67b21257bddf"),
        ("feffe9928665731c6d6a8f9467308308", "cafebabefacedbaddecaf888",
         "feedfacedeadbeeffeedfacedeadbeefabaddad2",
         "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
         "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39",
         "42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
         "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091",
         "5bc94fbc3221a5db94fae95ae7121a47"),
    ]
    for key, nonce, aad, plaintext, ciphertext, tag in vectors:
        actual = encrypt_gcm(*[bytes.fromhex(v) for v in (key, nonce, aad, plaintext)])
        assert actual == (bytes.fromhex(ciphertext), bytes.fromhex(tag))
    return aes_vectors
