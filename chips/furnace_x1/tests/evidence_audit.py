#!/usr/bin/env python3
"""Inventory explicitly named historical evidence without repairing or recertifying it.

Run from the project root:
  python3 tests/evidence_audit.py --out evidence/audit \
      --historical evidence/older-run/receipt.json \
      --surviving evidence/later-run/receipt.json

The shared runtime must independently admit this command before execution as a
recovery check. A successful audit means a factual record was retained, not that
missing history was recovered or engineering acceptance was granted. No search
outside the project, record reconstruction, hardware access or source edit occurs.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify import ROOT, Run, relative_output, write_json
from scoreboard import require


LIMITATIONS = (
    "Absence at an explicitly inspected path does not prove irrecoverability.",
    "No loss mechanism is established; storage exhaustion and receipt-writing "
    "repairs cannot explain missing records without authentic diagnostics.",
    "Later successful results cannot reconstruct earlier receipts or raw logs.",
    "Availability and hashes do not authenticate origin, recertify recorded "
    "results, or establish timing or physical hardware coverage.",
    "Historical preservation remains unresolved wherever a record is absent; "
    "independent disposition is required, not an acceptance waiver.",
)


def observe(text):
    path = relative_output(text)
    row = {"path": str(path.relative_to(ROOT))}
    require(not any(part in (".vulcan", ".git", ".tooling", "VULCAN")
                    for part in path.relative_to(ROOT).parts),
            "runtime-owned paths cannot be historical audit inputs")
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        row["availability"] = "absent_at_inspection"
        return row
    row.update(availability="present", size_bytes=len(content),
               sha256=hashlib.sha256(content).hexdigest())
    return row


def audit(historical, surviving):
    rows = [dict(observe(name), category=category)
            for category, names in (("historical", historical), ("surviving", surviving))
            for name in names]
    return {
        "schema": 1,
        "purpose": "historical_evidence_availability_only",
        "records": rows,
        "unavailable_records": [r["path"] for r in rows
                                if r["availability"] == "absent_at_inspection"],
        "historical_preservation": (
            "unresolved" if any(r["category"] == "historical" and
                                r["availability"] != "present" for r in rows)
            else "availability_observed_not_authenticated"),
        "loss_mechanism": "unknown",
        "engineering_acceptance": "not_established_by_this_audit",
        "limitations": list(LIMITATIONS),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--historical", action="append", required=True)
    parser.add_argument("--surviving", action="append", required=True)
    args = parser.parse_args()
    run = Run(relative_output(args.out), "historical-evidence-audit", None)
    run.record["tool_versions"]["python3"] = sys.version
    try:
        result = audit(args.historical, args.surviving)
        write_json(run.path / "availability.json", result)
        run.record["results"]["availability"] = result
        run.record["acceptance_evidence"] = False
        run.save()
        run.finish("passed")
    except Exception as error:
        (run.path / "stderr.log").write_text(traceback.format_exc())
        run.finish("failed", error)
        print(f"audit failed: {run.path.relative_to(ROOT)}/receipt.json", file=sys.stderr)
        return 1
    print(json.dumps({"audit_record": str((run.path / "availability.json").relative_to(ROOT)),
                      "historical_preservation": result["historical_preservation"],
                      "engineering_acceptance": result["engineering_acceptance"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
