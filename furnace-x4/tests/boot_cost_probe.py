#!/usr/bin/env python3
"""Audit actual checkpoint-lineage compute; never count other equivalence trajectories."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from boot_checkpoint_probe import identity
from boot_scoring import score_boot


def analyze(receipt_path):
    retained = {}

    def load(path, expected=None):
        actual = digest(path)
        if expected is not None and actual != expected:
            raise ValueError("predecessor receipt changed")
        retained[str(path.relative_to(ROOT))] = actual
        value = json.loads(path.read_text())
        if value["exit_code"] != 0:
            raise ValueError("lineage contains failed diagnostic")
        return value

    current_path = project_path(receipt_path)
    current = load(current_path)
    latest = current
    row = current["segments"][-1]
    endpoint = row["metrics"]
    visited, rows, missing = set(), [], []
    while True:
        if row["state"] in visited:
            raise ValueError("checkpoint lineage cycle")
        visited.add(row["state"])
        state = project_path(Path(row["state"]))
        state_missing = []
        for name in ("rtl-context.bin", "host.bin", "ram.bin"):
            path = state / name
            try:
                path.stat()
            except FileNotFoundError:
                state_missing.append(str(path.relative_to(ROOT)))
        missing.extend(state_missing)
        if not state_missing and identity(state) != row["identity"]:
            raise ValueError("checkpoint content changed")
        metrics_path = project_path(Path(row["metrics_path"]))
        try:
            metrics_path.stat()
        except FileNotFoundError:
            missing.append(str(metrics_path.relative_to(ROOT)))
            metrics = row["metrics"]
            metrics_retained = False
        else:
            if digest(metrics_path) != row["metrics_sha256"]:
                raise ValueError("segment metrics changed")
            metrics = json.loads(metrics_path.read_text())
            if metrics != row["metrics"]:
                raise ValueError("embedded and retained metrics disagree")
            metrics_retained = True
        if metrics["end_cycle"] <= metrics["start_cycle"] or row["duration_s"] <= 0:
            raise ValueError("invalid measured segment extent/cost")
        rows.append({
            "receipt": str(current_path.relative_to(ROOT)), "state": row["state"],
            "start_cycle": metrics["start_cycle"], "end_cycle": metrics["end_cycle"],
            "duration_s": row["duration_s"], "retired": metrics["retired"],
            "save_s": metrics["save_ns"] / 1e9, "load_s": metrics["load_ns"] / 1e9,
            "checkpoint_currently_restorable": not bool(state_missing),
            "metrics_artifact_retained": metrics_retained,
        })
        if metrics["start_cycle"] == 0:
            break
        restore = row.get("restored_from")
        if restore is None:
            links = [link for link in current["checkpoint_links"]
                     if link["consumer"] == str(metrics_path.parent.relative_to(ROOT))]
            if len(links) != 1:
                raise ValueError("missing exact historical restore link")
            restore = links[0]["restore"]
        matches = [s for s in current["segments"] if s["state"] == restore]
        if not matches:
            current_path = project_path(Path(current["predecessor"]))
            current = load(current_path, current["predecessor_sha256"])
            matches = [s for s in current["segments"] if s["state"] == restore]
        if len(matches) != 1 or matches[0]["metrics"]["end_cycle"] != metrics["start_cycle"]:
            raise ValueError("noncontiguous checkpoint lineage")
        row = matches[0]
    rows.reverse()
    if any(a["end_cycle"] != b["start_cycle"] for a, b in zip(rows, rows[1:])):
        raise ValueError("lineage contains gaps or overlapping compute")
    if endpoint["complete_boot"]:
        folder = project_path(Path(latest["segments"][-1]["metrics_path"])).parent
        score_boot(json.loads((folder / "execution-measurements.json").read_text()),
                   (folder / "uart.txt").read_text())
    build_path = project_path(Path(latest["software_build_receipt"]))
    build = load(build_path, latest["software_build_receipt_sha256"])
    build_s = sum(c["duration_s"] for c in build["commands"])
    prefix_s = sum(s["duration_s"] for s in rows)
    return {
        "scope": "Measured seed-17 execution prefix only; three-seed cost is a projection, not acceptance.",
        "seed": latest["seed"], "ram": latest["ram"], "segments": rows,
        "retained_receipt_sha256": retained,
        "missing_historical_artifacts": missing,
        "historical_cost_basis": "Hash-linked retained receipts. Missing historical checkpoints/"
                                 "metrics are explicitly listed, not certified restorable.",
        "cycles_from_reset": endpoint["end_cycle"], "retired": endpoint["retired"],
        "output_bytes_compared": endpoint["output_bytes_compared"],
        "complete_boot": bool(endpoint["complete_boot"]),
        "measured_prefix_simulation_s_including_serialization": prefix_s,
        "measured_prefix_serialization_s": sum(r["save_s"] + r["load_s"] for r in rows),
        "software_build_command_s": build_s,
        "latest_fresh_compilation_s": latest["cost"]["compilation_s"],
        "three_seed_prefix_projection_s": prefix_s * 3,
        "complete_boot_cost_s": prefix_s if endpoint["complete_boot"] else None,
        "aggregate_check_budget_s": 2700,
        "largest_lineage_segment_command_s": max(r["duration_s"] for r in rows),
        "all_segment_commands_within_600_s": all(r["duration_s"] < 600 for r in rows),
        "prefix_alone_exceeds_check_budget": prefix_s > 2700,
        "limitation": "No seed-89/211 boot measured. Additional boot and workload cost remains "
                      "unknown when incomplete. Segmentation does not reduce aggregate compute.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repair-of", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(analyze(args.continuation_receipt), indent=2))
        return 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-cost-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_cost_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 600, "timed_out": False, "commands": [],
        "source_sha256": {f"tests/{name}": digest(ROOT / "tests" / name) for name in (
            "boot_cost_probe.py", "boot_probe.py", "boot_checkpoint_probe.py",
            "boot_scoring.py", "workload_model.py", "verify.py")},
        "scope": "Retained measurement audit only; no simulation rerun or engineering acceptance.",
    }
    save(output, receipt)
    status = 1
    try:
        if args.repair_of:
            receipt.update(repair_of=str(args.repair_of),
                           repair_receipt_sha256=digest(project_path(args.repair_of)))
        run(["python3", "--version"], output, "python-version", receipt)
        result = run(["python3", "tests/boot_cost_probe.py", "--worker",
                      "--continuation-receipt", args.continuation_receipt],
                     output, "cost-analysis", receipt)
        analysis = json.loads((output / result["stdout"]).read_text())
        (output / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")
        receipt["analysis"] = analysis
        for name, value in receipt["source_sha256"].items():
            if digest(ROOT / name) != value:
                raise ValueError(f"source changed: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["end_utc"] = now()
        receipt["exit_code"] = status
        save(output, receipt)
    print(f"Boot cost receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
