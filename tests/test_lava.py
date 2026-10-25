"""Tests for the draft SREP "Add lava to the terrain grid" (T4 of SREP 12) and its reference module."""
from __future__ import annotations

import importlib.util
import math
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "lava_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-lava.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lv = _load(MODULE, "lava_reference")
tg = lv.terrain()
rs = lv.streams()


def _total(rows):
    return sum(v for row in rows for v in row)


def _layers(nx=6, ny=6, lava=0.0, bed=None, temperature=293.15):
    return {"bedrock": bed if bed is not None else tg.flat(nx, ny, 0.0), "lava": tg.flat(nx, ny, lava),
            "temperature": tg.flat(nx, ny, temperature)}


def _incline(nx, angle_degrees, dx):
    """A one-row bed descending to the right at the angle: z_i = -(i dx) tan(angle)."""
    t = math.tan(math.radians(angle_degrees))
    return [[-(i * dx) * t for i in range(nx)]]


ISOTHERMAL = dict(lv.DEFAULTS, emissivity=0.0, solidus=0.0, effusion=0.0)
E = rs.E(7, "ground", 11, "terrain")


# ----------------------------------------------------------------------------------------------------- rheology


def test_viscosity_and_yield_strength_rise_as_the_lava_cools():
    spec = dict(lv.DEFAULTS, viscosity=1000.0, viscosityRate=0.02, yieldStrength=2000.0, yieldRate=0.01,
                eruptionTemperature=1360.0)
    assert lv.viscosity(spec, 1360.0) == 1000.0
    assert lv.yield_strength(spec, 1360.0) == 2000.0
    assert math.isclose(lv.viscosity(spec, 1260.0), 1000.0 * 10.0 ** 2.0)
    assert math.isclose(lv.yield_strength(spec, 1260.0), 2000.0 * 10.0 ** 1.0)
    assert lv.viscosity(spec, 1400.0) < 1000.0 and lv.yield_strength(spec, 1400.0) < 2000.0


def test_the_critical_thickness_is_the_yield_strength_over_the_downslope_weight():
    h = lv.critical_thickness(2000.0, 2600.0, 0.1)
    assert math.isclose(h, 2000.0 / (2600.0 * lv.GRAVITY * 0.1))
    assert lv.critical_thickness(2000.0, 2600.0, 0.0) == math.inf
    assert math.isclose(lv.slope_sine(1.0, 1.0), 1.0 / math.sqrt(2.0))
    assert math.isclose(lv.slope_sine(3.0, 4.0), 0.6)
    assert lv.slope_sine(-1.0, 4.0) == 0.0


def test_the_bingham_flux_is_dragoni_s_and_vanishes_under_the_critical_thickness():
    rho, eta, s = 2600.0, 1000.0, 0.1
    h_cr = lv.critical_thickness(2000.0, rho, s)
    assert lv.bingham_flux(0.5 * h_cr, h_cr, s, rho, eta) == 0.0
    assert lv.bingham_flux(h_cr, h_cr, s, rho, eta) == 0.0
    a = 2.0
    want = rho * lv.GRAVITY * s * h_cr ** 3 / (3.0 * eta) * (a ** 3 - 1.5 * a ** 2 + 0.5)
    assert math.isclose(lv.bingham_flux(a * h_cr, h_cr, s, rho, eta), want)
    # the same number from the velocity profile: a sheared layer under a plug of thickness h_cr
    h = a * h_cr
    plug = rho * lv.GRAVITY * s / (2.0 * eta) * (h - h_cr) ** 2
    sheared = rho * lv.GRAVITY * s / eta * ((h - h_cr) ** 3 / 2.0 - (h - h_cr) ** 3 / 6.0)
    assert math.isclose(lv.bingham_flux(h, h_cr, s, rho, eta), sheared + plug * h_cr)
    # a Newtonian fluid (no yield strength) gives the Nusselt film flux rho g s h^3 / (3 eta)
    assert math.isclose(lv.bingham_flux(1.0, 0.0, s, rho, eta), rho * lv.GRAVITY * s / (3.0 * eta))
    assert lv.bingham_flux(1.0, h_cr, s, rho, eta) < lv.bingham_flux(1.0, h_cr, s, rho, eta / 2.0)


