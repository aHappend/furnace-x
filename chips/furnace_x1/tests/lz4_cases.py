"""Requirement-derived frames with independent complete-byte expectations."""

import ctypes
import ctypes.util
import itertools
import random

from reference import decode_lz4, literal_block, lz4_frame


def pattern(n, seed=17):
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(n))


def extended():
    raw = pattern(65536)
    tail1, tail2 = b"\xf3\x91\x52\xa6\xde", b"\x29\x05\x8e\xbb\x73"
    block1 = b"\x0c\xff\xff\x50" + tail1
    block2 = b"\x0c\x15\x00\x50" + tail2
    b1 = raw[:65535] + raw[:16] + tail1
    b2 = raw + raw[1:17] + tail1
    b3 = b2 + b2[65536:65552] + tail2
    assert len(b1) == 65556 and len(b2) == 65557 and len(b3) == 65578
    assert b2[65536:65552] != raw[:16], "wrapped-slot mutation must change expected bytes"
    cases = []
    for label, blocks, expected in [
        ("B1-offset65535", [(True, raw[:65535]), (False, block1)], b1),
        ("B2-linked-at65536", [(True, raw), (False, block1)], b2),
        ("B3-overwritten-history", [(True, raw), (False, block1), (False, block2)], b3),
        ("exact131072", [(True, raw), (True, raw[::-1])], raw + raw[::-1]),
    ]:
        for size in (False, True):
            frame = lz4_frame(blocks, expected, content_size=size,
                             block_checksum=True, content_checksum=True)
            assert decode_lz4(frame) == expected
            cases.append((label + ("-size" if size else ""), frame, expected))
    return cases


def library_check(frames):
    """Optional independent installed standard frame decoder, not a pass fallback."""
    library = ctypes.util.find_library("lz4")
    if not library:
        return {"available": False, "reason": "system liblz4 not installed", "comparisons": 0}
    lib = ctypes.CDLL(library)
    lib.LZ4_versionString.restype = ctypes.c_char_p
    lib.LZ4F_createDecompressionContext.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint]
    lib.LZ4F_createDecompressionContext.restype = ctypes.c_size_t
    lib.LZ4F_decompress.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                  ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    lib.LZ4F_decompress.restype = ctypes.c_size_t
    lib.LZ4F_isError.argtypes = [ctypes.c_size_t]
    lib.LZ4F_isError.restype = ctypes.c_uint
    lib.LZ4F_freeDecompressionContext.argtypes = [ctypes.c_void_p]
    comparisons = 0
    for label, frame, expected in frames:
        context = ctypes.c_void_p()
        assert lib.LZ4F_createDecompressionContext(ctypes.byref(context), 100) == 0
        try:
            source = ctypes.create_string_buffer(frame)
            destination = ctypes.create_string_buffer(max(1, len(expected)))
            source_size, destination_size = ctypes.c_size_t(len(frame)), ctypes.c_size_t(max(1, len(expected)))
            remaining = lib.LZ4F_decompress(context, destination, ctypes.byref(destination_size),
                                          source, ctypes.byref(source_size), None)
            assert not lib.LZ4F_isError(remaining), f"standard liblz4 rejects {label}"
            assert remaining == 0 and source_size.value == len(frame), label
            assert destination_size.value == len(expected), label
            assert destination.raw[:destination_size.value] == expected, label
            comparisons += 1
        finally:
            lib.LZ4F_freeDecompressionContext(context)
    return {"available": True, "version": lib.LZ4_versionString().decode(),
            "comparisons": comparisons}


