"""Tests for the draft SREP "Add a weather state" (A5 of SREP 12) and its reference module."""
from __future__ import annotations

import importlib.util
import math
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "weather_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-weather.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wx = _load(MODULE, "weather_reference")
rs = wx.streams()


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


E = wx.example_seed()


# ----------------------------------------------------------------------------------------- precipitation


def test_the_snow_fraction_follows_the_temperature():
    assert wx.snow_fraction(270.0) == 1.0 and wx.snow_fraction(274.15) == 1.0
    assert wx.snow_fraction(277.15) == 0.0 and wx.snow_fraction(290.0) == 0.0
    assert _close(wx.snow_fraction(275.65), 0.5)
    assert wx.snow_fraction(274.9) > wx.snow_fraction(276.4) > 0.0


def test_the_rain_rate_splits_into_rain_and_snow():
    spec = dict(wx.DEFAULTS, precipitation=0.4, rainMax=50.0, temperature=290.0)
    assert _close(wx.rain_rate(spec, 0.0), 20.0)
    assert _close(wx.split_rate(spec, 0.0), (20.0, 0.0))
    cold = dict(spec, temperature=270.0)
    assert _close(wx.split_rate(cold, 0.0), (0.0, 20.0))
    mixed = dict(spec, temperature=275.65)
    assert _close(wx.split_rate(mixed, 0.0), (10.0, 10.0))
    # animated attributes are functions of time
    animated = dict(spec, precipitation=lambda t: 0.0 if t < 10.0 else 1.0)
    assert wx.rain_rate(animated, 5.0) == 0.0 and _close(wx.rain_rate(animated, 12.0), 50.0)


def test_marshall_palmer_and_the_fall_speed():
    n0, lam = wx.marshall_palmer(5.0)
    assert n0 == 8000.0 and _close(lam, 4.1 * 5.0 ** -0.21)
    assert _close(wx.drop_density(5.0, 1.0), 8000.0 * math.exp(-lam))
    assert wx.drop_density(5.0, 0.5) > wx.drop_density(5.0, 2.0)
    assert _close(wx.rain_speed(1.0), 9.65 - 10.3 * math.exp(-0.6))
    assert wx.rain_speed(0.0) == 0.0 and wx.rain_speed(6.0) < 9.65
    assert wx.rain_speed(3.0) > wx.rain_speed(1.0)


@pytest.mark.parametrize("rate", (1.0, 5.0, 20.0))
def test_the_drop_spectrum_carries_its_own_rain_rate(rate):
    implied = wx.implied_rain_rate(rate)
    assert abs(implied - rate) / rate < 0.25, implied


def test_the_fluxes_grow_with_the_rate_and_snow_has_its_own_spectrum():
    assert wx.drop_flux(0.0) == 0.0
    assert 0.0 < wx.drop_flux(1.0) < wx.drop_flux(5.0) < wx.drop_flux(20.0)
    n0, lam = wx.gunn_marshall(2.0)
    assert _close(n0, 3800.0 * 2.0 ** -0.87) and _close(lam, 2.55 * 2.0 ** -0.48)
    assert wx.flake_flux(0.0) == 0.0
    assert wx.flake_flux(1.0) > wx.flake_flux(5.0) > 0.0                           # fewer, larger flakes as it snows harder
    assert wx.implied_snow_rate(1.0) < wx.implied_snow_rate(5.0)
    for rate in (1.0, 2.0, 5.0):
        assert abs(wx.implied_snow_rate(rate) - rate) / rate < 0.25, rate           # the spectrum carries its rate at 1 m/s
    spec = dict(wx.DEFAULTS, precipitation=0.2, rainMax=50.0, temperature=275.65)
    fluxes = wx.particle_fluxes(spec, 0.0)
    assert _close(fluxes["rain"], wx.drop_flux(5.0)) and _close(fluxes["snow"], wx.flake_flux(5.0))


def test_visibility_gives_the_koschmieder_extinction():
    assert _close(wx.extinction(1000.0), 3.912 / 1000.0)
    assert _close(wx.extinction_at(dict(wx.DEFAULTS, visibility=200.0), 0.0), 3.912 / 200.0)
    with pytest.raises(wx.WeatherError):
        wx.extinction(0.0)


