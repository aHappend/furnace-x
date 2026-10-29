"""Public host operations and byte-addressed memory expectations."""

import random
import struct

from crypto_reference import encrypt_gcm
from reference import literal_block, lz4_frame, tensor


def generate(path, count=24, max_tile=32, depth=1, seed=17):
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
            lines.append(f"0 {address+i:x} {a:x} {int(permitted)} {b:x}\n")

    read(0, 0x01000000)
    read(0x1C, depth)
    write(0x18, ring_base, aw_delay=3)
    for word in range(4):
        write(0x30 + 4 * word, int.from_bytes(key[4 * word:4 * word + 4], "little"),
              w_delay=2 if word & 1 else 0)
    write(0x40, 1)
    read(8, 2)
    write(0x10, 3)
    completed = 0
    next_slot = 0
    for batch_start in range(0, count, depth):
        batch_size = min(depth, count - batch_start)
        for position in range(batch_size):
            index = batch_start + position
            mode = index % 3
            vectors = min(1 + (index // 3) % 3, max_tile // (16 if mode == 1 else 4))
            if vectors < 1:
                raise ValueError("non-fitting success requested")
            weight_bytes = vectors * (16 if mode == 1 else 4)
            weights_bytes, activations_bytes = bytearray(), bytearray()
            accumulator = 0
            for vector in range(vectors):
                weights = [rng.randrange(65536 if mode == 1 else 16) for _ in range(8)]
                activations = [rng.randrange(65536) for _ in range(8)]
                if index < 3:
                    weights = [0x3F80] * 8 if mode == 1 else list(range(8, 16))
                    activations = [0x7FFF, 0x8000, 0, 1, 0xFFFF, 17, 0xFE00, 0x100] if mode == 0 else [
                        0x3F80, 0xBF80, 1, 0x8001, 0x3F81, 0x7F7F, 0, 0x8000]
                accumulator = tensor(mode, weights, activations, accumulator)
                w = sum(x << ((16 if mode == 1 else 4) * lane) for lane, x in enumerate(weights))
                weights_bytes.extend(w.to_bytes(16 if mode == 1 else 4, "little"))
                activations_bytes.extend(struct.pack("<8H", *activations))
            base = position * 0x400
            frame_addr = 0x40002000 + base
            plain_addr = 0x80004000 + base
            activation_addr = 0xC0006000 + base
            result_addr = 0x40008000 + base
            completion_addr = 0x8000C000 + base
            nonce = bytes(rng.randrange(256) for _ in range(12))
            # Raw and literal framing lengths are data independent, so AAD is frozen first.
            raw = bool(index & 1)
            provisional = lz4_frame([(raw, bytes(weight_bytes) if raw else literal_block(bytes(weight_bytes)))],
                                    bytes(weight_bytes), content_size=bool(index & 2),
                                    block_checksum=bool(index & 4), content_checksum=bool(index & 8))
            tile_id = seed * 1000 + index
            header = struct.pack("<10I", 1, mode | 256, frame_addr, len(provisional), plain_addr,
                                 activation_addr, result_addr, weight_bytes, vectors, tile_id) + nonce
            ciphertext, tag = encrypt_gcm(key, nonce, header, bytes(weights_bytes))
            frame = lz4_frame([(raw, ciphertext if raw else literal_block(ciphertext))], ciphertext,
                              content_size=bool(index & 2), block_checksum=bool(index & 4),
                              content_checksum=bool(index & 8))
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
            memory(plain_addr, b"\xa5" * rounded, after_plain, permitted=status == 0)
            result = struct.pack("<QII", accumulator, tile_id, 0)
            memory(result_addr, b"\xa5" * 16, result if status == 0 else b"\xa5" * 16,
                   permitted=status == 0)
            completion = struct.pack("<4I", status, tile_id, weight_bytes if status == 0 else 0, 0)
            memory(completion_addr, b"\xa5" * 16, completion, permitted=True)
            records.append(dict(index=index, mode=mode, vectors=vectors, weight_bytes=weight_bytes,
                                status=status, tile_id=tile_id, result=f"{accumulator:016x}"))
        # Disabled fetch makes all descriptors genuinely queued, including a full ring.
        write(4, 0)
        write(0x24, completed + batch_size)
        write(0x30, 0, response=2)  # Queued key changes must be rejected.
        write(4, 1)
        completed += batch_size
        lines.append(f"3 {completed}\n")
        write(4, 0)
    path.write_text("".join(lines))
    return records
