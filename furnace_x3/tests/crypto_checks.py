"""Standard independent AES/GCM comparisons, bad tags and frame quarantine."""

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crypto_reference import gcm_encrypt, known_answers
from record import Experiment, ROOT


def traces(seed, maximum=64):
    rng = random.Random(seed)
    rows = []
    for length in sorted({0, 1, maximum, *(v for v in (15, 16, 17, 63) if v <= maximum)}):
        key, nonce, aad, plaintext = (rng.randbytes(n) for n in (16, 12, 52, length))
        cipher, tag = gcm_encrypt(key, nonce, aad, plaintext)
        rows.append((key, nonce, aad, cipher, tag, plaintext, 0, 0))
        if length:
            rows.append((key, nonce, aad, cipher, bytes([tag[0] ^ 1]) + tag[1:],
                         plaintext, 4, 0))
            rows.append((key, nonce, aad, cipher, tag, plaintext, 2, 2))
    lines = []
    for key, nonce, aad, cipher, tag, plain, error, frame_error in rows:
        lines.append(f"{key.hex()} {nonce.hex()} {tag.hex()} "
                     f"{int.from_bytes(aad, 'little'):0104x} {len(cipher)} "
                     f"{error} {frame_error} 5000\n")
        lines += [f"{a:02x} {b:02x}\n" for a, b in zip(cipher, plain)]
    return "".join(lines), len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--maximum", type=int, default=64)
    args = parser.parse_args()
    experiment = Experiment("crypto-quarantine")
    obj = experiment.path / "compile-obj"
    try:
        known_answers()
        experiment.command(["verilator", "--version"], "verilator-version", version=True)
        trace = experiment.path / "crypto.trace"
        text, rows = traces(args.seed, args.maximum)
        trace.write_text(text)
        experiment.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "crypto_tb", f"-GMAX_TILE_BYTES={args.maximum}",
                            "--Mdir", str(obj.relative_to(ROOT)), "-o", "crypto-sim",
                            "rtl/furnace_aes128_gcm.sv", "rtl/furnace_aes128_block.sv",
                            "rtl/furnace_ghash_mul.sv", "tests/crypto_tb.sv"], "compile")
        output = experiment.command([str((obj / "crypto-sim").relative_to(ROOT)),
                                     f"+trace={trace.relative_to(ROOT)}", f"+rows={rows}",
                                     f"+seed={args.seed}"], "simulate")
        if "CRYPTO_PASS " not in output:
            raise AssertionError("crypto comparisons missing")
        print(output.strip())
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
