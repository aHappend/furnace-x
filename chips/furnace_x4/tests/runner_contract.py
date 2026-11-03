#!/usr/bin/env python3
"""Bounded runner self-test, including deliberate timeout and descendant cleanup."""

import argparse
import copy
import datetime
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def reject_stale_compilation(manifest_path, output, receipt):
    from boot_compilation import reusable_boot
    manifest = json.loads(manifest_path.read_text())
    paths = [manifest_path, project_path(Path(manifest["executable"])),
             project_path(Path(manifest["compilation_receipt"]))]
    identities = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    receipt["reuse_guard_fixture"] = identities
    fixture = manifest["binding"]
    cases = []
    for changed in ("source_sha256", "tool_versions", "image_manifest_sha256"):
        guard_output = output / f"guard-{changed}-{uuid.uuid4().hex[:8]}"
        guard_output.mkdir()
        consumer = copy.deepcopy(fixture)
        if changed == "source_sha256":
            consumer[changed]["tests/intentional-stale-fixture"] = "0" * 64
        elif changed == "tool_versions":
            consumer[changed]["intentional-stale-tool"] = {"stdout": "not the bound tool"}
        else:
            consumer[changed] = "0" * 64
        try:
            reusable_boot(manifest_path.parent, guard_output, consumer, 2,
                          fixture["compile_profile"], audit=fixture["audit_state"])
        except ValueError as error:
            assert "identity mismatch" in str(error), str(error)
        else:
            raise AssertionError(f"reused executable with changed {changed}")
        cases.append(changed)
        receipt["comparisons"] += 1
    assert {str(p.relative_to(ROOT)): digest(p) for p in paths} == identities
    receipt["comparisons"] += 1
    receipt["stale_compilation_rejections"] = cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-manifest", type=Path,
                        help="Retained executable fixture for non-executing identity-guard checks")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "evidence/preparation" / f"runner-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/runner_contract.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT / name) for name in (
            "tests/boot_probe.py", "tests/boot_compilation.py",
            "tests/runner_contract.py", "tests/verify.py",
        )}, "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 600, "commands": [], "comparisons": 0,
    }
    save(output, receipt)
    status = 1
    try:
        run(["python3", "--version"], output, "version", receipt)
        run(["python3", "tests/verify.py", "--help"], output, "entrypoint-help", receipt)
        help_text = (output / "entrypoint-help.stdout.txt").read_text()
        assert "{behavior,linux,defects,synthesis,portability}" in help_text
        receipt["comparisons"] += 1
        invalid = run(["python3", "tests/verify.py", "--suite", "behavior",
                       "--seeds", "17"], output, "entrypoint-invalid-seeds", receipt,
                      check=False)
        assert invalid["exit_code"] == 2
        assert "required seed sequence is 17,89,211" in (
            output / invalid["stderr"]).read_text()
        receipt["comparisons"] += 1
        run(["python3", "-c", "print('runner-success')"], output, "success", receipt)
        result = run(["python3", "-c", "import sys; sys.exit(7)"],
                     output, "nonzero", receipt, check=False)
        assert result["exit_code"] == 7 and not result["timed_out"]
        receipt["comparisons"] += 1
        marker = output.relative_to(ROOT) / "escaped-child.txt"
        grandchild = (
            "import time; from pathlib import Path; time.sleep(3); "
            f"Path({str(marker)!r}).write_text('child escaped cleanup')"
        )
        parent = (
            "import subprocess,time; "
            f"subprocess.Popen(['python3','-c',{grandchild!r}]); "
            "print('descendant launched',flush=True); time.sleep(10)"
        )
        try:
            # This short timeout tests timeout machinery, not RTL liveness.
            run(["python3", "-c", parent], output, "expected-timeout", receipt,
                timeout_s=0.5)
        except RuntimeError as error:
            assert "execution timeout" in str(error)
        else:
            raise AssertionError("runner accepted a timed-out command")
        record = receipt["commands"][-1]
        assert record["timed_out"] and record["exit_code"] != 0
        assert "descendant launched" in (output / record["stdout"]).read_text()
        receipt["comparisons"] += 1
        time.sleep(3.2)
        assert not (ROOT / marker).exists(), "descendant survived process-group cleanup"
        receipt["comparisons"] += 1
        try:
            run(["python3", "-c", "print('overwrite')"], output, "success", receipt)
        except ValueError as error:
            assert "overwrite" in str(error)
        else:
            raise AssertionError("runner overwrote an earlier command log")
        assert (output / "success.stdout.txt").read_text() == "runner-success\n"
        receipt["comparisons"] += 1
        try:
            run(["./tests/nonexistent-runner-fixture"], output, "launch-error", receipt)
        except OSError:
            pass
        else:
            raise AssertionError("missing executable accepted")
        assert receipt["commands"][-1]["launch_error"]
        assert receipt["commands"][-1]["end_utc"]
        receipt["comparisons"] += 1
        if args.reuse_manifest:
            reject_stale_compilation(project_path(args.reuse_manifest), output, receipt)
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError, AssertionError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(json.dumps({"receipt": str(output.relative_to(ROOT) / "receipt.json"),
                      "exit_code": status, "comparisons": receipt["comparisons"]}))
    return status


if __name__ == "__main__":
    sys.exit(main())
