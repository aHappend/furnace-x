#!/usr/bin/env python3
"""Source-bound native gates; run from the project root, never programs a device.

Append-only check commands (existing L1 checks remain mandatory):
  python3 tests/native_gates.py --mode lint --out evidence/native/timing-lint
  python3 tests/native_gates.py --mode prerequisites --out evidence/native/prerequisites
  python3 tests/native_gates.py --mode sta --width 64 --out evidence/native/sta-64
  python3 tests/native_gates.py --mode sta --width 512 --out evidence/native/sta-512
  python3 tests/native_gates.py --mode hil --width 64 --out evidence/native/hil-64
  python3 tests/native_gates.py --mode hil --width 512 --out evidence/native/hil-512

The supported shared-runtime configuration is fpga/board_hil.json, overridable
with --board-config (project-relative). Do not create a fictitious binding.
Its existing bridge_dir/chip_id/tools_win_dir keys pass to board-hil unchanged.
This wrapper never invokes auto_board_hil_gate, build/flash, transfer or deploy.
Remote capture commands must be independently admitted read-only commands.

Required project-specific extension, furnace_x1:
  device: 10AX115N2F45E1SG
  widths: {"64": {...}, "512": {...}}
Each width entry describes the *actual* adapter, not a virtual-pin core project:
  project_dir, revision, adapter_top, clock, clock_period_ns (positive, <=10);
  rtl_bindings: {original rtl/*.sv: project-relative integrated source};
  adapter_sources, constraints, implementation_inputs:
    {project-relative path: SHA256};
  public_pin_map: path to JSON mapping clk plus INPUTS and OUTPUTS to adapter nets;
  timing_budget: {description, evidence, input_min_ns, input_max_ns,
                  output_min_ns, output_max_ns};
  image, image_manifest: project-relative image and build manifest paths.
The immutable image manifest binds image_sha256, rtl_hashes, adapter_sources,
constraints, public_pin_map_sha256, width, device, top and clock_period_ns.
implementation_inputs declares the complete self-contained Quartus source/IP
closure (including QSF/QPF/SDC/QIP and any ROM/IP files), never old databases,
reports or images. All file references must stay relative within that closure.
The project/QSF/SDC and budget evidence must be independently reviewed before
these new checks are admitted; configuration text alone is not that approval.
Timing-budget evidence must give actual adapter launch/capture boundaries.
No default 2 ns budget, virtual-pin substitution or timing exception is added.
Quartus executables come from PATH or configured quartus_bin_dir.

For HIL, each width also needs remote_test_cmd, capture_only=true. The configured
command must contain @FURNACE_NONCE@, @FURNACE_VECTOR_SHA256@ and
@FURNACE_WIDTH@ tokens. Only these hexadecimal/integer values are substituted.
The bridge integration must already make that exact stimulus available; this
entrypoint does not invent remote commands or copy/program an image.
Each of three consecutive invocations emits only actual pre-edge public-pin
rows on stdout, in native_vectors.py format, and exactly one JSON object after
FURNACE_HIL_METADATA on stderr. Required metadata: origin="physical",
transport="PCIe", pcie_generation=3, pcie_lanes=8, width, device, top,
clock_period_ns, image_sha256, rtl_hashes, adapter_sources, constraints,
implementation_inputs,
public_pin_map_sha256, vector_sha256, nonce and strictly consecutive integer
run_sequence. Read these from the active adapter/image/link, not the oracle.
Width, PCIe generation/lanes and sequence are JSON integers, not coercible
floating-point values or booleans. Timing corner records must be uniquely
identified, in range and syntactically complete; malformed records fail closed.
Each reported corner must retain nonempty setup, hold, recovery and removal
reports, including reports for analysis kinds with no applicable paths.
Each analysis emits an explicit zero/one worst-path count; a nonzero count
requires exactly one slack record. Missing recovery/removal records alone never
establish that those analyses have no paths.
Physical run counts, indices and exit codes must likewise be JSON integers;
each run's passed field must be the JSON boolean true, never a truthy string.
Constraint-count rows must contain only nonnegative integer counts after their
label, and every analysis column must be zero, including hold.
Rows under a Property header must retain exactly its declared columns and
closing delimiter. Illegal-clock counts must also be zero.
Recognized constraint labels without count columns are malformed, never ignored.
Lint reports must bind every current RTL source, use a zero divider-width
threshold, and explicitly report empty hazard and source-sanitization lists;
a passed label alone does not establish these properties.
stdout must be deterministic across runs. Metadata and equal traces alone
cannot prove physical origin: independent review must inspect the actual
capture implementation, image build provenance and raw shared-runtime records.

Missing bindings/tools/license, non-post-fit STA, unknown report formats,
unconstrained timing, absent metadata or scoreboard errors are failures, not
skips. Coverage TimeQuest stdout, stderr and reports must contain no Quartus
errors or ignored-assignment Warning (10268), regardless of exit status.
Native gate wrapper stdout and stderr are checked too; a passed JSON report
cannot override these diagnostics.
JSON bindings, reports, manifests and physical metadata reject duplicate keys
at every nesting level and non-finite numbers, including exponent overflow.
Every invocation retains a fresh Run receipt and raw child logs.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_vectors import DEVICE, INPUTS, OUTPUTS, export_bundle, score_capture
from scoreboard import require
from verify import HIERARCHY, ROOT, Run, inventory, relative_output, write_json


class PrerequisiteError(RuntimeError):
    """A native integration input is absent or unusable."""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_path(text):
    path = relative_output(text)
    if not path.is_file():
        raise PrerequisiteError(f"missing integration input: {text}")
    return path


def parse_json_object(text, label):
    def unique_fields(pairs):
        fields = {}
        for name, value in pairs:
            require(name not in fields, f"duplicate JSON field {name}: {label}")
            fields[name] = value
        return fields

    def reject_constant(value):
        require(False, f"non-finite JSON constant {value}: {label}")

    value = json.loads(text, object_pairs_hook=unique_fields,
                       parse_constant=reject_constant,
                       parse_float=lambda number: finite(float(number), f"JSON number: {label}"))
    require(isinstance(value, dict), f"expected JSON object: {label}")
    return value


def load_json(path):
    return parse_json_object(path.read_text(), str(path.relative_to(ROOT)))


def finite(value, name):
    require(type(value) in (int, float) and math.isfinite(value),
            f"invalid numeric field {name}")
    return value


def retain_inputs(run, paths):
    saved = run.record.setdefault("integration_hashes", {})
    for path in paths:
        name = str(path.relative_to(ROOT))
        value = sha(path)
        require(name not in saved or saved[name] == value,
                f"integration input changed during execution: {name}")
        saved[name] = value
        target = run.path / "integration-inputs" / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    run.save()


def load_binding(run, text, width, physical=False):
    try:
        return _load_binding(run, text, width, physical)
    except KeyError as error:
        raise PrerequisiteError(
            f"{text}: missing required native integration field {error}") from error


def _load_binding(run, text, width, physical):
    path = relative_output(text)
    if not path.is_file():
        raise PrerequisiteError(
            f"missing supported shared-runtime configuration: {text}; no bound "
            "furnace_x1_top public-pin transport, physical image, adapter QSF/SDC "
            "or actual integration timing budget. A live bridge is not such a binding. "
            "The platform provider/shared-runtime owner must supply authoritative bridge RTL/ABI, "
            "clock/reset integration, actual launch/capture boundaries, complete projects for "
            "both widths, capture-only transport and active-image provenance; Coordinator "
            "and Reviewer must independently admit ownership, source selectors and exact commands "
            "before Designer implements the public-pin stimulus/capture adapter and Verifier "
            "executes native checks. Do not invent a binding or program hardware.")
    retain_inputs(run, [path])
    cfg = load_json(path)
    extension = cfg.get("furnace_x1")
    if not isinstance(extension, dict):
        raise PrerequisiteError(f"{text}: missing furnace_x1 adapter/timing/image binding")
    require(extension["device"] == DEVICE, "wrong native target device")
    entry = extension["widths"][str(width)]
    period = finite(entry["clock_period_ns"], "clock_period_ns")
    require(0 < period <= 10, "native adapter clock must meet <=10 ns")
    require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry["revision"]) is not None,
            "revision must be a simple Quartus identifier")
    require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry["clock"]) is not None,
            "clock must be a simple TimeQuest clock identifier")
    require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry["adapter_top"]) is not None,
            "adapter_top must identify the actual Quartus top entity")
    actual_rtl = {k: v for k, v in inventory().items() if k.startswith("rtl/")}
    require(set(entry["rtl_bindings"]) == set(actual_rtl),
            "adapter must bind every actual RTL file")
    paths = []
    for original, integrated in entry["rtl_bindings"].items():
        source = input_path(integrated)
        require(sha(source) == actual_rtl[original], f"integrated RTL differs: {original}")
        paths.append(source)
    for group in ("adapter_sources", "constraints", "implementation_inputs"):
        require(entry[group], f"missing actual adapter {group}")
        for name, digest in entry[group].items():
            source = input_path(name)
            require(sha(source) == digest, f"changed {group}: {name}")
            paths.append(source)
    pin_map = input_path(entry["public_pin_map"])
    pins = load_json(pin_map)
    require(set(pins) == set(["clk", *INPUTS, *OUTPUTS]),
            "public pin mapping must cover exactly the complete top interface")
    require(all(isinstance(v, str) and v for v in pins.values()),
            "empty public pin mapping")
    require(len(set(pins.values())) == len(pins), "public pins alias in adapter mapping")
    paths.append(pin_map)
    budget = entry["timing_budget"]
    require(isinstance(budget["description"], str) and budget["description"].strip(),
            "actual launch/capture timing-budget description missing")
    paths.append(input_path(budget["evidence"]))
    for direction in ("input", "output"):
        minimum = finite(budget[f"{direction}_min_ns"], f"{direction}_min_ns")
        maximum = finite(budget[f"{direction}_max_ns"], f"{direction}_max_ns")
        require(minimum <= maximum, "reversed timing-budget bounds")
    project = relative_output(entry["project_dir"])
    require(project.is_dir(), f"missing actual Quartus project: {entry['project_dir']}")
    for suffix in ("qpf", "qsf"):
        paths.append(input_path(f"{entry['project_dir']}/{entry['revision']}.{suffix}"))
    require(not re.search(r"VIRTUAL_PIN\s+ON", paths[-1].read_text(), re.I),
            "virtual-pin project cannot stand in for actual adapter implementation")
    implementation = entry["implementation_inputs"]
    required = [*entry["rtl_bindings"].values(), *entry["adapter_sources"],
                *entry["constraints"],
                f"{entry['project_dir']}/{entry['revision']}.qpf",
                f"{entry['project_dir']}/{entry['revision']}.qsf"]
    require(set(required) <= set(implementation), "incomplete implementation source closure")
    require(all(not any(part in ("db", "incremental_db", "output_files")
                        for part in Path(name).parts) and
                not name.endswith((".rpt", ".sof", ".rpd", ".pof", ".qdb"))
                for name in implementation), "old build products are not source inputs")
    if physical:
        require(entry.get("capture_only") is True,
                "native command must be independently admitted capture-only")
        command = entry["remote_test_cmd"]
        require(isinstance(command, str) and command.strip(), "missing actual remote_test_cmd")
        for token in ("NONCE", "VECTOR_SHA256", "WIDTH"):
            require(f"@FURNACE_{token}@" in command, f"remote binding missing {token} token")
        for name in ("image", "image_manifest"):
            paths.append(input_path(entry[name]))
        manifest = load_json(input_path(entry["image_manifest"]))
        expected = {
            "image_sha256": sha(input_path(entry["image"])), "rtl_hashes": actual_rtl,
            "adapter_sources": entry["adapter_sources"], "constraints": entry["constraints"],
            "implementation_inputs": entry["implementation_inputs"],
            "public_pin_map_sha256": sha(pin_map), "width": width, "device": DEVICE,
            "top": "furnace_x1_top", "clock_period_ns": period,
        }
        require(all(manifest.get(k) == v for k, v in expected.items()),
                "image build manifest differs from current RTL/adapter/constraints")
    retain_inputs(run, paths)
    return cfg, entry


def gate_command(run, argv, report):
    command, stdout, stderr = run.child(argv, ROOT, allowed=None)
    for text in (stdout, stderr):
        require(not re.search(r"(?:Error \(\d+\)|Warning \(10268\))", text),
                "forbidden Quartus diagnostic in native gate output")
    require(report.is_file(), f"native gate omitted raw JSON report: {report.name}")
    data = load_json(report)
    require(command["exit_code"] == 0 and data.get("status") == "passed",
            f"native gate failed: {data.get('detail', command['receipt'])}")
    return data


def lint(run):
    report = run.path / "rtl-timing-lint.json"
    data = gate_command(run, [
        "vulcan", "hardware", "fpga", "rtl-timing-lint",
        "--project", ".", "--rtl-glob", "rtl/*.sv",
        "--max-comb-div-width", "0", "--output", str(report.relative_to(ROOT)),
    ], report)
    require(data.get("gate") == "rtl-timing-lint", "wrong native lint report kind")
    require(type(data.get("max_comb_div_width")) is int and
            data["max_comb_div_width"] == 0, "lint must forbid all combinational division")
    rtl = {k: v for k, v in inventory().items() if k.startswith("rtl/")}
    require(type(data.get("rtl_files_checked")) is int and
            data["rtl_files_checked"] == len(rtl) and data.get("source_sha256") == rtl,
            "lint report must bind exactly every current RTL source")
    for name in ("rtl_div_mod_hazards", "netlist_div_mod_hazards",
                 "mixed_assign_hazards", "lut_clock_gate_hazards",
                 "ast_unroll_loop_hazards", "auto_sanitized_nomem2reg_files"):
        require(data.get(name) == [],
                f"native lint requires an explicit empty {name} list")
    run.record["results"]["lint"] = data


def quartus_tools(run, cfg):
    directory = cfg.get("quartus_bin_dir")
    tools = {}
    for name in ("quartus_map", "quartus_fit", "quartus_sta"):
        found = str(Path(directory) / name) if directory else shutil.which(name)
        if not found or not Path(found).is_file():
            raise PrerequisiteError(
                f"installed {name} unavailable via PATH/configured quartus_bin_dir; "
                "no tool installation or license substitution is permitted")
        tools[name] = str(Path(found).resolve())
        _, stdout, stderr = run.child([tools[name], "--version"], ROOT)
        version = stdout + stderr
        require(re.search(r"\b17\.1(?:\.|\b)", version) is not None,
                f"required Quartus 17.1 not identified by {name}")
        run.record["tool_versions"][name] = version.strip()
        run.save()
    require(len({str(Path(p).parent) for p in tools.values()}) == 1,
            "mixed Quartus installation directories")
    return tools


def coverage_script(revision, adapter_top):
    # Full post-fit only. Preserve all corners and unconstrained-path reports.
    return f"""project_open {{{revision}}}
