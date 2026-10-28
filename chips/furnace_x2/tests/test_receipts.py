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
        unittest.main(argv=[sys.argv[0]], verbosity=2)
    else:
        run = verify.Run(args.out, "receipt-retention-probe")
        run.receipt.update(
            argv=["python3", "tests/test_receipts.py", *sys.argv[1:]],
            acceptance_evidence=False)
        try:
            run.prerequisites(["python3"])
            run.command(["python3", "tests/test_receipts.py", "--fixtures",
                         run.rel(run.path / "fixtures")])
            run.verify_retention()
            run.receipt.update(outcome="passed", results={"harness_cases": 6})
        except Exception as exc:
            run.receipt.update(outcome="failed", failure=f"{type(exc).__name__}: {exc}")
            print(run.receipt["failure"], file=sys.stderr)
        finally:
            run.receipt["ended_at"] = verify.now()
            run.save()
        print(json.dumps({"outcome": run.receipt["outcome"],
                          "receipt": run.rel(run.receipt_path)}))
        sys.exit(0 if run.receipt["outcome"] == "passed" else 1)
