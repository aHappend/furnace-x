#!/usr/bin/env python3
"""Quantify a retained Linux loop from retired registers and the exact built ELF."""

import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-loop-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_loop_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT / name) for name in (
            "tests/boot_loop_probe.py", "tests/boot_probe.py",
        )},
        "start_utc": now(), "end_utc": None, "exit_code": None, "timeout_s": 600,
        "commands": [], "retained_inputs": {},
        "scope": "ELF/register-derived initialization progress and budget estimate, not complete Linux acceptance",
    }
    save(output, receipt)
    status = 1
    try:
        boot_path = project_path(args.boot_receipt)
        boot = json.loads(boot_path.read_text())
        build_path = project_path(Path(boot["software_build_receipt"]))
        if digest(build_path) != boot["software_build_receipt_sha256"]:
            raise ValueError("software build receipt changed")
        components_path = build_path.parent / "system/boot/boot-components.json"
        components = json.loads(components_path.read_text())
        elf = project_path(Path(components["kernel_elf"]["path"]))
        if digest(elf) != components["kernel_elf"]["sha256"]:
            raise ValueError("built kernel ELF changed")
        summary_path = boot_path.parent / "simulation-summary.txt"
        measured_path = boot_path.parent / "execution-measurements.json"
        measured = json.loads(measured_path.read_text())
        for path in (boot_path, build_path, components_path, elf, summary_path, measured_path):
            receipt["retained_inputs"][str(path.relative_to(ROOT))] = digest(path)
        for tool in ("riscv64-linux-gnu-nm", "riscv64-linux-gnu-objdump", "python3"):
            run([tool, "--version"], output, f"{tool}-version", receipt)
        run(["riscv64-linux-gnu-nm", "-n", "--defined-only", elf.relative_to(ROOT)],
            output, "kernel-symbols", receipt)
        symbols = {}
        for line in (output / "kernel-symbols.stdout.txt").read_text().splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]+) \w (.+)", line)
            if match:
                symbols[match[2]] = int(match[1], 16)
        start = symbols["memset"]
        run(["riscv64-linux-gnu-objdump", "-d", "--no-show-raw-insn",
             f"--start-address={start}", f"--stop-address={start+320}", elf.relative_to(ROOT)],
            output, "memset-disassembly", receipt)
        disassembly = (output / "memset-disassembly.stdout.txt").read_text()
        if not re.search(r"addi\s+t0,t0,256", disassembly) or not re.search(
                r"bltu\s+t0,a3,", disassembly):
            raise ValueError("built kernel does not contain the observed 256-byte memset loop")
        windows = []
        cycle = None
        pending = None
        for line in summary_path.read_text().splitlines():
            match = re.search(r"WINDOW end_cycle=(\d+)|^cycles=(\d+)", line)
            if match:
                cycle = int(match[1] or match[2])
            match = re.match(r"EXECUTION retired=(\d+) last_pc=(0x[0-9a-f]+)", line)
            if match:
                pending = {"cycle": cycle, "retired": int(match[1]), "pc": int(match[2], 16)}
            if line.startswith("retirement-derived registers t0/t1/t2/a0/a1/a2/a3="):
                if pending is None:
                    raise ValueError("register observation without retirement record")
                registers = [int(value, 16) for value in line.split("=")[1].split("/")]
                pending.update(t0=registers[0], a0=registers[3], a1=registers[4],
                               a2=registers[5], a3=registers[6])
                if start <= pending["pc"] < start+320:
                    windows.append(pending)
                pending = None
        if len(windows) < 2:
            raise ValueError("need two independently observed windows inside the same loop")
        before, after = windows[-2:]
        if any(before[name] != after[name] for name in ("a0", "a1", "a2", "a3")) or (
                after["a1"] != 0 or after["a0"]+after["a2"] != after["a3"]):
            raise ValueError("observed memset invocation or bounds changed")
        if after["t0"] <= before["t0"] or after["cycle"] <= before["cycle"] or (
                after["retired"] <= before["retired"] or after["t0"] >= after["a3"]):
            raise ValueError("loop did not demonstrate monotonic non-complete progress")
        if any(measured["retirement_registers"][index] != after[name] for index, name in (
                (5, "t0"), (10, "a0"), (11, "a1"), (12, "a2"), (13, "a3"))):
            raise ValueError("machine-readable final registers differ from retained observations")
        simulation = next(r for r in boot["commands"] if r["stdout"] == "simulation.stdout.txt")
        if simulation["timed_out"] or simulation["exit_code"] != 1:
            raise ValueError("need settled incomplete diagnostic, not timeout or passing boot")
        advance = after["t0"] - before["t0"]
        remaining = after["a3"] - after["t0"]
        cycles_per_byte = (after["cycle"]-before["cycle"]) / advance
        estimated_cycles = after["cycle"] + remaining*cycles_per_byte
        seconds_per_cycle = measured["profile"]["elapsed_ns"] / 1e9 / measured["cycles"]
        relocation = symbols["_start"] - components["kernel"]["address"]
        result = {
            "seed": boot["seed"], "memset_symbol": hex(start), "observed_windows": windows,
            "installed_ram_bytes": 0x08000000,
            "invocation_bytes": after["a2"], "advanced_bytes_in_last_window": advance,
            "remaining_bytes_conservative_at_observed_block": remaining,
            "cycles_per_initialized_byte_last_window": cycles_per_byte,
            "observed_physical_current_block": hex(after["t0"]-relocation),
            "observed_physical_limit": hex(after["a3"]-relocation),
            "estimated_cycles_from_reset_to_this_memset_end": estimated_cycles,
            "estimated_seconds_from_reset_to_this_memset_end": estimated_cycles*seconds_per_cycle,
            "individual_budget_s": 600,
            "complete_boot_budget_selected": False,
            "limitations": "Extrapolates one continuing invocation/window on a shared host; later initialization and userland work are unmeasured. Does not authorize larger deadlines, smaller RAM or skipped initialization.",
        }
        (output / "loop-analysis.json").write_text(json.dumps(result, indent=2) + "\n")
        receipt["analysis"] = result
        status = 0
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Boot loop receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
