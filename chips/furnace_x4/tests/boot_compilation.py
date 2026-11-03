#!/usr/bin/env python3
"""Invocation-local, source/tool/image-bound compiled boot executable reuse."""

import json
from pathlib import Path
import re
import uuid

from boot_probe import COMPILE_PROFILES, ROOT, digest, project_path, run, save


def binding(receipt, profile, audit):
    return {
        "source_sha256": receipt["source_sha256"],
        "tool_versions": receipt["tool_versions"],
        "image_manifest_sha256": receipt["image_manifest_sha256"],
        "compile_profile": profile,
        "configuration": COMPILE_PROFILES[profile],
        "audit_state": audit,
    }


def compile_boot(output, receipt, jobs, profile_name, *, obj=None, phase=None,
                 profile_directory=None, audit=False, stem="compile"):
    profile = COMPILE_PROFILES[profile_name]
    relative = output.relative_to(ROOT)
    obj = relative / "obj" if obj is None else obj
    optimization = profile["optimization"]
    flags = [optimization, "-std=c++17", *profile.get("compiler_flags", [])]
    link = list(profile.get("linker_flags", []))
    if audit:
        flags.append("-DFURNACE_BOOT_AUDIT")
    if phase is not None:
        if phase not in ("generate", "use") or profile_directory is None:
            raise ValueError("PGO requires a generation/use phase and profile directory")
        # GCC includes the object path in its profile key. Both passes must
        # compile in the same object directory with the same translation units.
        flag = f"-fprofile-{phase}={project_path(profile_directory)}"
        flags.append(flag)
        link.append(flag)
        if phase == "use":
            flags += ["-Wmissing-profile", "-Werror=coverage-mismatch"]
    cpp = Path(*([".."] * len(obj.parts))) / "tests/boot_endpoint.cpp"
    command = [
        "verilator", "--cc", "--exe", *([] if profile.get("generated_fixedpoint") else ["--build"]),
        "-j", str(jobs),
        "--top-module", "furnace_x4_top", "--Mdir", obj,
        "--assert", "-Wno-fatal", *(["--savable"] if audit else []),
        *profile["verilator"], "-MAKEFLAGS",
        f"OPT_FAST={optimization} OPT_SLOW={optimization} OPT_GLOBAL={optimization}",
        "-CFLAGS", " ".join(flags),
        *(["-LDFLAGS", " ".join(link)] if link else []),
        *[p.relative_to(ROOT) for p in sorted((ROOT / "rtl").glob("*.sv"))],
        "tests/boot_observers.sv", cpp,
    ]
    run(command, output, stem, receipt)
    if profile.get("generated_fixedpoint"):
        from generated_eval import optimize
        receipt.setdefault("generated_evaluation", {})[stem] = optimize(ROOT / obj, digest)
        if profile.get("generated_scalar"):
            from generated_scalar import optimize as scalar_optimize
            receipt.setdefault("generated_scalar", {})[stem] = scalar_optimize(ROOT / obj, digest)
        if profile.get("generated_replay"):
            from generated_replay import optimize as replay_optimize
            receipt.setdefault("generated_replay", {})[stem] = replay_optimize(ROOT / obj, digest)
        if profile.get("generated_schedule_profile"):
            from generated_schedule import instrument
            receipt.setdefault("generated_schedule_profile", {})[stem] = instrument(
                ROOT / obj, digest)
        save(output, receipt)
        run(["make", "-C", obj, "-f", "Vfurnace_x4_top.mk", "-j", str(jobs),
             f"OPT_FAST={optimization}", f"OPT_SLOW={optimization}",
             f"OPT_GLOBAL={optimization}"], output, stem + "-build", receipt)
    return obj / "Vfurnace_x4_top"


def clean_objects(obj):
    for path in obj.iterdir():
        if path.suffix in (".o", ".a", ".gch"):
            path.unlink()


