#!/usr/bin/env python3
"""Portable L1 checks. Hardware gates and product reporting belong to the runtime."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import shutil
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
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
            "commands": [], "tools": {"python3": sys.version}, "repair_of": repair_of,
        }

    def run(self, argv, name, cwd=ROOT, timeout=3600, expect_failure=False, env=None):
        argv = [str(x) for x in argv]
        stdout, stderr = self.path / f"{name}.stdout.txt", self.path / f"{name}.stderr.txt"
        record = {"argv": argv, "cwd": os.path.relpath(cwd, ROOT),
                  "start_time": time.time(), "timeout_s": timeout,
                  "stdout": str(stdout.relative_to(ROOT)),
                  "stderr": str(stderr.relative_to(ROOT))}
        self.record["commands"].append(record)
        with stdout.open("xb") as out, stderr.open("xb") as err:
            try:
                process = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err,
                                         timeout=timeout, check=False, env=env)
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
            if tool in self.record["tools"]:
                continue
            if shutil.which(tool) is None:
                raise RuntimeError(f"missing executable: {tool}")
            flag = "-V" if tool in ("iverilog", "vvp") else "--version"
            if tool == "yosys":
                flag = "-V"
            output = self.run([tool, flag], f"version-{tool}")
            self.record["tools"][tool] = output

    def finish(self, error=None):
        final_hashes = identity()
        if final_hashes != self.record["source_hashes"]:
            self.record["end_source_hashes"] = final_hashes
            error = (error + "; " if error else "") + "declared inputs changed during execution"
        self.record.update(end_time=time.time(), exit_code=1 if error else 0,
                           outcome="failed" if error else "passed", error=error,
                           timed_out=any(c.get("timed_out", False) for c in self.record["commands"]))
        (self.path / "receipt.json").write_text(json.dumps(self.record, indent=2) + "\n")
        print(f"{self.record['outcome']}: {self.path.relative_to(ROOT)}/receipt.json", flush=True)
        return error is None


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
                       expect_failure=index >= len(configs))
        if index >= len(configs):
            if "PARAMETER ERROR" not in output:
                raise AssertionError("invalid parameter failed without the explicit diagnostic")
        else:
            count = re.findall(r"STARTUP comparisons=(\d+)", output)
            if len(count) != 1 or int(count[0]) < 8:
                raise AssertionError("startup finished without all required reset edge comparisons")


def vectors(path, maximum, key=reference.DEFAULT_KEY, width=64):
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
                         f"{hash_value:x} {int(bool(tuple_bytes))} 0 {len(packet)}\n")
        packet = bytes.fromhex("a5003c")
        lanes = width >> 3
        values = []
        for bits, polynomial in ((32, 0x82F63B78), (64, 0x9A6C9329AC4BC9B5)):
            mask = (1 << bits) - 1
            state = reference.crc(packet + bytes(lanes - 3), bits, polynomial) ^ mask
            for _ in range((lanes - 2) * 8):
                low = state >> (bits - 1)
                state = (((state ^ (polynomial if low else 0)) << 1) | low) & mask
            values.append(state ^ mask)
        stream.write(f"{packet.hex()} {values[0]:x} {values[1]:x} {1 << 441:0128x} 0 0 1 2\n")
        packet = b"123456789"
        crc32, crc64 = reference.checksums(packet)
        header, _ = reference.parse(packet)
        stream.write(f"{packet.hex()} {crc32:x} {crc64:x} {header:0128x} 0 0 2 9\n")
        for mode in (3, 4):
            wire_bytes = bytearray(lanes + 1)
            if mode == 3:
                wire_bytes[0] = 0xA5
            wire_bytes[-1] = 0x57
            reported = lanes if mode == 3 else 1
            crc32, crc64 = reference.checksums(wire_bytes)
            header, _ = reference.parse(wire_bytes[:reported], malformed_keep=True)
            stream.write(f"{wire_bytes.hex()} {crc32:x} {crc64:x} {header:0128x} 0 0 {mode} {reported}\n")


def compile_sim(e, width, maximum, sg, root=ROOT, label="functional"):
    directory = e.path / f"{label}-{width}-{maximum}-{sg}-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    obj = directory / f"compile-obj-{uuid.uuid4().hex[:8]}"
    obj.mkdir()
    e.run(["verilator", "--cc", "--exe", "--build", "-j", "2",
           "-Wno-fatal", "--top-module", "furnace_x3_top",
           f"-GDATA_WIDTH={width}", f"-GMAX_PACKET_BYTES={maximum}", f"-GMAX_SG={sg}",
           "-CFLAGS", f"-DTEST_WIDTH={width} -DTEST_MAX={maximum} -DTEST_SG={sg}",
           "--Mdir", ".",
           *[os.path.relpath(p, obj) for p in sorted((root / "rtl").glob("*.sv"))],
           os.path.relpath(root / "tests/driver.cpp", obj)],
          f"{label}-{width}-{maximum}-{sg}-compile", cwd=obj)
    binary = directory / "simulator"
    shutil.copy2(obj / "Vfurnace_x3_top", binary)
    shutil.rmtree(obj)
    return binary


def functional(e, width, maximum, sg, seeds, mode="matrix", root=ROOT, label="functional"):
    try:
        binary = compile_sim(e, width, maximum, sg, root=root, label=label)
    except Exception:
        for row in e.record.get("matrix", []):
            if (row["width"], row["maximum"], row["sg"]) == (width, maximum, sg):
                row["status"] = "compilation_failed"
        raise
    corpus = binary.parent / "vectors.txt"
    vectors(corpus, maximum, width=width)
    results = []
    for seed in seeds:
        row = next((r for r in e.record.get("matrix", [])
                    if (r["width"], r["maximum"], r["sg"], r["seed"]) ==
                    (width, maximum, sg, seed)), None)
        if row is not None:
            row["status"] = "running"
        try:
            output = e.run([os.path.relpath(binary, root), os.path.relpath(corpus, root),
                            str(seed), mode], f"{label}-{width}-{maximum}-{sg}-{seed}", cwd=root)
        except Exception:
            if row is not None:
                row["status"] = "failed"
            raise
        records = [json.loads(line[7:]) for line in output.splitlines() if line.startswith("RESULT ")]
        if len(records) != 1:
            raise AssertionError("simulator did not emit exactly one structured coverage record")
        observed = records[0]
        if mode == "matrix":
            if observed["dma_successes"] < 64 or observed["legacy_packets"] < 16:
                raise AssertionError("observed successful packet thresholds not met")
            if len(observed["queue_successes"]) != 8 or min(observed["queue_successes"]) < 1:
                raise AssertionError("missing observed queue success")
            if len(observed["stall_cycles"]) != 6 or min(observed["stall_cycles"]) < 1:
                raise AssertionError("missing independent channel backpressure")
            for capacity in ([1, 3, 8, 256] if maximum == 9216 else [1, 3]):
                if observed["physical_wraps"][str(capacity)] < 2:
                    raise AssertionError("missing two actual physical wraps")
            if observed["reset_cases"] != 5:
                raise AssertionError("reset case denominator mismatch")
        if row is not None:
            row.update(status="passed", observed=observed,
                       log=str((e.path / f"{label}-{width}-{maximum}-{sg}-{seed}.stdout.txt").relative_to(ROOT)))
        results.append({"width": width, "maximum": maximum, "sg": sg, "seed": seed,
                        "mode": mode, **records[0]})
    e.record.setdefault("runs", []).extend(results)
    return results


def leaf(e, top, root=ROOT, seeds=(17,), label=None, icarus=False, width=64):
    label = label or top
    binary = e.path / f"{label}-simulator"
    sources = ["tests/credits.sv", "tests/ownership.sv", "tests/dma_contract.sv",
               "rtl/furnace_sg_dma.sv", "rtl/furnace_dma_reader.sv", "rtl/furnace_descriptor_rings.sv",
               "rtl/furnace_token_bucket8.sv",
               "rtl/furnace_drr_scheduler.sv"]
    if icarus:
        e.run(["iverilog", "-g2012", "-Wall", "-s", top, "-o",
               os.path.relpath(binary, root), *sources], f"{label}-compile", cwd=root)
    else:
        obj = e.path / f"{label}-compile-{uuid.uuid4().hex[:8]}"
        e.run(["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
               "--top-module", top, "--Mdir", os.path.relpath(obj, root),
               *([f"-GDATA_WIDTH={width}"] if top == "dma_contract_tb" else []), *sources],
              f"{label}-compile", cwd=root)
        shutil.copy2(obj / f"V{top}", binary)
        shutil.rmtree(obj)
    outputs = []
    for seed in seeds:
        argv = (["vvp"] if icarus else []) + [os.path.relpath(binary, root), f"+seed={seed}"]
        output = e.run(argv, f"{label}-{seed}", cwd=root)
        if "comparisons=" not in output:
            raise AssertionError(f"{label}: no observed numerical comparisons")
        outputs.append(output)
    return outputs


def portable(e):
    e.require(["iverilog", "vvp"])
    crc32, crc64 = reference.checksums(b"\xa5")
    for width in (64, 512):
        binary = e.path / f"portable-{width}.vvp"
        e.run(["iverilog", "-g2012", "-Wall", "-Itests", "-s", "portable_smoke",
               f"-Pportable_smoke.DATA_WIDTH={width}", "-o", binary.relative_to(ROOT),
               "tests/portable_smoke.sv", *map(str, sorted(Path("rtl").glob("*.sv")))],
              f"portable-{width}-compile")
        output = e.run(["vvp", binary.relative_to(ROOT), f"+c32={crc32:x}", f"+c64={crc64:x}"],
                       f"portable-{width}-run")
        if "PORTABLE comparisons=10 legacy=1 dma=1 reads=3" not in output:
            raise AssertionError("isolated smoke did not execute all public comparisons")


def rollover(e):
    script = e.path / "rollover.ys"
    assumptions = (
        "-set-def-inputs -set-init-def -set rst_n 1 "
        "-set db_producer 0 -set evt_queue 0 -set db_valid 0 -set retire_fire 0 "
        "-set-at 1 sequence_zero 32'hffffffff -set-at 1 pending_zero 0 "
        "-set-at 1 enabled_zero 1 -set-at 1 db_ready 1 -set-at 1 db_valid 1 "
        "-set-at 2 ctl_valid 1 -set-at 2 ctl_code 0 "
        "-set-at 2 retire_fire 1 "
    )
    script.write_text(
        "read_verilog -sv rtl/furnace_descriptor_rings.sv tests/rollover.sv\n"
        "hierarchy -check -top rollover\n"
        "proc; flatten; async2sync; opt; memory_map; opt; dffunmap\n"
        f"sat -seq 3 {assumptions} -show sequence_zero -show pending_zero -show db_ready "
        f"-dump_json {e.path.relative_to(ROOT)}/rollover-witness.json\n"
        f"sat -seq 2 {assumptions} -prove-skip 1 -prove wrapped_post 1 -verify\n"
        f"sat -seq 3 {assumptions} -prove-skip 2 -prove drained_zero 1 -verify "
        f"-dump_json {e.path.relative_to(ROOT)}/rollover-counterexample.json\n"
    )
    output = e.run(["yosys", "-s", script.relative_to(ROOT)], "ring-counter-rollover")
    if "SUCCESS" not in output or "model found" not in output:
        raise AssertionError("Yosys did not establish nonvacuity and prove the full-width ring transition")
    e.record["rollover_scope"] = (
        "Three-step nonvacuous SAT property of the actual descriptor-rings public outputs. "
        "Assume a defined arbitrary enabled/drained queue with consumer 0xffffffff, reset "
        "released, and an observed accepted forward producer doorbell to zero. The resulting "
        "one-pending-descriptor state becomes consumer zero and drained on retirement. "
        "SAT separately finds a witness satisfying every assumption. This covers the actual "
        "32-bit producer/consumer wrap transition, not reset reachability or 2^32 simulated transfers."
    )


def synthesize(e, minimum_only=False):
    e.require(["yosys"])
    results = []
    public_ports = []
    preserved_ports = {}
    configs = [("furnace_x3_top", w, m, s) for w in (64, 512)
               for m, s in ((1, 1), (65, 3), (9216, 16))]
    configs += [(top, w, None, None) for top in ("furnace_x1_top", "furnace_x2_top")
                for w in (64, 512)]
    if minimum_only:
        configs = configs[:1]
    for top, width, maximum, sg in configs:
        name = f"{top}-{width}-{maximum}-{sg}"
        netlist = e.path / f"{name}.json"
        script = e.path / f"{name}.ys"
        parameters = f"chparam -set DATA_WIDTH {width}"
        if maximum is not None:
            parameters += f" -set MAX_PACKET_BYTES {maximum} -set MAX_SG {sg}"
        script.write_text(
            "read_verilog -sv " + " ".join(map(str, sorted(Path("rtl").glob("*.sv")))) + "\n"
            + parameters + f" {top}\nhierarchy -check -top {top}\n"
            "proc; opt_expr; opt_clean; check -assert\n"
            "memory -nomap; opt_clean; check -assert\n"
            "select -assert-none t:$dlatch t:$adlatch t:$div t:$mod t:$divfloor t:$modfloor\n"
            f"stat\nwrite_json {netlist.relative_to(ROOT)}\n"
        )
        e.run(["yosys", "-s", script.relative_to(ROOT)], name)
        design = json.loads(netlist.read_text())
        modules = design["modules"]
        counts = {}
        sequential = memory_bits = 0

        def walk(module_name):
            nonlocal sequential, memory_bits
            module = modules[module_name]
            if module.get("attributes", {}).get("blackbox"):
                raise AssertionError(f"unresolved black box: {module_name}")
            hdlname = module.get("attributes", {}).get("hdlname", module_name).split()[0].lstrip("\\")
            counts[hdlname] = counts.get(hdlname, 0) + 1
            literal = {
                "furnace_x3_top": {
                    "x2_core": "furnace_x2_top", "queue_rings": "furnace_descriptor_rings",
                    "scheduler": "furnace_drr_scheduler", "shaper": "furnace_token_bucket8",
                    "dma_engine": "furnace_sg_dma"},
                "furnace_x2_top": {
                    "crc_core": "furnace_x1_top", "parser": "furnace_header_parser",
                    "rss": "furnace_rss_toeplitz", "classifier": "furnace_classifier64"},
                "furnace_x1_top": {
                    "beat_pipeline": "furnace_crc_beat_pipeline",
                    "packet_accumulator": "furnace_crc_packet_accumulator",
                    "tail_pipeline": "furnace_crc_tail_pipeline",
                    "output_stage": "furnace_crc_output_stage"},
            }.get(hdlname, {})
            actual_instances = {}
            for cell_name, cell in module.get("cells", {}).items():
                kind = cell["type"]
                if kind in modules:
                    actual_instances[cell_name.lstrip("\\").split(".")[-1]] = (
                        modules[kind].get("attributes", {}).get("hdlname", kind).split()[0].lstrip("\\"))
                    for direction in ("input", "output"):
                        ports = [p for p, d in cell["port_directions"].items() if d == direction]
                        if not any(isinstance(bit, int) for p in ports for bit in cell["connections"][p]):
                            raise AssertionError(f"disconnected {direction} of {kind}")
                    walk(kind)
                elif not kind.startswith("$"):
                    raise AssertionError(f"unknown synthesis cell: {kind}")
                if "latch" in kind or kind in ("$div", "$mod", "$divfloor", "$modfloor"):
                    raise AssertionError(f"forbidden synthesis cell: {kind}")
                if "dff" in kind:
                    sequential += len(cell["connections"].get("Q", []))
                if kind == "$mem_v2":
                    parameters = cell["parameters"]
                    memory_bits += int(parameters["SIZE"], 2) * int(parameters["WIDTH"], 2)
            for instance_name, expected_type in literal.items():
                if actual_instances.get(instance_name) != expected_type:
                    raise AssertionError(f"required literal instance missing: {hdlname}.{instance_name}")

        walk(top)
        required = ["furnace_x1_top", "furnace_crc_beat_pipeline",
                    "furnace_crc_packet_accumulator", "furnace_crc_tail_pipeline",
                    "furnace_crc_output_stage"]
        if top != "furnace_x1_top":
            required += ["furnace_x2_top", "furnace_header_parser", "furnace_rss_toeplitz",
                         "furnace_classifier64"]
        if top == "furnace_x3_top":
            required += ["furnace_x3_top", "furnace_descriptor_rings", "furnace_drr_scheduler",
                         "furnace_token_bucket8", "furnace_sg_dma", "furnace_dma_reader"]
        if any(counts.get(name, 0) != 1 for name in required):
            raise AssertionError(f"required literal module connectivity absent: {counts}")
        minimum_memory = 0 if top == "furnace_x1_top" else 64 * (512 + 512 + 32) + 256 * 8
        if top == "furnace_x3_top":
            minimum_memory += maximum * 8 + 8 * sg * (64 + 32)
        if sequential < 1000 or memory_bits < minimum_memory:
            raise AssertionError("non-substantive sequential/storage state")
        ports = {name: (p["direction"], len(p["bits"])) for name, p in modules[top]["ports"].items()}
        if top == "furnace_x3_top":
            public_ports.append((width, ports))
        if top == "furnace_x2_top":
            preserved_ports[width] = ports
        results.append({"top": top, "width": width, "maximum": maximum, "sg": sg,
                        "sequential_bits": sequential, "memory_bits": memory_bits,
                        "instances": counts, "netlist": str(netlist.relative_to(ROOT))})
    if not minimum_only:
        for width, ports in public_ports:
            for name, shape in preserved_ports[width].items():
                if ports.get(name) != shape:
                    raise AssertionError(f"X2 public port ABI changed on X3: {width}/{name}")
    e.record["synthesis"] = results


def defects(e, selected=None):
    e.require(["verilator", "make", "g++"])
    functional(e, 64, 65, 3, [17], label="baseline")
    mutations = [
        ("crc-polynomial", "furnace_crc_beat_pipeline.sv",
         "32'h82f63b78", "32'h82f63b79", "functional", "CRC polynomial/bit order mismatch"),
        ("rss-key-order", "furnace_rss_toeplitz.sv",
         "accumulator ^ key_shift[327:296]", "accumulator ^ key_shift[326:295]",
         "functional", "RSS tuple/key order mismatch"),
        ("classifier-priority", "furnace_classifier64.sv",
         "wire current_wins = !found && enable_q && equal_q;",
         "wire current_wins = enable_q && equal_q;", "functional", "classifier priority/action mismatch"),
        ("drr-debit", "furnace_drr_scheduler.sv",
         "deficit[evt_queue]<=deficit[evt_queue]-evt_bytes;",
         "deficit[evt_queue]<=deficit[evt_queue]-(evt_bytes+1'b1);", "scheduler_tb", "DRR visit/debit"),
        ("token-debit", "furnace_token_bucket8.sv",
         "balance[q]<=refilled-event_cost;", "balance[q]<=refilled;",
         "bucket_tb", "TOKEN refill/debit/refund"),
        ("sg-byte-boundary", "furnace_sg_dma.sv",
         "output_index<=output_index+1'b1;", "output_index<=output_index+2'd2;",
         "functional", "packet last mismatch"),
        ("ring-wrap", "furnace_descriptor_rings.sv",
         "physical_index[evt_queue]==entries[evt_queue]-1'b1",
         "physical_index[evt_queue]==entries[evt_queue]",
         "functional", "unexpected memory address"),
    ]
    if selected is not None:
        mutations = [mutation for mutation in mutations if mutation[0] in selected]
        if {mutation[0] for mutation in mutations} != set(selected):
            raise AssertionError("unknown selected defect")
    if any(mutation[4] == "bucket_tb" for mutation in mutations):
        leaf(e, "bucket_tb", label="baseline-bucket")
    if any(mutation[4] == "scheduler_tb" for mutation in mutations):
        leaf(e, "scheduler_tb", label="baseline-scheduler")
    records = [{"name": mutation[0], "status": "not_executed"} for mutation in mutations]
    e.record["mutants"] = records
    for record, (name, filename, old, new, kind, expected) in zip(records, mutations):
        root = e.path / f"mutant-{name}-{uuid.uuid4().hex[:8]}"
        root.mkdir()
        baseline_hashes = identity()
        for relative in baseline_hashes:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        path = root / "rtl" / filename
        text = path.read_text()
        if text.count(old) != 1:
            raise AssertionError(f"{name}: injection must identify one concrete source site")
        path.write_text(text.replace(old, new))
        record.update(
            status="compiling", file=f"rtl/{filename}", old=old, new=new,
            baseline_hash=baseline_hashes[f"rtl/{filename}"],
            mutant_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            source_copy=str(root.relative_to(ROOT)), expected_failure=expected)
        if kind == "functional":
            binary = compile_sim(e, 64, 65, 3, root=root, label=name)
            corpus = binary.parent / "vectors.txt"
            vectors(corpus, 65)
            argv = [os.path.relpath(binary, root), os.path.relpath(corpus, root), "17", "matrix"]
        else:
            obj = e.path / f"{name}-compile-{uuid.uuid4().hex[:8]}"
            e.run(["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
                   "--top-module", kind, "--Mdir", os.path.relpath(obj, root),
                   "tests/credits.sv", "rtl/furnace_token_bucket8.sv", "rtl/furnace_drr_scheduler.sv"],
                  f"{name}-compile", cwd=root)
            binary = e.path / f"{name}-simulator"
            shutil.copy2(obj / f"V{kind}", binary)
            shutil.rmtree(obj)
            argv = [os.path.relpath(binary, root), "+seed=17"]
        record["status"] = "compiled"
        record["rejection_stdout"] = str(
            (e.path / f"{name}-functional-rejection.stdout.txt").relative_to(ROOT))
        record["rejection_stderr"] = str(
            (e.path / f"{name}-functional-rejection.stderr.txt").relative_to(ROOT))
        output = e.run(argv, f"{name}-functional-rejection", cwd=root, expect_failure=True)
        first = next((line for line in output.splitlines() if "SCOREBOARD" in line), None)
        record.update(status="rejected_unclassified", first_functional_failure=first)
        if first is None or f"SCOREBOARD {expected}" not in first:
            raise AssertionError(f"{name}: rejection was not the expected functional comparison")
        record["status"] = "functionally_killed"
    if not records or any(record["status"] != "functionally_killed" for record in records):
        raise AssertionError("not all selected mutants compiled and failed functional comparisons")
    if selected is None and len(records) < 6:
        raise AssertionError("fewer than six compiling, functionally killed mutants")


def sensitivity_probe(e):
    e.require(["verilator", "make", "g++"])
    functional(e, 64, 1, 1, [17], mode="smoke", label="crc-baseline")
    root = e.path / f"crc-mutant-{uuid.uuid4().hex[:8]}"
    root.mkdir()
    before = identity()
    for relative in before:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    path = root / "rtl/furnace_crc_beat_pipeline.sv"
    text = path.read_text()
    if text.count("32'h82f63b78") != 1:
        raise AssertionError("CRC mutation site not unique")
    path.write_text(text.replace("32'h82f63b78", "32'h82f63b79"))
    binary = compile_sim(e, 64, 1, 1, root=root, label="crc-mutant")
    corpus = binary.parent / "vectors.txt"
    vectors(corpus, 1)
    output = e.run([os.path.relpath(binary, root), os.path.relpath(corpus, root), "17", "smoke"],
                   "crc-mutant-rejection", cwd=root, expect_failure=True)
    if "SCOREBOARD CRC polynomial/bit order mismatch" not in output:
        raise AssertionError("CRC mutant did not fail the independent numerical comparison")
    e.record["sensitivity_probe"] = {
        "scope": "One CRC defect only, not the admitted seven-mutant suite",
        "baseline_hash": before["rtl/furnace_crc_beat_pipeline.sv"],
        "mutant_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "first_failure": next(line for line in output.splitlines() if "SCOREBOARD" in line)}


def delivery(e):
    e.require(["iverilog", "vvp"])
    isolated = e.path / f"isolated-{uuid.uuid4().hex[:8]}"
    isolated.mkdir()
    before = identity()
    for relative in before:
        target = isolated / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    if identity(isolated) != before:
        raise AssertionError("isolated source copy differs")
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("PYTHONPATH", "PYTHONHOME")}
    # -I drops inherited import paths; the entrypoint imports only its own siblings.
    output = e.run(["python3", "-I", "tests/verify.py", "--delivery-smoke"],
                   "isolated-reproduction", cwd=isolated, env=environment)
    receipts = list((isolated / "evidence").glob("delivery-smoke-*/receipt.json"))
    if len(receipts) != 1:
        raise AssertionError("isolated reproduction receipt missing or ambiguous")
    receipt = json.loads(receipts[0].read_text())
    if receipt["exit_code"] != 0 or receipt["source_hashes"] != before:
        raise AssertionError("isolated reproduction not source-bound and successful")
    e.record["reproduction"] = {"receipt": str(receipts[0].relative_to(ROOT)),
                               "scope": "Both widths, compact one legacy packet plus one real DMA packet; not the full matrix"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["behavior", "defects", "synthesis", "delivery"])
    parser.add_argument("--prepare", choices=["startup", "smoke", "cell", "credits", "portable", "rollover", "synthesis-min", "sensitivity", "boundary-sensitivity"])
    parser.add_argument("--delivery-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--width", type=int, choices=[64, 512], default=64)
    parser.add_argument("--maximum", type=int, default=65)
    parser.add_argument("--segments", type=int, default=3)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    suites = [args.suite] if args.suite else ["behavior", "defects", "synthesis", "delivery"]
    if args.prepare:
        suites = [args.prepare]
    if args.delivery_smoke:
        suites = ["delivery-smoke"]
    failed = False
    for suite in suites:
        e = Evidence(suite, preparation=bool(args.prepare), repair_of=args.repair_of)
        try:
            for selector in SOURCES:
                if not any(path.is_file() for path in ROOT.glob(selector)):
                    raise RuntimeError(f"missing declared verification input: {selector}")
            reference.self_check()
            e.record["oracle_known_answers"] = {
                "input_hex": b"123456789".hex(), "crc32c": "e3069283",
                "crc64_nvme": "ae8b14860a799888", "matched": True}
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
                leaf(e, "ownership_tb")
                leaf(e, "dma_contract_tb", label="dma-contract-64")
                leaf(e, "dma_contract_tb", label="dma-contract-512", width=512)
            elif suite in ("portable", "delivery-smoke"):
                portable(e)
            elif suite == "rollover":
                e.require(["yosys"])
                rollover(e)
            elif suite == "synthesis-min":
                synthesize(e, minimum_only=True)
            elif suite == "sensitivity":
                sensitivity_probe(e)
            elif suite == "boundary-sensitivity":
                defects(e, selected=("sg-byte-boundary", "ring-wrap"))
            elif suite == "behavior":
                e.record["matrix"] = [
                    {"width": w, "maximum": m, "sg": s, "seed": seed,
                     "status": "not_executed",
                     "required": {"dma_successes": 64, "legacy_packets": 16,
                                  "queues": 8, "physical_wraps_per_capacity": 2},
                     "observed": None}
                    for w in (64, 512) for m, s in ((1, 1), (65, 3), (9216, 16))
                    for seed in (17, 43, 89)
                ]
                startup(e)
                e.require(["verilator", "make", "g++", "yosys"])
                portable(e)
                leaf(e, "bucket_tb", seeds=(17, 43, 89), icarus=True)
                leaf(e, "scheduler_tb", seeds=(17, 43, 89))
                leaf(e, "ownership_tb")
                leaf(e, "dma_contract_tb", label="dma-contract-64")
                leaf(e, "dma_contract_tb", label="dma-contract-512", width=512)
                rollover(e)
                for width in (64, 512):
                    for maximum, sg in ((1, 1), (65, 3), (9216, 16)):
                        functional(e, width, maximum, sg, [17, 43, 89])
            elif suite == "synthesis":
                synthesize(e)
            elif suite == "defects":
                defects(e)
            elif suite == "delivery":
                delivery(e)
            else:
                raise RuntimeError(f"unsupported verification suite: {suite}")
        except Exception as error:
            e.finish(f"{type(error).__name__}: {error}")
            print(str(error), file=sys.stderr)
            failed = True
        else:
            if not e.finish():
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
