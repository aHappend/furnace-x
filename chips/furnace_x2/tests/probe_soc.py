"""Bounded public-pin integrated SoC diagnostic; not full L1 acceptance."""

import argparse
import hashlib
import random
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mm_oracle as mm
import security_oracle as security
from run_support import ROOT, Run


CELLS = (
    (8, 8, 8, 8, 16, 4, 8, 4096),
    (1, 1, 1, 1, 8, 1, 1, 64),
    (5, 3, 7, 2, 32, 3, 3, 256),
    (13, 9, 3, 5, 64, 2, 8, 4096),
    (3, 2, 16, 9, 16, 4, 8, 4096),
    (64, 64, 64, 64, 64, 16, 16, 4096),
    (64, 1, 1, 64, 8, 1, 1, 64),
)


def stimulus(run, cell, seed, frames, errors=False):
    iw, ih, ow, oh, n, depth, ring, tile = cell
    weights = [-8, -3, 0, 7, 1, -1, 5, -6]
    packed_weights = sum((v & 15) << (4 * i) for i, v in enumerate(weights))
    plain = packed_weights.to_bytes(4, "little")
    key, nonce = bytes(range(16)), bytes(range(12))
    activations = [-32768, 32767, -1, 1, 19, -53, 117, -313]
    # Raw standard LZ4 frame overhead is 15 bytes; compression encloses GCM
    # ciphertext, not the plaintext weights.
    frame_length = len(plain) + 15
    descriptor = bytearray(128)
    fields = (1, 0x300, 0x2000, frame_length, 0x3000, 0x4000, 0x5000,
              4, 1, 0x1234)
    struct.pack_into("<10I", descriptor, 0, *fields)
    descriptor[40:52] = nonce
    struct.pack_into("<I", descriptor, 68, 0x6000)
    cipher, tag = security.gcm_encrypt(key, nonce, plain, bytes(descriptor[:52]))
    descriptor[52:68] = tag
    header = bytes((0x60, 0x40))
    compressed = (b"\x04\x22\x4d\x18" + header
                  + bytes(((security.xxh32(header) >> 8) & 255,))
                  + (0x80000000 | len(cipher)).to_bytes(4, "little") + cipher
                  + bytes(4))
    if len(compressed) != frame_length or security.lz4_frame(compressed) != cipher:
        raise AssertionError("independent frame construction")
    initial = {
        0x1000: descriptor, 0x2000: compressed,
        0x4000: b"".join(v.to_bytes(2, "little", signed=True) for v in activations),
    }
    bad_descriptor = bytearray(descriptor)
    struct.pack_into("<I", bad_descriptor, 8, 0x2100)
    struct.pack_into("<I", bad_descriptor, 16, 0x3100)
    struct.pack_into("<I", bad_descriptor, 24, 0x5100)
    struct.pack_into("<I", bad_descriptor, 36, 0x5678)
    struct.pack_into("<I", bad_descriptor, 68, 0x6100)
    bad_descriptor[40:52] = bytes(range(12, 24))
    bad_cipher, bad_tag = security.gcm_encrypt(
        key, bytes(bad_descriptor[40:52]), bytes.fromhex("76543210"),
        bytes(bad_descriptor[:52]))
    bad_descriptor[52:68] = bad_tag
    bad_descriptor[52] ^= 1
    bad_frame = compressed[:11] + bad_cipher + bytes(4)
    if security.lz4_frame(bad_frame) != bad_cipher:
        raise AssertionError("independent corrupted-tag frame construction")
    initial[0x8000] = bad_descriptor
    initial[0x2100] = bad_frame
    image = "".join(f"@{address:04x}\n" + "".join(f"{v:02x}\n" for v in data)
                    for address, data in initial.items())
    (ROOT / run.path / "memory.hex").write_text(image)
    vi, ai, ve, ae, re = [], [], [], [], []
    for frame in range(frames):
        ident = (65533 + frame) & 65535
        audio_ident = (ident + 1) & 65535 if errors and frame == 7 else ident
        from matrix_checks import frame_inputs
        pixels, samples = frame_inputs(cell, seed, frame)
        vision = mm.vision(pixels, iw, ih, ow, oh)[2]
        _, bins, audio = mm.audio(samples)
        mm.check_dft(mm.fir(samples), bins)

        def malformed(values, identifier, kind):
            items = [(p, identifier, i == len(values)-1) for i, p in enumerate(values)]
            if kind == "early" and len(values) > 1:
                items = [(values[0], identifier, True)]
            elif kind == "id" and len(values) > 1:
                p, _, last = items[1]
                items[1] = (p, (identifier + 1) & 65535, last)
            elif kind is not None:
                items[-1] = (values[-1], identifier, False)
                items += [(0, identifier, False), (0, identifier, True)]
            return items

        vision_kind = {1: "early", 2: "id", 3: "missing"}.get(frame) if errors else None
        audio_kind = {4: "early", 5: "id", 6: "missing"}.get(frame) if errors else None
        verror, aerror = (7 if vision_kind else 0), (7 if audio_kind else 0)
        vi.extend((int(last) << 24) | (identifier << 8) | p
                  for p, identifier, last in malformed(pixels, ident, vision_kind))
        ai.extend((int(last) << 32) | (identifier << 16) | (p & 65535)
                  for p, identifier, last in malformed(samples, audio_ident, audio_kind))
        vector = lambda lanes: sum((v & 65535) << (16 * i) for i, v in enumerate(lanes))
        ve.append(int.from_bytes(mm.record(0 if verror else vector(vision), ident, verror), "little"))
        ae.append(int.from_bytes(mm.record(0 if aerror else vector(audio),
                                          audio_ident, aerror), "little"))
        result_error = 8 if audio_ident != ident else verror or aerror
        result = 0 if result_error else mm.tensor_w4(weights, (*vision, *audio))
        re.append(int.from_bytes(mm.record(result, ident, result_error), "little"))
    files = (("vision.hex", vi, 7), ("audio.hex", ai, 9),
             ("vision-expected.hex", ve, 32), ("audio-expected.hex", ae, 32),
             ("result-expected.hex", re, 32))
    for name, values, width in files:
        (ROOT / run.path / name).write_text(
            "".join(f"{v:0{width}x}\n" for v in values))
    run.receipt["stimulus_sha256"] = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / run.path).glob("*.hex")
    }
    run.receipt["configuration"] = cell
    run.receipt["seed"] = seed
    run.receipt["expected_pairs"] = frames
    run.receipt["directed_errors"] = errors
    run.receipt["expected_correct_consecutive_tail"] = frames-8 if errors else frames
    run.save()
    return [f"+IMAGE={run.path}/memory.hex",
            f"+VISION={run.path}/vision.hex", f"+AUDIO={run.path}/audio.hex",
            f"+VEXPECTED={run.path}/vision-expected.hex",
            f"+AEXPECTED={run.path}/audio-expected.hex",
            f"+REXPECTED={run.path}/result-expected.hex",
            f"+VC={len(vi)}", f"+AC={len(ai)}", f"+FRAMES={frames}", f"+SEED={seed}",
            f"+KEY={int.from_bytes(key, 'little'):032x}",
            f"+WEIGHTS={packed_weights:08x}",
            f"+LEGACY={mm.tensor_w4(weights, activations) & ((1 << 64)-1):016x}"]


