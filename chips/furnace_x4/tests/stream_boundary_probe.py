#!/usr/bin/env python3
"""Vision geometry and all audio FFT sizes, with independent fixed-point models."""

import argparse
import datetime
import json
import math
from pathlib import Path
import random
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save

GEOMETRIES = (
    (8, 8, 8, 8, 16), (1, 1, 1, 1, 8), (1, 9, 1, 13, 32),
    (13, 1, 9, 1, 64), (5, 3, 7, 2, 16), (3, 5, 2, 7, 8),
    (64, 64, 64, 64, 64), (64, 1, 1, 64, 32), (1, 64, 64, 1, 16),
)


def vision_features(pixels, iw, ih, ow, oh):
    resized = []
    for y in range(oh):
        qy = 0 if oh == 1 else 256*y*(ih-1)//(oh-1)
        y0, fy = divmod(qy, 256)
        for x in range(ow):
            qx = 0 if ow == 1 else 256*x*(iw-1)//(ow-1)
            x0, fx = divmod(qx, 256)
            p = lambda dx, dy: pixels[min(ih-1, y0+dy)*iw+min(iw-1, x0+dx)]
            total = (p(0, 0)*(256-fx)+p(1, 0)*fx)*(256-fy)
            total += (p(0, 1)*(256-fx)+p(1, 1)*fx)*fy
            resized.append((total+32768) >> 16)
    totals = [0]*4
    for y in range(oh):
        for x in range(ow):
            p = lambda dx, dy: resized[min(oh-1, max(0, y+dy))*ow+min(ow-1, max(0, x+dx))]
            gx = sum(coef*p(dx, dy) for dy in (-1, 0, 1)
                     for dx, coef in ((-1, -2 if dy == 0 else -1),
                                      (1, 2 if dy == 0 else 1)))
            gy = sum(coef*p(dx, dy) for dx in (-1, 0, 1)
                     for dy, coef in ((-1, -2 if dx == 0 else -1),
                                      (1, 2 if dx == 0 else 1)))
            lap = p(0, -1)+p(-1, 0)+p(1, 0)+p(0, 1)-4*p(0, 0)
            for lane, value in enumerate((p(0, 0), abs(gx), abs(gy), abs(lap))):
                totals[lane] += value
    return sum((total//(ow*oh)) << (16*lane) for lane, total in enumerate(totals))


def audio_features(samples):
    n = len(samples)
    filtered = []
    for i, x in enumerate(samples):
        previous = lambda k: samples[i-k] if i >= k else 0
        filtered.append((x+3*previous(1)+3*previous(2)+previous(3)) >> 3)
    bits = n.bit_length()-1
    values = [(filtered[int(f"{i:0{bits}b}"[::-1], 2)], 0) for i in range(n)]
    saturate = lambda x: min((1 << 31)-1, max(-(1 << 31), x))
    span = 2
    while span <= n:
        half = span//2
        for base in range(0, n, span):
            for k in range(half):
                wr = round(32768*math.cos(2*math.pi*k/span))
                wi = round(-32768*math.sin(2*math.pi*k/span))
                ar, ai = values[base+k]
                br, bi = values[base+k+half]
                tr, ti = (br*wr-bi*wi) >> 15, (br*wi+bi*wr) >> 15
                values[base+k] = (saturate(ar+tr), saturate(ai+ti))
                values[base+k+half] = (saturate(ar-tr), saturate(ai-ti))
        span *= 2
    magnitude = [abs(real)+abs(imaginary) for real, imaginary in values]
    lanes = (sum(abs(x) for x in filtered)//n, min(32767, magnitude[0]//n),
             min(32767, sum(magnitude[1:n//4+1])//n),
             min(32767, sum(magnitude[n//4+1:n//2+1])//n))
    return sum(value << (16*lane) for lane, value in enumerate(lanes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"stream-boundary-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = [f"rtl/{name}.sv" for name in (
        "furnace_x2_vision", "furnace_bilinear_pipe", "furnace_spatial3x3_pipe",
        "furnace_x2_audio", "furnace_fir4_pipe", "furnace_fft_radix2",
    )]
    source_names = rtl + ["tests/stream_boundary_contract.sv", "tests/stream_boundary_probe.py",
                          "tests/boot_probe.py"]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/stream_boundary_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {name: digest(ROOT/name) for name in source_names},
        "start_utc": now(), "end_utc": None, "exit_code": None, "timeout_s": 2700,
        "commands": [], "runs": [], "fixtures": {}, "scope": "Leaf legal geometry/audio/reset/error boundaries",
    }
    save(output, receipt)
    status = 1
    try:
        if vision_features([73], 1, 1, 1, 1) != 73 or audio_features([0]*8) != 0:
            raise ValueError("independent model known-answer failure")
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        for cell, geometry in enumerate(GEOMETRIES):
            iw, ih, ow, oh, fn = geometry
            directory = output / f"cell{cell}-{uuid.uuid4().hex[:8]}"
            directory.mkdir()
            parameters = dict(zip(("IW", "IH", "OW", "OH", "FN"), geometry))
            run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                 "--top-module", "stream_boundary_contract", "--Mdir",
                 directory.relative_to(ROOT)/"obj",
                 *[f"-G{name}={value}" for name, value in parameters.items()],
                 *rtl, "tests/stream_boundary_contract.sv"],
                output, f"cell{cell}-verilator-compile", receipt)
            if cell == 1:
                run(["iverilog", "-g2012", "-Wall", "-s", "stream_boundary_contract", "-o",
                     directory.relative_to(ROOT)/"stream.vvp",
                     *[f"-Pstream_boundary_contract.{name}={value}"
                       for name, value in parameters.items()], *rtl, "tests/stream_boundary_contract.sv"],
                    output, f"cell{cell}-icarus-compile", receipt)
            for seed in (17, 89, 211):
                rng = random.Random(seed)
                pixels = [rng.randrange(256) for _ in range(iw*ih)]
                samples = [rng.randrange(-32768, 32768) for _ in range(fn)]
                expected = (vision_features(pixels, iw, ih, ow, oh) << 64) | audio_features(samples)
                paths = [directory/f"{name}-{seed}.hex" for name in ("pixels", "samples", "expected")]
                paths[0].write_text("".join(f"{x:02x}\n" for x in pixels))
                paths[1].write_text("".join(f"{x & 65535:04x}\n" for x in samples))
                paths[2].write_text(f"{expected:032x}\n")
                receipt["fixtures"].update({str(p.relative_to(ROOT)): digest(p) for p in paths})
                for simulator in (("icarus", "verilator") if cell == 1 and seed == 17 else ("verilator",)):
                    argv = (["vvp", directory.relative_to(ROOT)/"stream.vvp"] if simulator == "icarus" else
                            [directory.relative_to(ROOT)/"obj/Vstream_boundary_contract"])
                    stem = f"cell{cell}-{simulator}-{seed}"
                    run([*argv, *[f"+{name}={p.relative_to(ROOT)}"
                                  for name, p in zip(("pixels", "samples", "expected"), paths)]],
                        output, stem, receipt)
                    text = (output/f"{stem}.stdout.txt").read_text()
                    match = re.search(r"STREAM_BOUNDARY vision_tokens=(\d+) audio_tokens=(\d+) "
                                      r"comparisons=(\d+) stalls=(\d+) failures=(\d+)", text)
                    if not match:
                        raise ValueError(f"{stem}: missing comparison summary")
                    vision, audio, comparisons, stalls, failures = map(int, match.groups())
                    if (vision, audio, stalls, failures) != (4, 4, 24, 0) or comparisons <= 0:
                        raise ValueError(f"{stem}: observed coverage/assertion failure")
                    receipt["runs"].append({"scope": "leaf", "geometry": geometry, "seed": seed,
                                            "simulator": simulator, "vision_tokens": vision,
                                            "audio_tokens": audio, "comparisons": comparisons,
                                            "stalls": stalls, "failures": failures})
                    save(output, receipt)
            for path in (directory/"obj").iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        if len(receipt["runs"]) != len(GEOMETRIES)*3+1:
            raise ValueError("missing mandatory geometry/seed row")
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed during boundary verification: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for directory in output.glob("cell*-*/obj"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Stream boundary receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
