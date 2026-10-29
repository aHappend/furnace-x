"""Independent numerical expectations for the frozen FURNACE-X2 contract.

These functions consume mathematical inputs, never DUT state or RTL tables.
They do not model handshakes, security, latency, or imply hardware acceptance.
"""

from decimal import Decimal, localcontext
from functools import lru_cache


FFT_SIZES = (8, 16, 32, 64)
PI = Decimal(
    "3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628"
)


def _range(value, lower, upper, name):
    if not isinstance(value, int) or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer in {lower}..{upper}")
    return value


def bilinear(samples, fx, fy):
    if len(samples) != 4:
        raise ValueError("bilinear requires p00,p10,p01,p11")
    for pixel in samples:
        _range(pixel, 0, 255, "pixel")
    _range(fx, 0, 255, "fx")
    _range(fy, 0, 255, "fy")
    coefficients = ((256 - fx) * (256 - fy), fx * (256 - fy),
                    (256 - fx) * fy, fx * fy)
    return (sum(p * c for p, c in zip(samples, coefficients)) + 32768) // 65536


def spatial(window):
    if len(window) != 9:
        raise ValueError("spatial requires nine row-major pixels")
    for pixel in window:
        _range(pixel, 0, 255, "pixel")
    kernels = (
        (-1, 0, 1, -2, 0, 2, -1, 0, 1),
        (-1, -2, -1, 0, 0, 0, 1, 2, 1),
        (0, 1, 0, 1, -4, 1, 0, 1, 0),
    )
    return (window[4], *(sum(p * c for p, c in zip(window, k)) for k in kernels))


def vision(pixels, iw, ih, ow, oh):
    """Return all resized pixels, spatial tuples, and four summary lanes."""
    for dimension in (iw, ih, ow, oh):
        _range(dimension, 1, 64, "dimension")
    if len(pixels) != iw * ih:
        raise ValueError("incorrect input image length")
    for pixel in pixels:
        _range(pixel, 0, 255, "pixel")
    resized = []
    for y in range(oh):
        qy = 0 if oh == 1 else 256 * y * (ih - 1) // (oh - 1)
        y0, fy = divmod(qy, 256)
        y1 = min(y0 + 1, ih - 1)
        for x in range(ow):
            qx = 0 if ow == 1 else 256 * x * (iw - 1) // (ow - 1)
            x0, fx = divmod(qx, 256)
            x1 = min(x0 + 1, iw - 1)
            resized.append(bilinear(
                [pixels[y0 * iw + x0], pixels[y0 * iw + x1],
                 pixels[y1 * iw + x0], pixels[y1 * iw + x1]], fx, fy))
    neighborhoods = []
    for y in range(oh):
        for x in range(ow):
            window = [
                resized[min(max(y + dy, 0), oh - 1) * ow
                        + min(max(x + dx, 0), ow - 1)]
                for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            ]
            neighborhoods.append(spatial(window))
    features = tuple(
        sum(abs(item[lane]) for item in neighborhoods) // (ow * oh)
        for lane in range(4)
    )
    return resized, neighborhoods, features


def fir(samples):
    for sample in samples:
        _range(sample, -32768, 32767, "PCM sample")
    padded = [0, 0, 0, *samples]
    return [
        (padded[i + 3] + 3 * padded[i + 2]
         + 3 * padded[i + 1] + padded[i]) // 8
        for i in range(len(samples))
    ]


@lru_cache(maxsize=None)
def unit_root(n, k):
    """80-digit Taylor evaluation; negative-exponent complex unit root."""
    with localcontext() as ctx:
        ctx.prec = 80
        angle = -2 * PI * (k % n) / n
        if angle < -PI:
            angle += 2 * PI
        cosine, sine = Decimal(1), angle
        ct, st = cosine, sine
        for j in range(1, 180):
            ct *= -angle * angle / ((2 * j - 1) * (2 * j))
            st *= -angle * angle / ((2 * j) * (2 * j + 1))
            cosine += ct
            sine += st
        return +cosine, +sine


