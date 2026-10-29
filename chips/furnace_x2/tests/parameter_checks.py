"""Executable legal endpoints and diagnostic-only invalid configurations."""

from run_support import ROOT


RANGES = dict(MAX_TILE_BYTES=(1, 65536), RING_DEPTH=(1, 16),
              IN_WIDTH=(1, 64), IN_HEIGHT=(1, 64), OUT_WIDTH=(1, 64),
              OUT_HEIGHT=(1, 64), FFT_N=(8, 64), FUSION_DEPTH=(1, 16))


def execute(run):
    run.command(["iverilog", "-V"], "parameters-compiler-version")
    run.command(["vvp", "-V"], "parameters-simulator-version")
    cases = []
    for name, (low, high) in RANGES.items():
        cases.extend([({name: low}, True), ({name: high}, True),
                      ({name: low-1}, False), ({name: high+1}, False)])
    cases.append(({"FFT_N": 12}, False))
    cases.append(({name: values[1] for name, values in RANGES.items()}, True))
    rtl = [str(p.relative_to(ROOT)) for p in sorted(ROOT.glob("rtl/*.sv"))]
    ledger = []
    for index, (params, legal) in enumerate(cases):
        label = f"parameters-{index}"
        binary = run.path/f"{label}.vvp"
        try:
            run.command(["iverilog", "-g2012", "-Wall", "-s", "parameter_probe",
                         "-o", str(binary),
                         *[f"-Pparameter_probe.{name}={value}" for name, value in params.items()],
                         *rtl, "tests/parameter_probe.sv"], f"{label}-compile")
            failure = None
            try:
                log = run.command(["vvp", str(binary)], f"{label}-simulation")
            except RuntimeError as caught:
                failure = caught
                log = ROOT/run.receipt["commands"][-1]["stdout"]
            text = log.read_text()
            if legal:
                if failure is not None or "ELABORATED LEGAL" not in text:
                    raise AssertionError(f"legal endpoint rejected: {params}; see {log}")
            elif failure is None or "PARAMETER ERROR" not in text:
                raise AssertionError(f"invalid parameter diagnostic not executed: {params}; see {log}")
            ledger.append(dict(parameters=params, legal=legal, compile_exit=0,
                               diagnostic_rejection=not legal, raw_output=str(log.relative_to(ROOT))))
            run.receipt["parameter_boundaries"] = ledger
            run.save()
        finally:
            run.remove_intermediates(binary)
