"""Frozen seven-cell workload and per-pixel/per-bin public-leaf expectations."""

import random

import kernel_checks
import mm_oracle as model
import probe_soc
from run_support import Run


def frame_inputs(cell, seed, frame):
    iw, ih, _, _, n = cell[:5]
    rng = random.Random((seed << 32) + frame)
    pixels = [rng.randrange(256) for _ in range(iw * ih)]
    samples = [rng.randrange(-32768, 32768) for _ in range(n)]
    # The eight final frames are always correctly framed. Errors are injected
    # separately and cannot take credit for these numerical pattern comparisons.
    pattern = frame % 16
    if pattern == 0:
        pixels, samples = [255] * (iw * ih), [-32768] * n
    elif pattern == 1:
        pixels = [(x * 19 + y * 31) & 255 for y in range(ih) for x in range(iw)]
        samples = [32767 if i % 2 == 0 else -32768 for i in range(n)]
    elif pattern == 2:
        pixels, samples = [0] * (iw * ih), [0] * n
    elif pattern == 3:
        pixels = [255 * ((x + y) & 1) for y in range(ih) for x in range(iw)]
        samples = [12345] * n
    elif 4 <= pattern <= 11:
        locations = ((0, 0), (iw-1, 0), (0, ih-1), (iw-1, ih-1),
                     (iw//2, 0), (iw//2, ih-1), (0, ih//2), (iw-1, ih//2))
        x, y = locations[pattern-4]
        pixels = [0] * (iw * ih)
        pixels[y * iw + x] = 255
        samples = [32767 if i == (pattern-4) * n // 8 else 0 for i in range(n)]
    elif pattern == 12:
        # Generate the bin-centered tone using the independent high-precision
        # mathematical root, not the DUT's quantized twiddle table.
        samples = [int(model.unit_root(n, 3*i)[0] * 20000) for i in range(n)]
    elif pattern == 13:
        samples = [32767] * n
    return pixels, samples


def leaf_pairs(cell, seed, frames):
    iw, ih, ow, oh, n = cell[:5]
    result = [[] for _ in range(4)]
    pack16 = lambda values: sum((v & 65535) << (16*i) for i, v in enumerate(values))
    for frame in range(frames):
        pixels, samples = frame_inputs(cell, seed, frame)
        resized, spatial, _ = model.vision(pixels, iw, ih, ow, oh)
        for y in range(oh):
            qy = 0 if oh == 1 else 256*y*(ih-1)//(oh-1)
            y0, fy = divmod(qy, 256)
            y1 = min(y0+1, ih-1)
            for x in range(ow):
                qx = 0 if ow == 1 else 256*x*(iw-1)//(ow-1)
                x0, fx = divmod(qx, 256)
                x1 = min(x0+1, iw-1)
                taps = [pixels[y0*iw+x0], pixels[y0*iw+x1],
                        pixels[y1*iw+x0], pixels[y1*iw+x1]]
                packed = sum(p << (8*i) for i, p in enumerate(taps))
                result[0].append((packed | (fx << 32) | (fy << 40), resized[y*ow+x]))
                neighborhood = [
                    resized[min(max(y+dy, 0), oh-1)*ow+min(max(x+dx, 0), ow-1)]
                    for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
                result[1].append((sum(p << (8*i) for i, p in enumerate(neighborhood)),
                                  pack16(spatial[y*ow+x])))
        filtered, bins, _ = model.audio(samples)
        model.check_dft(filtered, bins)
        result[2].extend(((x & 65535) | (int(i == 0) << 16), y & 65535)
                         for i, (x, y) in enumerate(zip(samples, filtered)))
        result[3].extend((y & 65535, (re & 0xFFFFFFFF)
                         | ((im & 0xFFFFFFFF) << 32) | (i << 64)
                         | (int(i == n-1) << 70))
                         for i, (y, (re, im)) in enumerate(zip(filtered, bins)))
    return result


def execute_cell(run, index, seed):
    cell = probe_soc.CELLS[index]
    frames = max(24, cell[5]+2)
    probe_soc.execute(run, cell, seed, "verilator", errors=True, frames=frames)
    for kind, pairs in enumerate(leaf_pairs(cell, seed, frames)):
        kernel_checks.execute(run, kind, cell[4], "verilator", seed, pairs=pairs)
    run.receipt["matrix_cell"] = dict(
        index=index, seed=seed, frames=frames,
        consecutive_correct_tail=run.receipt["soc_comparisons"][-1]["observed_coverage"]["correct_tail"],
        unique_leaf_pixels=frames*cell[2]*cell[3],
        leaf_pixel_comparisons=2*frames*cell[2]*cell[3],
        spatial_lane_comparisons=8*frames*cell[2]*cell[3],
        filtered_sample_comparisons=2*frames*cell[4], fft_bin_comparisons=2*frames*cell[4])
    run.save()


def execute(run):
    ledger = [dict(cell=index, configuration=probe_soc.CELLS[index], seed=seed,
                   required_consecutive_correct_pairs=8, outcome="pending", actual=None)
              for index in range(len(probe_soc.CELLS)) for seed in (17, 89, 203)]
    run.receipt["matrix"] = ledger
    run.receipt["required_matrix_runs"] = 21
    run.save()
    for index in range(len(probe_soc.CELLS)):
        for seed in (17, 89, 203):
            entry = next(row for row in ledger if row["cell"]==index and row["seed"]==seed)
            child = Run(f"l1-behavior-cell{index}-seed{seed}",
                        ["python3", "tests/verify.py", "--suite", "behavior"],
                        preparation=not run.receipt["acceptance_evidence"])
            error = None
            entry.update(receipt=str(child.path/"receipt.json"), outcome="running")
            run.save()
            try:
                execute_cell(child, index, seed)
            except Exception as caught:
                error = caught
                raise
            finally:
                child.finish(error)
                entry.update(outcome="passed" if error is None else "failed",
                             actual=child.receipt.get("matrix_cell"))
                run.save()
    if len(ledger) != 21 or any(row["outcome"]!="passed" for row in ledger):
        raise AssertionError("incomplete mandatory matrix")
    child = Run("l1-shared-tensor-contention",
                ["python3", "tests/verify.py", "--suite", "behavior"],
                preparation=not run.receipt["acceptance_evidence"])
    error = None
    try:
        probe_soc.execute(child, (1, 1, 1, 1, 8, 16, 3, 4096), 203, "verilator",
                          frames=64, contention=True)
    except Exception as caught:
        error = caught
        raise
    finally:
        child.finish(error)
        run.receipt["shared_tensor_receipt"] = str(child.path/"receipt.json")
        run.save()