def twiddle(n, k):
    with localcontext() as ctx:
        ctx.prec = 80
        return tuple(int((abs(c) * 32768 + Decimal("0.5")) // 1)
                     * (-1 if c < 0 else 1) for c in unit_root(n, k))


def _sat32(value):
    return min((1 << 31) - 1, max(-(1 << 31), value))


def fft(samples):
    """Recursive mathematical DIT; tuple bins in natural frequency order."""
    if len(samples) not in FFT_SIZES:
        raise ValueError("FFT_N must be 8,16,32,64")
    for sample in samples:
        _range(sample, -32768, 32767, "FFT sample")

    def transform(values):
        n = len(values)
        if n == 1:
            return [(values[0], 0)]
        even, odd = transform(values[::2]), transform(values[1::2])
        low, high = [], []
        for k, ((ar, ai), (br, bi)) in enumerate(zip(even, odd)):
            wr, wi = twiddle(n, k)
            tr = (br * wr - bi * wi) // 32768
            ti = (br * wi + bi * wr) // 32768
            low.append((_sat32(ar + tr), _sat32(ai + ti)))
            high.append((_sat32(ar - tr), _sat32(ai - ti)))
        return low + high

    return transform(list(samples))


def audio(samples):
    filtered = fir(samples)
    bins = fft(filtered)
    n = len(samples)
    magnitude = [abs(re) + abs(im) for re, im in bins]
    features = (
        sum(abs(value) for value in filtered) // n,
        min(32767, magnitude[0] // n),
        min(32767, sum(magnitude[1:n // 4 + 1]) // n),
        min(32767, sum(magnitude[n // 4 + 1:n // 2 + 1]) // n),
    )
    return filtered, bins, features


def check_dft(samples, bins):
    """Supplement exact-bin checks with an independent high-precision DFT.

    In Euclidean complex norm, quantizing a Q15 twiddle adds at most
    epsilon=sqrt(2)/65536 times the ideal odd-subtransform magnitude.
    Two component floors add less than sqrt(2). Thus a conservative stage
    bound is E_s=(2+epsilon)*E_(s-1)+epsilon*2**(s-1)*maxabs+sqrt(2).
    Legal N<=64, signed-16 inputs cannot approach signed-32 saturation.
    """
    n = len(samples)
    if n not in FFT_SIZES or len(bins) != n:
        raise ValueError("invalid DFT shape")
    for sample in samples:
        _range(sample, -32768, 32767, "DFT sample")
    with localcontext() as ctx:
        ctx.prec = 70
        root2 = Decimal(2).sqrt()
        epsilon = root2 / 65536
        bound = Decimal(0)
        for stage in range(n.bit_length() - 1):
            bound = (2 + epsilon) * bound + epsilon * (1 << stage) * max(
                abs(x) for x in samples) + root2
        # Margin covers the finite-precision Taylor/DFT evaluation, not RTL error.
        bound += Decimal("1e-60")
        for k, (re, im) in enumerate(bins):
            dr = di = Decimal(0)
            for j, sample in enumerate(samples):
                wr, wi = unit_root(n, j * k)
                dr += sample * wr
                di += sample * wi
            distance = ((Decimal(re) - dr) ** 2 + (Decimal(im) - di) ** 2).sqrt()
            if distance > bound:
                raise AssertionError(f"DFT bin {k}: distance {distance} > {bound}")
        return bound


def tensor_w4(weights, activations):
    if len(weights) != 8 or len(activations) != 8:
        raise ValueError("tensor requires eight weights and activations")
    for weight in weights:
        _range(weight, -8, 7, "W4 weight")
    for activation in activations:
        _range(activation, -32768, 32767, "A16 activation")
    return sum(w * a for w, a in zip(weights, activations))


def record(payload, identifier, error=0):
    """Little-endian 16-byte feature/result record, including reserved zeros."""
    _range(payload, -(1 << 63), (1 << 64) - 1, "record payload")
    _range(identifier, 0, 65535, "record ID")
    _range(error, 0, 255, "record error")
    return ((payload & ((1 << 64) - 1)).to_bytes(8, "little")
            + bytes(4) + identifier.to_bytes(2, "little") + bytes((0, error)))