# ------------------------------------------------------------------------------------------- surfaces


def test_wet_albedo_darkens_monotonically_and_keeps_the_order():
    r_e = wx.diffuse_fresnel(wx.WATER_IOR)
    assert 0.05 < r_e < 0.08
    r_i = wx.internal_reflectance(wx.WATER_IOR)
    assert _close(r_i, 1.0 - (1.0 - r_e) / wx.WATER_IOR ** 2)
    for a in (0.1, 0.3, 0.5, 0.8, 1.0):
        last = a
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            v = wx.wet_albedo(a, w)
            assert v <= last + 1e-12 and 0.0 <= v <= a
            last = v
    assert wx.wet_albedo(0.5, 0.0) == 0.5
    assert wx.wet_albedo(0.0, 1.0) == 0.0
    assert wx.wet_albedo(0.3, 1.0) < wx.wet_albedo(0.5, 1.0) < wx.wet_albedo(0.8, 1.0)
    assert _close(wx.wet_albedo(0.5, 1.0), (1.0 - r_e) * (1.0 - r_i) * 0.5 / (1.0 - 0.5 * r_i))
    assert wx.wet_albedo(0.5, 1.0, metallic=1.0) == 0.5                       # metals do not soak
    assert _close(wx.wet_albedo((0.5, 0.2, 0.1), 1.0), (wx.wet_albedo(0.5, 1.0), wx.wet_albedo(0.2, 1.0), wx.wet_albedo(0.1, 1.0)))


def test_wet_roughness_never_rises():
    for r in (0.02, 0.05, 0.3, 0.9):
        last = r
        for w in (0.0, 0.5, 1.0):
            v = wx.wet_roughness(r, w)
            assert v <= last + 1e-12
            last = v
    assert _close(wx.wet_roughness(0.9, 1.0), wx.WATER_ROUGHNESS)
    assert wx.wet_roughness(0.02, 1.0) == 0.02


def test_snow_cover_and_the_snowy_look():
    assert wx.snow_cover(0.0, wx.DEFAULTS) == 0.0
    assert _close(wx.snow_cover(wx.DEFAULTS["snowScale"], wx.DEFAULTS), 1.0 - math.exp(-1.0))
    assert wx.snow_cover(1.0, wx.DEFAULTS) > 0.99
    assert _close(wx.snowy_albedo(0.2, 1.0, 1.0), wx.SNOW_ALBEDO)
    assert wx.snowy_albedo(0.2, 1.0, 0.0) == 0.2 and wx.snowy_albedo(0.2, 1.0, -1.0) == 0.2   # walls and ceilings
    assert _close(wx.snowy_albedo(0.2, 0.5, 1.0), 0.5 * 0.2 + 0.5 * wx.SNOW_ALBEDO)
    assert _close(wx.snowy_roughness(0.2, 1.0, 1.0), wx.SNOW_ROUGHNESS)
    look = wx.surface_look({"baseColor": (0.5, 0.5, 0.5), "roughness": 0.6, "metallic": 0.0}, {"wetness": 1.0, "snow": 0.0}, 1.0)
    assert look["baseColor"][0] < 0.5 and look["roughness"] < 0.6
    snowy = wx.surface_look({"baseColor": (0.5, 0.5, 0.5), "roughness": 0.6, "metallic": 0.0}, {"wetness": 0.0, "snow": 1.0}, 1.0)
    assert _close(snowy["baseColor"], (wx.SNOW_ALBEDO,) * 3) and _close(snowy["roughness"], wx.SNOW_ROUGHNESS)


def test_the_surface_state_saturates_like_the_analytic_solution():
    spec = dict(wx.DEFAULTS, precipitation=0.2, rainMax=50.0, temperature=290.0, humidity=0.5, wetTime=300.0,
                dryTime=1800.0, step=1.0)
    a = 1.0 / 300.0                                                                # 10 mm/h is the reference rate
    b = 0.5 / 1800.0
    for t in (60.0, 300.0, 1200.0):
        state = wx.surface_state(spec, t)
        exact = a / (a + b) * (1.0 - math.exp(-(a + b) * t))
        assert abs(state["wetness"] - exact) < 0.01, (t, state, exact)
        assert state["snow"] == 0.0 and state["steps"] == round(t)
    assert wx.surface_state(spec, 0.0) == {"wetness": 0.0, "snow": 0.0, "steps": 0}
    # it dries when the rain stops
    stopping = dict(spec, precipitation=lambda t: 0.2 if t < 600.0 else 0.0)
    assert wx.surface_state(stopping, 3600.0)["wetness"] < wx.surface_state(stopping, 600.0)["wetness"]
    assert wx.surface_state(stopping, 36000.0)["wetness"] < 1e-3


