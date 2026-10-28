"""Packet-space coverage, independent payload/CRC expectations, public cycle table.

The scheduler models only the specified 16-edge public latency and independent
output retirement. It has no DUT hierarchy or implementation-state access.
All numerical expectations use the serial reference, never padded-beat CRCs.
"""

import json
import random
from collections import deque

from reference import checksums


DIRECTED_LENGTHS = (255, 256, 257, 511, 512, 513, 4095, 4096, 4097,
                    65535, 65536, 65537)


class Packets:
    def __init__(self, width, seed):
        self.width = width
        self.lanes = width // 8
        self.rng = random.Random(seed)
        self.records = []

    def data(self, length, pattern):
        if pattern == "zero":
            return bytes(length)
        if pattern == "ones":
            return b"\xff" * length
        if pattern == "walking":
            return bytes(1 << (i & 7) for i in range(length))
        return self.rng.randbytes(length)

    def packet(self, data, *, enable=None, incorrect=0, extra=False,
               pattern="random", group="legal", pair=None, side=None,
               beats_override=None, overrides=None):
        identifier = len(self.records)
        enable = identifier % 4 if enable is None else enable
        values = checksums(data)
        expected = (values[0] ^ (1 if incorrect & 1 else 0),
                    values[1] ^ (1 if incorrect & 2 else 0))
        beats = []
        chunks = [data[i:i + self.lanes] for i in range(0, len(data), self.lanes)]
        if not chunks or (extra and len(data) % self.lanes == 0):
            chunks.append(b"")
        for index, chunk in enumerate(chunks):
            padding = self.rng.randbytes(self.lanes - len(chunk))
            beats.append({
                "data": int.from_bytes(chunk + padding, "little"),
                "keep": (1 << len(chunk)) - 1,
                "last": int(index == len(chunks) - 1),
                "enable": enable if index == 0 else (enable ^ 3),
                "expected32": expected[0] if index == 0 else (expected[0] ^ 0xFFFFFFFF),
                "expected64": expected[1] if index == 0 else (expected[1] ^ 0xFFFFFFFFFFFFFFFF),
                "packet": identifier,
            })
        if beats_override is not None:
            beats = beats_override
            for index, beat in enumerate(beats):
                beat.update(packet=identifier, enable=enable if index == 0 else enable ^ 3,
                            expected32=expected[0] if index == 0 else 0x12345678,
                            expected64=expected[1] if index == 0 else 0x123456789ABCDEF0)
        if overrides:
            for index, fields in overrides.items():
                beats[index].update(fields)
        protocol = any(
            (b["keep"] != (1 << self.lanes) - 1) if not b["last"]
            else (b["keep"] & (b["keep"] + 1)) != 0 for b in beats
        )
        record = {
            "id": identifier, "length": len(data), "pattern": pattern,
            "group": group, "pair": pair, "side": side, "enable": enable,
            "incorrect": incorrect, "extra": extra, "beats": len(beats),
            "final_count": beats[-1]["keep"].bit_count(),
            "crc32": values[0], "crc64": values[1],
            "protocol": int(protocol),
            "mismatch": 0 if protocol else (enable & incorrect),
        }
        self.records.append(record)
        for beat in beats:
            beat["result"] = record if beat["last"] else None
        return beats


