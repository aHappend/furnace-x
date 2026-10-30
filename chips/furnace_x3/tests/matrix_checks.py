"""Mandatory compiled C0..C4 firmware graph matrix, fresh inputs for every run."""

import argparse
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT
from x3_checks import engine_memory


CELLS = {
    "C0": (4096, 8, 4, 4, 8, 8, 8, 8, 16, 1048576),
    "C1": (64, 1, 1, 1, 1, 1, 1, 1, 8, 1),
    "C2": (256, 3, 3, 3, 3, 2, 5, 3, 32, 4096),
    "C3": (4096, 8, 4, 4, 8, 8, 3, 2, 64, 1048576),
    "C4": (65536, 16, 16, 16, 64, 64, 64, 64, 64, 1048576),
}
PARAMETERS = ("MAX_TILE_BYTES", "RING_DEPTH", "FUSION_DEPTH", "MAILBOX_DEPTH",
              "IN_WIDTH", "IN_HEIGHT", "OUT_WIDTH", "OUT_HEIGHT", "FFT_N", "MAX_DMA_BYTES")


def run_seed(experiment, cell, seed, binary, image, metadata, batch):
    tile, ring, fusion, mailbox, iw, ih, ow, oh, fft_n, max_dma = CELLS[cell]
    graphs = max(2, ring+1, 2*fusion+1, 2*mailbox+1)
    directory = experiment.path
    if batch:
        directory /= f"seed{seed}-{experiment.path.name.rsplit('-', 1)[1]}"
        directory.mkdir()
    experiment.command(["python3", "tests/firmware_reference_checks.py",
                        "--cell", cell, "--seed", str(seed)], f"reference-seed{seed}")
    for graph in range(graphs):
        memory, expected = engine_memory(seed, (iw, ih, ow, oh, fft_n),
            ring, fusion, max_dma, graph, 131072, tile)
        for name, data in (("memory", memory), ("expected", expected)):
            (directory / f"{name}-{graph}.hex").write_text(
                "".join(f"{value:02x}\n" for value in data))
    dma_bursts = 1+math.ceil(min(max_dma, 2049)/1024)
    output = experiment.command([
        str(binary.relative_to(ROOT)), f"+image={image.relative_to(ROOT)}",
        f"+words={metadata['bytes']//4}",
        f"+memory={(directory / 'memory-0.hex').relative_to(ROOT)}",
        f"+expected={(directory / 'expected-0.hex').relative_to(ROOT)}",
        f"+seed={seed}", "+engines=1", f"+graphs={graphs}", "+native_b_delay=4096",
        f"+dma_bursts={dma_bursts}", f"+matrix={directory.relative_to(ROOT)}"],
        f"simulate-seed{seed}", timeout=12000 if cell == "C4" else 3600)
    match = re.search(r"X3_GRAPH_EVENTS graphs=(\d+) descriptors=(\d+) frames=(\d+) "
                      r"mailboxes=(\d+) legacy_reads=(\d+) legacy_writes=(\d+) "
                      r"overlap=(\d+) multibeat=(\d+)", output)
    if "X3_FIRMWARE_SMOKE_PASS" not in output or not match:
        raise AssertionError("matrix comparisons/observed events missing")
    actual = dict(zip(("graphs", "descriptors", "frames", "mailboxes", "legacy_reads",
                       "legacy_writes", "overlap", "multibeat"), map(int, match.groups())))
    thresholds = {"graphs": 2, "descriptors": 2*ring+1, "frames": 2*fusion+1,
                  "mailboxes": 2*mailbox+1, "legacy_reads": 1, "legacy_writes": 1}
    if max_dma > 1:
        thresholds.update(multibeat=1, overlap=1)
    for name, minimum in thresholds.items():
        if actual[name] < minimum:
            raise AssertionError(f"{cell}/{seed}: {name}={actual[name]} < {minimum}")
    (directory / "coverage.json").write_text(json.dumps({
        "cell": cell, "seed": seed, "required": thresholds, "actual": actual,
        "numerical_comparison": "bit-exact complete DDR byte image after every graph",
        "input_parameters": dict(zip(PARAMETERS, CELLS[cell])),
    }, indent=2) + "\n")
    print(output.strip(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", choices=CELLS, default="C1")
    parser.add_argument("--seed", type=int, choices=(17, 89, 2027), default=17)
    parser.add_argument("--repair-of")
    parser.add_argument("--all-seeds", action="store_true")
    args = parser.parse_args()
    seed_label = "all-seeds" if args.all_seeds else f"seed{args.seed}"
    experiment = Experiment(f"firmware-matrix-{args.cell.lower()}-{seed_label}", args.repair_of)
    obj = experiment.path / "compile-obj"
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        tile, ring, fusion, mailbox, iw, ih, ow, oh, fft_n, max_dma = CELLS[args.cell]
        image = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", str(iw),
                            "--in-height", str(ih), "--fft-n", str(fft_n),
                            "--output", str(image.relative_to(ROOT))], "firmware-build")
        metadata = json.loads(image.with_suffix(".json").read_text())
        params = [f"-G{name}={value}" for name, value in zip(PARAMETERS, CELLS[args.cell])]
        cycle_limit = 500000000 if args.cell == "C4" else 200000000
        params += ["-GMEMORY_BYTES=131072", f"-GCYCLE_LIMIT={cycle_limit}"]
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "x3_smoke_tb", *params,
                            "-MAKEFLAGS", "OPT_FAST=-O3",
                            "--Mdir", str(obj.relative_to(ROOT)), "-o", "matrix-sim",
                            *sources, "tests/x3_smoke_tb.sv"], "compile")
        for seed in ((17, 89, 2027) if args.all_seeds else (args.seed,)):
            run_seed(experiment, args.cell, seed, obj / "matrix-sim", image, metadata, args.all_seeds)
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
