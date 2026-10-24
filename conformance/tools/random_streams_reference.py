#!/usr/bin/env python3
"""Reference implementation of the draft SREP "Define the random streams derived from the D24 hash"
(srep/srep-0000-random-streams.md), written from the SREP text and from D24 of conformance/DEFINITIONS.md, not
from an engine. Every function is a pure function of integers and binary64 numbers; integers are 64-bit two's
complement as the SREP states. tests/test_random_streams.py checks the golden values and the SREP's numeric table
against this module.

Usage: python3 random_streams_reference.py  (prints the numeric-test table of the SREP). Standard library only.
"""
import math

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1
PHI = 0x9E3779B97F4A7C15          # SplitMix64 increment
MUL1 = 0xBF58476D1CE4E5B9         # SplitMix64 finaliser multipliers
MUL2 = 0x94D049BB133111EB
TWO53 = float(1 << 53)
TWO32 = float(1 << 32)


def u64(x):
    """An integer in [-2^63, 2^64) as an unsigned 64-bit value (two's complement for negatives)."""
    if not isinstance(x, int) or x < -(1 << 63) or x >= (1 << 64):
        raise ValueError(f"not a 64-bit integer: {x!r}")
    return x & MASK64


# --- section 1: the lattice hash and the unit draw (D24; SREP 26) ---------------------------------------------

def mix64(z):
    """The SplitMix64 finaliser."""
    z &= MASK64
    z = ((z ^ (z >> 30)) * MUL1) & MASK64
    z = ((z ^ (z >> 27)) * MUL2) & MASK64
    return z ^ (z >> 31)


def splitmix64(x):
    """splitmix64(x) = mix64(x + 0x9E3779B97F4A7C15 mod 2^64)."""
    return mix64((u64(x) + PHI) & MASK64)


def H(seed, channel, index):
    """The lattice hash H(s, c, i) = splitmix64(s xor splitmix64(c xor splitmix64(i)))."""
    return splitmix64(u64(seed) ^ splitmix64(u64(channel) ^ splitmix64(u64(index))))


def U(seed, channel, index):
    """The unit draw U(s, c, i) = floor(H / 2^11) / 2^53, in [0, 1)."""
    return (H(seed, channel, index) >> 11) / TWO53


# --- section 2: derived draws ------------------------------------------------------------------------------------

def G(seed, channel, index):
    """The normal draw: Box-Muller from one hash, u1 = (high 32 bits + 1/2) / 2^32, u2 = low 32 bits / 2^32."""
    h = H(seed, channel, index)
    u1 = ((h >> 32) + 0.5) / TWO32
    u2 = (h & MASK32) / TWO32
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(math.tau * u2)


def P(seed, channel, n):
    """The permutation of 0..n-1: Fisher-Yates over U(s, c, 0), U(s, c, 1), ... for i = n-1 down to 1,
    swapping i with min(floor(u (i + 1)), i)."""
    if not isinstance(n, int) or n < 0:
        raise ValueError(f"not a count: {n!r}")
    p = list(range(n))
    for k, i in enumerate(range(n - 1, 0, -1)):
        j = int(U(seed, channel, k) * (i + 1))
        j = min(j, i)
        p[i], p[j] = p[j], p[i]
    return p


LATTICE_BITS = 21
LATTICE_MASK = (1 << LATTICE_BITS) - 1
LATTICE_MIN, LATTICE_MAX = -(1 << (LATTICE_BITS - 1)), (1 << (LATTICE_BITS - 1)) - 1


def pack(i, j, k):
    """The lattice index of (i, j, k): 21 bits of each as two's complement, i | j << 21 | k << 42."""
    for v in (i, j, k):
        if not isinstance(v, int) or v < LATTICE_MIN or v > LATTICE_MAX:
            raise ValueError(f"lattice coordinate outside [-2^20, 2^20): {v!r}")
    return (i & LATTICE_MASK) | (j & LATTICE_MASK) << LATTICE_BITS | (k & LATTICE_MASK) << (2 * LATTICE_BITS)


def unpack(packed):
    """The inverse of pack."""
    def signed(v):
        return v - (1 << LATTICE_BITS) if v > LATTICE_MAX else v
    return (signed(packed & LATTICE_MASK), signed((packed >> LATTICE_BITS) & LATTICE_MASK),
            signed((packed >> (2 * LATTICE_BITS)) & LATTICE_MASK))


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lattice_i(x):
    """floor(x) as a 64-bit integer (the lattice point left of x)."""
    return int(math.floor(x))


