#!/usr/bin/env python3
"""Bounded boot-oracle unit checks, separate from actual RTL/OS acceptance."""

import argparse
import datetime
from pathlib import Path
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
    output = project_path(args.output_root) / f"boot-model-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / "tests" / name for name in (
        "boot_model_probe.py", "boot_model_contract.cpp", "boot_execution_model.h",
        "boot_scoring_contract.py", "boot_scoring.py", "boot_probe.py", "workload_model.py",
    )]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_model_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None, "commands": [],
        "timeout_s": 600, "scope": "Synthetic independent-oracle unit/sensitivity checks only; no RTL/Linux coverage",
    }
    save(output, receipt)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        run(["g++", "--version"], output, "g++-version", receipt)
        run(["python3", "--version"], output, "python-version", receipt)
        # Preserve an exact-launch reproduction of the failed pre-bootstrap import.
        before = output / "pre-bootstrap.py"
        before.write_text("from boot_probe import ROOT\n")
        failed = run(["python3", "-P", before.relative_to(ROOT)], output,
                     "pre-bootstrap-rejection", receipt, check=False)
        if failed["exit_code"] != 1 or "ModuleNotFoundError: No module named 'boot_probe'" not in (
                output / failed["stderr"]).read_text():
            raise RuntimeError("pre-bootstrap import failure was not reproduced")
        receipt["bootstrap_repair"] = {
            "original_entrypoint_failure": "initial tool execution had no receipt; exact import rejection reproduced here",
            "reproduced_source_sha256": digest(before),
            "repair": "Explicit project-local script directory import, as in exp-6a4baac55d8459da132c8b6a",
        }
        run(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra",
             "tests/boot_model_contract.cpp", "-o", output.relative_to(ROOT) / "contract"],
            output, "compile", receipt)
        run([output.relative_to(ROOT) / "contract"], output, "model-contract", receipt)
        run(["python3", "tests/boot_scoring_contract.py"], output, "scoring-contract", receipt)
        for source in sources:
            if digest(source) != receipt["source_sha256"][str(source.relative_to(ROOT))]:
                raise RuntimeError("model source changed during execution")
        status = 0
    except (OSError, RuntimeError) as error:
        receipt["error"] = str(error)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Boot model receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
