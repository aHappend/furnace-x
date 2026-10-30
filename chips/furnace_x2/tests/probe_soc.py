"""Bounded public-pin integrated SoC diagnostic; not full L1 acceptance."""

import argparse
import hashlib
import random
import re
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


def stimulus(run, cell, seed, frames, errors=False, fault=0, contention=False):
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
    heavy_results = []
    if contention:
        if tile < 256 or ring < 3:
            raise ValueError("contention diagnostic requires tile>=256 and ring>=3")
        for job in range(2):
            rng = random.Random((seed << 8)+job)
            ws = [[rng.randrange(-8, 8) for _ in range(8)] for _ in range(64)]
            acts = [[rng.randrange(-32768, 32768) for _ in range(8)] for _ in range(64)]
            heavy_plain = b"".join(
                sum((w & 15) << (4*i) for i, w in enumerate(vector)).to_bytes(4, "little")
                for vector in ws)
            heavy_descriptor = bytearray(128)
            frame_address = 0x2200+0x200*job
            act_address = 0x4200+0x400*job
            struct.pack_into("<10I", heavy_descriptor, 0,
                             1, 0x100, frame_address, 271, 0x3000, act_address,
                             0x5200+0x100*job, 256, 64, 0x778899AA+job)
            heavy_nonce = (100+job).to_bytes(12, "big")
            heavy_descriptor[40:52] = heavy_nonce
            struct.pack_into("<I", heavy_descriptor, 68, 0x6300+16*job)
            heavy_cipher, heavy_tag = security.gcm_encrypt(
                key, heavy_nonce, heavy_plain, bytes(heavy_descriptor[:52]))
            heavy_descriptor[52:68] = heavy_tag
            from security_checks import frame as lz4_frame
            initial[0x8200+0x100*job] = heavy_descriptor
            initial[frame_address] = lz4_frame(heavy_cipher)
            initial[act_address] = b"".join(
                a.to_bytes(2, "little", signed=True) for vector in acts for a in vector)
            initial[0x9000+0x100*job] = heavy_plain
            heavy_results.append(sum(mm.tensor_w4(w, a) for w, a in zip(ws, acts)))
    image = "".join(f"@{address:04x}\n" + "".join(f"{v:02x}\n" for v in data)
                    for address, data in initial.items())
    (ROOT / run.path / "memory.hex").write_text(image)
    vi, ai, ve, ae, re = [], [], [], [], []
    for frame in range(frames):
        ident = ((65530+frame-8) if frame>=8 else (65533+frame)) & 65535
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
        token_verror = 5 if fault == 5 and frame == 0 else verror
        token_aerror = 5 if fault == 6 and frame == 0 else aerror
        result_error = 8 if audio_ident != ident else token_verror or token_aerror
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
    run.receipt["stream_axi_fault"] = fault
    run.receipt["expected_correct_consecutive_tail"] = frames-(8 if errors else int(fault != 0))
    run.save()
    arguments = [f"+IMAGE={run.path}/memory.hex",
            f"+VISION={run.path}/vision.hex", f"+AUDIO={run.path}/audio.hex",
            f"+VEXPECTED={run.path}/vision-expected.hex",
            f"+AEXPECTED={run.path}/audio-expected.hex",
            f"+REXPECTED={run.path}/result-expected.hex",
            f"+VC={len(vi)}", f"+AC={len(ai)}", f"+FRAMES={frames}", f"+SEED={seed}",
            f"+FAULT={fault}",
            f"+KEY={int.from_bytes(key, 'little'):032x}",
            f"+WEIGHTS={packed_weights:08x}",
            f"+LEGACY={mm.tensor_w4(weights, activations) & ((1 << 64)-1):016x}"]
    arguments += [f"+HEAVY{job}={value & ((1 << 64)-1):016x}"
                  for job, value in enumerate(heavy_results)]
    return arguments