def N(seed, channel, x):
    """D24's gradient noise N(s, c, x): gradients g_i = 2 U(s, c, i) - 1, quintic fade, in [-1, 1], 0 at integers."""
    fl = math.floor(x)
    f = x - fl
    i = int(fl)

    def g(k):
        return U(seed, channel, k & MASK64) * 2.0 - 1.0
    a = g(i) * f
    b = g((i + 1) & MASK64) * (f - 1.0)
    return 2.0 * (a + (b - a) * _fade(f))


def W(seed, channel, x, octaves, mult):
    """The octave sum: octave k (k < octaves, octaves read as 1 to 16) weighs mult^k and samples
    N(s, c 1024 + k, x 2^k); the sum is divided by the sum of the weights (0 when that sum is 0)."""
    octaves = min(max(int(octaves), 1), 16)
    total = norm = 0.0
    w = f = 1.0
    for k in range(octaves):
        total += w * N(seed, (u64(channel) * 1024 + k) & MASK64, x * f)
        norm += w
        w *= mult
        f *= 2.0
    return total / norm if norm != 0.0 else 0.0


def fractal(seed, channel, x, octaves):
    """D24's fractal noise: the octave sum with weights 0.5^k."""
    return W(seed, channel, x, octaves, 0.5)


def V(seed, channel, x):
    """The value noise V(s, c, x): lattice values 2 U(s, c, k) - 1 with the cubic smoothstep between them."""
    fl = math.floor(x)
    f = x - fl
    i = int(fl)
    u = f * f * (3.0 - 2.0 * f)
    a = U(seed, channel, i & MASK64) * 2.0 - 1.0
    b = U(seed, channel, (i + 1) & MASK64) * 2.0 - 1.0
    return a + (b - a) * u


def perlin3(perm, x, y, z):
    """Improved Perlin noise (Perlin 2002) over a 256-entry permutation, clamped to [-1, 1]; NaN for a
    non-finite input."""
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        return float("nan")
    if len(perm) != 256 or sorted(perm) != list(range(256)):
        raise ValueError("perm is not a permutation of 0..255")

    def p(i):
        return perm[i & 255]
    fx, fy, fz = math.floor(x), math.floor(y), math.floor(z)
    xi, yi, zi = int(fx) & 255, int(fy) & 255, int(fz) & 255
    x, y, z = x - fx, y - fy, z - fz
    u, v, w = _fade(x), _fade(y), _fade(z)

    def grad(h, x, y, z):
        h &= 15
        a = x if h < 8 else y
        b = y if h < 4 else (x if h in (12, 14) else z)
        return (a if h & 1 == 0 else -a) + (b if h & 2 == 0 else -b)

    def lerp(t, a, b):
        return a + t * (b - a)
    a, b = p(xi) + yi, p(xi + 1) + yi
    aa, ab, ba, bb = p(a) + zi, p(a + 1) + zi, p(b) + zi, p(b + 1) + zi
    r = lerp(w,
             lerp(v, lerp(u, grad(p(aa), x, y, z), grad(p(ba), x - 1.0, y, z)),
                  lerp(u, grad(p(ab), x, y - 1.0, z), grad(p(bb), x - 1.0, y - 1.0, z))),
             lerp(v, lerp(u, grad(p(aa + 1), x, y, z - 1.0), grad(p(ba + 1), x - 1.0, y, z - 1.0)),
                  lerp(u, grad(p(ab + 1), x, y - 1.0, z - 1.0), grad(p(bb + 1), x - 1.0, y - 1.0, z - 1.0))))
    return min(max(r, -1.0), 1.0)


# --- section 3: seeds ---------------------------------------------------------------------------------------------

def crc32(data):
    """CRC-32 (IEEE 802.3, reflected, polynomial 0xEDB88320, as zlib's crc32) of a byte string."""
    c = 0xFFFFFFFF
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
    return c ^ 0xFFFFFFFF


def E(project, element_id, seed, purpose):
    """The element seed E: CRC-32 of the UTF-8 text "project:id:seed:purpose", where seed is the decimal of the
    element's @seed, or empty when it has none."""
    s = "" if seed is None else str(u64(seed))
    return crc32(f"{u64(project)}:{element_id}:{s}:{purpose}".encode("utf-8"))


# --- section 5: simulation streams ----------------------------------------------------------------------------

def S(element_seed, purpose, step, index):
    """The stream draw S(e, p, t, i) = U(e, p + t 2^32, i): purpose p and step t below 2^32, index i any
    64-bit integer."""
    for v in (purpose, step):
        if not isinstance(v, int) or v < 0 or v > MASK32:
            raise ValueError(f"purpose and step are integers in [0, 2^32): {v!r}")
    return U(element_seed, purpose + (step << 32), index)


def S_signed(element_seed, purpose, step, index):
    """2 S - 1, in [-1, 1)."""
    return S(element_seed, purpose, step, index) * 2.0 - 1.0


