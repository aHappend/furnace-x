#!/usr/bin/env python3
"""Bounded runner self-test, including deliberate timeout and descendant cleanup."""

import datetime
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, run, save


def main():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "evidence/preparation" / f"runner-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/runner_contract.py"], "cwd": ".",
        "source_sha256": {name: digest(ROOT / name) for name in (
            "tests/boot_probe.py", "tests/runner_contract.py", "tests/verify.py",
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
        status = 0
    except (OSError, RuntimeError, AssertionError) as error:
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