def execute(run, cell, seed, simulator, sources=None, errors=False, frames=None, fault=0,
            reset_stalled=False, contention=False):
    if simulator == "iverilog" and (errors or contention or reset_stalled or fault or
                                   max(cell[:4])>=64 or (frames is not None and frames>1)):
        simulator = "verilator"
    frames = (1 if simulator == "iverilog" else
              frames if frames is not None else max(16, cell[5]+2) if errors else 8)
    if simulator == "iverilog":
        errors = False
    args = stimulus(run, cell, seed, frames, errors, fault, contention)
    parameters = dict(zip(("IW", "IH", "OW", "OH", "N", "DEPTH", "RING", "TILE"), cell))
    parameters["FAULT_SWEEP"] = int(simulator == "verilator" and fault == 0 and not contention)
    parameters["RESET_STALLED"] = int(reset_stalled)
    parameters["CONTENTION"] = int(contention)
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
            run.command(["g++", "--version"], "cxx-version")
            run.verilator_build(["verilator", "--binary", "--timing", "-Wno-fatal",
                         "--top-module", "soc_probe", "--Mdir", str(obj),
                         "-o", "sim", *[f"-G{k}={v}" for k, v in parameters.items()],
                         *rtl, "tests/soc_probe.sv"], "compile", obj)
            log = run.command([str(obj / "sim"), *args], "simulation")
        if reset_stalled:
            if "COMPARED reset_stalled=1 compared_pair=1 consumed_pair=0 zeroized_epoch=1" not in log.read_text():
                raise AssertionError("missing stalled-reset comparisons")
            run.receipt["stalled_soc_reset"] = dict(
                compared_pairs=1, consumed_pairs=0, raw_output=str(log.relative_to(ROOT)))
            run.save()
            return
        if "COMPARED legacy=1" not in log.read_text():
            raise AssertionError("missing completed comparison summary")
        if "COMPARED reset_partial_vision_audio=1 zeroized_epoch=1" not in log.read_text():
            raise AssertionError("partial-input reset comparisons absent")
        expected_faults = 4 if parameters["FAULT_SWEEP"] else int(fault != 0)
        if f"axi_faults={expected_faults}" not in log.read_text():
            raise AssertionError("required AXI error injection/comparison absent")
        summary = re.search(r"COMPARED legacy=1[^\n]*", log.read_text()).group()
        observed_coverage = {key: int(value)
                             for key, value in re.findall(r"(\w+)=(\d+)", summary)}
        if contention:
            if "COMPARED shared_legacy_jobs=2 accepted_activation_reads=128" not in log.read_text():
                raise AssertionError("shared tensor ownership workload did not complete")
            run.receipt["shared_tensor_contention"] = dict(
                legacy_jobs=2, vectors_per_job=64, multimodal_pairs=frames,
                raw_output=str(log.relative_to(ROOT)))
        run.receipt.setdefault("soc_comparisons", []).append(
            dict(configuration=cell, seed=seed, pairs=frames,
                 successful_legacy_completions=1, rejected_authentication_updates=1,
                 rejected_candidate_dma_updates=4 if parameters["FAULT_SWEEP"] else 0,
                 injected_axi_failures=expected_faults,
                 feature_record_data_comparisons=2*frames, result_record_data_comparisons=frames,
                 successful_feature_write_responses=2*frames-int(fault in (5, 6)),
                 successful_result_write_responses=frames-int(fault == 7),
                 observed_coverage=observed_coverage,
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
    parser.add_argument("--fault", type=int, choices=(0, 5, 6, 7), default=0)
    parser.add_argument("--reset-stalled", action="store_true")
    parser.add_argument("--contention", action="store_true")
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
        cell = (1, 1, 1, 1, 8, 16, 3, 4096) if args.contention else CELLS[args.cell]
        execute(run, cell, args.seed, args.simulator,
                sources=sources, errors=args.errors, fault=args.fault,
                reset_stalled=args.reset_stalled, contention=args.contention,
                frames=64 if args.contention else None)
    except Exception as caught:
        error = caught
    finally:
        run.finish(error)
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
