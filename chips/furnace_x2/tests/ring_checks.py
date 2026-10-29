"""Batch command-ring capacity, rejection, wrap and reset comparisons."""

from run_support import ROOT


def execute(run, depth, reference=False):
    label = f"ring-{depth}-{'parent' if reference else 'deliverable'}"
    obj = run.path/f"{label}-obj"
    directory = "furnace_x1_reference/rtl" if reference else "rtl"
    try:
        run.command(["verilator", "--version"], f"{label}-version")
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "ring_probe", "--Mdir", str(obj),
                     "-o", "sim", f"-GDEPTH={depth}", f"{directory}/furnace_command_ring.sv",
                     "tests/ring_probe.sv"], f"{label}-compile")
        log = run.command([str(obj/"sim")], f"{label}-simulation")
        if f"COMPARED ring_depth={depth}" not in log.read_text():
            raise AssertionError("ring comparisons absent")
        run.receipt.setdefault("ring_comparisons", []).append(
            dict(depth=depth, reference=reference, raw_output=str(log.relative_to(ROOT))))
        run.save()
    finally:
        run.remove_intermediates(obj)
