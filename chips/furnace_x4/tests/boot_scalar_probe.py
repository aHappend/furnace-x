#!/usr/bin/env python3
"""Receipt-bound inspection of the three profiled input-combinational schedules."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from verify import sources


FUNCTION = re.compile(
    r"VL_INLINE_OPT void (\w+___ico_sequent__TOP__[012])"
    r"\(Vfurnace_x4_top___024root\* vlSelf\) \{(.*?)\n\}", re.S)


def inspect(profile_path, output, receipt):
    profile = json.loads(profile_path.read_text())
    paths = [project_path(Path(row["receipt"])) for row in profile["children"]]
    children = [path for path in paths if
                json.loads(path.read_text()).get("compile_profile") == "schedule-profile"]
    if len(children) != 1:
        raise ValueError("expected one retained schedule-profile child")
    path = children[0]
    child = json.loads(path.read_text())
    executable = project_path(Path(child["executable"]))
    if digest(executable) != child["executable_sha256"]:
        raise ValueError("retained profiling executable identity mismatch")
    directory = executable.parent
    header = directory / "Vfurnace_x4_top___024root.h"
    receipt["inspected_sources"] = {str(header.relative_to(ROOT)): digest(header)}
    receipt["inspected_executable"] = {
        "path": str(executable.relative_to(ROOT)), "sha256": digest(executable)}
    run(["objdump", "--version"], output, "objdump-version", receipt)
    run(["nm", "--version"], output, "nm-version", receipt)
    run(["nm", "--defined-only", executable.relative_to(ROOT)], output, "symbols", receipt)
    symbols = (output / "symbols.stdout.txt").read_text().splitlines()
    rows = []
    for source in sorted(directory.glob("*DepSet*.cpp")):
        for match in FUNCTION.finditer(source.read_text()):
            code = match[2].split("// Body\n", 1)[1]
            fields = re.findall(r"vlSelf->(\w+)", code)
            calls = sorted(set(re.findall(r"\b(\w+)\s*\(", code)))
            name = match[1]
            found = [line.split()[-1] for line in symbols
                     if re.fullmatch(rf"_Z\d+{name}P\d+Vfurnace_x4_top___024root",
                                     line.split()[-1])]
            if len(found) != 1:
                raise ValueError(f"missing unique compiled function: {name}")
            stem = "ico-" + name.rsplit("__", 1)[1]
            run(["objdump", "-d", "--no-show-raw-insn", "--disassemble=" + found[0],
                 executable.relative_to(ROOT)], output, stem, receipt)
            assembly = (output / (stem + ".stdout.txt")).read_text()
            memory_operands = re.findall(r"(?m)^\s*[0-9a-f]+:\s+.*\([^)]*\).*", assembly)
            rows.append({
                "function": name, "source": str(source.relative_to(ROOT)),
                "body_bytes": len(code), "field_references": len(fields),
                "unique_fields": len(set(fields)), "calls_and_casts": calls,
                "assembly_memory_operand_instructions": len(memory_operands),
            })
            receipt["inspected_sources"][str(source.relative_to(ROOT))] = digest(source)
    if len(rows) != 3:
        raise ValueError("expected exactly three profiled ico functions")
    receipt["inspection"] = rows


def contract(output, receipt):
    from generated_scalar import transform
    header = r"""
struct Vfurnace_x4_top___024root {
    CData/*7:0*/ small;
    SData/*15:0*/ medium;
    IData/*31:0*/ input;
    IData/*31:0*/ output;
    QData/*63:0*/ wide;
    CData/*7:0*/ bytes[16];
};
"""
    signature = ("VL_INLINE_OPT void model___ico_sequent__TOP__0"
                 "(Vfurnace_x4_top___024root* vlSelf) {\n// Body\n")
    body = r"""
    vlSelf->small = vlSelf->small + vlSelf->input;
    vlSelf->bytes[vlSelf->input & 15U] = vlSelf->small;
    if (vlSelf->input & 1U) {
        vlSelf->medium = vlSelf->wide >> 13;
        vlSelf->small = vlSelf->medium + vlSelf->small;
    } else {
        vlSelf->output = vlSelf->small + vlSelf->medium;
    }
    vlSelf->wide = (vlSelf->wide << 17) ^ vlSelf->input;
    vlSelf->output = vlSelf->output + vlSelf->small + vlSelf->medium;
    vlSelf->output = vlSelf->output ^ vlSelf->bytes[(vlSelf->input >> 4) & 15U];
