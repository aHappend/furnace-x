#!/usr/bin/env python3
"""Bounded runner self-test, including deliberate timeout and descendant cleanup."""

import argparse
import copy
import datetime
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def fixedpoint_contract(output, receipt):
    from generated_eval import transform
    header = (ROOT / "tests/generated_eval_cache.h").read_text()
    (output / "generated_eval_cache.h").write_text(header)
    program = r'''
#include "generated_eval_cache.h"
#include <cassert>
int main() {
    using namespace furnace_generated;
    struct Model { unsigned input, output, counter; } a{3, 0, 0}, b{7, 0, 0};
    FixedPointCache cache;
    unsigned evaluated = 0, reused = 0;
    auto apply = [&](Model& m) {
        const Field fields[] = {{&m.input, sizeof(m.input)}, {&m.output, sizeof(m.output)}};
        if (cache.reuse(&m, fields)) { ++reused; return; }
        ++evaluated;
        m.output = m.input * 11;
        cache.fixed = cache.matches(fields);
    };
    apply(a); assert(a.output == 33 && !cache.fixed);
    apply(a); assert(cache.fixed);
    apply(a); assert(reused == 1 && evaluated == 2);
    a.output = 5; apply(a); assert(a.output == 33 && !cache.fixed);
    a.input = 9; apply(a); assert(a.output == 99);
    apply(b); assert(b.output == 77);
    apply(a); assert(a.output == 99);
    FixedPointCache sequential;
    for (unsigned i = 0; i < 100; ++i) {
        const Field fields[] = {{&a.counter, sizeof(a.counter)}};
        assert(!sequential.reuse(&a, fields));
        ++a.counter;
        sequential.fixed = sequential.matches(fields);
        assert(!sequential.fixed);
    }
    assert(a.counter == 100);
    unsigned char storage[16]{};
    FixedPointCache fragments;
    const Field fields[] = {{storage + 12, 4}, {storage + 4, 4}, {storage, 4}};
    fragments.bind(storage, fields);
    assert(fragments.ranges.size() == 2 && fragments.bytes.size() == 12);
    assert(!fragments.reuse());
    fragments.fixed = fragments.matches();
    assert(fragments.reuse());
    storage[8] = 1; assert(fragments.reuse());
    storage[12] = 1; assert(!fragments.reuse());
}
'''
    (output / "fixedpoint.cpp").write_text(program)
    run(["g++", "--version"], output, "compiler-version", receipt)
    run(["g++", "-std=c++17", "-O3", output.relative_to(ROOT) / "fixedpoint.cpp",
         "-o", output.relative_to(ROOT) / "fixedpoint"],
        output, "fixedpoint-build", receipt)
    run([output.relative_to(ROOT) / "fixedpoint"], output, "fixedpoint-run", receipt)
    receipt["comparisons"] += 217
    prefix = ("VL_INLINE_OPT void model___nba_sequent__TOP__2"
              "(Vfurnace_x4_top___024root* vlSelf) {\n// Body\n")
    body = "    vlSelf->aes__DOT__out = vlSelf->aes__DOT__in;\n" * 10000
    changed, rows = transform(prefix + body + "\n}")
    assert len(rows) == 1 and rows[0]["fields"] == ["aes__DOT__in", "aes__DOT__out"]
    assert body in changed
    receipt["comparisons"] += 2
    for forbidden in ("boot_retire(1);", "vlSymsp->callback();", "return;", "while (1) {}"):
        try:
            transform(prefix + body + forbidden + "\n}")
        except ValueError:
            receipt["comparisons"] += 1
        else:
            raise AssertionError(f"fixed-point optimizer accepted side effect: {forbidden}")


