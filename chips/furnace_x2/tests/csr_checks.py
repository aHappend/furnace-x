"""AXI-Lite transaction, byte-mask, security and event-side-effect assertions."""

from run_support import ROOT


def execute(run):
    obj = run.path/"csr-obj"
    try:
        run.command(["verilator", "--version"], "csr-version")
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "csr_probe", "--Mdir", str(obj),
                     "-o", "sim", "rtl/furnace_x2_csr.sv", "tests/csr_probe.sv"], "csr-compile")
        log = run.command([str(obj/"sim")], "csr-simulation")
        if "COMPARED csr_writes=" not in log.read_text():
            raise AssertionError("missing CSR comparison summary")
        run.receipt["csr_comparisons"] = dict(
            byte_strobes=16, channel_arrival_orders=3, lock_causes=3,
            raw_output=str(log.relative_to(ROOT)))
        run.save()
    finally:
        run.remove_intermediates(obj)
