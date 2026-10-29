"""Software-reference development checks only; these do not execute RTL."""

import ctypes
import ctypes.util
from pathlib import Path
import random
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import security_oracle as model
from test_mm_oracle import preparation


class SecurityOracleTests(unittest.TestCase):
    def test_fips197_aes(self):
        self.assertEqual(model.aes128(bytes(range(16)),
                         bytes.fromhex("00112233445566778899aabbccddeeff")),
                         bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a"))

    def test_nist_gcm(self):
        key, nonce = bytes(16), bytes(12)
        self.assertEqual(model.gcm_encrypt(key, nonce, b""),
                         (b"", bytes.fromhex("58e2fccefa7e3061367f1d57a4e7455a")))
        self.assertEqual(model.gcm_encrypt(key, nonce, bytes(16)),
                         (bytes.fromhex("0388dace60b6a392f328c2b971b2fe78"),
                          bytes.fromhex("ab6e47d42cec13bdf53a67b21257bddf")))

    def test_installed_crypto_reference(self):
        import cryptography
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        print(f"cryptography={cryptography.__version__}")
        rng = random.Random(203)
        for count in (0, 1, 15, 16, 17, 63, 256):
            key, nonce = rng.randbytes(16), rng.randbytes(12)
            plaintext, aad = rng.randbytes(count), rng.randbytes(31)
            ciphertext, tag = model.gcm_encrypt(key, nonce, plaintext, aad)
            self.assertEqual(ciphertext + tag, AESGCM(key).encrypt(nonce, plaintext, aad))

    def test_openssl_aes(self):
        version = subprocess.run(["openssl", "version"], capture_output=True,
                                 check=True, timeout=3600)
        print(version.stdout.decode().strip())
        rng = random.Random(89)
        for _ in range(8):
            key, block = rng.randbytes(16), rng.randbytes(16)
            result = subprocess.run(
                ["openssl", "enc", "-aes-128-ecb", "-K", key.hex(), "-nopad"],
                input=block, capture_output=True, check=True, timeout=3600)
            self.assertEqual(model.aes128(key, block), result.stdout)

    def test_xxh_known_answers_and_library(self):
        self.assertEqual(model.xxh32(b""), 0x02CC5D05)
        self.assertEqual(model.xxh32(b"a"), 0x550D7456)
        name = ctypes.util.find_library("xxhash")
        self.assertIsNotNone(name, "installed xxhash library is required for this probe")
        library = ctypes.CDLL(name)
        library.XXH_versionNumber.restype = ctypes.c_uint
        print(f"XXH_versionNumber={library.XXH_versionNumber()}")
        library.XXH32.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint]
        library.XXH32.restype = ctypes.c_uint
        rng = random.Random(17)
        for count in (0, 1, 15, 16, 17, 31, 32, 256, 4096):
            data = rng.randbytes(count)
            for seed in (0, 1, 0xFFFFFFFF):
                self.assertEqual(model.xxh32(data, seed),
                                 library.XXH32(data, len(data), seed))

    def test_lz4_overlapping_matches_and_library(self):
        name = ctypes.util.find_library("lz4")
        self.assertIsNotNone(name, "installed lz4 library is required for this probe")
        library = ctypes.CDLL(name)
        library.LZ4_versionString.restype = ctypes.c_char_p
        print(f"LZ4_versionString={library.LZ4_versionString().decode()}")
        library.LZ4_decompress_safe.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        library.LZ4_decompress_safe.restype = ctypes.c_int
        cases = [(b"\x00", b""), (b"\x10a", b"a"),
                 (b"\x1fa\x01\x00\x01\x50bcdef", b"a" * 21 + b"bcdef"),
                 (b"\xf0\x01" + bytes(range(16)), bytes(range(16)))]
        for block, expected in cases:
            self.assertEqual(model.lz4_block(block), expected)
            destination = ctypes.create_string_buffer(max(1, len(expected)))
            count = library.LZ4_decompress_safe(
                block, destination, len(block), max(1, len(expected)))
            self.assertEqual(count, len(expected))
            self.assertEqual(destination.raw[:count], expected)
        for invalid in (b"", b"\xf0", b"\x10", b"\x00\x00\x00", b"\x00\x01\x00"):
            with self.assertRaises(ValueError):
                model.lz4_block(invalid)

    def test_installed_lz4_frame_reference(self):
        name = ctypes.util.find_library("lz4")
        self.assertIsNotNone(name, "installed lz4 library is required for this probe")
        library = ctypes.CDLL(name)
        library.LZ4F_compressFrameBound.argtypes = [ctypes.c_size_t, ctypes.c_void_p]
        library.LZ4F_compressFrameBound.restype = ctypes.c_size_t
        library.LZ4F_compressFrame.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_void_p]
        library.LZ4F_compressFrame.restype = ctypes.c_size_t
        library.LZ4F_isError.argtypes = [ctypes.c_size_t]
        library.LZ4F_isError.restype = ctypes.c_uint
        rng = random.Random(89)
        for payload in (b"", b"a", b"abcd" * 4096, rng.randbytes(4096),
                        b"overlapping matches" * 3449):
            capacity = library.LZ4F_compressFrameBound(len(payload), None)
            self.assertEqual(library.LZ4F_isError(capacity), 0)
            destination = ctypes.create_string_buffer(capacity)
            count = library.LZ4F_compressFrame(
                destination, capacity, payload, len(payload), None)
            self.assertEqual(library.LZ4F_isError(count), 0)
            self.assertEqual(model.lz4_frame(
                destination.raw[:count], limit=len(payload)), payload)

    def test_lz4_frame_checksums(self):
        payload = b"independent frame"
        header = b"\x7c\x40" + len(payload).to_bytes(8, "little")
        frame = (b"\x04\x22\x4d\x18" + header
                 + bytes(((model.xxh32(header) >> 8) & 255,))
                 + (0x80000000 | len(payload)).to_bytes(4, "little") + payload
                 + model.xxh32(payload).to_bytes(4, "little") + bytes(4)
                 + model.xxh32(payload).to_bytes(4, "little"))
        self.assertEqual(model.lz4_frame(frame), payload)
        for index in (14, 19, len(frame) - 1):
            corrupted = bytearray(frame)
            corrupted[index] ^= 1
            with self.assertRaises(ValueError):
                model.lz4_frame(corrupted)
        with self.assertRaises(ValueError):
            model.lz4_frame(frame, limit=len(payload) - 1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--preparation"]:
        sys.exit(preparation(
            test_file="test_security_oracle.py",
            source_files=("tests/security_oracle.py", "tests/test_security_oracle.py",
                          "tests/test_mm_oracle.py", "tests/mm_oracle.py"),
            stem="security-oracle"))
    unittest.main()
