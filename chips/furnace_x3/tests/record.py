"""Source-bound, append-only preparation execution receipts."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]


def hashes(root=ROOT):
    patterns = ("rtl/*.sv", "design/*.md", "firmware/*", "tests/*",
                "furnace_x2_reference/rtl/*.sv")
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for pattern in patterns for path in sorted(root.glob(pattern))
        if path.is_file()
    }


class Experiment:
    def __init__(self, stem, repair_of=None):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = ROOT / "evidence" / "preparation" / f"{stem}-{stamp}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.data = {
            "advisory": True, "argv": list(os.sys.argv), "cwd": ".",
            "start": self.now(), "source_hashes": hashes(),
            "commands": [], "repair_of": repair_of,
        }
        self.save()

    @staticmethod
    def now():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def relative(self, path):
        return str(Path(path).resolve().relative_to(ROOT))

    def save(self):
        (self.path / "receipt.json").write_text(json.dumps(self.data, indent=2) + "\n")

    def command(self, argv, name, timeout=3600, cwd=ROOT, version=False):
        out = self.path / f"{name}.stdout.txt"
        err = self.path / f"{name}.stderr.txt"
        row = {
            "argv": [str(x) for x in argv], "cwd": self.relative(cwd),
            "start": self.now(), "timeout_s": timeout,
            "stdout": self.relative(out), "stderr": self.relative(err),
            "tool_version_query": version,
        }
        start = time.monotonic()
        with out.open("w") as stdout, err.open("w") as stderr:
            process = subprocess.Popen(row["argv"], cwd=cwd, stdout=stdout, stderr=stderr)
            row["pid"] = process.pid
            try:
                row["exit"] = process.wait(timeout=timeout)
                row["timed_out"] = False
            except subprocess.TimeoutExpired:
                process.kill()
                row["exit"] = process.wait()
                row["timed_out"] = True
        row.update(end=self.now(), elapsed_s=time.monotonic() - start)
        self.data["commands"].append(row)
        self.save()
        if row["exit"] or row["timed_out"]:
            raise RuntimeError(f"{name} failed: exit={row['exit']}, logs={row['stdout']}")
        return out.read_text()

    def finish(self, error=None):
        self.data.update(end=self.now(), outcome="failed" if error else "passed",
                         error=str(error) if error else None)
        self.save()
        print(self.relative(self.path / "receipt.json"), flush=True)