# --------------------------------------------------------------------------------------------------------- flow


def test_flow_halts_at_the_critical_thickness_on_an_incline():
    dx, angle = 10.0, 10.0
    spec = dict(ISOTHERMAL, viscosity=100.0, yieldStrength=2000.0, step=1.0)
    nx = 60
    layers = {"bedrock": _incline(nx, angle, dx), "lava": tg.flat(nx, 1, 0.0), "temperature": tg.flat(nx, 1, 1360.0)}
    for i in range(5):
        layers["lava"][0][i] = 1.0
    volume = _total(layers["lava"])
    h_cr = lv.critical_thickness(2000.0, spec["density"], math.sin(math.radians(angle)))
    moved = True
    n = 0
    while moved and n < 20000:
        before = layers["lava"]
        layers = lv.flow_step(layers, spec, dx, 1.0)
        moved = layers["lava"] is not before
        n += 1
    assert not moved, "the flow never halted"
    assert math.isclose(_total(layers["lava"]), volume)
    thick = max(layers["lava"][0])
    assert thick <= h_cr * (1.0 + lv.REST)
    assert thick >= 0.9 * h_cr
    # the deposit thins toward the front, and every cell is at rest under its own critical thickness
    front = max(i for i, v in enumerate(layers["lava"][0]) if v > 0.0)
    assert layers["lava"][0][front] < layers["lava"][0][0]
    assert layers["lava"][0][front] <= lv.critical_thickness(
        2000.0, spec["density"], lv.slope_sine(layers["lava"][0][front] + dx * math.tan(math.radians(angle)), dx)
    ) * (1.0 + lv.REST)
    assert layers["lava"][0][nx - 1] == 0.0, "the lava reached the edge: the incline is too short for the test"
    # the deposit reaches at least as far as the volume at the critical thickness allows
    assert sum(1 for v in layers["lava"][0] if v > 0.0) >= volume / h_cr


def test_flow_conserves_the_lava_and_moves_it_downhill_only():
    layers = _layers(bed=tg.plane(6, 6, -0.2, 0.0, 1.0), temperature=1360.0)
    layers["lava"][3][2] = 2.0
    out = lv.flow_step(layers, dict(ISOTHERMAL, viscosity=100.0), 1.0, 1.0)
    assert math.isclose(_total(out["lava"]), 2.0)
    assert out["lava"][3][2] < 2.0
    assert out["lava"][3][3] > 0.0
    assert out["lava"][3][3] > out["lava"][3][1]
    assert out["lava"][2][3] > out["lava"][2][1] and out["lava"][4][3] > out["lava"][4][1]
    assert out["bedrock"] == layers["bedrock"]
    # a sheet under its critical thickness is at rest on the slope
    still = _layers(bed=tg.plane(6, 6, -0.2, 0.0, 1.0), temperature=1360.0)
    h_cr = lv.critical_thickness(2000.0, 2600.0, lv.slope_sine(0.2, 1.0))
    still["lava"] = tg.flat(6, 6, 0.9 * h_cr)
    assert lv.flow_step(still, dict(ISOTHERMAL, viscosity=100.0), 1.0, 1.0) is still


def test_flow_never_takes_more_than_the_cell_holds_nor_overshoots_the_neighbour():
    layers = _layers(bed=tg.plane(6, 6, -1.0, 0.0, 1.0), temperature=1360.0)
    layers["lava"][3][2] = 0.5
    spec = dict(ISOTHERMAL, viscosity=1e-3, yieldStrength=0.0, step=10.0)
    out = lv.flow_step(layers, spec, 1.0, 10.0)
    assert out["lava"][3][2] >= 0.0
    assert math.isclose(_total(out["lava"]), 0.5)
    h = tg.surface(out)
    assert h[3][2] >= h[3][3] - 1e-12


