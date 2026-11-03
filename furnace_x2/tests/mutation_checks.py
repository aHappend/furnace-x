"""Disposable-source functional defect sensitivity, never source-text kills."""

import difflib
import hashlib

import fusion_checks
import kernel_checks
import probe_soc
import qos_checks
from run_support import ROOT, Run


CASES = (
    ("bilinear-rounding", "furnace_bilinear_pipe.sv",
     "+28'd32768", "+28'd0", "kernel0", "NUMERICAL kind=0"),
    ("sobel-sign", "furnace_spatial3x3_pipe.sv",
     "gx0<=p[2]-p[0]", "gx0<=p[0]-p[2]", "kernel1", "NUMERICAL kind=1"),
    ("fir-coefficient", "furnace_fir4_pipe.sv",
     "product1<=h0+(h0<<<1)", "product1<=h0+(h0<<<0)", "kernel2", "NUMERICAL kind=2"),
    ("fft-twiddle-sign", "furnace_fft_radix2.sv",
     "wi0<=twiddle_im", "wi0<=-twiddle_im", "kernel3", "NUMERICAL kind=3"),
    ("fusion-id", "furnace_fusion_buffer.sv",
     "output_id<=vh[79:64]", "output_id<=ah[79:64]", "fusion", "FUSION NUMERICAL"),
    ("fusion-lane-order", "furnace_fusion_buffer.sv",
     "output_data<={ah[63:0],vh[63:0]}", "output_data<={vh[63:0],ah[63:0]}",
     "fusion", "FUSION NUMERICAL"),
    ("qos-priority", "furnace_axi4_qos_xbar.sv",
     "s_axi_arqos[candidate]>s_axi_arqos[read_pick[t]]",
     "s_axi_arqos[candidate]<s_axi_arqos[read_pick[t]]", "qos", "QOS PRIORITY"),
    ("authentication-fence", "furnace_aes128_gcm.sv",
     "if (|tag_difference)", "if (1'b0 && (|tag_difference))",
     "soc", "corrupt-tag candidate was not rejected"),
)


def exercise(run, kind, sources=None):
    if kind.startswith("kernel"):
        kernel_checks.execute(run, int(kind[-1]), 16, "verilator", sources=sources)
    elif kind == "fusion":
        fusion_checks.execute(run, 1, sources=sources)
    elif kind == "qos":
        qos_checks.execute(run, sources=sources)
    elif kind == "soc":
        probe_soc.execute(run, probe_soc.CELLS[1], 17, "verilator", sources=sources)
    else:
        raise ValueError(f"unknown mutation target {kind}")


def one(run, index, control=True):
    name, filename, before, after, kind, assertion = CASES[index]
    original = ROOT/"rtl"/filename
    text = original.read_text()
    if text.count(before) != 1:
        raise AssertionError(f"{name}: mutation requires exactly one anchor")
    if control:
        exercise(run, kind)
        run.receipt["unmutated_control"] = "passed"
    # A separate namespace keeps all original logs, vectors and outputs intact.
    mutant = Run(f"l1-mutant-{name}",
                 ["python3", "tests/verify.py", "--suite", "mutations"],
                 preparation=not run.receipt["acceptance_evidence"])
    error = None
    try:
        copies = []
        for source in sorted(ROOT.glob("rtl/*.sv")):
            target = mutant.path/source.name
            data = (text.replace(before, after).encode() if source == original
                    else source.read_bytes())
            (ROOT/target).write_bytes(data)
            copies.append(str(target))
            mutant.receipt.setdefault("mutant_sha256", {})[str(target)] = hashlib.sha256(
                data).hexdigest()
        diff = "".join(difflib.unified_diff(
            text.splitlines(True), text.replace(before, after).splitlines(True),
            fromfile=f"rtl/{filename}", tofile=f"mutant/{filename}"))
        (ROOT/mutant.path/"mutation.diff").write_text(diff)
        mutant.receipt["mutation"] = dict(
            name=name, source=f"rtl/{filename}", diff=str(mutant.path/"mutation.diff"),
            required_assertion=assertion)
        mutant.save()
        try:
            exercise(mutant, kind, copies)
        except RuntimeError:
            commands = mutant.receipt["commands"]
            failures = [command for command in commands if command.get("exit_code") not in (0, None)]
            if len(failures) != 1:
                raise AssertionError("mutation did not produce exactly one functional rejection")
            failure = failures[0]
            if "simulation" not in failure["stdout"] or failure.get("timeout"):
                raise AssertionError("compile/tool/timeout failure is not a functional kill")
            log = (ROOT/failure["stdout"]).read_text()
            if assertion not in log:
                raise AssertionError(f"wrong rejection: expected {assertion!r}, see {failure['stdout']}")
            if not any("compile.stdout" in c["stdout"] and c.get("exit_code") == 0
                       for c in commands):
                raise AssertionError("functional kill requires successful real compilation")
            mutant.receipt["functional_kill"] = True
            mutant.receipt["expected_failure"] = failure["stdout"]
        else:
            raise AssertionError(f"mutation survived: {name}")
        for source in ROOT.glob("rtl/*.sv"):
            expected = run.receipt["source_sha256"][str(source.relative_to(ROOT))]
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise AssertionError("accepted RTL changed during mutation check")
        run.receipt.setdefault("mutation_results", []).append(
            dict(name=name, compiled=True, functional_kill=True,
                 required_assertion=assertion, receipt=str(mutant.path/"receipt.json")))
        run.save()
    except Exception as caught:
        error = caught
        raise
    finally:
        mutant.finish(error)


def execute(run):
    for kind in ("kernel0", "kernel1", "kernel2", "kernel3", "fusion", "qos", "soc"):
        exercise(run, kind)
    run.receipt["unmutated_control"] = "passed"
    for index in range(len(CASES)):
        one(run, index, control=False)
    if len(run.receipt["mutation_results"]) != 8:
        raise AssertionError("all eight distinct functional kills are mandatory")
