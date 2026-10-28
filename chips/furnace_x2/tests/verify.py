#!/usr/bin/env python3
"""Portable L1 acceptance. Native target timing/hardware gates belong to the runtime.

Mapping: smoke -> reset, parent, CRC, latency and independent channel consumption;
behavior -> full seeded packet oracle plus directed rule/parser/boundary coverage;
defects -> separately compiled observable mutants; synthesis -> real retained
hierarchy/memory/state and mapped no-latch/no-divide assertions; portability ->
fresh source-only package executing the same smoke/oracle and compiled samples.
All modes are mandatory; --probe is an advisory, bounded development diagnostic.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge import leaf_bench, top_bench
from oracle import DEFAULT_KEY, self_check
from scenarios import Campaign, classifier_vectors, directed, packet, rss_vectors, seeded, smoke

ROOT = Path(__file__).resolve().parent.parent
SELECTORS = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md",
             "tests/*.py", "furnace_x1_reference/rtl/*.sv")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def selected(root=ROOT):
    files = sorted({p for pattern in SELECTORS for p in root.glob(pattern)})
    for pattern in SELECTORS:
        if not list(root.glob(pattern)):
            raise AssertionError(f"missing declared source selector: {pattern}")
    return files


class Run:
    def __init__(self, out, mode, repair_of=None):
        self.path = ROOT / out / ("run-" + uuid.uuid4().hex[:12])
        self.path.mkdir(parents=True, exist_ok=False)
        self.commands = []
        self.receipt = {
            "schema": 1, "mode": mode, "started_at": now(), "cwd": ".",
            "argv": ["python3", "tests/verify.py", *sys.argv[1:]],
            "commands": self.commands, "source_sha256": {}, "repair_of": repair_of,
            "acceptance_evidence": "preparation" not in self.path.relative_to(ROOT).parts}
        for src in selected():
            relative = src.relative_to(ROOT)
            self.receipt["source_sha256"][str(relative)] = digest(src)
            dst = self.path / "source" / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        self.save()

    def save(self):
        write_json(self.path / "receipt.json", self.receipt)

    def rel(self, path):
        return str(Path(path).relative_to(ROOT))

    def command(self, argv, cwd=ROOT, timeout=3600, expect=0):
        number = len(self.commands)
        base = self.path / f"command-{number:04d}"
        record = {"argv": [str(a) for a in argv], "cwd": self.rel(cwd),
                  "started_at": now(), "timeout_s": timeout,
                  "stdout": self.rel(base.with_suffix(".stdout")),
                  "stderr": self.rel(base.with_suffix(".stderr"))}
        self.commands.append(record)
        self.save()
        with base.with_suffix(".stdout").open("w") as out, base.with_suffix(".stderr").open("w") as err:
            try:
                result = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err,
                                        timeout=timeout, check=False)
                record.update(exit=result.returncode, timeout=False)
            except subprocess.TimeoutExpired:
                record.update(exit=None, timeout=True)
            except OSError as exc:
                record.update(exit=None, timeout=False, error=str(exc))
        record["ended_at"] = now()
        self.save()
        text = base.with_suffix(".stdout").read_text()
        errors = base.with_suffix(".stderr").read_text()
        if record.get("exit") is None or (expect is not None and record["exit"] != expect):
            raise AssertionError(f"tool execution failed: {record}; {text[-1600:]} {errors[-1600:]}")
        return text, errors, record

    def prerequisites(self, names):
        versions = {}
        for name in sorted(set(names)):
            if shutil.which(name) is None:
                raise AssertionError(f"MISSING PREREQUISITE: {name}; tools are not installed by L1")
            args = [name, "-V"] if name in ("iverilog", "vvp") else [name, "--version"]
            if name == "yosys":
                args = [name, "-V"]
            text, err, rec = self.command(args)
            versions[name] = {"version": (text + err).splitlines()[:3],
                              "command": self.commands.index(rec)}
        self.receipt["tool_versions"] = versions
        self.save()


def prepare_parent(folder):
    source = (ROOT / "furnace_x1_reference/rtl/furnace_x1_top.sv").read_text()
    renamed = source.replace("module furnace_x1_top", "module parent_x1_top", 1)
    if source == renamed:
        raise AssertionError("parent module name not found")
    (folder / "parent_x1_top.sv").write_text(renamed)
    for p in (ROOT / "furnace_x1_reference/rtl").glob("*.sv"):
        assert p.read_bytes() == (ROOT / "rtl" / p.name).read_bytes(), f"parent copy changed: {p.name}"


def compile_sim(run, folder, backend, width=None, kind="top", rtl=None):
    folder.mkdir(parents=True, exist_ok=True)
    bench = top_bench(width) if kind == "top" else leaf_bench(kind)
    (folder / "tb.sv").write_text(bench)
    source_root = ROOT / "rtl" if rtl is None else rtl
    sources = sorted(source_root.glob("*.sv")) if kind == "top" else [
        source_root / ("furnace_rss_toeplitz.sv" if kind == "rss" else "furnace_classifier64.sv")]
    if kind == "top":
        prepare_parent(folder)
        sources.append(folder / "parent_x1_top.sv")
    argv = [run.rel(folder / "tb.sv"), *[run.rel(p) for p in sources]]
    if backend == "icarus":
        run.command(["iverilog", "-g2012", "-Wall", "-Wno-timescale", "-s", "tb",
                     "-o", run.rel(folder / "sim"), *argv])
        return ["vvp", "sim"]
    run.command(["verilator", "--binary", "--timing", "-Wno-fatal", "--top-module", "tb",
                 "-j", "2", "--Mdir", run.rel(folder / "obj"), "-o", "sim", *argv])
    return ["obj/sim"]


def parse_top_output(text, records, full=False, sample=False):
    completed, aborted = set(), set()
    coverage = Counter()
    for line in text.splitlines():
        if line.startswith("DONE "):
            words = line.split()
            ident, count = map(int, words[1:3])
            if ident in completed or ident not in records:
                raise AssertionError(f"duplicate/unissued packet: {line}")
            rec = records[ident]
            got = ([int(x, 16) for x in words[3:6]] + [int(words[6])] +
                   [int(words[7], 16)] + [int(x) for x in words[8:11]] +
                   [int(words[11], 16)])
            expected = [rec[k] for k in ("crc32", "crc64", "header", "length", "hash",
                                         "rss", "hit", "index", "action")]
            assert got == expected and count == rec["beats"], f"record mismatch: {line}"
            assert not rec["abort"]
            completed.add(ident)
            coverage.update(rec["labels"])
            coverage["compared_packets"] += 1
            coverage["compared_beats"] += count
            coverage["rss_eligible" if rec["rss"] else "rss_ineligible"] += 1
            if rec["fields"].get("error"):
                coverage["parse_error"] += 1
        elif line.startswith("ABORT "):
            ident, kind, sent, received = map(int, line.split()[1:])
            assert ident in records and ident not in aborted and records[ident]["abort"] == kind
            assert sent > 0 and received <= sent
            aborted.add(ident)
            coverage[f"reset_observed_{kind}"] += 1
        elif line.startswith("COUNTS "):
            values = list(map(int, line.split()[1:]))
            names = ("packets", "beats", "payload_stall_cycles", "crc_stall_cycles",
                     "meta_stall_cycles", "simultaneous_terminal", "resets", "configs")
            coverage.update(dict(zip(names, values)))
        elif (line.startswith("- ") or re.fullmatch(r".*tb\.sv:\d+: \$finish called at \d+ \(.+\)", line)
              or not line.strip()):
            pass
        else:
            raise AssertionError(f"unexpected simulator diagnostic: {line}")
    assert completed == {i for i, r in records.items() if not r["abort"]}, "missing completed packets"
    assert aborted == {i for i, r in records.items() if r["abort"]}, "missing reset-aborted packets"
    assert coverage["packets"] == len(completed) > 0
    for k in ("payload_stall_cycles", "crc_stall_cycles", "meta_stall_cycles", "simultaneous_terminal"):
        assert coverage[k] > 0, f"unobserved channel event: {k}"
    if full:
        assert coverage["seeded"] >= 1024
        for i in range(64):
            assert coverage[f"winner_{i}"] >= 1
        for a in range(64):
            for b in range(a + 1, 64):
                assert coverage[f"pair_{a}_{b}"] >= 1
        for k in ("default", "wildcard", "disabled", "malformed_final", "malformed_nonfinal"):
            assert coverage[k] >= 1, f"uncovered {k}"
        for kind in (1, 2, 3):
            assert coverage[f"reset_observed_{kind}"] >= 1
            assert coverage[f"reset_recovery_{kind}"] >= 1
        assert coverage["rss_eligible"] > 0 and coverage["rss_ineligible"] > 0
        assert coverage["truncated"] > 100
    if sample:
        assert coverage["seeded"] >= 128
        assert len(completed) - coverage["seeded"] >= 32
    return dict(coverage)


def top_run(run, width, backend, seed=17, full=False, sample=False, rtl=None, probe=False):
    folder = run.path / f"{backend}-{width}"
    folder.mkdir()
    campaign = Campaign(width, seed, folder / "stimulus.txt")
    smoke(campaign)
    if full or sample:
        directed(campaign, pairs=full)
        seeded(campaign, 1024 if full else 128)
    elif probe:
        # A bounded advisory smoke uses exactly the ordinary smoke checker.
        pass
    campaign.close()
    write_json(folder / "expected.json", campaign.records)
    executable = compile_sim(run, folder, backend, width=width, rtl=rtl)
    text, _, _ = run.command(executable, cwd=folder, timeout=600 if backend == "icarus" else 3600)
    counters = parse_top_output(text, campaign.records, full=full, sample=sample)
    if full:
        for n in range(width // 8 + 1):
            assert counters.get(f"keep_{n}", 0) >= 1
        for n in (0, 1, 255, 256, 257, 9215, 9216, 9217):
            assert counters.get(f"length_{n}", 0) >= 1
        for ihl in range(5, 16):
            assert counters.get(f"ihl_{ihl}", 0) >= 1
    write_json(folder / "coverage.json", counters)
    return counters


def leaf_run(run, kind, seed, suffix=""):
    folder = run.path / (kind + suffix)
    folder.mkdir()
    expected = (rss_vectors(folder / "stimulus.txt", seed) if kind == "rss" else
                classifier_vectors(folder / "stimulus.txt"))
    executable = compile_sim(run, folder, "verilator", kind=kind)
    text, _, _ = run.command(executable, cwd=folder)
    actual = []
    count = None
    for line in text.splitlines():
        if line.startswith("LEAF "):
            parts = line.split()
            assert int(parts[1]) == len(actual)
            actual.append((int(parts[2], 16), int(parts[3])) if kind == "rss" else
                          (int(parts[2]), int(parts[3]), int(parts[4], 16)))
        elif line.startswith("LEAF_COUNT "):
            count = int(line.split()[1])
        elif line.startswith("- ") or not line.strip():
            pass
        else:
            raise AssertionError(f"unexpected leaf diagnostic: {line}")
    assert actual == expected and count == len(expected) > 0
    result = {"compared": count, "kind": kind, "seed": seed,
              "threshold": 1056 if kind == "rss" else 3073}
    assert count >= result["threshold"]
    write_json(folder / "coverage.json", result)
    return result


def illegal_parameters(run):
    results = []
    for width in (-1, 0, 8, 32, 128, 1024):
        folder = run.path / f"illegal-{width}"
        folder.mkdir()
        (folder / "tb.sv").write_text(
            f"module tb; furnace_x2_top #(.DATA_WIDTH({width})) dut(); "
            "initial begin #20; $fatal(1,\"MISSING PARAMETER ERROR\"); end endmodule\n")
        run.command(["iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
                     run.rel(folder / "sim"), run.rel(folder / "tb.sv"),
                     *[run.rel(p) for p in sorted((ROOT / "rtl").glob("*.sv"))]])
        text, _, rec = run.command(["vvp", "sim"], cwd=folder, expect=None)
        assert rec["exit"] != 0 and "PARAMETER ERROR: DATA_WIDTH" in text
        assert "MISSING PARAMETER ERROR" not in text
        results.append({"width": width, "compiled": True, "explicit_rejection": True})
    return results


def synthesis(run):
    raise NotImplementedError("synthesis implementation is not yet complete")


def defects(run):
    raise NotImplementedError("mutation implementation is not yet complete")


def portability(run):
    stage = run.path / "package"
    stage.mkdir()
    for source in selected():
        dest = stage / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    # This subprocess resolves ROOT within the staged package, not the original.
    command = ["python3", "tests/verify.py", "--mode", "reproduction",
               "--out", "evidence/reproduction"]
    run.command(command, cwd=stage)
    receipts = list(stage.glob("evidence/reproduction/run-*/receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["outcome"] == "passed"
    assert receipt["source_sha256"] == run.receipt["source_sha256"]
    return {"package_receipt": run.rel(receipts[0]), "sources": len(selected())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="all", choices=(
        "all", "smoke", "behavior", "defects", "synthesis", "portability", "reproduction"))
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", default="evidence/l1/full")
    parser.add_argument("--probe", action="store_true", help="advisory bounded development execution")
    parser.add_argument("--repair-of", help="project-relative preserved prior failure receipt")
    args = parser.parse_args()
    if Path(args.out).is_absolute() or ".." in Path(args.out).parts:
        parser.error("--out must be a project-relative child directory")
    run = Run(args.out, args.mode, args.repair_of)
    try:
        tools = ["python3"]
        if args.mode in ("all", "smoke", "portability", "reproduction"):
            tools += ["iverilog", "vvp"]
        if args.mode in ("all", "behavior", "defects", "portability", "reproduction"):
            tools += ["verilator", "c++", "make"]
        if args.mode in ("all", "synthesis"):
            tools += ["yosys"]
        run.prerequisites(tools)
        self_check()
        results = {}
        if args.mode in ("all", "smoke", "reproduction"):
            for width in (64, 512):
                results[f"smoke-{width}"] = top_run(run, width, "icarus")
            results["illegal_parameters"] = illegal_parameters(run)
        if args.mode in ("all", "behavior", "reproduction"):
            seeds = (17, 43, 89) if args.mode == "all" else (args.seed,)
            for seed in seeds:
                for width in (64, 512):
                    # Names are unique even for the no-argument full invocation.
                    sub = run.path / f"seed-{seed}-{width}"
                    sub.mkdir()
                    original = run.path
                    run.path = sub
                    try:
                        results[f"behavior-{seed}-{width}"] = top_run(
                            run, width, "verilator", seed,
                            full=args.mode != "reproduction", sample=args.mode == "reproduction")
                        if args.mode != "reproduction":
                            results[f"rss-{seed}-{width}"] = leaf_run(run, "rss", seed)
                            results[f"classifier-{seed}-{width}"] = leaf_run(run, "classifier", seed)
                    finally:
                        run.path = original
        if args.mode in ("all", "defects"):
            results["defects"] = defects(run)
        if args.mode in ("all", "synthesis"):
            results["synthesis"] = synthesis(run)
        if args.mode in ("all", "portability"):
            results["portability"] = portability(run)
        run.receipt.update(outcome="passed", results=results)
    except Exception as exc:
        run.receipt.update(outcome="failed", failure=f"{type(exc).__name__}: {exc}")
        print(run.receipt["failure"], file=sys.stderr)
    finally:
        run.receipt["ended_at"] = now()
        run.save()
    print(json.dumps({"outcome": run.receipt["outcome"], "receipt": run.rel(run.path / "receipt.json")}))
    return 0 if run.receipt["outcome"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