def build_pgo(output, receipt, jobs, image_index, *, audit=False, profile_name="o3-pgo"):
    profile_directory = output.relative_to(ROOT) / "compiler-profiles"
    project_path(profile_directory).mkdir()
    obj = output.relative_to(ROOT) / "obj"
    executable = compile_boot(
        output, receipt, jobs, profile_name, obj=obj, phase="generate",
        profile_directory=profile_directory, audit=audit, stem="compile-generate",
    )
    cycles = COMPILE_PROFILES[profile_name]["pgo_training_cycles"]
    training = run([
        executable, image_index, output.relative_to(ROOT) / "training-uart.txt",
        str(cycles), "17", output.relative_to(ROOT) / "training-summary.txt",
        output.relative_to(ROOT) / "training-measurements.json",
    ], output, "profile-training", receipt, check=False)
    observed = json.loads((output / "training-measurements.json").read_text())
    if training["exit_code"] != 1 or observed["simulation_exit"] != 1 or (
            observed["cycles"] != cycles or observed["retired"] <= 0 or
            observed["equal_comparisons"] <= 0 or observed["require_comparisons"] <= 0):
        raise ValueError("PGO training did not reach its intended compared cycle boundary")
    if "FAIL: cycle budget exhausted without complete workload UART record" not in (
            output / "training-summary.txt").read_text():
        raise ValueError("PGO training has an unexpected semantic failure")
    profiles = sorted(project_path(profile_directory).rglob("*.gcda"))
    if not profiles:
        raise ValueError("GCC generated no training profiles")
    receipt["compiler_profiles"] = {
        str(p.relative_to(ROOT)): digest(p) for p in profiles
    }
    receipt["profile_training"] = observed
    save(output, receipt)
    clean_objects(ROOT / obj)
    executable = compile_boot(
        output, receipt, jobs, profile_name, obj=obj, phase="use",
        profile_directory=profile_directory, audit=audit, stem="compile",
    )
    diagnostics = (output / ("compile-build.stderr.txt" if
                   COMPILE_PROFILES[profile_name].get("generated_fixedpoint")
                   else "compile.stderr.txt")).read_text()
    missing = re.findall(r"^([^:\n]+\.cpp):.*\n.*profile count data file not found",
                         diagnostics, re.MULTILINE)
    warning_count = diagnostics.count("[-Wmissing-profile]")
    allowed = re.compile(
        r"Vfurnace_x4_top___024unit__(?:Slow|DepSet_h[0-9a-f]+__0__Slow)\.cpp")
    if warning_count != len(missing) or any(not allowed.fullmatch(name) for name in missing):
        raise ValueError(f"PGO has missing profiles outside unused unit helpers: {missing}")
    receipt["untrained_cold_units"] = missing
    save(output, receipt)
    return executable


def reusable_boot(cache, output, receipt, jobs, profile_name, *, audit=False):
    """Only share within the caller's fresh output namespace, never globally."""
    manifest_path = cache / "executable.json"
    expected = binding(receipt, profile_name, audit)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        executable = project_path(Path(manifest["executable"]))
        executable.relative_to(cache)
        compile_receipt = project_path(Path(manifest["compilation_receipt"]))
        compile_receipt.relative_to(cache.parent)
        recorded = json.loads(compile_receipt.read_text())
        if manifest["binding"] != expected or digest(executable) != manifest["sha256"]:
            raise ValueError("reused boot executable identity mismatch")
        if digest(compile_receipt) != manifest["compilation_receipt_sha256"] or (
                recorded["exit_code"] != 0):
            raise ValueError("reused boot compilation receipt mismatch")
        receipt["executable_reuse"] = {
            "manifest": str(manifest_path.relative_to(ROOT)),
            "manifest_sha256": digest(manifest_path), "compiled": False,
            "executable_sha256": manifest["sha256"],
        }
        save(output, receipt)
        return executable.relative_to(ROOT)
    if cache.exists():
        raise ValueError("occupied boot cache without a completed compilation manifest")
    cache.mkdir()
    compile_output = cache / f"compilation-{uuid.uuid4().hex[:8]}"
    compile_output.mkdir()
    compiled = {
        "schema": 1, "argv": receipt["argv"], "cwd": ".",
        "start_utc": receipt["start_utc"], "end_utc": None, "exit_code": None,
        "source_sha256": receipt["source_sha256"], "commands": [],
        "tool_versions": receipt["tool_versions"], "binding": expected,
    }
    save(compile_output, compiled)
    from boot_probe import now
    try:
        if "pgo_training_cycles" in COMPILE_PROFILES[profile_name]:
            executable = build_pgo(
                compile_output, compiled, jobs, output.relative_to(ROOT) / "image-index.txt",
                audit=audit, profile_name=profile_name)
        else:
            executable = compile_boot(compile_output, compiled, jobs, profile_name, audit=audit)
        compiled["exit_code"] = 0
    finally:
        compiled["end_utc"] = now()
        if compiled["exit_code"] is None:
            compiled["exit_code"] = 1
        save(compile_output, compiled)
        obj = compile_output / "obj"
        if obj.is_dir():
            clean_objects(obj)
    manifest = {
        "binding": expected, "executable": str(executable), "sha256": digest(ROOT / executable),
        "compilation_receipt": str((compile_output / "receipt.json").relative_to(ROOT)),
        "compilation_receipt_sha256": digest(compile_output / "receipt.json"),
    }
    with manifest_path.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    receipt["executable_reuse"] = {
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": digest(manifest_path), "compiled": True,
        "executable_sha256": manifest["sha256"],
    }
    save(output, receipt)
    return executable
