"""Portable L1 verification; delivery is not yet verification-complete.

Implemented entry paths:
  smoke: reference KATs, four public arithmetic kernels, authenticated single-pair
         complete SoC, corrupted candidate rejection, reset/startup/stall checks.
  synthesis: procedural Yosys synthesis of three complete configurations, syntax
             conversion behavioral comparison, literal hierarchy and cell checks.

Saved independent compiled probes additionally cover malformed vision/audio
streams, mismatched fusion IDs, full record-ring reservation/release, both lead
directions, authenticated bank retention, and exact three-mode legacy arithmetic.
They remain advisory until integrated into complete admitted check suites.

Unfinished: the complete 7x3 behavioral matrix with exhaustive per-frame leaf
vectors; complete legacy/security and CSR/DMA fault matrix; exhaustive QoS,
protocol and parameter-boundary checks; eight functional mutation kills; and
fresh-tree reproduction. Unfinished suites deliberately fail, never skip.
The shared runtime owns native timing and hardware gates and product reporting.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_support import ROOT, Run
from yosys_input import prepare_sources


SUITES = ("smoke", "behavior", "compatibility", "protocol", "mutations",
          "synthesis", "reproduction")


def synthesis(run):
    """Lower packed-vector syntax, preserving all procedural RTL for Yosys."""
    run.command(["yosys", "-V"], "yosys-version")
    lowered_sources = prepare_sources(run)
    # Exercise the actual syntax-lowered complete hierarchy as well as the
    # original source. Conversion is not allowed to create a passing netlist by
    # disconnecting public functionality.
    import probe_soc
    probe_soc.execute(run, probe_soc.CELLS[1], 17, "iverilog",
                      sources=lowered_sources)
    configurations = (
        ("default", {}),
        ("singleton", dict(MAX_TILE_BYTES=64, RING_DEPTH=1, IN_WIDTH=1,
                           IN_HEIGHT=1, OUT_WIDTH=1, OUT_HEIGHT=1, FFT_N=8,
                           FUSION_DEPTH=1)),
        ("nonpower", dict(MAX_TILE_BYTES=256, RING_DEPTH=3, IN_WIDTH=5,
                          IN_HEIGHT=3, OUT_WIDTH=7, OUT_HEIGHT=2, FFT_N=32,
                          FUSION_DEPTH=3)),
    )
    results = []
    for label, params in configurations:
        netlist = run.path / f"{label}.json"
        overrides = " ".join(f"-chparam {k} {v}" for k, v in params.items())
        script = (
            f"read_verilog -sv {' '.join(lowered_sources)}; "
            f"hierarchy -check -top furnace_x2_top {overrides}; "
            "proc; opt_expr; opt_clean; check -assert; "
            "memory -nomap; opt_clean; check -assert; stat; "
            f"write_json {netlist}"
        )
        run.command(["yosys", "-Q", "-T", "-p", script], f"{label}-synthesis")
        design = json.loads((ROOT / netlist).read_text())
        modules = design["modules"]
        counts = {}
        paths = {}
        subtree_state = {}
        leaf_cells = []

        def walk(module_name, path):
            module = modules[module_name]
            if module.get("attributes", {}).get("blackbox", 0):
                raise AssertionError(f"unresolved black box at {path}")
            original = module.get("attributes", {}).get("hdlname", module_name)
            original = original.split()[0].lstrip("\\")
            counts[original] = counts.get(original, 0) + 1
            paths[path] = original
            local_state = 0
            for name, cell in module.get("cells", {}).items():
                child = cell["type"]
                if child in modules:
                    local_state += walk(child, f"{path}.{name}")
                elif child.startswith("$"):
                    leaf_cells.append(cell)
                    local_state += int("dff" in child.lower() or child.startswith("$mem"))
                else:
                    raise AssertionError(f"unresolved cell {child} at {path}.{name}")
            output_bits = [bit for port in module.get("ports", {}).values()
                           if port["direction"] == "output" for bit in port["bits"]]
            subtree_state[path] = (local_state, sum(isinstance(b, int) for b in output_bits))
            return local_state

        walk("furnace_x2_top", "furnace_x2_top")
        forbidden = [c["type"] for c in leaf_cells
                     if "latch" in c["type"].lower()
                     or c["type"] in ("$div", "$mod", "$divfloor", "$modfloor")]
        if forbidden:
            raise AssertionError(f"forbidden synthesized cells: {forbidden[:16]}")
        required = {
            "vision_frontend": "furnace_x2_vision",
            "audio_frontend": "furnace_x2_audio",
            "fusion_buffer": "furnace_fusion_buffer",
            "unified_tensor": "furnace_tensor8",
            "axi_crossbar": "furnace_axi4_qos_xbar",
            "bilinear_kernel": "furnace_bilinear_pipe",
            "spatial_kernel": "furnace_spatial3x3_pipe",
            "fir_kernel": "furnace_fir4_pipe",
            "fft_kernel": "furnace_fft_radix2",
        }
        for instance, module in required.items():
            hits = [p for p, m in paths.items()
                    if p.split(".")[-1] == instance and m == module]
            if len(hits) != 1:
                raise AssertionError(f"{instance}/{module}: observed {hits}")
            if min(subtree_state[hits[0]]) == 0:
                raise AssertionError(f"constant/stateless replacement at {hits[0]}")
        if counts.get("furnace_tensor8") != 1:
            raise AssertionError("X2 must contain exactly one active tensor")
        for module, minimum in {
            "furnace_aes128_block": 1, "furnace_aes128_gcm": 1,
            "furnace_ghash_mul": 1, "furnace_lz4_frontend": 1,
            "furnace_xxh32": 3, "furnace_command_ring": 1,
            "furnace_x2_csr": 1, "furnace_dma128": 4,
        }.items():
            if counts.get(module, 0) < minimum:
                raise AssertionError(f"missing active legacy functionality: {module}")
        state = sum("dff" in c["type"].lower() for c in leaf_cells)
        memories = sum(c["type"].startswith("$mem") for c in leaf_cells)
        arithmetic = sum(c["type"] in ("$add", "$sub", "$mul") for c in leaf_cells)
        if min(state, memories, arithmetic) == 0:
            raise AssertionError("missing substantive state/memory/arithmetic")
        results.append(dict(configuration=label, parameters=params, state_cells=state,
                            memory_cells=memories, arithmetic_cells=arithmetic,
                            forbidden_cells=0, module_instances=counts))
    run.receipt["synthesis"] = results


def smoke(run):
    import kernel_checks
    import probe_soc
    run.command(["iverilog", "-V"], "iverilog-version")
    run.command(["vvp", "-V"], "vvp-version")
    run.command(["python3", "-m", "unittest", "discover", "-s", "tests",
                 "-p", "test_*_oracle.py"], "independent-reference-selfchecks")
    for kind in range(4):
        kernel_checks.execute(run, kind, 8, "iverilog")
    probe_soc.execute(run, probe_soc.CELLS[1], 17, "iverilog")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--preparation", action="store_true",
                        help="Retain an advisory preparation execution")
    parser.add_argument("--repair-of")
    parser.add_argument("--kernel", type=int, choices=range(4),
                        help="Preparation-only focused kernel probe")
    parser.add_argument("--fft-n", type=int, choices=(8, 16, 32, 64), default=16)
    parser.add_argument("--simulator", choices=("iverilog", "verilator"), default="iverilog")
    parser.add_argument("--tensor", action="store_true", help="Preparation-only tensor probe")
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--matrix-cell", type=int, choices=range(7),
                        help="Preparation-only one-cell matrix diagnostic")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--fusion-depth", type=int, choices=(1, 3, 16))
    parser.add_argument("--qos", action="store_true")
    parser.add_argument("--mutation", type=int, choices=range(8),
                        help="Preparation-only one mutation and unmutated control")
    parser.add_argument("--parameters", action="store_true")
    parser.add_argument("--security-kind", type=int, choices=range(4))
    parser.add_argument("--legacy-soc", action="store_true")
    parser.add_argument("--csr", action="store_true")
    args = parser.parse_args()
    run = Run(f"l1-{args.suite}", ["python3", *sys.argv],
              preparation=args.preparation, repair_of=args.repair_of)
    error = None
    try:
        if args.csr:
            if not args.preparation:
                raise ValueError("--csr requires --preparation")
            import csr_checks
            csr_checks.execute(run)
        elif args.legacy_soc:
            if not args.preparation:
                raise ValueError("--legacy-soc requires --preparation")
            import legacy_soc_checks
            legacy_soc_checks.execute(run, args.reference, args.seed, limit=6)
        elif args.security_kind is not None:
            if not args.preparation:
                raise ValueError("--security-kind requires --preparation")
            import security_checks
            security_checks.execute(run, args.security_kind, args.reference, args.simulator)
        elif args.parameters:
            if not args.preparation:
                raise ValueError("--parameters requires --preparation")
            import parameter_checks
            parameter_checks.execute(run)
        elif args.mutation is not None:
            if not args.preparation:
                raise ValueError("--mutation requires --preparation")
            import mutation_checks
            mutation_checks.one(run, args.mutation)
        elif args.qos:
            if not args.preparation:
                raise ValueError("--qos requires --preparation")
            import qos_checks
            qos_checks.execute(run, simulator=args.simulator)
        elif args.fusion_depth is not None:
            if not args.preparation:
                raise ValueError("--fusion-depth requires --preparation")
            import fusion_checks
            fusion_checks.execute(run, args.fusion_depth)
        elif args.matrix_cell is not None:
            if not args.preparation:
                raise ValueError("--matrix-cell requires --preparation")
            import matrix_checks
            matrix_checks.execute_cell(run, args.matrix_cell, args.seed)
        elif args.tensor:
            if not args.preparation:
                raise ValueError("--tensor requires --preparation")
            import tensor_checks
            tensor_checks.execute(run, reference=args.reference)
        elif args.kernel is not None:
            if not args.preparation:
                raise ValueError("--kernel requires --preparation; mandatory suites are not subsets")
            import kernel_checks
            run.command([args.simulator, "-V" if args.simulator == "iverilog" else "--version"],
                        "compiler-version")
            if args.simulator == "iverilog":
                run.command(["vvp", "-V"], "simulator-version")
            kernel_checks.execute(run, args.kernel, args.fft_n, args.simulator)
        elif args.suite == "synthesis":
            synthesis(run)
        elif args.suite == "smoke":
            smoke(run)
        elif args.suite == "behavior":
            import matrix_checks
            matrix_checks.execute(run)
        elif args.suite == "mutations":
            import mutation_checks
            mutation_checks.execute(run)
        elif args.suite == "reproduction":
            import reproduction_checks
            reproduction_checks.execute(run)
        else:
            raise NotImplementedError(
                f"{args.suite} suite is not yet implemented; no acceptance claimed")
    except Exception as caught:
        error = caught
    finally:
        run.finish(error)
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
