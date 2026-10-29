"""Contract-derived integer and exact-IEEE legacy tensor comparisons."""

import hashlib
import random

import legacy_oracle as model
from run_support import ROOT


def vectors(seed):
    rng = random.Random(seed)
    specials = [0, 0x8000, 0x0001, 0x007F, 0x0080, 0x3F80, 0xBF80,
                0x7F7F, 0xFF7F, 0x7F80, 0xFF80, 0x7FC1]
    jobs = []
    for mode in range(3):
        for length in (1, 3):
            for case in range(40):
                tile = []
                for vector in range(length):
                    weights = rng.getrandbits(128 if mode == 1 else 32)
                    activations = rng.getrandbits(128)
                    if mode == 0 and case < 3:
                        w = [-8, 7, -1][case]
                        a = [-32768, 32767, -1][case]
                        weights = sum((w & 15) << (4 * i) for i in range(8))
                        activations = sum((a & 65535) << (16 * i) for i in range(8))
                    elif mode != 0 and case < len(specials):
                        activations = sum(specials[case] << (16 * i) for i in range(8))
                        if mode == 1:
                            weights = sum(specials[(case + vector) % len(specials)]
                                          << (16 * i) for i in range(8))
                    tile.append((weights, activations))
                jobs.append((mode, tile))
    inputs, expected = [], []
    for mode, tile in jobs:
        expected.append(model.tensor_tile(tile, mode))
        for index, (weights, activations) in enumerate(tile):
            inputs.append((mode << 258) | (int(index == 0) << 257)
                          | (int(index == len(tile) - 1) << 256)
                          | (weights << 128) | activations)
    return inputs, expected


def execute(run, seed=17, reference=False):
    inputs, expected = vectors(seed)
    label = "tensor-parent" if reference else "tensor-deliverable"
    args = []
    for name, values, width in (("vectors", inputs, 65), ("expected", expected, 18)):
        path = run.path / f"{label}-{name}.hex"
        (ROOT / path).write_text("".join(f"{v:0{width}x}\n" for v in values))
        run.receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
            (ROOT / path).read_bytes()).hexdigest()
        args.append(f"+{name.upper()}={path}")
    args += [f"+COUNT={len(inputs)}", f"+JOBS={len(expected)}", f"+SEED={seed}"]
    directory = "furnace_x1_reference/rtl" if reference else "rtl"
    sources = [f"{directory}/{name}.sv" for name in (
        "furnace_tensor8", "furnace_fp32_round", "furnace_fp32_add5", "furnace_fp32_mul4")]
    obj = run.path / f"{label}-obj"
    try:
        run.command(["verilator", "--version"], f"{label}-version")
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "tensor_probe", "--Mdir", str(obj),
                     "-o", "sim", *sources, "tests/tensor_probe.sv"], f"{label}-compile")
        log = run.command([str(obj / "sim"), *args], f"{label}-simulation")
        if f"COMPARED tensor_jobs={len(expected)} vectors={len(inputs)}" not in log.read_text():
            raise AssertionError("tensor comparison summary absent/incomplete")
        run.receipt.setdefault("tensor_comparisons", []).append(
            dict(reference=reference, seed=seed, jobs=len(expected), vectors=len(inputs),
                 modes=[0, 1, 2], vector_lengths=[1, 3],
                 raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
