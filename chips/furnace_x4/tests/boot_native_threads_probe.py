#!/usr/bin/env python3
"""Bounded native-thread/save-state compatibility diagnostic, not acceptance."""

import argparse
import datetime
import hashlib
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


FIXTURE = """module native_thread_support(
    input wire clk, input wire rst_n,
    input wire [31:0] a, input wire [31:0] b,
    output reg [31:0] x, output reg [31:0] y
);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        x <= 0;
        y <= 0;
    end else begin
        x <= (x + a) ^ (a << 3);
        y <= (y + b) ^ (b << 5);
    end
end
endmodule
"""


def resources():
    result = {
        "online_cpus": os.cpu_count(),
        "affinity_cpus": sorted(os.sched_getaffinity(0)),
        "quota_note": "Only exposed cgroup files are reported; affinity is not a CPU quota.",
        "cgroup_files": {},
    }
    for name in (
        "/proc/self/cgroup",
        "/sys/fs/cgroup/cpu.max",
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us",
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us",
        "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us",
    ):
        path = Path(name)
        result["cgroup_files"][name] = (
            path.read_text().strip() if path.exists() else "not exposed"
        )
    print(json.dumps(result, indent=2))


def clean_completed_objects(output, receipt, prior_path):
    prior = json.loads(prior_path.read_text())
    directory = prior_path.parent
    directory.relative_to(ROOT / "evidence/preparation")
    if not directory.name.startswith("boot-native-threads-") or (
            prior.get("argv", [])[:2] != ["python3", "tests/boot_native_threads_probe.py"]):
        raise ValueError("cleanup target is not this probe's preparation output")
    if prior.get("end_utc") is None or prior.get("exit_code") is None or any(
            row.get("end_utc") is None for row in prior["commands"]):
        raise ValueError("cleanup target has unfinished commands")
    receipt["cleanup_of"] = {
        "receipt": str(prior_path.relative_to(ROOT)), "sha256": digest(prior_path)}
    files = [path for path in sorted(directory.rglob("*"))
             if path.is_file() and path.suffix in (".o", ".a", ".gch")]
    receipt["removed_transient_objects"] = [
        {"path": str(path.relative_to(ROOT)), "sha256": digest(path),
         "bytes": path.stat().st_size} for path in files]
    save(output, receipt)
    for path in files:
        path.resolve().relative_to(directory.resolve())
        path.unlink()
    receipt["cleanup_completed"] = True
    save(output, receipt)


def serialization_schema(directory):
    schema = {}
    generated = {}
    for path in sorted(directory.glob("*.cpp")):
        text = path.read_text()
        for match in re.finditer(r"void (\w+)::__Vserialize\(VerilatedSerialize& os\) \{", text):
            start = match.end()
            depth = 1
            end = start
            while end < len(text) and depth:
                depth += (text[end] == "{") - (text[end] == "}")
                end += 1
            if depth:
                raise ValueError(f"unclosed generated serializer: {path.name}")
            body = text[start:end - 1]
            schema[match[1]] = {
                "body": " ".join(body.split()),
                "writes": [" ".join(value.split())
                           for value in re.findall(r"\bos\s*<<\s*(.*?);", body, re.S)],
            }
            generated[str(path.relative_to(ROOT))] = digest(path)
    if not schema or not any(name.endswith("___024root") for name in schema):
        raise ValueError("complete generated RTL serializer is missing")
    return schema, generated


def fulltop_preflight(output, receipt):
    """Keep raw layout diagnostics and require complete logical accounting."""
    from boot_probe import COMPILE_PROFILES

    schemas = {}
    for name in ("o3-pgo-fixedpoint", "native-threads-candidate"):
        directory = output / f"schema-{name}"
        run([
            "verilator", "--cc", "--savable", "--assert", "-Wno-fatal",
            "--top-module", "furnace_x4_top", "--Mdir", directory.relative_to(ROOT),
            *COMPILE_PROFILES[name]["verilator"],
            *[path.relative_to(ROOT) for path in sorted((ROOT / "rtl").glob("*.sv"))],
            "tests/boot_observers.sv",
        ], output, f"schema-{name}", receipt)
        schema, generated = serialization_schema(directory)
        manifest = output / f"schema-{name}.json"
        manifest.write_text(json.dumps(schema, indent=2) + "\n")
        schemas[name] = schema
        receipt.setdefault("serialization_schemas", {})[name] = {
            "manifest": manifest.name, "sha256": digest(manifest),
            "generated_sha256": generated,
            "serializer_count": len(schema),
            "write_count": sum(len(row["writes"]) for row in schema.values()),
        }
        save(output, receipt)
    baseline = schemas["o3-pgo-fixedpoint"]
    candidate = schemas["native-threads-candidate"]
    differences = {}
    for name in sorted(baseline.keys() | candidate.keys()):
        left, right = baseline.get(name), candidate.get(name)
        if left == right:
            continue
        a = set(left["writes"]) if left else set()
        b = set(right["writes"]) if right else set()
        differences[name] = {
            "baseline_only_writes": sorted(a - b),
            "candidate_only_writes": sorted(b - a),
            "common_writes": len(a & b),
            "identical_body": False,
        }
    receipt["serialization_schema_differences"] = differences
    save(output, receipt)
    receipt["save_state_compatibility"] = (
        "different raw layouts; complete logical comparison required" if differences else
        "identical complete generated serialization schemas")
    save(output, receipt)
    return logical_preflight(
        output, receipt, output / "schema-o3-pgo-fixedpoint",
        output / "schema-native-threads-candidate")