def reject_stale_compilation(manifest_path, output, receipt):
    from boot_compilation import reusable_boot
    manifest = json.loads(manifest_path.read_text())
    paths = [manifest_path, project_path(Path(manifest["executable"])),
             project_path(Path(manifest["compilation_receipt"]))]
    identities = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    receipt["reuse_guard_fixture"] = identities
    fixture = manifest["binding"]
    cases = []
    for changed in ("source_sha256", "tool_versions", "image_manifest_sha256"):
        guard_output = output / f"guard-{changed}-{uuid.uuid4().hex[:8]}"
        guard_output.mkdir()
        consumer = copy.deepcopy(fixture)
        if changed == "source_sha256":
            consumer[changed]["tests/intentional-stale-fixture"] = "0" * 64
        elif changed == "tool_versions":
            consumer[changed]["intentional-stale-tool"] = {"stdout": "not the bound tool"}
        else:
            consumer[changed] = "0" * 64
        try:
            reusable_boot(manifest_path.parent, guard_output, consumer, 2,
                          fixture["compile_profile"], audit=fixture["audit_state"])
        except ValueError as error:
            assert "identity mismatch" in str(error), str(error)
        else:
            raise AssertionError(f"reused executable with changed {changed}")
        cases.append(changed)
        receipt["comparisons"] += 1
    assert {str(p.relative_to(ROOT)): digest(p) for p in paths} == identities
    receipt["comparisons"] += 1
    receipt["stale_compilation_rejections"] = cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-manifest", type=Path,
                        help="Retained executable fixture for non-executing identity-guard checks")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "evidence/preparation" / f"runner-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/runner_contract.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {name: digest(ROOT / name) for name in (
            "tests/boot_probe.py", "tests/boot_compilation.py",
            "tests/runner_contract.py", "tests/verify.py",
            "tests/generated_eval.py", "tests/generated_eval_cache.h",
        )}, "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 600, "commands": [], "comparisons": 0,
    }
    save(output, receipt)
    status = 1
    try:
        run(["python3", "--version"], output, "version", receipt)
        fixedpoint_contract(output, receipt)
        run(["python3", "tests/verify.py", "--help"], output, "entrypoint-help", receipt)
        help_text = (output / "entrypoint-help.stdout.txt").read_text()
        assert "{behavior,linux,defects,synthesis,portability}" in help_text
        receipt["comparisons"] += 1
        invalid = run(["python3", "tests/verify.py", "--suite", "behavior",
                       "--seeds", "17"], output, "entrypoint-invalid-seeds", receipt,
                      check=False)
        assert invalid["exit_code"] == 2
        assert "required seed sequence is 17,89,211" in (
            output / invalid["stderr"]).read_text()
        receipt["comparisons"] += 1
        run(["python3", "-c", "print('runner-success')"], output, "success", receipt)
        result = run(["python3", "-c", "import sys; sys.exit(7)"],
                     output, "nonzero", receipt, check=False)
        assert result["exit_code"] == 7 and not result["timed_out"]
        receipt["comparisons"] += 1
        marker = output.relative_to(ROOT) / "escaped-child.txt"
        grandchild = (
            "import time; from pathlib import Path; time.sleep(3); "
            f"Path({str(marker)!r}).write_text('child escaped cleanup')"
        )
        parent = (
            "import subprocess,time; "
            f"subprocess.Popen(['python3','-c',{grandchild!r}]); "
            "print('descendant launched',flush=True); time.sleep(10)"
        )
        try:
            # This short timeout tests timeout machinery, not RTL liveness.
            run(["python3", "-c", parent], output, "expected-timeout", receipt,
                timeout_s=0.5)
        except RuntimeError as error:
            assert "execution timeout" in str(error)
        else:
            raise AssertionError("runner accepted a timed-out command")
        record = receipt["commands"][-1]
        assert record["timed_out"] and record["exit_code"] != 0
        assert "descendant launched" in (output / record["stdout"]).read_text()
        receipt["comparisons"] += 1
        time.sleep(3.2)
        assert not (ROOT / marker).exists(), "descendant survived process-group cleanup"
        receipt["comparisons"] += 1
        try:
            run(["python3", "-c", "print('overwrite')"], output, "success", receipt)
        except ValueError as error:
            assert "overwrite" in str(error)
        else:
            raise AssertionError("runner overwrote an earlier command log")
        assert (output / "success.stdout.txt").read_text() == "runner-success\n"
        receipt["comparisons"] += 1
        try:
            run(["./tests/nonexistent-runner-fixture"], output, "launch-error", receipt)
        except OSError:
            pass
        else:
            raise AssertionError("missing executable accepted")
        assert receipt["commands"][-1]["launch_error"]
        assert receipt["commands"][-1]["end_utc"]
        receipt["comparisons"] += 1
        if args.reuse_manifest:
            reject_stale_compilation(project_path(args.reuse_manifest), output, receipt)
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError, AssertionError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(json.dumps({"receipt": str(output.relative_to(ROOT) / "receipt.json"),
                      "exit_code": status, "comparisons": receipt["comparisons"]}))
    return status


if __name__ == "__main__":
    sys.exit(main())
