#!/usr/bin/env python3
"""One bounded equal-work LTO comparison; never a complete Linux acceptance run."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from verify import sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--repair-of", type=Path, required=True)
    parser.add_argument("--cost-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-lto-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_lto_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "commands": [], "children": [],
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "seed": 17, "cycles_limit": 20000000,
        "hypothesis": "LTO reduces cross-translation-unit generated evaluation overhead.",
        "scope": "Equal-work diagnostic only; partial boots are not acceptance.",
    }
    save(output, receipt)
    print(f"LTO experiment receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        for key, path in (("repair_of", args.repair_of), ("cost_receipt", args.cost_receipt),
                          ("software_build_receipt", args.build_receipt)):
            resolved = project_path(path)
            receipt[key] = str(path)
            receipt[key + "_sha256"] = digest(resolved)
        run(["python3", "--version"], output, "python-version", receipt)
        receipt["tool_versions"] = {
            "python3": (output / "python-version.stdout.txt").read_text(),
        }
        before = None
        for profile in ("o3-split", "o3-lto"):
            child_root = output / f"{profile}-{uuid.uuid4().hex[:8]}"
            child_root.mkdir()
            result = run([
                "python3", "tests/boot_probe.py", "--output-root",
                child_root.relative_to(ROOT), "--build-receipt", args.build_receipt,
                "--seed", "17", "--cycles", str(receipt["cycles_limit"]),
                "--compile-profile", profile, "--jobs", "2",
                "--repair-of", before if before else args.repair_of,
            ], output, profile, receipt, timeout_s=1200, check=False)
            found = list(child_root.glob("boot-*/receipt.json"))
            if len(found) != 1:
                raise ValueError(f"{profile}: missing unique boot receipt")
            child_path = found[0].relative_to(ROOT)
            child = json.loads(found[0].read_text())
            receipt["children"].append({
                "receipt": str(child_path), "sha256": digest(found[0]),
            })
            save(output, receipt)
            if result["exit_code"] != 1 or child["exit_code"] != 1:
                raise ValueError(f"{profile}: expected bounded incomplete boot, not tool failure")
            if before is None:
                before = child_path
            else:
                after = child_path
        comparison_root = output / f"comparison-{uuid.uuid4().hex[:8]}"
        comparison_root.mkdir()
        run([
            "python3", "tests/boot_performance_probe.py", "--before", before,
            "--after", after, "--comparison-mode", "compiler-profile",
            "--cost-receipt", args.cost_receipt,
            "--output-root", comparison_root.relative_to(ROOT),
        ], output, "comparison", receipt)
        found = list(comparison_root.glob("boot-performance-*/receipt.json"))
        if len(found) != 1:
            raise ValueError("missing unique comparison receipt")
        comparison = json.loads(found[0].read_text())
        if comparison["exit_code"] != 0:
            raise ValueError("comparison did not pass")
        receipt["children"].append({
            "receipt": str(found[0].relative_to(ROOT)), "sha256": digest(found[0]),
        })
        receipt["comparison"] = comparison["comparison"]
        receipt["execution_replanning"] = comparison["execution_replanning"]
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError(f"source changed during comparison: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    return status


if __name__ == "__main__":
    sys.exit(main())
