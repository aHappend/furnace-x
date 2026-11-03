#!/usr/bin/env python3
"""Compiled full-top CPU-driven experiments, with public DDR/UART comparison."""

import argparse
import datetime
import json
from pathlib import Path
import struct
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from workload_model import FIXTURE_BASE, fixtures


INTEGRATED_MUTATIONS = {
    "dma_data_order": {
        "module": "furnace_dma512.sv",
        "before": "assign m_axi_wdata = m_axi_wvalid ? buffer_q : 512'b0;",
        "after": "assign m_axi_wdata = m_axi_wvalid ? (buffer_q ^ 512'b1) : 512'b0;",
        "message": r"DDR semantic write id=(?:[0-9]|1[0-5]) beat=0 at=0x86300000 observed=0 expected=1",
        "assertion": "DMA WDATA bytes match independently generated source pattern",
    },
    "cache_invalidation": {
        "module": "hammer_v3_cache.sv",
        "before": "if (cmd_q == 3) valid[scan] <= 1'b0;",
        "after": "if (cmd_q == 3 && READ_ONLY) valid[scan] <= 1'b0;",
        "code_low": 0x7000, "code_high": 0x700a,
        "assertion": "CPU feature re-read observes engine DMA update rather than retained clean cache line",
    },
    "reservation_invalidation": {
        "module": "hammer_v3_atomic.sv",
        "before": "if (invalidate || store_commit) reservation <= 1'b0;",
        "after": "if (store_commit) reservation <= 1'b0;",
        "code_low": 0x9000, "code_high": 0x9000,
        "assertion": "SC fails after real DMA activity without an intervening CPU store",
    },
    "plic_disconnect": {
        "module": "furnace_x4_top.sv",
        "before": ".plic_sources({30'b0,fabric_irq})",
        "after": ".plic_sources(31'b0)",
        "code_low": 0x0c200004, "code_high": 0x0c200004,
        "assertion": "PLIC claim returns actual fabric completion source 2",
    },
    "authenticated_weight_commit": {
        "module": "furnace_x2_top.sv",
        "before": "mm_weights<=candidate_weights; mm_weights_valid<=1;",
        "after": "mm_weights<=candidate_weights; mm_weights_valid<=0;",
        "code_low": 0x1008, "code_high": 0x1008,
        "assertion": "successful authenticated retirement establishes weights-valid",
    },
    "authentication_bypass": {
        "module": "furnace_aes128_gcm.sv",
        "before": "if (|tag_difference) begin status<=4; state<=ABORT; end",
        "after": "if (1'b0) begin status<=4; state<=ABORT; end",
        "code_low": 0x14, "code_high": 0x14,
        "public_message": r"DDR semantic write id=(?:[0-9]|1[0-5]) beat=0 at=0x86006000 observed=0 expected=4",
        "assertion": "corrupt-tag descriptor retires with authentication error 4",
    },
    "tensor_weight_sign": {
        "module": "furnace_tensor8.sv",
        "before": "$signed(weights[4*i+:4])*",
        "after": "$signed({1'b0,weights[4*i+:4]})*",
        "code_low": 0x5000, "code_high": 0x500F,
        "public_message": r"DDR semantic write id=(?:[0-9]|1[0-5]) beat=0 at=0x8600500[0-9a-f] observed=[0-9a-f]+ expected=[0-9a-f]+",
        "assertion": "signed W4 tensor result matches independent integer dot product",
    },
    "vision_numerical": {
        "module": "furnace_bilinear_pipe.sv",
        "before": "assign m_data=(rst_n && enabled) ? answer : 8'b0;",
        "after": "assign m_data=(rst_n && enabled) ? (answer ^ 8'h01) : 8'b0;",
        "code_low": 0x7000, "code_high": 0x7002,
        "public_message": r"DDR semantic write id=(?:[0-9]|1[0-5]) beat=0 at=0x8600700[0-9a-f] observed=[0-9a-f]+ expected=[0-9a-f]+",
        "assertion": "vision feature DMA matches independent constant-image spatial means",
    },
    "fft_numerical": {
        "module": "furnace_fft_radix2.sv",
        "before": "assign m_re=active ? answer_re : 32'sd0;",
        "after": "assign m_re=active ? (answer_re ^ 32'h00010000) : 32'sd0;",
        "code_low": 0x7001, "code_high": 0x7002,
        "public_message": r"DDR semantic write id=(?:[0-9]|1[0-5]) beat=0 at=0x8600710[0-9a-f] observed=[0-9a-f]+ expected=[0-9a-f]+",
        "assertion": "audio feature DMA matches independent all-zero FFT magnitudes",
    },
    "mailbox_semaphore_association": {
        "module": "furnace_mailboxes.sv",
        "before": "else result = pop_data[index_q];",
        "after": "else result = pop_data[index_q ^ 2'b01];",
        "code_low": 0x2600, "code_high": 0x2630,
        "assertion": "mailbox read returns the submitted data from the addressed queue",
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--seeds", default="17,89,211")
    parser.add_argument("--cycles", type=int, default=80000000)
    parser.add_argument("--stop-phase", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--mutation", choices=tuple(INTEGRATED_MUTATIONS))
    args = parser.parse_args()
    seeds = tuple(int(s) for s in args.seeds.split(","))
    if not seeds or len(set(seeds)) != len(seeds) or args.cycles <= 8:
        parser.error("nonempty distinct seeds and cycles > 8 required")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"integrated-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    sources = sorted(
        p for directory in ("rtl", "tests", "design", "sw/taskgraph")
        for p in (ROOT / directory).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    receipt = {
        "schema": 1, "kind": "verifier-integrated-public-pin-preparation",
        "argv": ["python3", "tests/integrated_probe.py", *sys.argv[1:]], "cwd": ".",
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 2700, "timed_out": False, "commands": [],
        "tool_versions": {}, "seeds": seeds, "cycles_limit": args.cycles,
        "stop_phase": args.stop_phase,
        "mutation": args.mutation,
        "scope": "Actual M-mode CPU, accepted fabric and public DDR/UART. Not Linux/privilege coverage.",
        "measurements": {}, "runs": [],
    }
    save(output, receipt)
    print(f"Integrated receipt: {relative}/receipt.json", flush=True)
    status = 1
    try:
        if args.repair_of:
            receipt["repair_of"] = str(args.repair_of)
            receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
        for tool in ("python3", "verilator", "make", "g++",
                     "riscv64-unknown-elf-gcc", "riscv64-unknown-elf-objcopy"):
            result = subprocess.run(
                [tool, "--version"], cwd=ROOT, capture_output=True, text=True, check=False,
            )
            receipt["tool_versions"][tool] = {
                "argv": [tool, "--version"], "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            }
            if result.returncode:
                raise RuntimeError(f"{tool} version query failed")
        run(["riscv64-unknown-elf-gcc", "-march=rv64im", "-mabi=lp64",
             "-nostdlib", "-nostartfiles", "-Wl,--build-id=none",
             "-T", "sw/taskgraph/task.ld", "sw/taskgraph/task.S",
             "-o", relative / "task.elf"], output, "task-compile", receipt)
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", relative / "task.elf",
             relative / "task.bin"], output, "task-binary", receipt)
        task = (output / "task.bin").read_bytes()
        if not task or len(task) % 4 or len(task) > 16384:
            raise ValueError("invalid actual task firmware size")
        words = struct.unpack("<" + "I"*(len(task)//4), task)
        (output / "task_words.h").write_text(
            "static const u32 task_words[] = {" +
            ",".join(f"0x{v:08x}U" for v in words) + "};\n"
        )
        run(["riscv64-unknown-elf-gcc", "-march=rv64ima_zicsr_zifencei", "-mabi=lp64",
             "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0",
             "-O2", "-ffreestanding", "-fno-builtin", "-nostdlib", "-nostartfiles",
             "-Wall", "-Wextra", "-Werror", "-Wl,--build-id=none",
             "-T", "tests/integrated.ld", "-I" + str(relative),
             "tests/integrated_start.S", "tests/integrated_firmware.c",
             "-o", relative / "firmware.elf"], output, "firmware-compile", receipt)
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", relative / "firmware.elf",
             relative / "firmware.bin"], output, "firmware-binary", receipt)
        run(["riscv64-unknown-elf-objdump", "-d", relative / "firmware.elf"],
            output, "firmware-disassembly", receipt)
        rtl_sources = sorted((ROOT / "rtl").glob("*.sv"))
        if args.mutation:
            mutation = INTEGRATED_MUTATIONS[args.mutation]
            disposable = output / "mutated-rtl"
            disposable.mkdir()
            receipt["mutated_source_sha256"] = {}
            for path in rtl_sources:
                text = path.read_text()
                if path.name == mutation["module"]:
                    if text.count(mutation["before"]) != 1:
                        raise ValueError(f"{args.mutation}: mutation site is not unique")
                    text = text.replace(mutation["before"], mutation["after"], 1)
                target = disposable / path.name
                target.write_text(text)
                receipt["mutated_source_sha256"][str(target.relative_to(ROOT))] = digest(target)
            rtl_sources = sorted(disposable.glob("*.sv"))
            receipt["intended_assertion"] = mutation["assertion"]
            save(output, receipt)
        cpp_from_obj = Path(*([".."]*len((relative / "obj").parts))) / "tests/integrated_endpoint.cpp"
        run(["verilator", "--cc", "--exe", "--build", "-j", "2",
             "--top-module", "furnace_x4_top", "--Mdir", relative / "obj",
             "--assert", "-Wno-fatal", "--output-split", "20000",
             "-CFLAGS", "-O2 -std=c++17",
             *[str(p.relative_to(ROOT)) for p in rtl_sources],
             cpp_from_obj], output, "rtl-compile", receipt)
        for seed in seeds:
            data, expected = fixtures(seed)
            fixture = output / f"fixtures-{seed}.bin"
            fixture.write_bytes(data)
            (output / f"expected-{seed}.json").write_text(json.dumps(expected, indent=2) + "\n")
            firmware = output / "firmware.bin"
            source = output / f"dma-source-{seed}.bin"
            with source.open("wb") as stream:
                for at in range(0, 1048576, 8):
                    stream.write(struct.pack("<Q", 0x0706050403020100 ^ (at << 32) ^ at))
            destination = output / f"dma-destination-{seed}.bin"
            destination.write_bytes(b"\xa5"*(1048576+128))
            index = output / f"images-{seed}.txt"
            index.write_text(
                f"2147483648 {firmware.stat().st_size} {firmware.relative_to(ROOT)}\n"
                f"{FIXTURE_BASE} {len(data)} {fixture.relative_to(ROOT)}\n"
                f"2249195520 {source.stat().st_size} {source.relative_to(ROOT)}\n"
                f"2251292608 {destination.stat().st_size} {destination.relative_to(ROOT)}\n"
            )
            receipt.setdefault("generated_sha256", {}).update({
                str(p.relative_to(ROOT)): digest(p)
                for p in (fixture, source, destination, index, firmware,
                          output / f"expected-{seed}.json", output / "task.bin")
            })
            save(output, receipt)
            run([relative / "obj/Vfurnace_x4_top", index.relative_to(ROOT),
                 relative / f"uart-{seed}.txt", str(args.cycles), str(seed),
                 relative / f"summary-{seed}.txt", relative / f"coverage-{seed}.json",
                 str(args.stop_phase)], output, f"simulation-{seed}", receipt)
            measured = json.loads((output / f"coverage-{seed}.json").read_text())
            if args.stop_phase == 8 and not measured["complete"]:
                raise ValueError(f"seed {seed}: incomplete run")
            receipt["runs"].append({"seed": seed, "observed": measured})
            receipt["measurements"].update({
                f"seed{seed}.{key}": value for key, value in measured["coverage"].items()
            })
            save(output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(project_path(Path(name))) != expected:
                raise ValueError(f"source changed during execution: {name}")
        status = 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        receipt["diagnostic_error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
        obj = output / "obj"
        if obj.is_dir():
            for path in obj.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
    print(f"Integrated exit={status}; receipt={relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