def make_cases(bound=131072, compact=False):
    cases = []
    valid = []

    def add(label, frame, expected, status=0, *, declared=None, decoded=None, last_mode=0,
            reset_after=0):
        cases.append(dict(label=label, frame=frame, expected=expected, status=status,
                          declared=len(frame) if declared is None else declared,
                          decoded=len(expected) if decoded is None else decoded,
                          last_mode=last_mode, reset_after=reset_after))

    good = b"\x81"
    good_frame = lz4_frame([(True, good)], good)

    def recover():
        add("recovery-singleton", good_frame, good)

    if compact:
        for payload in (b"", b"\x00", b"0123456789abcdefgh", bytes(range(64))):
            frame = lz4_frame([(False, literal_block(payload))], payload,
                             content_size=True, block_checksum=True, content_checksum=True)
            valid.append(("compact-literals", frame, payload))
            add("compact-literals", frame, payload)
        # Legal overlap offset one, match length sixteen, final literal sequence.
        payload = b"A" * 17 + b"12345"
        block = b"\x1cA\x01\x00\x5012345"
        frame = lz4_frame([(False, block)], payload)
        valid.append(("overlap1", frame, payload))
        add("overlap1", frame, payload)
        bad = bytearray(good_frame)
        bad[6] ^= 1
        add("header-checksum", bytes(bad), good, 2)
        recover()
        return cases, valid

    for independent, size, bc, cc, raw in itertools.product((False, True), repeat=5):
        for length in (0, 1, 15, 16, 271, 800):
            if length == 0 and raw:
                blocks = []
            else:
                payload = pattern(length, length + 89)
                blocks = [(raw, payload if raw else literal_block(payload))]
            payload = pattern(length, length + 89)
            frame = lz4_frame(blocks, payload, independent=independent, content_size=size,
                             block_checksum=bc, content_checksum=cc)
            label = f"flags-{int(independent)}{int(size)}{int(bc)}{int(cc)}-raw{int(raw)}-n{length}"
            valid.append((label, frame, payload))
            add(label, frame, payload)
    for offset in (1, 2, 3):
        prefix = bytes(range(0x61, 0x61 + offset))
        expected = bytearray(prefix)
        for _ in range(16):
            expected.append(expected[-offset])
        expected += b"\x18\x7d\xc9\x33\x55"
        block = bytes(((offset << 4) | 12,)) + prefix + offset.to_bytes(2, "little")
        block += b"\x50\x18\x7d\xc9\x33\x55"
        frame = lz4_frame([(False, block)], expected, block_checksum=True, content_checksum=True)
        label = f"overlap-offset{offset}"
        valid.append((label, frame, bytes(expected)))
        add(label, frame, bytes(expected))
    for label, frame, expected in extended():
        valid.append((label, frame, expected))
        if len(expected) <= bound:
            add(label, frame, expected)
        else:
            add(label + "-declared-bound-reject", frame, b"", 2, decoded=len(expected))
            recover()
    # Excess bytes are concealed behind an otherwise accepted declaration.
    b2_frame, b2_expected = extended()[2][1:]
    add("concealed-excess", b2_frame, b2_expected[:65536], 2, decoded=65536)
    recover()
    if bound == 131072:
        add("decoded131073-start-reject", good_frame, b"", 2, decoded=131073)
        recover()
        large = pattern(65536)
        blocks = [(True, large), (True, large[::-1]), (True, b"x")]
        frame = lz4_frame(blocks, large + large[::-1] + b"x")
        add("accepted131072-but-frame-excess", frame, large + large[::-1], 2, decoded=131072)
        recover()
    add("zero-frame-start", b"", b"", 2, declared=0)
    recover()
    add("frame-start-too-large", b"", b"", 2, declared=2 * bound + 257)
    recover()
    add("early-last", good_frame, b"", 2, last_mode=1, decoded=1)
    recover()
    add("missing-last", good_frame, good, 2, last_mode=2)
    recover()
    add("truncated-at-declared-length", good_frame[:-1], good, 2)
    recover()
    add("trailing-byte", good_frame + b"x", good, 2)
    recover()
    add("concatenated-frame", good_frame * 2, good, 2)
    recover()
    for index in range(4):
        frame = bytearray(good_frame)
        frame[index] ^= 0x80
        add(f"magic-byte{index}", bytes(frame), b"", 2, decoded=1)
        recover()
    for label, flags, bd in [
        ("version00", 0x20, 0x40), ("version10", 0xA0, 0x40),
        ("version11", 0xE0, 0x40), ("dictionary-id", 0x61, 0x40),
        ("reserved-flg", 0x62, 0x40), ("reserved-bd", 0x60, 0x41),
        ("bd-256k", 0x60, 0x50), ("bd-4m", 0x60, 0x70),
    ]:
        header = bytes((flags, bd))
        frame = b"\x04\x22\x4d\x18" + header + bytes(((xxhash(header) >> 8) & 255,))
        frame += good_frame[7:]
        add(label, frame, b"", 2, decoded=1)
        recover()
    frame = bytearray(good_frame); frame[6] ^= 1
    add("header-checksum", bytes(frame), b"", 2, decoded=1); recover()
    for kind in ("block", "content"):
        frame = bytearray(lz4_frame([(True, good)], good,
                                   block_checksum=kind == "block", content_checksum=kind == "content"))
        frame[12 if kind == "block" else -1] ^= 0x80
        add(kind + "-checksum", bytes(frame), good, 2); recover()
    from reference import xxh32
    frame = bytearray(lz4_frame([(True, good)], good, content_size=True))
    frame[6] = 2
    frame[14] = (xxh32(frame[4:14]) >> 8) & 255
    add("content-size-mismatch", bytes(frame), b"", 2, decoded=1); recover()
    for label, block, prefix, status in [
        ("zero-offset", b"\x10a\x00\x00\x5012345", b"a", 3),
        ("unavailable-offset", b"\x10a\x02\x00\x5012345", b"a", 3),
        ("literal-overrun", b"\xf0\x01abc", b"abc", 2),
        ("literal-extension-truncated", b"\xf0\xff", b"", 2),
        ("offset-truncated", b"\x10a\x01", b"a", 2),
        ("match-extension-truncated", b"\x1fa\x01\x00\xff", b"a", 2),
        ("no-final-literals", b"\x1ca\x01\x00", b"a" * 17, 2),
        ("short-final-literals", b"\x1ca\x01\x00\x401234", b"a" * 17 + b"1234", 2),
        ("last-match-too-near-end", b"\x10a\x01\x00\x5012345", b"a" * 5 + b"12345", 2),
    ]:
        # This declared length accommodates every provisional byte without making bad syntax valid.
        expected = prefix
        frame = lz4_frame([(False, block)], expected)
        add(label, frame, expected, status, decoded=max(64, len(expected))); recover()
    for label, word in [("block-zero-raw", 0x80000000), ("block-over64k", 65537)]:
        frame = good_frame[:7] + word.to_bytes(4, "little") + good_frame[11:]
        add(label, frame, b"", 2, decoded=1); recover()
    add("reset-in-raw", lz4_frame([(True, pattern(128))], pattern(128)),
        pattern(128), reset_after=40)
    recover()
    return cases, valid


def xxhash(data):
    from reference import xxh32
    return xxh32(data)


def write_cases(path, cases):
    with path.open("w") as out:
        for index, case in enumerate(cases):
            out.write(f"{index} {len(case['frame'])} {case['declared']} {case['decoded']} "
                      f"{len(case['expected'])} {case['status']} {case['last_mode']} {case['reset_after']}\n")
            for data in (case["frame"], case["expected"]):
                out.write("".join(f"{b:02x}\n" for b in data))
