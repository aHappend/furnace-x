#!/usr/bin/env python3
"""DMA length limits, byte memory, AXI faults and reset-epoch comparisons."""

import argparse
import datetime
import re
import sys
from pathlib import Path
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--limit", type=int, choices=(1, 4096, 1048576),
                        help="bounded diagnostic row; default executes all boundaries")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"dma-boundary-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    names = ["rtl/furnace_dma512.sv", "tests/dma_boundary_contract.sv",
             "tests/dma_boundary_probe.py", "tests/boot_probe.py"]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/dma_boundary_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {name: digest(ROOT/name) for name in names},
        "commands": [], "runs": [], "start_utc": now(), "end_utc": None,
        "exit_code": None, "timeout_s": 2700,
        "scope": "Leaf public DMA MAX_DMA_BYTES minimum/default/maximum; not complete-top fault coverage",
    }
    if args.repair_of:
        original = project_path(args.repair_of)
        receipt["repair_of"] = str(args.repair_of)
        receipt["repair_receipt_sha256"] = digest(original)
    save(output, receipt)
    status = 1
    try:
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        limits = (args.limit,) if args.limit else (1, 4096, 1048576)
        for limit in limits:
            directory = output / f"limit{limit}-{uuid.uuid4().hex[:8]}"
            directory.mkdir()
            rtl = ["rtl/furnace_dma512.sv", "tests/dma_boundary_contract.sv"]
            run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                 "--top-module", "dma_boundary_contract",
                 "--Mdir", directory.relative_to(ROOT)/"obj", f"-GLIMIT={limit}",
                 *rtl], output, f"limit{limit}-compile", receipt)
            if limit == 1:
                run(["iverilog", "-g2012", "-Wall", "-s", "dma_boundary_contract",
                     "-o", directory.relative_to(ROOT)/"dma.vvp",
                     "-Pdma_boundary_contract.LIMIT=1", *rtl],
                    output, "icarus-compile", receipt)
            for simulator, seed in (*((("icarus", 17),) if limit == 1 else ()),
                                    *(("verilator", s) for s in (17, 89, 211))):
                argv = (["vvp", directory.relative_to(ROOT)/"dma.vvp"] if simulator == "icarus"
                        else [directory.relative_to(ROOT)/"obj/Vdma_boundary_contract"])
                stem = f"limit{limit}-{simulator}-{seed}"
                run([*argv, f"+seed={seed}"], output, stem, receipt)
                text = (output/f"{stem}.stdout.txt").read_text()
                matches = re.findall(r"^DMA_BOUNDARY (.+)$", text, re.MULTILINE)
                if len(matches) != 1:
                    raise ValueError(f"{stem}: missing unique scored DMA summary")
                counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", matches[0])}
                if counts["limit"] != limit or counts["seed"] != seed or counts["failures"] or (
                        counts["resets"] != 6 or counts["canceled"] != 6 or
                        counts["accepted"] != counts["retired"]+counts["canceled"] or
                        counts["successes"] < 9 or counts["errors"] < (12 if limit>=65 else 4) or
                        counts["comparisons"] <= 0 or counts["stalls"] <= 0 or
                        (limit>=4096 and counts["splits"] <= 0)):
                    raise ValueError(f"{stem}: measured coverage/conservation failure")
                receipt["runs"].append({"scope": "leaf", "simulator": simulator, **counts})
                save(output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed during DMA experiment: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for directory in output.glob("limit*-*/obj"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["end_utc"] = now()
        receipt["exit_code"] = status
        save(output, receipt)
    print(f"DMA boundary receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
