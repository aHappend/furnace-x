#!/usr/bin/env python3
"""Resolve retained public DDR fills and public retirement observations against ELFs."""

import argparse
import bisect
import datetime
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"boot-address-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": 1, "argv": ["python3", "tests/boot_address_probe.py", *sys.argv[1:]],
        "cwd": ".", "start_utc": now(), "end_utc": None, "exit_code": None,
        "timeout_s": 600, "commands": [], "source_sha256": {
            name: digest(ROOT / name) for name in (
                "tests/boot_address_probe.py", "tests/boot_probe.py",
            )
        }, "scope": "ELF resolution of retained public fill lines, not retired PCs or completed boot",
    }
    save(output, receipt)
    status = 1
    try:
        old_path = project_path(args.boot_receipt)
        old = json.loads(old_path.read_text())
        build_path = project_path(Path(old["software_build_receipt"]))
        if digest(build_path) != old["software_build_receipt_sha256"]:
            raise ValueError("retained software receipt identity changed")
        summary = old_path.parent / "simulation-summary.txt"
        components_path = build_path.parent / "system/boot/boot-components.json"
        components = json.loads(components_path.read_text())
        receipt["retained_inputs"] = {
            str(p.relative_to(ROOT)): digest(p) for p in (
                old_path, build_path, summary, components_path,
            )
        }
        run(["riscv64-linux-gnu-nm", "--version"], output, "nm-version", receipt)
        run(["riscv64-linux-gnu-objdump", "--version"], output, "objdump-version", receipt)
        tables = []
        for kind in ("firmware", "kernel"):
            identity = components[f"{kind}_elf"]
            elf = project_path(Path(identity["path"]))
            if digest(elf) != identity["sha256"]:
                raise ValueError(f"{kind}: ELF identity mismatch")
            receipt["retained_inputs"][str(elf.relative_to(ROOT))] = digest(elf)
            run(["riscv64-linux-gnu-nm", "-n", "--defined-only", elf.relative_to(ROOT)],
                output, f"{kind}-symbols", receipt)
            symbols = []
            for line in (output / f"{kind}-symbols.stdout.txt").read_text().splitlines():
                match = re.fullmatch(r"([0-9a-fA-F]+) (\w) (.+)", line)
                if match:
                    symbols.append((int(match[1], 16), match[2], match[3]))
            start_name = "_start" if kind == "kernel" else "_fw_start"
            start = next(address for address, _, name in symbols if name == start_name)
            load = components[kind]["address"]
            tables.append((kind, elf, start - load, symbols))
        observations = []
        window = None
        for line in summary.read_text().splitlines():
            if line.startswith("WINDOW "):
                window = line
            retired = line.startswith("retired_hot_lines:")
            if not retired and not line.startswith("instruction_fill_lines_by_ARPROT "):
                continue
            for physical_hex, count in re.findall(r"(0x[0-9a-f]+),(\d+)", line):
                physical = int(physical_hex, 16)
                kind = "kernel" if physical >= components["kernel"]["address"] else "firmware"
                _, elf, relocation, symbols = next(row for row in tables if row[0] == kind)
                virtual = physical if retired and physical >> 63 else physical + relocation
                text_symbols = [(address, name) for address, typ, name in symbols
                                if typ in "tTwW"]
                at = bisect.bisect_right([address for address, _ in text_symbols], virtual) - 1
                if at < 0:
                    raise ValueError(f"unresolved instruction fill line {physical_hex}")
                address, name = text_symbols[at]
                observations.append({
                    "window": window, "physical_line": physical_hex,
                    "virtual_line": hex(virtual), "fill_count": int(count),
                    "observation": "retired instructions" if retired else "DDR instruction fills",
                    "elf": str(elf.relative_to(ROOT)), "symbol_at_line_start": name,
                    "symbol_offset": virtual - address,
                })
        if not observations:
            raise ValueError("no retained public instruction-fill observations")
        (output / "resolved-lines.json").write_text(json.dumps(observations, indent=2) + "\n")
        last_window = observations[-1]["window"]
        for index, row in enumerate(r for r in observations if r["window"] == last_window):
            start = int(row["virtual_line"], 16)
            run(["riscv64-linux-gnu-objdump", "-d", "--no-show-raw-insn",
                 f"--start-address={start}", f"--stop-address={start + 64}", row["elf"]],
                output, f"last-window-line-{index}", receipt)
        receipt["resolved_lines"] = len(observations)
        receipt["last_window"] = last_window
        status = 0
    except (OSError, ValueError, KeyError, StopIteration, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        receipt["end_utc"] = now()
        receipt["exit_code"] = status
        save(output, receipt)
    print(f"Boot-address receipt: {output.relative_to(ROOT)}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