def execute(run, cell, seed, simulator, sources=None, errors=False, frames=None):
    frames = (1 if simulator == "iverilog" else
              frames if frames is not None else max(16, cell[5]+2) if errors else 8)
    if simulator == "iverilog":
        errors = False
    if simulator == "iverilog" and max(cell[:4]) >= 64:
        cell = CELLS[1]
    args = stimulus(run, cell, seed, frames, errors)
    parameters = dict(zip(("IW", "IH", "OW", "OH", "N", "DEPTH", "RING", "TILE"), cell))
    rtl = (sources if sources is not None else
           [str(p.relative_to(ROOT)) for p in sorted(ROOT.glob("rtl/*.sv"))])
    obj = run.path / "compile-obj"
    try:
        if simulator == "iverilog":
            run.command(["iverilog", "-V"], "compiler-version")
            run.command(["vvp", "-V"], "simulator-version")
            run.command(["iverilog", "-g2012", "-Wall", "-s", "soc_probe",
                         "-o", str(run.path / "sim.vvp"),
                         *[f"-Psoc_probe.{k}={v}" for k, v in parameters.items()],
                         *rtl, "tests/soc_probe.sv"], "compile")
            log = run.command(["vvp", str(run.path / "sim.vvp"), *args], "simulation")
        else:
            run.command(["verilator", "--version"], "compiler-version")
            run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                         "--top-module", "soc_probe", "--Mdir", str(obj),
                         "-o", "sim", *[f"-G{k}={v}" for k, v in parameters.items()],
                         *rtl, "tests/soc_probe.sv"], "compile")
            log = run.command([str(obj / "sim"), *args], "simulation")
        if "COMPARED legacy=1" not in log.read_text():
            raise AssertionError("missing completed comparison summary")
        run.receipt.setdefault("soc_comparisons", []).append(
            dict(configuration=cell, seed=seed, pairs=frames,
                 legacy_completions=1, rejected_authentication_updates=1,
                 stored_feature_records=2 * frames, stored_result_records=frames,
                 raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
        run.remove_intermediates(run.path / "sim.vvp")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", type=int, choices=range(len(CELLS)), default=0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--simulator", choices=("iverilog", "verilator"), default="verilator")
    parser.add_argument("--repair-of")
    parser.add_argument("--errors", action="store_true")
    parser.add_argument("--lower-packed", action="store_true",
                        help="Behaviorally exercise the exact Yosys input conversion")
    args = parser.parse_args()
    run = Run("soc", ["python3", *sys.argv], preparation=True, repair_of=args.repair_of)
    error = None
    try:
        sources = None
        if args.lower_packed:
            from yosys_input import prepare_sources
            sources = prepare_sources(run)
        execute(run, CELLS[args.cell], args.seed, args.simulator,
                sources=sources, errors=args.errors)
    except Exception as caught:
        error = caught
    finally:
        run.finish(error)
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
