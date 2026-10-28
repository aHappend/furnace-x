#!/usr/bin/env python3
"""Prepare native public-pin stimulus or score three physical capture files.

This is shared-runtime integration support, not an L1 selector or a hardware
driver. Export does not execute Quartus, access a bridge or program a device.
The runtime must supply the physical adapter and implementation reports.

From the project root:
    python3 tests/native_vectors.py --mode export --out evidence/native/inputs

Use the printed unique run directory as --bundle. For each --width (64, 512),
score with --mode score, three --capture project-relative trace paths, and a
fresh --out evidence/native/score-WIDTH. A scoreboard pass alone is never a
physical-HIL verdict: the runtime must bind image/source/device identity,
100 MHz execution, negotiated PCIe Gen3x8, run order and actual capture origin.

vectors.txt contains the ten input fields listed below plus pulse_reset=0.
Hold each row through its rising edge; trace exactly one A row per input row,
including reset and idle/drain cycles. Data is lane-zero in the low eight bits.
The adapter must capture every public signal in OUTPUTS + INPUTS, not reconstruct
pins from expected.jsonl or reduce a packet to a software CRC calculation.
The native-contract.json identifies the exact field order and immutable inputs.
Adjacent capture rows check stalled fields even on protocol-error results.
Bundle validation requires the complete two-width vector, oracle and Quartus
input hash closure; omitted entries are failures even when files still exist.

Copy each exported quartus project into a fresh build directory before invoking
the native quartus-sta gate with --run-map --run-fit, --clock clk_main,
--min-setup-slack-ns 0, --min-hold-slack-ns 0 and --timeout-s 7200. Do not use
--post-map. Run quartus_sta -t reports.tcl there and retain all reports, QSF/SDC,
full map/fit logs and tool receipts. All relevant corners and unconstrained
paths still require independent review; the Tcl report script is not a verdict.
The exported synchronous 2 ns I/O budget requires admission as an integration
assumption; it neither establishes a board pinout nor waives timing acceptance.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenarios import Packets, Schedule
from scoreboard import check_stalled_outputs, compare, parse_observation, require
from verify import ROOT, Run, inventory, relative_output, write_json


DEVICE = "10AX115N2F45E1SG"
INPUTS = ("rst_n s_axis_tvalid s_axis_tdata s_axis_tkeep s_axis_tlast "
          "s_check_enable s_expected_crc32c s_expected_crc64_nvme "
          "m_axis_tready m_crc_ready").split()
OUTPUTS = ("s_axis_tready m_axis_tvalid m_axis_tdata m_axis_tkeep m_axis_tlast "
           "m_crc_valid m_crc32c m_crc64_nvme m_crc_mismatch "
           "m_crc_protocol_error").split()

SDC = """create_clock -name clk_main -period 10.000 [get_ports {clk}]
derive_clock_uncertainty
# Synchronous integration budget, not a board pinout or a timing exception.
set data_inputs [remove_from_collection [all_inputs] [get_ports {clk}]]
set_input_delay -clock clk_main -max 2.000 $data_inputs
set_input_delay -clock clk_main -min 0.000 $data_inputs
set_output_delay -clock clk_main -max 2.000 [all_outputs]
set_output_delay -clock clk_main -min 0.000 [all_outputs]
"""

STA_REPORTS = """project_open top
# Never fall back to post-map analysis.
create_timing_netlist
read_sdc
update_timing_netlist
report_clocks -file clocks.rpt
report_sdc -file constraints.rpt
check_timing -file constraint_coverage.rpt
report_ucp -file unconstrained_paths.rpt
report_timing -setup -npaths 100 -detail full_path -file setup.rpt
report_timing -hold -npaths 100 -detail full_path -file hold.rpt
report_timing -recovery -npaths 100 -detail full_path -file recovery.rpt
report_timing -removal -npaths 100 -detail full_path -file removal.rpt
delete_timing_netlist
project_close
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_path(text):
    path = relative_output(text)
    require(path.exists(), f"missing input: {text}")
    return path