"""
    original = signature + body + "\n}"
    changed, rows = transform(original, header)
    if len(rows) != 1 or len(rows[0]["scalar_fields"]) != 5:
        raise ValueError("scalar contract failed to select every scalar storage type")
    for bad in (
            "callback();", "escape(vlSelf);", "return;", "while (1) {}",
            "vlSelf->output++;", "vlSelf->output += 1;",
            "VL_ADD_W(1, &vlSelf->output, 0, 0);"):
        try:
            transform(signature + body + bad + "\n}", header)
        except ValueError:
            pass
        else:
            raise ValueError(f"scalar transform accepted unsupported operation: {bad}")
    program = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
using CData = uint8_t;
using SData = uint16_t;
using IData = uint32_t;
using QData = uint64_t;
#define VL_INLINE_OPT
""" + header + original.replace("model___ico_sequent__TOP__0", "reference") + changed + r"""
int main() {
    Vfurnace_x4_top___024root original{}, lowered{};
    uint32_t random = 17;
    for (unsigned i = 0; i < 20000; ++i) {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        original.input = random;
        original.bytes[i & 15] ^= i;
        if (i % 7 == 0) original.wide ^= (uint64_t(random) << 32) | i;
        lowered = original;
        reference(&original);
        model___ico_sequent__TOP__0(&lowered);
        assert(std::memcmp(&original, &lowered, sizeof(original)) == 0);
    }
}
"""
    (output / "scalar-contract.cpp").write_text(program)
    run(["g++", "--version"], output, "compiler-version", receipt)
    run(["g++", "-std=c++17", "-O3", output.relative_to(ROOT) / "scalar-contract.cpp",
         "-o", output.relative_to(ROOT) / "scalar-contract"],
        output, "scalar-contract-build", receipt)
    run([output.relative_to(ROOT) / "scalar-contract"], output, "scalar-contract-run", receipt)
    receipt["contract"] = {"full_state_comparisons": 20000, "rejected_side_effect_cases": 7}
    profile = json.loads(project_path(Path(receipt["profile_receipt"])).read_text())
    paths = [project_path(Path(row["receipt"])) for row in profile["children"]]
    child_path = next(path for path in paths
                      if json.loads(path.read_text()).get("compile_profile") == "schedule-profile")
    child = json.loads(child_path.read_text())
    directory = project_path(Path(child["executable"])).parent
    header_path = directory / "Vfurnace_x4_top___024root.h"
    header = header_path.read_text()
    dry_run = []
    for source in sorted(directory.glob("*DepSet*.cpp")):
        text = source.read_text()
        if not FUNCTION.search(text):
            continue
        changed, rows = transform(text, header)
        (output / source.name).write_text(changed)
        dry_run.extend(rows)
    if len(dry_run) != 3:
        raise ValueError("retained generated-code contract missed a profiled function")
    receipt["contract"]["retained_generated_functions"] = dry_run


def measure(output, receipt):
    from boot_pgo_probe import equivalent
    from verify import SEEDS, software
    build = software(output, receipt)
    receipt["fresh_software_s"] = time.monotonic() - receipt.pop("_monotonic_start")
    pairs = {}
    for profile in ("scalar-baseline", "scalar-candidate"):
        cache = output / f"{profile}-executable-{uuid.uuid4().hex[:8]}"
        for seed in SEEDS:
            root = output / f"{profile}-seed{seed}-{uuid.uuid4().hex[:8]}"
            root.mkdir()
            record = run([
                "python3", "tests/boot_probe.py", "--build-receipt", build.relative_to(ROOT),
                "--seed", str(seed), "--cycles", "5000000", "--compile-profile", profile,
                "--invocation-cache", cache.relative_to(ROOT), "--audit-state",
                "--output-root", root.relative_to(ROOT),
            ], output, f"{profile}-seed{seed}", receipt, timeout_s=1500, check=False)
            found = list(root.glob("boot-*/receipt.json"))
            if len(found) != 1:
                raise ValueError("missing unique scalar pairing child")
            path = found[0]
            child = json.loads(path.read_text())
            receipt["children"].append({"receipt": str(path.relative_to(ROOT)), "sha256": digest(path)})
            save(output, receipt)
            simulation = next(c for c in child["commands"]
                              if c["stdout"] == "simulation.stdout.txt")
            if record["exit_code"] != 1 or child["exit_code"] != 1 or (
                    simulation["exit_code"] != 1 or simulation["timed_out"]):
                raise ValueError("scalar pairing failed before intended cycle boundary")
            if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                    path.parent / "simulation-summary.txt").read_text():
                raise ValueError("scalar pairing contains a semantic failure")
            observed = child["execution_observations"]
            if observed["cycles"] != 5000000 or observed["retired"] <= 0 or (
                    observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
                raise ValueError("scalar pairing lacks complete compared prefix")
            row = {
                "seed": seed, "observed": observed, "final_state": child["final_state"],
                "uart_sha256": digest(path.parent / "uart.txt"),
                "simulation_s": simulation["duration_s"],
                "receipt": str(path.relative_to(ROOT)),
            }
            if profile == "scalar-baseline":
                pairs[seed] = (child, row)
            else:
                original, before = pairs[seed]
                for key in ("source_sha256", "tool_versions", "image_manifest_sha256",
                            "software_build_receipt_sha256"):
                    if original[key] != child[key]:
                        raise ValueError(f"scalar pairing input identity mismatch: {key}")
                equivalent(before, row)
                receipt.setdefault("equal_work", []).append({
                    "seed": seed, "baseline": before, "candidate": row,
                    "speedup": before["simulation_s"] / row["simulation_s"],
                })
            save(output, receipt)
    receipt["complete_three_seed_feasibility"] = "not established"
    receipt["promoted"] = False
    if any(row["speedup"] <= 1 for row in receipt["equal_work"]):
        raise ValueError("static scalar candidate did not improve every measured seed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-of", type=Path, required=True)
    parser.add_argument("--profile-receipt", type=Path, required=True)
    parser.add_argument("--mode", choices=("inspect", "contract", "measure"), default="inspect")
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    started = time.monotonic()
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(min(
        float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-scalar-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_scalar_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "source_sha256": {
            str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "children": [],
        "scope": "Static scalar-lowering diagnostic, not mandatory Linux acceptance.",
    }
    save(output, receipt)
    print(f"Scalar inspection: {output.relative_to(ROOT)}/receipt.json", flush=True)
    status = 1
    try:
        for key in ("repair_of", "profile_receipt"):
            path = project_path(getattr(args, key))
            receipt[key] = str(path.relative_to(ROOT))
            receipt[key + "_sha256"] = digest(path)
        run(["python3", "--version"], output, "python-version", receipt)
        if args.mode == "inspect":
            inspect(project_path(args.profile_receipt), output, receipt)
        else:
            contract(output, receipt)
            save(output, receipt)
            if args.mode == "measure":
                receipt["_monotonic_start"] = started
                measure(output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"source changed during scalar diagnostic: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["duration_s"] = time.monotonic() - started
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Scalar inspection exit={status}; {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
