"""Independent AES/GCM, XXH32 and framed LZ4 RTL transaction comparisons."""

import hashlib
import random

import security_oracle as model
from run_support import ROOT


def frame(payload, compressed=None, checksums=False):
    flags = 0x7C if checksums else 0x60
    header = bytes((flags, 0x40))
    if checksums:
        header += len(payload).to_bytes(8, "little")
    block = payload if compressed is None else compressed
    result = (b"\x04\x22\x4d\x18" + header
              + bytes(((model.xxh32(header) >> 8) & 255,))
              + ((0x80000000 if compressed is None else 0) | len(block)).to_bytes(4, "little")
              + block)
    if checksums:
        result += model.xxh32(block).to_bytes(4, "little")
    result += bytes(4)
    if checksums:
        result += model.xxh32(payload).to_bytes(4, "little")
    return result


def cases(kind, seed=203):
    rng = random.Random(seed)
    if kind == 0:
        inputs = [(bytes(range(16)), bytes.fromhex("00112233445566778899aabbccddeeff"))]
        inputs += [(rng.randbytes(16), rng.randbytes(16)) for _ in range(31)]
        return [dict(key=key, data=data, expected=model.aes128(key, data)) for key, data in inputs]
    if kind == 1:
        result = []
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        for size in (0, 1, 4, 15, 16, 17, 31, 32, 63, 256, 4096):
            key, nonce, aad = rng.randbytes(16), rng.randbytes(12), rng.randbytes(52)
            plain = rng.randbytes(size)
            cipher, tag = model.gcm_encrypt(key, nonce, plain, aad)
            if cipher+tag != AESGCM(key).encrypt(nonce, plain, aad):
                raise AssertionError("independent GCM implementations disagree")
            result.append(dict(key=key, nonce=nonce, tag=tag, aad=aad, data=cipher,
                               expected=plain))
            if size in (1, 17, 256):
                bad_tag = bytes((tag[0] ^ 1,))+tag[1:]
                result.append(dict(key=key, nonce=nonce, tag=bad_tag, aad=aad,
                                   data=cipher, expected=b"", status=4))
                bad_data = bytes((cipher[0] ^ 1,))+cipher[1:]
                result.append(dict(key=key, nonce=nonce, tag=tag, aad=aad,
                                   data=bad_data, expected=b"", status=4))
                bad_aad = bytes((aad[0] ^ 1,))+aad[1:]
                result.append(dict(key=key, nonce=nonce, tag=tag, aad=bad_aad,
                                   data=cipher, expected=b"", status=4))
                result.append(dict(key=key, nonce=nonce, tag=tag, aad=aad,
                                   data=cipher, expected=b"", status=5, options=2))
                if size > 1:
                    result.append(dict(key=key, nonce=nonce, tag=tag, aad=aad,
                                       data=cipher, expected=b"", status=2, options=1))
        return result
    if kind == 2:
        return [dict(data=payload, expected=b"", digest=model.xxh32(payload))
                for payload in (b"", b"a", *(rng.randbytes(n) for n in
                    (2, 3, 4, 7, 15, 16, 17, 31, 32, 33, 63, 256, 4096)))]
    result = []
    for payload in (b"a", bytes(range(16)), b"abcd"*8, rng.randbytes(4096)):
        for checksums in (False, True):
            encoded = frame(payload, checksums=checksums)
            if model.lz4_frame(encoded) != payload:
                raise AssertionError("independent LZ4 frame construction")
            result.append(dict(data=encoded, expected=payload, declared=len(payload)))
    # Standard match constraints retain at least five final literals.
    for block, payload in ((b"\x1fa\x01\x00\x01\x50bcdef", b"a"*21+b"bcdef"),
                           (b"\x44abcd\x04\x00\x50efghi", b"abcd"*3+b"efghi")):
        if model.lz4_block(block) != payload:
            raise AssertionError("independent compressed fixture")
        encoded = frame(payload, block, True)
        if model.lz4_frame(encoded) != payload:
            raise AssertionError("independent compressed frame construction")
        result.append(dict(data=encoded, expected=payload, declared=len(payload)))
    # Invalid offset: one literal precedes the malformed two-byte offset.
    for offset in (b"\x00\x00", b"\x02\x00"):
        encoded = frame(b"a"*10, b"\x10a"+offset+b"\x50abcde")
        result.append(dict(data=encoded, expected=b"a", declared=10, status=3))
    encoded = bytearray(frame(b"checksummed", checksums=True))
    encoded[14] ^= 1
    result.append(dict(data=bytes(encoded), expected=b"", declared=11, status=2))
    encoded = bytearray(frame(b"checksummed", checksums=True))
    encoded[-1] ^= 1
    result.append(dict(data=bytes(encoded), expected=b"checksummed", declared=11, status=2))
    return result


