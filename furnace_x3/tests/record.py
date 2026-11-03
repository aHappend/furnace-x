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
        self.versioned = set()
        self.save()
        self.command(["python3", "--version"], "runtime-python-version", version=True)

    @staticmethod
    def now():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def relative(self, path):
        return str(Path(path).resolve().relative_to(ROOT))

    def save(self):
        (self.path / "receipt.json").write_text(json.dumps(self.data, indent=2) + "\n")

    def command(self, argv, name, timeout=3600, cwd=ROOT, version=False):
        executable = str(argv[0])
        versions = {"python3": "--version", "iverilog": "-V", "vvp": "-V",
                    "verilator": "--version", "yosys": "-V",
                    "g++": "--version", "make": "--version"}
        if version:
            self.versioned.add(executable)
        else:
            required = [executable]
            if executable == "verilator" and "--binary" in argv:
                required += ["g++", "make"]
            for tool in required:
                if tool in versions and tool not in self.versioned:
                    self.command([tool, versions[tool]], f"tool-version-{tool}", version=True)
        out = self.path / f"{name}.stdout.txt"
        err = self.path / f"{name}.stderr.txt"
        if out.exists() or err.exists():
            raise RuntimeError(f"refusing to overwrite execution logs: {name}")
        row = {
            "argv": [str(x) for x in argv], "cwd": self.relative(cwd),
            "start": self.now(), "timeout_s": timeout,
            "stdout": self.relative(out), "stderr": self.relative(err),
            "tool_version_query": version,
            "source_hashes": hashes(),
        }
        self.data["commands"].append(row)
        self.save()
        start = time.monotonic()
        with out.open("w") as stdout, err.open("w") as stderr:
            try:
                process = subprocess.Popen(row["argv"], cwd=cwd, stdout=stdout, stderr=stderr)
            except OSError as error:
                stderr.write(f"{type(error).__name__}: {error}\n")
                row.update(exit=None, timed_out=False, launch_error=str(error), end=self.now(),
                           elapsed_s=time.monotonic()-start)
                self.save()
                raise
            row["pid"] = process.pid
            self.save()
            while True:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    process.kill()
                    row["exit"] = process.wait()
                    row["timed_out"] = True
                    break
                try:
                    row["exit"] = process.wait(timeout=min(30, remaining))
                    row["timed_out"] = False
                    break
                except subprocess.TimeoutExpired:
                    print(f"PROGRESS {name} elapsed_s={time.monotonic() - start:.0f}",
                          flush=True)
        row.update(end=self.now(), elapsed_s=time.monotonic() - start)
        self.save()
        if row["exit"] or row["timed_out"]:
            raise RuntimeError(f"{name} failed: exit={row['exit']}, logs={row['stdout']}")
        return out.read_text()

    def finish(self, error=None):
        self.data.update(end=self.now(), outcome="failed" if error else "passed",
                         error=str(error) if error else None)
        self.save()
        print(self.relative(self.path / "receipt.json"), flush=True)
