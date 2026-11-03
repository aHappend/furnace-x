#!/usr/bin/env python3
"""Fresh bounded clean-directory diagnostic using the mandatory reproduction implementation."""

import argparse
import datetime
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, save
from verify import portability, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"portability-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/portability_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources()},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "timed_out": False, "commands": [],
        "scope": "Fresh-source software/RTL reproduction preparation; mandatory runtime check remains required",
    }
    save(output, receipt)
    status = 1
    try:
        portability(output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError(f"source changed during reproduction: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["end_utc"] = now()
        receipt["exit_code"] = status
        save(output, receipt)
    print(f"Portability preparation receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
