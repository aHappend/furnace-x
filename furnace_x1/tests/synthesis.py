"""Real memory-preserving Yosys synthesis with live-hierarchy checks."""

import json
from pathlib import Path


ENGINES = {"furnace_csr", "furnace_command_ring", "furnace_axi4_xbar",
           "furnace_lz4_frontend", "furnace_aes128_gcm", "furnace_tensor8"}


def synthesize(run, max_tile, depth, name, rtl=None):
    rtl = rtl or sorted((run.root / "rtl").glob("*.sv"))
    script = run.directory / (name + ".ys")
    netlist = run.directory / (name + ".json")
    script.write_text(
        "read_verilog -sv " + " ".join(str(p) for p in rtl) + "\n"
        + f"chparam -set MAX_TILE_BYTES {max_tile} -set RING_DEPTH {depth} furnace_x1_top\n"
        + "hierarchy -check -top furnace_x1_top\n"
        + "proc\nopt_expr\nopt_clean\ncheck -noinit -assert\n"
        + "memory -nomap\nopt_clean\ncheck -noinit -assert\nstat\n"
        + f"write_json {netlist}\n"
    )
    run.command(["yosys", "-Q", "-T", "-s", script], name)
    modules = json.loads(netlist.read_text())["modules"]
    live = []
    cells = []
    memory_bits = 0

    def visit(module_name, path):
        nonlocal memory_bits
        module = modules[module_name]
        if int(module.get("attributes", {}).get("blackbox", "0"), 2):
            raise AssertionError(f"unresolved black box at {path}")
        source_name = module.get("attributes", {}).get("hdlname", module_name).split()[0].lstrip("\\")
        live.append(source_name)
        if not module.get("cells") or not module.get("ports"):
            raise AssertionError(f"empty live module: {path}")
        for port_name, port in module["ports"].items():
            if port["direction"] == "output" and port_name.endswith(("valid", "result", "irq")):
                if all(isinstance(bit, str) for bit in port["bits"]):
                    raise AssertionError(f"constant functional output: {path}.{port_name}")
        for cell_name, cell in module["cells"].items():
            kind = cell["type"]
            if kind in modules:
                visit(kind, path + "." + cell_name)
            else:
                cells.append(kind)
                if "latch" in kind.lower() or kind.lower() in (
                    "$div", "$mod", "$divfloor", "$modfloor"
                ):
                    raise AssertionError(f"forbidden synthesized cell {path}.{cell_name}: {kind}")
                if not kind.startswith("$"):
                    raise AssertionError(f"unresolved cell {kind}")
                if kind.startswith("$mem"):
                    parameters = cell["parameters"]
                    if "SIZE" in parameters and "WIDTH" in parameters:
                        memory_bits += int(parameters["SIZE"], 2) * int(parameters["WIDTH"], 2)

    visit("furnace_x1_top", "furnace_x1_top")
    missing = ENGINES - set(live)
    if missing:
        raise AssertionError(f"integrated hierarchy missing engines: {sorted(missing)}")
    if memory_bits < 65536 * 8 or not any("dff" in c.lower() for c in cells):
        raise AssertionError("live history/state storage absent")
    record = dict(max_tile=max_tile, depth=depth, live_modules=live, memory_bits=memory_bits,
                  latch_cells=0, div_mod_cells=0, unresolved_cells=0, structural_errors=0,
                  synthesized_cells=len(cells))
    run.receipt.setdefault("synthesis", []).append(record)
    run.save()
    return record