# --- appendix: the pre-1.8 draws of the reference engine, stated so that earlier documents reproduce --------

def legacy_sim_hash(seed, a, b):
    """crates/sr-sim/src/rng.rs hash(seed, a, b) = mix64(seed xor a 0x9E3779B97F4A7C15 xor b 0xC2B2AE3D27D4EB4F)."""
    return mix64(u64(seed) ^ ((u64(a) * PHI) & MASK64) ^ ((u64(b) * 0xC2B2AE3D27D4EB4F) & MASK64))


def legacy_sim_unit(seed, a, b):
    """The unit value of legacy_sim_hash: the top 53 bits over 2^53."""
    return (legacy_sim_hash(seed, a, b) >> 11) / TWO53


def fnv1a64(data):
    """FNV-1a, 64-bit, of a byte string."""
    h = 0xCBF29CE484222325
    for byte in data:
        h = ((h ^ byte) * 0x100000001B3) & MASK64
    return h


def legacy_id_seed(element_id):
    """crates/sr-eval/src/rng.rs hash_str: mix64 of the FNV-1a-64 of the id, the pre-1.8 element seed of
    simulations, agents, programs and clay."""
    return mix64(fnv1a64(element_id.encode("utf-8")))


def legacy_word_hash(words):
    """crates/sr-eval/src/rng.rs hash(words): h = 0x9E3779B97F4A7C15; for each word w, h = mix64(h xor
    mix64(w + 0x9E3779B97F4A7C15))."""
    h = PHI
    for w in words:
        h = mix64(h ^ mix64((u64(w) + PHI) & MASK64))
    return h


TABLE = [
    # (test, expression, expected): the numeric-test table of the SREP; expected values print from this module.
    ("Hash", "H(1, 2, 3)"), ("Hash", "H(42, 7, -5)"), ("Hash", "H(0, 0, 0)"),
    ("Hash", "H(14325487974692486532, 0, 0)"),
    ("Unit draw", "U(0, 0, 0)"), ("Unit draw", "U(7, 1, 0)"), ("Unit draw", "U(7, 2, 5)"),
    ("Normal draw", "G(1, 2, 3)"), ("Normal draw", "G(0, 0, 0)"), ("Normal draw", "G(14325487974692486532, 0, 0)"),
    ("Permutation", "P(5, 0, 10)"), ("Permutation", "P(1, 7, 8)"),
    ("Lattice index", "pack(-1, 2, 3)"), ("Lattice index", "pack(1048575, -1048576, 0)"),
    ("Lattice index", "unpack(0xC00005FFFFF)"),
    ("Element seed", "crc32(b'fontSize')"), ("Element seed", "E(1, '', 42, 'order')"),
    ("Element seed", "E(0, 'p1', None, 'stream')"), ("Element seed", "E(7, 'fx', 0, '7.0')"),
    ("Gradient noise", "N(0, 0, 0.5)"), ("Gradient noise", "N(42, 7, -1.3)"), ("Gradient noise", "N(0, 0, 2.0)"),
    ("Octave sum", "W(1, 0, 0.37, 4, 0.5)"), ("Octave sum", "W(42, 3, -2.6, 3, 0.5)"), ("Octave sum", "W(3, 1, 0.25, 2, 0.7)"),
    ("Value noise", "V(5, 2, 0.5)"), ("Value noise", "V(5, 2, -1.25)"),
    ("Perlin noise", "perlin3(P(1, 7, 256), 0.3, 0.7, 0.0)"), ("Perlin noise", "perlin3(P(1, 7, 256), 1.0, 2.0, -5.0)"),
    ("Stream draw", "S(E(0, 'p1', None, 'stream'), 11, 0, 4)"), ("Stream draw", "S(E(0, 'p1', None, 'stream'), 11, 3, 4)"),
    ("Stream draw", "S_signed(E(0, 'p1', None, 'stream'), 2, 0, 0)"),
    ("Legacy hash", "legacy_sim_hash(3, 4, 5)"), ("Legacy hash", "legacy_sim_unit(7, 0, 11)"),
    ("Legacy hash", "legacy_id_seed('')"), ("Legacy hash", "legacy_id_seed('p1')"),
    ("Legacy hash", "legacy_word_hash([1, 2, 3])"),
]


def _fmt(v):
    if isinstance(v, bool):
        return repr(v)
    if isinstance(v, int):
        return hex(v) if v > 0xFFFFFFFF else str(v)
    if isinstance(v, float):
        return repr(v)
    return repr(v)


def main():
    env = {k: v for k, v in globals().items() if not k.startswith("_")}
    print("| Test | Expression | Expected |")
    print("|---|---|---|")
    for name, expr in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, {'__builtins__': {}}, env))}` |")  # noqa: S307


if __name__ == "__main__":
    main()