if {{[get_global_assignment -name DEVICE] ne "{DEVICE}"}} {{
    error "FURNACE target device differs from actual Quartus project"
}}
if {{[get_global_assignment -name TOP_LEVEL_ENTITY] ne "{adapter_top}"}} {{
    error "FURNACE adapter top differs from actual Quartus project"
}}
create_timing_netlist
read_sdc
update_timing_netlist
report_clocks -file clocks.rpt
report_sdc -file constraints.rpt
check_timing -include {{no_clock multiple_clock generated_clock no_input_delay no_output_delay partial_input_delay partial_output_delay io_min_max_delay_consistency loops latches uncertainty}} -file constraint_coverage.rpt
report_ucp -file unconstrained_paths.rpt
set corner_index 0
foreach_in_collection oc [get_available_operating_conditions -all] {{
    set_operating_conditions $oc
    update_timing_netlist
    foreach kind {{setup hold recovery removal}} {{
        report_timing -$kind -npaths 100 -detail full_path -file corner-$corner_index-$kind.rpt
        set paths [get_timing_paths -$kind -npaths 1]
        puts "FURNACE_PATHS|$corner_index|$kind|[get_collection_size $paths]"
        foreach_in_collection path $paths {{
            puts "FURNACE_SLACK|$corner_index|$kind|[get_path_info $path -slack]"
        }}
    }}
    incr corner_index
}}
puts "FURNACE_CORNERS|$corner_index"
delete_timing_netlist
project_close
"""


def constraint_counts(text):
    """Validate every count column; retain the maximum per constraint category."""
    counts = {}
    summary_columns = None
    labels = {
        "illegal_clocks", "no_clock", "multiple_clock",
        "no_input_delay", "no_output_delay",
        "partial_input_delay", "partial_output_delay", "generated_clock",
        "io_min_max_delay_consistency", "loops", "latches", "uncertainty",
        "unconstrained_clocks", "unconstrained_input_ports",
        "unconstrained_input_port_paths", "unconstrained_output_ports",
        "unconstrained_output_port_paths",
        *(f"unconstrained_{kind}_paths" for kind in
          ("setup", "hold", "recovery", "removal")),
    }
    for line in text.splitlines():
        cells = [c.strip() for c in
                 line.strip().removeprefix(";").removesuffix(";").split(";")]
        if cells[0].lower() == "property":
            require(len(cells) >= 2 and all(cells[1:]) and
                    line.strip().endswith(";"),
                    f"unrecognized constraint-count header: {line.strip()}")
            summary_columns = len(cells)
            continue
        label = cells[0].lower().replace(" ", "_")
        if label in labels or (len(cells) >= 2 and "unconstrained" in label):
            require(len(cells) >= 2 and
                    line.strip().startswith(";") and line.strip().endswith(";") and
                    (summary_columns is None or len(cells) == summary_columns),
                    f"incomplete constraint-count row: {line.strip()}")
            require(all(re.fullmatch(r"\d+", cell) is not None
                        for cell in cells[1:]),
                    f"unrecognized constraint-count row: {line.strip()}")
            require(label not in counts, f"duplicate ambiguous constraint count: {label}")
            counts[label] = max(int(cell) for cell in cells[1:])
    require(counts, "no machine-readable TimeQuest constraint counts; retain report for review")
    require(all(v == 0 for v in counts.values()),
            f"unconstrained/ambiguous relevant paths require repair or independent diagnosis: {counts}")
    return counts


def validate_sta(data, stdout, build, clock, period, stderr=""):
    for text in (stdout, stderr):
        require(not re.search(r"(?:Error \(\d+\)|Warning \(10268\))", text),
                "forbidden Quartus diagnostic in timing-analysis output")
    for report in build.rglob("*.rpt"):
        require(not re.search(r"(?:Error \(\d+\)|Warning \(10268\))",
                              report.read_text()),
                f"forbidden Quartus diagnostic in timing report: {report.name}")
    summary = data["sta_summary"]
    require(summary["netlist_mode"] == "post_fit", "post-map fallback is not accepted")
    require(data["map_summary"].get("exists") is True, "missing real map report")
    for name in ("wns_setup_ns", "wns_hold_ns"):
        require(finite(summary[name], name) >= 0, f"negative {name}")
    clocks = [c for c in summary["clocks"] if c["name"] == clock]
    require(len(clocks) == 1 and
            0 < finite(clocks[0]["period_ns"], "clock period") == period <= 10,
            "actual clock constraint does not match admitted timing budget")
    corner_lines = [line for line in stdout.splitlines()
                    if line.startswith("FURNACE_CORNERS")]
    require(len(corner_lines) == 1 and
            re.fullmatch(r"FURNACE_CORNERS\|\d+", corner_lines[0]) is not None,
            "missing or malformed timing-corner count")
    corners = re.findall(r"^FURNACE_CORNERS\|(\d+)$", stdout, re.M)
    require(len(corners) == 1 and int(corners[0]) > 0, "missing analyzed timing corners")
    kinds = ("setup", "hold", "recovery", "removal")
    path_counts = {}
    for line in stdout.splitlines():
        if not line.startswith("FURNACE_PATHS"):
            continue
        match = re.fullmatch(
            r"FURNACE_PATHS\|(\d+)\|(setup|hold|recovery|removal)\|([01])", line)
        require(match is not None, f"malformed timing-path count: {line}")
        corner, kind, count = match.groups()
        key = (int(corner), kind)
        require(key[0] < int(corners[0]), "timing path count refers to an unreported corner")
        require(key not in path_counts, "duplicate ambiguous timing-path count")
        path_counts[key] = int(count)
    require(set(path_counts) == {(corner, kind)
                                for corner in range(int(corners[0])) for kind in kinds},
            "missing timing-path counts for reported corner analyses")
    rows = []
    seen = set()
    for line in stdout.splitlines():
        if not line.startswith("FURNACE_SLACK"):
            continue
        match = re.fullmatch(
            r"FURNACE_SLACK\|(\d+)\|(setup|hold|recovery|removal)\|(\S+)", line)
        require(match is not None, f"malformed timing-slack record: {line}")
        corner, kind, slack = match.groups()
        key = (int(corner), kind)
        require(key[0] < int(corners[0]), "timing slack refers to an unreported corner")
        require(key not in seen, "duplicate ambiguous timing-slack record")
        seen.add(key)
        rows.append((corner, kind, slack))
    for corner in range(int(corners[0])):
        for kind in kinds:
            report = build / f"corner-{corner}-{kind}.rpt"
            require(report.is_file(),
                    f"missing raw timing-corner report: {report.name}")
            require(report.read_text().strip(),
                    f"empty raw timing-corner report: {report.name}")
        for kind in ("setup", "hold"):
            require(path_counts[corner, kind] == 1,
                    f"no {kind} paths analyzed at corner {corner}")
    require(all(bool(count) == (key in seen) for key, count in path_counts.items()),
            "timing path presence differs from retained worst-path slack records")
    require(all(finite(float(s), "corner slack") >= 0 for _, _, s in rows),
            "negative setup/hold/recovery/removal corner slack")
    counts = {}
    for name in ("constraint_coverage.rpt", "unconstrained_paths.rpt"):
        report = build / name
        require(report.is_file(), f"missing constraint coverage report: {name}")
        counts[name] = constraint_counts(report.read_text())
    required_checks = {
        "no_clock", "multiple_clock", "generated_clock", "no_input_delay",
        "no_output_delay", "partial_input_delay", "partial_output_delay",
        "io_min_max_delay_consistency", "loops", "latches", "uncertainty",
    }
    require(required_checks <= set(counts["constraint_coverage.rpt"]),
            "not all required check_timing categories were reported")
    require({f"unconstrained_{kind}_paths" for kind in
             ("setup", "hold", "recovery", "removal")} <=
            set(counts["unconstrained_paths.rpt"]),
            "not all relevant unconstrained-path categories were reported")
    return {"corner_count": int(corners[0]), "worst_paths": rows,
            "path_counts": [{"corner": corner, "kind": kind, "count": count}
                            for (corner, kind), count in sorted(path_counts.items())],
            "constraint_counts": counts}


def sta(run, cfg, entry, width):
    tools = quartus_tools(run, cfg)
    project = relative_output(entry["project_dir"])
    build = run.path / f"quartus-width-{width}"
    build.mkdir()
    # Preserve project-relative layout, never import old DBs, reports or images.
    for name, digest in entry["implementation_inputs"].items():
        source = ROOT / name
        target = build / "project" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        require(sha(target) == digest, f"source changed while copying: {name}")
    cwd = build / "project" / project.relative_to(ROOT)
    revision = entry["revision"]
    for name in ("quartus_map", "quartus_fit"):
        _, stdout, stderr = run.child([tools[name], revision], cwd)
        require(not re.search(r"(?:Error \(\d+\)|Warning \(10268\))", stdout + stderr),
                f"forbidden diagnostic from {name}; inspect retained raw logs")
    for kind in ("map", "fit"):
        reports = list(cwd.rglob(f"{revision}.{kind}.rpt"))
        require(len(reports) == 1, f"missing or ambiguous actual {kind} report")
        text = reports[0].read_text()
        require(not re.search(r"(?:Error \(\d+\)|Warning \(10268\))", text),
                f"forbidden diagnostic in actual {kind} report")
        if kind == "map":
            require(all(name in text for name in ("furnace_x1_top", *HIERARCHY)),
                    "actual map report does not retain required core functional hierarchy")
    report = build / "quartus-sta.json"
    data = gate_command(run, [
        "vulcan", "hardware", "fpga", "quartus-sta",
        "--project-dir", str(cwd.relative_to(ROOT)), "--revision", revision,
        "--clock", entry["clock"], "--min-setup-slack-ns", "0",
        "--min-hold-slack-ns", "0", "--quartus-bin-dir",
        str(Path(tools["quartus_sta"]).parent), "--npaths", "100",
        "--timeout-s", "7200", "--output", str(report),
    ], report)
    script = cwd / "furnace-coverage.tcl"
    script.write_text(coverage_script(revision, entry["adapter_top"]))
    _, stdout, stderr = run.child([tools["quartus_sta"], "-t", script.name], cwd)
    measured = validate_sta(data, stdout, cwd, entry["clock"], entry["clock_period_ns"],
                            stderr)
    run.record["results"][f"sta-{width}"] = measured
    run.record["results"]["scope"] = (
        "actual integration project; raw constraints/corner reports require independent review")


def validate_physical_metadata(meta, expected, previous):
    require(isinstance(meta, dict), "physical metadata must be a JSON object")
    for name in ("width", "pcie_generation", "pcie_lanes"):
        require(type(meta.get(name)) is int, f"physical {name} must be an integer")
    require(all(meta.get(k) == v for k, v in expected.items()),
            "physical metadata differs from stimulus/image/source/device/clock/link binding")
    sequence = meta.get("run_sequence")
    require(type(sequence) is int and sequence >= 0, "missing physical execution sequence")
    require(previous is None or sequence == previous + 1,
            "physical runs are not three consecutive executions")
    return sequence


def validate_physical_runs(data):
    require(isinstance(data, dict), "physical gate report must be a JSON object")
    require(type(data.get("requested_runs")) is int and data["requested_runs"] == 3,
            "native gate did not execute three physical runs")
    rows = data.get("runs")
    require(isinstance(rows, list) and len(rows) == 3,
            "native gate must report exactly three physical run objects")
    probe = data.get("reg57_probe")
    require(isinstance(probe, dict) and type(probe.get("exit_code")) is int and
            probe["exit_code"] == 0, "physical identity probe failed")
    require(data.get("deterministic_across_runs") is True, "nondeterministic physical runs")
    for index, row in enumerate(rows, 1):
        require(isinstance(row, dict), "physical run must be a JSON object")
        require(type(row.get("run_index")) is int and row["run_index"] == index and
                type(row.get("exit_code")) is int and row["exit_code"] == 0 and
                row.get("passed") is True,
                "failed or out-of-order physical run")


def hil(run, cfg, entry, width):
    export_bundle(run)
    directory = run.path / f"width-{width}"
    nonce = uuid.uuid4().hex
    expected = {
        "origin": "physical", "transport": "PCIe", "pcie_generation": 3, "pcie_lanes": 8,
        "width": width, "device": DEVICE, "top": "furnace_x1_top",
        "clock_period_ns": entry["clock_period_ns"],
        "image_sha256": sha(input_path(entry["image"])),
        "rtl_hashes": {k: v for k, v in inventory().items() if k.startswith("rtl/")},
        "adapter_sources": entry["adapter_sources"], "constraints": entry["constraints"],
        "implementation_inputs": entry["implementation_inputs"],
        "public_pin_map_sha256": sha(input_path(entry["public_pin_map"])),
        "vector_sha256": sha(directory / "vectors.txt"), "nonce": nonce,
    }
    command = entry["remote_test_cmd"]
    for token, value in (("NONCE", nonce), ("WIDTH", str(width)),
                         ("VECTOR_SHA256", expected["vector_sha256"])):
        command = command.replace(f"@FURNACE_{token}@", value)
    require("@FURNACE_" not in command, "unresolved remote capture binding token")
    write_json(run.path / "physical-request.json", expected)
    report = run.path / f"board-hil-{width}.json"
    argv = ["vulcan", "hardware", "fpga", "board-hil", "--remote-test-cmd", command,
            "--runs", "3", "--timeout-s", "3600", "--output", str(report.relative_to(ROOT))]
    for key, option in (("bridge_dir", "--bridge-dir"), ("chip_id", "--chip-id"),
                        ("tools_win_dir", "--tools-win-dir")):
        if key in cfg:
            argv += [option, str(cfg[key])]
    # One CLI invocation contains three independently executed 3600 s runs.
    # Run.child's default 7200 s deadline cannot safely enclose that operation.
    import verify
    old_timeout = verify.TIMEOUT
    try:
        verify.TIMEOUT = 4 * 3600
        run.record["timeout_s"] = verify.TIMEOUT
        run.save()
        data = gate_command(run, argv, report)
    finally:
        verify.TIMEOUT = old_timeout
    validate_physical_runs(data)
    sequence = None
    hashes, comparisons = [], []
    for index, row in enumerate(data["runs"], 1):
        capture = run.path / f"physical-{width}-{index}.trace"
        capture.write_text(row["stdout"])
        (run.path / f"physical-{width}-{index}.stderr").write_text(row["stderr"])
        metadata = [line.removeprefix("FURNACE_HIL_METADATA ")
                    for line in row["stderr"].splitlines()
                    if line.startswith("FURNACE_HIL_METADATA ")]
        require(len(metadata) == 1, "physical capture must include exactly one metadata record")
        sequence = validate_physical_metadata(
            parse_json_object(metadata[0], f"physical run {index} metadata"), expected, sequence)
        comparisons.append(score_capture(directory, capture))
        hashes.append(sha(capture))
    require(len(set(hashes)) == 1, "physical public-pin captures differ")
    run.record["results"][f"hil-{width}"] = {
        "physical_runs": 3, "trace_hashes": hashes, "comparisons": comparisons,
        "last_execution_sequence": sequence, "request": expected,
        "scope": "physical attribution still requires independent adapter/image/bridge review"}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", required=True, choices=("prerequisites", "lint", "sta", "hil"))
    parser.add_argument("--width", type=int, choices=(64, 512))
    parser.add_argument("--board-config", default="fpga/board_hil.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run = Run(relative_output(args.out), f"native-gate-{args.mode}", None)
    label = f"{args.mode}-{args.width}" if args.width else args.mode
    run.track(label, status="running", width=args.width)
    try:
        run.record["tool_versions"]["python3"] = sys.version
        _, stdout, stderr = run.child(["vulcan", "hardware", "--version"], ROOT)
        run.record["tool_versions"]["vulcan"] = (stdout + stderr).strip()
        if args.mode == "lint":
            require(args.width is None, "lint scans both parameterized datapaths together")
            lint(run)
        elif args.mode == "prerequisites":
            require(args.width is None, "prerequisites covers both width configurations")
            for width in (64, 512):
                cfg, _ = load_binding(run, args.board_config, width, physical=True)
                quartus_tools(run, cfg)
        else:
            require(args.width is not None, "sta/hil requires explicit --width")
            cfg, entry = load_binding(run, args.board_config, args.width,
                                      physical=args.mode == "hil")
            if args.mode == "sta":
                sta(run, cfg, entry, args.width)
            else:
                hil(run, cfg, entry, args.width)
        retain_inputs(run, [ROOT / name for name in run.record.get("integration_hashes", {})])
        require(inventory() == run.record["source_hashes"], "deliverable changed during native gate")
        run.track(label, status="passed", raw_receipt=run.commands[-1]["receipt"],
                  measured=run.record["results"])
        run.finish("passed")
    except (AssertionError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        run.finish("failed", error)
        print(f"Native gate failed: {error}; receipt={run.path.relative_to(ROOT)}/receipt.json",
              file=sys.stderr)
        return 2 if isinstance(error, PrerequisiteError) else 1
    print(run.path.relative_to(ROOT) / "receipt.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
