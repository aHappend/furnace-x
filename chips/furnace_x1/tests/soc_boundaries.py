"""Descriptor validation, injected bus faults and reset-epoch public transactions."""

import struct

import soc_cases


CASES = [
    "good", "opcode", "flags", "mode", "reserved", "weight-zero",
    "weight-bound", "vector-zero", "vector-overflow", "frame-zero", "frame-bound",
    "unaligned", "overlap", "address-overflow", "completion-overlap",
    "header-checksum", "content-corruption", "footer-checksum", "descriptor-read", "frame-read",
    "plaintext-write", "weight-read", "activation-read", "result-write",
    "completion-write", "reset-descriptor", "reset-frame", "reset-plaintext",
    "reset-activation", "reset-result", "reset-completion",
]


def generate(path, max_tile, depth, *, compact=False):
    base = path.with_name("boundary-base-vectors.txt")
    soc_cases.generate(base, count=1, max_tile=max(32, max_tile), depth=depth, seed=89,
                       content_checksum=True)
    original = base.read_text().splitlines()
    prefix = original[:next(i for i, line in enumerate(original) if line.startswith("0 "))]
    memory_lines = [line.split() for line in original if line.startswith("0 ")]
    initial = {int(p[1], 16): int(p[2], 16) for p in memory_lines}
    expected = {int(p[1], 16): int(p[4], 16) for p in memory_lines}
    descriptor = bytearray(initial[0x1000 + i] for i in range(128))
    fields = struct.unpack_from("<10I", descriptor)
    _, _, frame, frame_bytes, plain, activation, result, weight_bytes, _, tile_id = fields
    original_completion = struct.unpack_from("<I", descriptor, 68)[0]
    completion = 0xC000
    struct.pack_into("<I", descriptor, 68, completion)
    for data in (initial, expected):
        for i in range(16):
            data[completion + i] = data.pop(original_completion + i)
        for i, byte in enumerate(descriptor):
            data[0x1000 + i] = byte
    lines = list(prefix)
    rows = []
    head = 0
    reads = writes = 0
    scenarios = ["opcode", "weight-bound"] if compact else list(CASES)
    if max_tile == 1:
        scenarios = ["weight-bound", "opcode", "vector-overflow"]
    if max_tile == 65536:
        scenarios += ["extended-B1", "extended-B2", "extended-B3"]
    # Recovery is an independently scored successful tile, not a discarded label.
    expanded = []
    for case in scenarios:
        expanded.append(case)
        if case != "good" and not case.startswith("reset-") and max_tile >= 4:
            expanded.append("good")
    for case in expanded:
        data = dict(initial)
        after = dict(initial)
        permissions = set()
        desc = bytearray(descriptor)
        slot = head % depth
        desc_address = 0x1000 + 128 * slot
        status = 0 if case == "good" else 1
        safe = True
        auth = False
        rd_fault = wr_fault = 0xFFFFFFFF

        def field(offset, value):
            struct.pack_into("<I", desc, offset, value)

        if case == "opcode":
            field(0, 0)
        elif case == "flags":
            field(4, 0x104)
        elif case == "mode":
            field(4, 0x103)
        elif case == "reserved":
            desc[127] = 1
        elif case == "weight-zero":
            field(28, 0)
        elif case == "weight-bound":
            field(28, max_tile + 1)
        elif case == "vector-zero":
            field(32, 0)
        elif case == "vector-overflow":
            field(32, 0x40000001)
        elif case == "frame-zero":
            field(12, 0)
        elif case == "frame-bound":
            field(12, 2 * max_tile + 257)
        elif case == "unaligned":
            field(8, frame + 1)
        elif case == "overlap":
            field(20, plain)
        elif case == "address-overflow":
            field(20, 0xFFFFFFF0)
            field(32, 2)
            field(28, 8)
        elif case == "completion-overlap":
            field(68, plain)
            safe = False
        elif case in ("header-checksum", "content-corruption", "footer-checksum"):
            status = 2
            offset = {"header-checksum": 6, "content-corruption": 12,
                      "footer-checksum": frame_bytes - 1}[case]
            data[frame + offset] ^= 1
            after[frame + offset] = data[frame + offset]
        elif case.startswith("extended-"):
            length = {"extended-B1": 65556, "extended-B2": 65557, "extended-B3": 65578}[case]
            field(28, length)
            field(32, (length + 3) // 4)
        elif case in ("descriptor-read", "frame-read", "weight-read", "activation-read"):
            status = 5
            rd_fault = {"descriptor-read": desc_address, "frame-read": frame,
                        "weight-read": plain, "activation-read": activation}[case]
            reads += 1
            safe = case != "descriptor-read"
            auth = case in ("weight-read", "activation-read")
        elif case in ("plaintext-write", "result-write", "completion-write"):
            status = 5
            wr_fault = {"plaintext-write": plain, "result-write": result,
                        "completion-write": completion}[case]
            writes += 1
            auth = True
        elif case.startswith("reset-"):
            status = 0
            auth = case in ("reset-plaintext", "reset-activation", "reset-result", "reset-completion")
        elif case != "good":
            raise AssertionError(case)
        if max_tile == 1:
            status = 1
        if status == 0 or auth:
            for address in range(plain, plain + weight_bytes):
                after[address] = expected[address]
                permissions.add(address)
        if case in ("good", "result-write", "completion-write", "reset-result", "reset-completion"):
            for address in range(result, result + 16):
                after[address] = expected[address]
                permissions.add(address)
        if safe:
            completion_status = 0 if case == "completion-write" else status
            record = struct.pack("<4I", completion_status, tile_id, weight_bytes if auth or status == 0 else 0, 0)
            for i, byte in enumerate(record):
                after[completion + i] = byte
                permissions.add(completion + i)
        # Replace the descriptor at the software producer's physical ring slot.
        for i in range(128):
            data.pop(0x1000 + i)
            after.pop(0x1000 + i)
        for i, byte in enumerate(desc):
            data[desc_address + i] = byte
            after[desc_address + i] = byte
        lines += [f"0 {a:x} {byte:x} {int(a in permissions)} {after[a]:x}" for a, byte in sorted(data.items())]
        lines += ["8", f"4 {rd_fault:x} {wr_fault:x} 2"]
        lines += ["1 4 0 f 0 0 0", f"1 24 {head+1:x} f 0 3 0",
                  f"1 24 {head:x} f 2 0 3",
                  f"1 24 {head+depth+1:x} f 2 0 0",
                  "1 18 0 f 2 0 0", "1 40 2 1 2 0 0", "1 4 1 f 0 0 0"]
        if case.startswith("reset-"):
            address, direction = {
                "reset-descriptor": (desc_address, 0), "reset-frame": (frame, 0),
                "reset-plaintext": (plain, 1), "reset-activation": (activation, 0),
                "reset-result": (result, 1), "reset-completion": (completion, 1),
            }[case]
            lines += [f"6 {direction} {address:x} 0", "5", *prefix]
            head = 0
        else:
            head += 1
            lines += [f"3 {head}", "1 4 0 f 0 0 0",
                      f"2 14 {status:x} 0", f"2 28 {0 if case == 'descriptor-read' else tile_id:x} 0"]
        rows.append({"case": case, "status": status, "completion_safe": safe,
                     "reset": case.startswith("reset-")})
    # End every reset campaign with fresh work in the new epoch.
    if expanded[-1].startswith("reset-"):
        recovery = path.with_name("boundary-recovery-vectors.txt")
        soc_cases.generate(recovery, count=1, max_tile=max_tile, depth=depth, seed=89)
        lines += recovery.read_text().splitlines()
        head = 1
    lines.append(f"7 {reads} {writes}")
    path.write_text("\n".join(lines) + "\n")
    return rows, head
