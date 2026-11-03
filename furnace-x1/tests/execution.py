"""Bounded subprocess execution with append-only source-bound advisory receipts."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hashes(root=ROOT):
    paths = sorted([*root.glob("rtl/*.sv"), *root.glob("design/*.md"), *root.glob("tests/*")])
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def fresh(stem, preparation=False, root=ROOT):
    parent = root / "evidence"
    if preparation:
        parent /= "preparation"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = parent / f"{stem}-{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class Run:
    def __init__(self, directory, root=ROOT):
        self.directory = Path(directory)
        self.root = Path(root)
        self.receipt = {
            "kind": "verification preparation" if "preparation" in directory.parts else "L1",
            "argv": [sys.executable, *sys.argv], "cwd": str(Path.cwd()),
            "source_sha256": hashes(root), "start": now(), "commands": [],
            "coverage": {}, "outcome": "running",
        }
        snapshot = self.directory / "sources"
        for path in self.receipt["source_sha256"]:
            destination = snapshot / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / path, destination)
        self.save()

    def save(self):
        # Only the current live receipt is updated; no completed run is reused.
        (self.directory / "receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")

    def command(self, argv, name, *, cwd=None, timeout=3600, expect=0):
        cwd = Path(cwd or self.root)
        if any(c["name"] == name for c in self.receipt["commands"]):
            raise ValueError(f"duplicate command log: {name}")
        record = {"name": name, "argv": [str(x) for x in argv], "cwd": str(cwd),
                  "start": now(), "timeout_s": timeout,
                  "stdout": f"{name}.stdout.txt", "stderr": f"{name}.stderr.txt"}
        self.receipt["commands"].append(record)
        self.save()
        start = time.monotonic()
        try:
            with (self.directory / record["stdout"]).open("wb") as out, (
                self.directory / record["stderr"]
            ).open("wb") as err:
                process = subprocess.Popen(record["argv"], cwd=cwd, stdout=out, stderr=err,
                                           start_new_session=True)
                try:
                    record["exit"] = process.wait(timeout=timeout)
                    record["timeout"] = False
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    record["timeout"] = True
                    record["exit"] = process.returncode
        except OSError as exc:
            record["launch_error"] = str(exc)
            raise
        finally:
            record["end"] = now()
            record["duration_s"] = time.monotonic() - start
            self.save()
        stdout = (self.directory / record["stdout"]).read_text(errors="replace")
        stderr = (self.directory / record["stderr"]).read_text(errors="replace")
        if record["timeout"] or (expect is not None and record["exit"] != expect):
            raise AssertionError(f"{name}: exit={record['exit']} timeout={record['timeout']}\n"
                                 f"{stdout[-6000:]}\n{stderr[-6000:]}")
        return record["exit"], stdout, stderr

    def versions(self, tools):
        commands = {"iverilog": ["iverilog", "-V"], "vvp": ["vvp", "-V"],
                    "verilator": ["verilator", "--version"], "yosys": ["yosys", "-V"],
                    "python3": ["python3", "--version"], "g++": ["g++", "--version"],
                    "make": ["make", "--version"]}
        for tool in tools:
            self.command(commands[tool], "version-" + tool)

    def finish(self, outcome, error=None):
        removed = []
        for directory in self.directory.glob("*-obj"):
            if directory.is_dir():
                for pattern in ("*.o", "*.a", "*.gch"):
                    for path in directory.rglob(pattern):
                        removed.append(str(path.relative_to(self.directory)))
                        path.unlink()
        self.receipt["removed_transient_objects"] = removed
        if outcome == "failed":
            rows = list(self.receipt.get("runs", []))
            rows += list(self.receipt.get("mutation_ledger", {}).values())
            for row in rows:
                if row.get("outcome") == "not_started":
                    row["outcome"] = "not_executed"
                elif row.get("outcome") == "running":
                    row["outcome"] = "failed"
        self.receipt.update(outcome=outcome, end=now())
        if error is not None:
            self.receipt["error"] = str(error)
        self.save()
