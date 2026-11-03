"""Mathematical ISP and independently generated fixed-point DSP oracle checks."""

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from numerical_reference import audio_features, vision_features
from record import Experiment, ROOT


def traces(seed, iw, ih, ow, oh, fft_n):
    rng = random.Random(seed)
    records = []
    for kind in (0, 1):
        count = iw * ih if kind == 0 else fft_n
        samples = [[0] * count, [255 if kind == 0 else 32767] * count,
                   [255 if kind == 0 else -32768] + [0] * (count - 1),
                   [rng.randrange(256) if kind == 0 else rng.randrange(-32768, 32768)
                    for _ in range(count)]]
        for index, values in enumerate(samples):
            packet_id = (seed * 23 + index * 7 + kind) & 65535
            result = vision_features(values, iw, ih, ow, oh) if kind == 0 else audio_features(values)
            records.append((kind, packet_id, result, 0,
                            [(v & 65535, packet_id, int(i == count - 1), rng.randrange(3))
                             for i, v in enumerate(values)]))
        # Malformed packets must drain to LAST, publish one error, then recover.
        if count > 1:
            packet_id = (seed * 29) & 65535
            records.append((kind, packet_id, 0, 7, [(23, packet_id, 1, 0)]))
        for malformed in ("late-last", "changed-id") if count > 1 else ("late-last",):
            packet_id = (seed * 31 + len(records)) & 65535
            total = count+3 if malformed == "late-last" else count
            records.append((kind, packet_id, 0, 7, [
                (23, packet_id ^ int(malformed == "changed-id" and i == 1),
                 int(i == total-1), rng.randrange(3))
                for i in range(total)]))
            values = [rng.randrange(256) if kind == 0 else rng.randrange(-32768, 32768)
                      for _ in range(count)]
            result = vision_features(values, iw, ih, ow, oh) if kind == 0 else audio_features(values)
            records.append((kind, packet_id, result, 0,
                            [(v & 65535, packet_id, int(i == count - 1), 0)
                             for i, v in enumerate(values)]))
    return "".join(
        f"{kind} {packet_id} {result:016x} {error} {len(samples)}\n" + "".join(
            f"{value:04x} {identifier} {last} {gap}\n"
            for value, identifier, last, gap in samples)
        for kind, packet_id, result, error, samples in records), len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--geometry", choices=("singleton", "upsample", "downsample", "large"),
                        default="upsample")
    args = parser.parse_args()
    geometries = {"singleton": (1, 1, 1, 1, 8), "upsample": (3, 2, 5, 3, 32),
                  "downsample": (8, 8, 3, 2, 64), "large": (64, 64, 64, 64, 64)}
    geometry = geometries[args.geometry]
    experiment = Experiment("frontend-numerical")
    obj = experiment.path / "compile-obj"
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        trace = experiment.path / "frontend.trace"
        text, rows = traces(args.seed, *geometry)
        trace.write_text(text)
        params = [f"-G{name}={value}" for name, value in zip(
            ("IN_WIDTH", "IN_HEIGHT", "OUT_WIDTH", "OUT_HEIGHT", "FFT_N"), geometry)]
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "frontend_tb", *params,
                            "--Mdir", str(obj.relative_to(ROOT)), "-o", "frontend-sim",
                            "rtl/furnace_x2_vision.sv", "rtl/furnace_bilinear_pipe.sv",
                            "rtl/furnace_spatial3x3_pipe.sv", "rtl/furnace_x2_audio.sv",
                            "rtl/furnace_fir4_pipe.sv", "rtl/furnace_fft_radix2.sv",
                            "tests/frontend_tb.sv"], "compile")
        output = experiment.command([str((obj / "frontend-sim").relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}", f"+rows={rows}"],
                                    "simulate")
        if "FRONTEND_PASS " not in output:
            raise AssertionError("frontend comparisons missing")
        print(output.strip())
    except Exception as error:
        experiment.finish(error)
        raise
    finally:
        for pattern in ("*.o", "*.a", "*.gch"):
            for path in obj.glob(pattern):
                path.unlink()
    experiment.finish()


if __name__ == "__main__":
    main()
