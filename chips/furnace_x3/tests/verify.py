#!/usr/bin/env python3
"""Portable L1 checks. Hardware gates and product reporting belong to the runtime."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md",
           "tests/*", "furnace_x2_reference/rtl/*.sv")


def identity(root=ROOT):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for selector in SOURCES for p in sorted(root.glob(selector)) if p.is_file()
    }


class Evidence:
    def __init__(self, suite, preparation=False, repair_of=None):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = ROOT / "evidence" / ("preparation" if preparation else "")
        self.path = base / f"{suite}-{stamp}-{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.record = {
            "schema": 1, "suite": suite, "advisory_preparation": preparation,
            "argv": [sys.executable, *sys.argv], "cwd": ".",
            "start_time": time.time(), "source_hashes": identity(),
            "commands": [], "tools": {}, "repair_of": repair_of,
        }

    def run(self, argv, name, cwd=ROOT, timeout=3600, expect_failure=False):
        argv = [str(x) for x in argv]
        stdout, stderr = self.path / f"{name}.stdout.txt", self.path / f"{name}.stderr.txt"
        record = {"argv": argv, "cwd": os.path.relpath(cwd, ROOT),
                  "start_time": time.time(), "timeout_s": timeout,
                  "stdout": str(stdout.relative_to(ROOT)),
                  "stderr": str(stderr.relative_to(ROOT))}
        self.record["commands"].append(record)
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                process = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err,
                                         timeout=timeout, check=False)
                record.update(exit_code=process.returncode, timed_out=False)
            except subprocess.TimeoutExpired:
                record.update(exit_code=None, timed_out=True)
            finally:
                record["end_time"] = time.time()
        if record["timed_out"]:
            raise RuntimeError(f"{name}: tool timeout, not a functional mismatch")
        if (record["exit_code"] == 0) == expect_failure:
            raise RuntimeError(f"{name}: unexpected exit {record['exit_code']}; see {stderr.relative_to(ROOT)}")
        return stdout.read_text(errors="replace") + stderr.read_text(errors="replace")

    def require(self, tools):
        for tool in tools:
            if shutil.which(tool) is None:
                raise RuntimeError(f"missing executable: {tool}")
            flag = "-V" if tool in ("iverilog", "vvp") else "--version"
            if tool == "yosys":
                flag = "-V"
            output = self.run([tool, flag], f"version-{tool}")
            self.record["tools"][tool] = output

    def finish(self, error=None):
        self.record.update(end_time=time.time(), exit_code=1 if error else 0,
                           outcome="failed" if error else "passed", error=error)
        (self.path / "receipt.json").write_text(json.dumps(self.record, indent=2) + "\n")
        print(f"{self.record['outcome']}: {self.path.relative_to(ROOT)}/receipt.json", flush=True)


def startup(e):
    e.require(["iverilog", "vvp"])
    configs = [(64, 1, 1), (512, 65, 3)]
    invalid = [(w, 1, 1) for w in (0, 32, 128)]
    invalid += [(64, n, 1) for n in (0, 9217)]
    invalid += [(64, 1, n) for n in (0, 17)]
    for index, (width, maximum, sg) in enumerate(configs + invalid):
        executable = e.path / f"startup-{index}.vvp"
        e.run(["iverilog", "-g2012", "-Wall", "-s", "startup",
               f"-Pstartup.DATA_WIDTH={width}", f"-Pstartup.MAX_PACKET_BYTES={maximum}",
               f"-Pstartup.MAX_SG={sg}", "-o", executable.relative_to(ROOT),
               "tests/startup.sv", *map(str, sorted(Path("rtl").glob("*.sv")))],
              f"startup-{index}-compile")
        output = e.run(["vvp", executable.relative_to(ROOT)], f"startup-{index}-run",
                       timeout=60, expect_failure=index >= len(configs))
        if index >= len(configs):
            if "PARAMETER ERROR" not in output:
                raise AssertionError("invalid parameter failed without the explicit diagnostic")
        elif "STARTUP comparisons=9" not in output:
            raise AssertionError("startup finished without comparisons")


def vectors(path, maximum, key=reference.DEFAULT_KEY):
    packets = reference.corpus()
    packets += [bytes((i * 41 + 3) & 255 for i in range(length))
                for length in (1, 7, 8, 9, 63, 64, 65, 255, 256, 257, 1500, 9216)
                if length <= maximum]
    with path.open("w") as stream:
        for packet in packets:
            crc32, crc64 = reference.checksums(packet)
            header, tuple_bytes = reference.parse(packet)
            hash_value = reference.toeplitz(tuple_bytes, key) if tuple_bytes else 0
            stream.write(f"{packet.hex() or '-'} {crc32:x} {crc64:x} {header:0128x} "
                         f"{hash_value:x} {int(bool(tuple_bytes))}\n")


def compile_sim(e, width, maximum, sg, root=ROOT, label="functional"):
    directory = e.path / f"{label}-{width}-{maximum}-{sg}-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    obj = directory / "compile-obj"
    e.run(["verilator", "--cc", "--exe", "--build", "-j", "2",
           "-Wno-fatal", "--top-module", "furnace_x3_top",
           f"-GDATA_WIDTH={width}", f"-GMAX_PACKET_BYTES={maximum}", f"-GMAX_SG={sg}",
           "-CFLAGS", f"-DTEST_WIDTH={width} -DTEST_MAX={maximum} -DTEST_SG={sg}",
           "--Mdir", os.path.relpath(obj, root),
           *[str(p.relative_to(root)) for p in sorted((root / "rtl").glob("*.sv"))],
           str((root / "tests/driver.cpp").resolve())],
          f"{label}-{width}-{maximum}-{sg}-compile", cwd=root)
    binary = directory / "simulator"
    shutil.copy2(obj / "Vfurnace_x3_top", binary)
    shutil.rmtree(obj)
    return binary


def functional(e, width, maximum, sg, seeds, mode="matrix", root=ROOT, label="functional"):
    binary = compile_sim(e, width, maximum, sg, root=root, label=label)
    corpus = binary.parent / "vectors.txt"
    vectors(corpus, maximum)
    results = []
    for seed in seeds:
        output = e.run([os.path.relpath(binary, root), os.path.relpath(corpus, root),
                        str(seed), mode], f"{label}-{width}-{maximum}-{sg}-{seed}", cwd=root)
        records = [json.loads(line[7:]) for line in output.splitlines() if line.startswith("RESULT ")]
        if len(records) != 1:
            raise AssertionError("simulator did not emit exactly one structured coverage record")
        results.append({"width": width, "maximum": maximum, "sg": sg, "seed": seed,
                        "mode": mode, **records[0]})
    e.record.setdefault("runs", []).extend(results)
    return results


def leaf(e, top, root=ROOT, seeds=(17,), label=None, icarus=False):
    label = label or top
    binary = e.path / f"{label}-simulator"
    sources = ["tests/credits.sv", "rtl/furnace_token_bucket8.sv",
               "rtl/furnace_drr_scheduler.sv"]
    if icarus:
        e.run(["iverilog", "-g2012", "-Wall", "-s", top, "-o",
               os.path.relpath(binary, root), *sources], f"{label}-compile", cwd=root)
    else:
        obj = e.path / f"{label}-compile-{uuid.uuid4().hex[:8]}"
        e.run(["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
               "--top-module", top, "--Mdir", os.path.relpath(obj, root), *sources],
              f"{label}-compile", cwd=root)
        shutil.copy2(obj / f"V{top}", binary)
        shutil.rmtree(obj)
    outputs = []
    for seed in seeds:
        argv = (["vvp"] if icarus else []) + [os.path.relpath(binary, root), f"+seed={seed}"]
        output = e.run(argv, f"{label}-{seed}", cwd=root, timeout=60 if icarus else 3600)
        if "comparisons=" not in output:
            raise AssertionError(f"{label}: no observed numerical comparisons")
        outputs.append(output)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["behavior", "defects", "synthesis", "delivery"])
    parser.add_argument("--prepare", choices=["startup", "smoke", "cell", "credits"])
    parser.add_argument("--width", type=int, choices=[64, 512], default=64)
    parser.add_argument("--maximum", type=int, default=65)
    parser.add_argument("--segments", type=int, default=3)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    suites = [args.suite] if args.suite else ["behavior", "defects", "synthesis", "delivery"]
    if args.prepare:
        suites = [args.prepare]
    reference.self_check()
    for suite in suites:
        e = Evidence(suite, preparation=bool(args.prepare), repair_of=args.repair_of)
        try:
            if suite == "startup":
                startup(e)
            elif suite == "smoke":
                e.require(["verilator", "make", "g++"])
                functional(e, 64, 1, 1, [17], mode="smoke")
            elif suite == "cell":
                e.require(["verilator", "make", "g++"])
                functional(e, args.width, args.maximum, args.segments, [17])
            elif suite == "credits":
                e.require(["verilator", "make", "g++", "iverilog", "vvp"])
                leaf(e, "bucket_tb", icarus=True)
                leaf(e, "scheduler_tb")
            else:
                raise RuntimeError(f"verification implementation incomplete: {suite}")
        except Exception as error:
            e.finish(f"{type(error).__name__}: {error}")
            print(str(error), file=sys.stderr)
            return 1
        e.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
