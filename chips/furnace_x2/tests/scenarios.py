"""Requirement-directed stimulus; coverage is credited only to compared completions."""
import itertools
import random

from oracle import DEFAULT_KEY, beats_for, classify, crc_beats, malformed, packet, parse, toeplitz


class Campaign:
    def __init__(self, width, seed, path):
        self.width, self.lanes = width, width // 8
        self.rng = random.Random(seed)
        self.stream = path.open("w")
        self.rules = [(0, 0, 0, False)] * 64
        self.default, self.key = 0, DEFAULT_KEY
        self.records = {}

    def config(self, op, index=0, value=0, mask=0, action=0, enable=0, key=None):
        key = self.key if key is None else key
        self.stream.write(f"0 {op} {index} {value:x} {mask:x} {action:x} {enable} {int.from_bytes(key, 'big'):x}\n")
        self.apply_config(op, index, value, mask, action, enable, key)

    def apply_config(self, op, index=0, value=0, mask=0, action=0, enable=0, key=None):
        key = self.key if key is None else key
        if op == 0:
            self.rules[index] = value, mask, action, bool(enable)
        elif op == 1:
            self.key = key
        elif op == 2:
            self.rules = [(v, m, a, False) for v, m, a, _ in self.rules]
        else:
            self.default = action

    def reset_model(self):
        self.rules = [(0, 0, 0, False)] * 64
        self.default, self.key = 0, DEFAULT_KEY

    def send(self, data, labels=(), mode=1, beats=None, abort=0, check=None, deferred=None):
        r, l = self.rng, self.lanes
        beats = beats_for(data, l, r) if beats is None else beats
        bad = malformed(beats, l)
        # Header positions remain beat positions. Invalid data is not compacted.
        positions = bytes((d >> (8 * j)) & 255 if k & (1 << j) else 0
                          for d, k, _ in beats for j in range(l))
        length = sum(k.bit_count() for _, k, _ in beats)
        fields, header, tup = parse(positions[:length], bad, length)
        c32 = crc_beats(beats, l, 32, 0x82f63b78)
        c64 = crc_beats(beats, l, 64, 0x9a6c9329ac4bc9b5)
        check = r.randrange(4) if check is None else check
        exp32, exp64 = c32 ^ r.randrange(2), c64 ^ r.randrange(2)
        mismatch = 0 if bad else ((int(exp32 != c32) & check) |
                                   ((int(exp64 != c64) << 1) & check))
        hit, index, action = classify(header, self.rules, self.default)
        h = toeplitz(tup, self.key) if tup else 0
        ident = len(self.records)
        self.stream.write(
            f"1 {ident} {len(beats)} {mode} {abort} {c32:x} {c64:x} {mismatch} {int(bad)} "
            f"{header:x} {length} {h:x} {int(bool(tup))} {hit} {index} {action:x} "
            f"{int(deferred is not None)}\n")
        if deferred is not None:
            p = dict(op=0, index=0, value=0, mask=0, action=0, enable=0, key=self.key)
            p.update(deferred)
            self.stream.write(
                f"{p['op']} {p['index']} {p['value']:x} {p['mask']:x} {p['action']:x} "
                f"{p['enable']} {int.from_bytes(p['key'], 'big'):x}\n")
        for i, (d, k, _) in enumerate(beats):
            # First-beat checking controls must dominate later randomized values.
            c, a, b = (check, exp32, exp64) if i == 0 else (
                r.randrange(4), r.getrandbits(32), r.getrandbits(64))
            self.stream.write(f"{d:x} {k:x} {c:x} {a:x} {b:x}\n")
        self.records[ident] = {
            "labels": list(labels), "beats": len(beats), "header": header,
            "length": length, "crc32": c32, "crc64": c64, "hash": h,
            "rss": int(bool(tup)), "hit": hit, "index": index, "action": action,
            "matching_rules": [i for i, (v, m, _, en) in enumerate(self.rules)
                               if en and ((header ^ v) & m) == 0],
            "fields": fields, "abort": abort}
        if abort:
            self.reset_model()
        elif deferred is not None:
            self.apply_config(**deferred)
        return ident

    def close(self):
        self.stream.close()


def smoke(c):
    c.send(b"", ["empty", "no_stalls"], mode=0, check=3)
    c.send(b"123456789", ["crc_known", "no_stalls"], mode=0, check=3)
    c.config(3, action=0x5a10)
    c.config(0, 63, action=0xaabbccdd, enable=1)
    c.send(packet(c.rng, version=6, proto=6, payload_size=90),
           ["ipv6_tcp", "wildcard", "independent_stalls"], deferred={"op": 2})
    c.send(packet(c.rng, version=4, proto=17, payload_size=80),
           ["ipv4_udp", "simultaneous"], mode=2)
    # Retained seed-17 packet 2975: the received extension length independently
    # establishes capture overflow even though the declared IPv6 extent is cut.
    c.send(bytes.fromhex(
        "0123456789abfedcba98765488a84be48100375286dd60000000004b3c40"
        "e4bbf8356b117f6888027305e26f09fce857285af73ca6a3c8003bef8dc6d24"
        "b3c010000000000000000000000000bcbef16fdbc128da1d313a6750e304eee8329"),
        ["truncated_extent_capture_overflow"])


