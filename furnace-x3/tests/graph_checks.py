"""Real-firmware graph rejection, error propagation, and 1/64-node domains."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT
from rv64_reference import CPU
from soc_reference import SoC
from x3_checks import engine_memory


def record(index, opcode=4, dependencies=0, arguments=(), wait=-1, post=-1, status_base=0x2000):
    return bytearray(struct.pack(
        "<IIQ6I6I", opcode, 777 + 13*index, dependencies,
        *(tuple(arguments)+(0,)*(6-len(arguments))), wait & 0xffffffff, post & 0xffffffff,
        0x80000000+status_base+16*index, 0, 0, 0))


def cases(seed):
    result = []

    def add(name, records, outcomes, memory=None, edits=(), count=None,
            graph_address=0x80000000, manifest_error=False):
        memory = (memory.copy() if memory is not None else
                  bytearray(((i*19+seed) ^ (i >> 8)) & 255 for i in range(32768)))
        for index, value in enumerate(records):
            memory[index*64:(index+1)*64] = value
        expected = memory.copy()
        for index, (state, error) in enumerate(outcomes):
            identifier = struct.unpack_from("<I", records[index], 4)[0]
            address = struct.unpack_from("<I", records[index], 48)[0] - 0x80000000
            expected[address:address+16] = struct.pack("<4I", state, error, identifier, 0)
        for address, data in edits:
            expected[address:address+len(data)] = data
        nodes = len(records) if count is None else count
        failed = manifest_error or any(state >= 3 for state, _ in outcomes)
        result.append({"name": name, "memory": memory, "expected": expected,
                       "nodes": nodes, "graph_address": graph_address,
                       "state": 3 if failed else 2,
                       "summary": 256 if manifest_error else int(failed),
                       "notification": 0x5843ff00 if manifest_error else
                           0x58430000 | nodes | (0x8000 if failed else 0),
                       "require_cpu_ddr": int(not manifest_error)})

    add("one-node", [record(0)], [(2, 0)])
    records = [record(i, dependencies=(1 << 63 if i == 0 else
                        0 if i == 63 else 1 << (i-1)),
                      wait=15 if i == 0 else -1, post=15 if i == 63 else -1)
               for i in range(64)]
    add("64-nodes-bit63-and-semaphore15", records, [(2, 0)]*64)
    mutations = [("opcode-zero", 0, 0), ("opcode-five", 0, 5),
                 ("reserved52", 52, 1), ("reserved56", 56, 1), ("reserved60", 60, 1),
                 ("barrier-argument", 16, 1), ("unused-argument", 28, 1),
                 ("wait0", 40, 0), ("wait1", 40, 1), ("wait16", 40, 16),
                 ("post0", 44, 0), ("post1", 44, 1), ("post16", 44, 16)]
    for name, offset, value in mutations:
        rows = [record(i) for i in range(6)]
        struct.pack_into("<I", rows[0], offset, value)
        add(name, rows, [(3, 256)]*6)
    for name, dependencies, code in (("dependency-out-of-range", 1 << 6, 256),
                                      ("dependency-high-out-of-range", 1 << 63, 256),
                                      ("self-cycle", 1, 257)):
        rows = [record(i) for i in range(6)]
        struct.pack_into("<Q", rows[0], 8, dependencies)
        add(name, rows, [(3, code)]*6)
    rows = [record(i) for i in range(6)]
    struct.pack_into("<Q", rows[0], 8, 2)
    struct.pack_into("<Q", rows[1], 8, 1)
    add("two-node-cycle", rows, [(3, 257)]*6)
    add("unsatisfied-waits", [record(i, wait=2) for i in range(6)], [(3, 259)]*6)
    for count in (0, 65):
        add(f"manifest-count-{count}", [record(i) for i in range(6)], [],
            count=count, manifest_error=True)
    add("manifest-unaligned-graph", [record(i) for i in range(6)], [],
        graph_address=0x80000001, manifest_error=True)
    rows = [record(i) for i in range(6)]
    struct.pack_into("<I", rows[1], 48, 0x80002001)
    add("manifest-unaligned-status-no-dereference", rows, [], manifest_error=True)
    rows = [record(0, 1, arguments=(0x80001001, 0x80003000, 1)),
            record(1, dependencies=1), record(2, post=2),
            record(3, dependencies=2), record(4, dependencies=4, wait=2),
            record(5, dependencies=8|16)]
    add("invalid-dma-dependent-failure-independent-progress", rows,
        [(3, 1), (4, 258), (2, 0), (4, 258), (2, 0), (4, 258)])
    for opcode, arguments, name in ((2, (0x80000401,), "descriptor-source-alignment"),
                                     (3, (0x80003000, 0x80003101, 7), "frame-audio-alignment")):
        rows = [record(0, opcode, arguments=arguments)] + [
            record(i, dependencies=1) for i in range(1, 6)]
        add(name, rows, [(3, 261)]+[(4, 258)]*5)
    for name, descriptor_offset, byte_offset, value, code in (
            ("wrong-authentication-tag", 0x400, 52, None, 4),
            ("reserved-descriptor-word", 0x400, 72, 1, 1),
            ("invalid-tensor-mode", 0x400, 4, 3, 1),
            ("invalid-lz4-magic", 0x1000, 0, 0, 2)):
        memory, _ = engine_memory(seed)
        memory[0x1000] = memory[0x1800]
        position = descriptor_offset+byte_offset
        if value is None:
            memory[position] ^= 1
        elif name == "invalid-tensor-mode":
            memory[position] |= value
        else:
            memory[position] = value
        rows = [record(0, 2, arguments=(0x80000400,), status_base=0x800)] + [
            record(i, dependencies=1, status_base=0x800) for i in range(1, 6)]
        add(name, rows, [(3, code)]+[(4, 258)]*5, memory,
            edits=((0x4000, memory[0x400:0x480]),
                   (0x2300, struct.pack("<4I", code, 203, 0, 0))))
    return result


def reference(image, case):
    device = SoC(image, case["memory"], (1, 1, 1, 1, 8), 1, 1, 1, 1)
    struct.pack_into("<10I", device.dmem, 0, case["graph_address"], case["nodes"], 0x80004000,
                     0x80005000, 0x80006000, 0x80007000, 0, 0, 0, 0)
    cpu = CPU(device)
    while device.run and device.time < 2000000:
        cpu.step()
    if device.run or device.mailboxes[0] != [case["notification"]]:
        raise AssertionError(f"reference notification/halt {case['name']}: {device.mailboxes[0]}")
    if tuple(struct.unpack_from("<2I", device.dmem, 64)) != (case["state"], case["summary"]):
        raise AssertionError(f"reference final state/summary {case['name']}")
    if device.ddr != case["expected"]:
        first = next(i for i, (a, b) in enumerate(zip(device.ddr, case["expected"])) if a != b)
        raise AssertionError(f"reference {case['name']} memory={first:#x} "
                             f"actual={device.ddr[first]:02x} expected={case['expected'][first]:02x}")
    return {"instructions": cpu.instructions, "traps": cpu.traps,
            "compared_bytes": len(device.ddr)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    experiment = Experiment("firmware-graph-domains-errors", args.repair_of)
    obj = experiment.path / "compile-obj"
    try:
        image_path = experiment.path / "scheduler.hex"
        experiment.command(["python3", "firmware/build.py", "--in-width", "1",
                            "--in-height", "1", "--fft-n", "8",
                            "--output", str(image_path.relative_to(ROOT))], "firmware-build")
        words = image_path.read_text().split()
        image = b"".join(struct.pack("<I", int(word, 16)) for word in words)
        fixtures = cases(args.seed)
        coverage = {}
        for case in fixtures:
            coverage[case["name"]] = reference(image, case)
            for name in ("memory", "expected"):
                (experiment.path / f"{case['name']}-{name}.hex").write_text(
                    "".join(f"{value:02x}\n" for value in case[name]))
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        sources = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "rtl").glob("*.sv"))]
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "x3_smoke_tb", "-GCYCLE_LIMIT=20000000",
                            "--Mdir", str(obj.relative_to(ROOT)), "-o", "graph-sim",
                            *sources, "tests/x3_smoke_tb.sv"], "compile")
        for case in fixtures:
            output = experiment.command([
                str((obj / "graph-sim").relative_to(ROOT)), f"+image={image_path.relative_to(ROOT)}",
                f"+words={len(words)}", f"+seed={args.seed}", "+dma_bursts=0",
                f"+memory={(experiment.path / (case['name']+'-memory.hex')).relative_to(ROOT)}",
                f"+expected={(experiment.path / (case['name']+'-expected.hex')).relative_to(ROOT)}",
                f"+nodes={case['nodes']}", f"+graph_address={case['graph_address']:08x}",
                f"+notification={case['notification']:08x}", f"+state={case['state']}",
                f"+summary={case['summary']}", f"+require_cpu_ddr={case['require_cpu_ddr']}"],
                case["name"])
            if "X3_FIRMWARE_SMOKE_PASS" not in output:
                raise AssertionError(f"missing real firmware comparisons: {case['name']}")
            print(f"FIRMWARE_GRAPH_CASE_PASS name={case['name']}", flush=True)
        (experiment.path / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        print(f"FIRMWARE_GRAPH_DOMAINS_PASS cases={len(fixtures)}")
    except Exception as error:
        experiment.finish(error)
        raise
    finally:
        for pattern in ("*.o", "*.a", "*.gch"):
            for path in obj.glob(pattern):
                path.unlink()
    experiment.finish()


if __name__ == "__main__":
    main()
