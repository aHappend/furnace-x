#!/usr/bin/env python3
"""Independent checksummed LZ4/AES-GCM tile limits and quarantine failures."""

import argparse
import datetime
import json
from pathlib import Path
import re
import struct
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_probe import ROOT, digest, now, project_path, run, save
from workload_model import gcm, known_answers, xxh32


def fixture(directory, limit, seed, variant):
    length = limit if variant == "boundary" else min(limit, 65)
    plain = bytes(((i*37) ^ (i>>8) ^ seed) & 255 for i in range(length))
    key = bytes(range(16))
    nonce = struct.pack(">III", seed, limit, length)
    aad = bytes((seed+i*11) & 255 for i in range(52))
    cipher, tag = gcm(key, nonce, aad, plain)
    lz_error, aes_error = 0, 0
    if variant == "tag":
        tag = bytes([tag[0] ^ 1])+tag[1:]
        aes_error = 4
    if variant == "aad":
        aad = aad[:-1]+bytes([aad[-1] ^ 1])
        aes_error = 4
    if variant == "cipher":
        cipher = bytes([cipher[0] ^ 1])+cipher[1:]
        aes_error = 4
    header = bytes([0x7c, 0x40])+struct.pack("<Q", length)
    frame = (struct.pack("<I", 0x184d2204) + header +
             bytes([(xxh32(header)>>8) & 255]) +
             struct.pack("<I", 0x80000000+length) + cipher +
             struct.pack("<I", xxh32(cipher)) + bytes(4) +
             struct.pack("<I", xxh32(cipher)))
    if variant == "checksum":
        frame = frame[:-1]+bytes([frame[-1] ^ 1])
        lz_error = aes_error = 2
    directory.mkdir()
    (directory/"metadata.txt").write_text(
        f"{length} {len(frame)} {lz_error} {aes_error}\n"
        f"{key.hex()}\n{nonce.hex()}\n{tag.hex()}\n{int.from_bytes(aad, 'little'):0104x}\n"
    )
    for name, data in (("frame", frame), ("cipher", cipher), ("plain", plain)):
        (directory/f"{name}.hex").write_text("".join(f"{b:02x}\n" for b in data))
    return length, len(frame), aes_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("evidence/preparation"))
    parser.add_argument("--repair-of", type=Path)
    parser.add_argument("--limit", type=int, choices=(1, 4096, 65536),
                        help="bounded diagnostic row; default enforces every tile endpoint")
    args = parser.parse_args()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = project_path(args.output_root) / f"tile-boundary-{stamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    relative = output.relative_to(ROOT)
    rtl = [f"rtl/{name}.sv" for name in (
        "furnace_lz4_frontend", "furnace_xxh32", "furnace_aes128_gcm",
        "furnace_aes128_block", "furnace_ghash_mul",
    )]
    names = rtl + ["tests/tile_boundary_probe.py", "tests/tile_boundary_contract.sv",
                   "tests/workload_model.py", "tests/boot_probe.py"]
    receipt = {
        "schema": 1, "argv": ["python3", "tests/tile_boundary_probe.py", *sys.argv[1:]],
        "cwd": ".", "source_sha256": {name: digest(ROOT/name) for name in names},
        "commands": [], "runs": [], "fixtures": {}, "start_utc": now(), "end_utc": None,
        "exit_code": None, "timeout_s": 2700,
        "scope": "Public chained LZ4/AES-GCM minimum/default/maximum tile with exact bytes; leaf, not Linux/full-top acceptance",
    }
    if args.repair_of:
        receipt["repair_of"] = str(args.repair_of)
        receipt["repair_receipt_sha256"] = digest(project_path(args.repair_of))
    save(output, receipt)
    status = 1
    try:
        known_answers()
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version")):
            run([tool, option], output, f"{tool}-version", receipt)
        limits = (args.limit,) if args.limit else (1, 4096, 65536)
        for limit in limits:
            directory = output / f"limit{limit}-{uuid.uuid4().hex[:8]}"
            directory.mkdir()
            run(["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
                 "--top-module", "tile_boundary_contract", "--Mdir",
                 directory.relative_to(ROOT)/"obj", f"-GLIMIT={limit}", *rtl,
                 "tests/tile_boundary_contract.sv"], output, f"limit{limit}-compile", receipt)
            if limit == 1:
                run(["iverilog", "-g2012", "-Wall", "-s", "tile_boundary_contract",
                     "-Ptile_boundary_contract.LIMIT=1",
                     "-o", directory.relative_to(ROOT)/"tile.vvp", *rtl,
                     "tests/tile_boundary_contract.sv"], output, "icarus-compile", receipt)
            for seed in (17, 89, 211):
                variants = ("boundary", "tag", "aad", "cipher", "checksum") if seed==17 else ("boundary",)
                for variant in variants:
                    data = directory / f"fixture-{seed}-{variant}"
                    length, frame_bytes, error = fixture(data, limit, seed, variant)
                    receipt["fixtures"].update({str(p.relative_to(ROOT)): digest(p)
                                                for p in data.iterdir()})
                    for simulator in (("icarus", "verilator") if limit==1 and seed==17 else ("verilator",)):
                        argv = (["vvp", directory.relative_to(ROOT)/"tile.vvp"] if simulator=="icarus"
                                else [directory.relative_to(ROOT)/"obj/Vtile_boundary_contract"])
                        stem = f"limit{limit}-{seed}-{variant}-{simulator}"
                        run([*argv, f"+seed={seed}", f"+fixture={data.relative_to(ROOT)}"],
                            output, stem, receipt)
                        matches = re.findall(r"^TILE_BOUNDARY (.+)$",
                                             (output/f"{stem}.stdout.txt").read_text(), re.MULTILINE)
                        if len(matches) != 1:
                            raise ValueError(f"{stem}: missing exact comparison summary")
                        counts = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", matches[0])}
                        if counts["limit"] != limit or counts["length"] != length or (
                                counts["frame_bytes"] != frame_bytes or counts["error"] != error or
                                counts["plain"] != (0 if error else length) or
                                counts["comparisons"] <= 0 or counts["stalls"] <= 0 or
                                counts["fence_stalls"] < 64):
                            raise ValueError(f"{stem}: compared length/quarantine/coverage failure")
                        receipt["runs"].append({"scope": "leaf chained engines", "variant": variant,
                                                "simulator": simulator, **counts})
                        save(output, receipt)
        for name, expected in receipt["source_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"source changed during tile comparison: {name}")
        status = 0
    except (OSError, ValueError, RuntimeError) as error:
        receipt["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        for directory in output.glob("limit*-*/obj"):
            for path in directory.iterdir():
                if path.suffix in (".o", ".a", ".gch"):
                    path.unlink()
        receipt["exit_code"] = status
        receipt["end_utc"] = now()
        save(output, receipt)
    print(f"Tile boundary receipt: {relative}/receipt.json", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
