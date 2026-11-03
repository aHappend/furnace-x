"""Oracle development checks, NOT an RTL verification or acceptance suite.

Run a source-bound advisory probe with:
python3 -B tests/test_mm_oracle.py --preparation
"""

import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mm_oracle as model


class NumericalOracleTests(unittest.TestCase):
    def test_bilinear_rounding(self):
        self.assertEqual(model.bilinear([0, 1, 0, 1], 128, 0), 1)
        self.assertEqual(model.bilinear([0, 1, 0, 1], 127, 0), 0)
        for value in (0, 1, 127, 255):
            self.assertEqual(model.bilinear([value] * 4, 255, 255), value)

    def test_spatial_orientation(self):
        self.assertEqual(model.spatial([0, 1, 2] * 3), (1, 8, 0, 0))
        self.assertEqual(model.spatial([0] * 3 + [1] * 3 + [2] * 3),
                         (1, 0, 8, 0))
        self.assertEqual(model.spatial([0] * 4 + [255] + [0] * 4),
                         (255, 0, 0, -1020))

    def test_vision_geometry(self):
        self.assertEqual(model.vision([255], 1, 1, 1, 1),
                         ([255], [(255, 0, 0, 0)], (255, 0, 0, 0)))
        resized, spatial, features = model.vision([0, 255], 2, 1, 3, 1)
        self.assertEqual(resized, [0, 128, 255])
        self.assertEqual(spatial,
                         [(0, 512, 0, 128), (128, 1020, 0, -1),
                          (255, 508, 0, -127)])
        self.assertEqual(features, (127, 680, 0, 85))
        for iw, ih, ow, oh in ((5, 3, 7, 2), (13, 9, 3, 5),
                               (3, 2, 16, 9), (64, 64, 64, 64),
                               (64, 1, 1, 64)):
            resized, neighborhoods, means = model.vision([37] * (iw * ih),
                                                         iw, ih, ow, oh)
            self.assertEqual(resized, [37] * (ow * oh))
            self.assertEqual(neighborhoods, [(37, 0, 0, 0)] * (ow * oh))
            self.assertEqual(means, (37, 0, 0, 0))

    def test_fir_floor_and_history(self):
        self.assertEqual(model.fir([8, 0, 0, 0, 0]), [1, 3, 3, 1, 0])
        self.assertEqual(model.fir([-1, 0, 0, 0, 0]), [-1, -1, -1, -1, 0])
        self.assertEqual(model.fir([-32768] * 4), [-4096, -16384, -28672, -32768])
        self.assertEqual(model.fir([32767] * 4), [4095, 16383, 28671, 32767])

    def test_twiddle_axes(self):
        self.assertEqual(model.twiddle(8, 0), (32768, 0))
        self.assertEqual(model.twiddle(8, 2), (0, -32768))
        self.assertEqual(model.twiddle(8, 4), (-32768, 0))
        self.assertEqual(model.twiddle(8, 6), (0, 32768))
        self.assertEqual(model.twiddle(8, 1), (23170, -23170))

    def test_fft_exact_cases(self):
        for n in model.FFT_SIZES:
            for amplitude in (-32768, -1, 1, 32767):
                self.assertEqual(model.fft([amplitude] + [0] * (n - 1)),
                                 [(amplitude, 0)] * n)
                dc = model.fft([amplitude] * n)
                self.assertEqual(dc, [(n * amplitude, 0)] + [(0, 0)] * (n - 1))
            nyquist = model.fft([7, -7] * (n // 2))
            expected = [(0, 0)] * n
            expected[n // 2] = (7 * n, 0)
            self.assertEqual(nyquist, expected)

    def test_dft_supplement(self):
        for n in model.FFT_SIZES:
            for seed in (17, 89, 203):
                rng = random.Random(seed)
                samples = [rng.randrange(-32768, 32768) for _ in range(n)]
                model.check_dft(samples, model.fft(samples))
        with self.assertRaises(AssertionError):
            model.check_dft([1] + [0] * 7, [(1000, 0)] * 8)

    def test_audio_silence(self):
        for n in model.FFT_SIZES:
            self.assertEqual(model.audio([0] * n),
                             ([0] * n, [(0, 0)] * n, (0, 0, 0, 0)))

    def test_tensor_and_record(self):
        self.assertEqual(model.tensor_w4([-8, 7] * 4, [-32768, 32767] * 4),
                         1966052)
        self.assertEqual(model.record(-1, 65535, 8),
                         b"\xff" * 8 + b"\x00" * 4 + b"\xff\xff\x00\x08")
        self.assertEqual(model.record(0, 0), bytes(16))

    def test_input_rejection(self):
        for bad in ([], [0] * 12, [32768] * 8):
            with self.assertRaises(ValueError):
                model.fft(bad)
        with self.assertRaises(ValueError):
            model.vision([0], 0, 1, 1, 1)


def preparation(*, test_file="test_mm_oracle.py", source_files=None, stem="oracle"):
    root = Path(__file__).resolve().parent.parent
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    relative = Path("evidence/preparation") / f"{stem}-{stamp}-{uuid4().hex[:12]}"
    output = root / relative
    output.mkdir(parents=True, exist_ok=False)
    sources = {}
    if source_files is None:
        source_files = ("tests/mm_oracle.py", "tests/test_mm_oracle.py")
    for name in source_files:
        sources[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    argv = ["python3", "-B", f"tests/{test_file}", "-v"]
    receipt = {
        "kind": "advisory-oracle-self-test",
        "acceptance_evidence": False,
        "argv": argv,
        "cwd": ".",
        "tool_version": platform.python_version(),
        "source_sha256": sources,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "timeout_seconds": 3600,
        "stdout": (relative / "stdout.txt").as_posix(),
        "stderr": (relative / "stderr.txt").as_posix(),
        "timed_out": False,
    }
    with (output / "stdout.txt").open("xb") as stdout, (
        output / "stderr.txt"
    ).open("xb") as stderr:
        try:
            result = subprocess.run(argv, cwd=root, stdout=stdout, stderr=stderr,
                                    timeout=3600, check=False,
                                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            receipt["exit_code"] = result.returncode
        except subprocess.TimeoutExpired:
            receipt["timed_out"] = True
            receipt["exit_code"] = None
    receipt["ended_at"] = datetime.now(timezone.utc).isoformat()
    with (output / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print((relative / "receipt.json").as_posix())
    return receipt["exit_code"] if not receipt["timed_out"] else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--preparation"]:
        sys.exit(preparation())
    unittest.main()