def make_native_scenario(directory, width):
    p = Packets(width, 2026)
    s = Schedule(directory, width, 2026)
    b = width // 8
    for _ in range(3):
        s.step(reset=True)
    s.step()
    for index in range(16):
        s.send(p.packet(b"" if index < 8 else bytes([index]), enable=3,
                        group="consecutive"))
    s.drain()
    s.send(p.packet(b"123456789", enable=3, group="known"))
    for length in list(range(2 * b + 2)) + [255, 256, 257, 4095, 4096, 4097]:
        s.send(p.packet(p.data(length, "random"), enable=3, group="boundary"),
               randomized=True)
    for length in (b, 2 * b):
        for extra in (False, True):
            s.send(p.packet(p.data(length, "walking"), extra=extra, enable=3,
                            group="exact-multiple"), randomized=True)
    for enable in range(4):
        s.send(p.packet(b"\x93\x27", enable=enable, incorrect=3, group="checking"))
    s.drain()
    for direction in ("payload", "result"):
        s.reach_output(p.packet(b"\x69", enable=3))
        for _ in range(40):
            s.step(mr=int(direction != "payload"), cr=int(direction != "result"))
        s.drain()
    for length in (1, b - 1, b, b + 1, 2 * b + 1):
        data = p.data(length, "random")
        changed = bytearray(data)
        changed[-1] ^= 1
        base = p.packet(data, enable=3, group="flip-base")
        flipped = p.packet(bytes(changed), enable=3, group="flip-changed")
        original = p.records[-2]
        flipped[0]["expected32"] = original["crc32"]
        flipped[0]["expected64"] = original["crc64"]
        p.records[-1]["mismatch"] = 3
        require(original["crc32"] != p.records[-1]["crc32"] and
                original["crc64"] != p.records[-1]["crc64"], "bit flip not discriminating")
        s.send(base)
        s.send(flipped)
    data = p.data(b - 1, "random")
    base = p.packet(data, enable=3, group="disabled-base")
    changed = p.packet(data, enable=3, group="disabled-changed")
    changed[-1]["data"] = base[-1]["data"] ^ (1 << (8 * (b - 1)))
    s.send(base)
    s.send(changed)
    s.drain()
    for direction in ("payload", "result"):
        s.reach_output(p.packet(b"\xa5", enable=3, group="aborted"))
        s.step(mr=int(direction == "result"), cr=int(direction == "payload"))
        s.step(reset=True)
        s.send(p.packet(b"\x16\x7d", enable=3, group="recovery"))
        s.drain()
    partial = p.packet(p.data(2 * b, "random"), enable=3, group="aborted")
    partial[-1]["last"] = 0
    partial[-1]["result"] = None
    s.send(partial)
    s.drain()
    s.step(reset=True)
    s.send(p.packet(b"\x42", enable=3, group="recovery"))
    s.drain()
    for _ in range(24):
        s.step()
    s.close()
    manifest = {"width": width, "seed": 2026, "cycles": s.cycles,
                "packets": p.records}
    write_json(directory / "manifest.json", manifest)
    return manifest


def export_bundle(run):
    contract = {
        "schema": 1, "device": DEVICE, "top": "furnace_x1_top",
        "widths": [64, 512], "clock_period_ns": 10.0,
        "source_hashes": inventory(), "physical_runs_per_width": 3,
        "stimulus_fields": INPUTS + ["pulse_reset"],
        "capture_fields": ["phase=A", "cycle_decimal"] + OUTPUTS + INPUTS,
        "encoding": "one whitespace-separated row per cycle; pins are hexadecimal",
        "capture_edge": "actual public pins immediately before each rising edge",
        "adapter_required": True,
        "adapter_status": "not supplied by this bundle; no physical execution is claimed",
        "timing_boundary": "virtual synchronous public pins, input max 2 ns/min 0 ns; "
                           "output max 2 ns/min 0 ns; no false or multicycle paths",
        "limitations": [
            "Virtual-pin projects are core STA projects, not PCIe bitstreams.",
            "Runtime must provide actual public-pin mapping, capture and PCIe Gen3x8 shell.",
            "Expected rows are host-only oracle data; never use them as hardware observations.",
            "No subcycle reset, post-edge or negedge coverage is claimed by native capture.",
            "No board pin budget is inferred from the synchronous core integration budget.",
            "All relevant implementation corners, constraints and recovery/removal require review.",
        ],
    }
    for width in (64, 512):
        directory = run.path / f"width-{width}"
        directory.mkdir()
        make_native_scenario(directory, width)
        project = directory / "quartus"
        (project / "rtl").mkdir(parents=True)
        for source in sorted((ROOT / "rtl").glob("*.sv")):
            shutil.copyfile(source, project / "rtl" / source.name)
        qsf = [
            'set_global_assignment -name FAMILY "Arria 10"',
            f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY furnace_x1_top",
            "set_global_assignment -name SDC_FILE timing.sdc",
            "set_global_assignment -name SEED 2026",
            "set_instance_assignment -name VIRTUAL_PIN ON -to *",
            "set_instance_assignment -name VIRTUAL_PIN OFF -to clk",
            f"set_parameter -name DATA_WIDTH {width}",
        ]
        qsf += [f"set_global_assignment -name SYSTEMVERILOG_FILE rtl/{p.name}"
                for p in sorted((project / "rtl").glob("*.sv"))]
        (project / "top.qsf").write_text("\n".join(qsf) + "\n")
        (project / "top.qpf").write_text('PROJECT_REVISION = "top"\n')
        (project / "timing.sdc").write_text(SDC)
        (project / "reports.tcl").write_text(STA_REPORTS)
    contract["bundle_hashes"] = {
        str(p.relative_to(run.path)): digest(p)
        for width in (64, 512)
        for p in sorted((run.path / f"width-{width}").rglob("*")) if p.is_file()
    }
    write_json(run.path / "native-contract.json", contract)
    run.record["results"]["bundle"] = "native-contract.json"
    run.save()


