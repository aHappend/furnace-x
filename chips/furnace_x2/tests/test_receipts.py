"""Bounded harness regression, not packet or engineering acceptance evidence."""
import argparse
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.root = FIXTURES / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)
        source = self.root / "input.txt"
        source.write_text("synthetic receipt fixture\n")
        self.root_patch = patch.object(verify, "ROOT", self.root)
        self.sources_patch = patch.object(verify, "selected", return_value=[source])
        self.root_patch.start()
        self.sources_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.sources_patch.stop)
        self.run = verify.Run("output", "synthetic-retention-test")

    def command(self, exit_code=0):
        return self.run.command([
            sys.executable, "-c",
            f"import sys; print('fixture stdout'); "
            f"print('fixture stderr', file=sys.stderr); sys.exit({exit_code})"],
            cwd=self.root)

    def test_partition_keeps_root_receipt_current(self):
        root_receipt = self.run.receipt_path
        partition = self.run.path / "partition"
        partition.mkdir()
        self.run.path = partition
        self.command()
        stored = json.loads(root_receipt.read_text())
        self.assertEqual(stored["commands"], self.run.commands)
        self.assertFalse((partition / "receipt.json").exists())
        self.run.verify_retention()

    def test_failure_is_journaled_before_exception(self):
        with self.assertRaisesRegex(AssertionError, "tool execution failed"):
            self.command(7)
        stored = json.loads(self.run.receipt_path.read_text())
        self.assertEqual(stored["commands"][0]["exit"], 7)
        self.assertFalse(stored["commands"][0]["timeout"])
        self.run.verify_retention()

    def test_missing_log_rejected(self):
        self.command()
        (self.root / self.run.commands[0]["stdout"]).unlink()
        with self.assertRaisesRegex(AssertionError, "missing retained log"):
            self.run.verify_retention()

    def test_changed_log_rejected(self):
        self.command()
        (self.root / self.run.commands[0]["stderr"]).write_text("changed fixture\n")
        with self.assertRaisesRegex(AssertionError, "changed retained log"):
            self.run.verify_retention()

    def test_changed_journal_rejected(self):
        self.command()
        (self.root / self.run.commands[0]["journal"]).write_text("{}\n")
        with self.assertRaisesRegex(AssertionError, "changed command journal"):
            self.run.verify_retention()

    def test_changed_source_snapshot_rejected(self):
        (self.run.path / "source/input.txt").write_text("changed fixture\n")
        with self.assertRaisesRegex(AssertionError, "changed source snapshot"):
            self.run.verify_retention()

    def next_run(self):
        return verify.Run("output", "synthetic-retention-successor")

    def test_missing_previous_run_rejected(self):
        self.command()
        self.run.finish()
        self.run.path.rename(self.root / "displaced-fixture")
        successor = self.next_run()
        with self.assertRaisesRegex(AssertionError, "missing registered invocation receipt"):
            successor.verify_history()

    def test_changed_previous_log_rejected(self):
        self.command()
        self.run.finish()
        (self.root / self.run.commands[0]["stdout"]).write_text("changed fixture\n")
        with self.assertRaisesRegex(AssertionError, "changed retained log"):
            self.next_run().verify_history()

    def test_changed_previous_receipt_rejected(self):
        self.command()
        self.run.finish()
        receipt = json.loads(self.run.receipt_path.read_text())
        receipt["commands"] = []
        verify.write_json(self.run.receipt_path, receipt)
        with self.assertRaisesRegex(AssertionError, "changed completed receipt"):
            self.next_run().verify_history()

    def test_failed_previous_run_retained(self):
        with self.assertRaisesRegex(AssertionError, "tool execution failed"):
            self.command(7)
        self.run.receipt["outcome"] = "failed"
        self.run.finish()
        self.next_run().verify_history()
        stored = json.loads(self.run.receipt_path.read_text())
        self.assertEqual(stored["outcome"], "failed")
        self.assertEqual(stored["commands"][0]["exit"], 7)

    def test_in_progress_previous_run_allowed(self):
        self.run.commands.append({"argv": ["synthetic-pending-command"]})
        self.run.save()
        self.next_run().verify_history()
        with self.assertRaisesRegex(AssertionError, "unfinished command"):
            self.run.verify_retention()

    def test_registration_is_exclusive_and_checked(self):
        with self.assertRaises(FileExistsError):
            self.run.registration_path.open("x")
        verify.write_json(self.run.registration_path, {})
        with self.assertRaisesRegex(AssertionError, "changed invocation registration"):
            self.run.verify_history()

    def repair_run(self, outcome="failed", finished=True):
        self.command(0)
        self.run.receipt["outcome"] = outcome
        if finished:
            self.run.finish()
        else:
            self.run.save()
        return verify.Run("repairs", "synthetic-repair",
                          repair_of=self.run.rel(self.run.receipt_path))

    def test_repair_reference_binds_retained_failure(self):
        successor = self.repair_run()
        successor.verify_history()
        self.assertEqual(successor.receipt["repair_reference"], {
            "receipt": self.run.rel(self.run.receipt_path),
            "receipt_sha256": verify.digest(self.run.receipt_path)})
        successor.verify_retention()
        self.assertEqual(json.loads(self.run.receipt_path.read_text())["outcome"], "failed")

    def test_missing_repair_reference_rejected(self):
        successor = verify.Run("repairs", "synthetic-repair",
                               repair_of="missing/receipt.json")
        with self.assertRaisesRegex(AssertionError, "missing repair reference receipt"):
            successor.verify_history()

    def test_passing_repair_reference_rejected(self):
        successor = self.repair_run(outcome="passed")
        with self.assertRaisesRegex(AssertionError, "not a completed failure"):
            successor.verify_history()

    def test_incomplete_repair_reference_rejected(self):
        successor = self.repair_run(finished=False)
        with self.assertRaisesRegex(AssertionError, "not a completed failure"):
            successor.verify_history()

    def test_changed_repair_receipt_rejected(self):
        successor = self.repair_run()
        successor.verify_history()
        original = json.loads(self.run.receipt_path.read_text())
        original["failure"] = "changed synthetic diagnosis"
        verify.write_json(self.run.receipt_path, original)
        with self.assertRaisesRegex(AssertionError, "changed repair reference receipt"):
            successor.verify_retention()

    def test_missing_repair_log_rejected(self):
        successor = self.repair_run()
        (self.root / self.run.commands[0]["stdout"]).unlink()
        with self.assertRaisesRegex(AssertionError, "missing retained log"):
            successor.verify_history()

    def test_changed_repair_snapshot_rejected(self):
        successor = self.repair_run()
        (self.run.path / "source/input.txt").write_text("changed fixture\n")
        with self.assertRaisesRegex(AssertionError, "changed source snapshot"):
            successor.verify_history()

    def test_nonportable_repair_reference_rejected(self):
        for reference in ("/unavailable/receipt.json", "../unavailable/receipt.json"):
            with self.subTest(reference=reference):
                successor = verify.Run("repairs", "synthetic-repair", repair_of=reference)
                with self.assertRaisesRegex(AssertionError, "must be project-relative"):
                    successor.verify_history()

    def transcripts(self, stdout, mirror):
        output = self.root / "synthetic.stdout"
        duplicate = self.root / "synthetic.transcript"
        output.write_bytes(stdout)
        duplicate.write_bytes(mirror)
        return verify.transcript_comparison(output, duplicate)

    def test_equal_transcript_channels(self):
        events = b"DONE 1 synthetic\nABORT 2 synthetic\nCOUNTS synthetic\n"
        measured = self.transcripts(events + b"- tb.sv:1: Verilog $finish\n", events)
        self.assertTrue(measured["equal"])
        self.assertIsNone(measured["first_different_event_byte"])
        self.assertEqual(measured["stdout_event_bytes"], len(events))

    def test_buffer_boundary_splice_localized(self):
        original = b"DONE 1 " + b"a" * 110000 + b"\nCOUNTS synthetic\n"
        damaged = original[:102400] + b"DONE 664 synthetic\n" + original[108000:]
        measured = self.transcripts(damaged, original)
        self.assertFalse(measured["equal"])
        self.assertEqual(measured["first_different_event_byte"], 102400)

    def test_missing_and_duplicate_transcript_events_rejected(self):
        events = b"DONE 1 synthetic\nCOUNTS synthetic\n"
        for damaged in (b"COUNTS synthetic\n", events + b"DONE 1 synthetic\n", b""):
            with self.subTest(damaged=damaged):
                self.assertFalse(self.transcripts(damaged, events)["equal"])

    def test_mirror_loss_is_not_replaced_by_stdout(self):
        self.assertFalse(self.transcripts(b"DONE 1 synthetic\n", b"")["equal"])

    def test_malformed_done_framing_has_explicit_diagnostic(self):
        with self.assertRaisesRegex(AssertionError, "malformed DONE record"):
            verify.parse_top_output("DONE 530 1 abcdDONE 664 1\n", {})
        with self.assertRaisesRegex(AssertionError, "nonhexadecimal DONE field"):
            verify.parse_top_output("DONE 530 1 abcd 0 0DONE 14 0 0 0 0 0\n", {})

    def test_abort_framing_rejected_before_numeric_conversion(self):
        for line, diagnostic in (
                ("ABORT 1 2 3\n", "malformed ABORT record"),
                ("ABORT 1 2 3 0DONE\n", "nondecimal ABORT field"),
                ("ABORT 1 2 -3 0\n", "nondecimal ABORT field")):
            with self.subTest(line=line):
                with self.assertRaisesRegex(AssertionError, diagnostic):
                    verify.parse_top_output(line, {})

    def test_counts_framing_rejected_before_numeric_conversion(self):
        for line, diagnostic in (
                ("COUNTS 1 2\n", "malformed public-event counters"),
                ("COUNTS 1 2 3 4 5 6 7 8 9 10 11DONE\n", "nondecimal COUNTS field"),
                ("COUNTS 1 2 3 4 5 6 7 8 9 10 -11\n", "nondecimal COUNTS field")):
            with self.subTest(line=line):
                with self.assertRaisesRegex(AssertionError, diagnostic):
                    verify.parse_top_output(line, {})

    def test_duplicate_terminal_counts_cannot_inflate_coverage(self):
        counts = "COUNTS 1 1 1 1 1 1 1 1 1 1 1\n"
        with self.assertRaisesRegex(AssertionError, "event after terminal COUNTS"):
            verify.parse_top_output(counts + counts, {})

    def test_packet_event_after_terminal_counts_rejected(self):
        counts = "COUNTS 1 1 1 1 1 1 1 1 1 1 1\n"
        for event in ("DONE 1 1 0 0 0 0 0 0 0 0 0\n", "ABORT 1 1 1 0\n"):
            with self.subTest(event=event):
                with self.assertRaisesRegex(AssertionError, "event after terminal COUNTS"):
                    verify.parse_top_output(counts + event, {})

    def test_duplicate_abort_cannot_inflate_reset_coverage(self):
        records = {1: {"abort": 1}}
        with self.assertRaises(AssertionError):
            verify.parse_top_output("ABORT 1 1 1 0\nABORT 1 1 1 0\n", records)

    def test_equal_channels_do_not_certify_record_validity(self):
        damaged = b"COUNTS 1 2 3 4 5 6 7 8 9 10 11DONE\n"
        self.assertTrue(self.transcripts(damaged, damaged)["equal"])
        with self.assertRaisesRegex(AssertionError, "nondecimal COUNTS field"):
            verify.parse_top_output(damaged.decode("ascii"), {})

    def test_missing_terminal_counts_rejected_explicitly(self):
        with self.assertRaisesRegex(AssertionError, "missing terminal COUNTS"):
            verify.parse_top_output("", {})

    def test_simulator_stderr_rejected_before_records(self):
        for diagnostic in ("warning: unexpected simulation warning\n",
                           "DONE 1 synthetic\n", "\x00"):
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaisesRegex(AssertionError, "unexpected simulator stderr"):
                    verify.parse_top_output("", {}, stderr=diagnostic)
                with self.assertRaisesRegex(AssertionError, "unexpected simulator stderr"):
                    verify.check_simulator_stderr(diagnostic)

    def test_only_recognized_simulator_finish_notices_are_ignored(self):
        for line in ("- tb.sv:271: Verilog $finish",
                     "- evidence/run/verilator-64/tb.sv:271: Verilog $finish",
                     "evidence/run/icarus-64/tb.sv:271: $finish called at 61585000 (1ps)"):
            with self.subTest(line=line):
                self.assertTrue(verify.simulator_finish(line))
        for line in ("- unexpected simulator diagnostic",
                     "- tb.sv:271: Verilog $finish warning",
                     "- tb.sv:271: Verilog $stop",
                     "- other.sv:271: Verilog $finish"):
            with self.subTest(line=line):
                self.assertFalse(verify.simulator_finish(line))
                with self.assertRaisesRegex(AssertionError, "unexpected simulator diagnostic"):
                    verify.parse_top_output(line + "\n", {})

    def test_complete_synthetic_transcript_measures_events_once(self):
        record = dict.fromkeys(
            ("crc32", "crc64", "header", "length", "hash", "rss", "hit", "index", "action"), 0)
        record.update(beats=1, abort=0, fields={}, labels=["synthetic"])
        text = ("DONE 1 1 0 0 0 0 0 0 0 0 0\n"
                "ABORT 2 1 1 0\n"
                "COUNTS 1 1 1 1 1 1 1 1 1 1 2\n")
        for trailer in ("", "- tb.sv:1: Verilog $finish\n"):
            with self.subTest(trailer=trailer):
                coverage = verify.parse_top_output(
                    text + trailer, {1: record, 2: {"abort": 1}})
                self.assertEqual(coverage["compared_packets"], 1)
                self.assertEqual(coverage["compared_beats"], 1)
                self.assertEqual(coverage["reset_observed_1"], 1)
                self.assertEqual(coverage["synthetic"], 1)

    def test_changed_mirror_rejected_by_retention(self):
        events = b"DONE 1 synthetic\n"
        channels = self.transcripts(events, events)
        channels.update(stdout="synthetic.stdout", mirror="synthetic.transcript")
        self.run.receipt["transcript_channels"] = [channels]
        self.run.save()
        self.run.verify_retention()
        (self.root / channels["mirror"]).write_bytes(b"changed synthetic record\n")
        with self.assertRaisesRegex(AssertionError, "changed transcript channel"):
            self.run.verify_retention()

    def test_leaf_records_compare_complete_public_values(self):
        for kind, record, expected in (
                ("rss", "LEAF 0 51ccc178 1", [(0x51ccc178, 1)]),
                ("classifier", "LEAF 0 1 63 deadbeef", [(1, 63, 0xdeadbeef)])):
            with self.subTest(kind=kind):
                text = record + "\nLEAF_COUNT 1\n- tb.sv:1: Verilog $finish\n"
                self.assertEqual(verify.parse_leaf_output(text, expected, kind), expected)
                with self.assertRaisesRegex(AssertionError, "leaf result/count mismatch"):
                    verify.parse_leaf_output(text, [(0, 0)], kind)

    def test_leaf_framing_rejects_splices_unknowns_and_extra_fields(self):
        for kind, line, diagnostic in (
                ("rss", "LEAF 0 abcdDONE 1", "nonhexadecimal LEAF field"),
                ("rss", "LEAF 0 x 1", "nonhexadecimal LEAF field"),
                ("rss", "LEAF 0 abcd z", "nondecimal LEAF field"),
                ("rss", "LEAF 0 abcd 1 ignored", "malformed LEAF record"),
                ("classifier", "LEAF 0 1 3 deadbeef ignored", "malformed LEAF record"),
                ("classifier", "LEAF 0 1 3 xx", "nonhexadecimal LEAF field"),
                ("classifier", "LEAF 0 1 z deadbeef", "nondecimal LEAF field")):
            with self.subTest(kind=kind, line=line):
                with self.assertRaisesRegex(AssertionError, diagnostic):
                    verify.parse_leaf_output(line + "\n", [], kind)

    def test_leaf_terminal_record_is_unique_and_final(self):
        for event in ("LEAF_COUNT 1", "LEAF 1 0 1"):
            with self.subTest(event=event):
                with self.assertRaisesRegex(AssertionError, "event after terminal LEAF_COUNT"):
                    verify.parse_leaf_output(
                        "LEAF 0 0 1\nLEAF_COUNT 1\n" + event + "\n", [(0, 1)], "rss")
        for count in ("LEAF_COUNT 1 ignored", "LEAF_COUNT -1", "LEAF_COUNT x"):
            with self.subTest(count=count):
                with self.assertRaisesRegex(AssertionError, "malformed LEAF_COUNT"):
                    verify.parse_leaf_output(count + "\n", [], "rss")
        with self.assertRaisesRegex(AssertionError, "missing terminal LEAF_COUNT"):
            verify.parse_leaf_output("LEAF 0 0 1\n", [(0, 1)], "rss")

    def test_leaf_order_diagnostics_and_stderr_remain_failures(self):
        with self.assertRaisesRegex(AssertionError, "duplicate/out-of-order"):
            verify.parse_leaf_output("LEAF 0 0 1\nLEAF 0 0 1\n", [(0, 1)], "rss")
        with self.assertRaisesRegex(AssertionError, "unexpected leaf diagnostic"):
            verify.parse_leaf_output("warning: synthetic\n", [], "rss")
        with self.assertRaisesRegex(AssertionError, "unexpected simulator stderr"):
            verify.parse_leaf_output("", [], "rss", stderr="synthetic warning\n")

    def test_simulation_cleanup_preserves_evidence_and_executable(self):
        self.check_simulation_cleanup(0)

    def test_rejected_simulation_still_cleans_build_intermediates(self):
        self.check_simulation_cleanup(7)

    def reproduction_receipt(self):
        results = {}
        for width in (64, 512):
            for name, packets, seeded in (("smoke", 8, 0), ("behavior-17", 160, 128)):
                results[f"{name}-{width}"] = {
                    "packets": packets, "compared_packets": packets, "seeded": seeded,
                    "payload_stall_cycles": 1, "crc_stall_cycles": 1,
                    "meta_stall_cycles": 1, "simultaneous_terminal": 1}
        return {"outcome": "passed", "mode": "reproduction", "python_isolated": True,
                "source_sha256": {"synthetic": "binding"}, "results": results}

    def test_reproduction_measures_both_widths(self):
        receipt = self.reproduction_receipt()
        measured = verify.check_reproduction(receipt, receipt["source_sha256"])
        self.assertEqual(set(measured), {"64", "512"})
        for width in measured:
            self.assertEqual(measured[width]["sample_seeded_packets"], 128)
            self.assertEqual(measured[width]["sample_directed_packets"], 32)

    def test_reproduction_pass_label_cannot_replace_coverage(self):
        for width in (64, 512):
            for field, value in (("seeded", 127), ("compared_packets", 159),
                                 ("packets", 159), ("meta_stall_cycles", 0)):
                with self.subTest(width=width, field=field):
                    receipt = self.reproduction_receipt()
                    receipt["results"][f"behavior-17-{width}"][field] = value
                    with self.assertRaises(AssertionError):
                        verify.check_reproduction(receipt, receipt["source_sha256"])
            receipt = self.reproduction_receipt()
            del receipt["results"][f"smoke-{width}"]
            with self.assertRaises(KeyError):
                verify.check_reproduction(receipt, receipt["source_sha256"])

    def test_reproduction_rejects_nonisolated_or_wrong_sources(self):
        for field, value in (("python_isolated", False), ("mode", "smoke"),
                             ("outcome", "failed"), ("source_sha256", {})):
            with self.subTest(field=field):
                receipt = self.reproduction_receipt()
                receipt[field] = value
                with self.assertRaises(AssertionError):
                    verify.check_reproduction(receipt, {"synthetic": "binding"})

    def test_isolated_python_ignores_poisoned_pythonpath(self):
        poison = self.root / "poison"
        poison.mkdir()
        (poison / "sitecustomize.py").write_text(
            "POISON_MARKER = True\n"
            "raise RuntimeError('synthetic inherited import must not run')\n")
        with patch.dict(verify.os.environ, {"PYTHONPATH": str(poison)}):
            text, errors, _ = self.run.command([
                sys.executable, "-I", "-c",
                "import json,os,sys; print(json.dumps({'isolated': sys.flags.isolated, "
                "'poison_loaded': getattr(sys.modules.get('sitecustomize'), "
                "'POISON_MARKER', False), "
                "'poison_on_path': os.environ['PYTHONPATH'] in sys.path}))"], cwd=self.root)
        self.assertEqual(json.loads(text), {
            "isolated": 1, "poison_loaded": False, "poison_on_path": False})
        self.assertEqual(errors, "")

    def check_simulation_cleanup(self, exit_code):
        folder = self.run.path / "simulation"
        objects = folder / "obj"
        objects.mkdir(parents=True)
        disposable = ("model.o", "model.a", "model.fast.gch")
        retained = ("sim", "model.cpp", "model.h", "model.mk")
        for name in disposable + retained:
            (objects / name).write_text("synthetic build fixture\n")
        (folder / "stimulus.txt").write_text("synthetic input\n")
        executable = [
            sys.executable, "-c",
            f"import sys; print('synthetic simulation'); sys.exit({exit_code})"]
        if exit_code:
            with self.assertRaisesRegex(AssertionError, "tool execution failed"):
                verify.execute_sim(self.run, folder, executable)
        else:
            verify.execute_sim(self.run, folder, executable)
        for name in disposable:
            self.assertFalse((objects / name).exists())
        for name in retained:
            self.assertEqual((objects / name).read_text(), "synthetic build fixture\n")
        self.assertEqual((folder / "stimulus.txt").read_text(), "synthetic input\n")
        self.assertEqual(self.run.commands[-1]["exit"], exit_code)
        self.run.verify_retention()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    paths = parser.add_mutually_exclusive_group(required=True)
    paths.add_argument("--out", type=Path)
    paths.add_argument("--fixtures", type=Path)
    parser.add_argument("--repair-of", help="project-relative preserved prior failure receipt")
    args = parser.parse_args()
    destination = args.out if args.out is not None else args.fixtures
    if destination.is_absolute() or ".." in destination.parts:
        parser.error("--out must be a fresh project-relative fixture directory")
    if args.fixtures is not None:
        FIXTURES = args.fixtures
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReceiptTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(json.dumps({"harness_cases": result.testsRun,
                          "failures": len(result.failures),
                          "errors": len(result.errors),
                          "skipped": len(result.skipped)}))
        sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
    else:
        run = verify.Run(args.out, "receipt-retention-probe", repair_of=args.repair_of)
        run.receipt.update(
            argv=["python3", "tests/test_receipts.py", *sys.argv[1:]],
            acceptance_evidence=False)
        try:
            run.verify_history()
            run.prerequisites(["python3"])
            text, _, _ = run.command([
                "python3", "tests/test_receipts.py", "--fixtures",
                run.rel(run.path / "fixtures")])
            measured = json.loads(text)
            assert measured["harness_cases"] >= 20
            assert measured["failures"] == measured["errors"] == measured["skipped"] == 0
            run.verify_retention()
            run.receipt.update(outcome="passed", results=measured)
        except Exception as exc:
            run.receipt.update(outcome="failed", failure=f"{type(exc).__name__}: {exc}")
            print(run.receipt["failure"], file=sys.stderr)
        finally:
            run.finish()
        print(json.dumps({"outcome": run.receipt["outcome"],
                          "receipt": run.rel(run.receipt_path)}))
        sys.exit(0 if run.receipt["outcome"] == "passed" else 1)