def test_snow_accumulates_in_the_cold_and_melts_by_degree_days():
    cold = dict(wx.DEFAULTS, precipitation=0.2, rainMax=50.0, temperature=270.0, step=1.0, meltRate=1e-7)
    state = wx.surface_state(cold, 3600.0)
    assert state["wetness"] == 0.0
    assert _close(state["snow"], 10.0 / 3.6e6 / wx.FRESH_SNOW_DENSITY * 3600.0, 1e-9)        # 10 mm/h for an hour
    warm = dict(cold, temperature=lambda t: 270.0 if t < 3600.0 else 283.15)
    later = wx.surface_state(warm, 7200.0)
    assert 0.0 < later["snow"] < state["snow"]
    assert _close(later["snow"], state["snow"] - 1e-7 * 10.0 * 3600.0, 1e-9)
    assert wx.surface_state(dict(warm, meltRate=1e-3), 7200.0)["snow"] == 0.0


def test_steps_are_bounded_and_the_step_positive():
    assert wx.steps_for(2.5, 1.0, 100) == 2 and wx.steps_for(1e9, 1.0, 100) == 100
    with pytest.raises(wx.WeatherError):
        wx.steps_for(1.0, 0.0, 10)


# ------------------------------------------------------------------------------------------- lightning


def test_strikes_follow_the_integrated_rate():
    spec = dict(wx.DEFAULTS, lightning=0.5, step=1.0, maxStrikes=1000)
    none = wx.strikes(dict(spec, lightning=0.0), E, 1000.0)
    assert none == []
    hits = wx.strikes(spec, E, 400.0)
    times = [h["time"] for h in hits]
    assert times == sorted(times) and all(0.0 <= t_ <= 400.0 for t_ in times)
    assert 120 <= len(hits) <= 280, len(hits)                                      # 200 expected
    assert all(0.0 <= h["x"] <= 1.0 for h in hits)
    assert wx.strikes(spec, E, 400.0) == hits
    assert wx.strikes(spec, E, 100.0) == [h for h in hits if h["time"] <= 100.0]
    # the first gap is the unit exponential of the first draw scaled by the rate
    u = rs.S(E, wx.STRIKE_PURPOSE, 1, 0)
    assert _close(times[0], -math.log(1.0 - u) / 0.5, 1e-9)
    # a storm that starts later strikes later
    late = dict(spec, lightning=lambda t: 0.0 if t < 200.0 else 0.5)
    assert all(h["time"] >= 200.0 for h in wx.strikes(late, E, 400.0))
    assert len(wx.strikes(dict(spec, maxStrikes=5), E, 400.0)) == 5


def test_a_bolt_is_a_function_of_its_seed_and_index():
    spec = dict(wx.DEFAULTS, lightningGrid=24)
    a = wx.bolt(E, 1, 0.5, spec)
    b = wx.bolt(E, 1, 0.5, spec)
    assert a == b
    other = wx.bolt(rs.E(7, "wx", 99, "weather"), 1, 0.5, spec)
    assert other["cells"] != a["cells"]
    assert wx.bolt(E, 2, 0.5, spec)["cells"] != a["cells"]


def test_a_bolt_is_connected_and_reaches_the_ground():
    spec = dict(wx.DEFAULTS, lightningGrid=24)
    bolt = wx.bolt(E, 1, 0.5, spec)
    n = spec["lightningGrid"]
    cells = bolt["cells"]
    assert cells[0] == (round(0.5 * (n - 1)), 0)
    assert bolt["hit"][1] == n - 1
    parents = bolt["parent"]
    for cell in cells[1:]:
        p = parents[cell]
        assert p in parents or p == cells[0]
        assert max(abs(cell[0] - p[0]), abs(cell[1] - p[1])) == 1                  # eight-connected
    assert len(set(cells)) == len(cells)
    assert all(0 <= i < n and 0 <= j < n for i, j in cells)
    main = bolt["main"]
    assert main[0] == cells[0] and main[-1] == bolt["hit"]
    assert set(main) <= set(cells)
    brightness = bolt["brightness"]
    assert all(brightness[c] == 1.0 for c in main)
    assert all(0.0 < brightness[c] <= 1.0 for c in cells)
    assert any(brightness[c] < 1.0 for c in cells)                                 # it branches
    assert len(cells) <= wx.max_growth(n)


