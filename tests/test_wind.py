"""Tests for the draft SREP "Add the wind field" (F4 of SREP 12) and its reference module."""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "wind_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-wind.md")


def _load():
    spec = importlib.util.spec_from_file_location("wind_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wd = _load()
rs = wd.streams()


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


# ------------------------------------------------------------------------------------------- the mean wind


def test_mean_velocity_from_speed_direction_and_speed_z():
    assert _close(wd.mean_velocity({"speed": 6.0, "direction": 0.0}, 0.0), (6.0, 0.0, 0.0))
    assert _close(wd.mean_velocity({"speed": 6.0, "direction": 90.0}, 0.0), (0.0, 6.0, 0.0))
    assert _close(wd.mean_velocity({"speed": 2.0, "direction": 180.0, "speedZ": 0.5}, 0.0), (-2.0, 0.0, 0.5))
    # animated attributes are functions of time
    assert _close(wd.mean_velocity({"speed": lambda t: 3.0 * t, "direction": 0.0}, 2.0), (6.0, 0.0, 0.0))
    # defaults: no wind at all
    assert wd.mean_velocity({}, 5.0) == (0.0, 0.0, 0.0)


def test_element_seed_uses_the_wind_purpose_of_the_random_streams_draft():
    assert wd.element_seed(7, "w1", 11) == rs.E(7, "w1", 11, "wind")
    assert wd.element_seed(7, "w1", None) == rs.E(7, "w1", None, "wind")
    assert wd.element_seed(7, "w1", 11) != wd.element_seed(8, "w1", 11)
    assert wd.example_seed() == wd.element_seed(7, "w1", 11)


# ------------------------------------------------------------------------------------------------- gusts


def test_gust_noise_is_the_octave_sum_of_d24_value_noise_on_the_gust_channels():
    e = wd.example_seed()
    # one octave is the value noise of the random-streams draft on channel 1024
    assert _close(wd.gust_noise(e, 0.37, 1), rs.V(e, wd.GUST_CHANNEL * wd.OCTAVE_STRIDE, 0.37))
    # two octaves weigh 1 and 1/2
    want = (rs.V(e, 1024, 0.37) + 0.5 * rs.V(e, 1025, 0.74)) / 1.5
    assert _close(wd.gust_noise(e, 0.37, 2), want)
    for x in (0.0, 0.37, 2.9, 11.5):
        assert -1.0 <= wd.gust_noise(e, x, 3) <= 1.0


def test_gust_factor_is_bounded_by_the_gustiness_and_reproduces_from_its_seed():
    spec = wd.example_wind()
    e = wd.example_seed()
    lo, hi = wd.gust_range(spec, e, 0.0, 60.0, 601)
    assert 1.0 - spec["gustiness"] <= lo < 1.0 < hi <= 1.0 + spec["gustiness"]
    assert wd.gust_factor(spec, e, 1.3) == wd.gust_factor(spec, wd.element_seed(7, "w1", 11), 1.3)
    assert wd.gust_factor(spec, e, 1.3) != wd.gust_factor(spec, wd.element_seed(8, "w1", 11), 1.3)
    assert wd.gust_factor(dict(spec, gustiness=0.0), e, 1.3) == 1.0
    # the period stretches time: the same factor at twice the time with twice the period
    assert _close(wd.gust_factor(dict(spec, gustPeriod=8.0), e, 2.6), wd.gust_factor(spec, e, 1.3))


def test_gust_bumps_cosine_and_iec():
    assert wd.bump("cosine", 0.0) == 0.0 and wd.bump("cosine", 1.0) == 0.0
    assert _close(wd.bump("cosine", 0.5), 1.0) and _close(wd.bump("cosine", 0.25), 0.5)
    assert wd.bump("cosine", -0.1) == 0.0 and wd.bump("cosine", 1.1) == 0.0
    # the IEC extreme operating gust shape, scaled so that its peak is 1
    peak = max(wd.bump("iec", i / 4000.0) for i in range(4001))
    assert abs(peak - 1.0) < 1e-6
    assert wd.bump("iec", 0.0) == 0.0 and abs(wd.bump("iec", 1.0)) < 1e-12
    assert wd.bump("iec", 0.15) < 0.0 and wd.bump("iec", 0.85) < 0.0   # the dips either side of the peak
    assert _close(wd.IEC_PEAK, 0.37 * max(-math.sin(3 * math.pi * t) * (1 - math.cos(2 * math.pi * t))
                                           for t in (i / 100000.0 for i in range(100001))), 1e-6)
    with pytest.raises(wd.WindError):
        wd.bump("square", 0.5)


def test_declared_gusts_add_along_their_direction():
    spec = wd.example_wind()
    # gust 1: cosine at 2 s for 3 s, peak 4 m/s along the wind's direction (30 degrees)
    assert _close(wd.declared_gusts(spec, 3.5), (4.0 * math.cos(math.radians(30)), 2.0, 0.0))
    assert wd.declared_gusts(spec, 6.0) == (0.0, 0.0, 0.0)
    assert wd.declared_gusts(spec, 1.0) == (0.0, 0.0, 0.0)
    # a gust with its own direction
    own = dict(spec, gusts=[{"at": 0.0, "duration": 2.0, "peak": 3.0, "direction": 90.0}])
    assert _close(wd.declared_gusts(own, 1.0), (0.0, 3.0, 0.0))
    # overlapping gusts sum; a negative peak is a lull
    two = dict(spec, gusts=[{"at": 0.0, "duration": 2.0, "peak": 3.0, "direction": 0.0},
                            {"at": 0.0, "duration": 2.0, "peak": -1.0, "direction": 0.0}])
    assert _close(wd.declared_gusts(two, 1.0), (2.0, 0.0, 0.0))


# --------------------------------------------------------------------------------------------- turbulence


def test_value3_interpolates_the_lattice_with_an_exact_gradient():
    e = wd.example_seed()
    c = 2 * wd.OCTAVE_STRIDE
    v, _g = wd.value3(e, c, 3.0, -2.0, 5.0)
    assert v == wd.lattice_value(e, c, 3, -2, 5)
    assert wd.lattice_value(e, c, 3, -2, 5) == 2.0 * rs.U(e, c, rs.pack(3, -2, 5)) - 1.0
    assert -1.0 <= v <= 1.0
    # the analytic gradient agrees with central differences
    x, y, z = 0.37, 0.53, 0.11
    _v, g = wd.value3(e, c, x, y, z)
    h = 1e-5
    num = ((wd.value3(e, c, x + h, y, z)[0] - wd.value3(e, c, x - h, y, z)[0]) / (2 * h),
           (wd.value3(e, c, x, y + h, z)[0] - wd.value3(e, c, x, y - h, z)[0]) / (2 * h),
           (wd.value3(e, c, x, y, z + h)[0] - wd.value3(e, c, x, y, z - h)[0]) / (2 * h))
    assert _close(g, num, 1e-6)
    # the gradient vanishes at lattice points (quintic fade)
    assert _close(wd.value3(e, c, 3.0, -2.0, 5.0)[1], (0.0, 0.0, 0.0))


def test_potential_is_three_octave_sums_on_the_potential_channels():
    e = wd.example_seed()
    q = (0.37, 0.53, 0.11)
    psi = wd.potential(e, q, 1)
    for a in range(3):
        c = (2 + a) * wd.OCTAVE_STRIDE
        assert _close(psi[a], wd.value3(e, c, *q)[0])
    psi3 = wd.potential(e, q, 3)
    want = sum(0.5 ** k * wd.value3(e, 2 * wd.OCTAVE_STRIDE + k, *(x * 2 ** k for x in q))[0] for k in range(3))
    assert _close(psi3[0], want / 1.75)
    # the gradient of the octave sum
    g = wd.potential_gradient(e, q, 3)
    h = 1e-5
    num = (wd.potential(e, (q[0] + h, q[1], q[2]), 3)[1] - wd.potential(e, (q[0] - h, q[1], q[2]), 3)[1]) / (2 * h)
    assert _close(g[1][0], num, 1e-6)
    with pytest.raises(wd.WindError):
        wd.potential(e, q, 0)
    with pytest.raises(wd.WindError):
        wd.potential(e, q, 9)


def test_turbulence_is_divergence_free_in_3d_and_in_the_2d_form():
    spec = wd.example_wind()
    e = wd.example_seed()
    for p, t in (((3.0, 2.0, 0.5), 1.0), ((-7.3, 4.1, 2.2), 0.0), ((0.2, 0.9, -1.3), 7.7)):
        v = wd.turbulence_at(spec, e, p, t)
        assert _norm(v) > 0.05
        assert abs(wd.divergence(spec, e, p, t)) < wd.DIVERGENCE_TOLERANCE
        v2 = wd.turbulence2_at(spec, e, p[:2], t)
        assert len(v2) == 2 and _norm(v2) > 0.0
        assert abs(wd.divergence2(spec, e, p[:2], t)) < wd.DIVERGENCE_TOLERANCE
    # a lone component field is not: the 2D form uses the third potential alone
    assert wd.turbulence2_at(spec, e, (3.0, 2.0), 1.0) != tuple(wd.turbulence_at(spec, e, (3.0, 2.0, 0.0), 1.0)[:2])


def test_turbulence_scales_with_its_amplitude_and_vanishes_when_off():
    spec = wd.example_wind()
    e = wd.example_seed()
    p, t = (3.0, 2.0, 0.5), 1.0
    one = wd.turbulence_at(dict(spec, turbulence=1.0), e, p, t)
    assert _close(wd.turbulence_at(dict(spec, turbulence=2.5), e, p, t), tuple(2.5 * x for x in one))
    assert wd.turbulence_at(dict(spec, turbulence=0.0), e, p, t) == (0.0, 0.0, 0.0)
    # the scale stretches space
    assert _close(wd.turbulence_at(dict(spec, speed=0.0, turbulenceScale=10.0), e, (6.0, 4.0, 1.0), 0.0),
                  wd.turbulence_at(dict(spec, speed=0.0, turbulenceScale=5.0), e, (3.0, 2.0, 0.5), 0.0))


def test_frozen_turbulence_rides_the_mean_wind_and_slides_in_time():
    frozen = dict(wd.example_wind(), turbulenceTime=1e12, speed=2.0, direction=0.0)
    e = wd.example_seed()
    # Taylor's hypothesis: the pattern at t is the pattern at 0 carried by the mean wind
    a = wd.turbulence_at(frozen, e, (3.0 + 2.0 * 1.5, 1.0, 0.0), 1.5)
    b = wd.turbulence_at(frozen, e, (3.0, 1.0, 0.0), 0.0)
    assert _close(a, b, 1e-6)
    # with a finite turbulenceTime the pattern also changes in place
    live = dict(frozen, turbulenceTime=4.0)
    assert not _close(wd.turbulence_at(live, e, (3.0 + 2.0 * 1.5, 1.0, 0.0), 1.5), b, 1e-6)
    # the slide is one lattice cell per turbulenceTime along the third coordinate
    q0 = wd.lattice_point(dict(live, speed=0.0), (3.0, 1.0, 0.0), 4.0)
    assert _close(q0, (0.6, 0.2, 1.0))


def test_displacement_is_the_trapezoid_over_the_frames():
    spec = wd.example_wind()
    d = wd.displacement(spec, 2.5, 24)
    assert _close(d, (6.0 * 2.5 * math.cos(math.radians(30)), 6.0 * 2.5 * 0.5, 0.0))
    ramp = dict(spec, speed=lambda t: 4.0 * t, direction=0.0)
    assert _close(wd.displacement(ramp, 2.0, 24), (8.0, 0.0, 0.0), 1e-9)
    assert wd.displacement(spec, 0.0, 24) == (0.0, 0.0, 0.0)
    # a time between frames adds the partial step
    assert _close(wd.displacement(dict(spec, direction=0.0), 1.0 / 48.0, 24), (6.0 / 48.0, 0.0, 0.0))


def test_wind_at_sums_the_gusting_mean_the_declared_gusts_and_the_turbulence():
    doc = wd.example_document()
    spec = wd.example_wind()
    e = wd.example_seed()
    p, t = (3.0, 2.0, 0.0), 3.5
    g = wd.gust_factor(spec, e, t)
    m = wd.mean_velocity(spec, t)
    want = tuple(g * m[i] + wd.declared_gusts(spec, t)[i] + wd.turbulence_at(spec, e, p, t)[i] for i in range(3))
    assert _close(wd.wind_at(doc, "w1", p, t), want)
    # a 2D point reads the 2D turbulence form
    w2 = wd.wind_at(doc, "w1", (3.0, 2.0), t)
    t2 = wd.turbulence2_at(spec, e, (3.0, 2.0), t)
    assert _close(w2, (g * m[0] + wd.declared_gusts(spec, t)[0] + t2[0], g * m[1] + wd.declared_gusts(spec, t)[1] + t2[1]))
    with pytest.raises(wd.WindError):
        wd.wind_at(doc, "nope", p, t)


def test_the_wind_is_absent_outside_its_window():
    doc = wd.example_document()
    doc["physics"]["winds"][0]["start"] = 1.0
    doc["physics"]["winds"][0]["end"] = 15.0
    assert wd.wind_at(doc, "w1", (3.0, 2.0, 0.0), 0.5) == (0.0, 0.0, 0.0)
    assert wd.wind_at(doc, "w1", (3.0, 2.0, 0.0), 20.0) == (0.0, 0.0, 0.0)
    assert wd.wind_at(doc, "w1", (3.0, 2.0, 0.0), 1.0) != (0.0, 0.0, 0.0)
    assert wd.wind_at(doc, "w1", (3.0, 2.0, 0.0), 15.0) != (0.0, 0.0, 0.0)


# ------------------------------------------------------------------------------------------------ readers


def test_relaxation_toward_the_wind_and_the_settling_time():
    assert wd.relaxation((6.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.5) == (10.0, 0.0, 0.0)
    assert wd.relaxation((6.0, 0.0, 0.0), (6.0, 0.0, 0.0), 0.5) == (0.0, 0.0, 0.0)
    assert _close(wd.settle_fraction(1.0), 1.0 - math.exp(-1.0))
    # a particle from rest in a steady 6 m/s wind reaches 63.2 % after one response time
    assert _close(wd.settled_speed(6.0, 0.5, 0.5, 240), 6.0 * (1.0 - math.exp(-1.0)), 1e-6)
    assert _close(wd.settled_speed(6.0, 0.5, 5.0, 240), 6.0 * (1.0 - math.exp(-10.0)), 1e-6)
    with pytest.raises(wd.WindError):
        wd.relaxation((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0)


def test_to_pixels_flips_y_and_scales():
    assert wd.to_pixels((1.0, 2.0), 100.0) == (100.0, -200.0)
    assert wd.to_pixels((1.0, 2.0, 0.5), 50.0) == (50.0, -100.0)


def test_turbulence_rms_is_deterministic_and_the_octave_weights_keep_it_near_one_octave():
    e = wd.example_seed()
    r1 = wd.turbulence_rms(e, 1, 8)
    r3 = wd.turbulence_rms(e, 3, 8)
    assert r1 == wd.turbulence_rms(e, 1, 8)
    assert 0.2 < r1 < 3.0
    # octave k weighs 1/2^k in the potential and its gradient grows by 2^k, so every octave adds about the
    # same speed and the division by the summed weights keeps the RMS near the one-octave value
    assert 0.5 < r3 / r1 < 2.0


# ---------------------------------------------------------------------------------------------- validation


def test_the_example_document_is_valid_and_the_bad_one_lists_every_rule():
    assert wd.validate_document(wd.example_document()) == []
    assert wd.validate_document(wd.bad_document()) == ["WD1", "WD2", "WD3", "WD4", "WD5"]


def test_validation_rules_one_at_a_time():
    def with_wind(**kw):
        doc = wd.example_document()
        doc["physics"]["winds"][0].update(kw)
        return doc

    for kw in (dict(speed=-1.0), dict(gustiness=1.5), dict(gustPeriod=0.0), dict(gustOctaves=0), dict(gustOctaves=9),
               dict(turbulence=-0.1), dict(turbulenceScale=0.0), dict(turbulenceOctaves=0), dict(turbulenceOctaves=9),
               dict(turbulenceTime=0.0), dict(response=0.0), dict(gustOctaves=2.5)):
        assert wd.validate_document(with_wind(**kw)) == ["WD1"], kw
    for gust in ({"at": -1.0, "duration": 1.0}, {"at": 0.0, "duration": 0.0}, {"at": 0.0, "duration": 1.0, "shape": "square"}):
        assert wd.validate_document(with_wind(gusts=[gust])) == ["WD2"], gust
    doc = wd.example_document()
    doc["readers"][0]["forceFields"] = ["w1", "ghost"]
    assert wd.validate_document(doc) == ["WD3"]
    doc = wd.example_document()
    doc["readers"][0]["forceFields"] = ["w1", "f1"]        # a 1.7 force field beside the wind is fine
    assert wd.validate_document(doc) == []
    assert wd.validate_document(with_wind(start=5.0, end=5.0)) == ["WD4"]
    assert wd.validate_document(with_wind(start=5.0, end=6.0)) == []
    assert wd.validate_document(with_wind(affects="clouds")) == ["WD5"]
    # animated values are checked at the window's start
    assert wd.validate_document(with_wind(speed=lambda t: -1.0)) == ["WD1"]
    assert wd.validate_document(with_wind(speed=lambda t: 1.0)) == []
    low = wd.example_document()
    low["version"] = "1.7"
    assert wd.validate_document(low) == ["V17"]
    low["physics"]["winds"] = []
    low["readers"][0]["forceFields"] = ["f1"]
    assert wd.validate_document(low) == []


def test_constants():
    assert wd.PURPOSE == "wind"
    assert wd.GUST_CHANNEL == 1 and wd.POTENTIAL_CHANNELS == (2, 3, 4) and wd.OCTAVE_STRIDE == 1024
    assert wd.MAX_OCTAVES == 8 and wd.GUST_SHAPES == ("cosine", "iec") and wd.AFFECTS == ("all", "bodies", "particles")
    assert wd.DEFAULTS["gustPeriod"] == 4.0 and wd.DEFAULTS["turbulenceScale"] == 5.0
    assert wd.DEFAULTS["turbulenceTime"] == 4.0 and wd.DEFAULTS["response"] == 0.5
    assert wd.DEFAULTS["gustOctaves"] == 3 and wd.DEFAULTS["turbulenceOctaves"] == 3
    assert wd.DIVERGENCE_TOLERANCE == 1e-6


# ------------------------------------------------------------------------------------------------ the draft


@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    for heading in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics", "## Rationale",
                    "## Rejected alternatives", "## Backwards compatibility", "## Engine impact", "## Conformance",
                    "### Numeric tests", "### Kit cases", "## Open issues", "## References", "## History"):
        assert heading in draft, heading
    assert "SREP:            0" in draft
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    for word in ("SR-101", "SREP 12", "SREP 14", "`wind`", "`gust`", "speed", "direction", "speedZ", "gustiness",
                 "gustPeriod", "gustOctaves", "turbulence", "turbulenceScale", "turbulenceOctaves", "turbulenceTime",
                 "response", "forceFields", "affects", "`at`", "duration", "peak", "shape", "cosine", "iec",
                 "WD1", "WD2", "WD3", "WD4", "WD5", "V17", "wind_reference.py", "random-streams", "D24",
                 "pack(i, j, k)", "curl", "divergence-free", "Taylor", "Bridson", "IEC 61400-1", "earth.nullschool",
                 "Windy", "type=\"wind\"", "fields.rs", "frozen", "quintic", "relaxation", "clouds", "snow",
                 "wildfire", "vegetation", "ocean"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 24


def test_the_table_is_what_the_module_prints(draft):
    assert len(wd.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(wd.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = wd.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or wd._same(got, want), f"{name}: {got!r} != {want!r}"
