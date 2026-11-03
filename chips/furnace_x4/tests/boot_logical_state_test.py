#!/usr/bin/env python3
"""Bounded comparator sensitivity fixtures; no SoC execution or acceptance claim."""

import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_logical_state import (
    MAGIC, SAVE_HEADER, SAVE_TRAILER, compare_fields, declarations, equivalent, flat_fields,
    read_fields, scratch_proofs, serializer_writes, sha256, type_shape,
    validate_accounting, validate_raw_capture,
)

FIXTURE_ROOT = None


def fixture_model():
    fields = {
        "state": {"bits": 3, "shape": [], "element_bytes": 1, "words": 1,
                  "bytes": 1, "serializer_loops": []},
        "bytes": {"bits": 8, "shape": [2, 3], "element_bytes": 1, "words": 1,
                  "bytes": 6, "serializer_loops": [2, 3]},
        "wide": {"bits": 65, "shape": [], "element_bytes": 4, "words": 3,
                 "bytes": 12, "serializer_loops": [3]},
    }
    return {"classes": {"fixture___024root": {
        "fields": fields, "unserialized_data": {}, "unserialized_scheduler": {}}},
        "generated_sha256": {}}


def fixture_plan():
    model = fixture_model()
    return {"schema": 1, "baseline": model, "candidate": copy.deepcopy(model),
            "fields": {name: {"disposition": "compare_exact", "baseline": name, "candidate": name}
                       for name in flat_fields(model)},
            "unserialized": {}, "complete": True}


def values(model):
    return {name: bytes((i * 13 + 7) & 255 for i in range(spec["bytes"]))
            for name, spec in flat_fields(model).items()}


def tagged(path, data):
    with path.open("wb") as stream:
        stream.write(MAGIC)
        for name, value in data.items():
            encoded = name.encode("ascii")
            stream.write(struct.pack("<I", len(encoded)) + encoded +
                         struct.pack("<Q", len(value)) + value)


def archive_plan():
    plan = fixture_plan()
    for model in (plan["baseline"], plan["candidate"]):
        root = model["classes"]["fixture___024root"]
        root["writes"] = [
            {"kind": "signature", "value": 0x1234},
            {"kind": "signature_write"}, {"kind": "context"},
            *[{"kind": "field", "name": name} for name in root["fields"]],
        ]
        root["module_instances"] = {}
        model["classes"]["fixture__Syms"] = {
            "fields": {"initialized": {"bits": 1, "shape": [], "element_bytes": 1,
                                       "words": 1, "bytes": 1, "serializer_loops": []}},
            "writes": [{"kind": "field", "name": "initialized"},
                       {"kind": "instance", "name": "TOP"}],
            "module_instances": {"TOP": "fixture___024root"},
            "unserialized_data": {}, "unserialized_scheduler": {},
        }
        model["archive_entry"] = "fixture__Syms"
    identity = "fixture__Syms.initialized"
    plan["fields"][identity] = {"disposition": "compare_exact",
                                "baseline": identity, "candidate": identity}
    return plan


def snapshot(folder, model, data):
    context = b"all serialized context bytes including padding"
    (folder / "context.bin").write_bytes(SAVE_HEADER + context + SAVE_TRAILER)
    raw = bytearray(SAVE_HEADER + context + data["fixture__Syms.initialized"])
    root = model["classes"]["fixture___024root"]
    for row in root["writes"]:
        if row["kind"] == "signature":
            signature = row["value"]
        elif row["kind"] == "signature_write":
            raw.extend(signature.to_bytes(8, sys.byteorder))
        elif row["kind"] == "context":
            raw.extend(context)
        else:
            raw.extend(data["fixture___024root." + row["name"]])
    raw.extend(SAVE_TRAILER)
    (folder / "rtl-context.bin").write_bytes(raw)
    (folder / "host.bin").write_bytes(b"all exact reference/host bytes")
    tagged(folder / "logical-state.bin", data)
    return {
        "final_state": {
            **{name: {"bytes": (folder / name).stat().st_size, "sha256": sha256(folder / name)}
               for name in ("rtl-context.bin", "host.bin", "context.bin", "logical-state.bin")},
            "ram.bin": {"bytes": 128 * 1024 * 1024, "sha256": "synthetic-full-ram-identity"},
        },
        "uart_sha256": "uart", "observed": {
            "cycles": 123, "coverage": {"boot": 1}, "equal_comparisons": 64,
            "require_comparisons": 98, "retired": 17, "profile": {"ns": 1}},
    }


