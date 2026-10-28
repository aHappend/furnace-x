#!/usr/bin/env python3
"""Portable FURNACE-X1 L1 verification; run from the delivered project root.

behavior: independent polynomial cross-check, six width/seed cells, public
          timing/ready/valid/reset/XZ, exact payload/result conservation,
          numerical error injection, coverage thresholds, illegal parameters.
defects:  baseline and three independently applied functional mutants at both
          widths, with explicit scoreboard rejection (not tool-failure credit).
synthesis: real Yosys lowering/synthesis/check and inspected hierarchy/netlists.
portable: fresh declared-input copy, isolated Python smoke at both widths,
          real simulation plus synthesis, strict child result inspection.
all:      all four mandatory selectors. smoke is not full acceptance.

Only Python's standard library, Icarus/vvp, Verilator and Yosys are used.
Icarus retains four-state compact startup/protocol checks. Full seeded sweeps
and disposable mutants use compiled Verilator with the same vectors and oracle;
neither simulator's successful exit substitutes for the scoreboard verdict.
X/Z sensitivity is established by Icarus, not by Verilator's two-state model.
Native timing and physical hardware gates belong to the shared runtime,
not this L1 script.
Child receipts resolve file arguments against the child's working directory,
so generated simulator inputs are bound to the files the command actually uses.
Pending receipts and log paths are retained before child execution; a running
receipt without a recorded exit is incomplete evidence, never a passing result.
Literal child arguments longer than filesystem path limits are not file inputs.
Child log hashes are captured at completion. Before recording success, every
child receipt must match its parent entry and both raw logs must still match.
Child exit policies are retained and rechecked before success, so catching an
unexpected tool failure cannot turn it into a passing run. Explicitly permitted
negative diagnostics and caller-adjudicated exits remain supported.
This guards new runs; it cannot recover evidence lost from a historical run.
Successful runs also require unchanged deliverable inputs and every retained
source snapshot to match its recorded hash; missing snapshots fail closed.
"""

