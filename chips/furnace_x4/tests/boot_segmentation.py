"""Invocation-local Linux continuation, with a reset-origin equivalence gate.

The Linux suite builds its images and one savable PGO executable from source.
Before using 40-million-cycle segments it compares uninterrupted and restored
execution, including an actual pending-DDR/active-UART cut. All commands inherit
the original 2700-second deadline; each executable leaf is bounded to 600 seconds.
Only score_boot and the unchanged three-seed coverage ledger confer success.
Historical checkpoints and the slower native-thread candidate are never used.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from boot_probe import ROOT, digest, now, run, save
from boot_scoring import score_boot


SEGMENT_CYCLES = 40000000
STATE_FILES = ("rtl-context.bin", "host.bin", "ram.bin",
               "context.bin", "logical-state.bin", "scheduler-state.bin")


def check_deadline():
    if time.monotonic() >= float(os.environ["FURNACE_VERIFY_DEADLINE"]):
        raise RuntimeError("2700-second aggregate execution deadline exhausted")


def identity(directory):
    return {name: {"sha256": digest(directory / name),
                   "bytes": (directory / name).stat().st_size} for name in STATE_FILES}


def validate_segment(metrics, observations, start, end, previous=None):
    if metrics["start_cycle"] != start or not start < metrics["end_cycle"] <= end:
        raise ValueError("segment cycle continuity violated")
    if metrics["context_time"] != metrics["end_cycle"] * 10:
        raise ValueError("segment context time differs from executed cycles")
    complete = bool(metrics["complete_boot"])
    if metrics["outcome"] != ("complete" if complete else "continuation"):
        raise ValueError("inconsistent segment outcome")
    if not complete and metrics["end_cycle"] != end:
        raise ValueError("incomplete segment stopped before its boundary")
    if observations["simulation_exit"] != (0 if complete else 1):
        raise ValueError("segment claimed success without completed execution")
    if observations["cycles"] != metrics["end_cycle"]:
        raise ValueError("segment measurements disagree with endpoint")
    for field in ("retired", "equal_comparisons", "require_comparisons",
                  "output_bytes_compared", "coverage"):
        if observations[field] != metrics[field]:
            raise ValueError(f"segment observation mismatch: {field}")
    if not metrics["retired"] or not metrics["equal_comparisons"]:
        raise ValueError("segment contains no compared instruction execution")
    if previous:
        if metrics["retired"] <= previous["retired"]:
            raise ValueError("segment made no instruction progress")
        for field in ("equal_comparisons", "require_comparisons",
                      "output_bytes_compared", "uart_bytes"):
            if metrics[field] < previous[field]:
                raise ValueError(f"segment lost cumulative state: {field}")
        if any(metrics["coverage"].get(k, 0) < v
               for k, v in previous["coverage"].items()):
            raise ValueError("segment lost cumulative coverage")


class Segments:
    def __init__(self, output, receipt, executable, image_index, binding):
        self.output, self.receipt = output, receipt
        self.executable, self.image_index = executable, image_index
        self.binding = binding
        self.storage = output / "checkpoint-images"
        self.storage.mkdir()

    def guard(self):
        check_deadline()
        for name, expected in self.binding.items():
            if digest(ROOT / name) != expected:
                raise ValueError(f"segment input identity changed: {name}")
        check_deadline()

    def execute(self, name, seed, end, *, prior=None, cut=0, event=None,
                compare_progress=True):
        self.guard()
        folder = self.storage / f"{name}-{uuid.uuid4().hex[:8]}"
        folder.mkdir()
        final = self.storage / f"state-{uuid.uuid4().hex[:8]}"
        start = 0 if prior is None else prior["metrics"]["end_cycle"]
        restore = None if prior is None else ROOT / prior["state"]
        before = None if restore is None else identity(restore)
        if prior is not None and before != prior["identity"]:
            raise ValueError("checkpoint identity changed before restoration")
        record = run([
            self.executable, self.image_index.relative_to(ROOT), folder.relative_to(ROOT),
            str(end), str(seed), "-" if restore is None else restore.relative_to(ROOT),
            final.relative_to(ROOT), "-" if event is None else event.relative_to(ROOT), str(cut),
        ], self.output, name, self.receipt, timeout_s=600)
        metrics_path = folder / "metrics.json"
        observed_path = folder / "execution-measurements.json"
        metrics = json.loads(metrics_path.read_text())
        observations = json.loads(observed_path.read_text())
        validate_segment(metrics, observations, start, end,
                         None if prior is None or not compare_progress else prior["metrics"])
        if restore is not None:
            if identity(restore) != before:
                raise ValueError("restoration modified its predecessor checkpoint")
            roundtrip = folder / f"roundtrip-{folder.name}"
            if identity(roundtrip) != before:
                raise ValueError("immediate restored state differs from predecessor")
        row = {
            "seed": seed, "state": str(final.relative_to(ROOT)), "identity": identity(final),
            "restored_from": None if restore is None else str(restore.relative_to(ROOT)),
            "restored_identity": before, "immediate_roundtrip_identical": restore is not None,
            "metrics": metrics, "observations": observations, "duration_s": record["duration_s"],
            "folder": str(folder.relative_to(ROOT)),
            "metrics_sha256": digest(metrics_path), "observations_sha256": digest(observed_path),
            "uart_sha256": digest(folder / "uart.txt"),
        }
        self.receipt.setdefault("segments", []).append(row)
        save(self.output, self.receipt)
        self.guard()
        return row

    def compare(self, name, left, right):
        same = left["identity"] == right["identity"]
        semantic = left["observations"] == right["observations"]
        uart = (ROOT / left["folder"] / "uart.txt").read_bytes() == (
            ROOT / right["folder"] / "uart.txt").read_bytes()
        self.receipt.setdefault("equivalence_comparisons", []).append({
            "name": name, "left": left["state"], "right": right["state"],
            "left_identity": left["identity"], "right_identity": right["identity"],
            "complete_state_identical": same, "observations_identical": semantic,
            "uart_identical": uart,
        })
        save(self.output, self.receipt)
        if not (same and semantic and uart):
            raise ValueError(f"{name}: continuous/restored execution differs")

    def equivalence(self):
        event = self.storage / f"pending-uart-{uuid.uuid4().hex[:8]}"
        baseline = self.execute("equivalence-continuous", 17, 5000000,
                                cut=2500000, event=event)
        cycle = baseline["metrics"]["event_cycle"]
        if not event.is_dir() or not 8 < cycle < 5000000:
            raise ValueError("no actual pending-DDR/active-UART checkpoint")
        first = self.execute("equivalence-first", 17, 2500000)
        cut = ROOT / baseline["folder"] / ("cut-" + Path(baseline["folder"]).name)
        if identity(cut) != first["identity"]:
            raise ValueError("continuous/split first-boundary state differs")
        resumed = self.execute("equivalence-resumed", 17, 5000000, prior=first)
        self.compare("two-segment-final", baseline, resumed)
        active = self.execute("equivalence-pending-uart", 17, 5000000, prior={
            "state": str(event.relative_to(ROOT)), "identity": identity(event),
            "metrics": {"end_cycle": cycle},
        }, compare_progress=False)
        if not active["metrics"]["restored_pending"] or not active["metrics"]["restored_uart_active"]:
            raise ValueError("restoration did not exercise pending DDR and active UART")
        self.compare("pending-uart-final", baseline, active)
        corrupted = self.storage / f"corrupted-{uuid.uuid4().hex[:8]}"
        shutil.copytree(ROOT / first["state"], corrupted)
        with (corrupted / "host.bin").open("r+b") as stream:
            stream.write((0).to_bytes(8, "little"))
        if identity(corrupted) == first["identity"]:
            raise ValueError("state corruption failed to change checkpoint identity")
        rejected = self.storage / f"rejection-{uuid.uuid4().hex[:8]}"
        rejected.mkdir()
        record = run([
            self.executable, self.image_index.relative_to(ROOT), rejected.relative_to(ROOT),
            "5000000", "17", corrupted.relative_to(ROOT),
            (self.storage / f"never-created-{uuid.uuid4().hex[:8]}").relative_to(ROOT), "-", "0",
        ], self.output, "corrupted-state-rejection", self.receipt, timeout_s=600, check=False)
        if record["exit_code"] != 1 or record["timed_out"] or (
                "unsupported host checkpoint version" not in
                (self.output / record["stderr"]).read_text()):
            raise ValueError("corrupted checkpoint was not rejected by the intended assertion")
        self.receipt["corrupted_state_rejection"] = {
            "original_identity": first["identity"], "corrupted_identity": identity(corrupted),
            "exit_code": record["exit_code"], "semantic_assertion": "unsupported host checkpoint version",
        }
        self.receipt["equivalence_passed"] = True
        save(self.output, self.receipt)


def linux_runs(output, receipt, seeds, build):
    from verify import child_probe, coverage_requirements, write_coverage
    from boot_native_threads_probe import logical_preflight

    cache = output / f"boot-executable-{uuid.uuid4().hex[:8]}"
    compile_path, compiled = child_probe("boot_probe.py", [
        "--build-receipt", str(build.relative_to(ROOT)),
        "--compile-profile", "o3-pgo-fixedpoint", "--invocation-cache",
        str(cache.relative_to(ROOT)), "--audit-state", "--logical-state",
        "--checkpoint-endpoint", "--compile-only",
    ], output, receipt, "boot-segment-compilation")
    manifest_path = cache / "executable.json"
    manifest = json.loads(manifest_path.read_text())
    executable = Path(manifest["executable"])
    if digest(ROOT / executable) != manifest["sha256"] or (
            not manifest["binding"].get("checkpoint_endpoint")):
        raise ValueError("checkpoint executable identity/binding mismatch")
    logical_preflight(output, receipt, (ROOT / executable).parent, (ROOT / executable).parent)
    images_path = ROOT / compiled["image_manifest"]
    images = json.loads(images_path.read_text())
    binding = {
        **receipt["source_sha256"], str(executable): manifest["sha256"],
        str(manifest_path.relative_to(ROOT)): digest(manifest_path),
        str(compile_path.relative_to(ROOT)): digest(compile_path),
        str(build.relative_to(ROOT)): digest(build),
        compiled["image_manifest"]: compiled["image_manifest_sha256"],
        **{str((images_path.parent / image["file"]).relative_to(ROOT)): image["sha256"]
           for image in images["images"]},
    }
    image_index = compile_path.parent / "image-index.txt"
    binding[str(image_index.relative_to(ROOT))] = digest(image_index)
    receipt["segmentation_binding"] = binding
    receipt["tool_versions"] = compiled["tool_versions"]
    receipt["segment_cycles"] = SEGMENT_CYCLES
    save(output, receipt)
    Segments(output, receipt, executable, image_index, binding).equivalence()
    measured, failures = {}, []

    def launch(seed):
        folder = output / f"seed{seed}-{uuid.uuid4().hex[:8]}"
        folder.mkdir()
        child = {
            "schema": 1, "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
            "source_sha256": receipt["source_sha256"], "commands": [], "seed": seed,
            "timeout_s": 2700, "segment_cycles": SEGMENT_CYCLES, "segments": [],
            "binding": binding,
        }
        save(folder, child)
        runner = Segments(folder, child, executable, image_index, binding)
        prior = None
        try:
            while True:
                start = 0 if prior is None else prior["metrics"]["end_cycle"]
                prior = runner.execute(f"segment-{start}", seed, start + SEGMENT_CYCLES, prior=prior)
                if prior["metrics"]["complete_boot"]:
                    scored = score_boot(prior["observations"],
                                        (ROOT / prior["folder"] / "uart.txt").read_text())
                    runner.guard()
                    child["measurements"] = {f"seed{seed}.{k}": v for k, v in scored.items()}
                    child["exit_code"] = 0
                    break
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            child["error"] = str(error)
            child["exit_code"] = 1
        finally:
            child["end_utc"] = now()
            save(folder, child)
        return folder / "receipt.json", child

    with ThreadPoolExecutor(max_workers=len(seeds)) as workers:
        futures = {workers.submit(launch, seed): seed for seed in seeds}
        for future in as_completed(futures):
            seed = futures[future]
            try:
                path, child = future.result()
                receipt.setdefault("children", []).append({
                    "receipt": str(path.relative_to(ROOT)), "sha256": digest(path)})
                measured.update(child.get("measurements", {}))
                if child["exit_code"]:
                    failures.append(f"seed{seed}: {child.get('error', 'incomplete Linux execution')}")
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                failures.append(f"seed{seed}: {error}")
            write_coverage(output, coverage_requirements("linux", seeds), measured)
            save(output, receipt)
    if failures:
        raise ValueError("; ".join(failures))
    check_deadline()
    return measured
