"""Compact real-firmware DMA/fork-join smoke, independent byte-memory expected values."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT
from lower_packed import lower
from crypto_reference import gcm_encrypt, known_answers, raw_lz4_frame
from numerical_reference import audio_features, pack_lanes, tensor_vector, vision_features


def graph_memory():
    memory = bytearray((i * 37 + 19) & 255 for i in range(32768))
    # Six nodes: DMA -> {semaphore barrier, DMA} -> barrier fork/join.
    # Dependencies are record indices, not the deliberately unrelated node IDs.
    nodes = [(1, 0, (0x80001000, 0x80002000, 1), -1, 2),
             (4, 1, (), 2, 3),
             (1, 1, (0x80002000, 0x80003000, 1), -1, -1),
             (4, 1, (), 3, -1),
             (4, (1 << 2) | (1 << 3), (), -1, -1),
             (4, 1 << 4, (), -1, -1)]
    for index, (opcode, deps, args, wait, post) in enumerate(nodes):
        record = struct.pack("<IIQ6I6I", opcode, 100 + index * 7, deps,
                             *(tuple(args) + (0,) * (6 - len(args))),
                             wait & 0xffffffff, post & 0xffffffff,
                             0x80000800 + index * 16, 0, 0, 0)
        assert len(record) == 64
        memory[index * 64:(index + 1) * 64] = record
    expected = memory.copy()
    expected[0x2000] = expected[0x1000]
    expected[0x3000] = expected[0x2000]
    for index in range(6):
        expected[0x800 + index * 16:0x810 + index * 16] = struct.pack(
            "<4I", 2, 0, 100 + index * 7, 0)
    return memory, expected


def engine_memory(seed, geometry=(1, 1, 1, 1, 8), ring_depth=1, fusion_depth=1,
                  max_dma_bytes=1, graph_index=0, memory_bytes=32768, max_tile_bytes=64):
    known_answers()
    iw, ih, ow, oh, fft_n = geometry
    memory = bytearray(((i * 37 + 19 + graph_index * 11) ^ ((i >> 8) * 29) ^
                       ((i >> 16) * 17)) & 255 for i in range(memory_bytes))
    expected = memory.copy()

    def provision(offset, data):
        memory[offset:offset + len(data)] = data
        expected[offset:offset + len(data)] = data

    def descriptor(mode, commit, tile_id, frame_offset, plain_offset, act_offset,
                   result_offset, completion_offset, weights, activations):
        vectors = len(activations) // 8
        assert len(activations) == len(weights) == vectors * 8
        weight_data = pack_lanes(weights, 16 if mode == 1 else 4).to_bytes(
            (16 if mode == 1 else 4) * vectors, "little")
        nonce = bytes(range(12))
        desc = bytearray(128)
        frame_bytes = len(weight_data) + 15
        struct.pack_into("<10I", desc, 0, 1, mode | 256 | (512 if commit else 0),
                         0x80000000 + frame_offset, frame_bytes,
                         0x80000000 + plain_offset, 0x80000000 + act_offset,
                         0x80000000 + result_offset, len(weight_data), vectors, tile_id)
        desc[40:52] = nonce
        ciphertext, tag = gcm_encrypt(bytes(16), nonce, desc[:52], weight_data)
        desc[52:68] = tag
        struct.pack_into("<I", desc, 68, 0x80000000 + completion_offset)
        frame = raw_lz4_frame(ciphertext)
        assert len(frame) == frame_bytes
        provision(frame_offset, frame)
        provision(act_offset, pack_lanes(activations, 16).to_bytes(16 * vectors, "little"))
        expected[plain_offset:plain_offset + len(weight_data)] = weight_data
        accumulated = 0
        for vector in range(vectors):
            accumulated = tensor_vector(mode, weights[vector * 8:(vector + 1) * 8],
                                        activations[vector * 8:(vector + 1) * 8], accumulated)
        expected[result_offset:result_offset + 16] = struct.pack("<QII", accumulated, tile_id, 0)
        expected[completion_offset:completion_offset + 16] = struct.pack(
            "<4I", 0, tile_id, len(weight_data), 0)
        return desc

    weights = [1, 2, 13, 4, 11, 6, 9, 8]
    d0 = descriptor(0, True, 203, 0x1000, 0x2000, 0x2100, 0x2200, 0x2300,
                    weights, [2, 65533, 4, 5, 6, 7, 8, 9])
    tensor_mode = 1 if graph_index % 2 == 0 else 2
    other_weights = [0x3f80, 0x4000, 0xbf00, 0x4080, 0x3f80, 0xc000, 0x3f00, 0x4040] if (
        tensor_mode == 1) else [1, 2, 15, 4, 1, 14, 3, 5]
    vectors = min(max_tile_bytes // (16 if tensor_mode == 1 else 4), 16)
    d1 = descriptor(tensor_mode, False, 997, 0x2800, 0x2a00, 0x2c00, 0x2e00, 0x2f00,
                    other_weights * vectors,
                    [0x3f80, 0x3f80, 0x4000, 0x3f00, 0xbf80, 0x4000, 0x4080, 0x3f80] * vectors)
    provision(0x400, d0)
    provision(0x500, d1)
    # Singleton DMA genuinely repairs the first magic byte before authentication.
    copy_bytes = min(max_dma_bytes, 19)
    provision(0x1800, bytes(memory[0x1000:0x1000 + copy_bytes]))
    memory[0x1000] = 0
    dma_source = 0x3800 if memory_bytes == 32768 else 0xa000
    dma_destination = 0x3900 if memory_bytes == 32768 else 0xc000
    dma_length = min(max_dma_bytes, 2049)
    expected[dma_destination:dma_destination + dma_length] = memory[
        dma_source:dma_source + dma_length]
    pixels = [(seed * 7 + i * 31 + graph_index * 3) & 255 for i in range(iw * ih)]
    samples = [(i * 2719 + seed * 31) % 65536 - 32768 for i in range(fft_n)]
    image_offset = 0x3000 if memory_bytes == 32768 else 0x8000
    audio_offset = 0x3100 if memory_bytes == 32768 else 0x9100
    provision(image_offset, bytes(pixels))
    provision(audio_offset, struct.pack(f"<{fft_n}h", *samples))
    frame_id = 4321 + graph_index
    vf, af = vision_features(pixels, iw, ih, ow, oh), audio_features(samples)
    fused = [(vf >> (16 * i)) & 65535 for i in range(4)] + [
        (af >> (16 * i)) & 65535 for i in range(4)]
    mm = tensor_vector(0, weights, fused)
    for offset, result in ((0x5000, vf), (0x6000, af), (0x7000, mm)):
        slot = graph_index % fusion_depth
        expected[offset + slot * 16:offset + (slot + 1) * 16] = struct.pack(
            "<QI HBB", result, 0, frame_id, 0, 0)
    for submission, desc in enumerate((d0, d1)):
        slot = (2 * graph_index + submission) % ring_depth
        expected[0x4000 + slot * 128:0x4080 + slot * 128] = desc
    nodes = [(1, 0, (0x80001800, 0x80001000, copy_bytes), -1, 2),
             (2, 1, (0x80000400,), 2, -1),
             (2, 1 << 1, (0x80000500,), -1, -1),
             (3, 1 << 1, (0x80000000 + image_offset, 0x80000000 + audio_offset, frame_id), -1, 3),
             (1, 1 << 1, (0x80000000 + dma_source, 0x80000000 + dma_destination, dma_length), -1, -1),
             (4, (1 << 2) | (1 << 3) | (1 << 4), (), 3, -1)]
    for index, (opcode, deps, args, wait, post) in enumerate(nodes):
        provision(index * 64, struct.pack(
            "<IIQ6I6I", opcode, 100 + index * 7, deps,
            *(tuple(args) + (0,) * (6 - len(args))), wait & 0xffffffff,
            post & 0xffffffff, 0x80000800 + index * 16, 0, 0, 0))
        expected[0x800 + index * 16:0x810 + index * 16] = struct.pack(
            "<4I", 2, 0, 100 + index * 7, 0)
    return memory, expected


def legacy_memory(seed):
    memory, graph_expected = engine_memory(seed)
    memory[0x1000] = memory[0x1800]
    memory[0x4000:0x4080] = memory[0x400:0x480]
    expected = memory.copy()
    for offset, length in ((0x2000, 4), (0x2200, 16), (0x2300, 16),
                           (0x5000, 16), (0x6000, 16), (0x7000, 16)):
        expected[offset:offset+length] = graph_expected[offset:offset+length]
    return memory, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--lowered", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--engines", action="store_true")
    parser.add_argument("--tile-bytes", type=int, choices=(1, 64), default=64)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--repair-of")
    mode.add_argument("--host-running", action="store_true")
    mode.add_argument("--legacy-streams", action="store_true")
    args = parser.parse_args()
    if args.engines and args.tile_bytes == 1:
        parser.error("one-byte tiles use the DMA/barrier workload, not a four-byte tensor descriptor")
    experiment = Experiment("x3-firmware-smoke", args.repair_of)
    try:
        experiment.command(["iverilog", "-V"], "iverilog-version", version=True)
        experiment.command(["vvp", "-V"], "vvp-version", version=True)
        image = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", "1",
                            "--in-height", "1", "--fft-n", "8",
                            "--output", str(image.relative_to(ROOT))], "firmware-build")
        metadata = json.loads(image.with_suffix(".json").read_text())
        memory, expected = (legacy_memory(args.seed) if args.legacy_streams else
                            engine_memory(args.seed) if args.engines else graph_memory())
        for name, data in (("memory", memory), ("expected", expected)):
            (experiment.path / f"{name}.hex").write_text(
                "".join(f"{value:02x}\n" for value in data))
        binary = experiment.path / "x3.vvp"
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        if args.lowered:
            lowered = experiment.path / "lowered"
            lowered.mkdir()
            mappings = []
            for name in sources:
                text, mapping = lower((ROOT / name).read_text(), name)
                (lowered / Path(name).name).write_text(text)
                mappings.append(mapping)
            (experiment.path / "lowering-map.json").write_text(
                json.dumps(mappings, indent=2) + "\n")
            sources = [str(p.relative_to(ROOT)) for p in sorted(lowered.glob("*.sv"))]
        experiment.command(["iverilog", "-g2012", "-Wall", "-s", "x3_smoke_tb",
                            f"-Px3_smoke_tb.MAX_TILE_BYTES={args.tile_bytes}",
                            "-o", str(binary.relative_to(ROOT)), *sources,
                            "tests/x3_smoke_tb.sv"], "compile")
        output = experiment.command([
            "vvp", str(binary.relative_to(ROOT)),
            f"+image={image.relative_to(ROOT)}", f"+words={metadata['bytes'] // 4}",
            f"+memory={(experiment.path / 'memory.hex').relative_to(ROOT)}",
            f"+expected={(experiment.path / 'expected.hex').relative_to(ROOT)}",
            f"+engines={int(args.engines)}",
            f"+preflight={int(args.preflight)}",
            f"+host_running={int(args.host_running)}",
            f"+legacy_probe={int(args.legacy_streams)}",
            f"+seed={args.seed}"], "simulate")
        expected_summary = ("HOST_RUNNING_ACCESS_PASS" if args.host_running else
                            "LEGACY_STREAM_MODE_PASS" if args.legacy_streams else
                            "X3_FIRMWARE_SMOKE_PASS")
        if expected_summary not in output:
            raise AssertionError("missing firmware comparisons")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
