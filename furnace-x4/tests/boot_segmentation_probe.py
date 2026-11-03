#!/usr/bin/env python3
"""One repair-linked validation of the admitted segmented Linux orchestration."""

import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from verify import SEEDS, linux, sources, coverage_requirements, write_coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-of", type=Path, required=True)
    parser.add_argument("--deadline-origin", type=Path,
                        help="Retain the original diagnostic deadline when repairing an entry failure")
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    deadline = min(float(os.environ["FURNACE_VERIFY_DEADLINE"]), time.monotonic() + 2700)
    origin = None
    if args.deadline_origin:
        origin_path = project_path(args.deadline_origin)
        origin = json.loads(origin_path.read_text())
        if origin.get("deadline_origin"):
            parser.error("deadline origin must be the first diagnostic, not a later repair")
        # Older receipts predate explicit epoch accounting. Subtract a second
        # conservatively rather than recover any elapsed setup time.
        original_end = origin.get("deadline_unix", (
            datetime.datetime.fromisoformat(origin["start_utc"]).timestamp()
            + origin["initial_remaining_s"] - 1))
        deadline = min(deadline, time.monotonic() + original_end - time.time())
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(deadline)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-segmentation-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_segmentation_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "initial_remaining_s": deadline - time.monotonic(),
        "deadline_unix": time.time() + deadline - time.monotonic(),
        "timed_out": False, "commands": [], "seeds": SEEDS,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "scope": "Advisory recovery validation; not an admitted mandatory check result.",
    }
    save(output, receipt)
    write_coverage(output, coverage_requirements("linux", SEEDS), {})
    print(f"Segmentation preparation receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        if origin is not None:
            receipt["deadline_origin"] = str(args.deadline_origin)
            receipt["deadline_origin_sha256"] = digest(origin_path)
            receipt["prior_commands"] = origin["commands"]
            save(output, receipt)
        if time.monotonic() >= deadline:
            raise RuntimeError("original diagnostic deadline already exhausted")
        original = project_path(args.repair_of)
        json.loads(original.read_text())
        receipt["repair_of"] = str(args.repair_of)
        receipt["repair_receipt_sha256"] = digest(original)
        save(output, receipt)
        run(["python3", "-B", "tests/boot_segmentation_test.py"],
            output, "orchestration-sensitivity", receipt)
        linux(output, receipt, SEEDS)
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"source changed during diagnostic: {name}")
        if time.monotonic() >= deadline:
            raise RuntimeError("2700-second aggregate execution deadline exhausted")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        receipt["remaining_s"] = deadline - time.monotonic()
        save(output, receipt)
    print(f"Segmentation exit={status}; receipt={output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
