"""Self-contained admitted suites; no prior evidence or generated build is an input."""

import re
import shutil
import sys
import uuid

from execution import ROOT, Run, fresh, hashes
import interfaces
import mutations
import soc_cases
import synthesis
import yosys_packed


def child(parent, label, function):
    directory = fresh(label, preparation="preparation" in parent.directory.parts)
    run = Run(directory)
    run.receipt["parent_receipt"] = str(parent.directory.relative_to(ROOT) / "receipt.json")
    run.save()
    rows = parent.receipt.setdefault("runs", [])
    row = next((r for r in rows if r["label"] == label), None)
    if row is None:
        row = {"label": label}
        rows.append(row)
    elif row["outcome"] != "not_started":
        raise AssertionError(f"duplicate verification run: {label}")
    row.update(receipt=str(directory.relative_to(ROOT) / "receipt.json"), outcome="running")
    parent.save()
    try:
        function(run)
    except Exception as exc:
        run.finish("failed", exc)
        row["outcome"] = "failed"
        parent.save()
        raise AssertionError(f"{row['receipt']}: {exc}") from exc
    run.finish("passed")
    row["outcome"] = "passed"
    row["coverage"] = run.receipt["coverage"]
    parent.save()


def soc_build(run, api, simulator, max_tile, depth, rtl=None):
    tb = run.directory / "soc_tb.sv"
    tb.write_text((ROOT / "tests/soc_tb.sv").read_text().replace(
        "/* PUBLIC_DECLARATIONS */", interfaces.declarations()).replace(
        "/* PUBLIC_RESET_EXPRESSION */", interfaces.reset_expression()))
    parameters = ([f"-Psoc_tb.MAX_TILE_BYTES={max_tile}", f"-Psoc_tb.RING_DEPTH={depth}"]
                  if simulator == "iverilog" else [
                      f"-GMAX_TILE_BYTES={max_tile}", f"-GRING_DEPTH={depth}"])
    return api.compile_tb(run, "soc", simulator, parameters, rtl=rtl, tb=tb)


def soc_matrix_cell(run, api, max_tile, depth):
    command = soc_build(run, api, "verilator", max_tile, depth)
    rows = []
    for seed in (17, 89, 2026):
        path = run.directory / f"soc-seed-{seed}.txt"
        expected = soc_cases.generate(path, 24, max_tile, depth, seed)
        run.receipt.setdefault("soc_expected", {})[str(seed)] = expected
        run.save()
        _, stdout, _ = run.command([*command, "+vectors=" + str(path), f"+seed={seed}"], f"soc-seed-{seed}")
        match = re.search(r"COUNTS soc completed=(\d+) compared_bytes=(\d+) read_beats=(\d+) "
                          r"write_beats=(\d+) aw_stall=(\d+) w_stall=(\d+) ar_stall=(\d+)", stdout)
        if match is None or int(match[1]) != 24 or min(map(int, match.groups()[1:])) <= 0:
            raise AssertionError("absent SoC comparisons/independent channel stalls: " + stdout)
        success = [record for record in expected if record["status"] == 0]
        failed = [record for record in expected if record["status"] == 4]
        if len(success) < 12 or len(failed) < 4 or {r["mode"] for r in success} != {0, 1, 2}:
            raise AssertionError("integrated matrix thresholds not met")
        if {r["encoding"] for r in success} != {"literal", "raw", "overlap", "linked"}:
            raise AssertionError("integrated compression matrix not met")
        rows.append(dict(seed=seed, max_tile=max_tile, depth=depth, compared=24,
                         successful=len(success), tag_rejections=len(failed),
                         compared_bytes=int(match[2]), read_beats=int(match[3]),
                         write_beats=int(match[4])))
    run.receipt["coverage"]["integrated_matrix"] = rows
    run.save()


def illegal_parameter(run, api, name, parameters):
    if name == "soc":
        tb = run.directory / "soc_tb.sv"
        tb.write_text((ROOT / "tests/soc_tb.sv").read_text().replace(
            "/* PUBLIC_DECLARATIONS */", interfaces.declarations()).replace(
            "/* PUBLIC_RESET_EXPRESSION */", interfaces.reset_expression()))
    else:
        tb = ROOT / "tests/lz4_tb.sv"
    command = api.compile_tb(run, name, "iverilog", parameters, tb=tb)
    exit_code, stdout, stderr = run.command(command, "illegal-parameter-sim", expect=None, timeout=600)
    if exit_code == 0 or "PARAMETER ERROR" not in stdout + stderr:
        raise AssertionError("illegal value did not reach explicit diagnostic: " + stdout + stderr)
    run.receipt["coverage"]["explicit_parameter_diagnostic"] = parameters
    run.save()


