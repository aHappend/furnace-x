"""Published KATs, independent optional library checks and tag-bit rejection."""

import importlib.util
import random

from crypto_reference import aes128, encrypt_gcm, selftest


def generate(directory, compact=False, max_length=257):
    rng = random.Random(89)
    aes_cases = [(bytes.fromhex(k), bytes.fromhex(p), bytes.fromhex(c)) for k, p, c in selftest()]
    for _ in range(0 if compact else 32):
        key, block = (bytes(rng.randrange(256) for _ in range(16)) for _ in range(2))
        aes_cases.append((key, block, aes128(key, block)))
    gcm_cases = []
    checked_library = 0
    optional = None
    if importlib.util.find_spec("cryptography") is not None:
        import cryptography
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        optional = {"name": "cryptography", "version": cryptography.__version__}

    def case(length, status=0, tag_bit=None, frame_error=0, delay=0):
        nonlocal checked_library
        length = min(length, max_length)
        key = bytes(rng.randrange(256) for _ in range(16))
        nonce = bytes(rng.randrange(256) for _ in range(12))
        aad = bytes(rng.randrange(256) for _ in range(52))
        plaintext = bytes(rng.randrange(256) for _ in range(length))
        ciphertext, tag = encrypt_gcm(key, nonce, aad, plaintext)
        if optional is not None:
            assert AESGCM(key).encrypt(nonce, plaintext, aad) == ciphertext + tag
            checked_library += 1
        if tag_bit is not None:
            tag = (int.from_bytes(tag, "big") ^ (1 << tag_bit)).to_bytes(16, "big")
        gcm_cases.append((key, nonce, tag, aad, plaintext, ciphertext, status, frame_error, delay))

    for length in ((0, 1, 16, 17) if compact else (0, 1, 2, 3, 4, 15, 16, 17, 31, 32, 33, 255, 256, 257)):
        case(length, delay=1000 if length & 1 else 0)
    for _ in range(0 if compact else 32):
        case(rng.randrange(258))
    for bit in range(1 if compact else 128):
        case(4, status=4, tag_bit=bit)
        case(1)  # Every rejection is followed by a fresh shorter success.
    case(33 if not compact else 4, status=2, frame_error=2, delay=1000)
    case(1)
    aes_path, gcm_path = directory / "aes-vectors.txt", directory / "gcm-vectors.txt"
    aes_path.write_text("".join(f"{k.hex()} {p.hex()} {c.hex()}\n" for k, p, c in aes_cases))
    with gcm_path.open("w") as out:
        for key, nonce, tag, aad, plaintext, ciphertext, status, frame_error, delay in gcm_cases:
            out.write(f"{key.hex()} {nonce.hex()} {tag.hex()} {int.from_bytes(aad,'little'):0104x} "
                      f"{len(plaintext)} {status} {frame_error} {delay}\n")
            for data in (ciphertext, plaintext):
                out.write("".join(f"{b:02x} " for b in data) + "\n")
    return {
        "aes_cases": len(aes_cases), "aes_published_kats": 8, "gcm_cases": len(gcm_cases),
        "successes": sum(c[6] == 0 for c in gcm_cases),
        "failures": sum(c[6] != 0 for c in gcm_cases),
        "tag_bits": list(range(1 if compact else 128)),
        "optional_library": optional, "library_comparisons": checked_library,
    }
