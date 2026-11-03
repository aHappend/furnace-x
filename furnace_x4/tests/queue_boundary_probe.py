#!/usr/bin/env python3
"""Public queue/semaphore boundary comparisons at singleton, odd and maximum depths."""

import argparse
import datetime
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"queue-boundary-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = [f"rtl/{name}.sv" for name in (
        "furnace_mailbox_fifo", "furnace_fusion_buffer", "furnace_command_ring", "furnace_hw_semaphores",
    )]
    names = rtl + ["tests/queue_boundary_contract.sv", "tests/queue_boundary_probe.py", "tests/boot_probe.py"]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/queue_boundary_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT/name) for name in names}, "commands": [], "runs": [],
        "start_utc": now(), "end_utc": None, "exit_code": None, "timeout_s": 2700,
        "scope": "Leaf FIFO/fusion/ring depth 1/3/16 and all semaphore/overflow/reset priorities",
    }
    save(output, receipt)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        for depth in (1, 3, 16):
            directory = output / f"depth{depth}-{uuid.uuid4().hex[:8]}"
            directory.mkdir()
            run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                 "--top-module", "queue_boundary_contract", "--Mdir",
                 directory.relative_to(ROOT)/"obj", f"-GDEPTH={depth}",
                 *rtl, "tests/queue_boundary_contract.sv"], output, f"depth{depth}-compile", receipt)
            if depth == 1:
                run(["iverilog", "-g2012", "-Wall", "-s", "queue_boundary_contract", "-o",
                     directory.relative_to(ROOT)/"queue.vvp", f"-Pqueue_boundary_contract.DEPTH={depth}",
                     *rtl, "tests/queue_boundary_contract.sv"], output, "icarus-compile", receipt)
            for simulator, seed in (*((("icarus", 17),) if depth == 1 else ()),
                                    *(("verilator", s) for s in (17, 89, 211))):
                argv = (["vvp", directory.relative_to(ROOT)/"queue.vvp"] if simulator == "icarus" else
                        [directory.relative_to(ROOT)/"obj/Vqueue_boundary_contract"])
                stem = f"depth{depth}-{simulator}-{seed}"
                run([*argv, f"+seed={seed}"], output, stem, receipt)
                text = (output/f"{stem}.stdout.txt").read_text()
                matches = re.findall(r"^QUEUE_BOUNDARY (.+)$", text, re.MULTILINE)
                if len(matches) != 1:
                    raise ValueError(f"{stem}: absent unique measured summary")
                counts = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", matches[0])}
                if counts["depth"] != depth or counts["failures"] or counts["sem_positions"] != 16 or (
                        counts["overflow"] != 1 or any(counts[name] <= 0 for name in (
                            "comparisons", "simultaneous", "full", "stalls", "pairs", "fifo_puts", "fifo_takes"))):
                    raise ValueError(f"{stem}: measured queue coverage/assertion failure")
                conservation = re.findall(r"^QUEUE_CONSERVATION (.+)$", text, re.MULTILINE)
                if len(conservation) != 1:
                    raise ValueError(f"{stem}: missing explicit reset cancellation accounting")
                canceled = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", conservation[0])}
                if counts["fifo_puts"] != counts["fifo_takes"]+canceled["fifo_canceled"] or (
                        canceled["vision_puts"] != counts["pairs"]+canceled["vision_canceled"] or
                        canceled["audio_puts"] != counts["pairs"]+canceled["audio_canceled"] or
                        counts["pairs"] != canceled["fusion_retired"]+canceled["fusion_canceled"]):
                    raise ValueError(f"{stem}: independent conservation/cancellation mismatch")
                receipt["runs"].append({"scope": "leaf", "seed": seed, "simulator": simulator,
                                        **counts, **canceled})
                save(output, receipt)
            for path in (directory/"obj").iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        if len(receipt["runs"]) != 10:
            raise ValueError("queue boundary configuration/seed matrix incomplete")
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed during queue boundary comparisons: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for directory in output.glob("depth*-*/obj"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Queue boundary receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
