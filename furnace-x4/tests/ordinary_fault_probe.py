#!/usr/bin/env python3
"""Architectural ordinary DDR and unowned halt-clean errors; real cache recovery."""

import argparse
import datetime
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
    parser.add_argument("--simulator", choices=("both", "icarus", "verilator"), default="both")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"ordinary-fault-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = [p.relative_to(ROOT) for p in sorted((ROOT / "rtl").glob("hammer*.sv"))]
    names = [*rtl, *[Path("tests") / name for name in (
        "ordinary_fault_probe.py", "ordinary_fault_program.S", "ordinary_fault_contract.sv",
        "boot_probe.py")]]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/ordinary_fault_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "runs": [],
        "source_sha256": {str(p): digest(ROOT / p) for p in names},
        "scope": "HAMMER public CPU/cache/DDR/coherence pins; not full-top Linux acceptance.",
        "reset_scope": "Time-zero/both-edge gated parent controls; inherited raw host/debug "
                       "status after first reset edge. X4 public-pin startup remains separately checked.",
    }
    if args.repair_of:
        receipt.update(repair_of=str(args.repair_of),
                       repair_receipt_sha256=digest(project_path(args.repair_of)))
    save(output, receipt)
    print(f"Ordinary fault receipt: {relative}/receipt.json", flush=True)
    status = 1
    obj = relative / f"obj-{uuid.uuid4().hex[:8]}"
    try:
        for tool, option in (("python3", "--version"), ("iverilog", "-V"), ("vvp", "-V"),
                             ("verilator", "--version"), ("riscv64-unknown-elf-gcc", "--version"),
                             ("riscv64-unknown-elf-objcopy", "--version"),
                             ("riscv64-unknown-elf-nm", "--version")):
            run([tool, option], output, tool + "-version", receipt)
        fixtures = []
        for case in range(3):
            elf, binary, hexfile = [relative / f"program{case}.{suffix}"
                                    for suffix in ("elf", "bin", "hex")]
            run(["riscv64-unknown-elf-gcc", "-march=rv64ima_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--build-id=none", "-Wl,-Ttext=0",
                 f"-DCASE={case}", "tests/ordinary_fault_program.S", "-o", elf],
                output, f"program{case}-compile", receipt)
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, binary],
                output, f"program{case}-binary", receipt)
            run(["riscv64-unknown-elf-nm", elf], output, f"program{case}-symbols", receipt)
            data = (ROOT / binary).read_bytes()
            if not data or len(data) % 4 or len(data) > 512:
                raise ValueError("firmware must fit actual local IMEM")
            (ROOT / hexfile).write_text("".join(
                f"{int.from_bytes(data[i:i+4], 'little'):08x}\n" for i in range(0, len(data), 4)))
            symbols = dict((name, address) for address, name in re.findall(
                r"^([0-9a-f]+) T (\w+)$",
                (output / f"program{case}-symbols.stdout.txt").read_text(), re.MULTILINE))
            fixtures.append([f"+case={case}", f"+program={hexfile}", f"+words={len(data)//4}",
                             *[f"+{arg}={symbols[name]}" for arg, name in (
                                 ("probe", "probe"), ("idle", "idle"), ("handler", "trap_handler"),
                                 ("done", "done"), ("failed", "failed"))]])
            receipt.setdefault("firmware_sha256", {})[str(binary)] = digest(ROOT / binary)
        inputs = [*rtl, "tests/ordinary_fault_contract.sv"]
        if args.simulator != "verilator":
            run(["iverilog", "-g2012", "-Wall", "-s", "ordinary_fault_contract",
                 "-o", relative / "contract.vvp", *inputs], output, "icarus-compile", receipt)
        if args.simulator != "icarus":
            run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                 "--top-module", "ordinary_fault_contract", "--Mdir", obj, *inputs],
                output, "verilator-compile", receipt)
        for simulator, command in (
                ("icarus", ["vvp", relative / "contract.vvp"]),
                ("verilator", [obj / "Vordinary_fault_contract"])):
            if args.simulator not in ("both", simulator):
                continue
            for case, fixture in enumerate(fixtures):
                for response in (2, 3):
                    result = run([*command, *fixture, f"+response={response}"], output,
                                 f"{simulator}-case{case}-response{response}", receipt)
                    text = (output / result["stdout"]).read_text()
                    lines = re.findall(r"^ORDINARY_FAULT (.+)$", text, re.MULTILINE)
                    if len(lines) != 1:
                        raise ValueError("missing actual ordinary-error comparison summary")
                    counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", lines[0])}
                    required = {"case": case, "response": response, "traps": 1, "handler": 1,
                                "failed_reads": int(case == 0), "failed_writes": int(case != 0),
                                "dirty_compared": 0 if case == 0 else 5, "recovery": 1}
                    if any(counts[k] != v for k, v in required.items()) or any(
                            counts[k] <= 0 for k in ("comparisons", "retired", "loads", "stalls")):
                        raise ValueError(f"incomplete ordinary fault/recovery witness: {counts}")
                    receipt["runs"].append({"simulator": simulator, **counts})
                    save(output, receipt)
        for name, value in receipt["source_sha256"].items():
            if digest(ROOT / name) != value:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for path in (ROOT / obj).glob("*"):
            if path.suffix in (".o", ".a", ".gch"):
                path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Ordinary fault exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
