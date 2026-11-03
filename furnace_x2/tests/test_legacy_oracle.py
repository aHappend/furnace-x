"""Development checks of the independent oracle; never DUT acceptance."""

from fractions import Fraction
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import legacy_oracle as model
from test_mm_oracle import preparation


def pack(lanes, width):
    return sum((value & ((1 << width) - 1)) << (i * width)
               for i, value in enumerate(lanes))


class LegacyOracleTests(unittest.TestCase):
    def test_exact_encodings(self):
        for value, encoding in (
            (0, 0), (1, 0x3F800000), (-1, 0xBF800000),
            (7, 0x40E00000), (-8, 0xC1000000),
            (Fraction(1, 1 << 149), 1),
            (Fraction((1 << 23) - 1, 1 << 149), 0x007FFFFF),
            (Fraction(1, 1 << 126), 0x00800000),
            ((1 << 128) - (1 << 104), 0x7F7FFFFF),
        ):
            self.assertEqual(model.round_fp32(value), encoding)
            self.assertEqual(model.finite_value(encoding), value)

    def test_finite_encoding_roundtrip(self):
        rng = random.Random(203)
        patterns = [rng.getrandbits(32) for _ in range(4096)]
        patterns += [bf16 << 16 for bf16 in range(65536)]
        for bits in patterns:
            if (bits >> 23) & 255 == 255:
                continue
            self.assertEqual(model.round_fp32(
                model.finite_value(bits), negative_zero=bool(bits >> 31)), bits)

    def test_ties_even_and_carry(self):
        self.assertEqual(model.round_fp32(1 + Fraction(1, 1 << 24)), 0x3F800000)
        self.assertEqual(model.round_fp32(1 + Fraction(3, 1 << 24)), 0x3F800002)
        self.assertEqual(model.round_fp32(2 - Fraction(1, 1 << 24)), 0x40000000)
        self.assertEqual(model.round_fp32(-1 - Fraction(3, 1 << 24)), 0xBF800002)
        self.assertEqual(model.round_fp32((1 << 128) - (1 << 103)), 0x7F800000)

    def test_gradual_underflow(self):
        self.assertEqual(model.round_fp32(Fraction(1, 1 << 150)), 0)
        self.assertEqual(model.round_fp32(-Fraction(1, 1 << 150)), 0x80000000)
        self.assertEqual(model.round_fp32(Fraction(3, 1 << 150)), 2)
        self.assertEqual(model.round_fp32(
            Fraction((1 << 24) - 1, 1 << 150)), 0x00800000)
        self.assertEqual(model.multiply_fp32(1, 0x3F000000), 0)
        self.assertEqual(model.multiply_fp32(3, 0x3F000000), 2)
        self.assertEqual(model.multiply_fp32(0x80000001, 0x3F000000), 0x80000000)
        self.assertEqual(model.add_fp32(0x007FFFFF, 1), 0x00800000)
        self.assertEqual(model.add_fp32(0x00800000, 0x80000001), 0x007FFFFF)

    def test_specials_and_signed_zero(self):
        for nan in (0x7F800001, 0x7FC00001, 0xFFC12345):
            self.assertEqual(model.add_fp32(nan, 0), model.CANONICAL_NAN)
            self.assertEqual(model.multiply_fp32(0x3F800000, nan),
                             model.CANONICAL_NAN)
        self.assertEqual(model.add_fp32(0x7F800000, 0xFF800000),
                         model.CANONICAL_NAN)
        self.assertEqual(model.multiply_fp32(0x7F800000, 0),
                         model.CANONICAL_NAN)
        self.assertEqual(model.add_fp32(0x7F800000, 0x3F800000), 0x7F800000)
        self.assertEqual(model.multiply_fp32(0xFF800000, 0xBF800000), 0x7F800000)
        self.assertEqual(model.add_fp32(0x80000000, 0x80000000), 0x80000000)
        self.assertEqual(model.add_fp32(0, 0x80000000), 0)
        self.assertEqual(model.add_fp32(0x3F800000, 0xBF800000), 0)
        self.assertEqual(model.multiply_fp32(0x80000000, 0x3F800000), 0x80000000)

    def test_add_and_multiply_round_separately(self):
        self.assertEqual(model.multiply_fp32(0x3F800001, 0x3F7FFFFE), 0x3F800000)
        self.assertEqual(model.add_fp32(0x3F800000, 0xBF800000), 0)
        exact = model.finite_value(0x3F800001) * model.finite_value(0x3F7FFFFE) - 1
        self.assertNotEqual(model.round_fp32(exact), 0)

    def test_integer_lanes_and_multivector(self):
        weights = [-8, 7, -1, 0, 1, 2, -3, 4]
        activations = [-32768, 32767, -3, 4, -5, 6, 7, -8]
        vector = (pack(weights, 4), pack(activations, 16))
        expected = 491470
        self.assertEqual(sum(w * a for w, a in zip(weights, activations)), expected)
        self.assertEqual(model.vector_value(*vector, 0), expected)
        self.assertEqual(model.tensor_tile([vector] * 3, 0), expected * 3)
        negative = (pack([-1] + [0] * 7, 4), pack([1] * 8, 16))
        self.assertEqual(model.tensor_tile([negative], 0), (1 << 64) - 1)

    def test_bfloat_and_mixed_lanes(self):
        ones = pack([0x3F80] * 8, 16)
        self.assertEqual(model.tensor_tile([(ones, ones)], 1), 0x41000000)
        self.assertEqual(model.tensor_tile([(ones, ones)] * 3, 1), 0x41C00000)
        self.assertEqual(model.tensor_tile([(pack([-8, 7] * 4, 4), ones)], 2),
                         0xC0800000)
        tiny = pack([1] + [0] * 7, 16)
        first_weight = pack([0x3F80] + [0] * 7, 16)
        self.assertEqual(model.tensor_tile([(first_weight, tiny)], 1), 0x00010000)
        self.assertEqual(model.tensor_tile([
            (pack([0x7F80] + [0] * 7, 16), ones)], 1), 0x7F800000)

    def test_pairwise_and_tile_order(self):
        weights = pack([0x3F80] * 8, 16)
        lanes = [0x4C80, 0x3F80, 0xCC80, 0x3F80] + [0] * 4
        vector = (weights, pack(lanes, 16))
        self.assertEqual(model.vector_value(*vector, 1), 0)
        exact_sum = sum(model.finite_value(value << 16) for value in lanes)
        self.assertEqual(model.round_fp32(exact_sum), 0x40000000)
        single = lambda bf16: (weights, pack([bf16] + [0] * 7, 16))
        self.assertEqual(model.tensor_tile(
            [single(0x4C80), single(0x3F80), single(0xCC80)], 1), 0)
        self.assertEqual(model.tensor_tile(
            [single(0x4C80), single(0xCC80), single(0x3F80)], 1), 0x3F800000)

    def test_invalid_inputs(self):
        for bits in (-1, 1 << 32):
            with self.assertRaises(ValueError):
                model.finite_value(bits)
        for bits in (0x7F800000, 0x7FC00000):
            with self.assertRaises(ValueError):
                model.finite_value(bits)
        for vectors, mode in (([], 0), ([(0, 0)], 3),
                              ([(1 << 32, 0)], 0), ([(1 << 32, 0)], 2),
                              ([(0, -1)], 1)):
            with self.assertRaises(ValueError):
                model.tensor_tile(vectors, mode)


if __name__ == "__main__":
    if sys.argv[1:] == ["--preparation"]:
        sys.exit(preparation(
            test_file="test_legacy_oracle.py",
            source_files=("tests/legacy_oracle.py", "tests/test_legacy_oracle.py",
                          "tests/test_mm_oracle.py", "tests/mm_oracle.py"),
            stem="legacy-oracle"))
    unittest.main()