def ring(run, api, depth):
    command = api.compile_tb(run, "ring", "iverilog", [f"-Pring_tb.RING_DEPTH={depth}"])
    _, stdout, _ = run.command(command, "ring-sim", timeout=600)
    match = re.search(rf"COUNTS ring depth={depth} comparisons=(\d+) wraps=8 coincidences=16", stdout)
    if match is None or int(match[1]) < 40:
        raise AssertionError("ring comparisons missing: " + stdout)
    run.receipt["coverage"]["ring"] = dict(depth=depth, comparisons=int(match[1]), wraps=8,
                                         pre_edge_capacity_collisions=16)
    run.save()


def parameter_diagnostics(run, api):
    for field, values in (("MAX_TILE_BYTES", (0, 65537)), ("RING_DEPTH", (0, 17))):
        for value in values:
            child(run, f"illegal-{field}-{value}", lambda r, f=field, v=value:
                  illegal_parameter(r, api, "soc", [f"-Psoc_tb.{f}={v}"]))
    for value in (0, 131073):
        child(run, f"illegal-decoder-{value}", lambda r, v=value:
              illegal_parameter(r, api, "lz4", [f"-Plz4_tb.MAX_DECODED_BYTES={v}"]))


def synthesis_matrix(run, api, configurations=((1, 1), (257, 3), (4096, 8), (65536, 16))):
    rtl = yosys_packed.sources(run)
    # Execute the generated syntax-lowered sources, not a bypass implementation.
    api.soc_probe(run, "iverilog", count=5, rtl=rtl)
    for max_tile, depth in configurations:
        synthesis.synthesize(run, max_tile, depth, f"yosys-{max_tile}-{depth}", rtl=rtl)
    if len(run.receipt["synthesis"]) != len(configurations):
        raise AssertionError("missing synthesis configurations")
    run.receipt["coverage"]["synthesized_configurations"] = list(configurations)
    run.save()


def portable(run):
    bundle = run.directory / ("bundle-" + uuid.uuid4().hex[:8])
    bundle.mkdir()
    for name in hashes():
        target = bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    copied = hashes(bundle)
    if copied != hashes():
        raise AssertionError("portable source hashes differ")
    run.receipt["portable_source_sha256"] = copied
    run.save()
    _, stdout, _ = run.command(
        ["python3", "tests/verify.py", "--probe", "portable-smoke"], "portable-fresh-process",
        cwd=bundle, timeout=3600)
    match = re.search(r"PREPARATION ONLY (evidence/preparation/[^ \n]+/receipt.json)", stdout)
    if match is None:
        raise AssertionError("portable child did not complete representative checks: " + stdout)
    import json
    receipt = json.loads((bundle / match[1]).read_text())
    if receipt["outcome"] != "passed" or receipt["source_sha256"] != copied:
        raise AssertionError("portable child sources/outcome not bound")
    expected = receipt.get("soc_expected", [])
    if (receipt["coverage"].get("soc_compared_descriptors") != 5 or not receipt.get("synthesis")
            or {r["mode"] for r in expected if r["status"] == 0} != {0, 1, 2}
            or not any(r["status"] == 4 for r in expected) or expected[-1]["status"] != 0):
        raise AssertionError("portable integrated/synthesis evidence absent")
    run.receipt["coverage"]["portable"] = {
        "copied_files": len(copied), "all_modes_and_tag_rejection": True,
        "child_receipt": str((bundle / match[1]).relative_to(ROOT)),
    }
    run.save()


