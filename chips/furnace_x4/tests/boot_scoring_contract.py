"""Synthetic oracle-only fixtures; these do not certify DUT or Linux execution."""

import copy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_scoring import score_boot
from workload_model import gcm, xxh32


def fixture():
    records = []
    for job in range(17):
        nonce = bytes(8) + struct.pack(">I", job)
        aad = struct.pack("<10I", 1, 0x300 if job in (0, 16) else 0x100,
                          0x86000ff0, 19, 0x86003000, 0x86004000,
                          0x86005000, 4, 1, job) + nonce
        cipher, tag = gcm(bytes(16), nonce, aad, bytes.fromhex("21436587"))
        if job == 16:
            tag = tag[:7] + bytes([tag[7] ^ 128]) + tag[8:]
        desc = aad + tag + struct.pack("<I", 0x86006000) + bytes(56)
        frame = bytes.fromhex("04224d186040") + bytes([xxh32(b"\x60\x40") >> 8 & 255])
        frame += struct.pack("<I", 0x80000004) + cipher + bytes(4)
        records.append({"job": job, "descriptor": desc.hex(), "frame": frame.hex()})
    observed = {"simulation_exit": 0, "retired": 1, "output_bytes_compared": 2*1048576,
                "crypto_records": records, "coverage": {
                    "tensor_outputs_compared": 16, "vision_audio_fusion_submissions": 16,
                    "dma_taskgraph_submissions": 16, "plic_claim_complete": 49,
                    **{name: 1 for name in (
                        "complete_boot", "m_mode", "s_mode", "u_mode", "sv39_walk",
                        "timer_irq", "permission_fault", "cross_page_mapping")},
                }}
    uart = "\n".join((
        "FURNACE-X4 authenticated tensor exact successes=16 corrupt-tag isolation=1",
        "FURNACE-X4 task-graph copy exact successes=16 dependencies=2..15 mailboxes=0..3",
        "FURNACE-X4 vision/audio/fusion exact successes=16",
        "FURNACE-X4 U permission fault and page-boundary aliases checked",
        "FURNACE-X4 all three families compared; actual fabric IRQs=49",
    )) + "\n"
    return observed, uart


class ScoringContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observed, cls.uart = fixture()

    def test_positive_oracle_fixture(self):
        self.assertEqual(score_boot(self.observed, self.uart)["lz4_aes_tensor_submissions"], 16)

    def test_uart_only_rejected(self):
        value = copy.deepcopy(self.observed)
        value["crypto_records"] = []
        with self.assertRaisesRegex(ValueError, "tensor completions"):
            score_boot(value, self.uart)

    def test_crypto_frame_and_coverage_corruption(self):
        for field, index in (("descriptor", 52), ("frame", 6), ("frame", 11)):
            value = copy.deepcopy(self.observed)
            data = bytearray.fromhex(value["crypto_records"][0][field])
            data[index] ^= 1
            value["crypto_records"][0][field] = data.hex()
            with self.subTest(field=field, index=index), self.assertRaises(ValueError):
                score_boot(value, self.uart)
        for name in ("s_mode", "u_mode", "timer_irq", "permission_fault", "cross_page_mapping"):
            value = copy.deepcopy(self.observed)
            del value["coverage"][name]
            with self.subTest(bin=name), self.assertRaisesRegex(ValueError, "missing"):
                score_boot(value, self.uart)

    def test_uart_interrupt_disagreement(self):
        with self.assertRaisesRegex(ValueError, "interrupt count"):
            score_boot(self.observed, self.uart.replace("IRQs=49", "IRQs=50"))


if __name__ == "__main__":
    unittest.main()