class Schedule:
    def __init__(self, directory, width, seed):
        self.width = width
        self.rng = random.Random(seed ^ 0xBAD5EED)
        self.vector = (directory / "vectors.txt").open("w")
        self.expect = (directory / "expected.jsonl").open("w")
        self.delay = deque([None] * 15)
        self.payload = None
        self.result = None
        self.cycles = 0

    def outputs(self, mr, cr, reset=False):
        if reset:
            return {"ready": 0, "payload": None, "result": None, "reset": True}
        ready = int((self.payload is None or mr) and (self.result is None or cr))
        return {"ready": ready, "payload": self.payload, "result": self.result,
                "reset": False}

    def step(self, beat=None, *, mr=1, cr=1, reset=False, pulse=False, event=None):
        if pulse:
            assert not reset and beat is None, "asynchronous reset probe isolation"
            self.delay = deque([None] * 15)
            self.payload = self.result = None
        pre = self.outputs(mr, cr, reset)
        accepted = beat is not None and pre["ready"]
        if reset:
            self.delay = deque([None] * 15)
            self.payload = self.result = None
        elif pre["ready"]:
            arrived = self.delay.pop()
            self.delay.appendleft(beat if accepted else None)
            self.payload = arrived
            self.result = arrived["result"] if arrived else None
        else:
            if mr:
                self.payload = None
            if cr:
                self.result = None
        post = self.outputs(mr, cr, reset)
        fields = [int(not reset), int(beat is not None),
                  beat["data"] if beat else 0, beat["keep"] if beat else 0,
                  beat["last"] if beat else 0, beat["enable"] if beat else 0,
                  beat["expected32"] if beat else 0,
                  beat["expected64"] if beat else 0, mr, cr]
        self.vector.write(" ".join(f"{x:x}" for x in fields + [int(pulse)]) + "\n")
        self.expect.write(json.dumps({
            "cycle": self.cycles, "pre": pre, "post": post,
            "accepted": beat if accepted else None, "mr": mr, "cr": cr,
            "event": event, "inputs": fields, "pulse": pulse,
        }, separators=(",", ":")) + "\n")
        self.cycles += 1
        assert self.cycles < 2_000_000, "cycle-bounded stimulus progress"
        return accepted

    def send(self, beats, randomized=False):
        for beat in beats:
            if randomized:
                for _ in range(self.rng.randrange(3)):
                    self.step(mr=int(self.rng.random() > .3),
                              cr=int(self.rng.random() > .4))
            for wait in range(4096):
                mr = int(self.rng.random() > .3) if randomized else 1
                cr = int(self.rng.random() > .4) if randomized else 1
                if self.step(beat, mr=mr, cr=cr):
                    break
            else:
                raise AssertionError("bounded source progress")

    def drain(self):
        for _ in range(128):
            if not any(self.delay) and self.payload is None and self.result is None:
                return
            self.step()
        raise AssertionError("bounded drain")

    def reach_output(self, beats):
        self.send(beats)
        for _ in range(32):
            if self.payload is not None and self.result is not None:
                return
            self.step(mr=0, cr=0)
        raise AssertionError("bounded output occupancy")

    def close(self):
        self.vector.close()
        self.expect.close()


