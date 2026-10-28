#!/usr/bin/env python3
"""Portable L1 acceptance. Native target timing/hardware gates belong to the runtime.

Mapping: smoke -> reset, parent, CRC, latency and independent channel consumption;
behavior -> full seeded packet oracle plus directed rule/parser/boundary coverage;
defects -> separately compiled observable mutants; synthesis -> real retained
hierarchy/memory/state and mapped no-latch/no-divide assertions; portability ->
fresh source-only package executing the same smoke/oracle and compiled samples.
All modes are mandatory; --probe is an advisory, bounded development diagnostic.
Receipts stay at the invocation root even while commands use partition folders.
Exclusive sibling registrations detect whole-run loss on later invocations of
the same output root; completion seals bind finished receipts. These are local
detection safeguards, not backups, authenticated storage or historical recovery.
Explicit repair links must name a retained failed receipt with intact artifacts;
their receipt hash is bound before execution and rechecked at completion.
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
        self.receipt_path = self.path / "receipt.json"
        self.commands = []
        self.receipt = {
            "schema": 1, "mode": mode, "started_at": now(), "cwd": ".",
            "argv": ["python3", "tests/verify.py", *sys.argv[1:]],
            "commands": self.commands, "source_sha256": {}, "repair_of": repair_of,
            "acceptance_evidence": ("preparation" not in self.path.relative_to(ROOT).parts
                                    and "--probe" not in sys.argv)}
        for src in selected():
            relative = src.relative_to(ROOT)
            self.receipt["source_sha256"][str(relative)] = digest(src)
            dst = self.path / "source" / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        self.save()
        self.catalog = self.path.parent / "retention"
        self.catalog.mkdir(exist_ok=True)
        self.registration_path = self.catalog / (self.path.name + ".json")
        self.registration = {
            "schema": 1, "registered_at": now(),
            "receipt": self.rel(self.receipt_path),
            "source_sha256": dict(self.receipt["source_sha256"])}
        with self.registration_path.open("x") as output:
            output.write(json.dumps(self.registration, indent=2, sort_keys=True) + "\n")

    def save(self):
        write_json(self.receipt_path, self.receipt)

    @staticmethod
    def verify_artifacts(receipt_path, receipt):
        for relative, expected in receipt["source_sha256"].items():
            snapshot = receipt_path.parent / "source" / relative
            assert snapshot.is_file(), f"missing source snapshot: {relative}"
            assert digest(snapshot) == expected, f"changed source snapshot: {relative}"
        for record in receipt["commands"]:
            # A different invocation may still be running a command. Its
            # completed journals are checked on the next audit as well.
            if "ended_at" not in record:
                continue
            for stream in ("stdout", "stderr"):
                artifact = ROOT / record[stream]
                assert artifact.is_file(), f"missing retained log: {record[stream]}"
                assert digest(artifact) == record[stream + "_sha256"], (
                    f"changed retained log: {record[stream]}")
            journal = ROOT / record["journal"]
            assert journal.is_file(), f"missing command journal: {record['journal']}"
            assert json.loads(journal.read_text()) == record, (
                f"changed command journal: {record['journal']}")

    def verify_repair_reference(self):
        reference = self.receipt["repair_of"]
        if reference is None:
            return
        relative = Path(reference)
        assert not relative.is_absolute() and ".." not in relative.parts, (
            "repair reference must be project-relative")
        path = ROOT / relative
        assert path.resolve().is_relative_to(ROOT.resolve()), (
            "repair reference escapes project")
        assert path.is_file(), f"missing repair reference receipt: {reference}"
        original = json.loads(path.read_text())
        assert original.get("outcome") == "failed" and original.get("ended_at"), (
            f"repair reference is not a completed failure: {reference}")
        assert all("ended_at" in command for command in original["commands"]), (
            f"repair reference has unfinished commands: {reference}")
        binding = {"receipt": str(relative), "receipt_sha256": digest(path)}
        if "repair_reference" in self.receipt:
            assert self.receipt["repair_reference"] == binding, (
                f"changed repair reference receipt: {reference}")
        self.verify_artifacts(path, original)
        self.receipt["repair_reference"] = binding
        self.save()

    def verify_history(self):
        self.verify_repair_reference()
        assert self.registration_path.is_file(), "missing invocation registration"
        assert json.loads(self.registration_path.read_text()) == self.registration, (
            "changed invocation registration")
        for path in sorted(self.catalog.glob("run-*.json")):
            if path.name.endswith(".complete.json"):
                continue
            registration = json.loads(path.read_text())
            receipt_path = ROOT / registration["receipt"]
            assert receipt_path.is_file(), (
                f"missing registered invocation receipt: {registration['receipt']}")
            receipt = json.loads(receipt_path.read_text())
            assert receipt["source_sha256"] == registration["source_sha256"], (
                f"changed registered source identity: {registration['receipt']}")
            seal_path = path.with_suffix(".complete.json")
            if seal_path.exists():
                seal = json.loads(seal_path.read_text())
                assert seal["receipt"] == registration["receipt"]
                assert seal["receipt_sha256"] == digest(receipt_path), (
                    f"changed completed receipt: {registration['receipt']}")
            self.verify_artifacts(receipt_path, receipt)

    def verify_retention(self):
        self.verify_history()
        assert all("ended_at" in record for record in self.commands), (
            "unfinished command at invocation completion")
        self.verify_artifacts(self.receipt_path, self.receipt)

    def finish(self):
        self.receipt["ended_at"] = now()
        self.save()
        seal = {"schema": 1, "sealed_at": now(),
                "receipt": self.rel(self.receipt_path),
                "receipt_sha256": digest(self.receipt_path)}
        with self.registration_path.with_suffix(".complete.json").open("x") as output:
            output.write(json.dumps(seal, indent=2, sort_keys=True) + "\n")

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
        for stream in ("stdout", "stderr"):
            record[stream + "_sha256"] = digest(ROOT / record[stream])
        journal = base.with_suffix(".json")
        record["journal"] = self.rel(journal)
        with journal.open("x") as output:
            output.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
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
    parents = sorted((ROOT / "furnace_x1_reference/rtl").glob("*.sv"))
    assert len(parents) == 6
    names = {p.stem: "parent_" + p.stem for p in parents}
    names["furnace_x1_top"] = "parent_x1_top"
    pieces = []
    for p in parents:
        assert p.read_bytes() == (ROOT / "rtl" / p.name).read_bytes(), f"parent copy changed: {p.name}"
        pieces.append(re.sub(r"\b(" + "|".join(names) + r")\b",
                             lambda match: names[match.group()], p.read_text()))
    (folder / "parent_x1_top.sv").write_text("\n".join(pieces))


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
    # PCH use is optional; some GCC/Verilator combinations reject the generated
    # .fast.gch without a fallback header. Compile the ordinary includes instead.
    run.command(["verilator", "--binary", "--timing", "-Wno-fatal", "--top-module", "tb",
                 "-j", "2", "-MAKEFLAGS", "VK_PCH_I_FAST= VK_PCH_I_SLOW=",
                 "--Mdir", run.rel(folder / "obj"), "-o", "sim", *argv])
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
            for label in rec["labels"]:
                if label.startswith("winner_"):
                    winner = int(label.split("_")[1])
                    assert rec["matching_rules"] == [winner] and rec["index"] == winner and rec["hit"]
                elif label.startswith("pair_"):
                    a, b = map(int, label.split("_")[1:])
                    assert rec["matching_rules"] == [a, b] and rec["index"] == a and rec["hit"]
            completed.add(ident)
            coverage.update(rec["labels"])
            coverage["compared_packets"] += 1
            coverage["compared_beats"] += count
            coverage["rss_eligible" if rec["rss"] else "rss_ineligible"] += 1
            if rec["fields"].get("error"):
                coverage["parse_error"] += 1
            else:
                fields = rec["fields"]
                for name in ("ip", "l4", "fragment", "unsupported"):
                    coverage[f"observed_{name}"] += int(bool(fields.get(name)))
                if fields.get("ip"):
                    coverage[f"observed_ipv{fields['version']}"] += 1
                    coverage[f"observed_protocol_{fields['proto']}"] += 1
                coverage[f"observed_vlans_{fields.get('vlans', 0)}"] += 1
        elif line.startswith("ABORT "):
            ident, kind, sent, received = map(int, line.split()[1:])
            assert ident in records and ident not in aborted and records[ident]["abort"] == kind
            assert sent > 0 and received <= sent
            aborted.add(ident)
            coverage[f"reset_observed_{kind}"] += 1
        elif line.startswith("COUNTS "):
            values = list(map(int, line.split()[1:]))
            names = ("packets", "beats", "payload_stall_cycles", "crc_stall_cycles",
                     "meta_stall_cycles", "simultaneous_terminal", "resets", "configs",
                     "ingress_bubbles", "deferred_configs", "priority_configs")
            assert len(values) == len(names), "malformed public-event counters"
            coverage.update(dict(zip(names, values)))
        elif (line.startswith("- ") or re.fullmatch(r".*tb\.sv:\d+: \$finish called at \d+ \(.+\)", line)
              or not line.strip()):
            pass
        else:
            raise AssertionError(f"unexpected simulator diagnostic: {line}")
    assert completed == {i for i, r in records.items() if not r["abort"]}, "missing completed packets"
    assert aborted == {i for i, r in records.items() if r["abort"]}, "missing reset-aborted packets"
    assert coverage["packets"] == len(completed) > 0
    assert coverage["priority_configs"] == len(records)
    for k in ("payload_stall_cycles", "crc_stall_cycles", "meta_stall_cycles", "simultaneous_terminal"):
        assert coverage[k] > 0, f"unobserved channel event: {k}"
    if full:
        assert coverage["ingress_bubbles"] > 0
        assert coverage["seeded"] >= 1024
        for i in range(64):
            assert coverage[f"winner_{i}"] >= 1
        for a in range(64):
            for b in range(a + 1, 64):
                assert coverage[f"pair_{a}_{b}"] >= 1
        for k in ("default", "wildcard", "disabled", "malformed_final", "malformed_nonfinal"):
            assert coverage[k] >= 1, f"uncovered {k}"
        required = (
            "capture_exceeded", "ah_invalid_length", "ipv4_reserved_fragment",
            "udp_first_fragment_long", "bad_version", "bad_ihl", "total_under_ihl",
            "total_truncated", "ipv6_bad_version", "ipv6_jumbogram", "third_vlan", "non_ip",
            "observed_ip", "observed_l4", "observed_fragment", "observed_unsupported",
            "observed_ipv4", "observed_ipv6", "observed_protocol_6", "observed_protocol_17")
        for k in required:
            assert coverage[k] >= 1, f"uncovered {k}"
        assert coverage["deferred_configs"] >= 5
        for op in range(4):
            assert coverage[f"atomicity_{op}"] >= 1
            assert coverage[f"atomicity_following_{op}"] >= 1
        for n in range(3):
            assert coverage[f"observed_vlans_{n}"] >= 1
        for kind in (0, 43, 60, 44, 51):
            for n in (1, 8, 9):
                assert coverage[f"ext_{kind}_{n}"] >= 1
        for n in (0, 1, 8, 9):
            assert coverage[f"extensions_{n}"] >= 1
        for v, fragment in ((4, 0x2000), (4, 1), (6, 1), (6, 8), (6, 0)):
            assert coverage[f"fragment_{v}_{fragment}"] >= 1
        for n in (0, 4, 5, 6, 15):
            assert coverage[f"tcp_offset_{n}"] >= 1
        for n in (0, 7, 8, 20, 22, 400):
            assert coverage[f"udp_length_{n}"] >= 1
        for v in (4, 6):
            for proto in (1, 50, 59, 132):
                assert coverage[f"protocol_{v}_{proto}"] >= 1
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
        for boundary in range(width // 8, width // 2 + 1, width // 8):
            for n in (boundary - 1, boundary, boundary + 1):
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
    if kind == "classifier":
        assert count == 512 * 6 + 1
        result.update(compared_walking_one_bits=512, compared_walking_zero_bits=512,
                      compared_care_mask_bits=512, compared_ignore_mask_bits=512)
    else:
        assert count == 104 + 296 + 328 * 2 + 5
        assert actual[-3] == (0x51ccc178, 1)
        result.update(compared_ipv4_tuple_bits=104, compared_ipv6_tuple_bits=296,
                      compared_key_bits_per_tuple=328, four_tuple_zero_protocol=True,
                      nonzero_protocol_cases=2)
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
        text, _, rec = run.command(["vvp", "sim"], cwd=folder, timeout=600, expect=None)
        assert rec["exit"] != 0 and "PARAMETER ERROR: DATA_WIDTH" in text, (
            f"DATA_WIDTH={width}: explicit parameter diagnostic not observed; "
            f"actual exit={rec['exit']}, stdout={rec['stdout']}")
        assert "MISSING PARAMETER ERROR" not in text, f"DATA_WIDTH={width}: missing RTL diagnostic"
        results.append({"width": width, "compiled": True, "explicit_rejection": True})
    return results


def synthesis(run, probe=False):
    results = {}
    for width in ((64,) if probe else (64, 512)):
        folder = run.path / f"yosys-{width}"
        folder.mkdir()
        source_args = " ".join(run.rel(p) for p in sorted((ROOT / "rtl").glob("*.sv")))
        before, mapped = folder / "structure.json", folder / "mapped.json"
        flattened = folder / "flattened.json"
        script = (
            f"read_verilog -sv {source_args}\n"
            f"hierarchy -check -top furnace_x2_top -chparam DATA_WIDTH {width}\n"
            "proc; opt_expr; opt_clean; check -assert\n"
            "memory -nomap; opt_clean; check -assert\n"
            f"write_json {run.rel(before)}\nstat\n"
            "techmap; opt -fast; check -assert\n"
            f"write_json {run.rel(mapped)}\nstat\n"
            "flatten; opt_clean; check -assert\n"
            f"write_json {run.rel(flattened)}\nstat\n")
        (folder / "synthesis.ys").write_text(script)
        run.command(["yosys", "-s", run.rel(folder / "synthesis.ys")])
        netlists = [json.loads(p.read_text())["modules"] for p in (before, mapped)]
        for modules in netlists:
            assert "furnace_x2_top" in modules
            for name, module in modules.items():
                assert int(module.get("attributes", {}).get("blackbox", "0"), 2) == 0, name
                for cell in module.get("cells", {}).values():
                    typ = cell["type"]
                    assert not re.search(r"(?i)(dlatch|\$div|\$mod|\$divfloor|\$modfloor)", typ), typ
                    assert typ.startswith("$") or typ in modules, f"unresolved module: {typ}"
            # Every required block must survive as a connected, substantive block.
            top = modules["furnace_x2_top"]
            majors = {}
            for instance in ("crc_core", "parser", "rss", "classifier"):
                found = [c for n, c in top["cells"].items() if n.split(".")[-1] == instance]
                assert len(found) == 1, (width, instance)
                cell = found[0]
                module = modules[cell["type"]]
                assert len(module.get("cells", {})) > 0, f"empty block: {instance}"
                outputs = [c for p, c in cell["connections"].items()
                           if cell["port_directions"].get(p) == "output"]
                assert outputs and any(isinstance(b, int) for c in outputs for b in c)
                used = Counter(b for c in top["cells"].values()
                               for p, bits in c["connections"].items()
                               if c["port_directions"].get(p) == "input"
                               for b in bits if isinstance(b, int))
                used.update(b for p in top["ports"].values() if p["direction"] == "output"
                            for b in p["bits"] if isinstance(b, int))
                assert any(used[b] for c in outputs for b in c if isinstance(b, int)), instance
                majors[instance] = module
            crc = majors["crc_core"]
            for instance in ("beat_pipeline", "packet_accumulator", "tail_pipeline", "output_stage"):
                assert any(n.split(".")[-1] == instance for n in crc["cells"]), instance
            assert any("furnace_crc_linear" in n for n in modules)
            classifier = majors["classifier"]
            memory_cells = [c for c in classifier["cells"].values() if c["type"] == "$mem_v2"]
            memories = [{"width": int(c["parameters"]["WIDTH"], 2),
                         "size": int(c["parameters"]["SIZE"], 2)} for c in memory_cells]
            assert sum(x["width"] * x["size"] for x in memories) >= 64 * (512 * 2 + 32)
            assert sum(x["width"] == 512 and x["size"] == 64 for x in memories) >= 2
            assert any(x["width"] == 32 and x["size"] == 64 for x in memories)
            state_cells = [c for m in modules.values() for c in m.get("cells", {}).values()
                           if re.search(r"(?i)dff", c["type"])]
            assert len(state_cells) > 0, "no retained state"
        flat = json.loads(flattened.read_text())["modules"]["furnace_x2_top"]
        flat_types = Counter(c["type"] for c in flat["cells"].values())
        assert all(t.startswith("$") for t in flat_types), "unresolved mapped hierarchy"
        assert not any(re.search(r"(?i)(dlatch|\$div|\$mod)", t) for t in flat_types)
        assert any("DFF" in t.upper() for t in flat_types)
        assert sum(t == "$mem_v2" for t in flat_types) >= 1
        stats = {"width": width, "hierarchy_modules": len(netlists[0]),
                 "mapped_modules": len(netlists[1]),
                 "mapped_cell_types": dict(Counter(c["type"] for m in netlists[1].values()
                                                   for c in m.get("cells", {}).values())),
                 "flattened_cell_types": dict(flat_types),
                 "classifier_memory": memories, "retained_state_cells": len(state_cells),
                 "latches": 0, "division_or_remainder": 0}
        write_json(folder / "assertions.json", stats)
        results[str(width)] = stats
    return results


def defects(run, probe=False):
    # One local semantic edit per disposable source copy. A build or timeout is
    # not a kill: each compiled binary must reach the ordinary numerical checker.
    mutants = [
        ("crc-polynomial", "furnace_crc_linear.sv",
         "state = (state >> 1) ^ POLYNOMIAL;",
         "state = (state >> 1) ^ (POLYNOMIAL ^ 1);", "CRC_MISMATCH"),
        ("parser-endian", "furnace_header_parser.sv",
         "nh[31:0]={header[23:0],octet};", "nh[31:0]={octet,header[31:8]};", "META_MISMATCH"),
        ("transport-offset", "furnace_header_parser.sv",
         "if (rel+17'd1==header_len) begin", "if (rel+17'd2==header_len) begin", "META_MISMATCH"),
        ("fragment-eligibility", "furnace_header_parser.sv",
         "!final_header[302] && !final_header[441]", "1'b1 && !final_header[441]", "META_MISMATCH"),
        ("rss-key-direction", "furnace_rss_toeplitz.sv",
         "key_shift[327:296]", "key_shift[31:0]", "META_MISMATCH"),
        ("rss-tuple-direction", "furnace_rss_toeplitz.sv",
         "tuple_shift[295]", "tuple_shift[0]", "META_MISMATCH"),
        ("mask-polarity", "furnace_classifier64.sv",
         "mask_q[63:0])", "~mask_q[63:0])", "META_MISMATCH"),
        ("priority-reversed", "furnace_classifier64.sv",
         "!found && enable_q && equal_q", "enable_q && equal_q", "META_MISMATCH"),
        ("metadata-dropped", "furnace_x2_top.sv",
         "meta_valid<=1;", "meta_valid<=0;", "LOST_RESULT"),
        ("metadata-unstable", "furnace_x2_top.sv",
         "if (meta_terminal) begin meta_done<=1; meta_valid<=0; end",
         "if (meta_valid && !m_meta_ready) meta_header<=meta_header ^ 512'b1;\n"
         "                if (meta_terminal) begin meta_done<=1; meta_valid<=0; end", "UNSTABLE_META"),
    ]
    if probe:
        mutants = [m for m in mutants if m[0] in ("crc-polynomial", "metadata-unstable")]
    results = []
    for name, filename, old, new, marker in mutants:
        folder = run.path / name
        folder.mkdir()
        rtl = folder / "rtl"
        rtl.mkdir()
        patches = []
        for p in sorted((ROOT / "rtl").glob("*.sv")):
            original = p.read_text()
            text = original
            if p.name == filename:
                assert old in original, f"mutation anchor absent: {name}"
                # The offset mutant deliberately changes the IPv4 boundary only.
                text = original.replace(old, new, 1)
                patches.extend(difflib.unified_diff(
                    original.splitlines(True), text.splitlines(True),
                    fromfile="rtl/" + p.name, tofile="mutant/rtl/" + p.name))
            (rtl / p.name).write_text(text)
        (folder / "mutation.patch").write_text("".join(patches))
        hashes = {p.name: digest(p) for p in sorted(rtl.glob("*.sv"))}
        sim = folder / "simulation"
        sim.mkdir()
        c = Campaign(64, 17, sim / "stimulus.txt")
        c.send(b"123456789", ["crc_known"], mode=1 if name.startswith("metadata-") else 0)
        c.config(0, 0, value=0, mask=0, action=0x100, enable=1)
        c.config(0, 63, value=0, mask=0, action=0x200, enable=1)
        c.send(packet(c.rng, version=4, proto=6), ["ipv4_tcp"], mode=1)
        c.send(packet(c.rng, version=6, proto=17), ["ipv6_udp"], mode=1)
        c.send(packet(c.rng, fragment=0x2000), ["fragment"], mode=1)
        c.close()
        write_json(folder / "expected.json", c.records)
        write_json(folder / "mutation.json", {"name": name, "source_sha256": hashes,
                                            "expected_checker": marker})
        executable = compile_sim(run, sim, "verilator", width=64, rtl=rtl)
        text, err, rec = run.command(executable, cwd=sim, expect=None)
        assert rec["exit"] != 0 and not rec["timeout"], f"surviving mutant: {name}"
        assert marker in text + err, f"wrong rejection for {name}: {text[-1600:]} {err[-1600:]}"
        assert "Error-" in text + err or "Assertion failed" in text + err
        result = {"name": name, "killed": True, "checker": marker,
                  "exit": rec["exit"], "patch": run.rel(folder / "mutation.patch"),
                  "mutant_sha256": hashes, "execution": rec}
        write_json(folder / "detected.json", result)
        results.append(result)
    assert len(results) == len(mutants) and all(r["killed"] for r in results)
    if not probe:
        assert len(results) >= 8
    return results


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
        run.verify_history()
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
                            full=args.mode != "reproduction" and not args.probe,
                            sample=args.mode == "reproduction" or args.probe)
                        if args.mode != "reproduction" and (not args.probe or width == 64):
                            results[f"rss-{seed}-{width}"] = leaf_run(run, "rss", seed)
                            results[f"classifier-{seed}-{width}"] = leaf_run(run, "classifier", seed)
                    finally:
                        run.path = original
        if args.mode in ("all", "defects"):
            results["defects"] = defects(run, probe=args.probe)
        if args.mode in ("all", "synthesis"):
            results["synthesis"] = synthesis(run, probe=args.probe)
        if args.mode in ("all", "portability"):
            results["portability"] = portability(run)
        run.verify_retention()
        run.receipt.update(outcome="passed", results=results)
    except Exception as exc:
        run.receipt.update(outcome="failed", failure=f"{type(exc).__name__}: {exc}")
        print(run.receipt["failure"], file=sys.stderr)
    finally:
        run.finish()
    print(json.dumps({"outcome": run.receipt["outcome"], "receipt": run.rel(run.path / "receipt.json")}))
    return 0 if run.receipt["outcome"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
