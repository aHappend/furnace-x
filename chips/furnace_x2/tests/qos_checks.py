"""Exhaustive strict-priority permutations and public AXI ownership checking."""

import hashlib
import itertools

from run_support import ROOT


def scenarios():
    cases = []
    for bank in range(4):
        for write in (0, 1):
            base = (bank << 16) | (write << 18)
            cases.append(base)
            for index, order in enumerate(itertools.permutations(range(4))):
                priorities = [0] * 4
                for source, value in zip(order, (15, 11, 5, 0)):
                    priorities[source] = value
                cases.append(base | ((index & 1) << 19)
                             | sum(q << (4*i) for i, q in enumerate(priorities)))
            for priority in (0, 7, 15):
                for repeat in range(4):
                    cases.append(base | ((repeat & 1) << 19)
                                 | sum(priority << (4*i) for i in range(4)))
            for malformed in range(1, 6):
                for source in range(4):
                    cases.append(base | (1 << 19) | (malformed << 20)
                                 | (source << 26) | 0x7531)
            if write:
                for wlast in (1, 2):
                    cases.append(base | (1 << 19) | (wlast << 24) | 0x7531)
                    for malformed in range(1, 6):
                        cases.append(base | (1 << 19) | (wlast << 24)
                                     | (malformed << 20) | 0x7531)
            cases.append(base | (3 << 24) | 0x00F0)
    return cases


def execute(run, sources=None, simulator="verilator"):
    cases = scenarios()
    path = run.path / "qos-cases.hex"
    (ROOT/path).write_text("".join(f"{case:08x}\n" for case in cases))
    run.receipt.setdefault("stimulus_sha256", {})[str(path)] = hashlib.sha256(
        (ROOT/path).read_bytes()).hexdigest()
    obj = run.path / "qos-obj"
    sources = ["rtl/furnace_axi4_qos_xbar.sv"] if sources is None else sources
    try:
        if simulator == "verilator":
            run.command(["verilator", "--version"], "qos-version")
            run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                         "--top-module", "qos_probe", "--Mdir", str(obj),
                         "-o", "sim", *sources, "tests/qos_probe.sv"], "qos-compile")
            command = [str(obj/"sim")]
        else:
            run.command(["iverilog", "-V"], "qos-version")
            run.command(["vvp", "-V"], "qos-simulator-version")
            run.command(["iverilog", "-g2012", "-Wall", "-s", "qos_probe",
                         "-o", str(run.path/"qos.vvp"), *sources,
                         "tests/qos_probe.sv"], "qos-compile")
            command = ["vvp", str(run.path/"qos.vvp")]
        log = run.command([*command, f"+CASES={path}", f"+COUNT={len(cases)}"],
                          "qos-simulation")
        if f"COMPARED qos_cases={len(cases)}" not in log.read_text():
            raise AssertionError("incomplete QoS comparison summary")
        run.receipt["qos_comparisons"] = dict(
            cases=len(cases), strict_orderings_per_target_direction=24,
            targets=4, directions=["AR", "AW"], equal_priorities=[0, 7, 15],
            lengths=[1, 16], invalid_lengths=[17],
            raw_output=str(log.relative_to(ROOT)))
        run.save()
    finally:
        run.remove_intermediates(obj)
        run.remove_intermediates(run.path/"qos.vvp")
