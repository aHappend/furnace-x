#!/usr/bin/env python3
"""Invocation-local, source/tool/image-bound compiled boot executable reuse."""

import json
from pathlib import Path

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
            flags += ["-Werror=missing-profile", "-Werror=coverage-mismatch"]
    cpp = Path(*([".."] * len(obj.parts))) / "tests/boot_endpoint.cpp"
    run([
        "verilator", "--cc", "--exe", "--build", "-j", str(jobs),
        "--top-module", "furnace_x4_top", "--Mdir", obj,
        "--assert", "-Wno-fatal", *(["--savable"] if audit else []),
        *profile["verilator"], "-MAKEFLAGS",
        f"OPT_FAST={optimization} OPT_SLOW={optimization} OPT_GLOBAL={optimization}",
        "-CFLAGS", " ".join(flags),
        *(["-LDFLAGS", " ".join(link)] if link else []),
        *[p.relative_to(ROOT) for p in sorted((ROOT / "rtl").glob("*.sv"))],
        "tests/boot_observers.sv", cpp,
    ], output, stem, receipt)
    return obj / "Vfurnace_x4_top"


def clean_objects(obj):
    for path in obj.iterdir():
        if path.suffix in (".o", ".a", ".gch"):
            path.unlink()


def build_pgo(output, receipt, jobs, image_index, *, audit=False):
    profile_directory = output.relative_to(ROOT) / "compiler-profiles"
    project_path(profile_directory).mkdir()
    obj = output.relative_to(ROOT) / "obj"
    executable = compile_boot(
        output, receipt, jobs, "o3-pgo", obj=obj, phase="generate",
        profile_directory=profile_directory, audit=audit, stem="compile-generate",
    )
    cycles = COMPILE_PROFILES["o3-pgo"]["pgo_training_cycles"]
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
    return compile_boot(
        output, receipt, jobs, "o3-pgo", obj=obj, phase="use",
        profile_directory=profile_directory, audit=audit, stem="compile",
    )


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
    compile_output = cache / "compilation"
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
        if profile_name == "o3-pgo":
            executable = build_pgo(
                compile_output, compiled, jobs, output.relative_to(ROOT) / "image-index.txt",
                audit=audit)
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
