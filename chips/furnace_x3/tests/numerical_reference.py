"""Exact integer/dyadic FP32 arithmetic; no host float or DUT table dependency."""

import math

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


def vision_features(pixels, iw, ih, ow, oh):
    image = []
    for y in range(oh):
        qy = 256 * y * (ih - 1) // (oh - 1) if oh > 1 else 0
        y0, fy = divmod(qy, 256)
        y1 = min(y0 + 1, ih - 1)
        line = []
        for x in range(ow):
            qx = 256 * x * (iw - 1) // (ow - 1) if ow > 1 else 0
            x0, fx = divmod(qx, 256)
            x1 = min(x0 + 1, iw - 1)
            weighted = (pixels[y0 * iw + x0] * (256 - fx) * (256 - fy) +
                        pixels[y0 * iw + x1] * fx * (256 - fy) +
                        pixels[y1 * iw + x0] * (256 - fx) * fy +
                        pixels[y1 * iw + x1] * fx * fy)
            line.append((weighted + 32768) >> 16)
        image.append(line)
    sums = [0] * 4
    for y in range(oh):
        for x in range(ow):
            p = [[image[max(0, min(oh - 1, y + dy))][max(0, min(ow - 1, x + dx))]
                  for dx in (-1, 0, 1)] for dy in (-1, 0, 1)]
            gx = p[0][2] + 2 * p[1][2] + p[2][2] - p[0][0] - 2 * p[1][0] - p[2][0]
            gy = p[2][0] + 2 * p[2][1] + p[2][2] - p[0][0] - 2 * p[0][1] - p[0][2]
            laplacian = p[0][1] + p[1][0] + p[1][2] + p[2][1] - 4 * p[1][1]
            sums = [a + b for a, b in zip(sums, (p[1][1], abs(gx), abs(gy), abs(laplacian)))]
    return pack_lanes([total // (ow * oh) for total in sums], 16)


def q15_twiddles():
    return [(round(32768 * math.cos(2 * math.pi * k / 64)),
             round(-32768 * math.sin(2 * math.pi * k / 64))) for k in range(64)]


def fft_integer(samples):
    n = len(samples)
    bits = n.bit_length() - 1
    if n not in (8, 16, 32, 64):
        raise ValueError(n)
    values = [(samples[int(f"{i:0{bits}b}"[::-1], 2)], 0) for i in range(n)]
    twiddles = q15_twiddles()
    saturation = lambda value: max(-(1 << 31), min((1 << 31) - 1, value))
    for span in (1 << stage for stage in range(1, bits + 1)):
        half = span // 2
        for group in range(0, n, span):
            for index in range(half):
                ar, ai = values[group + index]
                br, bi = values[group + index + half]
                wr, wi = twiddles[index * 64 // span]
                real, imag = (br * wr - bi * wi) >> 15, (br * wi + bi * wr) >> 15
                values[group + index] = saturation(ar + real), saturation(ai + imag)
                values[group + index + half] = saturation(ar - real), saturation(ai - imag)
    return values


def audio_features(samples):
    n = len(samples)
    history = [0] * 3
    filtered = []
    for sample in samples:
        filtered.append((sample + 3 * history[0] + 3 * history[1] + history[2]) >> 3)
        history = [sample, *history[:2]]
    spectrum = fft_integer(filtered)
    energies = [abs(real) + abs(imag) for real, imag in spectrum]
    lanes = [sum(map(abs, filtered)) // n,
             min(32767, energies[0] // n),
             min(32767, sum(energies[1:n // 4 + 1]) // n),
             min(32767, sum(energies[n // 4 + 1:n // 2 + 1]) // n)]
    return pack_lanes(lanes, 16)
