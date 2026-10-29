"""Complete secure descriptor/DMA/tensor/completion comparisons in all modes."""

import hashlib
import struct

import security_oracle as security
import security_checks
import tensor_checks
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
    for index, (mode, tile, result) in enumerate(jobs):
        plain = b"".join(w for w, _ in tile)
        activations = b"".join(a for _, a in tile)
        nonce = index.to_bytes(12, "big")
        descriptor = bytearray(128)
        frame_size = len(plain)+15
        struct.pack_into("<10I", descriptor, 0,
                         1, mode | 0x100, 0x2000, frame_size,
                         0x3000, 0x4000, 0x5000, len(plain), len(tile), 0xC000+index)
        descriptor[40:52] = nonce
        struct.pack_into("<I", descriptor, 68, 0x6000)
        cipher, tag = security.gcm_encrypt(key, nonce, plain, bytes(descriptor[:52]))
        descriptor[52:68] = tag
        frame = security_checks.frame(cipher)
        if len(frame) != frame_size or security.lz4_frame(frame) != cipher:
            raise AssertionError("independent legacy encrypted-frame construction")
        offsets = []
        for data in (descriptor, frame, activations, plain):
            offsets.append(len(blob))
            blob.extend(data)
        word = (offsets[0] | (offsets[1] << 32) | (offsets[2] << 64)
                | (len(frame) << 96) | (len(activations) << 128)
                | (result << 160) | (len(plain) << 224) | (offsets[3] << 256))
        metadata.append(word)
    label = "legacy-soc-parent" if reference else "legacy-soc-deliverable"
    args = []
    for name, values, width in (("meta", metadata, 128), ("data", blob, 2)):
        path = run.path/f"{label}-{name}.hex"
        (ROOT/path).write_text("".join(f"{value:0{width}x}\n" for value in values))
        run.receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
            (ROOT/path).read_bytes()).hexdigest()
        args.append(f"+{name.upper()}={path}")
    args += [f"+JOBS={len(jobs)}", f"+DATA_SIZE={len(blob)}", f"+SEED={seed}",
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
        vectors_count = sum(len(tile) for _, tile, _ in jobs)
        if f"COMPARED integrated_legacy_jobs={len(jobs)} vectors={vectors_count}" not in log.read_text():
            raise AssertionError("incomplete integrated legacy comparisons")
        run.receipt.setdefault("integrated_legacy", []).append(
            dict(reference=reference, seed=seed, jobs=len(jobs), vectors=vectors_count,
                 modes=[0, 1, 2], lengths=[1, 3], raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