def make_scenario(directory, width, seed, full):
    p = Packets(width, seed)
    s = Schedule(directory, width, seed)
    b = p.lanes
    s.step(reset=True, event="idle")
    s.step(reset=True)
    s.step()

    # Guaranteed consecutive single-beat completions and empty-packet coverage.
    for index in range(32):
        data = b"" if index < 12 else bytes([index])
        s.send(p.packet(data, enable=index % 4, incorrect=(index // 4) % 4,
                        group="consecutive"))
    s.drain()
    s.send(p.packet(b"123456789", enable=3, group="known"))
    s.send(p.packet(p.data(2 * b + 3, "walking"), enable=3, pattern="walking"))
    s.drain()

    # Observe each independent-retirement direction for forty actual stall edges.
    for direction in ("payload", "result"):
        s.reach_output(p.packet(b"\x69", enable=3))
        for _ in range(40):
            s.step(mr=int(direction != "payload"), cr=int(direction != "result"))
        s.drain()

    # Sixteen publicly outstanding beats, a blocked source held unchanged,
    # one-channel retirement, and advance on the other channel's later retire.
    for index in range(16):
        s.send(p.packet(bytes([index ^ 0xAA]), enable=index % 4,
                        incorrect=index % 4, group="full-occupancy"))
    blocked = p.packet(b"\x51", enable=3, group="full-occupancy")[0]
    for _ in range(8):
        assert not s.step(blocked, mr=0, cr=0), "full pipeline must backpressure"
    assert not s.step(blocked, mr=1, cr=0), "result stall must prevent advance"
    assert s.step(blocked, mr=0, cr=1), "retired payload must not block result retirement"
    s.drain()

    # Reset every possible latency occupancy, then demonstrate fresh recovery.
    for age in range(16):
        s.send(p.packet(b"\xa5", enable=3, group="aborted"))
        for _ in range(age):
            s.step(mr=0, cr=0)
        s.step(reset=True, event=f"occupancy-{age}")
        s.send(p.packet(bytes([age]), enable=3, group="recovery"))
        s.drain()

    # Leave a real open packet, including recurrence after all payload has drained.
    partial = p.packet(p.data(2 * b, "random"), group="aborted")
    partial[-1]["last"] = 0
    partial[-1]["result"] = None
    s.send(partial)
    s.drain()
    for _ in range(20):
        s.step()
    s.step(reset=True, event="partial")
    s.send(p.packet(b"\x13", enable=3, group="recovery"))
    s.drain()

    for direction in ("payload", "result", "both"):
        s.reach_output(p.packet(b"\x7e", enable=3, group="aborted"))
        mr, cr = int(direction == "result"), int(direction == "payload")
        s.step(mr=mr, cr=cr)
        s.step(mr=mr, cr=cr)
        s.step(reset=True, event=f"stalled-{direction}")
        s.send(p.packet(b"\x42", enable=3, group="recovery"))
        s.drain()

    # No rising edge occurs during these pulses: a synchronous-reset substitute
    # cannot erase occupied state and then pass the fresh recovery packet.
    for condition in ("idle", "internal", "partial", "stalled"):
        if condition == "internal":
            s.send(p.packet(b"\x36", enable=3, group="aborted"))
            for _ in range(4):
                s.step()
        elif condition == "partial":
            partial = p.packet(p.data(b, "random"), group="aborted")
            partial[-1]["last"] = 0
            partial[-1]["result"] = None
            s.send(partial)
            s.drain()
        elif condition == "stalled":
            s.reach_output(p.packet(b"\xc3", enable=3, group="aborted"))
        s.step(pulse=True, mr=0, cr=0, event=f"async-{condition}")
        s.send(p.packet(b"\x16\x7d", enable=3, group="recovery"))
        s.drain()

    # Holey final, partial nonfinal, and accumulated error through a legal last.
    for index in range(8):
        malformed = [
            {"data": p.rng.getrandbits(width), "keep": 5, "last": 1}
        ] if index % 2 == 0 else [
            {"data": p.rng.getrandbits(width), "keep": 1, "last": 0},
            {"data": p.rng.getrandbits(width), "keep": (1 << b) - 1, "last": 1},
        ]
        beats = p.packet(b"", enable=3, incorrect=3, group="malformed",
                        beats_override=malformed)
        if index == 0:
            s.drain()
            s.reach_output(beats)
            s.step(mr=0, cr=0)
            for _ in range(4):
                s.step(mr=1, cr=0)
            s.drain()
        else:
            s.send(beats, randomized=True)
        s.send(p.packet(b"\x93\x27", enable=3, group="recovery"), randomized=True)

    patterns = ("zero", "ones", "walking", "random")
    if full:
        lengths = list(range(2 * b + 2)) + list(DIRECTED_LENGTHS)
        lengths += [p.rng.randrange(4097) for _ in range(100)]
        random_start = 2 * b + 2 + len(DIRECTED_LENGTHS)
        while len(lengths) < 512:
            lengths.append(p.rng.randrange(4097))
    else:
        lengths = [0, 1, b - 1, b, b + 1, 2 * b, 2 * b + 1, 9]
        random_start = len(lengths)
    for index, length in enumerate(lengths):
        pattern = patterns[index % 4]
        group = "random-length" if random_start <= index < random_start + 100 else "legal"
        s.send(p.packet(p.data(length, pattern), enable=index % 4,
                        incorrect=(index // 4) % 4, extra=index % 2 == 0,
                        pattern=pattern, group=group), randomized=True)
    for length in (b, 2 * b):
        for extra in (False, True):
            s.send(p.packet(p.data(length, "random"), extra=extra, enable=3,
                            group="exact-multiple"), randomized=True)

    flip_lengths = (1, b - 1, b, b + 1, 2 * b - 1, 2 * b, 2 * b + 1, 3 * b + 3)
    proofs = []
    for pair in range(128 if full else 8):
        length = flip_lengths[pair % len(flip_lengths)]
        original = p.data(length, "random")
        bit = p.rng.randrange(8 * length)
        changed = bytearray(original)
        changed[bit // 8] ^= 1 << (bit % 8)
        changed = bytes(changed)
        assert sum((x ^ y).bit_count() for x, y in zip(original, changed)) == 1
        before, after = checksums(original), checksums(changed)
        assert before[0] != after[0] and before[1] != after[1]
        base = p.packet(original, enable=3, group="flip", pair=pair, side="base")
        mutated = p.packet(changed, enable=3, group="flip", pair=pair, side="changed")
        mutated[0]["expected32"], mutated[0]["expected64"] = before
        p.records[-1]["mismatch"] = 3
        proofs.append({"pair": pair, "bit": bit, "original": original.hex(),
                       "changed": changed.hex(), "before": before, "after": after})
        s.send(base, randomized=True)
        s.send(mutated, randomized=True)

    for pair in range(16):
        data = p.data(b - 1, "random")
        base = p.packet(data, enable=3, group="disabled-flip", pair=pair, side="base")
        changed = p.packet(data, enable=3, group="disabled-flip", pair=pair, side="changed")
        changed[-1]["data"] = base[-1]["data"] ^ (1 << (8 * (b - 1) + pair % 8))
        assert (base[-1]["data"] ^ changed[-1]["data"]).bit_count() == 1
        assert not base[-1]["keep"] & (1 << (b - 1))
        s.send(base, randomized=True)
        s.send(changed, randomized=True)
    s.drain()
    for _ in range(24):
        s.step()
    s.close()
    manifest = {"width": width, "seed": seed, "full": full, "cycles": s.cycles,
                "packets": p.records, "flip_proofs": proofs}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