import argparse
import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference import crosscheck
from scenarios import make_scenario
from scoreboard import FunctionalMismatch, check_trace, require


ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 7200
SOURCES = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md", "tests/*.py")
HIERARCHY = ("furnace_crc_beat_pipeline", "furnace_crc_packet_accumulator",
             "furnace_crc_tail_pipeline", "furnace_crc_output_stage")


TESTBENCH = r"""
`timescale 1ns/1ps
module tb;
    parameter integer DATA_WIDTH=512;
    localparam integer B=DATA_WIDTH>>3;
    reg clk, rst_n;
    reg [DATA_WIDTH-1:0] s_axis_tdata;
    reg [B-1:0] s_axis_tkeep;
    reg s_axis_tvalid, s_axis_tlast;
    wire s_axis_tready;
    reg [1:0] s_check_enable;
    reg [31:0] s_expected_crc32c;
    reg [63:0] s_expected_crc64_nvme;
    wire [DATA_WIDTH-1:0] m_axis_tdata;
    wire [B-1:0] m_axis_tkeep;
    wire m_axis_tvalid, m_axis_tlast;
    reg m_axis_tready;
    wire m_crc_valid;
    reg m_crc_ready;
    wire [31:0] m_crc32c;
    wire [63:0] m_crc64_nvme;
    wire [1:0] m_crc_mismatch;
    wire m_crc_protocol_error;
    integer vectors, trace_file, scan, cycle, pulse_reset;
    furnace_x1_top #(.DATA_WIDTH(DATA_WIDTH)) dut (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tlast(s_axis_tlast),
        .s_axis_tready(s_axis_tready), .s_check_enable(s_check_enable),
        .s_expected_crc32c(s_expected_crc32c),
        .s_expected_crc64_nvme(s_expected_crc64_nvme),
        .m_axis_tdata(m_axis_tdata), .m_axis_tkeep(m_axis_tkeep),
        .m_axis_tvalid(m_axis_tvalid), .m_axis_tlast(m_axis_tlast),
        .m_axis_tready(m_axis_tready), .m_crc_valid(m_crc_valid),
        .m_crc_ready(m_crc_ready), .m_crc32c(m_crc32c),
        .m_crc64_nvme(m_crc64_nvme), .m_crc_mismatch(m_crc_mismatch),
        .m_crc_protocol_error(m_crc_protocol_error)
    );
    task automatic observe(input [31:0] phase, input integer index);
        begin
            $fdisplay(trace_file,
                "%0s %0d %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h",
                phase, index, s_axis_tready, m_axis_tvalid,
                m_axis_tdata, m_axis_tkeep, m_axis_tlast,
                m_crc_valid, m_crc32c, m_crc64_nvme,
                m_crc_mismatch, m_crc_protocol_error,
                rst_n, s_axis_tvalid, s_axis_tdata, s_axis_tkeep, s_axis_tlast,
                s_check_enable, s_expected_crc32c, s_expected_crc64_nvme,
                m_axis_tready, m_crc_ready);
        end
    endtask
    task automatic reset_check;
        begin
            if ({s_axis_tready, m_axis_tvalid, m_axis_tdata, m_axis_tkeep,
                 m_axis_tlast, m_crc_valid, m_crc32c, m_crc64_nvme,
                 m_crc_mismatch, m_crc_protocol_error} !==
                {(DATA_WIDTH+B+103){1'b0}})
                $fatal(1, "PUBLIC RESET ASSERTION");
        end
    endtask
    initial begin
        clk=0;
        rst_n=0;
        s_axis_tdata=0; s_axis_tkeep=0; s_axis_tvalid=0; s_axis_tlast=0;
        s_check_enable=0; s_expected_crc32c=0; s_expected_crc64_nvme=0;
        m_axis_tready=0; m_crc_ready=0;
        vectors=$fopen("vectors.txt", "r");
        trace_file=$fopen("trace.txt", "w");
        if (!vectors || !trace_file) $fatal(1, "FILE OPEN FAILURE");
`ifdef VERILATOR
        #1ps;
`else
        #0;
`endif
        reset_check(); observe("T0", -1);
        #5; clk=1; reset_check(); observe("BP", -1);
        #5; clk=0; reset_check(); observe("BN", -1);
        cycle=0;
        while (!$feof(vectors)) begin
            scan=$fscanf(vectors, "%h %h %h %h %h %h %h %h %h %h %h\n",
                rst_n, s_axis_tvalid, s_axis_tdata, s_axis_tkeep,
                s_axis_tlast, s_check_enable, s_expected_crc32c,
                s_expected_crc64_nvme, m_axis_tready, m_crc_ready, pulse_reset);
            if (scan != 11) $fatal(1, "VECTOR PARSE FAILURE count=%0d", scan);
            if (pulse_reset != 0) begin
                rst_n=0;
                #1; reset_check(); observe("Q0", cycle);
                rst_n=1;
                #1; observe("Q1", cycle);
                #3;
            end else begin
                #5;
            end
            clk=1; observe("A", cycle);
            if (!rst_n) reset_check();
            #1; observe("P", cycle);
            #4; clk=0; observe("N", cycle);
            if (!rst_n) reset_check();
            cycle=cycle+1;
            if (cycle > 2000000) $fatal(1, "CYCLE PROGRESS LIMIT");
        end
        $fclose(vectors); $fclose(trace_file);
        vectors=$fopen("completion.json", "w");
        if (!vectors) $fatal(1, "COMPLETION FILE OPEN FAILURE");
        $fdisplay(vectors, "{\"simulated_cycles\":%0d}", cycle);
        $fclose(vectors);
        $finish(0);
    end
endmodule
"""


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def inventory(root=ROOT):
    files = sorted({p for pattern in SOURCES for p in root.glob(pattern)})
    for pattern in SOURCES:
        require(any(root.glob(pattern)), f"missing declared input {pattern}")
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files}


def relative_output(text):
    path = Path(text)
    require(not path.is_absolute() and bool(path.parts) and ".." not in path.parts,
            "--out must be a project-relative directory without '..'")
    require(not any(p in (".vulcan", ".git", ".tooling", "VULCAN") for p in path.parts),
            "runtime-owned paths cannot be verification outputs")
    resolved = (ROOT / path).resolve()
    require(resolved.is_relative_to(ROOT), "output escapes project through a symlink")
    return resolved


def required_runs(mode):
    modes = ("behavior", "defects", "synthesis", "portable") if mode == "all" else (mode,)
    rows = []

    def add(label, width=None, seed=None, thresholds=None, expected="pass"):
        rows.append({"label": label, "width": width, "seed": seed,
                     "required": thresholds or {}, "expected": expected,
                     "status": "not_run", "measured": None, "raw_receipt": None})

    for selected in modes:
        if selected == "behavior":
            for width in (64, 512):
                add(f"icarus-compact-{width}", width, 17)
            for width in (64, 512):
                for seed in (17, 89, 2026):
                    add(f"behavior-{width}-{seed}", width, seed,
                        {"legal_packets": 512, "enabled_bit_flip_pairs": 128,
                         "additional_random_lengths": 100, "payload_stalls": 32,
                         "result_stalls": 32, "malformed_packets": 8,
                         "zero_packets": 8, "consecutive_single_beats": 8})
        if selected in ("behavior", "smoke"):
            for width in (0, 8, 128, 1024):
                add(f"illegal-{width}", width, expected="explicit parameter rejection")
        if selected == "defects":
            for width in (64, 512):
                add(f"baseline-{width}", width, 17)
            for mutation in ("recurrence", "tail", "checking"):
                for width in (64, 512):
                    add(f"mutant-{mutation}/width-{width}", width, 17,
                        expected="functional scoreboard rejection after successful simulation")
        if selected == "smoke":
            for width in (64, 512):
                add(f"smoke-{width}", width, 17)
        if selected in ("synthesis", "smoke"):
            for width in (64, 512):
                add(f"synthesis-{width}", width, thresholds={"latches": 0, "division_modulo": 0})
        if selected == "portable":
            add("portable-reproduction", thresholds={"simulation_widths": [64, 512],
                                                    "synthesis_widths": [64, 512]})
    return rows


class Run:
    def __init__(self, output, mode, repair_of):
        output.mkdir(parents=True, exist_ok=True)
        name = "run-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        self.path = output / (name + uuid.uuid4().hex[:10])
        self.path.mkdir()
        self.commands = []
        self.simulators = {}
        self.record = {
            "schema": 1, "mode": mode, "status": "running", "start": stamp(),
            "argv": [sys.executable, *sys.argv], "cwd": str(Path.cwd()),
            "source_hashes": inventory(), "repair_of": repair_of,
            "timeout_s": TIMEOUT, "tool_versions": {}, "commands": self.commands,
            "results": {}, "stdout": "stdout.log", "stderr": "stderr.log",
            "ledger": required_runs(mode),
        }
        snapshot = self.path / "source"
        for source in self.record["source_hashes"]:
            target = snapshot / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        self.save()
        (self.path / "stdout.log").write_text("")
        (self.path / "stderr.log").write_text("")

    def save(self):
        write_json(self.path / "receipt.json", self.record)

    def track(self, label, **fields):
        row = next((row for row in self.record["ledger"] if row["label"] == label), None)
        if row is None:
            row = {"label": label, "status": "not_run", "measured": None,
                   "raw_receipt": None}
            self.record["ledger"].append(row)
        row.update(fields)
        self.save()

    def child(self, argv, cwd, *, allowed=(0,), env=None):
        cwd = Path(cwd).resolve()
        index = len(self.commands)
        folder = self.path / "commands" / f"{index:04d}"
        folder.mkdir(parents=True)
        record = {"argv": [str(a) for a in argv], "cwd": str(cwd),
                  "start": stamp(), "timeout_s": TIMEOUT,
                  "status": "running", "exit_code": None, "timeout": False,
                  "allowed_exit_codes": None if allowed is None else list(allowed),
                  "stdout": str((folder / "stdout.log").relative_to(self.path)),
                  "stderr": str((folder / "stderr.log").relative_to(self.path)),
                  "source_hashes": self.record["source_hashes"],
                  "tool_versions": dict(self.record["tool_versions"]),
                  "receipt": str((folder / "receipt.json").relative_to(self.path))}
        candidates = [Path(a) if Path(a).is_absolute() else cwd / a
                      for a in record["argv"]]
        bound_inputs = set()
        for path in candidates:
            try:
                if path.is_file():
                    bound_inputs.add(path.resolve())
            except OSError as error:
                if error.errno != errno.ENAMETOOLONG:
                    raise
        for name in ("vectors.txt", "tb.sv", "manifest.json"):
            if (Path(cwd) / name).is_file():
                bound_inputs.add(Path(cwd) / name)
        record["input_hashes"] = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(bound_inputs)}
        self.commands.append(record)
        start = time.monotonic()
        try:
            with (folder / "stdout.log").open("wb") as stdout, \
                    (folder / "stderr.log").open("wb") as stderr:
                write_json(folder / "receipt.json", record)
                self.save()
                result = subprocess.run(record["argv"], cwd=cwd, env=env,
                                        stdout=stdout, stderr=stderr,
                                        timeout=TIMEOUT, check=False)
            record.update(exit_code=result.returncode, timeout=False, status="completed")
        except subprocess.TimeoutExpired:
            record.update(exit_code=None, timeout=True, status="timed_out")
            raise RuntimeError(f"tool timeout: commands/{index:04d}/receipt.json")
        except OSError as error:
            record.update(exit_code=None, timeout=False, status="launch_failed",
                          launch_error=str(error))
            raise RuntimeError(f"tool launch failed: {argv[0]}: {error}") from error
        finally:
            record.update(end=stamp(), duration_s=time.monotonic() - start)
            record["log_hashes"] = {
                name: hashlib.sha256((self.path / record[name]).read_bytes()).hexdigest()
                for name in ("stdout", "stderr") if (self.path / record[name]).is_file()}
            write_json(folder / "receipt.json", record)
            self.save()
        if (record["allowed_exit_codes"] is not None and
                result.returncode not in record["allowed_exit_codes"]):
            raise RuntimeError(f"tool exit {result.returncode}: commands/{index:04d}/receipt.json")
        return record, (folder / "stdout.log").read_text(errors="replace"), \
            (folder / "stderr.log").read_text(errors="replace")

    def tools(self, names):
        for name in names:
            require(shutil.which(name) is not None, f"required installed tool unavailable: {name}")
            option = "-V" if name in ("iverilog", "vvp", "yosys") else "--version"
            _, stdout, stderr = self.child([name, option], ROOT)
            self.record["tool_versions"][name] = (stdout + stderr).strip()
        self.record["tool_versions"]["python3"] = sys.version
        self.save()

    def finish(self, status, error=None):
        if status == "passed":
            require(inventory() == self.record["source_hashes"],
                    "deliverable sources changed during execution")
            for name, digest in self.record["source_hashes"].items():
                snapshot = self.path / "source" / name
                require(snapshot.is_file(), f"missing source snapshot: {name}")
                require(hashlib.sha256(snapshot.read_bytes()).hexdigest() == digest,
                        f"changed source snapshot: {name}")
            for command in self.commands:
                require(command["status"] == "completed" and not command["timeout"] and
                        type(command["exit_code"]) is int,
                        f"incomplete child evidence: {command['receipt']}")
                require(command["allowed_exit_codes"] is None or
                        command["exit_code"] in command["allowed_exit_codes"],
                        f"unexpected child exit: {command['receipt']}")
                receipt = self.path / command["receipt"]
                require(receipt.is_file(), f"missing child evidence: {command['receipt']}")
                require(receipt.read_text() ==
                        json.dumps(command, indent=2, sort_keys=True) + "\n",
                        f"changed child evidence: {command['receipt']}")
                for name in ("stdout", "stderr"):
                    path = self.path / command[name]
                    require(path.is_file(), f"missing child evidence: {command[name]}")
                    require(hashlib.sha256(path.read_bytes()).hexdigest() ==
                            command["log_hashes"].get(name),
                            f"changed child evidence: {command[name]}")
        self.record.update(status=status, end=stamp(), exit_code=0 if status == "passed" else 1,
                           timeout=any(c.get("timeout") for c in self.commands))
        if error is not None:
            self.record["error"] = str(error)
            self.record["error_type"] = type(error).__name__
            for row in self.record["ledger"]:
                if row["status"] == "running":
                    row.update(status="failed", error=str(error))
                    if self.commands:
                        row["raw_receipt"] = self.commands[-1]["receipt"]
        self.record["ledger_totals"] = {
            "required_runs": len(self.record["ledger"]),
            "passed": sum(r["status"] in ("passed", "detected") for r in self.record["ledger"]),
            "failed": sum(r["status"] == "failed" for r in self.record["ledger"]),
            "not_run": sum(r["status"] == "not_run" for r in self.record["ledger"]),
        }
        if status == "passed":
            require(self.record["ledger_totals"]["passed"] ==
                    self.record["ledger_totals"]["required_runs"], "incomplete required-run ledger")
        self.save()


def simulate(run, width, seed, full, label, rtl=None, *, backend=None):
    backend = backend or ("verilator" if full else "iverilog")
    require(backend in ("iverilog", "verilator"), f"unknown simulator {backend}")
    run.track(label, status="running", width=width, seed=seed)
    directory = run.path / label
    directory.mkdir(parents=True)
    manifest = make_scenario(directory, width, seed, full)
    (directory / "tb.sv").write_text(TESTBENCH)
    rtl = ROOT / "rtl" if rtl is None else rtl
    sources = sorted(rtl.glob("*.sv"))
    require(len(sources) >= 4, "missing actual RTL sources")
    identity = (backend, width, hashlib.sha256(TESTBENCH.encode()).hexdigest(),
                tuple((p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources))
    if identity not in run.simulators:
        if backend == "iverilog":
            binary = directory / "sim.vvp"
            argv = ["iverilog", "-g2012", "-Wall", "-s", "tb",
                    "-P", f"tb.DATA_WIDTH={width}", "-o", str(binary),
                    str(directory / "tb.sv"), *map(str, sources)]
        else:
            binary = directory / "obj_dir" / "sim"
            argv = ["verilator", "--binary", "--timing", "--top-module", "tb",
                    "-Wno-fatal", f"-GDATA_WIDTH={width}", "-j", "2",
                    "--Mdir", str(binary.parent), "-o", binary.name,
                    str(directory / "tb.sv"), *map(str, sources)]
        build, _, _ = run.child(argv, ROOT)
        run.simulators[identity] = (binary, build["receipt"])
    binary, build_receipt = run.simulators[identity]
    argv = ["vvp", str(binary)] if backend == "iverilog" else [str(binary)]
    command, _, _ = run.child(argv, directory)
    try:
        simulator = json.loads((directory / "completion.json").read_text())
    except json.JSONDecodeError as error:
        raise RuntimeError("missing strict simulator completion record") from error
    require(simulator == {"simulated_cycles": manifest["cycles"]},
            "simulator did not complete exactly the generated bounded scenario")
    try:
        coverage = check_trace(directory, manifest, full)
    except FunctionalMismatch as error:
        write_json(directory / "functional_failure.json",
                   {"category": "functional", "assertion": str(error),
                    "simulation_exit_code": command["exit_code"],
                    "timeout": command["timeout"], "width": width, "seed": seed})
        run.track(label, status="failed", assertion=str(error),
                  raw_receipt=command["receipt"],
                  failure=str((directory / "functional_failure.json").relative_to(run.path)))
        raise
    coverage["simulation_receipt"] = str(
        (run.path / "commands" / f"{len(run.commands)-1:04d}" / "receipt.json").relative_to(run.path))
    coverage["simulator"] = backend
    coverage["state_model"] = "four-state" if backend == "iverilog" else "two-state"
    coverage["build_receipt"] = build_receipt
    write_json(directory / "coverage.json", coverage)
    run.track(label, status="passed", measured=coverage["measured"],
              raw_receipt=command["receipt"],
              coverage=str((directory / "coverage.json").relative_to(run.path)))
    return coverage


def illegal_parameters(run):
    results = []
    for width in (0, 8, 128, 1024):
        run.track(f"illegal-{width}", status="running")
        folder = run.path / f"illegal-{width}"
        folder.mkdir()
        binary = folder / "sim.vvp"
        run.child(["iverilog", "-g2012", "-Wall", "-s", "furnace_x1_top",
                   "-P", f"furnace_x1_top.DATA_WIDTH={width}", "-o", str(binary),
                   *map(str, sorted((ROOT / "rtl").glob("*.sv")))], ROOT)
        record, stdout, stderr = run.child(["vvp", str(binary)], ROOT, allowed=None)
        require(record["exit_code"] != 0 and "PARAMETER ERROR" in stdout + stderr,
                f"illegal DATA_WIDTH={width} lacks explicit executable diagnostic")
        results.append({"width": width, "compile": "passed", "diagnostic": "PARAMETER ERROR",
                        "simulation_exit": record["exit_code"]})
        run.track(f"illegal-{width}", status="passed", measured=results[-1],
                  raw_receipt=record["receipt"])
    return results


def behavior(run):
    result = {"reference": crosscheck(), "icarus_compact": [], "cells": []}
    run.record["results"]["behavior"] = result
    for width in (64, 512):
        result["icarus_compact"].append(
            simulate(run, width, 17, False, f"icarus-compact-{width}"))
    for width in (64, 512):
        for seed in (17, 89, 2026):
            result["cells"].append(simulate(run, width, seed, True, f"behavior-{width}-{seed}"))
            run.save()
    result["illegal_parameters"] = illegal_parameters(run)
    return result


def defects(run):
    mutations = (
        ("recurrence", "furnace_crc_packet_accumulator.sv",
         "wire [31:0] next32 = advanced32 ^ in_crc32c;",
         "wire [31:0] next32 = advanced32 ^ in_crc32c ^ 32'h1;", 1),
        ("tail", "furnace_crc_tail_pipeline.sv", ".INVERSE(1)", ".INVERSE(0)", 2),
        ("checking", "furnace_crc_output_stage.sv",
         "result_mismatch <= protocol_error ? 2'b0 : mismatches;",
         "result_mismatch <= 2'b0;", 1),
    )
    result = {"reference": crosscheck(), "baseline": [], "mutants": []}
    run.record["results"]["defects"] = result
    for width in (64, 512):
        result["baseline"].append(simulate(run, width, 17, False, f"baseline-{width}",
                                          backend="verilator"))
    for name, filename, old, new, count in mutations:
        folder = run.path / f"mutant-{name}"
        rtl = folder / "rtl"
        rtl.mkdir(parents=True)
        for source in (ROOT / "rtl").glob("*.sv"):
            shutil.copyfile(source, rtl / source.name)
        target = rtl / filename
        text = target.read_text()
        require(text.count(old) == count, f"mutation anchor no longer exact: {name}")
        target.write_text(text.replace(old, new))
        mutation = {"name": name, "file": filename, "old": old, "new": new,
                    "replacements": count, "source_hashes": {
                        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(rtl.glob("*.sv"))}, "cells": []}
        write_json(folder / "mutation.json", mutation)
        result["mutants"].append(mutation)
        for width in (64, 512):
            label = f"mutant-{name}/width-{width}"
            try:
                simulate(run, width, 17, False, label, rtl, backend="verilator")
            except FunctionalMismatch as error:
                failure = run.path / label / "functional_failure.json"
                require(failure.is_file(), "non-scoreboard failure cannot detect a mutant")
                observed = json.loads(failure.read_text())
                require(observed["simulation_exit_code"] == 0 and not observed["timeout"],
                        "build errors or timeouts cannot count as mutant detection")
                mutation["cells"].append({"width": width, "status": "rejected",
                                          "assertion": str(error),
                                          "failure": str(failure.relative_to(run.path))})
                run.track(label, status="detected",
                          measured={"functional_rejections": 1, "simulation_exit": 0},
                          failure=str(failure.relative_to(run.path)))
            else:
                raise FunctionalMismatch(f"UNDETECTED MUTANT {name} width={width}")
            write_json(folder / "mutation.json", mutation)
            run.save()
    require(len(result["mutants"]) == 3 and
            all(len(m["cells"]) == 2 for m in result["mutants"]), "mutant matrix incomplete")
    return result


def module_name(name, module):
    return module.get("attributes", {}).get("hdlname", name).split()[0].lstrip("\\")


def inspect_netlist(path, *, hierarchy):
    netlist = json.loads(path.read_text())
    modules = netlist["modules"]
    require("furnace_x1_top" in modules, "missing synthesized public top")
    top = modules["furnace_x1_top"]
    names = {name: module_name(name, module) for name, module in modules.items()}
    counts = {}
    for name, module in modules.items():
        cells = module.get("cells", {})
        for cell in cells.values():
            kind = cell["type"].lower()
            require(not any(term in kind for term in ("latch", "$div", "$mod")),
                    f"forbidden synthesis cell {name}: {kind}")
        driven = {"0", "1"}
        for port in module.get("ports", {}).values():
            if port["direction"] == "input":
                driven.update(port["bits"])
        for cell in cells.values():
            for port, direction in cell["port_directions"].items():
                if direction == "output":
                    driven.update(cell["connections"][port])
        for port_name, port in module.get("ports", {}).items():
            if port["direction"] == "output":
                require(set(port["bits"]) <= driven,
                        f"undriven output {name}.{port_name}")
                require(not any(bit in ("x", "z") for bit in port["bits"]),
                        f"unknown output {name}.{port_name}")
        counts[name] = {"identity": names[name], "cells": len(cells),
                        "sequential": sum("dff" in c["type"].lower() for c in cells.values())}
    direct = [names.get(c["type"], c["type"]) for c in top.get("cells", {}).values()]
    require(all(direct.count(name) == 1 for name in HIERARCHY),
            f"required direct functional hierarchy missing: {direct}")
    for identity in HIERARCHY:
        require(any(c["identity"] == identity and c["sequential"] > 0
                    for c in counts.values()), f"no registered state in {identity}")
    for port in ("m_crc32c", "m_crc64_nvme", "m_axis_tdata", "s_axis_tready"):
        bits = top["ports"][port]["bits"]
        require(any(isinstance(bit, int) for bit in bits), f"constant/trivial public port {port}")
    require(top["ports"]["m_crc32c"]["bits"] != top["ports"]["m_crc64_nvme"]["bits"][:32],
            "CRC outputs aliased")
    require(sum(c["sequential"] for c in counts.values()) >= 16, "trivial sequential design")
    require(sum(c["cells"] for c in counts.values()) > 100, "empty/substituted design")
    return {"status": "passed", "hierarchy_before_synthesis": hierarchy,
            "modules": counts, "latches": 0, "division_modulo": 0,
            "direct_functional_modules": direct}


def synthesis(run):
    results = []
    run.record["results"]["synthesis"] = results
    for source in (ROOT / "rtl").glob("*.sv"):
        text = re.sub(r"//[^\n]*|/\*.*?\*/", "", source.read_text(), flags=re.S)
        require("/" not in text and "%" not in text, f"division/modulo operator {source.name}")
        for match in re.finditer(r"\balways\s*@\s*\(\s*posedge[^)]*\)\s*begin\b", text):
            depth = 1
            end = None
            for token in re.finditer(r"\bbegin\b|\bend\b", text[match.end():]):
                depth += 1 if token.group() == "begin" else -1
                if depth == 0:
                    end = match.end() + token.start()
                    break
            require(end is not None, f"unterminated sequential process {source.name}")
            block = text[match.end():end]
            require(re.search(r"(?<![<>=!:])=(?!=)", block) is None,
                    f"blocking assignment in sequential process {source.name}")
    for width in (64, 512):
        run.track(f"synthesis-{width}", status="running", width=width)
        folder = run.path / f"synthesis-{width}"
        folder.mkdir()
        script = folder / "synth.ys"
        inputs = " ".join('"' + str(p) + '"' for p in sorted((ROOT / "rtl").glob("*.sv")))
        script.write_text(
            f"read_verilog -sv {inputs}\n"
            f"hierarchy -check -top furnace_x1_top -chparam DATA_WIDTH {width}\n"
            "proc\nopt\ncheck -assert\n"
            f"write_json \"{folder / 'hierarchy.json'}\"\n"
            "synth -top furnace_x1_top -noabc\ncheck -assert\n"
            f"write_json \"{folder / 'netlist.json'}\"\nstat\n")
        run.child(["yosys", "-Q", "-T", "-s", str(script)], ROOT)
        pre = inspect_netlist(folder / "hierarchy.json", hierarchy=True)
        post = inspect_netlist(folder / "netlist.json", hierarchy=False)
        result = {"width": width, "status": "passed", "pre": pre, "post": post,
                  "receipt": f"commands/{len(run.commands)-1:04d}/receipt.json"}
        write_json(folder / "structure.json", result)
        results.append(result)
        run.track(f"synthesis-{width}", status="passed",
                  measured={"latches": 0, "division_modulo": 0,
                            "functional_hierarchy_modules": len(HIERARCHY)},
                  raw_receipt=result["receipt"],
                  structure=str((folder / "structure.json").relative_to(run.path)))
        run.save()
    return results


