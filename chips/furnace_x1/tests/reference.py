"""Independent serial CRC oracles and normal-polynomial cross-checks."""

import random


PARAMETERS = (
    (32, 0x82F63B78, 0x1EDC6F41, 0xE3069283),
    (64, 0x9A6C9329AC4BC9B5, 0xAD93D23594C93659, 0xAE8B14860A799888),
)


def crc(data, width, polynomial):
    state = (1 << width) - 1
    for byte in data:
        for bit in range(8):
            feedback = (state ^ (byte >> bit)) & 1
            state >>= 1
            if feedback:
                state ^= polynomial
    return state ^ ((1 << width) - 1)


def checksums(data):
    return tuple(crc(data, width, reflected) for width, reflected, _, _ in PARAMETERS)


def reflect(value, width):
    return int(f"{value:0{width}b}"[::-1], 2)


def normal_crc(data, width, polynomial):
    mask = (1 << width) - 1
    state = mask
    for byte in data:
        state ^= reflect(byte, 8) << (width - 8)
        for _ in range(8):
            carry = state & (1 << (width - 1))
            state = (state << 1) & mask
            if carry:
                state ^= polynomial
    return reflect(state, width) ^ mask


def tail_identity():
    """Independently invert a serial zero-byte matrix by Gaussian elimination.

    This supplemental proof checks the architecture's invertibility claim on
    every basis state and missing count. It is never the packet CRC oracle.
    """
    comparisons = 0
    for width, polynomial, _, _ in PARAMETERS:
        mask = (1 << width) - 1

        def zero_byte(state):
            for _ in range(8):
                state = (state >> 1) ^ (polynomial if state & 1 else 0)
            return state

        columns = [zero_byte(1 << bit) for bit in range(width)]
        rows = [sum(((columns[col] >> row) & 1) << col for col in range(width))
                | (1 << (width + row)) for row in range(width)]
        for col in range(width):
            pivot = next(row for row in range(col, width) if rows[row] & (1 << col))
            rows[col], rows[pivot] = rows[pivot], rows[col]
            for row in range(width):
                if row != col and rows[row] & (1 << col):
                    rows[row] ^= rows[col]
        assert all(row & mask == 1 << index for index, row in enumerate(rows))
        inverse = [row >> width for row in rows]
        states = [0, mask] + [1 << bit for bit in range(width)]
        for initial in states:
            padded = initial
            for missing in range(65):
                recovered = padded
                for _ in range(missing):
                    recovered = sum(((recovered & row).bit_count() & 1) << index
                                    for index, row in enumerate(inverse))
                assert recovered == initial, (width, initial, missing, recovered)
                comparisons += 1
                padded = zero_byte(padded)
    return {"basis_and_boundary_states": 100, "missing_counts": 65,
            "identity_comparisons": comparisons, "inversion": "GF2 Gaussian elimination"}


def crosscheck():
    rng = random.Random(0xF123)
    messages = [b"", b"123456789"]
    messages += [rng.randbytes(rng.randrange(513)) for _ in range(128)]
    for width, reflected, normal, known in PARAMETERS:
        assert crc(b"", width, reflected) == 0
        assert crc(b"123456789", width, reflected) == known
        assert normal_crc(b"123456789", width, normal) == known
        for index, data in enumerate(messages):
            actual = crc(data, width, reflected)
            alternate = normal_crc(data, width, normal)
            assert actual == alternate, (width, index, actual, alternate)
    return {"messages": len(messages), "comparisons": 2 * len(messages),
            "known_crc32c": "e3069283", "known_crc64_nvme": "ae8b14860a799888",
            "inverse_tail_math": tail_identity()}
