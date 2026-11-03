"""Bounded compiler-optimization equivalence probe, never matrix acceptance."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matrix_checks import CELLS, PARAMETERS
from record import Experiment, ROOT
from x3_checks import engine_memory


def main():
    experiment = Experiment("c4-compiled-optimization",
        "evidence/preparation/firmware-matrix-c4-seed89-20261030T142210205515Z/receipt.json")
    try:
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        experiment.command(["g++", "--version"], "cxx-version", version=True)
        tile, ring, fusion, _, iw, ih, ow, oh, fft_n, max_dma = CELLS["C4"]
        image = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", str(iw),
                            "--in-height", str(ih), "--fft-n", str(fft_n),
                            "--output", str(image.relative_to(ROOT))], "firmware-build")
        words = len(image.read_text().split())
        memory, expected = engine_memory(89, (iw, ih, ow, oh, fft_n),
                                         ring, fusion, max_dma, 0, 131072, tile)
        for name, data in (("memory", memory), ("expected", expected)):
            (experiment.path / f"{name}.hex").write_text("".join(f"{value:02x}\n" for value in data))
        outputs, performance = {}, {}
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        for option in ("-Os", "-O3"):
            label = option[1:].lower()
            obj = experiment.path / f"compile-{label}-{experiment.path.name.rsplit('-', 1)[1]}"
            try:
                experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                    "--top-module", "x3_smoke_tb",
                    *(f"-G{name}={value}" for name, value in zip(PARAMETERS, CELLS["C4"])),
                    "-GMEMORY_BYTES=131072", "-GCYCLE_LIMIT=20000000",
                    "-MAKEFLAGS", f"OPT_FAST={option}",
                    "--Mdir", str(obj.relative_to(ROOT)), "-o", "profile-sim",
                    *sources, "tests/x3_smoke_tb.sv"], f"compile-{label}")
                output = experiment.command([str((obj / "profile-sim").relative_to(ROOT)),
                    f"+image={image.relative_to(ROOT)}", f"+words={words}",
                    f"+memory={(experiment.path / 'memory.hex').relative_to(ROOT)}",
                    f"+expected={(experiment.path / 'expected.hex').relative_to(ROOT)}",
                    "+seed=89", "+engines=1", "+graphs=1", "+native_b_delay=4096",
                    "+dma_bursts=4"], f"simulate-{label}", timeout=1200)
                outputs[label] = [line for line in output.splitlines() if line.startswith("X3_")]
                if not any("X3_FIRMWARE_SMOKE_PASS" in line for line in outputs[label]):
                    raise AssertionError("bounded profile numerical comparisons absent")
                performance[label] = experiment.data["commands"][-1]["elapsed_s"]
            finally:
                for pattern in ("*.o", "*.a", "*.gch"):
                    for path in obj.glob(pattern):
                        path.unlink()
        if outputs["os"] != outputs["o3"]:
            raise AssertionError("compiler optimization changed public numerical/protocol/cycle results")
        (experiment.path / "performance.json").write_text(json.dumps({
            "simulation_seconds": performance, "public_results": outputs["os"],
            "scope": "one graph; not C4 queue-wrap/multiseed matrix acceptance",
        }, indent=2) + "\n")
        print(f"SIMULATOR_OPTIMIZATION_EQUIVALENCE_PASS compared_graphs=1 "
              f"guard_bytes=131072 os_seconds={performance['os']:.3f} "
              f"o3_seconds={performance['o3']:.3f}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
