"""Independent exact-rational legacy tensor arithmetic, not an RTL model.

FP32 operations round once to nearest, ties to even, after each specified
operation. No host floating-point arithmetic or DUT-generated tables are used.
The numerical API does not model tensor timing, protocol errors, DMA or crypto.
"""

from fractions import Fraction


CANONICAL_NAN = 0x7FC00000
INFINITY = 0x7F800000


def _uint(value, width):
    if not isinstance(value, int) or not 0 <= value < 1 << width:
        raise ValueError(f"expected an unsigned {width}-bit encoding")
    return value


def _parts(bits):
    _uint(bits, 32)
    return bits >> 31, (bits >> 23) & 255, bits & 0x7FFFFF


def finite_value(bits):
    """Decode a finite binary32 encoding to an exact rational."""
    sign, exponent, fraction = _parts(bits)
    if exponent == 255:
        raise ValueError("NaN and infinity have no finite rational value")
    significand = fraction if exponent == 0 else (1 << 23) + fraction
    power = -149 if exponent == 0 else exponent - 150
    value = Fraction(significand << power) if power >= 0 else Fraction(
        significand, 1 << -power)
    return -value if sign else value


def round_fp32(value, *, negative_zero=False):
    """Encode a rational with gradual underflow and round-to-nearest-even."""
    value = Fraction(value)
    if value == 0:
        return int(negative_zero) << 31
    sign = int(value < 0) << 31
    value = abs(value)
    numerator, denominator = value.numerator, value.denominator
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        if numerator < denominator << exponent:
            exponent -= 1
    elif numerator << -exponent < denominator:
        exponent -= 1
    quantum = max(exponent - 23, -149)
    scaled = value / (1 << quantum) if quantum >= 0 else value * (1 << -quantum)
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    twice = 2 * remainder
    if twice > scaled.denominator or (
        twice == scaled.denominator and whole & 1
    ):
        whole += 1
    if whole < 1 << 23:
        return sign | whole
    exponent = quantum + 23
    if whole == 1 << 24:
        whole >>= 1
        exponent += 1
    if exponent > 127:
        return sign | INFINITY
    return sign | ((exponent + 127) << 23) | (whole - (1 << 23))


def add_fp32(a, b):
    sa, ea, fa = _parts(a)
    sb, eb, fb = _parts(b)
    if (ea == 255 and fa) or (eb == 255 and fb):
        return CANONICAL_NAN
    if ea == 255 and eb == 255 and sa != sb:
        return CANONICAL_NAN
    if ea == 255:
        return (sa << 31) | INFINITY
    if eb == 255:
        return (sb << 31) | INFINITY
    value = finite_value(a) + finite_value(b)
    return round_fp32(value, negative_zero=bool(
        sa and sb and (a & 0x7FFFFFFF) == 0 and (b & 0x7FFFFFFF) == 0))


def multiply_fp32(a, b):
    sa, ea, fa = _parts(a)
    sb, eb, fb = _parts(b)
    az, bz = (a & 0x7FFFFFFF) == 0, (b & 0x7FFFFFFF) == 0
    if (ea == 255 and fa) or (eb == 255 and fb):
        return CANONICAL_NAN
    if (ea == 255 and bz) or (eb == 255 and az):
        return CANONICAL_NAN
    sign = sa ^ sb
    if ea == 255 or eb == 255:
        return (sign << 31) | INFINITY
    return round_fp32(finite_value(a) * finite_value(b),
                      negative_zero=bool(sign))


def _signed_lane(word, lane, width):
    value = (word >> (lane * width)) & ((1 << width) - 1)
    return value - (1 << width) if value & (1 << (width - 1)) else value


def vector_value(weight_data, activation_data, mode):
    """Return one vector's signed integer or binary32 result encoding."""
    _uint(weight_data, 128)
    _uint(activation_data, 128)
    if mode not in (0, 1, 2):
        raise ValueError("legal tensor modes are 0,1,2")
    if mode != 1 and weight_data >> 32:
        raise ValueError("W4 modes require zero reserved weight bits")
    if mode == 0:
        return sum(_signed_lane(weight_data, i, 4)
                   * _signed_lane(activation_data, i, 16) for i in range(8))
    products = []
    for i in range(8):
        weight = ((weight_data >> (16 * i)) & 65535) << 16 if mode == 1 else (
            round_fp32(_signed_lane(weight_data, i, 4)))
        activation = ((activation_data >> (16 * i)) & 65535) << 16
        products.append(multiply_fp32(weight, activation))
    while len(products) > 1:
        products = [add_fp32(products[i], products[i + 1])
                    for i in range(0, len(products), 2)]
    return products[0]


def tensor_tile(vectors, mode):
    """Expected public result for a complete legal first..last vector tile."""
    if mode not in (0, 1, 2):
        raise ValueError("legal tensor modes are 0,1,2")
    if not vectors:
        raise ValueError("a tile must contain at least one vector")
    accumulated = 0
    for weights, activations in vectors:
        value = vector_value(weights, activations, mode)
        accumulated = accumulated + value if mode == 0 else add_fp32(
            accumulated, value)
    if mode == 0:
        if not -(1 << 63) <= accumulated < 1 << 63:
            raise OverflowError("tile exceeds the exact signed-64 contract")
        return accumulated & ((1 << 64) - 1)
    return accumulated
