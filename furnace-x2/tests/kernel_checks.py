"""Independent kernel stimuli, exact output vectors and portable tool execution."""

import hashlib
import random

import mm_oracle as model
from run_support import ROOT


def vectors(kind, n, seed):
    rng = random.Random(seed)
    if kind == 0:
        cases = [
            ([0, 0, 0, 0], 0, 0), ([255] * 4, 255, 255),
            ([0, 1, 0, 1], 128, 0), ([255, 0, 0, 255], 127, 129),
        ]
        cases += [([rng.randrange(256) for _ in range(4)],
                   rng.randrange(256), rng.randrange(256)) for _ in range(252)]
        return [
            (sum(p << (8 * i) for i, p in enumerate(pixels)) | (fx << 32)
             | (fy << 40), model.bilinear(pixels, fx, fy))
            for pixels, fx, fy in cases
        ]
    if kind == 1:
        windows = [[0] * 9, [255] * 9, list(range(9))]
        windows += [[255 if i == border else 0 for i in range(9)] for border in range(9)]
        windows += [[rng.randrange(256) for _ in range(9)] for _ in range(244)]
        return [(sum(p << (8 * i) for i, p in enumerate(window)),
                 sum((v & 65535) << (16 * i) for i, v in enumerate(model.spatial(window))))
                for window in windows]
    samples = [[0] * n, [32767] + [0] * (n - 1), [-32768] * n,
               [32767, -32768] * (n // 2),
               [rng.randrange(-32768, 32768) for _ in range(n)]]
    if kind == 2:
        return [((x & 65535) | (int(i == 0) << 16), y & 65535)
                for window in samples for i, (x, y) in enumerate(zip(window, model.fir(window)))]
    result = []
    for window in samples:
        bins = model.fft(window)
        model.check_dft(window, bins)
        for i, (sample, (re, im)) in enumerate(zip(window, bins)):
            expected = ((re & 0xFFFFFFFF) | ((im & 0xFFFFFFFF) << 32)
                        | (i << 64) | (int(i == n - 1) << 70))
            result.append((sample & 65535, expected))
    return result


def execute(run, kind, n, simulator, seed=17, sources=None, pairs=None):
    pairs = vectors(kind, n, seed) if pairs is None else pairs
    if simulator == "iverilog" and (n>=64 or len(pairs)>4096):
        simulator = "verilator"
    label = f"kernel-{kind}-n{n}-{simulator}"
    args = []
    for stem, index in (("input", 0), ("expected", 1)):
        path = run.path / f"{label}-{stem}.hex"
        (ROOT / path).write_text("".join(f"{p[index]:032x}\n" for p in pairs))
        run.receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
            (ROOT / path).read_bytes()).hexdigest()
        args.append(f"+{stem.upper()}={path}")
    args += [f"+COUNT={len(pairs)}", f"+SEED={seed}"]
    rtl = sources if sources is not None else [
        "rtl/furnace_bilinear_pipe.sv", "rtl/furnace_spatial3x3_pipe.sv",
        "rtl/furnace_fir4_pipe.sv", "rtl/furnace_fft_radix2.sv",
    ]
    obj = run.path / f"{label}-obj"
    vvp = run.path / f"{label}.vvp"
    try:
        if simulator == "iverilog":
            run.command(["iverilog", "-g2012", "-Wall", "-s", "kernel_probe",
                         "-o", str(vvp), f"-Pkernel_probe.KIND={kind}",
                         f"-Pkernel_probe.N={n}", *rtl, "tests/kernel_probe.sv"],
                        f"{label}-compile")
            log = run.command(["vvp", str(vvp), *args], f"{label}-simulation")
        else:
            run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                         "--top-module", "kernel_probe", "--Mdir", str(obj),
                         "-o", "sim", f"-GKIND={kind}", f"-GN={n}", *rtl,
                         "tests/kernel_probe.sv"], f"{label}-compile")
            log = run.command([str(obj / "sim"), *args], f"{label}-simulation")
        summary = f"COMPARED kind={kind} count={2*len(pairs)} phases=2"
        if summary not in log.read_text():
            raise AssertionError(f"missing exact comparison count: {summary}")
        run.receipt.setdefault("kernel_comparisons", []).append(
            dict(kind=kind, fft_n=n, simulator=simulator,
                 comparisons=2 * len(pairs), latency_checked=True,
                 reset_abort_checked=True, raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
        run.remove_intermediates(vvp)