def test_inflow_mixes_the_temperatures_by_volume():
    layers = _layers(bed=tg.plane(6, 6, -0.5, 0.0, 1.0), temperature=293.15)
    layers["lava"][3][2] = 1.0
    layers["temperature"][3][2] = 1300.0
    layers["lava"][3][3] = 1.0
    layers["temperature"][3][3] = 1100.0
    out = lv.flow_step(layers, dict(ISOTHERMAL, viscosity=100.0, viscosityRate=0.0, yieldRate=0.0), 1.0, 1.0)
    assert out["lava"][3][2] < 1.0
    t = out["temperature"][3][3]
    assert 1100.0 < t < 1300.0
    assert out["temperature"][3][2] == 1300.0
    # a cell that had no lava takes the inflow's temperature
    assert out["lava"][3][4] > 0.0 and out["temperature"][3][4] == 1100.0


def test_a_cell_with_no_lava_and_a_higher_neighbour_still_receives_by_the_surface_slope():
    layers = _layers(temperature=1360.0)
    layers["lava"][2][2] = 3.0
    out = lv.flow_step(layers, dict(ISOTHERMAL, viscosity=100.0), 1.0, 1.0)
    assert out["lava"][2][2] < 3.0
    assert all(out["lava"][2 + dj][2 + di] > 0.0 for di, dj, _ in tg.D8)
    assert math.isclose(_total(out["lava"]), 3.0)


# ------------------------------------------------------------------------------------------------------ cooling


def test_radiative_cooling_follows_stefan_boltzmann_with_the_lava_s_thermal_mass():
    spec = dict(lv.DEFAULTS, emissivity=0.9, density=2600.0, heatCapacity=1150.0, ambient=293.15, crust=0.5)
    t0, h, dt = 1360.0, 1.0, 1e-3
    rate = 0.9 * lv.STEFAN_BOLTZMANN * (t0 ** 4 - 293.15 ** 4) / (2600.0 * 1150.0 * h)
    assert math.isclose(lv.cool(spec, t0, h, dt), t0 - rate * dt, rel_tol=1e-6)
    # against a fine integration over 1000 s
    fine = t0
    for _ in range(100000):
        fine = lv.cool(spec, fine, h, 0.01)
    coarse = t0
    for _ in range(1000):
        coarse = lv.cool(spec, coarse, h, 1.0)
    assert abs(fine - coarse) < 1.0
    assert coarse < t0
    assert lv.cool(spec, t0, h, 1e9) == 293.15
    assert lv.cool(spec, 293.15, h, 1.0) == 293.15
    # a cell without lava cools with the crust's thermal mass
    assert lv.cool(spec, t0, 0.0, dt) == lv.cool(spec, t0, 0.5, dt)
    assert lv.cool(spec, t0, 0.1, dt) == lv.cool(spec, t0, 0.5, dt)
    assert lv.cool(dict(spec, emissivity=0.0), t0, h, 1.0) == t0


def test_solidification_moves_the_cold_lava_into_the_bedrock():
    layers = _layers()
    layers["lava"][1][1] = 2.0
    layers["temperature"][1][1] = 1100.0
    layers["lava"][2][2] = 2.0
    layers["temperature"][2][2] = 1200.0
    out, solid = lv.solidify(layers, dict(lv.DEFAULTS, solidus=1173.15))
    assert out["lava"][1][1] == 0.0 and out["bedrock"][1][1] == 2.0
    assert out["lava"][2][2] == 2.0 and out["bedrock"][2][2] == 0.0
    assert solid == 2.0
    assert tg.surface(out) == tg.surface(layers)
    assert out["temperature"] == layers["temperature"]


# --------------------------------------------------------------------------------------------------------- vent


def test_the_vent_erupts_the_effusion_rate_at_the_eruption_temperature():
    spec = dict(lv.DEFAULTS, ventX=125.0, ventY=75.0, effusion=20.0, eruptionTemperature=1360.0, step=1.0)
    assert lv.vent_cell(spec, 50.0, 6, 4) == (2, 1)
    layers = _layers()
    out = lv.erupt(layers, spec, 50.0, E, 0)
    assert math.isclose(out["lava"][1][2], 20.0 / 2500.0)
    assert out["temperature"][1][2] == 1360.0
    assert math.isclose(_total(out["lava"]) * 2500.0, 20.0)
    # mixing with lava already there
    layers["lava"][1][2] = 20.0 / 2500.0
    layers["temperature"][1][2] = 1200.0
    out = lv.erupt(layers, spec, 50.0, E, 0)
    assert math.isclose(out["temperature"][1][2], 1280.0)
    assert lv.erupt(layers, dict(spec, effusion=0.0), 50.0, E, 0) is layers