def portable(run):
    run.track("portable-reproduction", status="running")
    isolated = Path(tempfile.mkdtemp(prefix="isolated-project-", dir=run.path))
    hashes = inventory()
    for name in hashes:
        target = isolated / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    require(inventory(isolated) == hashes, "portable copy source identity")
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    record, stdout, _ = run.child(
        ["python3", "-I", "tests/verify.py", "--mode", "smoke", "--out", "evidence/smoke"],
        isolated, env=env)
    try:
        summary = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("portable child missing machine-readable result") from error
    require(summary["status"] == "passed", "portable child reported failure")
    result_path = isolated / summary["receipt"]
    require(result_path.resolve().is_relative_to(isolated), "portable result escapes copy")
    result = json.loads(result_path.read_text())
    require(result["status"] == "passed" and result["source_hashes"] == hashes,
            "portable receipt/source identity failure")
    require({c["width"] for c in result["results"]["smoke"]["cells"]} == {64, 512},
            "portable simulation widths missing")
    require({c["width"] for c in result["results"]["synthesis"]} == {64, 512},
            "portable synthesis widths missing")
    result = {"status": "passed", "source_hashes": hashes,
              "child_exit": record["exit_code"],
              "receipt": str(result_path.relative_to(run.path)),
              "python_environment_cleared": ["PYTHONPATH", "PYTHONHOME"]}
    run.track("portable-reproduction", status="passed", raw_receipt=record["receipt"],
              measured={"simulation_widths": [64, 512], "synthesis_widths": [64, 512]},
              child_receipt=result["receipt"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "behavior", "defects", "synthesis",
                                           "portable", "smoke"), default="all")
    parser.add_argument("--out", default="evidence/l1/all")
    parser.add_argument("--repair-of", help="project-relative earlier failed advisory receipt")
    args = parser.parse_args()
    require(Path.cwd().resolve() == ROOT, "run tests/verify.py from the delivered project root")
    run = Run(relative_output(args.out), args.mode, args.repair_of)
    try:
        modes = ("behavior", "defects", "synthesis", "portable") if args.mode == "all" else (args.mode,)
        tools = set()
        if any(m in modes for m in ("behavior", "defects", "smoke", "portable")):
            tools.update(("iverilog", "vvp"))
        if any(m in modes for m in ("behavior", "defects")):
            tools.add("verilator")
        if any(m in modes for m in ("synthesis", "smoke", "portable")):
            tools.add("yosys")
        run.tools(sorted(tools))
        for mode in modes:
            if mode == "behavior":
                run.record["results"][mode] = behavior(run)
            elif mode == "defects":
                run.record["results"][mode] = defects(run)
            elif mode == "synthesis":
                synthesis(run)
            elif mode == "portable":
                run.record["results"][mode] = portable(run)
            elif mode == "smoke":
                result = {"reference": crosscheck(), "cells": []}
                run.record["results"][mode] = result
                for width in (64, 512):
                    result["cells"].append(simulate(run, width, 17, False, f"smoke-{width}"))
                result["illegal_parameters"] = illegal_parameters(run)
                synthesis(run)
            run.save()
        require(inventory() == run.record["source_hashes"], "sources changed during verification")
        run.finish("passed")
    except (AssertionError, RuntimeError, OSError, ValueError, KeyError) as error:
        (run.path / "failure.txt").write_text(traceback.format_exc())
        run.finish("failed", error)
        summary = json.dumps({"status": "failed", "error": str(error),
                              "receipt": str((run.path / "receipt.json").relative_to(ROOT))})
        (run.path / "stdout.log").write_text(summary + "\n")
        print(summary)
        return 1
    summary = json.dumps({"status": "passed",
                          "receipt": str((run.path / "receipt.json").relative_to(ROOT))})
    (run.path / "stdout.log").write_text(summary + "\n")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
