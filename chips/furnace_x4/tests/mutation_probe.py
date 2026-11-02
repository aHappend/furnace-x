#!/usr/bin/env python3
"""Semantic adapter mutants in disposable copies; incomplete full-system matrix."""

import argparse
import datetime
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


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
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"mutations-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    sources = [ROOT / "tests" / name for name in (
        "mutation_probe.py", "boot_probe.py", "mmio_contract.sv", "cpu_adapter_contract.sv",
    )] + [ROOT / "rtl" / name for name in (
        "furnace_x4_mmio_bridge.sv", "furnace_x4_cpu_axi512_bridge.sv",
    )]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/mutation_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "timed_out": False, "commands": [], "mutants": [],
    }
    save(output, receipt)
    status = 1
    try:
        run(["verilator", "--version"], output, "verilator-version", receipt)
        measured = {}
        for name, kind, before, after, assertion in MUTATIONS:
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
        coverage = [{"bin": name, "required": 1, "observed": measured.get(name, 0)}
                    for name in REQUIRED]
        (output / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        if any(row["observed"] != row["required"] for row in coverage):
            raise ValueError("mandatory full-system semantic mutation comparisons incomplete; "
                             "see coverage.json (adapter mutants are separate leaf evidence)")
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