def test_the_potential_prefers_the_ground():
    channel = [(5, 0), (5, 1)]
    ground = [(i, 11) for i in range(11)]                                          # centred under the channel
    low = wx.potential((5, 2), channel, ground, 1.0)
    high = wx.potential((5, 9), channel, ground, 1.0)
    assert high > low
    assert wx.potential((5, 1), channel, ground, 1.0) < wx.potential((6, 1), channel, ground, 1.0)
    weights = wx.growth_weights([(5, 2), (4, 1), (6, 1)], channel, ground, 1.0, 2.0)
    assert _close(sum(weights), 1.0) and weights[0] > weights[1] and _close(weights[1], weights[2])
    assert wx.pick([0.2, 0.3, 0.5], 0.1) == 0 and wx.pick([0.2, 0.3, 0.5], 0.45) == 1 and wx.pick([0.2, 0.3, 0.5], 0.999) == 2


def test_the_flash_decays_after_each_strike():
    spec = dict(wx.DEFAULTS, flashDuration=0.2)
    hits = [{"time": 1.0, "x": 0.3}, {"time": 2.0, "x": 0.6}]
    assert wx.flash(spec, 0.5, hits) == 0.0
    assert _close(wx.flash(spec, 1.0, hits), 1.0)
    assert _close(wx.flash(spec, 1.2, hits), math.exp(-1.0))
    assert _close(wx.flash(spec, 2.0, hits), 1.0 + math.exp(-5.0))
    assert wx.flash(spec, 3.0, hits) < 0.01


# ------------------------------------------------------------------------------------------- the element


def test_the_state_drives_the_readers():
    doc = wx.example_document()
    state = wx.state(doc, "wx", 1200.0)
    assert state["cloud"]["coverage"] == pytest.approx(wx.value(doc["physics"]["weathers"][0], "cloudiness", 1200.0))
    assert state["cloud"]["precipitation"] == pytest.approx(wx.value(doc["physics"]["weathers"][0], "precipitation", 1200.0))
    rain, snow = wx.split_rate(doc["physics"]["weathers"][0], 1200.0)
    assert _close(state["terrain"]["rain"], rain / 3.6e6)                           # metres of water per second
    assert _close(state["terrain"]["snowfall"], snow / 3.6e6 / wx.FRESH_SNOW_DENSITY)
    assert state["terrain"]["temperature"] == wx.value(doc["physics"]["weathers"][0], "temperature", 1200.0)
    assert _close(state["medium"]["extinction"], wx.extinction_at(doc["physics"]["weathers"][0], 1200.0))
    assert state["particles"] == wx.particle_fluxes(doc["physics"]["weathers"][0], 1200.0)
    assert state["surface"] == wx.surface_state(doc["physics"]["weathers"][0], 1200.0)
    assert state["strikes"] == wx.strikes(doc["physics"]["weathers"][0], E, 1200.0)
    assert state["flash"] == wx.flash(doc["physics"]["weathers"][0], 1200.0, state["strikes"])
    assert state["wind"] == "w1"
    assert state["digest"] == wx.state(doc, "wx", 1200.0)["digest"]
    with pytest.raises(wx.WeatherError):
        wx.state(doc, "nope", 0.0)


def test_validation_lists_the_rules():
    assert wx.validate_document(wx.example_document()) == []
    assert wx.validate_document(wx.bad_document()) == ["WX1", "WX2", "WX3", "WX4"]
    doc = wx.example_document()
    doc["version"] = "1.7"
    assert wx.validate_document(doc) == ["V17"]
    doc = wx.example_document()
    del doc["physics"]["weathers"]
    assert wx.validate_document(doc) == []


