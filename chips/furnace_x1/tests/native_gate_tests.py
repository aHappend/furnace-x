#!/usr/bin/env python3
"""Unit tests for native orchestration, never timing or physical-HIL evidence.

Use --out PROJECT_RELATIVE_DIRECTORY for fresh source-bound receipts and raw
unittest logs. --fixtures is the child entrypoint for disposable unit fixtures.
Neither selector establishes timing closure or physical hardware coverage.
"""

import argparse
import copy
import errno
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_gates as gates
from scoreboard import FunctionalMismatch, check_trace
from native_vectors import export_bundle, score_capture, verify_bundle
from verify import ROOT, Run, inventory, relative_output, write_json


FIXTURES = None
CHECKS = ("no_clock multiple_clock generated_clock no_input_delay no_output_delay "
          "partial_input_delay partial_output_delay io_min_max_delay_consistency "
          "loops latches uncertainty").split()


def timing_path_counts(corners):
    return "".join(f"FURNACE_PATHS|{corner}|{kind}|{int(kind in ('setup', 'hold'))}\n"
                   for corner in range(corners)
                   for kind in ("setup", "hold", "recovery", "removal"))


class NativeGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = FIXTURES / self._testMethodName
        self.directory.mkdir(parents=True)

    def test_json_update_preserves_previous_receipt_on_storage_failure(self):
        receipt = self.directory / "receipt.json"
        previous = {"status": "running", "commands": [{"exit_code": None}]}
        write_json(receipt, previous)
        original = receipt.read_bytes()
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation):
                with patch(f"verify.os.{operation}",
                           side_effect=OSError(errno.ENOSPC, "synthetic storage failure")), \
                        self.assertRaises(OSError):
                    write_json(receipt, {"status": "passed"})
                self.assertEqual(receipt.read_bytes(), original)
                self.assertEqual(json.loads(receipt.read_text()), previous)
        pending = list(self.directory.glob(".receipt.json.*.pending"))
        self.assertEqual(len(pending), 2)
        for path in pending:
            self.assertEqual(json.loads(path.read_text()), {"status": "passed"})

    def test_json_update_serialization_failure_preserves_previous_receipt(self):
        receipt = self.directory / "receipt.json"
        write_json(receipt, {"status": "running"})
        original = receipt.read_bytes()
        with self.assertRaises(TypeError):
            write_json(receipt, {"status": object()})
        self.assertEqual(receipt.read_bytes(), original)
        write_json(receipt, {"status": "completed", "exit_code": 0})
        self.assertEqual(json.loads(receipt.read_text()),
                         {"status": "completed", "exit_code": 0})

    def test_child_receipt_is_retained_before_execution(self):
        run = Run(self.directory / "receipts", "pending-child-receipt-test", None)
        run.record["tool_versions"]["python3"] = sys.version
        receipt = run.path / "commands" / "0000" / "receipt.json"
        script = (
            "import json, pathlib, sys; "
            "receipt = pathlib.Path(sys.argv[1]); "
            "record = json.loads(receipt.read_text()); "
            "parent = json.loads((receipt.parents[2] / 'receipt.json').read_text()); "
            "assert record['status'] == 'running'; "
            "assert record['exit_code'] is None; "
            "assert record['argv'][3] == sys.argv[1]; "
            "assert record['cwd'] == str(pathlib.Path.cwd()); "
            "assert record['input_hashes']; "
            "assert parent['commands'][0] == record; "
            "print('pending child receipt observed')"
        )
        command, stdout, _ = run.child(
            [sys.executable, "-c", script, str(receipt)], ROOT)
        self.assertEqual(stdout.strip(), "pending child receipt observed")
        self.assertEqual(command["status"], "completed")
        retained = json.loads(receipt.read_text())
        self.assertEqual(retained, command)
        self.assertEqual(retained["exit_code"], 0)
        run.finish("passed")

    def test_child_receipt_binds_inputs_relative_to_child_working_directory(self):
        working = self.directory / "working"
        working.mkdir()
        source = working / "payload.txt"
        source.write_text("synthetic receipt input, not product evidence\n")
        run = Run(self.directory / "receipts", "child-input-binding-test", None)
        run.record["tool_versions"]["python3"] = sys.version
        command, stdout, _ = run.child(
            [sys.executable, "-c",
             "from pathlib import Path; import sys; "
             "print(Path(sys.argv[1]).read_text(), end='')", source.name],
            working)
        self.assertEqual(stdout, source.read_text())
        self.assertEqual(command["exit_code"], 0)
        self.assertFalse(command["timeout"])
        self.assertEqual(command["input_hashes"].get(str(source.resolve())),
                         gates.sha(source))
        retained = json.loads((run.path / command["receipt"]).read_text())
        self.assertEqual(retained["input_hashes"], command["input_hashes"])
        run.finish("passed")

    def test_child_receipt_accepts_long_nonfile_arguments(self):
        run = Run(self.directory / "receipts", "long-child-argument-test", None)
        run.record["tool_versions"]["python3"] = sys.version
        argument = "x" * 4096
        command, stdout, _ = run.child(
            [sys.executable, "-c", "import sys; print(len(sys.argv[1]))", argument],
            ROOT)
        self.assertEqual(stdout.strip(), str(len(argument)))
        self.assertEqual(command["exit_code"], 0)
        self.assertNotIn(str(ROOT / argument), command["input_hashes"])
        self.assertEqual(json.loads((run.path / command["receipt"]).read_text()),
                         command)
        run.finish("passed")

    def test_run_success_rejects_missing_or_changed_child_evidence(self):
        for artifact in ("receipt", "stdout", "stderr"):
            for alteration in ("missing", "changed"):
                with self.subTest(artifact=artifact, alteration=alteration):
                    run = Run(self.directory / "receipts", "evidence-integrity-test", None)
                    command, _, _ = run.child(
                        [sys.executable, "-c",
                         "import sys; print('fixture'); print('fixture', file=sys.stderr)"],
                        ROOT)
                    path = run.path / command[artifact]
                    if alteration == "missing":
                        path.rename(path.with_suffix(path.suffix + ".retained"))
                    else:
                        path.write_text("{}\n" if artifact == "receipt" else "changed\n")
                    with self.assertRaisesRegex(
                            FunctionalMismatch, "child evidence"):
                        run.finish("passed")
                    self.assertNotEqual(
                        json.loads((run.path / "receipt.json").read_text())["status"],
                        "passed")
                    run.finish("failed", RuntimeError("deliberately altered unit fixture"))

    def test_run_success_accepts_retained_expected_nonzero_child(self):
        run = Run(self.directory / "receipts", "expected-rejection-evidence-test", None)
        command, _, _ = run.child(
            [sys.executable, "-c", "raise SystemExit(7)"], ROOT, allowed=(7,))
        self.assertEqual(command["exit_code"], 7)
        self.assertFalse(command["timeout"])
        run.finish("passed")
        self.assertEqual(json.loads((run.path / "receipt.json").read_text())["status"],
                         "passed")

    def test_run_success_rejects_missing_or_changed_source_snapshot(self):
        for alteration in ("missing", "changed"):
            with self.subTest(alteration=alteration):
                run = Run(self.directory / "receipts", "source-integrity-test", None)
                name = next(iter(run.record["source_hashes"]))
                snapshot = run.path / "source" / name
                if alteration == "missing":
                    snapshot.rename(snapshot.with_suffix(snapshot.suffix + ".retained"))
                else:
                    snapshot.write_bytes(snapshot.read_bytes() + b"\n")
                with self.assertRaisesRegex(FunctionalMismatch, "source snapshot"):
                    run.finish("passed")
                self.assertNotEqual(
                    json.loads((run.path / "receipt.json").read_text())["status"],
                    "passed")
                run.finish("failed", RuntimeError("deliberately altered source fixture"))

    def test_run_success_rejects_changed_deliverable_inventory(self):
        run = Run(self.directory / "receipts", "source-freshness-test", None)
        changed = dict(run.record["source_hashes"])
        changed[next(iter(changed))] = "0" * 64
        with patch("verify.inventory", return_value=changed), \
                self.assertRaisesRegex(FunctionalMismatch, "sources changed"):
            run.finish("passed")
        self.assertNotEqual(
            json.loads((run.path / "receipt.json").read_text())["status"], "passed")
        run.finish("failed", RuntimeError("synthetic changed-inventory fixture"))

    def test_run_success_rejects_caught_unexpected_child_exit(self):
        for allowed in ((0,), (7,)):
            with self.subTest(allowed=allowed):
                run = Run(self.directory / "receipts", "unexpected-child-exit-test", None)
                with self.assertRaisesRegex(RuntimeError, "tool exit 9"):
                    run.child([sys.executable, "-c", "raise SystemExit(9)"],
                              ROOT, allowed=allowed)
                with self.assertRaisesRegex(FunctionalMismatch, "unexpected child exit"):
                    run.finish("passed")
                self.assertNotEqual(
                    json.loads((run.path / "receipt.json").read_text())["status"],
                    "passed")
                run.finish("failed", RuntimeError("deliberate unexpected unit-fixture exit"))

    def test_run_success_retains_caller_adjudicated_child_exit(self):
        run = Run(self.directory / "receipts", "adjudicated-child-exit-test", None)
        command, _, _ = run.child(
            [sys.executable, "-c", "raise SystemExit(9)"], ROOT, allowed=None)
        self.assertEqual(command["exit_code"], 9)
        self.assertIsNone(command.get("allowed_exit_codes", "missing"))
        run.finish("passed")

    def test_protocol_error_crc_fields_remain_stable_across_stalled_edge(self):
        # Truncated synthetic traces exercise edge stability, not product coverage.
        result = {"id": 0, "protocol": 1, "mismatch": 0}
        stalled = {"reset": False, "ready": 0, "payload": None, "result": result}
        reset = {"reset": True, "ready": 0, "payload": None, "result": None}
        inputs = (1, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        rows = [
            {"cycle": 0, "pulse": False, "inputs": inputs, "pre": stalled,
             "post": stalled, "event": None, "mr": 0, "cr": 0, "accepted": None},
            {"cycle": 1, "pulse": False, "inputs": (0,) * 10, "pre": reset,
             "post": reset, "event": None, "mr": 0, "cr": 0, "accepted": None},
        ]
        (self.directory / "expected.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n")

        def observation(phase, cycle, outputs, pins):
            return (f"{phase} {cycle} " +
                    " ".join(f"{value:x}" for value in (*outputs, *pins)) + "\n")

        baseline = (0, 0, 0, 0, 0, 1, 0x1234, 0x5678, 0, 1)
        for field in (None, 6, 7):
            post = list(baseline)
            if field is not None:
                post[field] ^= 1
            trace = "".join(observation(phase, -1, (0,) * 10, (0,) * 10)
                            for phase in ("T0", "BP", "BN"))
            trace += observation("A", 0, baseline, inputs)
            trace += observation("P", 0, post, inputs)
            trace += observation("N", 0, post, inputs)
            trace += "".join(observation(phase, 1, (0,) * 10, (0,) * 10)
                             for phase in ("A", "P", "N"))
            (self.directory / "trace.txt").write_text(trace)
            expected = ("insufficient observed independent stalls" if field is None
                        else "stalled result changed across edge")
            with self.subTest(field=field), self.assertRaisesRegex(
                    FunctionalMismatch, expected):
                check_trace(self.directory, {"cycles": 2, "packets": []}, False)

    def test_native_protocol_error_crc_fields_remain_stable_while_stalled(self):
        result = {"id": 0, "protocol": 1, "mismatch": 0}
        stalled = {"reset": False, "ready": 0, "payload": None, "result": result}
        pins = (1, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        rows = [{"cycle": cycle, "pulse": False, "inputs": pins, "pre": stalled}
                for cycle in range(2)]
        (self.directory / "expected.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n")
        write_json(self.directory / "manifest.json",
                   {"cycles": 2, "packets": [], "width": 64})
        baseline = (0, 0, 0, 0, 0, 1, 0x1234, 0x5678, 0, 1)
        capture = self.directory / "capture.trace"
        for field in (None, 6, 7):
            changed = list(baseline)
            if field is not None:
                changed[field] ^= 1
            capture.write_text("".join(
                f"A {cycle} " +
                " ".join(f"{value:x}" for value in (*outputs, *pins)) + "\n"
                for cycle, outputs in enumerate((baseline, changed))))
            expected = ("independent physical stalls not observed" if field is None
                        else "stalled result changed across edge")
            with self.subTest(field=field), self.assertRaisesRegex(
                    FunctionalMismatch, expected):
                score_capture(self.directory, capture)

    def test_missing_binding_reports_adapter_handoff(self):
        run = Mock()
        missing = str((self.directory / "absent.json").relative_to(ROOT))
        for width in (64, 512):
            with self.subTest(width=width):
                with self.assertRaises(gates.PrerequisiteError) as caught:
                    gates.load_binding(run, missing, width, physical=True)
                message = str(caught.exception)
                self.assertIn(missing, message)
                self.assertIn("platform provider/shared-runtime owner", message)
                self.assertIn("authoritative bridge RTL/ABI", message)
                self.assertIn("independently admit ownership, source selectors and exact commands",
                              message)
                self.assertIn("before Designer implements", message)
        self.assertEqual(run.mock_calls, [])

    def test_native_bundle_binds_every_consumed_input(self):
        run = Mock()
        run.path = self.directory / "bundle"
        run.path.mkdir()
        run.record = {"results": {}}
        export_bundle(run)
        contract_path = run.path / "native-contract.json"
        original = json.loads(contract_path.read_text())
        self.assertEqual(verify_bundle(run.path), original)
        for width in (64, 512):
            for name in ("vectors.txt", "expected.jsonl", "manifest.json",
                         "quartus/top.qsf", "quartus/top.qpf",
                         "quartus/timing.sdc", "quartus/reports.tcl",
                         *[f"quartus/{name}" for name in inventory()
                           if name.startswith("rtl/")]):
                relative = f"width-{width}/{name}"
                changed = copy.deepcopy(original)
                del changed["bundle_hashes"][relative]
                write_json(contract_path, changed)
                for missing_file in (False, True):
                    source = run.path / relative
                    content = source.read_bytes()
                    if missing_file:
                        source.unlink()
                    try:
                        with self.subTest(input=relative, missing_file=missing_file), \
                                self.assertRaisesRegex(FunctionalMismatch,
                                                       "bundle input closure"):
                            verify_bundle(run.path)
                    finally:
                        if missing_file:
                            source.write_bytes(content)
        write_json(contract_path, original)
        self.assertEqual(verify_bundle(run.path), original)

    def test_native_json_rejects_ambiguous_or_nonfinite_fields(self):
        report = self.directory / "report.json"
        for text in (
                '{"status":"failed","status":"passed"}',
                '{"widths":{"64":{"clock_period_ns":11,"clock_period_ns":10}}}',
                '{"wns_setup_ns":NaN}',
                '{"wns_hold_ns":Infinity}',
                '{"wns_hold_ns":-Infinity}',
                '{"unexamined_field":1e999}',
                '{"nested":[{"width":64,"width":512}]}'):
            report.write_text(text)
            with self.subTest(text=text), self.assertRaises(FunctionalMismatch):
                gates.load_json(report)
        report.write_text('{"status":"passed","width":64,"slack":0.25}')
        self.assertEqual(gates.load_json(report),
                         {"status": "passed", "width": 64, "slack": 0.25})

    def test_constraint_counts_fail_closed(self):
        self.assertEqual(gates.constraint_counts("; no_clock ; 0 ;"), {"no_clock": 0})
        for text in ("", "PASS", "; no_clock ; unknown ;", "; no_clock ; 1 ;",
                     "; no_clock ; 0 ;\n; no_clock ; 0 ;"):
            with self.subTest(text=text), self.assertRaises(FunctionalMismatch):
                gates.constraint_counts(text)

    def test_constraint_counts_check_every_analysis_column(self):
        labels = ("Unconstrained Clocks", "Unconstrained Input Ports",
                  "Unconstrained Input Port Paths", "Unconstrained Output Ports",
                  "Unconstrained Output Port Paths")
        header = "; Property ; Setup ; Hold ;\n"
        clear = header + "\n".join(f"; {label} ; 0 ; 0 ;" for label in labels)
        self.assertEqual(gates.constraint_counts(clear),
                         {label.lower().replace(" ", "_"): 0 for label in labels})
        for label in labels:
            for counts in ("0 ; 679", "75819 ; 0", "0 ; unknown", "0 ; -1",
                           "0 ;", "0 ; 0 ; 1361"):
                text = clear.replace(f"; {label} ; 0 ; 0 ;",
                                     f"; {label} ; {counts} ;")
                with self.subTest(label=label, counts=counts), \
                        self.assertRaises(FunctionalMismatch):
                    gates.constraint_counts(text)

    def test_constraint_summary_rejects_illegal_clocks_and_truncated_columns(self):
        labels = ("Illegal Clocks", "Unconstrained Clocks",
                  "Unconstrained Input Ports", "Unconstrained Input Port Paths",
                  "Unconstrained Output Ports", "Unconstrained Output Port Paths")
        header = "; Property ; Setup ; Hold ;\n"
        clear = header + "\n".join(f"; {label} ; 0 ; 0 ;" for label in labels)
        self.assertEqual(gates.constraint_counts(clear),
                         {label.lower().replace(" ", "_"): 0 for label in labels})
        for label in labels:
            for row in (f"; {label} ; 1 ; 0 ;",
                        f"; {label} ; 0 ; 1 ;",
                        f"; {label} ; 0 ;",
                        f"; {label} ; 0 ; 0",
                        f"; {label} ; 0 ; 0 ; 0 ;"):
                text = clear.replace(f"; {label} ; 0 ; 0 ;", row)
                with self.subTest(label=label, row=row), \
                        self.assertRaises(FunctionalMismatch):
                    gates.constraint_counts(text)

    def test_constraint_counts_reject_label_only_rows(self):
        labels = ("Illegal Clocks", "Unconstrained Clocks",
                  "Unconstrained Setup Paths", *CHECKS)
        clear = "; no_clock ; 0 ;\n"
        self.assertEqual(gates.constraint_counts(clear), {"no_clock": 0})
        self.assertEqual(gates.constraint_counts(
            "Unconstrained Paths\nConstraint Coverage\n" + clear), {"no_clock": 0})
        for label in labels:
            for row in (label, f"; {label}", f"; {label} ;"):
                with self.subTest(row=row), self.assertRaisesRegex(
                        FunctionalMismatch, "incomplete constraint-count row"):
                    gates.constraint_counts(clear + row + "\n")

    def test_incomplete_configuration_is_explicit_prerequisite_failure(self):
        config = self.directory / "incomplete.json"
        write_json(config, {"furnace_x1": {"device": gates.DEVICE}})
        run = Mock()
        run.record = {}
        run.path = self.directory / "retained"
        run.path.mkdir()
        with self.assertRaisesRegex(gates.PrerequisiteError, "missing required.*widths"):
            gates.load_binding(run, str(config.relative_to(ROOT)), 512)

    def test_sta_reports_reject_incomplete_or_negative_results(self):
        for corner in range(2):
            for kind in ("setup", "hold", "recovery", "removal"):
                (self.directory / f"corner-{corner}-{kind}.rpt").write_text(
                    "Synthetic corner report; not timing evidence.\n")
        (self.directory / "constraint_coverage.rpt").write_text(
            "\n".join(f"; {name} ; 0 ;" for name in CHECKS))
        (self.directory / "unconstrained_paths.rpt").write_text(
            "\n".join(f"; Unconstrained {kind} Paths ; 0 ;" for kind in
                      ("Setup", "Hold", "Recovery", "Removal")))
        data = {"map_summary": {"exists": True}, "sta_summary": {
            "netlist_mode": "post_fit", "wns_setup_ns": 0.2, "wns_hold_ns": 0.1,
            "clocks": [{"name": "core_clk", "period_ns": 10.0}],
        }}
        stdout = ("FURNACE_CORNERS|2\nFURNACE_SLACK|0|setup|0.2\n"
                  "FURNACE_SLACK|0|hold|0.1\nFURNACE_SLACK|1|setup|0.3\n"
                  "FURNACE_SLACK|1|hold|0.4\n") + timing_path_counts(2)
        self.assertEqual(gates.validate_sta(data, stdout, self.directory, "core_clk", 10)
                         ["corner_count"], 2)
        for diagnostic in ("Error (272006): invalid timing netlist",
                           "Error (332000): timing analysis failed",
                           "Warning (10268): assignment ignored"):
            with self.subTest(diagnostic=diagnostic, stream="stdout"), \
                    self.assertRaisesRegex(FunctionalMismatch, "forbidden Quartus diagnostic"):
                gates.validate_sta(data, stdout + diagnostic + "\n",
                                   self.directory, "core_clk", 10)
            with self.subTest(diagnostic=diagnostic, stream="stderr"), \
                    self.assertRaisesRegex(FunctionalMismatch, "forbidden Quartus diagnostic"):
                gates.validate_sta(data, stdout, self.directory, "core_clk", 10,
                                   stderr=diagnostic)
            report = self.directory / "corner-0-setup.rpt"
            report.write_text(diagnostic + "\n")
            with self.subTest(diagnostic=diagnostic, stream="report"), \
                    self.assertRaisesRegex(FunctionalMismatch, "forbidden Quartus diagnostic"):
                gates.validate_sta(data, stdout, self.directory, "core_clk", 10)
            report.write_text("Synthetic corner report; not timing evidence.\n")
        for field, value in (("netlist_mode", "post_map"), ("wns_setup_ns", -0.01),
                             ("wns_hold_ns", -0.242), ("wns_hold_ns", None),
                             ("wns_setup_ns", float("nan"))):
            changed = copy.deepcopy(data)
            changed["sta_summary"][field] = value
            with self.subTest(field=field), self.assertRaises(FunctionalMismatch):
                gates.validate_sta(changed, stdout, self.directory, "core_clk", 10)
        with self.assertRaises(FunctionalMismatch):
            gates.validate_sta(data, stdout.replace("FURNACE_SLACK|1|hold|0.4\n", ""),
                               self.directory, "core_clk", 10)
        with self.assertRaises(FunctionalMismatch):
            gates.validate_sta(data, stdout.replace("|hold|0.4", "|hold|-0.1"),
                               self.directory, "core_clk", 10)
        for changed in (
                stdout + "FURNACE_SLACK|0|setup|0.5\n",
                stdout + "FURNACE_SLACK|2|setup|0.5\n",
                stdout + "FURNACE_SLACK|0|unexpected|0.5\n",
                stdout.replace("|hold|0.4", "|hold|nan")):
            with self.subTest(stdout=changed), self.assertRaises(FunctionalMismatch):
                gates.validate_sta(data, changed, self.directory, "core_clk", 10)
        (self.directory / "unconstrained_paths.rpt").write_text(
            "; Unconstrained Setup Paths ; 0 ;")
        with self.assertRaises(FunctionalMismatch):
            gates.validate_sta(data, stdout, self.directory, "core_clk", 10)
        (self.directory / "constraint_coverage.rpt").write_text("; no_clock ; 0 ;")
        with self.assertRaises(FunctionalMismatch):
            gates.validate_sta(data, stdout, self.directory, "core_clk", 10)

    def test_sta_requires_retained_nonempty_reports_for_every_corner(self):
        (self.directory / "constraint_coverage.rpt").write_text(
            "\n".join(f"; {name} ; 0 ;" for name in CHECKS))
        (self.directory / "unconstrained_paths.rpt").write_text(
            "\n".join(f"; Unconstrained {kind} Paths ; 0 ;" for kind in
                      ("Setup", "Hold", "Recovery", "Removal")))
        data = {"map_summary": {"exists": True}, "sta_summary": {
            "netlist_mode": "post_fit", "wns_setup_ns": 0.2, "wns_hold_ns": 0.1,
            "clocks": [{"name": "core_clk", "period_ns": 10.0}],
        }}
        stdout = ("FURNACE_CORNERS|2\nFURNACE_SLACK|0|setup|0.2\n"
                  "FURNACE_SLACK|0|hold|0.1\nFURNACE_SLACK|1|setup|0.3\n"
                  "FURNACE_SLACK|1|hold|0.4\n") + timing_path_counts(2)
        reports = [self.directory / f"corner-{corner}-{kind}.rpt"
                   for corner in range(2)
                   for kind in ("setup", "hold", "recovery", "removal")]
        content = "Synthetic corner report; not timing evidence.\n"
        for report in reports:
            report.write_text(content)
        self.assertEqual(gates.validate_sta(data, stdout, self.directory, "core_clk", 10)
                         ["corner_count"], 2)
        for report in reports:
            for damage in ("missing", "empty", "whitespace"):
                if damage == "missing":
                    report.unlink()
                else:
                    report.write_text("" if damage == "empty" else " \n\t")
                with self.subTest(report=report.name, damage=damage), \
                        self.assertRaisesRegex(FunctionalMismatch, "corner report"):
                    gates.validate_sta(data, stdout, self.directory, "core_clk", 10)
                report.write_text(content)

    def test_sta_requires_explicit_path_presence_for_every_analysis(self):
        for kind in ("setup", "hold", "recovery", "removal"):
            (self.directory / f"corner-0-{kind}.rpt").write_text(
                "Synthetic path-presence fixture; not timing evidence.\n")
        (self.directory / "constraint_coverage.rpt").write_text(
            "\n".join(f"; {name} ; 0 ;" for name in CHECKS))
        (self.directory / "unconstrained_paths.rpt").write_text(
            "\n".join(f"; Unconstrained {kind} Paths ; 0 ;" for kind in
                      ("Setup", "Hold", "Recovery", "Removal")))
        data = {"map_summary": {"exists": True}, "sta_summary": {
            "netlist_mode": "post_fit", "wns_setup_ns": 0.2, "wns_hold_ns": 0.1,
            "clocks": [{"name": "core_clk", "period_ns": 10.0}],
        }}
        stdout = ("FURNACE_CORNERS|1\nFURNACE_SLACK|0|setup|0.2\n"
                  "FURNACE_SLACK|0|hold|0.1\n") + timing_path_counts(1)
        validate = lambda text: gates.validate_sta(
            data, text, self.directory, "core_clk", 10)
        self.assertEqual(validate(stdout)["corner_count"], 1)
        for kind in ("setup", "hold", "recovery", "removal"):
            row = f"FURNACE_PATHS|0|{kind}|{int(kind in ('setup', 'hold'))}\n"
            for replacement in ("", row + row,
                                f"FURNACE_PATHS|1|{kind}|0\n",
                                f"FURNACE_PATHS|0|{kind}|unknown\n",
                                f"FURNACE_PATHS|0|{kind}|2\n"):
                with self.subTest(kind=kind, replacement=replacement), \
                        self.assertRaisesRegex(FunctionalMismatch, "path"):
                    validate(stdout.replace(row, replacement))
        for kind in ("recovery", "removal"):
            absent = f"FURNACE_PATHS|0|{kind}|0\n"
            present = f"FURNACE_PATHS|0|{kind}|1\n"
            with self.subTest(kind=kind, damage="missing slack"), \
                    self.assertRaisesRegex(FunctionalMismatch, "path"):
                validate(stdout.replace(absent, present))
            with self.subTest(kind=kind, damage="unexpected slack"), \
                    self.assertRaisesRegex(FunctionalMismatch, "path"):
                validate(stdout + f"FURNACE_SLACK|0|{kind}|0.1\n")
            observed = stdout.replace(absent, present) + f"FURNACE_SLACK|0|{kind}|0.1\n"
            self.assertEqual(validate(observed)["corner_count"], 1)
            with self.subTest(kind=kind, damage="negative slack"), \
                    self.assertRaises(FunctionalMismatch):
                validate(observed.replace(f"|{kind}|0.1", f"|{kind}|-0.1"))
        for kind in ("setup", "hold"):
            no_paths = stdout.replace(f"FURNACE_PATHS|0|{kind}|1",
                                      f"FURNACE_PATHS|0|{kind}|0")
            no_paths = no_paths.replace(
                f"FURNACE_SLACK|0|{kind}|{'0.2' if kind == 'setup' else '0.1'}\n", "")
            with self.subTest(kind=kind, damage="no synchronous paths"), \
                    self.assertRaisesRegex(FunctionalMismatch, "paths analyzed"):
                validate(no_paths)

    def test_physical_identity_and_consecutive_execution_required(self):
        expected = {"origin": "physical", "width": 64, "nonce": "1234",
                    "pcie_generation": 3, "pcie_lanes": 8, "clock_period_ns": 10,
                    "image_sha256": "a" * 64, "vector_sha256": "b" * 64}
        meta = dict(expected, run_sequence=8)
        self.assertEqual(gates.validate_physical_metadata(meta, expected, 7), 8)
        for field, value in (("origin", "simulation"), ("width", 512),
                             ("width", 64.0), ("pcie_generation", 3.0),
                             ("pcie_lanes", 8.0),
                             ("nonce", "stale"), ("pcie_lanes", 4),
                             ("clock_period_ns", 11), ("image_sha256", "c" * 64),
                             ("vector_sha256", "c" * 64), ("run_sequence", 9)):
            changed = dict(meta, **{field: value})
            with self.subTest(field=field), self.assertRaises(FunctionalMismatch):
                gates.validate_physical_metadata(changed, expected, 7)

    def test_zero_exit_or_pass_text_is_not_native_verdict(self):
        report = self.directory / "report.json"
        run = Mock()
        run.child.return_value = ({"exit_code": 0, "receipt": "synthetic-unit-only"}, "PASS", "")
        with self.assertRaises(FunctionalMismatch):
            gates.gate_command(run, ["unit-fixture-not-a-tool"], report)
        write_json(report, {"status": "failed", "detail": "unit negative fixture"})
        with self.assertRaises(FunctionalMismatch):
            gates.gate_command(run, ["unit-fixture-not-a-tool"], report)
        write_json(report, {"status": "passed"})
        run.child.return_value = ({"exit_code": 2, "receipt": "synthetic-unit-only"}, "", "")
        with self.assertRaises(FunctionalMismatch):
            gates.gate_command(run, ["unit-fixture-not-a-tool"], report)

    def test_native_report_cannot_override_quartus_diagnostics(self):
        report = self.directory / "report.json"
        write_json(report, {"status": "passed"})
        run = Mock()
        receipt = {"exit_code": 0, "receipt": "synthetic-unit-only"}
        run.child.return_value = (receipt, "", "")
        self.assertEqual(gates.gate_command(run, ["unit-fixture-not-a-tool"], report),
                         {"status": "passed"})
        for diagnostic in ("Error (272006): invalid timing netlist",
                           "Error (332000): timing analysis failed",
                           "Warning (10268): assignment ignored"):
            for stream in ("stdout", "stderr"):
                with self.subTest(diagnostic=diagnostic, stream=stream):
                    run.child.return_value = (
                        receipt, diagnostic if stream == "stdout" else "",
                        diagnostic if stream == "stderr" else "")
                    with self.assertRaisesRegex(FunctionalMismatch,
                                                "forbidden Quartus diagnostic"):
                        gates.gate_command(run, ["unit-fixture-not-a-tool"], report)

    def test_lint_verdict_requires_current_sources_and_zero_hazards(self):
        rtl = {k: v for k, v in inventory().items() if k.startswith("rtl/")}
        hazards = ("rtl_div_mod_hazards", "netlist_div_mod_hazards",
                   "mixed_assign_hazards", "lut_clock_gate_hazards",
                   "ast_unroll_loop_hazards")
        data = dict(gate="rtl-timing-lint", status="passed",
                    max_comb_div_width=0, rtl_files_checked=len(rtl),
                    source_sha256=rtl, auto_sanitized_nomem2reg_files=[],
                    **{name: [] for name in hazards})
        run = Mock()
        run.path = self.directory
        run.record = {"results": {}}
        with patch.object(gates, "gate_command", return_value=data):
            gates.lint(run)
        self.assertEqual(run.record["results"]["lint"], data)
        cases = [(name, [{"synthetic": "hazard"}]) for name in hazards]
        cases += [(name, None) for name in hazards]
        cases += [
            ("gate", "unrelated-gate"), ("max_comb_div_width", 32),
            ("max_comb_div_width", False), ("rtl_files_checked", len(rtl) - 1),
            ("rtl_files_checked", float(len(rtl))),
            ("source_sha256", {}),
            ("source_sha256", dict(rtl, **{next(iter(rtl)): "0" * 64})),
            ("auto_sanitized_nomem2reg_files", ["rtl/synthetic.sv"]),
        ]
        for field, value in cases:
            changed = dict(data, **{field: value})
            with self.subTest(field=field, value=value), \
                    patch.object(gates, "gate_command", return_value=changed), \
                    self.assertRaises(FunctionalMismatch):
                gates.lint(run)
        for field in (*hazards, "source_sha256", "rtl_files_checked",
                      "max_comb_div_width", "auto_sanitized_nomem2reg_files"):
            changed = dict(data)
            del changed[field]
            with self.subTest(missing=field), \
                    patch.object(gates, "gate_command", return_value=changed), \
                    self.assertRaises(FunctionalMismatch):
                gates.lint(run)

    def test_physical_run_verdicts_require_exact_types(self):
        data = {
            "requested_runs": 3,
            "reg57_probe": {"exit_code": 0},
            "deterministic_across_runs": True,
            "runs": [{"run_index": index, "exit_code": 0, "passed": True}
                     for index in range(1, 4)],
        }
        gates.validate_physical_runs(data)
        for field, value in (("requested_runs", 3.0),
                             ("deterministic_across_runs", "true")):
            changed = copy.deepcopy(data)
            changed[field] = value
            with self.subTest(field=field, value=value), \
                    self.assertRaises(FunctionalMismatch):
                gates.validate_physical_runs(changed)
        for field, value in (("run_index", True), ("run_index", 1.0),
                             ("exit_code", False), ("exit_code", 0.0),
                             ("passed", "false"), ("passed", "true"),
                             ("passed", 1), ("passed", False)):
            changed = copy.deepcopy(data)
            changed["runs"][0][field] = value
            with self.subTest(field=field, value=value), \
                    self.assertRaises(FunctionalMismatch):
                gates.validate_physical_runs(changed)
        for value in (False, 0.0):
            changed = copy.deepcopy(data)
            changed["reg57_probe"]["exit_code"] = value
            with self.subTest(probe_exit=value), self.assertRaises(FunctionalMismatch):
                gates.validate_physical_runs(changed)
        for field, value in (("runs", None), ("runs", {}), ("runs", [None] * 3),
                             ("runs", data["runs"][:2]), ("reg57_probe", None)):
            changed = copy.deepcopy(data)
            changed[field] = value
            with self.subTest(field=field, value=value), \
                    self.assertRaises(FunctionalMismatch):
                gates.validate_physical_runs(changed)
        for field in ("run_index", "exit_code", "passed"):
            changed = copy.deepcopy(data)
            del changed["runs"][0][field]
            with self.subTest(missing=field), self.assertRaises(FunctionalMismatch):
                gates.validate_physical_runs(changed)
        for index in (0, 2, 3):
            changed = copy.deepcopy(data)
            changed["runs"][0]["run_index"] = index
            with self.subTest(index=index), self.assertRaises(FunctionalMismatch):
                gates.validate_physical_runs(changed)
        changed = copy.deepcopy(data)
        changed["runs"][0]["exit_code"] = 1
        with self.assertRaises(FunctionalMismatch):
            gates.validate_physical_runs(changed)

    def test_binding_covers_actual_sources_and_image(self):
        base = str(self.directory.relative_to(ROOT))
        adapter = self.directory / "adapter.sv"
        adapter.write_text("// Orchestration unit fixture only; never elaborated or deployed.\n")
        sdc = self.directory / "adapter.sdc"
        sdc.write_text("# Unit fixture only, not accepted timing constraints.\n")
        qsf = self.directory / "fixture.qsf"
        qsf.write_text("set_global_assignment -name DEVICE 10AX115N2F45E1SG\n")
        qpf = self.directory / "fixture.qpf"
        qpf.write_text('PROJECT_REVISION = "fixture"\n')
        budget = self.directory / "budget.txt"
        budget.write_text("Synthetic unit fixture, not actual timing evidence.\n")
        pinmap = self.directory / "pins.json"
        write_json(pinmap, {p: f"adapter|core|{p}" for p in
                           ["clk", *gates.INPUTS, *gates.OUTPUTS]})
        rtl = {k: v for k, v in inventory().items() if k.startswith("rtl/")}
        adapter_hashes = {f"{base}/adapter.sv": gates.sha(adapter)}
        constraints = {f"{base}/adapter.sdc": gates.sha(sdc)}
        implementation = dict(rtl, **adapter_hashes, **constraints,
                              **{f"{base}/fixture.qsf": gates.sha(qsf),
                                 f"{base}/fixture.qpf": gates.sha(qpf)})
        entry = {
            "project_dir": base, "revision": "fixture", "adapter_top": "unit_adapter",
            "clock": "core_clk",
            "clock_period_ns": 10, "rtl_bindings": {k: k for k in rtl},
            "adapter_sources": adapter_hashes, "constraints": constraints,
            "implementation_inputs": implementation, "public_pin_map": f"{base}/pins.json",
            "timing_budget": {"description": "unit fixture", "evidence": f"{base}/budget.txt",
                             "input_min_ns": 0, "input_max_ns": 1,
                             "output_min_ns": 0, "output_max_ns": 1},
            "capture_only": True, "remote_test_cmd":
                "unit-fixture @FURNACE_NONCE@ @FURNACE_VECTOR_SHA256@ @FURNACE_WIDTH@",
            "image": f"{base}/fixture.sof", "image_manifest": f"{base}/image.json",
        }
        image = self.directory / "fixture.sof"
        image.write_bytes(b"not a bitstream: unit-test fixture only")
        manifest = dict(
            image_sha256=gates.sha(image), rtl_hashes=rtl, adapter_sources=adapter_hashes,
            constraints=constraints, implementation_inputs=implementation,
            public_pin_map_sha256=gates.sha(pinmap), width=64, device=gates.DEVICE,
            top="furnace_x1_top", clock_period_ns=10)
        write_json(self.directory / "image.json", manifest)
        config = self.directory / "board.json"
        write_json(config, {"furnace_x1": {"device": gates.DEVICE, "widths": {"64": entry}}})
        run = Mock()
        run.record = {}
        run.path = self.directory / "retained-inputs"
        run.path.mkdir()
        gates.load_binding(run, str(config.relative_to(ROOT)), 64, physical=True)
        image.write_bytes(b"changed fixture")
        with self.assertRaisesRegex(FunctionalMismatch, "image build manifest"):
            gates.load_binding(run, str(config.relative_to(ROOT)), 64, physical=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--fixtures")
    selector.add_argument("--out")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    if args.out:
        if args.repair_of and not relative_output(args.repair_of).is_file():
            parser.error("--repair-of must identify a retained project-relative receipt")
        run = Run(relative_output(args.out), "native-orchestration-tests", args.repair_of)
        run.record["tool_versions"]["python3"] = sys.version
        run.track("native-orchestration-tests", status="running")
        try:
            command, _, _ = run.child(
                [sys.executable, "tests/native_gate_tests.py", "--fixtures",
                 str((run.path / "fixtures").relative_to(ROOT))], ROOT)
            if inventory() != run.record["source_hashes"]:
                raise RuntimeError("verification sources changed during unit tests")
            run.track("native-orchestration-tests", status="passed",
                      raw_receipt=command["receipt"],
                      measured={"scope": "synthetic orchestration fixtures only"})
            run.finish("passed")
        except (AssertionError, OSError, ValueError, RuntimeError) as error:
            run.finish("failed", error)
            print(f"{error}; receipt={run.path.relative_to(ROOT)}/receipt.json",
                  file=sys.stderr)
            sys.exit(1)
        print(run.path.relative_to(ROOT) / "receipt.json")
        sys.exit(0)
    FIXTURES = relative_output(args.fixtures)
    FIXTURES.mkdir(parents=True, exist_ok=False)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NativeGateTests))
    sys.exit(0 if result.wasSuccessful() else 1)
