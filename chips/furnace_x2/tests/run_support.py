"""Source-bound, append-only execution records for project-owned verification."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from threading import Event
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent


def now():
    return datetime.now(timezone.utc).isoformat()


class Run:
    def __init__(self, stem, argv, preparation=False, repair_of=None):
        prefix = Path("evidence/preparation" if preparation else "evidence")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = prefix / f"{stem}-{stamp}-{uuid4().hex[:12]}"
        (ROOT / self.path).mkdir(parents=True, exist_ok=False)
        sources = []
        for pattern in ("rtl/*.sv", "tests/*", "design/*.md",
                        "furnace_x1_reference/rtl/*.sv"):
            sources.extend(p for p in ROOT.glob(pattern) if p.is_file())
        self.receipt = {
            "schema": 1, "acceptance_evidence": not preparation,
            "argv": argv, "cwd": ".", "started_at": now(),
            "source_sha256": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(sources)
            },
            "commands": [],
        }
        if repair_of is not None:
            prior = Path(repair_of)
            if prior.is_absolute() or ".." in prior.parts or not (ROOT / prior).is_file():
                raise ValueError("repair_of must be an existing project-relative receipt")
            self.receipt["repair_of"] = str(prior)
        self.save()

    def save(self):
        (ROOT / self.path / "receipt.json").write_text(
            json.dumps(self.receipt, indent=2) + "\n")

    def command(self, argv, stem, timeout=3600, cwd=Path("."), storage_path=None):
        record = {
            "argv": [str(arg) for arg in argv], "cwd": str(cwd),
            "started_at": now(), "timeout_s": timeout,
            "stdout": str(self.path / f"{stem}.stdout.txt"),
            "stderr": str(self.path / f"{stem}.stderr.txt"),
        }
        self.receipt["commands"].append(record)
        self.save()
        stop_sampling = Event()
        sampler = None
        executor = None
        if storage_path is not None:
            target = ROOT / storage_path
            if not target.is_relative_to(ROOT / self.path):
                raise ValueError("storage monitoring must stay inside this exact run")
            storage = dict(path=str(storage_path), sample_period_s=0.25, samples=0,
                           peak_allocated_bytes=0, peak_apparent_bytes=0,
                           peak_pch_bytes=0,
                           minimum_available_bytes=shutil.disk_usage(ROOT).free)
            record["storage"] = storage

            def sample():
                allocated = apparent = pch = 0
                for path in target.rglob("*"):
                    try:
                        stat = path.stat()
                    except FileNotFoundError:
                        continue
                    allocated += stat.st_blocks * 512
                    apparent += stat.st_size
                    if path.suffix == ".gch":
                        pch += stat.st_size
                storage["samples"] += 1
                storage["peak_allocated_bytes"] = max(storage["peak_allocated_bytes"], allocated)
                storage["peak_apparent_bytes"] = max(storage["peak_apparent_bytes"], apparent)
                storage["peak_pch_bytes"] = max(storage["peak_pch_bytes"], pch)
                storage["minimum_available_bytes"] = min(
                    storage["minimum_available_bytes"], shutil.disk_usage(ROOT).free)

            def monitor():
                while not stop_sampling.wait(storage["sample_period_s"]):
                    sample()

            sample()
            executor = ThreadPoolExecutor(max_workers=1)
            sampler = executor.submit(monitor)
        try:
            with (ROOT / record["stdout"]).open("w") as stdout, (
                    ROOT / record["stderr"]).open("w") as stderr:
                child = subprocess.run(record["argv"], cwd=ROOT / cwd,
                                       stdout=stdout, stderr=stderr,
                                       timeout=timeout, check=False)
            record.update(exit_code=child.returncode, timeout=False)
            if child.returncode:
                raise RuntimeError(f"{stem}: exit {child.returncode}; "
                                   f"see {record['stdout']} and {record['stderr']}")
        except subprocess.TimeoutExpired:
            record.update(exit_code=None, timeout=True)
            raise
        finally:
            if sampler is not None:
                stop_sampling.set()
                executor.shutdown(wait=True)
                sampler.result()
                sample()
            record["ended_at"] = now()
            self.save()
        return ROOT / record["stdout"]

    def verilator_build(self, argv, stem, obj):
        # Verilator 5.020's split-build PCH can dwarf the generated model.
        # Its supported legacy make rules keep split C++ compilation without PCH.
        return self.command(
            [*argv, "-MAKEFLAGS", "VM_DEFAULT_RULES=0", "-CFLAGS", "-Os"],
            stem, storage_path=obj)

    def finish(self, error=None):
        self.receipt.update(ended_at=now(), exit_code=0 if error is None else 1)
        if error is not None:
            self.receipt["error"] = str(error)
        self.save()
        print(f"{self.path}/receipt.json: exit={self.receipt['exit_code']}")

    def remove_intermediates(self, relative_path):
        target = ROOT / relative_path
        if not target.is_relative_to(ROOT / self.path) or target == ROOT / self.path:
            raise ValueError("cleanup target must be inside this exact run")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
