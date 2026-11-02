#!/usr/bin/env python3
"""Default integrated-top synthesis diagnostic, retaining inferred memories."""

import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--frontend", choices=("yosys", "icarus"), default="yosys")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"synthesis-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = sorted((ROOT / "rtl").glob("*.sv"))
    sources = rtl + [ROOT / name for name in (
        "tests/synthesis_probe.py", "tests/boot_probe.py",
        "design/SPEC.md", "design/ARCHITECTURE.md",
    )]
    read_sources = (
        str(relative / "lowered.v") if args.frontend == "icarus" else
        " ".join(str(p.relative_to(ROOT)) for p in rtl)
    )
    script = (
        "read_verilog -sv " + read_sources + "\n"
        "hierarchy -check -top furnace_x4_top\n"
        "proc\nopt_expr\nopt_clean\ncheck -noinit\n"
        "memory -nomap\nopt_clean\n"
        "synth -top furnace_x4_top -nomem -noabc\n"
        "check -assert\n"
        "select -assert-none t:$dlatch t:$adlatch t:$dlatchsr t:$div t:$mod\n"
        f"write_json {relative}/netlist.json\n"
        "stat\n"
    )
    (output / "synthesis.ys").write_text(script)
    receipt = {
        "schema": 1, "kind": "verifier-default-top-synthesis-preparation",
        "argv": ["python3", "tests/synthesis_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "script_sha256": digest(output / "synthesis.ys"),
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": None, "timed_out": False, "commands": [], "tool_versions": {},
        "frontend": args.frontend,
        "scope": "Default integrated hierarchy, generic synthesis with inferred memories; no FPGA timing or hardware claim.",
    }
    if args.repair_of:
        receipt["repair_of"] = str(args.repair_of)
        receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
    save(output, receipt)
    print(f"Synthesis diagnostic: {relative}/receipt.json", flush=True)
    status = 1
    try:
        result = subprocess.run(
            ["yosys", "-V"], cwd=ROOT, capture_output=True, text=True, check=False,
        )
        receipt["tool_versions"]["yosys"] = {
            "argv": ["yosys", "-V"], "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
        }
        if result.returncode:
            raise RuntimeError("Yosys version query failed")
        if args.frontend == "icarus":
            result = subprocess.run(
                ["iverilog", "-V"], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            receipt["tool_versions"]["iverilog"] = {
                "argv": ["iverilog", "-V"], "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            }
            if result.returncode:
                raise RuntimeError("Icarus version query failed")
            run(["iverilog", "-g2012", "-Wall", "-t", "vlog95",
                 "-pallowsigned=1", "-s", "furnace_x4_top",
                 "-o", relative / "lowered.v",
                 *[p.relative_to(ROOT) for p in rtl]],
                output, "lowering", receipt)
            receipt["lowered_sha256"] = digest(output / "lowered.v")
        run(["yosys", "-Q", "-T", "-s", relative / "synthesis.ys"],
            output, "synthesis", receipt)
        netlist = json.loads((output / "netlist.json").read_text())
        modules = netlist["modules"]
        counts = {}
        memories = []
        instances = []

        def walk(name, prefix):
            module = modules[name]
            if module.get("attributes", {}).get("blackbox"):
                raise ValueError(f"unresolved black box: {prefix}")
            for instance, cell in module.get("cells", {}).items():
                kind = cell["type"]
                path = prefix + "." + instance
                counts[kind] = counts.get(kind, 0) + 1
                if kind in modules:
                    instances.append({"path": path, "module": kind})
                    walk(kind, path)
                elif kind.startswith("$mem"):
                    memories.append({"path": path, "type": kind})

        walk("furnace_x4_top", "furnace_x4_top")
        for required in ("application_processor", "heterogeneous_fabric"):
            if not any(row["path"] == f"furnace_x4_top.{required}" for row in instances):
                raise ValueError(f"missing integrated instance: {required}")
        if not any("dff" in kind.lower() for kind in counts):
            raise ValueError("integrated synthesis contains no sequential cells")
        if not memories:
            raise ValueError("integrated synthesis contains no inferred memory cells")
        (output / "structure.json").write_text(json.dumps({
            "cell_counts": counts, "instances": instances, "memories": memories,
        }, indent=2) + "\n")
        receipt["structure_sha256"] = digest(output / "structure.json")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["end_utc"] = now()
        receipt["exit_code"] = status
        save(output, receipt)
    print(f"Synthesis diagnostic exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