def logical_preflight(output, receipt, baseline, candidate, *, syntax_capture=False):
    from boot_logical_state import accounting, schema, validate_accounting, write_exporter

    left, right = schema(baseline), schema(candidate)
    plan = accounting(left, right, baseline, candidate)
    path = output / "logical-state-accounting.json"
    with path.open("x") as stream:
        stream.write(json.dumps(plan, indent=2) + "\n")
    counts = {}
    for row in plan["fields"].values():
        key = row["disposition"]
        counts[key] = counts.get(key, 0) + 1
    scheduler_counts = {}
    for row in plan["unserialized"].values():
        key = row["disposition"]
        scheduler_counts[key] = scheduler_counts.get(key, 0) + 1
    receipt["logical_comparator"] = {
        "manifest": path.name, "sha256": digest(path), "dispositions": counts,
        "baseline_directory": str(baseline.relative_to(ROOT)),
        "candidate_directory": str(candidate.relative_to(ROOT)),
        "unserialized_fields": len(plan["unserialized"]), "complete": plan["complete"],
        "unserialized_dispositions": scheduler_counts,
        "unresolved_scheduler_fields": [
            name for name, row in plan["unserialized"].items()
            if row["disposition"] == "unresolved"],
        "baseline_serialized_fields": sum(len(row["fields"]) for row in left["classes"].values()),
        "candidate_serialized_fields": sum(len(row["fields"]) for row in right["classes"].values()),
    }
    save(output, receipt)
    if syntax_capture:
        version = run(["verilator", "-V"], output, "verilator-build-configuration", receipt)
        configuration = (output / version["stdout"]).read_text()
        roots = re.findall(r"^\s*VERILATOR_ROOT\s*=\s*(.+?)\s*$", configuration, re.M)
        if not roots or not (Path(roots[0]) / "include/verilated.h").is_file():
            raise ValueError("cannot identify the installed Verilator include directory")
        includes = Path(roots[0]) / "include"
        from boot_lifetime import CASTS, SCALAR_PURE, balanced
        from boot_logical_state import clean_cpp
        functions_header = clean_cpp((includes / "verilated_funcs.h").read_text())
        helpers = {}
        for name in sorted(SCALAR_PURE - CASTS):
            matches = list(re.finditer(
                r"static inline (?:IData|QData) " + re.escape(name) +
                r"\(([^()]*)\)\s+(?:VL_PURE|VL_MT_SAFE)\s*\{", functions_header))
            if len(matches) != 1 or re.search(r"[*&]", matches[0][1]):
                raise ValueError("audited scalar helper no longer has a scalar-only signature: " + name)
            match = matches[0]
            end = balanced(functions_header, match.end() - 1)
            body = functions_header[match.end():end - 1]
            if re.search(r"\b(?:vlSelf|vlSymsp|voidSelf)\b", body):
                raise ValueError("audited scalar helper accesses model state: " + name)
            helpers[name] = {"scalar_signature": match[1].strip(),
                             "definition_sha256": hashlib.sha256(
                                 functions_header[match.start():end].encode()).hexdigest()}
        receipt["logical_runtime_library"] = {
            "headers_sha256": {name: digest(includes / name) for name in (
                "verilated_funcs.h", "verilated_threads.h", "verilated_threads.cpp")},
            "scalar_helpers": helpers,
            "scope": "Source-bound scalar helper and scheduler API audit; not a scheduler-state proof.",
        }
        save(output, receipt)
        result = run(["g++", "--version"], output, "comparator-cxx-version", receipt)
        receipt.setdefault("tool_versions", {})["g++"] = (output / result["stdout"]).read_text()
        from boot_logical_state_test import exporter_fixture
        exporter_fixture(output, receipt)
        for owner, directory, model in (("baseline", baseline, left),
                                        ("candidate", candidate, right)):
            capture = output / f"capture-{owner}"
            capture.mkdir()
            write_exporter(capture, model)
            run([
                "g++", "-std=c++17", "-fsyntax-only", "-DFURNACE_BOOT_AUDIT",
                "-DFURNACE_BOOT_LOGICAL_AUDIT",
                *(["-DFURNACE_BOOT_NATIVE_THREADS=2"] if owner == "candidate" else []),
                "-I", capture.relative_to(ROOT), "-I", directory.relative_to(ROOT),
                "-I", includes, "-I", includes / "vltstd", "tests/boot_endpoint.cpp",
            ], output, f"capture-{owner}-syntax", receipt)
            receipt.setdefault("logical_capture_syntax", {})[owner] = {
                "exporter": str((capture / "boot_logical_capture.h").relative_to(ROOT)),
                "sha256": digest(capture / "boot_logical_capture.h"),
                "scope": "C++ syntax and all field-storage static_asserts only; no model build/run.",
            }
            save(output, receipt)
    validate_accounting(plan)
    return plan


