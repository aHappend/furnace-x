"""Complete secure descriptor/DMA/tensor/completion comparisons in all modes."""

import hashlib
import struct

import security_oracle as security
import security_checks
import tensor_checks
import legacy_oracle
from run_support import ROOT


def fixtures(seed=17):
    vectors, expected = tensor_checks.vectors(seed)
    jobs = []
    current = []
    for vector in vectors:
        mode = (vector >> 258) & 3
        first, last = (vector >> 257) & 1, (vector >> 256) & 1
        if first:
            current = []
        width = 16 if mode == 1 else 4
        weights = ((vector >> 128) & ((1 << (8*width))-1)).to_bytes(width, "little")
        activations = (vector & ((1 << 128)-1)).to_bytes(16, "little")
        current.append((weights, activations))
        if last:
            jobs.append((mode, current, expected[len(jobs)]))
    return jobs


def execute(run, reference=False, seed=17, limit=None):
    jobs = fixtures(seed)
    if limit is not None:
        # A bounded diagnostic still includes both vector lengths in all modes.
        jobs = [jobs[index] for index in (0, 40, 80, 120, 160, 200)]
    key = bytes(range(16))
    blob = bytearray()
    metadata = []
    plans = [(job, None) for job in jobs]
    plans.append((jobs[80] if limit is None else jobs[2], "compressed"))
    plans += [(jobs[0], corruption) for corruption in (
        "version", "overlap", "wrapping-frame", "wrapping-activations",
        "unsafe-completion", "reserved", "weight-length", "mode",
        "tag", "cipher", "aad", "lz4-header")]
    plans.append((jobs[80] if limit is None else jobs[2], "illegal-mm-commit"))
    plans.append((jobs[0], None))
    for index, ((mode, tile, result), corruption) in enumerate(plans):
        plain = b"".join(w for w, _ in tile)
        activations = b"".join(a for _, a in tile)
        nonce = index.to_bytes(12, "big")
        descriptor = bytearray(128)
        compressed_block = None
        if corruption == "compressed":
            compressed_block = b"\x43abcd\x04\x00\x50abcde"
            target_cipher = security.lz4_block(compressed_block)
            if len(target_cipher) != 16 or mode != 1 or len(tile) != 1:
                raise AssertionError("incorrect compressed end-to-end fixture shape")
            stream = security.aes128(key, nonce+b"\0\0\0\2")
            plain = bytes(a ^ b for a, b in zip(target_cipher, stream))
            result = legacy_oracle.tensor_tile(
                [(int.from_bytes(plain, "little"), int.from_bytes(activations, "little"))], mode)
        frame_size = (len(plain) if compressed_block is None else len(compressed_block))+15
        struct.pack_into("<10I", descriptor, 0,
                         1, mode | 0x100, 0x2000, frame_size,
                         0x3000, 0x4000, 0x5000, len(plain), len(tile), 0xC000+index)
        descriptor[40:52] = nonce
        struct.pack_into("<I", descriptor, 68, 0x6000)
        cipher, tag = security.gcm_encrypt(key, nonce, plain, bytes(descriptor[:52]))
        descriptor[52:68] = tag
        frame = security_checks.frame(cipher, compressed_block)
        if len(frame) != frame_size or security.lz4_frame(frame) != cipher:
            raise AssertionError("independent legacy encrypted-frame construction")
        status, completion_safe = 0, True
        if corruption in ("version", "overlap", "wrapping-frame", "wrapping-activations",
                          "unsafe-completion", "reserved", "weight-length", "mode",
                          "illegal-mm-commit"):
            status = 1
            if corruption == "version":
                struct.pack_into("<I", descriptor, 0, 2)
            elif corruption == "overlap":
                struct.pack_into("<I", descriptor, 16, 0x2000)
            elif corruption == "wrapping-frame":
                struct.pack_into("<I", descriptor, 8, 0xFFFFFFF0)
            elif corruption == "wrapping-activations":
                struct.pack_into("<I", descriptor, 20, 0xFFFFFFF0)
                struct.pack_into("<I", descriptor, 32, 3)
                struct.pack_into("<I", descriptor, 28, 12)
            elif corruption == "unsafe-completion":
                struct.pack_into("<I", descriptor, 68, 0x3000)
                completion_safe = False
            elif corruption == "reserved":
                descriptor[-1] = 1
            elif corruption == "weight-length":
                struct.pack_into("<I", descriptor, 28, len(plain)+1)
            elif corruption == "mode":
                struct.pack_into("<I", descriptor, 4, 3)
            elif corruption == "illegal-mm-commit":
                struct.pack_into("<I", descriptor, 4, mode | 0x300)
        elif corruption == "tag":
            descriptor[52] ^= 1
            status = 4
        elif corruption == "cipher":
            frame = frame[:11]+bytes((frame[11] ^ 1,))+frame[12:]
            status = 4
        elif corruption == "aad":
            descriptor[40] ^= 1
            status = 4
        elif corruption == "lz4-header":
            frame = frame[:6]+bytes((frame[6] ^ 1,))+frame[7:]
            status = 2
        offsets = []
        for data in (descriptor, frame, activations, plain):
            offsets.append(len(blob))
            blob.extend(data)
        word = (offsets[0] | (offsets[1] << 32) | (offsets[2] << 64)
                | (len(frame) << 96) | (len(activations) << 128)
                | (result << 160) | (len(plain) << 224) | (offsets[3] << 256))
        word |= status << 288
        word |= int(completion_safe) << 296
        word |= int.from_bytes(descriptor[36:40], "little") << 304
        metadata.append(word)
    label = "legacy-soc-parent" if reference else "legacy-soc-deliverable"
    args = []
    for name, values, width in (("meta", metadata, 128), ("data", blob, 2)):
        path = run.path/f"{label}-{name}.hex"
        (ROOT/path).write_text("".join(f"{value:0{width}x}\n" for value in values))
        run.receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
            (ROOT/path).read_bytes()).hexdigest()
        args.append(f"+{name.upper()}={path}")
    args += [f"+JOBS={len(plans)}", f"+DATA_SIZE={len(blob)}", f"+SEED={seed}",
             f"+KEY={int.from_bytes(key, 'little'):032x}"]
    directory = "furnace_x1_reference/rtl" if reference else "rtl"
    rtl = [str(p.relative_to(ROOT)) for p in sorted((ROOT/directory).glob("*.sv"))]
    obj = run.path/f"{label}-obj"
    try:
        run.command(["verilator", "--version"], f"{label}-version")
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "soc_probe", "--Mdir", str(obj),
                     "-o", "sim", "-GLEGACY_TEST=1", f"-GPARENT={int(reference)}",
                     *rtl, "tests/soc_probe.sv"], f"{label}-compile")
        log = run.command([str(obj/"sim"), *args], f"{label}-simulation")
        if f"COMPARED integrated_legacy_jobs={len(plans)}" not in log.read_text():
            raise AssertionError("incomplete integrated legacy comparisons")
        run.receipt.setdefault("integrated_legacy", []).append(
            dict(reference=reference, seed=seed, jobs=len(plans), correct_jobs=len(jobs)+2,
                 rejected_descriptors=9, authentication_corruptions=3,
                 malformed_frames=1, modes=[0, 1, 2], lengths=[1, 3],
                 raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
