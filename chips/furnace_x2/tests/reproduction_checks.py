"""Fresh project execution using only the admitted deliverable source set."""

import hashlib
import json
import shutil
from uuid import uuid4

from run_support import ROOT


def execute(run):
    fresh = run.path/f"fresh-project-{uuid4().hex[:12]}"
    (ROOT/fresh).mkdir()
    copied = {}
    for pattern in ("rtl/*.sv", "tests/*", "design/*.md", "furnace_x1_reference/rtl/*.sv"):
        for source in sorted(ROOT.glob(pattern)):
            if not source.is_file():
                continue
            relative = source.relative_to(ROOT)
            target = ROOT/fresh/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != run.receipt["source_sha256"][str(relative)]:
                raise AssertionError(f"source changed while copying {relative}")
            copied[str(relative)] = digest
    if not copied or any(name.startswith((".vulcan/", ".git/", ".tooling/", "VULCAN/", "evidence/"))
                         for name in copied):
        raise AssertionError("incorrect reproduction source set")
    run.receipt["reproduction"] = dict(project=str(fresh), copied_sha256=copied, suites=[])
    run.save()
    for suite in ("smoke", "synthesis"):
        args = ["python3", "tests/verify.py", "--suite", suite]
        if not run.receipt["acceptance_evidence"]:
            args.append("--preparation")
        log = run.command(args, f"fresh-{suite}", cwd=fresh)
        receipts = sorted((ROOT/fresh/"evidence").rglob("receipt.json"))
        passed = []
        for receipt in receipts:
            record = json.loads(receipt.read_text())
            if record.get("exit_code") == 0 and record.get("argv", [])[1:4] == [
                    "tests/verify.py", "--suite", suite]:
                passed.append(str(receipt.relative_to(ROOT)))
        if not passed:
            raise AssertionError(f"fresh {suite} lacks a successful execution receipt")
        run.receipt["reproduction"]["suites"].append(
            dict(suite=suite, receipts=passed, raw_output=str(log.relative_to(ROOT))))
        run.save()