def execute(suite, run, api):
    parameter_labels = [f"illegal-{field}-{value}" for field, values in
                        (("MAX_TILE_BYTES", (0, 65537)), ("RING_DEPTH", (0, 17)))
                        for value in values] + ["illegal-decoder-0", "illegal-decoder-131073"]
    required = {
        "behavior": ["icarus-tensor", "icarus-crypto", "icarus-lz4", "icarus-soc",
                     "tensor", "crypto", "lz4", "xbar", "soc-32-1", "soc-257-3", "soc-4096-8"],
        "boundaries": ["csr-icarus", "csr-verilator"] + [f"ring-{d}" for d in (1, 3, 8, 16)] +
                      [f"boundary-{m}-{d}" for m in (1, 16, 257, 4096, 65536) for d in (1, 3, 8, 16)] +
                      ["soc-fault-reset", "soc-integrated-65536", "soc-capacity-65536"] +
                      parameter_labels + ["lz4-bound-131072", "lz4-bound-65536", "lz4-bound-1",
                                          "singleton-crypto"],
    }
    if suite in required:
        run.receipt["runs"] = [{"label": label, "outcome": "not_started", "receipt": None}
                               for label in required[suite]]
    if suite == "synthesis":
        run.receipt["required_synthesis_configurations"] = [[1, 1], [257, 3], [4096, 8], [65536, 16]]
    if suite == "defects":
        run.receipt["mutation_ledger"] = {key: {"outcome": "not_started", "receipt": None}
                                          for key in mutations.MUTANTS}
    run.save()
    if suite == "behavior":
        run.versions(["python3", "iverilog", "vvp", "verilator", "make", "g++"])
        for label, fn in [
            ("icarus-tensor", lambda r: api.tensor_probe(r, "iverilog", 8)),
            ("icarus-crypto", lambda r: api.crypto_probe(r, "iverilog")),
            ("icarus-lz4", lambda r: api.lz4_probe(r, "iverilog")),
            ("icarus-soc", lambda r: api.soc_probe(r, "iverilog", 5)),
            ("tensor", api.tensor_probe), ("crypto", api.crypto_probe),
            ("lz4", api.lz4_probe), ("xbar", api.xbar_probe),
        ]:
            child(run, label, fn)
        for max_tile, depth in ((32, 1), (257, 3), (4096, 8)):
            child(run, f"soc-{max_tile}-{depth}",
                  lambda r, m=max_tile, d=depth: soc_matrix_cell(r, api, m, d))
    elif suite == "boundaries":
        run.versions(["python3", "iverilog", "vvp", "verilator", "make", "g++"])
        child(run, "csr-icarus", lambda r: api.csr_probe(r, "iverilog"))
        child(run, "csr-verilator", lambda r: api.csr_probe(r, "verilator"))
        for depth in (1, 3, 8, 16):
            child(run, f"ring-{depth}", lambda r, d=depth: ring(r, api, d))
        for max_tile in (1, 16, 257, 4096, 65536):
            for depth in (1, 3, 8, 16):
                child(run, f"boundary-{max_tile}-{depth}",
                      lambda r, m=max_tile, d=depth: api.soc_boundary_probe(
                          r, "iverilog", m, d, compact=True))
        child(run, "soc-fault-reset", lambda r: api.soc_boundary_probe(r, max_tile=257, depth=3))
        child(run, "soc-integrated-65536", lambda r: api.soc_boundary_probe(r, max_tile=65536, depth=16))
        child(run, "soc-capacity-65536", lambda r: api.soc_probe(
            r, max_tile=65536, depth=16, count=1, large=True))
        parameter_diagnostics(run, api)
        for bound in (131072, 65536, 1):
            child(run, f"lz4-bound-{bound}", lambda r, b=bound: api.lz4_probe(r, bound=b))
        child(run, "singleton-crypto", lambda r: api.crypto_probe(r, max_length=1))
    elif suite == "defects":
        run.versions(["python3", "verilator", "make", "g++"])
        for key in mutations.MUTANTS:
            run.receipt["mutation_ledger"][key]["outcome"] = "running"
            run.save()
            receipt = mutations.execute(key, api.compile_tb, api.tensor_vectors, preparation=False)
            run.receipt.setdefault("mutations", {})[key] = receipt
            run.receipt["mutation_ledger"][key] = {"outcome": "detected", "receipt": receipt}
            run.save()
        if len(run.receipt["mutations"]) != 6:
            raise AssertionError("missing mandatory detected mutants")
        run.receipt["coverage"]["functionally_detected_mutants"] = 6
    elif suite == "synthesis":
        run.versions(["python3", "yosys", "iverilog", "vvp"])
        synthesis_matrix(run, api)
    elif suite == "portable":
        run.versions(["python3", "iverilog", "vvp", "verilator", "make", "g++", "yosys"])
        portable(run)
    else:
        raise ValueError(f"unknown suite: {suite}")
    if hashes() != run.receipt["source_sha256"]:
        raise AssertionError("accepted verification/design sources changed during execution")
    if suite in required and any(row["outcome"] != "passed" for row in run.receipt["runs"]):
        raise AssertionError("required verification run missing or incomplete")
    run.save()