def execute(run, kind, reference=False, simulator="verilator"):
    if simulator == "iverilog" and kind != 0:
        simulator = "verilator"
    fixtures = cases(kind)
    label = f"security-{kind}-{'parent' if reference else 'deliverable'}"
    inputs, expected, metadata = bytearray(), bytearray(), []
    for fixture in fixtures:
        word = int.from_bytes(fixture.get("key", bytes(16)), "big")
        word |= int.from_bytes(fixture.get("nonce", bytes(12)), "big") << 128
        word |= int.from_bytes(fixture.get("tag", bytes(16)), "big") << 224
        word |= int.from_bytes(fixture.get("aad", bytes(52)), "little") << 352
        word |= len(inputs) << 768
        word |= len(fixture["data"]) << 800
        word |= len(expected) << 832
        word |= len(fixture["expected"]) << 864
        word |= fixture.get("declared", len(fixture["data"])) << 896
        word |= fixture.get("status", 0) << 928
        word |= fixture.get("options", 0) << 936
        word |= fixture.get("digest", 0) << 944
        metadata.append(word)
        inputs.extend(fixture["data"])
        expected.extend(fixture["expected"])
    args = []
    for name, values, width in (("meta", metadata, 288), ("input", inputs or b"\0", 2),
                                ("expected", expected or b"\0", 2)):
        path = run.path/f"{label}-{name}.hex"
        (ROOT/path).write_text("".join(f"{value:0{width}x}\n" for value in values))
        run.receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
            (ROOT/path).read_bytes()).hexdigest()
        args.append(f"+{name.upper()}={path}")
    args += [f"+CASES={len(fixtures)}", f"+INPUT_SIZE={max(1, len(inputs))}",
             f"+OUTPUT_SIZE={max(1, len(expected))}"]
    directory = "furnace_x1_reference/rtl" if reference else "rtl"
    names = ("furnace_aes128_block", "furnace_aes128_gcm", "furnace_ghash_mul",
             "furnace_lz4_frontend", "furnace_xxh32")
    sources = [f"{directory}/{name}.sv" for name in names]
    obj = run.path/f"{label}-obj"
    binary = run.path/f"{label}.vvp"
    try:
        if simulator == "verilator":
            run.command(["verilator", "--version"], f"{label}-version")
            run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                         "--top-module", "security_probe", "--Mdir", str(obj),
                         "-o", "sim", f"-GKIND={kind}", *sources,
                         "tests/security_probe.sv"], f"{label}-compile")
            command = [str(obj/"sim")]
        else:
            run.command(["iverilog", "-V"], f"{label}-version")
            run.command(["vvp", "-V"], f"{label}-simulator-version")
            run.command(["iverilog", "-g2012", "-Wall", "-s", "security_probe",
                         "-o", str(binary), f"-Psecurity_probe.KIND={kind}",
                         *sources, "tests/security_probe.sv"], f"{label}-compile")
            command = ["vvp", str(binary)]
        log = run.command([*command, *args], f"{label}-simulation")
        if f"COMPARED security_kind={kind} cases={len(fixtures)}" not in log.read_text():
            raise AssertionError("incomplete security comparison summary")
        run.receipt.setdefault("security_comparisons", []).append(
            dict(kind=kind, reference=reference, cases=len(fixtures),
                 expected_bytes=len(expected), raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
        run.remove_intermediates(binary)
