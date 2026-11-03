"""Disposable RTL defects detected only by the unchanged public-pin comparisons."""

import hashlib
import re
import shutil

import crypto_cases
from execution import ROOT, Run, fresh
import interfaces
import lz4_cases


MUTANTS = {
    "tag": ("furnace_aes128_gcm.sv", "if (|tag_difference)", "if (1'b0)",
            "gcm", r"GCM_QUARANTINE case=\d+ status=4"),
    "ghash": ("furnace_ghash_mul.sv", "128'he1000000000000000000000000000000",
              "128'he0000000000000000000000000000000",
              "gcm", r"GCM_COMPLETION case=\d+ expected=0 actual=4"),
    "overlap": ("furnace_lz4_frontend.sv", "history_pointer-offset;",
                "history_pointer-offset-16'd1;", "lz4", r"LZ4_BYTE case=\d+ index=\d+"),
    "sign": ("furnace_tensor8.sv", "$signed(weights[4*i+:4])",
             "$signed({1'b0,weights[4*i+:4]})", "tensor", r"TENSOR_MISMATCH vector=\d+ mode=0"),
    "round": ("furnace_fp32_round.sv", "significand[1] || significand[0] || significand[3]",
              "1'b1", "tensor", r"TENSOR_MISMATCH vector=\d+ mode=[12]"),
    "owner": ("furnace_axi4_xbar.sv", "read_owner[n]<=read_pick[n];",
              "read_owner[n]<=read_pick[n]+2'd1;", "xbar", r"RESPONSE_OWNERSHIP"),
}


def execute(key, compile_tb, tensor_vectors, *, preparation=True):
    filename, before, after, bench, detecting = MUTANTS[key]
    directory = fresh("mutant-" + key, preparation=preparation)
    run = Run(directory)
    try:
        run.versions(["python3", "verilator", "make", "g++"])
        copied = directory / "mutant-rtl"
        copied.mkdir()
        rtl = []
        for path in sorted(ROOT.glob("rtl/*.sv")):
            destination = copied / path.name
            shutil.copyfile(path, destination)
            rtl.append(destination)
        path = copied / filename
        original = path.read_text()
        if original.count(before) != 1:
            raise AssertionError(f"mutation anchor count: {filename}: {original.count(before)}")
        path.write_text(original.replace(before, after))
        run.receipt["mutation"] = {
            "file": filename, "before": before, "after": after,
            "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "mutant_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "expected_detection": detecting,
        }
        tb = None
        plusargs = []
        if bench == "tensor":
            vectors = directory / "tensor-vectors.txt"
            tensor_vectors(vectors)
            plusargs = ["+vectors=" + str(vectors)]
        elif bench == "gcm":
            crypto_cases.generate(directory)
            plusargs = ["+vectors=" + str(directory / "gcm-vectors.txt")]
        elif bench == "lz4":
            cases, valid = lz4_cases.make_cases(compact=True)
            vectors = directory / "lz4-vectors.txt"
            lz4_cases.write_cases(vectors, cases)
            plusargs = ["+vectors=" + str(vectors)]
        elif bench == "xbar":
            tb = directory / "xbar_tb.sv"
            tb.write_text((ROOT / "tests/xbar_tb.sv").read_text().replace(
                "/* PUBLIC_DECLARATIONS */", interfaces.crossbar_declarations()).replace(
                    "/* PUBLIC_RESET_EXPRESSION */", interfaces.crossbar_reset_expression()))
        command = compile_tb(run, bench, rtl=rtl, tb=tb)
        exit_code, stdout, stderr = run.command([*command, *plusargs], "mutant-sim", expect=None)
        match = re.search(detecting, stdout + stderr)
        if exit_code == 0 or match is None:
            raise AssertionError(f"not detected by intended functional comparison: {key}: "
                                 f"exit={exit_code}\n{stdout[-3000:]}\n{stderr[-3000:]}")
        run.receipt["detected"] = {
            "comparison": next(line for line in (stdout + stderr).splitlines() if match[0] in line),
            "simulation_exit": exit_code, "compile_exit": 0, "timeout": False,
        }
        run.finish("detected")
        return str(directory.relative_to(ROOT) / "receipt.json")
    except Exception as exc:
        run.finish("failed", exc)
        raise AssertionError(f"mutation {key}: {directory.relative_to(ROOT)}/receipt.json: {exc}") from exc