def verify_bundle(bundle):
    contract = json.loads((bundle / "native-contract.json").read_text())
    sources = inventory()
    require(contract["source_hashes"] == sources,
            "bundle source identity differs from current deliverable inputs")
    require(contract["device"] == DEVICE and contract["widths"] == [64, 512],
            "native contract target/configuration differs")
    required_inputs = {
        f"width-{width}/{name}"
        for width in (64, 512)
        for name in ("vectors.txt", "expected.jsonl", "manifest.json",
                     "quartus/top.qsf", "quartus/top.qpf",
                     "quartus/timing.sdc", "quartus/reports.tcl",
                     *[f"quartus/{name}" for name in sources
                       if name.startswith("rtl/")])
    }
    require(isinstance(contract.get("bundle_hashes"), dict) and
            set(contract["bundle_hashes"]) == required_inputs,
            "native bundle input closure must bind every declared input at both widths")
    for name, sha in contract["bundle_hashes"].items():
        path = (bundle / name).resolve()
        require(path.is_relative_to(bundle), f"bundle path escapes root: {name}")
        require(path.is_file() and digest(path) == sha, f"bundle input changed: {name}")
    return contract


def score_capture(directory, capture):
    manifest = json.loads((directory / "manifest.json").read_text())
    completed = set()
    counts = {"cycles": 0, "payload_beats": 0, "results": 0,
              "payload_stalls": 0, "result_stalls": 0}
    previous = None
    with capture.open() as trace, (directory / "expected.jsonl").open() as expected:
        for line in expected:
            row = json.loads(line)
            observed, pins = parse_observation(trace.readline(), row["cycle"], "A")
            require(pins == tuple(row["inputs"]), f"physical input mismatch cycle={row['cycle']}")
            require(not row["pulse"], "native scenario unexpectedly requires subcycle reset")
            compare(observed, row["pre"], row["cycle"], "physical-pre-edge")
            counts["cycles"] += 1
            if row["pre"]["reset"]:
                previous = None
                continue
            if previous is not None:
                before, previous_pins = previous
                check_stalled_outputs(before, observed, previous_pins[8],
                                      previous_pins[9], row["cycle"])
            previous = observed, pins
            counts["payload_stalls"] += int(observed[1] and not pins[8])
            counts["result_stalls"] += int(observed[5] and not pins[9])
            counts["payload_beats"] += int(observed[1] and pins[8])
            if observed[5] and pins[9]:
                record = row["pre"]["result"]
                require(record["id"] not in completed, "duplicate physical result")
                completed.add(record["id"])
                counts["results"] += 1
        require(trace.readline() == "", "extra physical observations after drain")
    require(counts["cycles"] == manifest["cycles"], "incomplete physical capture")
    records = [r for r in manifest["packets"] if r["id"] in completed]
    require({r["id"] for r in manifest["packets"] if r["group"] != "aborted"} <= completed,
            "missing physical packet completion")
    require(counts["payload_stalls"] >= 32 and counts["result_stalls"] >= 32,
            "independent physical stalls not observed")
    require(set(range(manifest["width"] // 8 + 1)) <= {r["final_count"] for r in records},
            "physical tail-count coverage missing")
    require(any(r["group"] == "known" for r in records)
            and any(r["beats"] > 1 for r in records), "physical known/multibeat coverage missing")
    counts["crc32c_comparisons"] = counts["crc64_nvme_comparisons"] = len(records)
    return counts


def score_runs(run, bundle, width, captures):
    verify_bundle(bundle)
    require(len(captures) == 3, "three consecutive raw captures are required per width")
    require(len(set(captures)) == 3, "captures must be three distinct retained files")
    directory = run.path / f"scored-width-{width}"
    directory.mkdir()
    counts = []
    hashes = []
    for index, source in enumerate(captures, 1):
        saved = directory / f"capture-{index}.trace"
        shutil.copyfile(source, saved)
        hashes.append(digest(saved))
        counts.append(score_capture(bundle / f"width-{width}", saved))
    require(len(set(hashes)) == 1, "physical pin captures differ across deterministic runs")
    run.record["results"][f"scored-width-{width}"] = {
        "width": width, "raw_capture_sha256": hashes, "comparisons": counts,
        "scope": "pin-trace scoreboard only; runtime must independently bind physical provenance, "
                 "run consecutiveness, image/source identity, device, clock and PCIe Gen3x8 link"}
    run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("export", "score"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--bundle")
    parser.add_argument("--width", type=int, choices=(64, 512))
    parser.add_argument("--capture", action="append", default=[])
    args = parser.parse_args()
    run = Run(relative_output(args.out), "native-" + args.mode, None)
    run.record["tool_versions"]["python3"] = sys.version
    try:
        if args.mode == "export":
            require(not args.bundle and args.width is None and not args.capture,
                    "export does not take capture inputs")
            export_bundle(run)
        else:
            require(args.bundle and args.width, "score requires --bundle and --width")
            score_runs(run, project_path(args.bundle), args.width,
                       [project_path(p) for p in args.capture])
        run.finish("passed")
    except (AssertionError, OSError, ValueError, KeyError) as error:
        run.finish("failed", error)
        print(f"Native integration support failed: {error}", file=sys.stderr)
        return 1
    print(run.path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
