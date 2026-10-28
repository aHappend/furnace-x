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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    paths = parser.add_mutually_exclusive_group(required=True)
    paths.add_argument("--out", type=Path)
    paths.add_argument("--fixtures", type=Path)
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
        run = verify.Run(args.out, "receipt-retention-probe")
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