def comparator_diagnostic(output, receipt, retained):
    """Repair diagnostics use saved codegen, never rerun the known slow boots."""
    path = project_path(retained)
    previous = json.loads(path.read_text())
    directory = path.parent
    directory.relative_to(ROOT / "evidence/preparation")
    if previous.get("serialization_schema_differences") is None:
        raise ValueError("retained receipt does not contain the original schema failure")
    receipt["retained_schema_input"] = {
        "receipt": str(retained), "sha256": digest(path),
        "scope": "Historical generated C++ inputs for comparator development only.",
    }
    for profile in ("o3-pgo-fixedpoint", "native-threads-candidate"):
        schema_directory = directory / f"schema-{profile}"
        for name, expected in previous["serialization_schemas"][profile]["generated_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError("retained generated serializer changed: " + name)
        receipt.setdefault("retained_codegen_sha256", {})[profile] = {
            str(item.relative_to(ROOT)): digest(item)
            for item in sorted(schema_directory.iterdir())
            if item.suffix in (".cpp", ".h")
        }
    save(output, receipt)
    run(["python3", "tests/boot_logical_state_test.py", "--fixture-root",
         (output / "comparator-fixtures").relative_to(ROOT)],
        output, "comparator-sensitivity", receipt)
    receipt["comparator_sensitivity"] = "passed; see complete unittest stdout/stderr"
    save(output, receipt)
    return logical_preflight(output, receipt, directory / "schema-o3-pgo-fixedpoint",
                             directory / "schema-native-threads-candidate", syntax_capture=True)


def measure(output, receipt, cycles, comparison_plan):
    from boot_logical_state import equivalent, validate_accounting
    from verify import SEEDS, assert_coverage, coverage_requirements, linux_runs, software

    validate_accounting(comparison_plan)
    started = time.monotonic()
    build = software(output, receipt)
    receipt["fresh_software_s"] = time.monotonic() - started
    pairs = {}
    caches = {}
    mismatches = []
    for profile in ("o3-pgo-fixedpoint", "native-threads-candidate"):
        cache = output / f"{profile}-executable-{uuid.uuid4().hex[:8]}"
        caches[profile] = cache
        for seed in SEEDS:
            root = output / f"{profile}-seed{seed}-{uuid.uuid4().hex[:8]}"
            root.mkdir()
            record = run([
                "python3", "tests/boot_probe.py", "--build-receipt", build.relative_to(ROOT),
                "--seed", str(seed), "--cycles", str(cycles), "--compile-profile", profile,
                "--invocation-cache", cache.relative_to(ROOT), "--audit-state",
                "--logical-state",
                "--output-root", root.relative_to(ROOT),
            ], output, f"{profile}-seed{seed}", receipt, timeout_s=2700, check=False)
            found = list(root.glob("boot-*/receipt.json"))
            if len(found) != 1:
                raise ValueError("missing unique native-thread comparison receipt")
            path = found[0]
            child = json.loads(path.read_text())
            receipt.setdefault("children", []).append({
                "receipt": str(path.relative_to(ROOT)), "sha256": digest(path)})
            save(output, receipt)
            simulation = next((row for row in child["commands"]
                               if row["stdout"] == "simulation.stdout.txt"), None)
            if simulation is None:
                raise ValueError("native-thread pairing failed before simulation: " +
                                 child.get("diagnostic_error", str(record["exit_code"])))
            if record["exit_code"] != 1 or child["exit_code"] != 1 or (
                    simulation["exit_code"] != 1 or simulation["timed_out"]):
                raise ValueError("native-thread pairing did not reach compared cycle boundary")
            if "FAIL: cycle budget exhausted without complete workload UART record" not in (
                    path.parent / "simulation-summary.txt").read_text():
                raise ValueError("native-thread pairing contains a semantic failure")
            observed = child["execution_observations"]
            if observed["cycles"] != cycles or observed["retired"] <= 0 or (
                    observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
                raise ValueError("native-thread pairing lacks full compared execution")
            executable_manifest = json.loads((cache / "executable.json").read_text())
            compiled_path = project_path(Path(executable_manifest["compilation_receipt"]))
            compiled = json.loads(compiled_path.read_text())
            if digest(compiled_path) != executable_manifest["compilation_receipt_sha256"]:
                raise ValueError("native-thread compilation receipt identity changed")
            capture = compiled["logical_capture"]["compile"]
            schema_path = project_path(Path(capture["schema"]))
            expected = comparison_plan[
                "baseline" if profile == "o3-pgo-fixedpoint" else "candidate"]
            if digest(schema_path) != capture["schema_sha256"] or (
                    json.loads(schema_path.read_text()) != expected):
                raise ValueError("compiled logical schema or proof inputs differ from preflight")
            row = {
                "seed": seed, "observed": observed, "final_state": child["final_state"],
                "uart_sha256": digest(path.parent / "uart.txt"),
                "simulation_s": simulation["duration_s"], "receipt": str(path.relative_to(ROOT)),
                "state_directory": child["final_state_directory"],
            }
            if profile == "o3-pgo-fixedpoint":
                pairs[seed] = (child, row)
            else:
                original, before = pairs[seed]
                for key in ("source_sha256", "tool_versions", "image_manifest_sha256",
                            "software_build_receipt_sha256"):
                    if original[key] != child[key]:
                        raise ValueError(f"native-thread pairing input mismatch: {key}")
                comparison = {
                    "seed": seed, "baseline": before, "candidate": row,
                    "speedup": before["simulation_s"] / row["simulation_s"],
                }
                try:
                    comparison["logical_state_comparison"] = equivalent(
                        comparison_plan, before, row,
                        project_path(Path(before["state_directory"])),
                        project_path(Path(row["state_directory"])))
                    comparison["full_equivalence"] = True
                except ValueError as error:
                    comparison["full_equivalence"] = False
                    comparison["mismatch"] = str(error)
                    mismatches.append(f"seed{seed}: {error}")
                receipt.setdefault("equal_work", []).append(comparison)
            save(output, receipt)
    if mismatches:
        raise ValueError("native-thread state comparison rejected: " + "; ".join(mismatches))
    receipt["paired_three_seed_equivalence"] = "exact full-state equality"
    if any(row["speedup"] <= 1 for row in receipt["equal_work"]):
        raise ValueError("native-thread candidate did not improve every measured seed")
    measured = linux_runs(output, receipt, SEEDS, build, audit=True,
                          cache=caches["native-threads-candidate"], stem="complete-native-threads",
                          profile="native-threads-candidate", logical=True)
    assert_coverage(output, coverage_requirements("linux", SEEDS), measured)
    receipt["complete_three_seed_feasibility"] = "scored complete within inherited deadline"
    receipt["requires_independent_evaluation"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repair-of", type=Path, action="append")
    parser.add_argument("--mode", choices=("support", "preflight", "measure", "cleanup", "comparator"),
                        default="support")
    parser.add_argument("--retained-schema", type=Path)
    parser.add_argument("--cleanup-of", type=Path)
    parser.add_argument("--cycles", type=int, default=5000000)
    parser.add_argument("--experiment-origin", type=Path,
                        help="Retain the original support/setup experiment's aggregate deadline")
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    if args.resources:
        resources()
        return 0
    if args.mode == "cleanup" and args.cleanup_of is None:
        parser.error("--mode cleanup requires --cleanup-of")
    if args.mode == "comparator" and args.retained_schema is None:
        parser.error("--mode comparator requires --retained-schema")
    started = time.monotonic()
    deadline = min(float(os.environ.get("FURNACE_VERIFY_DEADLINE", "inf")), started + 2700)
    origin = None
    if args.experiment_origin:
        origin_path = project_path(args.experiment_origin)
        origin = json.loads(origin_path.read_text())
        original_start = datetime.datetime.fromisoformat(origin["start_utc"])
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - original_start).total_seconds()
        deadline = min(deadline, started + 2700 - elapsed - 1)
    if args.cycles <= 8:
        parser.error("prefix cycles must exceed reset duration")
    os.environ["FURNACE_VERIFY_DEADLINE"] = str(deadline)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-native-threads-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    receipt = {
        "schema": 1,
        "argv": ["python3", "tests/boot_native_threads_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "initial_remaining_s": deadline - started,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "commands": [], "promoted": False,
        "scope": "Native two-thread code-generation and complete-state audit compatibility only.",
        "complete_three_seed_feasibility": "not established",
        "paired_three_seed_equivalence": "not executed",
        "full_state_requirement": {
            "rtl_context": "VerilatedSave via --savable, including all RTL and context state",
            "host_reference": "checkpoint_host without field exclusions",
            "ram": "all 128 MiB",
            "observations": "UART, observers, coverage and every comparison counter unchanged",
        },
    }
    if origin is not None:
        receipt["experiment_origin"] = {
            "receipt": str(args.experiment_origin), "sha256": digest(origin_path),
            "start_utc": origin["start_utc"],
        }
    save(output, receipt)
    print(f"Native-thread support receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        receipt["repair_of"] = [
            {"receipt": str(path), "sha256": digest(project_path(path))}
            for path in (args.repair_of or [])
        ]
        for tool in ("python3", "verilator"):
            record = run([tool, "--version"], output, tool + "-version", receipt)
            receipt.setdefault("tool_versions", {})[tool] = (output / record["stdout"]).read_text()
        if args.mode == "comparator":
            receipt["scope"] = "Comparator sensitivity and retained-codegen state accounting only."
            comparator_diagnostic(output, receipt, args.retained_schema)
            status = 0
            return 0
        if args.mode == "cleanup":
            clean_completed_objects(output, receipt, project_path(args.cleanup_of))
            receipt["scope"] = "Completed diagnostic object cleanup only; no new simulation."
            status = 0
            return 0
        run(["python3", "tests/boot_native_threads_probe.py", "--resources"],
            output, "cpu-resources", receipt)
        receipt["resources"] = json.loads((output / "cpu-resources.stdout.txt").read_text())
        if len(receipt["resources"]["affinity_cpus"]) < 2:
            raise ValueError("two-thread candidate lacks two affinity-eligible CPUs")
        fixture = output / "native_thread_support.sv"
        fixture.write_text(FIXTURE)
        receipt["fixture_sha256"] = digest(fixture)
        save(output, receipt)
        base = ["verilator", "--cc", "--threads", "2",
                "--top-module", "native_thread_support", fixture.relative_to(ROOT)]
        run([*base, "--Mdir", relative / "obj-threads"],
            output, "native-two-thread-codegen", receipt)
        receipt["native_two_thread_codegen"] = "supported"
        result = run([*base, "--savable", "--Mdir", relative / "obj-savable-threads"],
                     output, "native-savable-two-thread-codegen", receipt, check=False)
        if result["exit_code"] != 0:
            diagnostic = (output / result["stderr"]).read_text()
            receipt["save_state_compatibility"] = "rejected by installed tool"
            receipt["tool_diagnostic"] = diagnostic.strip()
            raise ValueError(
                "native two-thread evaluation cannot use the existing complete RTL/context "
                "save-state comparison; see native-savable-two-thread-codegen.stderr.txt. "
                "No full-top candidate was built and no output-only substitute was used."
            )
        receipt["save_state_compatibility"] = "code generation accepted; paired comparison still required"
        if args.mode in ("preflight", "measure"):
            comparison_plan = fulltop_preflight(output, receipt)
        if args.mode == "measure":
            measure(output, receipt, args.cycles, comparison_plan)
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        changed = [name for name, expected in receipt["source_sha256"].items()
                   if not (ROOT / name).is_file() or digest(ROOT / name) != expected]
        receipt["source_binding_changes"] = changed
        if changed:
            status = 1
            receipt["source_binding_error"] = "inputs changed during diagnostic"
        receipt["duration_s"] = time.monotonic() - started
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Native-thread support exit={status}; {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
