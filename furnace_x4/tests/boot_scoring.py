"""Independent boot-result scoring; UART messages are never coverage evidence."""

import struct

from workload_model import gcm, known_answers, xxh32


def score_boot(observations, uart):
    known_answers()
    coverage = dict(observations["coverage"])
    records = observations["crypto_records"]
    if observations["simulation_exit"] or not observations["retired"]:
        raise ValueError("boot did not complete executed-instruction comparisons")
    if len(records) != 17 or coverage.get("tensor_outputs_compared") != 16:
        raise ValueError("boot lacks all independently compared tensor completions")
    for job, record in enumerate(records):
        if record["job"] != job:
            raise ValueError("boot crypto submission order/ID mismatch")
        descriptor, frame = bytes.fromhex(record["descriptor"]), bytes.fromhex(record["frame"])
        if len(descriptor) != 128 or len(frame) != 19:
            raise ValueError("boot descriptor/frame snapshot length mismatch")
        fields = struct.unpack_from("<10I", descriptor)
        if (fields[0], fields[1], fields[3], fields[7], fields[8], fields[9]) != (
                1, 0x300 if job in (0, 16) else 0x100, 19, 4, 1, job):
            raise ValueError(f"boot independent descriptor ABI mismatch: job={job}")
        addresses = (fields[2], fields[4], fields[5], fields[6],
                     struct.unpack_from("<I", descriptor, 68)[0])
        sizes = (32, 16, 16, 16, 16)
        if any(a < 0x86000000 or a + n > 0x87000000 or a & 15
               for a, n in zip(addresses, sizes)):
            raise ValueError("boot descriptor addresses outside controlled DMA allocation")
        if any(a < b + m and b < a + n
               for i, (a, n) in enumerate(zip(addresses, sizes))
               for b, m in tuple(zip(addresses, sizes))[:i]):
            raise ValueError("boot descriptor regions overlap")
        nonce = bytes(8) + struct.pack(">I", job)
        if descriptor[40:52] != nonce or descriptor[72:] != bytes(56):
            raise ValueError("boot independent nonce/reserved descriptor bytes mismatch")
        cipher, tag = gcm(bytes(16), nonce, descriptor[:52], bytes.fromhex("21436587"))
        if job == 16:
            tag = tag[:7] + bytes([tag[7] ^ 128]) + tag[8:]
        if descriptor[52:68] != tag:
            raise ValueError(f"boot independent AES-GCM tag/AAD mismatch: job={job}")
        header = bytes.fromhex("04224d186040") + bytes([xxh32(b"\x60\x40") >> 8 & 255])
        expected_frame = header + struct.pack("<I", 0x80000004) + cipher + bytes(4)
        if frame != expected_frame:
            raise ValueError(f"boot LZ4 header/checksum/ciphertext mismatch: job={job}")
    coverage["lz4_aes_tensor_submissions"] = 16
    if coverage.get("vision_audio_fusion_submissions") != 16 or (
            coverage.get("dma_taskgraph_submissions") != 16):
        raise ValueError("boot lacks all three independently compared workload families")
    if observations["output_bytes_compared"] < 2 * 1048576:
        raise ValueError("boot missing independently checked maximum-length DMA bytes")
    expected_lines = (
        "FURNACE-X4 authenticated tensor exact successes=16 corrupt-tag isolation=1",
        "FURNACE-X4 task-graph copy exact successes=16 dependencies=2..15 mailboxes=0..3",
        "FURNACE-X4 vision/audio/fusion exact successes=16",
        "FURNACE-X4 U permission fault and page-boundary aliases checked",
    )
    lines = uart.replace("\r", "").splitlines()
    for line in expected_lines:
        if lines.count(line) != 1:
            raise ValueError(f"physical UART result differs from independent observations: {line}")
    completions = [
        line for line in lines if line.startswith(
            "FURNACE-X4 all three families compared; actual fabric IRQs=")
    ]
    if len(completions) != 1 or int(completions[0].split("=")[1]) != coverage.get(
            "plic_claim_complete", 0):
        raise ValueError("UART fabric interrupt count differs from executed PLIC claim/complete pairs")
    for name in ("complete_boot", "m_mode", "s_mode", "u_mode", "sv39_walk",
                 "timer_irq", "permission_fault", "cross_page_mapping"):
        if coverage.get(name, 0) <= 0:
            raise ValueError(f"missing executed/compared Linux coverage: {name}")
    return coverage
