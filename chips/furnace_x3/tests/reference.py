"""Independent byte-oriented packet references; no RTL imports or co-simulation."""

DEFAULT_KEY = int(
    "6d5a56da255b0ec24167253d43a38fb0d0ca2bcbae7b30b477cb2da38030f20c6a42b73bbeac01fa00", 16
)


def crc(data, width, polynomial):
    value = (1 << width) - 1
    for octet in data:
        value ^= octet
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value ^ ((1 << width) - 1)


def checksums(data):
    return crc(data, 32, 0x82F63B78), crc(data, 64, 0x9A6C9329AC4BC9B5)


def toeplitz(data, key=DEFAULT_KEY):
    result = 0
    for index in range(len(data) * 8):
        if data[index // 8] & (0x80 >> (index % 8)):
            result ^= (key >> (296 - index)) & 0xFFFFFFFF
    return result


def parse(data, malformed_keep=False):
    """Reconstruct the specified header with bounded wire-format decoding."""
    header = 0
    unsupported = False

    def field(value, offset):
        nonlocal header
        header |= value << offset

    def u16(offset):
        return int.from_bytes(data[offset:offset + 2], "big")

    def require(condition):
        if not condition:
            raise ValueError("truncated or malformed wire header")

    def result(value, tuple_bytes=b""):
        if malformed_keep or len(data) > 9216:
            return (1 << 441) | (value & (1 << 442)), b""
        return value, tuple_bytes

    try:
        require(len(data) >= 14)
        field(int.from_bytes(data[:6], "big"), 393)
        field(int.from_bytes(data[6:12], "big"), 345)
        etype, cursor, vlans = u16(12), 14, []
        while etype in (0x8100, 0x88A8):
            if len(vlans) == 2:
                unsupported = True
                break
            require(cursor + 4 <= len(data))
            vlans.append(u16(cursor) & 4095)
            etype, cursor = u16(cursor + 2), cursor + 4
        field(len(vlans), 303)
        for index, value in enumerate(vlans):
            field(value, 305 + 12 * index)
        field(etype, 329)
        if unsupported or etype not in (0x0800, 0x86DD):
            return result(header | (1 << 442))
        start = cursor
        more = noninitial = False
        if etype == 0x0800:
            require(cursor + 20 <= min(len(data), 256))
            ihl = (data[cursor] & 15) * 4
            total = u16(cursor + 2)
            require(data[cursor] >> 4 == 4 and ihl >= 20 and total >= ihl)
            require(start + total <= len(data) and start + ihl <= 256)
            frag = u16(cursor + 6)
            require(not (frag & 0x8000))
            more, noninitial = bool(frag & 0x2000), bool(frag & 8191)
            protocol = data[cursor + 9]
            src, dst = data[cursor + 12:cursor + 16], data[cursor + 16:cursor + 20]
            field(4, 296)
            end, cursor = start + total, start + ihl
        else:
            require(cursor + 40 <= min(len(data), 256))
            require(data[cursor] >> 4 == 6)
            end = start + 40 + u16(cursor + 4)
            require(end <= len(data))
            protocol = data[cursor + 6]
            src, dst = data[cursor + 8:cursor + 24], data[cursor + 24:cursor + 40]
            field(6, 296)
            field(int.from_bytes(src, "big"), 0)
            field(int.from_bytes(dst, "big"), 128)
            field(protocol, 288)
            field(1, 300)
            cursor += 40
            if end == cursor and protocol != 59:
                return result(header | (1 << 442))
            extensions = 0
            fragment_seen = False
            while protocol in (0, 43, 60, 44, 51):
                if extensions == 8:
                    return result(header | (1 << 442))
                require(cursor + 2 <= min(end, len(data), 256))
                next_protocol = data[cursor]
                size = (8 if protocol == 44 else
                        (data[cursor + 1] + 2) * 4 if protocol == 51 else
                        (data[cursor + 1] + 1) * 8)
                require(protocol != 51 or size >= 12)
                require(cursor + size <= end)
                if cursor + size > 256:
                    return result(header | (1 << 442))
                if protocol == 44:
                    require(not fragment_seen)
                    fragment_seen = True
                    frag = u16(cursor + 2)
                    noninitial, more = bool(frag & 0xFFF8), bool(frag & 1)
                cursor, protocol = cursor + size, next_protocol
                header = (header & ~(255 << 288)) | (protocol << 288)
                extensions += 1
                if noninitial:
                    break
        field(int.from_bytes(src, "big"), 0)
        field(int.from_bytes(dst, "big"), 128)
        header = (header & ~(255 << 288)) | (protocol << 288)
        field(1, 300)
        field(int(more or noninitial), 302)
        if noninitial:
            if protocol not in (6, 17, 59):
                return result(header | (1 << 442))
            return result(header)
        if protocol not in (6, 17):
            if etype == 0x86DD and protocol == 59:
                return result(header)
            return result(header | (1 << 442))
        minimum = 20 if protocol == 6 else 8
        require(cursor + minimum <= min(end, len(data)))
        if cursor + minimum > 256:
            return result(header | (1 << 442))
        if protocol == 6:
            size = (data[cursor + 12] >> 4) * 4
            require(size >= 20 and cursor + size <= end)
            if cursor + size > 256:
                return result(header | (1 << 442))
        else:
            size = u16(cursor + 4)
            require(size >= 8 and (more or cursor + size <= end))
        sport, dport = data[cursor:cursor + 2], data[cursor + 2:cursor + 4]
        field(int.from_bytes(sport, "big"), 256)
        field(int.from_bytes(dport, "big"), 272)
        field(1, 301)
        return result(header, b"" if more else src + dst + sport + dport + bytes([protocol]))
    except ValueError:
        return (1 << 441) | (int(unsupported) << 442), b""


def classify(header, rules, default=0):
    for index, rule in sorted(rules.items()):
        value, mask, action, enabled = rule
        if enabled and ((header ^ value) & mask) == 0:
            return True, index, action
    return False, 0, default


def ethernet(ipv6=False, tcp=False, vlans=0, payload=0, fragment=0,
             extensions=0, unsupported=False):
    macs = bytes.fromhex("00112233445566778899aabb")
    ethertype = 0x86DD if ipv6 else 0x0800
    if unsupported:
        return macs + b"\x88\xb5" + bytes(range(30))
    prefix = macs
    for index in range(vlans):
        prefix += (0x8100 if index else 0x88A8).to_bytes(2, "big")
        prefix += (101 + index).to_bytes(2, "big")
    prefix += ethertype.to_bytes(2, "big")
    proto = 6 if tcp else 17
    transport = bytearray(20 if tcp else 8)
    transport[:4] = bytes.fromhex("1234abcd")
    if tcp:
        transport[12] = 0x50
    else:
        transport[4:6] = (len(transport) + payload).to_bytes(2, "big")
    body = bytes(transport) + bytes((i * 73 + 19) & 255 for i in range(payload))
    if ipv6:
        ext = b""
        for index in range(extensions):
            ext += bytes([0 if index + 1 < extensions else proto, 0]) + bytes(6)
        ip = bytearray(40)
        ip[0], ip[6], ip[7] = 0x60, (0 if extensions else proto), 64
        ip[4:6] = (len(ext) + len(body)).to_bytes(2, "big")
        ip[8:24] = bytes.fromhex("20010db8000000000000000000000001")
        ip[24:40] = bytes.fromhex("20010db8000000000000000000000002")
        return prefix + ip + ext + body
    ip = bytearray(20)
    ip[0], ip[8], ip[9] = 0x45, 64, proto
    ip[2:4] = (20 + len(body)).to_bytes(2, "big")
    ip[6:8] = fragment.to_bytes(2, "big")
    ip[12:20] = bytes.fromhex("0a000001c0a80109")
    return prefix + ip + body


def corpus():
    packets = [b"", b"123456789", bytes(range(7))]
    for ipv6 in (False, True):
        for tcp in (False, True):
            for vlans in (0, 1, 2):
                packets.append(ethernet(ipv6, tcp, vlans, 11))
    packets += [
        ethernet(unsupported=True),
        ethernet(fragment=0x2000),
        ethernet(fragment=1),
        ethernet(ipv6=True, extensions=8),
        ethernet(ipv6=True, extensions=9),
        ethernet(ipv6=True, extensions=1),
        ethernet(payload=400),
        ethernet()[:30],
        ethernet(ipv6=True)[:50],
        ethernet(vlans=3),
        ethernet(payload=9200),
    ]
    bad = bytearray(ethernet())
    bad[14] = 0x44
    packets.append(bytes(bad))
    bad = bytearray(ethernet(tcp=True))
    bad[46] = 0x40
    packets.append(bytes(bad))
    for fragment in (0, 1, 8):
        packet = bytearray(ethernet(ipv6=True))
        packet[20] = 44
        packet[18:20] = (16).to_bytes(2, "big")
        packet[54:54] = bytes([17, 0]) + fragment.to_bytes(2, "big") + bytes(4)
        packets.append(bytes(packet))
    bad = bytearray(ethernet())
    bad[38:40] = b"\x00\x07"
    packets.append(bytes(bad))
    bad = bytearray(ethernet(ipv6=True))
    bad[18:20] = b"\x00\x00"
    packets.append(bytes(bad[:54]))
    return packets


def self_check():
    assert checksums(b"123456789") == (0xE3069283, 0xAE8B14860A799888)
    assert checksums(b"") == (0, 0)
    h, t = parse(ethernet())
    assert h & 0xFFFFFFFF == 0x0A000001 and len(t) == 13
    h, t = parse(ethernet(ipv6=True))
    assert (h >> 296) & 15 == 6 and len(t) == 37
    assert classify(0, {63: (0, 0, 99, True), 0: (0, 0, 7, True)}) == (True, 0, 7)
