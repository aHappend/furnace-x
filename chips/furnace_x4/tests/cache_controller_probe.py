#!/usr/bin/env python3
"""Real HAMMER controller/cache boundary faults with error-only disposable interposers."""

import argparse
import datetime
import difflib
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--mutation", choices=("fault_classifier_disconnect",))
    parser.add_argument("--simulator", choices=("both", "icarus", "verilator"), default="both")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root)/f"cache-controller-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = sorted((ROOT/"rtl").glob("hammer*.sv"))
    names = [*rtl, ROOT/"tests/cache_controller_contract.sv",
             ROOT/"tests/cache_error_interposer.sv", ROOT/"tests/cache_controller_probe.py",
             ROOT/"tests/boot_probe.py"]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/cache_controller_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(name.relative_to(ROOT)): digest(name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [], "mutation": args.mutation,
        "scope": "HAMMER public coherence interface and cache-port error-only injection; "
                 "distinct from real full-top DRAIN writeback or fabric error-buffer witnesses.",
    }
    if args.repair_of:
        receipt.update(repair_of=str(args.repair_of),
                       repair_receipt_sha256=digest(project_path(args.repair_of)))
    save(output, receipt)
    print(f"Cache controller receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        original = (ROOT/"rtl/hammer_v3_top.sv").read_text()
        text = original
        for prefix, is_data in (("dc", 1), ("ic", 0)):
            before = f".out_rsp_rdata({prefix}_data), .out_rsp_error({prefix}_error)"
            if text.count(before) != 1:
                raise ValueError(f"{prefix}: expected one actual cache-to-arbiter error boundary")
            text = text.replace(before,
                                f".out_rsp_rdata({prefix}_data), .out_rsp_error(test_{prefix}_error)")
            interposer = f"""
        wire test_{prefix}_error;
        cache_error_interposer #(.IS_DATA({is_data})) test_{prefix}_error_interposer (
            .clk(clk), .rst_n(rst_n), .req_valid({prefix}_valid), .req_ready({prefix}_ready),
            .req_cmd({prefix}_cmd), .rsp_valid({prefix}_rsp_valid),
            .rsp_ready({prefix}_rsp_ready), .raw_error({prefix}_error),
            .rsp_error(test_{prefix}_error)
        );
"""
            marker = "        wire mi_request ="
            if text.count(marker) != 1:
                raise ValueError("interposer declaration marker not unique")
            text = text.replace(marker, interposer+marker)
        if args.mutation:
            before = "(coherence_state == CDWAIT && da_rsp_valid[2] && da_rsp_ready[2] && da_error[2])"
            if text.count(before) != 1:
                raise ValueError("fault classifier mutant site not unique")
            text = text.replace(before, "1'b0")
        copied = output/f"disposable-hammer-{uuid.uuid4().hex[:8]}.sv"
        copied.write_text(text)
        (output/"error-only-interposer.diff").write_text("".join(difflib.unified_diff(
            original.splitlines(True), text.splitlines(True),
            fromfile="rtl/hammer_v3_top.sv", tofile=copied.name)))
        receipt["disposable_source"] = str(copied.relative_to(ROOT))
        receipt["disposable_source_sha256"] = digest(copied)
        inputs = ["tests/cache_error_interposer.sv",
                  *[p.relative_to(ROOT) for p in rtl if p.name != "hammer_v3_top.sv"],
                  copied.relative_to(ROOT), "tests/cache_controller_contract.sv"]
        obj = output/f"obj-{uuid.uuid4().hex[:8]}"
        if not args.mutation and args.simulator != "verilator":
            run(["iverilog", "-g2012", "-Wall", "-s", "cache_controller_contract",
                 "-o", relative/"controller.vvp", *inputs], output, "icarus-compile", receipt)
        if args.mutation or args.simulator != "icarus":
            run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                 "--top-module", "cache_controller_contract", "--Mdir", obj.relative_to(ROOT),
                 *inputs], output, "verilator-compile", receipt)
        simulators = ("icarus", "verilator") if args.simulator == "both" else (args.simulator,)
        for simulator in (("verilator",) if args.mutation else simulators):
            for target in ((1,) if args.mutation else (0, 1, 2)):
                stem = f"{simulator}-target{target}"
                argv = (["vvp", relative/"controller.vvp"] if simulator == "icarus"
                        else [obj.relative_to(ROOT)/"Vcache_controller_contract"])
                result = run([*argv, f"+target={target}"], output, stem, receipt,
                             check=not args.mutation)
                text = (output/result["stdout"]).read_text()
                if args.mutation:
                    assertion = "registered maintenance fault prevents successful grant"
                    if not result["exit_code"] or result["timed_out"] or (
                            f"MISMATCH {assertion}" not in text):
                        raise ValueError("classifier mutant did not fail its intended semantic assertion")
                    receipt["mutant_detected"] = True
                    receipt["intended_assertion"] = assertion
                else:
                    matches = re.findall(r"^CACHE_CONTROLLER (.+)$", text, re.MULTILINE)
                    if len(matches) != 1:
                        raise ValueError(f"{stem}: missing boundary comparison summary")
                    counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", matches[0])}
                    if counts["target"] != target or counts["comparisons"] <= 0 or (
                            counts["retired"] < 6 or counts["clean2"] < 2 or
                            counts["injected"] != int(target != 0) or counts["recovery"] != 1):
                        raise ValueError(f"{stem}: missing actual boundary/clean/recovery events")
                    receipt["runs"].append({"scope": "controller boundary", "simulator": simulator,
                                            **counts})
                save(output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for directory in output.glob("obj-*"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Cache controller exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