class LogicalStateSensitivity(unittest.TestCase):
    def test_equal_values_and_reordered_storage(self):
        plan = fixture_plan()
        a = values(plan["baseline"])
        b = dict(reversed(list(a.items())))
        result = compare_fields(plan, a, b)
        self.assertEqual(result["exact_fields"], 3)
        self.assertEqual(result["exact_storage_bytes"], 19)

    def test_omitted_accounting(self):
        plan = fixture_plan()
        del plan["fields"]["fixture___024root.state"]
        with self.assertRaisesRegex(ValueError, "omitted"):
            compare_fields(plan, values(plan["baseline"]), values(plan["candidate"]))

    def test_omitted_capture(self):
        plan = fixture_plan()
        a = values(plan["baseline"])
        b = dict(a)
        del b["fixture___024root.bytes"]
        with self.assertRaisesRegex(ValueError, "omitted"):
            compare_fields(plan, a, b)

    def test_changed_state_array_tail_and_unused_high_bits(self):
        plan = fixture_plan()
        a = values(plan["baseline"])
        for field in a:
            for index in (0, len(a[field]) - 1):
                with self.subTest(field=field, index=index):
                    b = dict(a)
                    changed = bytearray(b[field])
                    changed[index] ^= 0x80
                    b[field] = bytes(changed)
                    with self.assertRaisesRegex(ValueError, "logical RTL state mismatch"):
                        compare_fields(plan, a, b)

    def test_incorrect_mapping(self):
        plan = fixture_plan()
        plan["fields"]["fixture___024root.state"]["candidate"] = "fixture___024root.wide"
        with self.assertRaisesRegex(ValueError, "incorrect logical field mapping"):
            compare_fields(plan, values(plan["baseline"]), values(plan["candidate"]))

    def test_width_or_shape_mapping_corruption(self):
        for key, changed in (("bits", 4), ("shape", [6]), ("bytes", 5)):
            plan = fixture_plan()
            plan["candidate"]["classes"]["fixture___024root"]["fields"]["bytes"][key] = changed
            with self.assertRaisesRegex(ValueError, "shape/width"):
                validate_accounting(plan)

    def test_unsupported_exclusion(self):
        plan = fixture_plan()
        plan["fields"]["fixture___024root.state"] = {"disposition": "dead_entry_value"}
        with self.assertRaisesRegex(ValueError, "incorrect logical field mapping"):
            validate_accounting(plan)

    def test_unknown_backend_state_and_unsaved_scheduler(self):
        plan = fixture_plan()
        del plan["candidate"]["classes"]["fixture___024root"]["fields"]["state"]
        plan["fields"]["fixture___024root.state"] = {
            "disposition": "unresolved", "backend": "baseline"}
        with self.assertRaisesRegex(ValueError, "unproved backend-only"):
            validate_accounting(plan)
        plan = fixture_plan()
        plan["unserialized"]["candidate:root.task_state"] = {"disposition": "unresolved"}
        with self.assertRaisesRegex(ValueError, "settled-boundary proof"):
            validate_accounting(plan)

    def test_exact_context_host_ram_uart_and_observations(self):
        plan = archive_plan()
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            folder = Path(directory)
            original = snapshot(folder, plan["baseline"], values(plan["baseline"]))
            self.assertEqual(equivalent(plan, original, original, folder, folder)["exact_fields"], 4)
            cases = []
            for key in original["final_state"]:
                modified = copy.deepcopy(original)
                modified["final_state"][key]["sha256"] = "changed"
                cases.append(modified)
            for key in original["observed"]:
                if key != "profile":
                    modified = copy.deepcopy(original)
                    modified["observed"][key] = {"changed": 1}
                    cases.append(modified)
            modified = copy.deepcopy(original)
            modified["observed"]["extra_counter"] = 1
            cases.append(modified)
            modified = copy.deepcopy(original)
            modified["uart_sha256"] = "changed"
            cases.append(modified)
            for changed in cases:
                with self.assertRaisesRegex(ValueError, "equal-work"):
                    equivalent(plan, original, changed, folder, folder)

    def test_raw_archive_order_signature_and_full_context(self):
        plan = archive_plan()
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            folder = Path(directory)
            data = values(plan["baseline"])
            snapshot(folder, plan["baseline"], data)
            self.assertEqual(validate_raw_capture(plan["baseline"], folder, data)[
                "raw_fields_validated"], 4)
            raw = (folder / "rtl-context.bin").read_bytes()
            for index in (0, len(SAVE_HEADER), len(SAVE_HEADER) + 44 + 1,
                          len(raw) - len(SAVE_TRAILER) - 1, len(raw) - 1):
                changed = bytearray(raw)
                changed[index] ^= 1
                (folder / "rtl-context.bin").write_bytes(changed)
                with self.assertRaisesRegex(ValueError, "raw RTL/context"):
                    validate_raw_capture(plan["baseline"], folder, data)
            (folder / "rtl-context.bin").write_bytes(raw + b"extra")
            with self.assertRaisesRegex(ValueError, "unaccounted"):
                validate_raw_capture(plan["baseline"], folder, data)
            (folder / "rtl-context.bin").write_bytes(raw)
            wrong_schema = copy.deepcopy(plan["baseline"])
            wrong_schema["classes"]["fixture___024root"]["writes"][-2:] = list(reversed(
                wrong_schema["classes"]["fixture___024root"]["writes"][-2:]))
            with self.assertRaisesRegex(ValueError, "raw RTL/context"):
                validate_raw_capture(wrong_schema, folder, data)

    def test_equal_logical_state_with_different_archive_layouts(self):
        plan = archive_plan()
        candidate = plan["candidate"]["classes"]["fixture___024root"]
        candidate["writes"][0]["value"] ^= 0x55
        candidate["writes"][3:] = reversed(candidate["writes"][3:])
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            left, right = Path(directory) / "baseline", Path(directory) / "candidate"
            left.mkdir()
            right.mkdir()
            a = snapshot(left, plan["baseline"], values(plan["baseline"]))
            b = snapshot(right, plan["candidate"], values(plan["candidate"]))
            self.assertNotEqual(a["final_state"]["rtl-context.bin"], b["final_state"]["rtl-context.bin"])
            self.assertEqual(equivalent(plan, a, b, left, right)["exact_storage_bytes"], 20)

    def test_type_and_array_schema(self):
        self.assertEqual(type_shape("VlUnpacked<VlUnpacked<CData/*7:0*/, 3>, 2>"),
                         {"bits": 8, "shape": [2, 3], "element_bytes": 1, "words": 1})
        fields, unsaved = declarations(
            "VL_INW(data,64,0,3);\nVlTriggerVec<8> trigger;\nVlMTaskVertex task;\n")
        self.assertEqual(fields["data"]["bits"], 65)
        self.assertEqual(fields["data"]["words"], 3)
        self.assertEqual(set(unsaved), {"trigger", "task"})
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            type_shape("unrecognized")
        with self.assertRaisesRegex(ValueError, "unaccounted"):
            declarations("UnknownState hidden;")

    def test_serializer_parser_does_not_ignore_statements(self):
        prefix = ("uint64_t __Vcheckval = 0x1234ULL; os << __Vcheckval; "
                  "os << vlSymsp->_vm_contextp__; ")
        valid = ("for (int __Vi0 = 0; __Vi0 < 2; ++__Vi0) { "
                 "for (int __Vi1 = 0; __Vi1 < 3; ++__Vi1) { os << bytes[__Vi0][__Vi1]; }}")
        self.assertEqual(serializer_writes(prefix + valid)[-1]["loops"], [2, 3])
        for invalid in ("os << bytes[__Vi1][__Vi0];", "os << bytes[0];",
                        "os.write(raw, 8);", "if (enable) { os << state; }"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                serializer_writes(prefix + invalid)

    def test_tagged_capture_strictness(self):
        model = fixture_model()
        expected = flat_fields(model)
        data = values(model)
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            path = Path(directory) / "fields.bin"

            def emit(rows, extra=b""):
                with path.open("wb") as stream:
                    stream.write(MAGIC)
                    for name, value in rows:
                        encoded = name.encode("ascii")
                        stream.write(struct.pack("<I", len(encoded)) + encoded +
                                     struct.pack("<Q", len(value)) + value)
                    stream.write(extra)

            emit(reversed(list(data.items())))
            self.assertEqual(read_fields(path, expected), data)
            rows = list(data.items())
            for bad, extra in ((rows[:-1], b""), (rows + rows[:1], b""),
                               (rows, b"\x01"), ([("unknown", b"\x00")], b""),
                               ([(rows[0][0], b"")], b"")):
                emit(bad, extra)
                with self.assertRaises(ValueError):
                    read_fields(path, expected)

    def test_dead_scalar_entry_proof_and_counterexamples(self):
        cases = {
            "copy": ("void f(Root* vlSelf) { vlSelf->scratch = vlSelf->state; "
                     "consume(vlSelf->scratch); }", True),
            "constant": ("void f(Root* vlSelf) { vlSelf->scratch = 0U; "
                         "consume(vlSelf->scratch); }", True),
            "read_first": ("void f(Root* vlSelf) { consume(vlSelf->scratch); "
                           "vlSelf->scratch = 0U; }", False),
            "conditional": ("void f(Root* vlSelf) { if (enable) { vlSelf->scratch = 0U; } "
                            "consume(vlSelf->scratch); }", False),
            "unguarded_if": ("void f(Root* vlSelf) { if (enable) vlSelf->scratch = 0U; "
                             "consume(vlSelf->scratch); }", False),
            "self_read": ("void f(Root* vlSelf) { vlSelf->scratch = vlSelf->scratch + 1U; }", False),
            "function_call": ("void f(Root* vlSelf) { vlSelf->scratch = helper(); }", False),
            "address": ("void f(Root* vlSelf) { helper(&vlSelf->scratch); }", False),
            "split": ("void f(Root* vlSelf) { vlSelf->scratch = 0U; }\n"
                      "void g(Root* vlSelf) { consume(vlSelf->scratch); }", False),
            "jump": ("void f(Root* vlSelf) { goto later; vlSelf->scratch = 0U; "
                     "later: consume(vlSelf->scratch); }", False),
            "other_signature": ("int g(Root* vlSelf) { return vlSelf->scratch; }\n"
                                "void f(Root* vlSelf) { vlSelf->scratch = 0U; }", False),
        }
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            folder = Path(directory)
            for name, (body, expected) in cases.items():
                with self.subTest(name=name):
                    (folder / "generated.cpp").write_text(body)
                    proof = scratch_proofs(folder, ["fixture___024root.scratch"])
                    self.assertEqual(proof["fixture___024root.scratch"]["proven"], expected)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--fixture-root":
        sys.exit("usage: boot_logical_state_test.py --fixture-root PROJECT_OUTPUT_DIRECTORY")
    FIXTURE_ROOT = Path(sys.argv[2]).resolve()
    FIXTURE_ROOT.relative_to(Path(__file__).resolve().parents[1] / "evidence/preparation")
    FIXTURE_ROOT.mkdir(exist_ok=False)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LogicalStateSensitivity)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "soc_simulation": False}))
    sys.exit(0 if result.wasSuccessful() else 1)
