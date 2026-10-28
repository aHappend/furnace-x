"""Independent byte/field and polynomial models for the frozen FURNACE-X2 contract."""
import random

DEFAULT_KEY = bytes.fromhex(
    "6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa00")
FIELDS = {
    "src": (0, 128), "dst": (128, 128), "sport": (256, 16),
    "dport": (272, 16), "proto": (288, 8), "version": (296, 4),
    "ip": (300, 1), "l4": (301, 1), "fragment": (302, 1),
    "vlans": (303, 2), "outer": (305, 12), "inner": (317, 12),
    "ethertype": (329, 16), "smac": (345, 48), "dmac": (393, 48),
    "error": (441, 1), "unsupported": (442, 1)}


def pack(fields):
    return sum((fields.get(k, 0) & ((1 << n) - 1)) << s
               for k, (s, n) in FIELDS.items())


def toeplitz(data, key=DEFAULT_KEY):
    """Sliding integer windows, not the RTL shift-register recurrence."""
    integer = int.from_bytes(key, "big")
    result = 0
    for i in range(len(data) * 8):
        if data[i // 8] & (128 >> (i % 8)):
            result ^= (integer >> (len(key) * 8 - 32 - i)) & 0xffffffff
    return result


def crc_bytes(data, width, polynomial):
    value = (1 << width) - 1
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value ^ ((1 << width) - 1)


def crc_beats(beats, lanes, width, polynomial):
    raw = bytes((data >> (8 * j)) & 255 if keep & (1 << j) else 0
                for data, keep, _ in beats for j in range(lanes))
    state = crc_bytes(raw, width, polynomial) ^ ((1 << width) - 1)
    # Invert the final zero-byte transitions, not compacted-byte semantics.
    for _ in range((lanes - beats[-1][1].bit_count()) * 8):
        top = state >> (width - 1)
        state = (((state ^ (polynomial if top else 0)) << 1) | top) & ((1 << width) - 1)
    return state ^ ((1 << width) - 1)


def malformed(beats, lanes):
    full = (1 << lanes) - 1
    return any(keep != full for _, keep, _ in beats[:-1]) or (
        beats[-1][1] & (beats[-1][1] + 1)) != 0


def parse(data, bad_keep=False, packet_bytes=None):
    """Parse independent offsets into field dictionaries; then pack the pin vector."""
    f = {}
    length = len(data) if packet_bytes is None else packet_bytes
    error = bad_keep or length < 14 or length > 9216
    unsupported = False

    class Truncated(Exception):
        pass

    def need(end, extent=None):
        if end > len(data) or (extent is not None and end > extent):
            raise Truncated()

    def u16(pos):
        need(pos + 2)
        return int.from_bytes(data[pos:pos + 2], "big")

    try:
        need(14)
        f.update(dmac=int.from_bytes(data[:6], "big"),
                 smac=int.from_bytes(data[6:12], "big"))
        typ, pos, tags = u16(12), 14, []
        while typ in (0x8100, 0x88a8) and len(tags) < 2:
            need(pos + 4)
            tags.append(u16(pos) & 4095)
            typ = u16(pos + 2)
            pos += 4
        f.update(ethertype=typ, vlans=len(tags))
        if tags:
            f["outer"] = tags[0]
        if len(tags) == 2:
            f["inner"] = tags[1]
        if typ not in (0x0800, 0x86dd):
            unsupported = True
        else:
            start = pos
            more, noninitial = False, False
            if typ == 0x0800:
                need(pos + 20)
                ihl = (data[pos] & 15) * 4
                extent = start + u16(pos + 2)
                if data[pos] >> 4 != 4 or ihl < 20 or extent < start + ihl:
                    error = True
                error |= extent > len(data)
                need(start + ihl, extent)
                flags = u16(start + 6)
                error |= bool(flags & 0x8000)
                more, noninitial = bool(flags & 0x2000), bool(flags & 0x1fff)
                proto = data[start + 9]
                f.update(version=4, src=int.from_bytes(data[start + 12:start + 16], "big"),
                         dst=int.from_bytes(data[start + 16:start + 20], "big"), ip=1)
                pos += ihl
            else:
                need(start + 40)
                error |= data[start] >> 4 != 6
                size = u16(start + 4)
                extent = start + 40 + size
                error |= extent > len(data)
                proto = data[start + 6]
                f.update(version=6, src=int.from_bytes(data[start + 8:start + 24], "big"),
                         dst=int.from_bytes(data[start + 24:start + 40], "big"), ip=1)
                pos += 40
                if size == 0 and proto != 59:
                    unsupported = True
                count, seen_fragment = 0, False
                while not unsupported and proto in (0, 43, 60, 44, 51):
                    if count == 8:
                        unsupported = True
                        break
                    error |= pos + 8 > extent or pos + 8 > len(data)
                    if pos + 8 > 256:
                        unsupported = True
                        break
                    need(pos + 8, extent)
                    next_proto = data[pos]
                    n = 8 if proto == 44 else (
                        (data[pos + 1] + 2) * 4 if proto == 51 else (data[pos + 1] + 1) * 8)
                    if proto == 51 and n < 12:
                        error = True
                    if proto == 44:
                        error |= seen_fragment
                        seen_fragment = True
                        frag = u16(pos + 2)
                        noninitial, more = bool(frag >> 3), bool(frag & 1)
                    error |= pos + n > extent or pos + n > len(data)
                    if pos + n > 256:
                        unsupported = True
                        break
                    need(pos + n, extent)
                    pos, proto, count = pos + n, next_proto, count + 1
                    if noninitial:
                        break
            f.update(proto=proto, fragment=int(more or noninitial))
            if not unsupported:
                if proto not in (6, 17):
                    unsupported = not (typ == 0x86dd and proto == 59)
                elif not noninitial:
                    minimum = 20 if proto == 6 else 8
                    error |= pos + minimum > extent or pos + minimum > len(data)
                    if pos + minimum > 256:
                        unsupported = True
                    else:
                        need(pos + minimum, extent)
                        n = (data[pos + 12] >> 4) * 4 if proto == 6 else 8
                        if proto == 6:
                            error |= n < 20
                            error |= pos + n > extent or pos + n > len(data)
                            if pos + n > 256:
                                unsupported = True
                            else:
                                need(pos + n, extent)
                        else:
                            udp = u16(pos + 4)
                            error |= udp < 8 or (not more and pos + udp > extent)
                        if not unsupported:
                            f.update(sport=u16(pos), dport=u16(pos + 2), l4=1)
    except Truncated:
        error = True
    if error:
        f = {"error": 1}
    f["unsupported"] = int(unsupported)
    eligible = bool(f.get("ip") and f.get("l4") and not f.get("fragment") and
                    not error and not unsupported and f.get("proto") in (6, 17))
    tup = b""
    if eligible:
        n = 4 if f["version"] == 4 else 16
        tup = (f["src"].to_bytes(n, "big") + f["dst"].to_bytes(n, "big") +
               f["sport"].to_bytes(2, "big") + f["dport"].to_bytes(2, "big") +
               bytes([f["proto"]]))
    return f, pack(f), tup


def classify(header, rules, default):
    for i, (value, mask, action, enabled) in enumerate(rules):
        if enabled and ((header ^ value) & mask) == 0:
            return 1, i, action
    return 0, 0, default


def ethernet(body, typ=0x0800, tags=()):
    return (bytes.fromhex("0123456789abfedcba987654") +
            b"".join(t.to_bytes(2, "big") + v.to_bytes(2, "big") for t, v in tags) +
            typ.to_bytes(2, "big") + body)


def packet(rng, version=4, proto=17, tags=(), ihl=5, extensions=(),
           fragment=0, tcp_offset=5, udp_length=None, payload_size=13):
    payload = rng.randbytes(payload_size)
    sport, dport = rng.randrange(65536), rng.randrange(65536)
    if proto == 6:
        transport = (sport.to_bytes(2, "big") + dport.to_bytes(2, "big") +
                     bytes(8) + bytes([tcp_offset << 4, 0]) + bytes(6) +
                     rng.randbytes(max(0, tcp_offset * 4 - 20)) + payload)
    elif proto == 17:
        n = len(payload) + 8 if udp_length is None else udp_length
        transport = sport.to_bytes(2, "big") + dport.to_bytes(2, "big") + n.to_bytes(2, "big") + bytes(2) + payload
    else:
        transport = payload
    if version == 4:
        h = bytearray(20)
        h[0] = 0x40 | ihl
        h[2:4] = (ihl * 4 + len(transport)).to_bytes(2, "big")
        h[6:8] = fragment.to_bytes(2, "big")
        h[8:10] = bytes([64, proto])
        h[12:20] = rng.randbytes(8)
        return ethernet(bytes(h) + rng.randbytes(max(0, ihl * 4 - 20)) + transport, tags=tags)
    chain, nxt = b"", proto
    for kind, size in reversed(extensions):
        e = bytearray(size)
        e[0] = nxt
        e[1] = size // 4 - 2 if kind == 51 else size // 8 - 1
        if kind == 44:
            e[1] = 0
            e[2:4] = fragment.to_bytes(2, "big")
        chain, nxt = bytes(e) + chain, kind
    h = bytearray(40)
    h[0] = 0x60
    h[4:6] = (len(chain) + len(transport)).to_bytes(2, "big")
    h[6:8] = bytes([nxt, 64])
    h[8:40] = rng.randbytes(32)
    return ethernet(bytes(h) + chain + transport, 0x86dd, tags)


def beats_for(data, lanes, rng, empty_tail=False):
    parts = [data[i:i + lanes] for i in range(0, len(data), lanes)] or [b""]
    if empty_tail and parts[-1]:
        if len(parts[-1]) != lanes:
            raise ValueError("empty tail requires full preceding beats")
        parts.append(b"")
    return [(int.from_bytes(p + rng.randbytes(lanes - len(p)), "little"),
             (1 << len(p)) - 1, int(i == len(parts) - 1)) for i, p in enumerate(parts)]


def self_check():
    assert crc_bytes(b"123456789", 32, 0x82f63b78) == 0xe3069283
    assert crc_bytes(b"123456789", 64, 0x9a6c9329ac4bc9b5) == 0xae8b14860a799888
    assert crc_bytes(b"", 64, 0x9a6c9329ac4bc9b5) == 0
    # Microsoft RSS published IPv4 address and TCP four-tuple examples.
    addresses = bytes([66, 9, 149, 187, 161, 142, 100, 80])
    assert toeplitz(addresses) == 0x323e8fc2
    assert toeplitz(addresses + bytes.fromhex("0aea06e6") + b"\0") == 0x51ccc178
    # A missing declared payload does not erase capabilities established by
    # received header bytes. No unavailable bytes may establish such a flag.
    ipv6 = bytearray(40)
    ipv6[0] = 0x60
    ipv6[4:6] = (256).to_bytes(2, "big")
    ipv6[6] = 60
    for extension, unsupported in ((b"\x3b\xff" + bytes(6), 1),
                                   (b"\x3b\x00" + bytes(6), 0),
                                   (b"", 0)):
        fields, header, tup = parse(ethernet(bytes(ipv6) + extension, 0x86dd))
        assert fields == {"error": 1, "unsupported": unsupported}
        assert header == (1 << 441) | (unsupported << 442)
        assert tup == b""
    r = random.Random(221)
    for n in (0, 1, 7, 8, 63, 64, 65, 255):
        data = r.randbytes(n)
        for lanes in (8, 64):
            beats = beats_for(data, lanes, r)
            for w, p in ((32, 0x82f63b78), (64, 0x9a6c9329ac4bc9b5)):
                assert crc_beats(beats, lanes, w, p) == crc_bytes(data, w, p)
