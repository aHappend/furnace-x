"""Exact integer/dyadic FP32 arithmetic; no host float or DUT table dependency."""

from cpu_reference import signed

NAN = 0x7fc00000


def unpack_fp32(bits):
    sign = bits >> 31
    exponent, fraction = (bits >> 23) & 255, bits & 0x7fffff
    if exponent == 255:
        return ("nan" if fraction else "inf"), sign, 0, 0
    mantissa = fraction | (0x800000 if exponent else 0)
    return "finite", sign, mantissa, exponent - 150 if exponent else -149


def rounded_shift(value, shift):
    if shift <= 0:
        return value << -shift
    quotient, remainder = divmod(value, 1 << shift)
    half = 1 << (shift - 1)
    return quotient + int(remainder > half or (remainder == half and quotient & 1))


def fp32_round(sign, magnitude, exponent):
    if magnitude == 0:
        return sign << 31
    top = magnitude.bit_length() - 1 + exponent
    if top < -126:
        rounded = rounded_shift(magnitude, -149 - exponent)
        if rounded < 0x800000:
            return (sign << 31) | rounded
        top, significand = -126, rounded
    else:
        significand = rounded_shift(magnitude, magnitude.bit_length() - 24)
        if significand == 0x1000000:
            top += 1
            significand >>= 1
    if top > 127:
        return (sign << 31) | 0x7f800000
    return (sign << 31) | ((top + 127) << 23) | (significand & 0x7fffff)


def fp32_multiply(a, b):
    ka, sa, ma, ea = unpack_fp32(a)
    kb, sb, mb, eb = unpack_fp32(b)
    if ka == "nan" or kb == "nan" or (
        ka == "inf" and kb == "finite" and mb == 0
    ) or (kb == "inf" and ka == "finite" and ma == 0):
        return NAN
    if ka == "inf" or kb == "inf":
        return ((sa ^ sb) << 31) | 0x7f800000
    return fp32_round(sa ^ sb, ma * mb, ea + eb)


def fp32_add(a, b):
    ka, sa, ma, ea = unpack_fp32(a)
    kb, sb, mb, eb = unpack_fp32(b)
    if ka == "nan" or kb == "nan" or (ka == kb == "inf" and sa != sb):
        return NAN
    if ka == "inf":
        return (sa << 31) | 0x7f800000
    if kb == "inf":
        return (sb << 31) | 0x7f800000
    exponent = min(ea, eb)
    total = (-1 if sa else 1) * (ma << (ea - exponent)) + (
        (-1 if sb else 1) * (mb << (eb - exponent)))
    sign = int(total < 0) if total else int(sa == sb == 1)
    return fp32_round(sign, abs(total), exponent)


def tensor_vector(mode, weights, activations, accumulator=0):
    if mode == 0:
        return (accumulator + sum(signed(w, 4) * signed(a, 16)
                                  for w, a in zip(weights, activations))) & ((1 << 64) - 1)
    products = []
    for w, a in zip(weights, activations):
        if mode == 1:
            weight = w << 16
        else:
            integer = signed(w, 4)
            weight = fp32_round(int(integer < 0), abs(integer), 0)
        products.append(fp32_multiply(weight, a << 16))
    while len(products) > 1:
        products = [fp32_add(products[i], products[i + 1])
                    for i in range(0, len(products), 2)]
    return fp32_add(accumulator, products[0])


def pack_lanes(lanes, width):
    return sum(value << (i * width) for i, value in enumerate(lanes))
