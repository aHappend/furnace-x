#!/usr/bin/env python3
"""Bounded comparator sensitivity fixtures; no SoC execution or acceptance claim."""

import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_logical_state import (
    MAGIC, SAVE_HEADER, SAVE_TRAILER, compare_fields, declarations, equivalent, flat_fields,
    read_fields, scratch_proofs, serializer_writes, sha256, type_shape,
    schema, unserialized_fields, validate_accounting, validate_raw_capture, write_exporter,
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


def exporter_fixture(output, receipt):
    """Execute the generated codec on known storage, not a replacement SoC."""
    from boot_probe import ROOT, digest, run, save

    directory = output / "codec-fixture"
    directory.mkdir()
    root = "Vfurnace_x4_top___024root"
    model = fixture_model()
    model["classes"] = {root: model["classes"].pop("fixture___024root")}
    (directory / (root + ".h")).write_text(
        "#pragma once\n#include <cstdint>\n"
        "struct Vfurnace_x4_top___024root {\n"
        "  uint8_t state;\n  uint8_t bytes[2][3];\n  uint32_t wide[3];\n};\n")
    (directory / "Vfurnace_x4_top__Syms.h").write_text(
        '#pragma once\n#include "Vfurnace_x4_top___024root.h"\n'
        "struct Vfurnace_x4_top { Vfurnace_x4_top___024root *rootp; };\n")
    write_exporter(directory, model)
    (directory / "fixture.cpp").write_text(
        '#include "boot_logical_capture.h"\n'
        "int main(int argc, char **argv) {\n"
        "  if (argc != 2) return 2;\n"
        "  Vfurnace_x4_top___024root state{5, {{1, 2, 3}, {4, 5, 6}},\n"
        "      {0x12345678U, 0xabcdef01U, 0xfedcba98U}};\n"
        "  Vfurnace_x4_top dut{&state};\n"
        "  furnace_logical_capture(argv[1], dut);\n"
        "  return 0;\n}\n")
    receipt["codec_fixture"] = {
        "source_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in sorted(directory.iterdir()) if path.suffix in (".h", ".cpp")},
        "scope": "Known C++ storage codec only; not RTL simulation, Linux or workload coverage.",
    }
    save(output, receipt)
    relative = directory.relative_to(ROOT)
    run(["g++", "-std=c++17", relative / "fixture.cpp", "-o", relative / "fixture"],
        output, "codec-fixture-compile", receipt)
    run([relative / "fixture", relative / "logical-state.bin"],
        output, "codec-fixture-execute", receipt)
    observed = read_fields(directory / "logical-state.bin", flat_fields(model))
    expected = {root + ".state": b"\x05", root + ".bytes": bytes(range(1, 7)),
                root + ".wide": struct.pack("=3I", 0x12345678, 0xabcdef01, 0xfedcba98)}
    if observed != expected:
        raise ValueError("compiled tagged codec changed scalar, array ordering or wide/high bits")
    receipt["codec_fixture"].update({
        "compared_fields": len(expected), "compared_storage_bytes": sum(map(len, expected.values())),
        "capture_sha256": digest(directory / "logical-state.bin"),
        "executable_sha256": digest(directory / "fixture"),
    })
    save(output, receipt)


class LogicalStateSensitivity(unittest.TestCase):
    def test_changed_python_entrypoints_compile(self):
        for name in ("boot_logical_state.py", "boot_logical_state_test.py",
                     "boot_lifetime.py", "boot_task_graph.py", "boot_scheduler.py",
                     "boot_native_threads_probe.py", "boot_probe.py",
                     "boot_compilation.py", "verify.py"):
            path = Path(__file__).with_name(name)
            compile(path.read_text(), str(path), "exec")

    def test_existing_compilation_path_is_not_promoted(self):
        from boot_compilation import binding, compile_boot
        from boot_probe import ROOT

        receipt = {"source_sha256": {}, "tool_versions": {}, "image_manifest_sha256": "image"}
        self.assertNotIn("logical_state", binding(receipt, "baseline", True))
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            output = Path(directory)
            for profile in ("baseline", "native-threads-candidate"):
                with patch("boot_compilation.run") as execute:
                    compile_boot(output, receipt, 2, profile, audit=True)
                command = execute.call_args.args[0]
                self.assertIn("--build", command)
                self.assertIn("--savable", command)
                self.assertIn("-DFURNACE_BOOT_AUDIT", command[command.index("-CFLAGS") + 1])
                self.assertNotIn("-DFURNACE_BOOT_LOGICAL_AUDIT",
                                 command[command.index("-CFLAGS") + 1])
                self.assertFalse((output / "obj/logical-schema.json").exists())
            output.relative_to(ROOT)

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
        plan["candidate"]["classes"]["fixture___024root"]["unserialized_scheduler"][
            "task_state"] = "VlMTaskVertex"
        plan["unserialized"] = unserialized_fields(plan["baseline"], plan["candidate"])
        with self.assertRaisesRegex(ValueError, "settled-boundary proof"):
            validate_accounting(plan)
        plan["unserialized"].clear()
        with self.assertRaisesRegex(ValueError, "omitted or introduced unserialized"):
            validate_accounting(plan)

    def test_scheduler_omission_parity_pending_and_pointer_sensitivity(self):
        from boot_scheduler import capture_fields, compare, validate_capture

        model = fixture_model()
        root = model["classes"]["fixture___024root"]
        root["unserialized_scheduler"] = {
            "__VnbaTriggered": "VlTriggerVec<65>",
            "__Vm_mtaskstate_final__nba": "VlMTaskVertex",
        }
        model["classes"]["fixture__Syms"] = {
            "fields": {}, "unserialized_scheduler": {},
            "unserialized_data": {
                "__Vm_even_cycle__nba": {
                    "bits": 1, "shape": [], "element_bytes": 1, "words": 1},
                "__Vm_even_cycle__ico": {
                    "bits": 1, "shape": [], "element_bytes": 1, "words": 1},
            },
        }
        trigger = "fixture___024root.__VnbaTriggered"
        vertex = "fixture___024root.__Vm_mtaskstate_final__nba"
        parity = "fixture__Syms.__Vm_even_cycle__nba"
        unused = "fixture__Syms.__Vm_even_cycle__ico"
        values = {trigger: bytes(16), vertex: b"\x02", parity: b"\x01", unused: b"\x00"}
        self.assertEqual(set(capture_fields(model)), set(values))
        plan = {"baseline": model, "candidate": copy.deepcopy(model)}
        self.assertEqual(compare(plan, values, values)["scheduler_exact_trigger_bytes"], 16)
        changed = dict(values)
        changed[trigger] = bytes(15) + b"\x80"
        with self.assertRaisesRegex(ValueError, "scheduler trigger mismatch"):
            compare(plan, values, changed)
        for field in values:
            changed = dict(values)
            del changed[field]
            with self.subTest(omitted=field), self.assertRaisesRegex(ValueError, "omitted"):
                validate_capture(model, changed)
        for field, corrupt in ((vertex, b"\x00"), (vertex, b"\x03"),
                               (vertex, b"\x01"), (parity, b"\x00"),
                               (parity, b"\x02"), (unused, b"\x01")):
            changed = dict(values)
            changed[field] = corrupt
            with self.subTest(field=field, value=corrupt), self.assertRaisesRegex(
                    ValueError, "pending task|parity mismatch"):
                validate_capture(model, changed)
        for field, spec in (("__Vm_modelp", "Vfurnace_x4_top* const"),
                            ("__Vm_threadPoolp", "VlThreadPool*")):
            identity = "fixture__Syms." + field
            model["classes"]["fixture__Syms"]["unserialized_scheduler"][field] = spec
            values[identity] = b"\x01"
            validate_capture(model, values)
            changed = dict(values)
            changed[identity] = b"\x00"
            with self.assertRaisesRegex(ValueError, "pointer topology"):
                validate_capture(model, changed)

    def test_scheduler_opaque_state_cannot_be_promoted_by_capture(self):
        from boot_scheduler import capture_fields

        plan = fixture_plan()
        root = plan["candidate"]["classes"]["fixture___024root"]
        root["unserialized_scheduler"]["__Vm_deleter"] = "VlDeleter"
        plan["unserialized"] = unserialized_fields(plan["baseline"], plan["candidate"])
        self.assertNotIn("fixture___024root.__Vm_deleter", capture_fields(plan["candidate"]))
        with self.assertRaisesRegex(ValueError, "settled-boundary proof"):
            validate_accounting(plan)
        row = next(iter(plan["unserialized"].values()))
        row["disposition"] = "settled_capture"
        row["proof"] = {"rule": "settled-scheduler-capture-v1",
                        "identity": "fixture___024root.__Vm_deleter",
                        "capture": {"bytes": 1, "capture": "empty"},
                        "generated_sha256": {}}
        with self.assertRaisesRegex(ValueError, "unproved settled-boundary"):
            validate_accounting(plan)

    def test_scheduler_missing_graph_keeps_vertex_and_pool_unresolved(self):
        from boot_scheduler import accounting

        model = fixture_model()
        model["classes"]["fixture___024root"]["unserialized_scheduler"] = {
            "__Vm_mtaskstate_final__nba": "VlMTaskVertex",
            "__Vm_threadPoolp": "VlThreadPool*",
        }
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            rows = accounting(model, Path(directory))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["disposition"] == "unresolved" for row in rows.values()))

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

    def test_full_schema_array_omission_and_incorrect_extent(self):
        root = "Vfurnace_x4_top___024root"
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            folder = Path(directory)
            (folder / (root + ".h")).write_text(
                "// DESIGN SPECIFIC STATE\n"
                "VlUnpacked<VlUnpacked<CData/*7:0*/, 3>, 2> bytes;\n"
                "// CONSTRUCTORS\n")
            (folder / "Vfurnace_x4_top__Syms.h").write_text(
                "// INTERNAL STATE\nbool __Vm_didInit = false;\n" + root + " TOP;\n"
                "// CONSTRUCTORS\n")
            (folder / "Vfurnace_x4_top__Syms.cpp").write_text(
                "void Vfurnace_x4_top__Syms::__Vserialize(VerilatedSerialize& os) {\n"
                "os << __Vm_didInit; TOP.__Vserialize(os);\n}\n")
            (folder / "Vfurnace_x4_top.cpp").write_text(
                "VerilatedSerialize& operator<<(VerilatedSerialize& os, Vfurnace_x4_top& rhs) {\n"
                "Verilated::quiesce(); rhs.vlSymsp->__Vserialize(os); return os;\n}\n")
            prefix = "void " + root + "::__Vserialize(VerilatedSerialize& os) {\n" + (
                "uint64_t __Vcheckval = 0x1234ULL; os << __Vcheckval; "
                "os << vlSymsp->_vm_contextp__; ")
            loops = ("for (int __Vi0 = 0; __Vi0 < 2; ++__Vi0) { "
                     "for (int __Vi1 = 0; __Vi1 < 3; ++__Vi1) { os << bytes[__Vi0][__Vi1]; }}")
            path = folder / (root + "__Slow.cpp")
            path.write_text(prefix + loops + "\n}\n")
            model = schema(folder)
            self.assertEqual(flat_fields(model)[root + ".bytes"]["bytes"], 6)
            path.write_text(prefix + loops.replace("__Vi1 < 3", "__Vi1 < 2") + "\n}\n")
            with self.assertRaisesRegex(ValueError, "incomplete serialized array"):
                schema(folder)
            path.write_text(prefix + loops + loops + "\n}\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                schema(folder)
            path.write_text(prefix + "\n}\n")
            model = schema(folder)
            self.assertIn("bytes", model["classes"][root]["unserialized_data"])

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
            "opaque_pointer": ("void f(Root* vlSelf) { vlSelf->scratch = 0U; }\n"
                               "void g(Root* vlSelf) { external(vlSelf); }", False),
        }
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            folder = Path(directory)
            for name, (body, expected) in cases.items():
                with self.subTest(name=name):
                    (folder / "generated.cpp").write_text(body)
                    proof = scratch_proofs(folder, ["fixture___024root.scratch"])
                    self.assertEqual(proof["fixture___024root.scratch"]["proven"], expected)

    def test_interprocedural_lifetimes_and_counterexamples(self):
        from boot_lifetime import entry_proofs
        from boot_logical_state import clean_cpp, closing

        writer = "void writer(Root* vlSelf) { vlSelf->scratch = vlSelf->state; }\n"
        reader = "void reader(Root* vlSelf) { consume(vlSelf->scratch); }\n"
        cases = {
            "ordered_calls": (writer + reader +
                              "void entry(Root* vlSelf) { writer(vlSelf); reader(vlSelf); }", True),
            "reordered_calls": (writer + reader +
                                "void entry(Root* vlSelf) { reader(vlSelf); writer(vlSelf); }", False),
            "separate_entries": (writer + reader, False),
            "correlated_conditions": (writer + reader + "void entry(Root* vlSelf) { "
                                      "if (vlSelf->enable) writer(vlSelf); "
                                      "if (vlSelf->enable) reader(vlSelf); }", True),
            "changed_condition": (writer + reader + "void entry(Root* vlSelf) { "
                                  "if (vlSelf->enable) writer(vlSelf); vlSelf->enable = 1U; "
                                  "if (vlSelf->enable) reader(vlSelf); }", False),
            "hidden_condition_write": (writer + reader +
                                       "void change(Root* vlSelf) { vlSelf->enable = 1U; }\n"
                                       "void entry(Root* vlSelf) { "
                                       "if (vlSelf->enable) writer(vlSelf); change(vlSelf); "
                                       "if (vlSelf->enable) reader(vlSelf); }", False),
            "external_condition_write": (writer + reader + "void entry(Root* vlSelf) { "
                                         "if (vlSelf->enable) writer(vlSelf); "
                                         "external(vlSelf->enable); "
                                         "if (vlSelf->enable) reader(vlSelf); }", False),
            "unstable_condition": (writer + reader + "void entry(Root* vlSelf) { "
                                   "if (external()) writer(vlSelf); "
                                   "if (external()) reader(vlSelf); }", False),
            "early_return": (
                "void writer(Root* vlSelf) { if (vlSelf->enable) return; "
                "vlSelf->scratch = 1U; }\n" + reader +
                "void entry(Root* vlSelf) { writer(vlSelf); reader(vlSelf); }", False),
            "conditional_definition": ("void entry(Root* vlSelf) { if (vlSelf->enable) "
                                       "vlSelf->scratch = 1U; consume(vlSelf->scratch); }", False),
            "compound_call": (writer +
                              "void entry(Root* vlSelf) { consume(vlSelf->scratch, writer(vlSelf)); }",
                              False),
            "self_read": ("void entry(Root* vlSelf) { vlSelf->scratch = vlSelf->scratch + 1U; }",
                          False),
            "partial_array_store": ("void entry(Root* vlSelf) { vlSelf->scratch[0] = 1U; "
                                    "consume(vlSelf->scratch); }", False),
            "zero_iteration": ("void entry(Root* vlSelf) { while (vlSelf->enable) { "
                               "vlSelf->scratch = 1U; } consume(vlSelf->scratch); }", False),
            "loop_local_lifetime": ("void entry(Root* vlSelf) { while (vlSelf->enable) { "
                                    "vlSelf->scratch = 1U; consume(vlSelf->scratch); } }", True),
            "loop_read_first": ("void entry(Root* vlSelf) { while (vlSelf->enable) { "
                                "consume(vlSelf->scratch); vlSelf->scratch = 1U; } }", False),
            "opaque_pointer": (writer + reader + "void entry(Root* vlSelf) { "
                                "writer(vlSelf); external(vlSelf); reader(vlSelf); }", False),
            "opaque_symbol_pointer": (writer + reader + "void entry(Root* vlSelf) { "
                                       "writer(vlSelf); external(vlSelf->vlSymsp); "
                                       "reader(vlSelf); }", False),
            "unknown_syntax": ("void entry(Root* vlSelf) { goto later; vlSelf->scratch = 1U; "
                               "later: consume(vlSelf->scratch); }", False),
            "returned_callee": (
                "bool reader(Root* vlSelf) { return vlSelf->scratch; }\n"
                "bool entry(Root* vlSelf) { return reader(vlSelf); }", False),
            "bool_helper": (
                "bool helper(Root* vlSelf) { vlSelf->scratch = 1U; consume(vlSelf->scratch); "
                "return true; }\nvoid entry(Root* vlSelf) { helper(vlSelf); }", True),
            "scope_and_ternary": (
                "void entry(Root* vlSelf) { vlSelf->scratch = vlSelf->enable ? 1U : 0U; "
                "Consumer::observe(vlSelf->scratch); }", True),
            "native_worker_prologue": (
                "void Vroot____Vthread__0(void* voidSelf, bool even_cycle) {\n"
                "VL_DEBUG_IF(VL_DBG_MSGF(\"worker\"); );\n"
                "Vroot* const __restrict vlSelf VL_ATTR_UNUSED = static_cast<Vroot*>(voidSelf);\n"
                "Vtop__Syms* const __restrict vlSymsp VL_ATTR_UNUSED = vlSelf->vlSymsp;\n"
                "Verilated::mtaskId(1); vlSelf->scratch = 1U; consume(vlSelf->scratch); }", True),
            "read_only_trigger_on_other_worker": (
                writer + reader +
                "void A____Vthread__0(Root* vlSelf) { "
                "if (8ULL & vlSelf->__VnbaTriggered.word(0U)) writer(vlSelf); "
                "if (8ULL & vlSelf->__VnbaTriggered.word(0U)) reader(vlSelf); }\n"
                "void B____Vthread__1(Root* vlSelf) { "
                "if (8ULL & vlSelf->__VnbaTriggered.word(0U)) unrelated(); }", True),
            "cross_worker": (
                "void A____Vthread__0(Root* vlSelf) { vlSelf->scratch = 1U; }\n"
                "void B____Vthread__1(Root* vlSelf) { consume(vlSelf->scratch); }", False),
            "local_shadow": ("void entry(Root* vlSelf) { int scratch = 0; "
                             "vlSelf->scratch = 1U; consume(vlSelf->scratch); }", False),
            "redeclared_condition": (writer + reader + "void entry(Root* vlSelf) { "
                                      "if (enable) writer(vlSelf); int enable = 1; "
                                      "if (enable) reader(vlSelf); }", False),
            "prefix_member_increment": (writer + reader + "void entry(Root* vlSelf) { "
                                        "if (vlSelf->enable) writer(vlSelf); ++vlSelf->enable; "
                                        "if (vlSelf->enable) reader(vlSelf); }", False),
            "prefix_local_increment": (writer + reader + "void entry(Root* vlSelf) { "
                                       "if (enable) writer(vlSelf); ++enable; "
                                       "if (enable) reader(vlSelf); }", False),
            "shift_assignment": (writer + reader + "void entry(Root* vlSelf) { "
                                  "if (vlSelf->enable) writer(vlSelf); vlSelf->enable <<= 1; "
                                  "if (vlSelf->enable) reader(vlSelf); }", False),
            "effectful_condition": (writer + reader + "void entry(Root* vlSelf) { "
                                     "if (++vlSelf->enable) writer(vlSelf); "
                                     "if (++vlSelf->enable) reader(vlSelf); }", False),
            "comma_declaration": (writer + reader + "void entry(Root* vlSelf) { "
                                   "if (enable) writer(vlSelf); int dummy = 0, enable = 1; "
                                   "if (enable) reader(vlSelf); }", False),
            "audited_scalar_helpers": (
                "void entry(Root* vlSelf) { vlSelf->scratch = VL_MULS_QQQ(49, "
                "VL_EXTENDS_QI(64, 32, vlSelf->a), vlSelf->b); consume(vlSelf->scratch); }", True),
            "helper_self_read": (
                "void entry(Root* vlSelf) { vlSelf->scratch = VL_SHIFTL_III(32,32,32,"
                "vlSelf->scratch, 1U); consume(vlSelf->scratch); }", False),
            "unknown_helper": (
                "void entry(Root* vlSelf) { vlSelf->scratch = unknown(vlSelf->a); "
                "consume(vlSelf->scratch); }", False),
            "field_address_escape": (
                "void entry(Root* vlSelf) { vlSelf->scratch = 1U; "
                "external(&vlSelf->scratch); consume(vlSelf->scratch); }", False),
        }
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            folder = Path(directory)
            for name, (body, expected) in cases.items():
                with self.subTest(name=name):
                    (folder / "generated.cpp").write_text(body)
                    proof = entry_proofs(folder, ["fixture___024root.scratch"], clean_cpp, closing)
                    row = proof["fixture___024root.scratch"]
                    self.assertEqual(row["proven"], expected, row)

    def test_guarded_payload_requires_complete_flag_lifetime(self):
        from boot_lifetime import entry_proofs
        from boot_logical_state import clean_cpp, closing

        payload = "__Vdlyvval__array__v0"
        flag = "__Vdlyvset__array__v0"
        reader = f"void reader(Root* vlSelf) {{ if (vlSelf->{flag}) consume(vlSelf->{payload}); }}\n"
        producer = (f"void producer(Root* vlSelf) {{ if (vlSelf->enable) {{ "
                    f"vlSelf->{payload} = vlSelf->data; vlSelf->{flag} = 1U; }} }}\n")
        for variant in ("correct", "missing_reset", "missing_payload", "reordered",
                        "early_return", "different_guard", "reset_after_producer"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
                reset = f"vlSelf->{flag} = 0U; "
                calls = "producer(vlSelf); reader(vlSelf);"
                prefix = producer + reader
                if variant == "missing_reset":
                    reset = ""
                if variant == "missing_payload":
                    prefix = prefix.replace(f"vlSelf->{payload} = vlSelf->data;", "")
                if variant == "reordered":
                    calls = "reader(vlSelf); producer(vlSelf);"
                if variant == "early_return":
                    prefix = prefix.replace(f"vlSelf->{payload} =", "if (vlSelf->bad) return; "
                                             f"vlSelf->{payload} =")
                    # A flag published before an early return is not safe.
                    prefix = prefix.replace("if (vlSelf->bad) return;",
                                            f"vlSelf->{flag} = 1U; if (vlSelf->bad) return;")
                if variant == "different_guard":
                    prefix = prefix.replace(f"if (vlSelf->{flag})", "if (vlSelf->other)")
                if variant == "reset_after_producer":
                    reset, calls = "", f"producer(vlSelf); vlSelf->{flag} = 0U; reader(vlSelf);"
                body = prefix + "void entry(Root* vlSelf) { " + reset + calls + " }"
                folder = Path(directory)
                (folder / "generated.cpp").write_text(body)
                row = entry_proofs(folder, ["fixture___024root." + payload],
                                   clean_cpp, closing)["fixture___024root." + payload]
                self.assertEqual(row["proven"], variant == "correct", row)

    def test_native_task_happens_before_and_scheduler_mutations(self):
        from boot_lifetime import entry_proofs
        from boot_logical_state import clean_cpp, closing

        root = "Vfixture___024root"
        worker0, worker1 = (root + "____Vthread__nba__" + str(i) for i in (0, 1))
        parity = "vlSymsp->__Vm_even_cycle__nba"
        body = (
            f"void writer({root}* vlSelf) {{ vlSelf->scratch = 1U; }}\n"
            f"void reader({root}* vlSelf) {{ consume(vlSelf->scratch); }}\n"
            f"void {worker0}({root}* vlSelf, bool even_cycle) {{\n"
            "Verilated::mtaskId(1);\n"
            "if ((8ULL & vlSelf->__VnbaTriggered.word(0U))) { writer(vlSelf); }\n"
            "Verilated::endOfThreadMTask(vlSymsp->__Vm_evalMsgQp);\n"
            "vlSelf->__Vm_mtaskstate_2.signalUpstreamDone(even_cycle);\n"
            "vlSelf->__Vm_mtaskstate_final__nba.signalUpstreamDone(even_cycle);\n}\n"
            f"void {worker1}({root}* vlSelf, bool even_cycle) {{\n"
            "vlSelf->__Vm_mtaskstate_2.waitUntilUpstreamDone(even_cycle);\n"
            "Verilated::mtaskId(2);\n"
            "if ((8ULL & vlSelf->__VnbaTriggered.word(0U))) { reader(vlSelf); }\n"
            "Verilated::endOfThreadMTask(vlSymsp->__Vm_evalMsgQp);\n"
            "vlSelf->__Vm_mtaskstate_final__nba.signalUpstreamDone(even_cycle);\n}\n"
            f"void {root}___eval_nba({root}* vlSelf) {{\n"
            f"{parity} = !{parity};\n"
            f"vlSymsp->__Vm_threadPoolp->workerp(0)->addTask(&{worker0}, vlSelf, {parity});\n"
            f"{worker1}(vlSelf, {parity});\nVerilated::mtaskId(0);\n"
            f"vlSelf->__Vm_mtaskstate_final__nba.waitUntilUpstreamDone({parity});\n}}\n")
        constructor = "__Vm_mtaskstate_2(1U), __Vm_mtaskstate_final__nba(2U)"
        for variant in ("correct", "wrong_fanin", "wrong_parity", "missing_final_join",
                        "unordered", "unknown_task_operation", "extra_entry", "duplicate_signal",
                        "read_only_fanout"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
                code, init = body, constructor
                if variant == "wrong_fanin":
                    init = init.replace("_2(1U)", "_2(2U)")
                elif variant == "wrong_parity":
                    code = code.replace(f"{worker1}(vlSelf, {parity})",
                                        f"{worker1}(vlSelf, !{parity})")
                elif variant == "missing_final_join":
                    code = code.replace(
                        f"vlSelf->__Vm_mtaskstate_final__nba.waitUntilUpstreamDone({parity});", "")
                elif variant == "unordered":
                    code = code.replace("vlSelf->__Vm_mtaskstate_2.signalUpstreamDone(even_cycle);", "")
                    code = code.replace("vlSelf->__Vm_mtaskstate_2.waitUntilUpstreamDone(even_cycle);", "")
                    init = "__Vm_mtaskstate_final__nba(2U)"
                elif variant == "unknown_task_operation":
                    code = code.replace("writer(vlSelf); }", "writer(vlSelf); extra(); }")
                elif variant == "extra_entry":
                    code += f"void extra({root}* vlSelf) {{ reader(vlSelf); }}\n"
                elif variant == "duplicate_signal":
                    code = code.replace("vlSelf->__Vm_mtaskstate_2.signalUpstreamDone(even_cycle);",
                                        "vlSelf->__Vm_mtaskstate_2.signalUpstreamDone(even_cycle); " * 2)
                elif variant == "read_only_fanout":
                    code = code.replace("consume(vlSelf->scratch)", "vlSelf->result = vlSelf->scratch")
                    signal = "vlSelf->__Vm_mtaskstate_2.signalUpstreamDone(even_cycle);\n"
                    code = code.replace(signal, signal + (
                        "Verilated::mtaskId(3);\n"
                        "if ((8ULL & vlSelf->__VnbaTriggered.word(0U))) { reader(vlSelf); }\n"
                        "Verilated::endOfThreadMTask(vlSymsp->__Vm_evalMsgQp);\n"), 1)
                folder = Path(directory)
                (folder / "generated.cpp").write_text(code)
                (folder / (root + "__Slow.cpp")).write_text(init)
                row = entry_proofs(folder, [root + ".scratch"], clean_cpp, closing)[root + ".scratch"]
                self.assertEqual(row["proven"], variant in ("correct", "read_only_fanout"), row)
                if variant == "correct":
                    self.assertEqual(row["native_task_graph"]["tasks"], 2)
                    self.assertEqual(row["ordered_native_regions"], ["1", "2"])

    def test_wide_and_array_storage_lifetimes(self):
        from boot_lifetime import entry_proofs
        from boot_logical_state import clean_cpp, closing

        identity = "fixture___024root.scratch"
        for shape, words in (([], 3), ([2, 3], 1)):
            indices = (["[0U]", "[1U]", "[2U]"] if not shape else
                       [f"[{i}U][{j}U]" for i in range(2) for j in range(3)])
            for variant in ("complete", "missing_tail", "read_before_tail", "bad_index"):
                with self.subTest(shape=shape, variant=variant), tempfile.TemporaryDirectory(
                        dir=FIXTURE_ROOT) as directory:
                    stores = [f"vlSelf->scratch{index} = vlSelf->data;" for index in indices]
                    reads = "".join(f"consume(vlSelf->scratch{index});" for index in indices)
                    if variant == "missing_tail":
                        stores.pop()
                    if variant == "read_before_tail":
                        stores.insert(0, reads)
                    if variant == "bad_index":
                        stores[-1] = "vlSelf->scratch[99U] = 0U;"
                    body = "void entry(Root* vlSelf) {" + "".join(stores) + reads + "}"
                    folder = Path(directory)
                    (folder / "generated.cpp").write_text(body)
                    row = entry_proofs(folder, [identity], clean_cpp, closing, {
                        identity: {"shape": shape, "words": words}})[identity]
                    self.assertEqual(row["proven"], variant == "complete", row)


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
