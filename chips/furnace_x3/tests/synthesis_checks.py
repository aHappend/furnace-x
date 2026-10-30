"""Memory-preserving complete-hierarchy Yosys experiment and structural checks."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lower_packed import lower
from record import Experiment, ROOT
from matrix_checks import CELLS, PARAMETERS


def inspect_netlist(path, top):
    netlist = json.loads(path.read_text())
    modules = netlist["modules"]
    counts = Counter()
    states = Counter()
    memories = Counter()
    memory_bits = Counter()

    def visit(name, prefix):
        module = modules[name]
        if int(module.get("attributes", {}).get("blackbox", "0"), 2):
            raise AssertionError(f"blackbox at {prefix}")
        for cell_name, cell in module.get("cells", {}).items():
            kind = cell["type"]
            if kind in modules:
                identity = modules[kind].get("attributes", {}).get("hdlname", kind)
                counts[identity.split()[0].lstrip("\\")] += 1
                visit(kind, f"{prefix}.{cell_name}")
            elif kind.startswith("$"):
                if "latch" in kind.lower() or kind in ("$div", "$mod", "$divfloor", "$modfloor"):
                    raise AssertionError(f"forbidden structural cell {kind} at {prefix}.{cell_name}")
                if "dff" in kind.lower():
                    states[prefix] += len(cell["connections"].get("Q", []))
                if kind.startswith("$mem"):
                    memories[prefix] += 1
                    parameters = cell["parameters"]
                    if "WIDTH" in parameters and "SIZE" in parameters:
                        memory_bits[prefix] += (int(parameters["WIDTH"], 2) *
                                                int(parameters["SIZE"], 2))
            else:
                raise AssertionError(f"unresolved design instance {kind} at {prefix}.{cell_name}")

    visit(top, top)
    if not sum(states.values()):
        raise AssertionError("no substantive sequential state")
    if top == "furnace_x3_top":
        required = ("furnace_rv64im_core", "furnace_dma512", "furnace_x3_local_memory",
                    "furnace_x3_control", "furnace_hw_semaphores", "furnace_mailboxes",
                    "furnace_x3_cpu_axi_bridge", "furnace_x3_axi512_arb", "furnace_x3_mmio_arb",
                    "furnace_interrupt_aggregator", "furnace_x2_top", "furnace_tensor8",
                    "furnace_aes128_gcm", "furnace_lz4_frontend",
                    "furnace_x2_vision", "furnace_x2_audio", "furnace_fusion_buffer")
        for kind in required:
            if counts[kind] == 0:
                raise AssertionError(f"missing required hierarchy {kind}")
        if counts["furnace_axi128_to512"] != 4:
            raise AssertionError("missing four retained legacy memory adapters")
        for instance, minimum in (("control_cpu", 2048), ("burst_dma", 1),
                                  ("local_memory", 1), ("legacy_soc", 1),
                                  ("semaphores", 256), ("mailboxes", 1), ("interrupts", 32)):
            prefix = f"{top}.{instance}"
            state_bits = sum(bits for path, bits in states.items()
                             if path == prefix or path.startswith(prefix + "."))
            state_bits += sum(bits for path, bits in memory_bits.items()
                              if path == prefix or path.startswith(prefix + "."))
            if state_bits < minimum:
                raise AssertionError(f"insubstantial sequential state at {instance}: {state_bits}")
        local_rams = sum(count for path, count in memories.items()
                         if path.startswith(f"{top}.local_memory"))
        if local_rams < 2:
            raise AssertionError("local IMEM/DMEM were not preserved as memories")
        if sum(bits for path, bits in memory_bits.items()
               if path.startswith(f"{top}.local_memory")) < 2*16384*8:
            raise AssertionError("local instruction/data storage is smaller than the frozen ABI")
        direct = {"control_cpu": "furnace_rv64im_core", "control": "furnace_x3_control",
                  "local_memory": "furnace_x3_local_memory", "mmio_arbiter": "furnace_x3_mmio_arb",
                  "legacy_soc": "furnace_x2_top", "burst_dma": "furnace_dma512",
                  "semaphores": "furnace_hw_semaphores", "mailboxes": "furnace_mailboxes",
                  "interrupts": "furnace_interrupt_aggregator",
                  "cpu_memory_bridge": "furnace_x3_cpu_axi_bridge",
                  "memory_arbiter": "furnace_x3_axi512_arb"}
        for instance, identity in direct.items():
            cell = modules[top]["cells"].get(instance)
            if cell is None or cell["type"] not in modules:
                raise AssertionError(f"missing named direct boundary: {instance}")
            actual = modules[cell["type"]]["attributes"].get("hdlname", cell["type"])
            if actual.split()[0].lstrip("\\") != identity:
                raise AssertionError(f"incorrect named direct boundary: {instance}/{actual}")
    return {"instance_counts": dict(counts), "state_bits_by_instance": dict(states),
            "memory_cells_by_instance": dict(memories),
            "memory_bits_by_instance": dict(memory_bits)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", choices=("furnace_x3_top", "furnace_x2_top", "furnace_x1_top"),
                        default="furnace_x3_top")
    geometry = parser.add_mutually_exclusive_group()
    geometry.add_argument("--minimum", action="store_true")
    geometry.add_argument("--cell", choices=CELLS)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    if args.cell and args.top != "furnace_x3_top":
        parser.error("--cell selects a complete X3 geometry")
    experiment = Experiment("complete-hierarchy-synthesis", args.repair_of)
    try:
        experiment.command(["yosys", "-V"], "yosys-version", version=True)
        original = experiment.command(
            ["python3", "tests/x3_checks.py", "--engines", "--seed", "17"],
            "original-behavior")
        lowered_behavior = experiment.command(
            ["python3", "tests/x3_checks.py", "--engines", "--lowered", "--seed", "17"],
            "lowered-behavior")
        original_summary = [line for line in original.splitlines() if line.startswith("X3_")]
        lowered_summary = [line for line in lowered_behavior.splitlines() if line.startswith("X3_")]
        if not original_summary or original_summary != lowered_summary:
            raise AssertionError("original/lowered public-interface behavioral differences")
        sources = experiment.path / "lowered"
        sources.mkdir()
        mapping = []
        for path in sorted((ROOT / "rtl").glob("*.sv")):
            transformed, record = lower(path.read_text(), str(path.relative_to(ROOT)))
            (sources / path.name).write_text(transformed)
            mapping.append(record)
        (experiment.path / "lowering-map.json").write_text(json.dumps(mapping, indent=2) + "\n")
        config = ""
        if args.cell:
            config = (f"chparam " + " ".join(
                f"-set {name} {value}" for name, value in zip(PARAMETERS, CELLS[args.cell])) +
                f" {args.top}\n")
        if args.minimum:
            config = f"chparam -set MAX_TILE_BYTES 64 -set RING_DEPTH 1 {args.top}\n"
            if args.top != "furnace_x1_top":
                config += (f"chparam -set IN_WIDTH 1 -set IN_HEIGHT 1 -set OUT_WIDTH 1 "
                           f"-set OUT_HEIGHT 1 -set FFT_N 8 -set FUSION_DEPTH 1 {args.top}\n")
            if args.top == "furnace_x3_top":
                config += f"chparam -set MAILBOX_DEPTH 1 -set MAX_DMA_BYTES 1 {args.top}\n"
        script = experiment.path / "synthesis.ys"
        netlist = experiment.path / "netlist.json"
        files = " ".join(str(p.relative_to(ROOT)) for p in sorted(sources.glob("*.sv")))
        script.write_text(
            f"read_verilog -sv {files}\n{config}"
            f"hierarchy -check -top {args.top}\n"
            "proc\nopt_expr\nopt_clean\ncheck -assert\n"
            "memory -nomap\nopt_clean\ncheck -assert\nstat\n"
            f"write_json {netlist.relative_to(ROOT)}\n")
        experiment.command(["yosys", "-Q", "-T", "-s", str(script.relative_to(ROOT))],
                           "synthesize")
        result = inspect_netlist(netlist, args.top)
        (experiment.path / "structural.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"YOSYS_STRUCTURAL_PASS top={args.top} minimum={args.minimum} cell={args.cell}")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
