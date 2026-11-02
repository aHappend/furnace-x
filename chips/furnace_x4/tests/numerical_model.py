"""Exact binary32 arithmetic oracle using unbounded integers, not DUT recurrences."""

NAN = 0x7FC00000


def decode(bits):
    sign = bits >> 31
    exponent = (bits >> 23) & 255
    fraction = bits & 0x7FFFFF
    if exponent == 255:
        return ("nan" if fraction else "inf"), sign, 0, 0
    magnitude = fraction if exponent == 0 else fraction + (1 << 23)
    return "finite", sign, magnitude, (-149 if exponent == 0 else exponent - 150)


def round_even_integer(value, shift):
    if shift <= 0:
        return value << -shift
    quotient, remainder = divmod(value, 1 << shift)
    halfway = 1 << (shift - 1)
    return quotient + int(remainder > halfway or
                          (remainder == halfway and quotient & 1))


def encode(sign, magnitude, power):
    if magnitude == 0:
        return sign << 31
    exponent = magnitude.bit_length() - 1 + power
    if exponent < -126:
        mantissa = round_even_integer(magnitude, -149 - power)
        if mantissa < (1 << 23):
            return (sign << 31) | mantissa
        exponent = -126
    else:
        mantissa = round_even_integer(magnitude, magnitude.bit_length() - 24)
        if mantissa == (1 << 24):
            mantissa >>= 1
            exponent += 1
    if exponent > 127:
        return (sign << 31) | 0x7F800000
    return (sign << 31) | ((exponent + 127) << 23) | (mantissa & 0x7FFFFF)


def multiply(a, b):
    ak, sa, ma, ea = decode(a)
    bk, sb, mb, eb = decode(b)
    if ak == "nan" or bk == "nan":
        return NAN
    if ak == "inf" or bk == "inf":
        if (ak == "finite" and ma == 0) or (bk == "finite" and mb == 0):
            return NAN
        return ((sa ^ sb) << 31) | 0x7F800000
    return encode(sa ^ sb, ma * mb, ea + eb)


def add(a, b):
    ak, sa, ma, ea = decode(a)
    bk, sb, mb, eb = decode(b)
    if ak == "nan" or bk == "nan" or (ak == bk == "inf" and sa != sb):
        return NAN
    if ak == "inf":
        return (sa << 31) | 0x7F800000
    if bk == "inf":
        return (sb << 31) | 0x7F800000
    power = min(ea, eb)
    total = (-1 if sa else 1) * (ma << (ea - power))
    total += (-1 if sb else 1) * (mb << (eb - power))
    negative = int(total < 0 or (ma == mb == 0 and sa == sb == 1))
    return encode(negative, abs(total), power)


def known_answers():
    cases = (
        (multiply, 0x3FC00000, 0x40000000, 0x40400000),
        (multiply, 0x00000001, 0x3F000000, 0),
        (multiply, 0x00000003, 0x3F000000, 0x00000002),
        (multiply, 0x7F7FFFFF, 0x40000000, 0x7F800000),
        (multiply, 0x7F800000, 0, NAN),
        (add, 0x3F800000, 0x33800000, 0x3F800000),
        (add, 0x3F800001, 0x33800000, 0x3F800002),
        (add, 0x00800000, 0x80000001, 0x007FFFFF),
        (add, 0x3F800000, 0xBF800000, 0),
        (add, 0x80000000, 0x80000000, 0x80000000),
        (add, 0x7F800000, 0xFF800000, NAN),
    )
    for operation, a, b, expected in cases:
        actual = operation(a, b)
        if actual != expected:
            raise ValueError(f"FP oracle known answer: {a:08x},{b:08x}: "
                             f"{actual:08x} != {expected:08x}")
    return len(cases)
