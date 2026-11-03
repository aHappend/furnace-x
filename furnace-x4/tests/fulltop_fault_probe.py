#!/usr/bin/env python3
"""CPU-executed full-top persistent clean error, containment and coherent reset recovery."""

import argparse
import datetime
import difflib
import json
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
    parser.add_argument("--mutation", choices=("drain_fault_classifier_disconnect",))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root)/f"fulltop-fault-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = sorted((ROOT/"rtl").glob("*.sv"))
    names = [*rtl, *[ROOT/"tests"/name for name in (
        "fulltop_fault_endpoint.cpp", "fulltop_fault_program.S", "fulltop_fault_probe.py",
        "boot_endpoint.cpp", "boot_execution_model.h", "boot_observers.sv", "boot_probe.py")]]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/fulltop_fault_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(name.relative_to(ROOT)): digest(name) for name in names},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [], "mutation": args.mutation,
        "scope": "Real complete default top; persistent DRAIN halt-clean endpoint SLVERR, "
                 "architectural containment and reset/reboot/coherent DMA recovery. Not Linux acceptance.",
    }
    if args.repair_of:
        receipt.update(repair_of=str(args.repair_of),
                       repair_receipt_sha256=digest(project_path(args.repair_of)))
    save(output, receipt)
    print(f"Full-top fault receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        for tool in ("python3", "verilator", "make", "g++",
                     "riscv64-unknown-elf-gcc", "riscv64-unknown-elf-objcopy",
                     "riscv64-unknown-elf-nm"):
            run([tool, "--version"], output, tool+"-version", receipt)
        run(["riscv64-unknown-elf-gcc", "-march=rv64ima_zicsr", "-mabi=lp64", "-mno-relax",
             "-nostdlib", "-nostartfiles", "-Wl,--build-id=none", "-Wl,-Ttext=0x80000000",
             "tests/fulltop_fault_program.S", "-o", relative/"firmware.elf"],
            output, "firmware-compile", receipt)
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", relative/"firmware.elf",
             relative/"firmware.bin"], output, "firmware-binary", receipt)
        run(["riscv64-unknown-elf-nm", relative/"firmware.elf"], output, "firmware-symbols", receipt)
        symbols = (output/"firmware-symbols.stdout.txt").read_text()
        matches = re.findall(r"^([0-9a-f]+) T trap_handler$", symbols, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("actual trap-handler symbol required")
        handler = int(matches[0], 16)
        firmware = output/"firmware.bin"
        (output/"image-index.txt").write_text(
            f"2147483648 {firmware.stat().st_size} {firmware.relative_to(ROOT)}\n")
        receipt["firmware_sha256"] = digest(firmware)
        receipt["trap_handler_pc"] = handler
        if args.mutation:
            original = (ROOT/"rtl/hammer_v3_top.sv").read_text()
            before = "(coherence_state == CDRAIN && halt_clean_error)"
            if original.count(before) != 1:
                raise ValueError("DRAIN classifier site not unique")
            text = original.replace(before, "1'b0")
            copied = output/f"disposable-hammer-{uuid.uuid4().hex[:8]}.sv"
            copied.write_text(text)
            (output/"classifier-disconnect.diff").write_text("".join(difflib.unified_diff(
                original.splitlines(True), text.splitlines(True),
                fromfile="rtl/hammer_v3_top.sv", tofile=copied.name)))
            receipt["disposable_source_sha256"] = digest(copied)
            rtl = [copied if p.name == "hammer_v3_top.sv" else p for p in rtl]
        obj = relative/f"obj-{uuid.uuid4().hex[:8]}"
        cpp = Path(*([".."]*len(obj.parts)))/"tests/fulltop_fault_endpoint.cpp"
        run(["verilator", "--cc", "--exe", "--build", "-j", "2",
             "--top-module", "furnace_x4_top", "--Mdir", obj, "--assert", "-Wno-fatal",
             "-O3", "--output-split", "10000", "--output-split-cfuncs", "10000",
             "-MAKEFLAGS", "OPT_FAST=-O3 OPT_SLOW=-O3 OPT_GLOBAL=-O3",
             "-CFLAGS", "-O3 -std=c++17",
             *[p.relative_to(ROOT) for p in rtl], "tests/boot_observers.sv", cpp],
            output, "compile", receipt)
        for seed in ((17,) if args.mutation else (17, 89, 211)):
            folder = output/f"seed{seed}-{uuid.uuid4().hex[:8]}"
            folder.mkdir()
            result = run([obj/"Vfurnace_x4_top", relative/"image-index.txt",
                          folder.relative_to(ROOT), str(seed), str(handler),
                          str(int(bool(args.mutation)))],
                         output, f"seed{seed}", receipt, check=not args.mutation)
            if args.mutation:
                message = (output/result["stderr"]).read_text()
                intended = next((assertion for assertion in (
                    "fault containment forbids handler retirement",
                    "fault containment forbids post-fault retirement",
                    "fault containment forbids persistent writeback retries",
                    "fault containment forbids any fabric DDR admission",
                ) if "FAIL: " + assertion in message), None)
                if not result["exit_code"] or result["timed_out"] or intended is None:
                    raise ValueError("DRAIN classifier mutant lacks intended semantic rejection")
                receipt["mutant_detected"] = True
                receipt["intended_assertion"] = intended
            else:
                measured = json.loads((folder/"metrics.json").read_text())
                epochs = measured["epochs"]
                if len(epochs) != 3 or epochs[0]["fault_responses"] != 1 or (
                        epochs[0]["settled_cycles"] != 4096 or
                        epochs[0]["fabric_reads"] or epochs[0]["fabric_writes"]):
                    raise ValueError("missing actual persistent fault/containment witness")
                if any(e["fabric_reads"] != 1 or e["fabric_writes"] != 1 or
                       e["fault_responses"] for e in epochs[1:]):
                    raise ValueError("missing actual reset recovery DMA comparisons")
                if any(e["equal_comparisons"] <= 0 or e["assertions"] <= 0 for e in epochs):
                    raise ValueError("empty architectural/endpoint comparison counts")
                receipt["runs"].append({"seed": seed, "scope": "full top", **measured})
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
    print(f"Full-top fault exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
