"""Ordered-stream public-pin fusion checks, including depth-one pop/push."""

from run_support import ROOT


def execute(run, depth=1, sources=None):
    label = f"fusion-depth{depth}"
    obj = run.path / f"{label}-obj"
    sources = ["rtl/furnace_fusion_buffer.sv"] if sources is None else sources
    try:
        run.command(["verilator", "--version"], f"{label}-version")
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "fusion_probe", "--Mdir", str(obj),
                     "-o", "sim", f"-GDEPTH={depth}", *sources,
                     "tests/fusion_probe.sv"], f"{label}-compile")
        log = run.command([str(obj/"sim")], f"{label}-simulation")
        if f"COMPARED fusion=128 depth={depth}" not in log.read_text():
            raise AssertionError("fusion comparison summary absent")
        run.receipt.setdefault("fusion_comparisons", []).append(
            dict(depth=depth, pairs=128, raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