def test_the_effusion_variation_draws_from_the_terrain_streams():
    spec = dict(lv.DEFAULTS, effusion=10.0, effusionVariation=0.5, step=1.0)
    s = rs.S(E, lv.PURPOSE, 3, 0)
    assert math.isclose(lv.effusion_volume(spec, E, 3), 10.0 * (1.0 + 0.5 * (2.0 * s - 1.0)))
    assert lv.effusion_volume(dict(spec, effusionVariation=0.0), E, 3) == 10.0
    # an animated effusion is read at the step's start time
    ramp = dict(spec, effusionVariation=0.0, effusion=lambda t: 2.0 * t, step=0.5)
    assert lv.effusion_volume(ramp, E, 3) == 2.0 * 1.5 * 0.5
    assert lv.value(ramp, "effusion", 4.0) == 8.0 and lv.value(spec, "effusion", 4.0) == 10.0
    assert lv.PURPOSE == 2 ** 31 + 2 ** 17
    assert lv.PURPOSE != lv.erosion().PURPOSE_BASE


# ---------------------------------------------------------------------------------------------------------- run


def test_run_counts_steps_and_builds_a_cooling_flow():
    doc = lv.example_document()
    out = lv.run(doc, 300.0)
    assert out["steps"] == 300
    assert out["shape"] == (16, 12)
    assert _total(out["layers"]["lava"]) > 0.0
    hot = max(v for row in out["layers"]["temperature"] for v in row)
    assert 293.15 < hot <= doc["lavaFlow"]["eruptionTemperature"]
    assert out["erupted"] > 0.0
    assert math.isclose(_total(out["layers"]["lava"]) * 2500.0 + out["solidified"] * 2500.0, out["erupted"],
                        rel_tol=1e-9)
    assert out["digest"] == lv.run(doc, 300.0)["digest"]
    assert out["digest"] != lv.run(doc, 200.0)["digest"]
    assert len(out["digest"]) == 64


def test_a_long_run_solidifies_lava_into_the_bedrock():
    doc = lv.example_document()
    doc.update(width=60.0, height=60.0, cells=6, metersPerCell=10.0, masks=[], materials=[])
    doc["layers"] = [{"kind": "bedrock", "value": 100.0}, {"kind": "lava", "value": 0.0},
                     {"kind": "temperature", "value": 293.15}]
    doc["lavaFlow"].update(ventX=25.0, ventY=25.0, effusion=lambda t: 0.5 if t < 600.0 else 0.0,
                           effusionVariation=0.0, crust=0.2)
    out = lv.run(doc, 3000.0)
    assert math.isclose(out["erupted"], 300.0)
    assert out["solidified"] > 0.0
    assert _total(out["layers"]["bedrock"]) > 36 * 100.0
    assert math.isclose(_total(out["layers"]["bedrock"]) - 36 * 100.0, out["solidified"])
    assert math.isclose((_total(out["layers"]["lava"]) + out["solidified"]) * 100.0, out["erupted"])
    # the solidified cells are colder than the solidus and keep cooling toward the ambient
    cold = [(j, i) for j in range(6) for i in range(6)
            if out["layers"]["bedrock"][j][i] > 100.0 and out["layers"]["lava"][j][i] == 0.0]
    assert cold
    assert all(out["layers"]["temperature"][j][i] < doc["lavaFlow"]["solidus"] for j, i in cold)
    assert all(out["layers"]["temperature"][j][i] > 293.15 for j, i in cold)