def directed(c, pairs=True):
    r, l = c.rng, c.lanes
    c.config(2)
    c.config(3, action=0x1234abcd)
    c.send(packet(r), ["default"])
    c.config(0, 0, action=0xbad, enable=0)
    c.config(0, 63, action=0x11223344, enable=1)
    c.send(packet(r), ["wildcard", "disabled"])
    c.config(2)
    c.config(0, 0, action=0x11112222, enable=1)
    for op, pending in enumerate((
            dict(op=0, index=0, action=0x33334444, enable=1),
            dict(op=1, key=r.randbytes(41)),
            dict(op=2),
            dict(op=3, action=0x55556666))):
        c.send(packet(r), [f"atomicity_{op}"], deferred=pending)
        c.send(packet(r), [f"atomicity_following_{op}"])
    for i in range(64):
        c.config(2)
        c.config(0, i, action=0x50000000 + i, enable=1)
        c.send(packet(r, version=4 + 2 * (i & 1), proto=6 if i & 2 else 17),
               [f"winner_{i}"])
    if pairs:
        for a, b in itertools.combinations(range(64), 2):
            c.config(2)
            c.config(0, a, action=0xa0000000 + a, enable=1)
            c.config(0, b, action=0xb0000000 + b, enable=1)
            c.send(packet(r), [f"pair_{a}_{b}"])
    c.config(2)
    c.config(1, key=r.randbytes(41))
    for version, proto in itertools.product((4, 6), (6, 17)):
        for tags in ((), ((0x8100, 0x123),), ((0x88a8, 0xabc), (0x8100, 0x456))):
            c.send(packet(r, version=version, proto=proto, tags=tags),
                   [f"v{version}_p{proto}", f"tags_{len(tags)}"])
    for ihl in range(5, 16):
        c.send(packet(r, ihl=ihl, proto=6), [f"ihl_{ihl}"])
    for kind in (0, 43, 60, 44, 51):
        for count in (1, 8, 9):
            # Repeated Fragment is separately required to be a parse error.
            exts = [(kind, 12 if kind == 51 else 8)] * count
            c.send(packet(r, version=6, extensions=exts),
                   [f"ext_{kind}_{count}"])
    for n in (0, 1, 8, 9):
        c.send(packet(r, version=6, extensions=[(0, 8)] * n), [f"extensions_{n}"])
    c.send(packet(r, version=6, extensions=[(0, 208)]), ["capture_exceeded"])
    c.send(packet(r, version=6, extensions=[(51, 8)]), ["ah_invalid_length"])
    for version, fragment in ((4, 0x2000), (4, 1), (6, 1), (6, 8), (6, 0)):
        c.send(packet(r, version=version, fragment=fragment,
                      extensions=[(44, 8)] if version == 6 else ()),
               [f"fragment_{version}_{fragment}"])
    c.send(packet(r, fragment=0x8000), ["ipv4_reserved_fragment"])
    for proto in (1, 50, 59, 132):
        for v in (4, 6):
            c.send(packet(r, version=v, proto=proto), [f"protocol_{v}_{proto}"])
    for offset in (0, 4, 5, 6, 15):
        c.send(packet(r, proto=6, tcp_offset=offset), [f"tcp_offset_{offset}"])
    for n in (0, 7, 8, 20, 22, 400):
        c.send(packet(r, udp_length=n), [f"udp_length_{n}"])
    c.send(packet(r, udp_length=400, fragment=0x2000), ["udp_first_fragment_long"])
    for original in (packet(r, ihl=15, proto=6, tcp_offset=15),
                     packet(r, version=6, extensions=[(0, 8), (51, 12), (44, 8)],
                            proto=6),
                     packet(r, tags=((0x8100, 5), (0x88a8, 7)))):
        for n in range(len(original)):
            c.send(original[:n], [f"truncation_{len(original)}_{n}", "truncated"])
    base = bytearray(packet(r))
    for name, pos, value in (("bad_version", 14, 0x65), ("bad_ihl", 14, 0x44),
                             ("total_under_ihl", 17, 1), ("total_truncated", 16, 1)):
        d = base.copy()
        d[pos] = value
        c.send(bytes(d), [name])
    d = bytearray(packet(r, version=6))
    d[14] = 0x40
    c.send(bytes(d), ["ipv6_bad_version"])
    d[14] = 0x60
    d[18:20] = bytes(2)
    c.send(bytes(d), ["ipv6_jumbogram"])
    c.send(packet(r, tags=((0x8100, 1), (0x88a8, 2), (0x8100, 3))),
           ["third_vlan"])
    c.send(bytes.fromhex("0123456789abfedcba9876540806") + r.randbytes(30),
           ["non_ip"])
    # Every final keep prefix, including a zero-length trailing beat.
    for n in range(l + 1):
        raw = r.randbytes(l + n)
        beats = beats_for(raw, l, r, empty_tail=(n == 0))
        c.send(raw, [f"keep_{n}"], beats=beats)
    boundaries = {0, 1, 13, 14, 15, 255, 256, 257, 9215, 9216, 9217}
    for boundary in range(l, 4 * l + 1, l):
        boundaries.update((boundary - 1, boundary, boundary + 1))
    for n in sorted(boundaries):
        c.send(r.randbytes(n), [f"length_{n}"])
    # Retain bad-mask numerical semantics, random invalid-lane poison.
    for nonfinal in (False, True):
        beats = beats_for(r.randbytes(l * 2), l, r)
        i = 0 if nonfinal else 1
        d, _, last = beats[i]
        beats[i] = d, 0x5, last
        c.send(b"", ["malformed_nonfinal" if nonfinal else "malformed_final"], beats=beats)
    for kind in (1, 2, 3):
        c.config(0, 0, action=0xabcdef01, enable=1)
        c.config(1, key=r.randbytes(41))
        c.config(3, action=0x12345678)
        c.send(packet(r, payload_size=l * 3), [f"reset_{kind}"],
               mode=2 if kind == 3 else 1, abort=kind)
        c.send(packet(r), [f"reset_recovery_{kind}"])
    c.send(packet(r), ["simultaneous"], mode=2)
    c.send(packet(r), ["no_stalls"], mode=0)


