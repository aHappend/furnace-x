"""Public host operations and byte-addressed memory expectations."""

import random
import struct

from crypto_reference import encrypt_gcm
from reference import literal_block, lz4_frame, tensor, decode_lz4


REQUIRED_INFINITY_OPERANDS = tuple(
    f"mode{mode}_{source}_{sign}_infinity"
    for mode, sources in ((1, ("weight", "activation")), (2, ("activation",)))
    for source in sources for sign in ("positive", "negative")
)


def infinity_operands(mode, weights, activations):
    """Classify final byte buffers, including ciphertext-selected plaintext."""
    counts = {}
    operands = [("activation", activations)] if mode in (1, 2) else []
    if mode == 1:
        operands.append(("weight", weights))
    for source, data in operands:
        for (word,) in struct.iter_unpack("<H", data):
            if word in (0x7F80, 0xFF80):
                sign = "negative" if word & 0x8000 else "positive"
                category = f"mode{mode}_{source}_{sign}_infinity"
                counts[category] = counts.get(category, 0) + 1
    return counts


def generate(path, count=24, max_tile=32, depth=1, seed=17, *, content_checksum=False,
             large=False):
    rng = random.Random(seed)
    lines = []
    records = []
    key = bytes(rng.randrange(256) for _ in range(16))
    ring_base = 0x1000

    def write(address, value, response=0, strobe=15, aw_delay=0, w_delay=0):
        lines.append(f"1 {address:x} {value:x} {strobe:x} {response} {aw_delay} {w_delay}\n")

    def read(address, value, response=0):
        lines.append(f"2 {address:x} {value:x} {response}\n")

    def memory(address, before, after=None, permitted=False):
        if after is None:
            after = before
        assert len(before) == len(after)
        for i, (a, b) in enumerate(zip(before, after)):
            allowed = permitted is True or (type(permitted) is int and i < permitted)
            lines.append(f"0 {address+i:x} {a:x} {int(allowed)} {b:x}\n")

    read(0, 0x01000000)
    read(0x1C, depth)
    write(0x18, ring_base, aw_delay=3)
    for word in range(4):
        write(0x30 + 4 * word, int.from_bytes(key[4 * word:4 * word + 4], "little"),
              w_delay=2 if word & 1 else 0)
    write(0x40, 1)
    read(8, 2)
    write(0x10, 3)
    lines.append("9 0\n")
    completed = 0
    next_slot = 0
    for batch_start in range(0, count, depth):
        batch_size = min(depth, count - batch_start)
        for position in range(batch_size):
            index = batch_start + position
            mode = index % 3
            if large:
                if count != 1 or max_tile != 65536:
                    raise ValueError("large capacity construction requires one 65536-byte tile")
                mode = 1
            encoding = ("literal", "raw", "overlap", "linked")[(index // 3) % 4]
            if max_tile < 32 and encoding in ("overlap", "linked"):
                encoding = "raw"
            vectors = min(1 + (index // 3) % 5, max_tile // (16 if mode == 1 else 4))
            if encoding in ("overlap", "linked"):
                vectors = min(32, max_tile) // (16 if mode == 1 else 4)
            if large:
                vectors = 4096
                encoding = "raw"
            if vectors < 1:
                raise ValueError("non-fitting success requested")
            weight_bytes = vectors * (16 if mode == 1 else 4)
            weights_bytes, activations_bytes = bytearray(), bytearray()
            for vector in range(vectors):
                weights = [rng.randrange(65536 if mode == 1 else 16) for _ in range(8)]
                activations = [rng.randrange(65536) for _ in range(8)]
                if index < 3:
                    weights = [0x3F80] * 8 if mode == 1 else list(range(8, 16))
                    activations = [0x7FFF, 0x8000, 0, 1, 0xFFFF, 17, 0xFE00, 0x100] if mode == 0 else [
                        0x3F80, 0xBF80, 1, 0x8001, 0x3F81, 0x7F7F, 0, 0x8000]
                # Successful raw frames preserve these operands; overlap/linked
                # frames instead select ciphertext and replace generated weights.
                if index in (4, 5, 16, 17):
                    infinity = 0x7F80 if index < 16 else 0xFF80
                    weights = [0x3F80 if mode == 1 else 1] * 8
                    activations = [0x3F80] * 8
                    activations[1] = infinity
                    if mode == 1:
                        weights[0] = infinity
                if large:
                    weights = [0x3F00 | rng.randrange(128) for _ in range(8)]
                    activations = [0x3F00 | rng.randrange(128) for _ in range(8)]
                w = sum(x << ((16 if mode == 1 else 4) * lane) for lane, x in enumerate(weights))
                weights_bytes.extend(w.to_bytes(16 if mode == 1 else 4, "little"))
                activations_bytes.extend(struct.pack("<8H", *activations))
            base = position * 0x400
            frame_addr = 0x40002000 + base
            plain_addr = 0x80004000 + base
            activation_addr = 0xC0006000 + base
            result_addr = 0x40008000 + base
            completion_addr = 0x8000C000 + base
            if large:
                frame_addr, plain_addr, activation_addr = 0x40000000, 0x80000000, 0xC0000000
                result_addr, completion_addr = 0x4000, 0x8000
            nonce = bytes(rng.randrange(256) for _ in range(12))
            def blocks(data):
                if encoding == "raw":
                    return [(True, data)]
                if encoding == "overlap":
                    match = len(data) - 6
                    assert 4 <= match < 274
                    return [(False, bytes((0x10 | min(15, match - 4),)) + data[:1] +
                             b"\x01\x00" + (bytes((match - 19,)) if match >= 19 else b"") +
                             b"\x50" + data[-5:])]
                if encoding == "linked":
                    return [(True, data[:8]), (False, b"\x0c\x08\x00\x80" + data[-8:])]
                return [(False, literal_block(data))]

            # Deliberately compressible ciphertext is selected first, then the
            # independent CTR keystream determines its authenticated plaintext.
            if encoding in ("overlap", "linked"):
                assert weight_bytes == 32
                prefix = bytes(rng.randrange(256) for _ in range(8))
                chosen = (prefix[:1] * 27 + prefix[-5:] if encoding == "overlap"
                          else prefix * 3 + prefix[::-1])
                stream, _ = encrypt_gcm(key, nonce, b"", bytes(weight_bytes))
                weights_bytes = bytes(a ^ b for a, b in zip(chosen, stream))
            accumulator = 0
            stride = 16 if mode == 1 else 4
            for vector in range(vectors):
                word = int.from_bytes(weights_bytes[vector*stride:(vector+1)*stride], "little")
                weights = [(word >> ((16 if mode == 1 else 4) * lane)) &
                           (65535 if mode == 1 else 15) for lane in range(8)]
                activations = struct.unpack_from("<8H", activations_bytes, 16 * vector)
                accumulator = tensor(mode, weights, activations, accumulator)
            provisional = lz4_frame(blocks(bytes(weights_bytes)), bytes(weights_bytes),
                                    content_size=bool(index & 2), independent=encoding != "linked",
                                    block_checksum=bool(index & 4),
                                    content_checksum=content_checksum or bool(index & 8))
            tile_id = seed * 1000 + index
            header = struct.pack("<10I", 1, mode | 256, frame_addr, len(provisional), plain_addr,
                                 activation_addr, result_addr, weight_bytes, vectors, tile_id) + nonce
            ciphertext, tag = encrypt_gcm(key, nonce, header, bytes(weights_bytes))
            frame = lz4_frame(blocks(ciphertext), ciphertext,
                              content_size=bool(index & 2), independent=encoding != "linked",
                              block_checksum=bool(index & 4),
                              content_checksum=content_checksum or bool(index & 8))
            assert decode_lz4(frame) == ciphertext
            assert len(frame) == len(provisional)
            tag_failure = index % 6 == 3
            if tag_failure:
                tag = bytes((tag[0] ^ 1,)) + tag[1:]
            status = 4 if tag_failure else 0
            descriptor = header + tag + struct.pack("<I", completion_addr) + bytes(56)
            memory(ring_base + 128 * next_slot, descriptor)
            next_slot = (next_slot + 1) % depth
            memory(frame_addr, frame + bytes((-len(frame)) % 16))
            memory(activation_addr, activations_bytes)
            rounded = (weight_bytes + 15) & ~15
            after_plain = (bytes(weights_bytes) + b"\xa5" * (rounded - weight_bytes)
                           if status == 0 else b"\xa5" * rounded)
            memory(plain_addr, b"\xa5" * rounded, after_plain,
                   permitted=weight_bytes if status == 0 else False)
            result = struct.pack("<QII", accumulator, tile_id, 0)
            memory(result_addr, b"\xa5" * 16, result if status == 0 else b"\xa5" * 16,
                   permitted=status == 0)
            completion = struct.pack("<4I", status, tile_id, weight_bytes if status == 0 else 0, 0)
            memory(completion_addr, b"\xa5" * 16, completion, permitted=True)
            records.append(dict(index=index, mode=mode, vectors=vectors, encoding=encoding,
                                weight_bytes=weight_bytes,
                                infinity_operands=infinity_operands(
                                    mode, weights_bytes, activations_bytes),
                                status=status, tile_id=tile_id, result=f"{accumulator:016x}"))
        # Disabled fetch makes all descriptors genuinely queued, including a full ring.
        write(4, 0)
        write(0x24, completed + batch_size)
        write(0x30, 0, response=2)  # Queued key changes must be rejected.
        write(4, 1)
        completed += batch_size
        lines.append(f"3 {completed}\n")
        write(4, 0)
        batch = records[batch_start:completed]
        irq_status = int(any(r["status"] == 0 for r in batch))
        irq_status |= 2 * int(any(r["status"] != 0 for r in batch))
        read(0x0C, irq_status)
        read(0x14, batch[-1]["status"])
        read(0x28, batch[-1]["tile_id"])
        read(0x24, completed)
        read(8, 2 | (8 if any(r["status"] != 0 for r in records) else 0))
        lines.append("9 1\n")
        write(0x0C, 3)
        lines.append("9 0\n")
    path.write_text("".join(lines))
    return records