def test_steps_are_bounded_and_the_step_positive():
    assert lv.steps_for(10.0, 1.0, 100000) == 10
    assert lv.steps_for(10.0, 1.0, 4) == 4
    assert lv.steps_for(0.49, 1.0, 100000) == 0
    with pytest.raises(lv.LavaError):
        lv.steps_for(1.0, 0.0, 10)


# --------------------------------------------------------------------------------------------------- validation


def test_validation_lists_the_rules():
    assert lv.validate_document(lv.example_document()) == []
    assert lv.validate_document(lv.bad_document()) == ["LV1", "LV2", "LV3", "LV4"]
    with pytest.raises(lv.LavaError):
        lv.run(lv.bad_document(), 1.0)
    old = lv.example_document()
    old["version"] = "1.7"
    assert lv.validate_document(old) == ["V17"]
    plain = lv.example_document()
    del plain["lavaFlow"]
    assert lv.validate_document(plain) == []


@pytest.mark.parametrize("change,code", [
    (dict(effusion=-1.0), "LV1"), (dict(effusionVariation=1.5), "LV1"), (dict(eruptionTemperature=0.0), "LV1"),
    (dict(ambient=-1.0), "LV1"), (dict(density=0.0), "LV1"), (dict(heatCapacity=0.0), "LV1"),
    (dict(emissivity=1.5), "LV1"), (dict(crust=0.0), "LV1"), (dict(solidus=-1.0), "LV1"),
    (dict(viscosity=0.0), "LV1"), (dict(viscosityRate=-1.0), "LV1"), (dict(yieldStrength=-1.0), "LV1"),
    (dict(yieldRate=-1.0), "LV1"), (dict(step=0.0), "LV1"), (dict(maxSteps=0), "LV1"),
    (dict(ventX=-1.0), "LV4"), (dict(ventY=1e9), "LV4"),
])
def test_validation_rules_one_at_a_time(change, code):
    doc = lv.example_document()
    doc["lavaFlow"].update(change)
    assert lv.validate_document(doc) == [code]


def test_validation_needs_the_layers():
    doc = lv.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "lava"]
    assert lv.validate_document(doc) == ["LV2"]
    doc = lv.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "temperature"]
    assert lv.validate_document(doc) == ["LV3"]
    doc = lv.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "bedrock"]
    assert "LV2" in lv.validate_document(doc)


def test_constants():
    d = lv.DEFAULTS
    assert d["layer"] == "lava" and d["ventX"] == 0.0 and d["ventY"] == 0.0 and d["effusion"] == 0.0
    assert d["effusionVariation"] == 0.0 and d["eruptionTemperature"] == 1360.0 and d["ambient"] == 293.15
    assert d["density"] == 2600.0 and d["heatCapacity"] == 1150.0 and d["emissivity"] == 0.9 and d["crust"] == 0.5
    assert d["solidus"] == 1173.15 and d["viscosity"] == 1000.0 and d["viscosityRate"] == 0.02
    assert d["yieldStrength"] == 2000.0 and d["yieldRate"] == 0.01 and d["step"] == 1.0 and d["maxSteps"] == 100000
    assert lv.GRAVITY == 9.81 and math.isclose(lv.STEFAN_BOLTZMANN, 5.670374419e-8)


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
    for word in ("SR-108", "SR-100", "SREP 12", "SREP 14", "`lavaFlow`", "ventX", "ventY", "effusion",
                 "effusionVariation", "eruptionTemperature", "ambient", "density", "heatCapacity", "emissivity",
                 "crust", "solidus", "viscosity", "viscosityRate", "yieldStrength", "yieldRate", "step", "maxSteps",
                 "LV1", "LV2", "LV3", "LV4", "V17", "lava_reference.py", "terrain-grid", "random-streams",
                 "Bingham", "Dragoni", "Vicari", "MAGFLOW", "Ishihara", "Stefan", "Boltzmann", "critical thickness",
                 "τ", "plug", "`lava`", "`bedrock`", "`temperature`", "Nusselt", "2³¹ + 2¹⁷", "solidif",
                 "mass", "cellular", "Giordano", "Harris"):
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
    assert len(lv.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in lv.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = lv.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert lv._same(value, want), (name, value, want)
