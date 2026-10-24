"""Draft SREP "Define the random streams derived from the D24 hash" (srep/srep-0000-random-streams.md, the F1
building block of SREP 12): the reference implementation conformance/tools/random_streams_reference.py, its golden
values, and the agreement between the SREP's numeric-test table and that implementation.

The golden values come from three independent statements: SREP 26's hash table (section Conformance), the
reference engine's own unit tests of its D24 module (crates/sr-vector/src/d24.rs, computed there "by an independent
reference implementation"), and this module, written from the SREP text. Where the SREP defines a draw the engine
does not have yet (the simulation streams), only the SREP's table and this module can agree, and the test says so.
"""
import ast
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT = os.path.join(ROOT, "srep", "srep-0000-random-streams.md")
MODULE = os.path.join(ROOT, "conformance", "tools", "random_streams_reference.py")


def _load():
    spec = importlib.util.spec_from_file_location("random_streams_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load()

MASK = (1 << 64) - 1


# --- the lattice hash and the unit draw (D24, SREP 26) --------------------------------------------------------

def test_splitmix64_matches_the_engine():
    assert rs.splitmix64(0) == 0xE220A8397B1DCDAF
    assert rs.splitmix64(1) == 0x910A2DEC89025CC1


@pytest.mark.parametrize("args, expected", [
    ((1, 2, 3), 0xD62A7F6E291FEF64),                       # crates/sr-vector/src/d24.rs
    ((42, 7, -5), 0x2BF4C61D835A19BB),                     # a negative index enters as two's complement
    ((0, 0, 0), 0x238275BC38FCBE91),                       # SREP 26, Conformance, hash tests
    ((7, 0, 0), 0xD3C8201D52FD2DF4),
    ((7, 1, 0), 0x7A099DAD0DD482F0),
    ((14325487974692486532, 0, 0), 0x0),
])
def test_lattice_hash_golden_values(args, expected):
    assert rs.H(*args) == expected


@pytest.mark.parametrize("args, expected", [
    ((0, 0, 0), 0.13870941014555427),
    ((7, 0, 0), 0.8272724219886994),
    ((7, 1, 0), 0.47670922732307197),
    ((14325487974692486532, 0, 0), 0.0),
    ((7, 2, 0), 0.5407366383275906),                       # SREP 26, pointRandom
    ((7, 2, 5), 0.356758657594873),
])
def test_unit_draw_golden_values(args, expected):
    assert rs.U(*args) == expected


def test_unit_draw_is_the_top_53_bits():
    for s, c, k in [(0, 0, 0), (1, 2, 3), (42, 7, -5), (2**64 - 1, 2**64 - 1, 2**64 - 1)]:
        h = rs.H(s, c, k)
        assert rs.U(s, c, k) == (h >> 11) / 2**53
        assert 0.0 <= rs.U(s, c, k) < 1.0


def test_hash_accepts_the_whole_64_bit_range_and_nothing_else():
    assert rs.H(2**64 - 1, 0, 0) == rs.H(-1, 0, 0)          # two's complement
    with pytest.raises(ValueError):
        rs.H(2**64, 0, 0)
    with pytest.raises(ValueError):
        rs.H(0, 0, -(2**63) - 1)


# --- derived draws (section 2 of the SREP) -----------------------------------------------------------------

def test_normal_draw_golden_value_and_distribution():
    assert abs(rs.G(1, 2, 3) - 0.3180452816872121) < 1e-12   # crates/sr-vector/src/d24.rs
    xs = [rs.G(9, 1, k) for k in range(20000)]
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    assert abs(mean) < 0.02 and abs(var - 1.0) < 0.03
    assert all(math.isfinite(x) for x in xs)                 # u1 never reaches 0, so log(u1) is finite


def test_permutation_golden_value_and_validity():
    assert rs.P(5, 0, 10) == [9, 8, 3, 7, 2, 6, 5, 0, 1, 4]  # crates/sr-vector/src/d24.rs
    for n in (0, 1, 2, 17, 256):
        p = rs.P(1, 7, n)
        assert sorted(p) == list(range(n))
    assert rs.P(3, 0, 256) != rs.P(3, 1, 256)


def test_pack_golden_value_and_round_trip():
    assert rs.pack(-1, 2, 3) == 0xC00005FFFFF                 # crates/sr-vector/src/d24.rs
    assert rs.pack(0, 0, 0) == 0
    assert rs.pack(2**20 - 1, -(2**20), 5) == rs.pack(2**20 - 1, -(2**20), 5)
    assert rs.unpack(rs.pack(-1, 2, 3)) == (-1, 2, 3)
    assert rs.unpack(rs.pack(2**20 - 1, -(2**20), -7)) == (2**20 - 1, -(2**20), -7)
    with pytest.raises(ValueError):
        rs.pack(2**20, 0, 0)                                  # outside the 21-bit two's-complement range
    with pytest.raises(ValueError):
        rs.pack(0, -(2**20) - 1, 0)


def test_crc32_and_element_seed_golden_values():
    assert rs.crc32(b"fontSize") == 1178744372               # zlib's crc32
    assert rs.crc32(b"") == 0
    assert rs.E(1, "", 42, "order") == 3996963903            # crates/sr-vector/src/d24.rs
    assert rs.E(1, "", None, "order") == rs.crc32(b"1:::order")   # empty id and absent seed keep their colons
    assert rs.E(7, "a", 0, "p") == rs.crc32(b"7:a:0:p")       # an explicit 0 is "0", an absent seed is ""
    assert rs.E(7, "a", 0, "p") != rs.E(7, "a", None, "p")


def test_perlin3_golden_value_and_bounds():
    perm = rs.P(1, 7, 256)
    assert abs(rs.perlin3(perm, 0.3, 0.7, 0.0) - 0.28006378512) < 1e-9   # crates/sr-vector/src/d24.rs
    for x in (0.0, 1.0, -3.0, 17.0):
        assert rs.perlin3(perm, x, 2.0, -5.0) == 0.0          # zero at lattice points
    assert all(-1.0 <= rs.perlin3(perm, i * 0.37, i * 0.11, -i * 0.05) <= 1.0 for i in range(500))
    assert math.isnan(rs.perlin3(perm, float("inf"), 0.0, 0.0))


def test_gradient_noise_golden_values():
    close = lambda a, b: abs(a - b) < 1e-12                   # noqa: E731
    assert close(rs.N(0, 0, 0.5), -0.554802728864675)         # crates/sr-vector/src/d24.rs
    assert close(rs.N(1, 0, 0.25), -0.2591138999211539)
    assert close(rs.N(42, 7, -1.3), -0.22195948101587748)
    assert close(rs.N(12345, 3, 99.75), 0.052042264166522356)
    assert close(rs.N(7, 1024, 3.14159), 0.14007526307765447)
    assert rs.N(0, 0, 2.0) == 0.0
    assert close(rs.W(1, 0, 0.37, 1, 0.5), -0.29073717200676585)
    assert close(rs.W(1, 0, 0.37, 4, 0.5), -0.11429312869138876)
    assert close(rs.W(42, 3, -2.6, 3, 0.5), 0.13784387603697973)


def test_octave_sum_is_bounded_in_octaves():
    assert rs.W(1, 0, 0.37, 0, 0.5) == rs.W(1, 0, 0.37, 1, 0.5)     # fewer than one octave reads as one
    assert rs.W(1, 0, 0.37, 40, 0.5) == rs.W(1, 0, 0.37, 16, 0.5)   # more than sixteen read as sixteen
    assert rs.W(1, 0, 0.37, 3, 0.0) == rs.W(1, 0, 0.37, 1, 0.0)     # a zero multiplier leaves the first octave


def test_value_noise_is_the_smoothstep_of_lattice_draws():
    s, c = 5, 2
    for k in (-2, 0, 3):
        assert rs.V(s, c, float(k)) == rs.U(s, c, k) * 2.0 - 1.0
    mid = rs.V(s, c, 0.5)
    assert mid == (rs.U(s, c, 0) * 2 - 1) * 0.5 + (rs.U(s, c, 1) * 2 - 1) * 0.5
    assert all(-1.0 <= rs.V(s, c, i * 0.013) <= 1.0 for i in range(1000))


# --- simulation streams (section 5 of the SREP) ------------------------------------------------------------

def test_stream_address_is_a_function_of_its_four_parts():
    s = rs.E(0, "e", None, "stream")
    a = rs.S(s, 11, 0, 4)
    assert a == rs.S(s, 11, 0, 4)
    assert a != rs.S(s, 12, 0, 4) and a != rs.S(s, 11, 1, 4) and a != rs.S(s, 11, 0, 5)
    assert a == rs.U(s, 11 + (0 << 32), 4)                    # purpose in the low 32 bits, step above them
    assert rs.S(s, 11, 3, 4) == rs.U(s, 11 + (3 << 32), 4)
    with pytest.raises(ValueError):
        rs.S(s, 2**32, 0, 0)
    with pytest.raises(ValueError):
        rs.S(s, 0, 2**32, 0)
    with pytest.raises(ValueError):
        rs.S(s, -1, 0, 0)


def test_signed_stream_draw():
    s = 9
    assert rs.S_signed(s, 1, 0, 2) == rs.S(s, 1, 0, 2) * 2.0 - 1.0
    assert -1.0 <= rs.S_signed(s, 1, 0, 2) < 1.0


def test_legacy_simulation_hash_is_stated_exactly():
    # The pre-1.8 mixer of the reference engine (crates/sr-sim/src/rng.rs), kept for earlier documents.
    x = 3 ^ ((4 * 0x9E3779B97F4A7C15) & MASK) ^ ((5 * 0xC2B2AE3D27D4EB4F) & MASK)
    assert rs.legacy_sim_hash(3, 4, 5) == rs.mix64(x)
    assert rs.legacy_sim_unit(3, 4, 5) == (rs.legacy_sim_hash(3, 4, 5) >> 11) / 2**53
    assert rs.fnv1a64(b"") == 0xCBF29CE484222325
    assert rs.legacy_id_seed("") == rs.mix64(0xCBF29CE484222325)


# --- the SREP's own numeric table agrees with the reference implementation ---------------------------------

def _numeric_rows():
    text = open(DRAFT, encoding="utf-8").read()
    body = text.split("### Numeric tests", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in body.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", line)
        if m and m.group(1) not in ("Test", "---"):
            rows.append((m.group(1), m.group(2), m.group(3)))
    return rows


def test_the_draft_states_numeric_tests():
    rows = _numeric_rows()
    assert len(rows) >= 20
    assert {r[0] for r in rows} >= {"Hash", "Unit draw", "Normal draw", "Permutation", "Lattice index",
                                    "Element seed", "Gradient noise", "Octave sum", "Value noise",
                                    "Perlin noise", "Stream draw"}


@pytest.mark.parametrize("name, expr, expected", _numeric_rows() if os.path.exists(DRAFT) else [])
def test_the_draft_table_matches_the_reference(name, expr, expected):
    env = {k: getattr(rs, k) for k in dir(rs) if not k.startswith("_")}
    got = eval(expr, {"__builtins__": {}}, env)  # noqa: S307 - expressions copied from the SREP, no builtins
    want = ast.literal_eval(expected)
    if isinstance(want, float):
        assert abs(got - want) <= 1e-12 * max(1.0, abs(want)), (name, got, want)
    else:
        assert got == want, (name, got, want)
