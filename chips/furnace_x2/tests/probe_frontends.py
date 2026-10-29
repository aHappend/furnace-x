"""Bounded public-pin preparation probe; not a replacement for any L1 suite."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mm_oracle as model


ROOT = Path(__file__).resolve().parent.parent
CELLS = [(8, 8, 8, 8, 16), (1, 1, 1, 1, 8), (5, 3, 7, 2, 32),
         (13, 9, 3, 5, 64), (3, 2, 16, 9, 16),
         (64, 64, 64, 64, 64), (64, 1, 1, 64, 8)]


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", type=int, choices=range(len(CELLS)), default=0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--simulator", choices=("iverilog", "verilator"), default="verilator")
    parser.add_argument("--repair-of", help="Project-relative earlier preparation receipt")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path("evidence/preparation") / f"frontends-{stamp}-{uuid4().hex[:12]}"
    (ROOT / out).mkdir(parents=True, exist_ok=False)
    sources = (sorted(ROOT.glob("rtl/*.sv")) + sorted(ROOT.glob("tests/*"))
               + sorted(ROOT.glob("design/*.md")))
    sources = [p for p in sources if p.is_file()]
    receipt = {
        "schema": 1, "acceptance_evidence": False,
        "argv": [sys.executable, *sys.argv], "cwd": ".",
        "started_at": now(), "configuration": CELLS[args.cell], "seed": args.seed,
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sources},
        "commands": [],
    }
    if args.repair_of:
        prior = Path(args.repair_of)
        if prior.is_absolute() or ".." in prior.parts or not (ROOT / prior).is_file():
            raise ValueError("--repair-of must name an existing project-relative receipt")
        receipt["repair_of"] = str(prior)
    obj = out / "compile-obj"

    def run(argv, stem, timeout=3600):
        record = {"argv": argv, "cwd": ".", "started_at": now(), "timeout_s": timeout,
                  "stdout": str(out / f"{stem}.stdout.txt"),
                  "stderr": str(out / f"{stem}.stderr.txt")}
        receipt["commands"].append(record)
        try:
            with (ROOT / record["stdout"]).open("w") as stdout, (
                    ROOT / record["stderr"]).open("w") as stderr:
                child = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr,
                                       timeout=timeout, check=False)
            record.update(exit_code=child.returncode, timeout=False)
            if child.returncode:
                raise RuntimeError(f"{stem} exit {child.returncode}; see {record['stdout']} and {record['stderr']}")
        except subprocess.TimeoutExpired:
            record.update(exit_code=None, timeout=True)
            raise
        finally:
            record["ended_at"] = now()

    def write_hex(name, values, width):
        path = out / name
        (ROOT / path).write_text("".join(f"{v:0{width}x}\n" for v in values))
        receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
            (ROOT / path).read_bytes()).hexdigest()
        return str(path)

    try:
        cell = CELLS[args.cell]
        if args.simulator == "iverilog" and max(cell[:4]) >= 64:
            args.simulator = "verilator"
        receipt["configuration"] = cell
        iw, ih, ow, oh, n = cell
        frames = 1 if args.simulator == "iverilog" else 8
        receipt["frames_per_modality"] = frames
        rng = random.Random(args.seed)
        vi, ai, ve, ae = [], [], [], []
        for frame in range(frames):
            ident = (65533 + frame) & 65535
            pixels = [rng.randrange(256) for _ in range(iw * ih)]
            samples = [rng.randrange(-32768, 32768) for _ in range(n)]
            if frame == 0:
                pixels = [255] * len(pixels)
                samples = [-32768] * n
            elif frame == 1:
                pixels = [i & 255 for i in range(len(pixels))]
                samples = [32767, -32768] * (n // 2)
            elif frame == 2:
                pixels = [0] * len(pixels)
                pixels[0] = 255
                samples = [32767] + [0] * (n - 1)
            vf = model.vision(pixels, iw, ih, ow, oh)[2]
            _, bins, af = model.audio(samples)
            model.check_dft(model.fir(samples), bins)
            vi.extend((int(i == len(pixels)-1) << 24) | (ident << 8) | p
                      for i, p in enumerate(pixels))
            ai.extend((int(i == n-1) << 32) | (ident << 16) | (p & 65535)
                      for i, p in enumerate(samples))
            ve.append((ident << 64) | sum((v & 65535) << (16*i) for i, v in enumerate(vf)))
            ae.append((ident << 64) | sum((v & 65535) << (16*i) for i, v in enumerate(af)))
        vf = write_hex("vision.hex", vi, 7)
        af = write_hex("audio.hex", ai, 9)
        vef = write_hex("vision-expected.hex", ve, 22)
        aef = write_hex("audio-expected.hex", ae, 22)
        params = dict(zip(("IW", "IH", "OW", "OH", "N"), cell))
        rtl = ["rtl/furnace_x2_vision.sv", "rtl/furnace_bilinear_pipe.sv",
               "rtl/furnace_spatial3x3_pipe.sv", "rtl/furnace_x2_audio.sv",
               "rtl/furnace_fir4_pipe.sv", "rtl/furnace_fft_radix2.sv",
               "tests/frontend_probe.sv"]
        simulation_args = [f"+VISION={vf}", f"+AUDIO={af}",
                           f"+VEXPECTED={vef}", f"+AEXPECTED={aef}",
                           f"+VC={len(vi)}", f"+AC={len(ai)}", f"+FRAMES={frames}",
                           f"+SEED={args.seed}"]
        # Compiled simulation is mandatory for multiframe sweeps.
        if args.simulator == "iverilog":
            run(["iverilog", "-V"], "compiler-version")
            run(["vvp", "-V"], "simulator-version")
            run(["iverilog", "-g2012", "-Wall", "-s", "frontend_probe",
                 "-o", str(out / "sim.vvp"),
                 *[f"-Pfrontend_probe.{k}={v}" for k, v in params.items()], *rtl], "compile")
            run(["vvp", str(out / "sim.vvp"), *simulation_args], "simulation")
        else:
            run(["verilator", "--version"], "version")
            run(["verilator", "--binary", "--timing", "-Wno-fatal",
                 "--top-module", "frontend_probe", "--Mdir", str(obj),
                 "-o", "sim", *[f"-G{k}={v}" for k, v in params.items()], *rtl], "compile")
            run([str(obj / "sim"), *simulation_args], "simulation")
        receipt["exit_code"] = 0
    except Exception as error:
        receipt["exit_code"] = 1
        receipt["error"] = str(error)
    finally:
        if (ROOT / obj).is_dir():
            shutil.rmtree(ROOT / obj)
        binary = ROOT / out / "sim.vvp"
        if binary.is_file():
            binary.unlink()
        receipt["ended_at"] = now()
        (ROOT / out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"{out}/receipt.json: exit={receipt['exit_code']}")
    return receipt["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