def test_validation_rules_one_at_a_time():
    def with_(**kw):
        doc = wx.example_document()
        doc["physics"]["weathers"][0].update(kw)
        return doc

    for kw in (dict(temperature=0.0), dict(humidity=1.5), dict(precipitation=-0.1), dict(cloudiness=2.0),
               dict(visibility=0.0), dict(lightning=-1.0), dict(rainMax=-1.0), dict(wetTime=0.0), dict(dryTime=0.0),
               dict(snowScale=0.0), dict(meltRate=-1.0), dict(step=0.0), dict(maxSteps=0), dict(lightningGrid=4),
               dict(lightningGrid=300), dict(lightningEta=-1.0), dict(maxStrikes=0), dict(flashDuration=0.0)):
        assert wx.validate_document(with_(**kw)) == ["WX1"], kw
    assert wx.validate_document(with_(wind="w9")) == ["WX2"]
    doc = wx.example_document()
    doc["readers"].append({"element": "cloudLayer", "id": "c9", "weather": "ghost"})
    assert wx.validate_document(doc) == ["WX3"]
    doc = wx.example_document()
    doc["readers"][0]["precipitation"] = 0.5
    assert wx.validate_document(doc) == ["WX4"]


def test_constants():
    d = wx.DEFAULTS
    assert d["wind"] is None and d["temperature"] == 288.15 and d["humidity"] == 0.5 and d["precipitation"] == 0.0
    assert d["cloudiness"] == 0.5 and d["visibility"] == 20000.0 and d["lightning"] == 0.0 and d["rainMax"] == 50.0
    assert d["wetTime"] == 300.0 and d["dryTime"] == 1800.0 and d["snowScale"] == 0.02 and d["meltRate"] == 1e-7
    assert d["step"] == 1.0 and d["maxSteps"] == 100000 and d["seed"] is None
    assert d["lightningGrid"] == 32 and d["lightningEta"] == 2.0 and d["maxStrikes"] == 1000 and d["flashDuration"] == 0.2
    assert wx.FREEZING == 273.15 and wx.KOSCHMIEDER == 3.912 and wx.WATER_IOR == 1.333 and wx.WATER_ROUGHNESS == 0.05
    assert wx.SNOW_ALBEDO == 0.85 and wx.SNOW_ROUGHNESS == 0.7 and wx.FRESH_SNOW_DENSITY == 0.1
    assert wx.REFERENCE_RAIN == 10.0 and wx.SNOWFLAKE_SPEED == 1.0 and wx.BRANCH_DIM == 0.3 and wx.SPHERE_RADIUS == 0.5
    assert wx.STRIKE_PURPOSE == 1 and wx.GROWTH_PURPOSE == 2 and wx.PURPOSE == "weather"
    assert wx.DRIVEN == {"cloudLayer": ("coverage", "precipitation"), "snowpack": ("snowfall", "temperature"),
                         "shallowWater": ("rain",), "erode": ("rain",), "emitter": ("rate",), "medium": ("extinction",),
                         "material": ()}


# --------------------------------------------------------------------------------------------- the draft


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
    for word in ("SR-107", "SR-101", "SR-102", "SR-104", "SR-105", "SR-106", "SREP 12", "SREP 14", "`weather`",
                 "`weatherMap`", "temperature", "humidity", "precipitation", "cloudiness", "visibility", "lightning",
                 "rainMax", "wetTime", "dryTime", "snowScale", "meltRate", "step", "maxSteps", "lightningGrid",
                 "lightningEta", "maxStrikes", "flashDuration", "WX1", "WX2", "WX3", "WX4", "V17",
                 "weather_reference.py", "Marshall", "Palmer", "Gunn", "Atlas", "Koschmieder", "Lekner", "Dorf",
                 "Lagarde", "Auer", "Kim and Lin", "Niemeyer", "dielectric breakdown", "Poisson", "time-change",
                 "degree-day", "monoton", "`cloudLayer`", "`snowpack`", "`shallowWater`", "`erode`", "`emitter`",
                 "`medium`", "`material`", "S(e, 1, k, 0)", "S(e, 2, k, n)", "3.912"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 20
    assert len(wx.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in wx.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = wx.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert wx._same(value, want), (name, value, want)