def seeded(c, count):
    r = c.rng
    for i in range(count):
        v = 4 if i % 2 == 0 else 6
        proto = 6 if i % 4 < 2 else 17
        ntags = i % 3
        tags = tuple((r.choice((0x8100, 0x88a8)), r.randrange(65536)) for _ in range(ntags))
        ext = ([(r.choice((0, 43, 60, 51)), 16)] * r.randrange(4)) if v == 6 else ()
        data = packet(r, version=v, proto=proto, tags=tags, ihl=r.randrange(5, 16),
                      extensions=ext, payload_size=r.randrange(100),
                      fragment=(0x2000 if v == 4 else 0) if i % 13 == 0 else 0)
        if i % 19 == 0:
            data = data[:r.randrange(len(data))]
        if i % 23 == 0:
            data += r.randbytes(r.randrange(20))  # ignored Ethernet padding
        if i % 37 == 0:
            c.config(1, key=r.randbytes(41))
        if i % 41 == 0:
            index = r.randrange(64)
            _, h, _ = parse(data)
            mask = r.getrandbits(512)
            c.config(0, index, value=h, mask=mask, action=r.getrandbits(32), enable=1)
        c.send(data, ["seeded", f"seeded_v{v}_p{proto}"], mode=0 if i % 17 == 0 else 1)


def classifier_vectors(path):
    """Public-interface walking data/value/mask tests, all 512 ordinary care bits."""
    expected = []
    with path.open("w") as f:
        def rule(v, m, enable=1):
            f.write(f"0 0 {v:x} {m:x} 51a7 {enable}\n")

        def query(key, hit):
            f.write(f"1 {key:x} deadbeef {hit} 0 {0x51a7 if hit else 0xdeadbeef:x}\n")
            expected.append((hit, 0, 0x51a7 if hit else 0xdeadbeef))

        f.write("2\n")
        full = (1 << 512) - 1
        for bit in range(512):
            one = 1 << bit
            for value, key in ((0, one), (full, full ^ one)):
                rule(value, one)
                query(value, 1)
                query(key, 0)
                rule(value, full ^ one)
                query(key, 1)
        rule(0, 0, 0)
        query(0, 0)
    return expected


def rss_vectors(path, seed):
    r = random.Random(seed)
    cases = []
    for bits in (104, 296):
        n = bits // 8
        for i in range(bits):
            data = (1 << (bits - 1 - i)).to_bytes(n, "big")
            cases.append((data, DEFAULT_KEY, True))
        data = r.randbytes(n)
        for i in range(328):
            cases.append((data, (1 << i).to_bytes(41, "big"), True))
    cases.extend([(bytes(37), DEFAULT_KEY, True),
                  (r.randbytes(37), DEFAULT_KEY, False)])
    a = bytes([66, 9, 149, 187, 161, 142, 100, 80]) + bytes.fromhex("0aea06e6")
    cases.extend([(a + b"\0", DEFAULT_KEY, True), (a + b"\x06", DEFAULT_KEY, True),
                  (a + b"\x11", DEFAULT_KEY, True)])
    expected = []
    with path.open("w") as f:
        for data, key, eligible in cases:
            h = toeplitz(data, key) if eligible else 0
            tup = int.from_bytes(data, "big") << (296 - len(data) * 8)
            f.write(f"1 {tup:x} {len(data)*8} {int(eligible)} {int.from_bytes(key, 'big'):x} {h:x}\n")
            expected.append((h, int(eligible)))
    return expected
