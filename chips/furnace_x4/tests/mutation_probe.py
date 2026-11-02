#!/usr/bin/env python3
"""Semantic adapter mutants in disposable copies; incomplete full-system matrix."""

import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from integrated_probe import INTEGRATED_MUTATIONS


MUTATIONS = (
    ("mmio_decode", "mmio", "write_offset[15:0]",
     "(write_offset[15:0] ^ 16'h0004)",
     "write offset, upper subword lane, strobes and PROT"),
    ("mmio_strobe", "mmio",
     "(awaddr_q[2] ? wstrb_q[7:4] : wstrb_q[3:0])",
     "(awaddr_q[2] ? wstrb_q[3:0] : wstrb_q[7:4])",
     "write offset, upper subword lane, strobes and PROT"),
    ("cpu_write_data", "cpu", "{448'b0,wdata_q}",
     "{448'b0,(wdata_q ^ 64'h1)}", "full target payload and lane stable at E1/stalls"),
)
REQUIRED = (
    "mmio_decode", "mmio_strobe", "dma_data_order", "cache_invalidation",
    "reservation_invalidation", "plic_disconnect", "authentication_bypass",
    "tensor_rounding", "tensor_weight_sign", "vision_numerical", "fft_numerical",
    "mailbox_semaphore_association", "authenticated_weight_commit",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--focus", choices=("adapters", "integrated", "tensor"),
                        help="bounded diagnostic subset; default enforces the full mandatory matrix")
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--only", help="comma-separated integrated diagnostic mutants")
    args = parser.parse_args()
    selected = dict(INTEGRATED_MUTATIONS)
    if args.only:
        names = args.only.split(",")
        if args.focus != "integrated" or len(set(names)) != len(names) or any(
                name not in INTEGRATED_MUTATIONS for name in names):
            parser.error("--only requires distinct known mutants and --focus integrated")
        selected = {name: INTEGRATED_MUTATIONS[name] for name in names}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"mutations-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    sources = sorted(
        p for directory in ("tests", "rtl", "sw/taskgraph", "design")
        for p in (ROOT / directory).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    receipt = {
        "schema": 1, "argv": ["python3", "tests/mutation_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "timed_out": False, "commands": [], "mutants": [],
        "focus": args.focus, "selected_integrated_mutants": list(selected), "children": [],
    }
    save(output, receipt)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        run(["verilator", "--version"], output, "verilator-version", receipt)
        measured = {}
        for name, kind, before, after, assertion in (
            MUTATIONS if args.focus in (None, "adapters") else ()
        ):
            top = "mmio_contract" if kind == "mmio" else "cpu_adapter_contract"
            module = "furnace_x4_mmio_bridge" if kind == "mmio" else "furnace_x4_cpu_axi512_bridge"
            original = (ROOT / "rtl" / f"{module}.sv").read_text()
            if original.count(before) != 1:
                raise ValueError(f"{name}: mutation site must occur exactly once")
            row = {"name": name, "intended_assertion": assertion, "detected": False}
            receipt["mutants"].append(row)
            for variant in ("baseline", "mutant"):
                directory = output / f"{name}-{variant}"
                directory.mkdir()
                copied = directory / f"{module}.sv"
                copied.write_text(original if variant == "baseline" else
                                  original.replace(before, after, 1))
                row[f"{variant}_sha256"] = digest(copied)
                run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                     "--top-module", top, "--Mdir", directory.relative_to(ROOT) / "obj",
                     copied.relative_to(ROOT), f"tests/{top}.sv"],
                    output, f"{name}-{variant}-compile", receipt)
                record = run([directory.relative_to(ROOT) / f"obj/V{top}"],
                             output, f"{name}-{variant}-simulation", receipt,
                             check=variant == "baseline")
                text = (output / record["stdout"]).read_text()
                if variant == "mutant":
                    if record["exit_code"] == 0 or f"MISMATCH {assertion}" not in text:
                        raise ValueError(
                            f"{name}: no intended semantic rejection; tool failure "
                            "and watchdog expiry do not count as sensitivity"
                        )
                    row["detected"] = True
                    measured[name] = 1
                else:
                    if "failures=0" not in text:
                        raise ValueError(f"{name}: baseline comparison summary absent")
                for transient in (directory / "obj").iterdir():
                    if transient.suffix in (".o", ".a", ".gch"):
                        transient.unlink()
                save(output, receipt)
        if args.focus in (None, "integrated"):
            # One fresh, complete baseline proves that the same CPU-executed
            # assertions are reachable before any disposable mutation is scored.
            variants = [("baseline", None), *selected.items()]
            for name, mutation in variants:
                child_root = output / f"integrated-{name}-{uuid.uuid4().hex[:8]}"
                child_root.mkdir()
                argv = ["python3", "tests/integrated_probe.py", "--output-root",
                        child_root.relative_to(ROOT), "--seeds", "17", "--cycles", "10000000"]
                if mutation:
                    argv += ["--mutation", name]
                result = run(argv, output, f"integrated-{name}", receipt,
                             timeout_s=2700, check=False)
                found = list(child_root.glob("*/receipt.json"))
                if len(found) != 1:
                    raise ValueError(f"{name}: missing unique source-bound child receipt")
                path = found[0]
                child = json.loads(path.read_text())
                receipt["children"].append({
                    "receipt": str(path.relative_to(ROOT)), "sha256": digest(path),
                })
                for source, expected in child["source_sha256"].items():
                    if digest(project_path(Path(source))) != expected:
                        raise ValueError(f"{name}: source changed since child execution")
                if not mutation:
                    if result["exit_code"] or child["exit_code"]:
                        raise ValueError("integrated mutation baseline did not pass")
                    if not child["runs"] or not child["runs"][0]["observed"]["complete"]:
                        raise ValueError("integrated baseline omitted successful comparisons")
                    continue
                row = {"name": name, "intended_assertion": mutation["assertion"],
                       "receipt": str(path.relative_to(ROOT)), "detected": False}
                receipt["mutants"].append(row)
                simulation = next((r for r in child["commands"]
                                   if r["stdout"] == "simulation-17.stdout.txt"), None)
                if not simulation or simulation["timed_out"] or simulation["exit_code"] != 1:
                    raise ValueError(f"{name}: compile/tool/timeout failure is not sensitivity")
                message = (path.parent / simulation["stderr"]).read_text()
                if "public_message" in mutation and re.search(mutation["public_message"], message):
                    row.update(detected=True, observed_failure=message.strip())
                    measured[name] = 1
                    save(output, receipt)
                    continue
                if "message" in mutation:
                    if not re.search(mutation["message"], message):
                        raise ValueError(f"{name}: missing intended public-DDR rejection")
                    row.update(detected=True, observed_failure=message.strip())
                    measured[name] = 1
                    save(output, receipt)
                    continue
                matches = re.findall(
                    r"CPU assertion/trap: F ([0-9a-f]{16}) ([0-9a-f]{16}) ([0-9a-f]{16})",
                    message,
                )
                if len(matches) != 1:
                    raise ValueError(f"{name}: missing intended CPU numerical/protocol rejection")
                code, observed, expected = [int(v, 16) for v in matches[0]]
                if not (mutation["code_low"] <= code <= mutation["code_high"]) or observed == expected:
                    raise ValueError(f"{name}: rejection does not match intended semantic assertion")
                if name == "authentication_bypass" and (observed, expected) != (0, 4):
                    raise ValueError("authentication mutant did not reach actual corrupt-tag retirement")
                if name == "authenticated_weight_commit" and (observed, expected) != (0, 1):
                    raise ValueError("commit mutant did not reach actual successful tensor retirement")
                row.update(detected=True, code=code, observed=observed, expected=expected)
                measured[name] = 1
                save(output, receipt)
        if args.focus in (None, "tensor"):
            for variant in ("baseline", "mutant"):
                child_root = output / f"tensor-{variant}-{uuid.uuid4().hex[:8]}"
                child_root.mkdir()
                argv = ["python3", "tests/tensor_probe.py", "--output-root",
                        child_root.relative_to(ROOT)]
                if variant == "mutant":
                    argv += ["--mutation", "tensor_rounding"]
                result = run(argv, output, f"tensor-{variant}", receipt, timeout_s=2700,
                             check=False)
                found = list(child_root.glob("*/receipt.json"))
                if len(found) != 1:
                    raise ValueError("tensor mutation missing unique child receipt")
                path = found[0]
                child = json.loads(path.read_text())
                receipt["children"].append({
                    "receipt": str(path.relative_to(ROOT)), "sha256": digest(path),
                })
                if result["exit_code"] or child["exit_code"]:
                    raise ValueError("tensor baseline or semantic-sensitivity procedure failed")
                if variant == "mutant":
                    if not child["mutant_detected"]:
                        raise ValueError("tensor rounding mutant lacks semantic comparison rejection")
                    measured["tensor_rounding"] = 1
                    receipt["mutants"].append({
                        "name": "tensor_rounding", "scope": "leaf public tensor interface",
                        "intended_assertion": "independent balanced tensor numeric/protocol result",
                        "receipt": str(path.relative_to(ROOT)), "detected": True,
                    })
                elif len(child["runs"]) != 4:
                    raise ValueError("tensor baseline omitted dual-simulator/three-seed comparisons")
                save(output, receipt)
        coverage = [{"bin": name, "required": 1, "observed": measured.get(name, 0)}
                    for name in REQUIRED]
        (output / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        required = (tuple(selected) if args.focus == "integrated" else
                    tuple(row[0] for row in MUTATIONS) if args.focus == "adapters" else REQUIRED)
        if args.focus == "tensor":
            required = ("tensor_rounding",)
        if any(measured.get(name, 0) != 1 for name in required):
            raise ValueError("mandatory full-system semantic mutation comparisons incomplete; "
                             "see coverage.json (adapter mutants are separate leaf evidence)")
        for source, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(source))) != expected:
                raise ValueError(f"source changed during mutation execution: {source}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Mutation receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
