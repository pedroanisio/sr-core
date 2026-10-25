"""Tests for the draft SREP "Add snow and ice to the terrain grid" (T3 of SREP 12) and its reference module."""
from __future__ import annotations

import importlib.util
import math
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "snow_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-snow.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sn = _load(MODULE, "snow_reference")
tg = sn.terrain()
rs = sn.streams()


def _close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def _total(rows):
    return sum(v for row in rows for v in row)


def _layers(n=6, snow=0.0, water=True, ice=False, bed=None):
    layers = {"bedrock": bed if bed is not None else tg.flat(n, n, 0.0), "snow": tg.flat(n, n, snow)}
    if water:
        layers["water"] = tg.flat(n, n, 0.0)
    if ice:
        layers["ice"] = tg.flat(n, n, 0.0)
    return layers


def _wind_doc(speed, direction=0.0):
    return {"version": "1.8", "project": 7,
            "physics": {"winds": [{"id": "w1", "speed": speed, "direction": direction, "seed": 3}]}}


E = rs.E(7, "ground", 11, "terrain")


# --------------------------------------------------------------------------------------------- snowfall and melt


def test_snowfall_accumulates_exactly_in_the_cold():
    spec = dict(sn.DEFAULTS, snowfall=0.001, temperature=263.15, step=0.1)
    layers = _layers()
    for n in range(10):
        layers, lost = sn.step(layers, spec, 1.0, E, n, None)
    assert all(_close(v, 0.001 * 1.0) for row in layers["snow"] for v in row)
    assert lost == 0.0
    assert _total(layers["water"]) == 0.0


def test_snowfall_variation_draws_from_the_terrain_stream():
    spec = dict(sn.DEFAULTS, snowfall=0.001, snowfallVariation=0.5, step=0.1)
    draw = rs.S(E, sn.PURPOSE, 3, rs.pack(2, 4, 0))
    assert _close(sn.snowfall_depth(spec, E, 3, 2, 4), 0.001 * 0.1 * (1.0 + 0.5 * (2.0 * draw - 1.0)))
    assert sn.snowfall_depth(dict(spec, snowfallVariation=0.0), E, 3, 2, 4) == 0.001 * 0.1
    assert sn.PURPOSE == 2 ** 31 + 2 ** 16


def test_melt_follows_the_degree_day_law_and_feeds_the_water_layer():
    assert sn.melt_depth(dict(sn.DEFAULTS, meltRate=1e-5), 263.15, 1.0) == 0.0
    assert _close(sn.melt_depth(dict(sn.DEFAULTS, meltRate=1e-5), 275.15, 2.0), 1e-5 * 2.0 * 2.0)
    spec = dict(sn.DEFAULTS, snowfall=0.0, temperature=275.15, meltRate=1e-3, density=0.3, step=0.1)
    layers = _layers(snow=0.01)
    layers, _ = sn.step(layers, spec, 1.0, E, 0, None)
    melted = 1e-3 * 2.0 * 0.1
    assert all(_close(v, 0.01 - melted) for row in layers["snow"] for v in row)
    assert all(_close(v, 0.3 * melted) for row in layers["water"] for v in row)
    # melting never goes below zero snow
    layers = _layers(snow=0.0001)
    layers, _ = sn.step(layers, spec, 1.0, E, 0, None)
    assert all(v == 0.0 for row in layers["snow"] for v in row)
    assert all(_close(v, 0.3 * 0.0001) for row in layers["water"] for v in row)


def test_the_temperature_layer_overrides_the_attribute():
    layers = _layers(snow=0.01)
    layers["temperature"] = tg.flat(6, 6, 263.15)
    layers["temperature"][2][3] = 280.15
    spec = dict(sn.DEFAULTS, temperature=275.15, meltRate=1e-3, step=0.1)
    assert sn.cell_temperature(layers, spec, 3, 2) == 280.15
    assert sn.cell_temperature(layers, spec, 0, 0) == 263.15
    assert sn.cell_temperature(_layers(), spec, 0, 0) == 275.15
    out, _ = sn.step(layers, spec, 1.0, E, 0, None)
    assert out["snow"][2][3] < 0.01 and out["snow"][0][0] == 0.01


def test_mass_balance_is_snowfall_minus_melt():
    spec = dict(sn.DEFAULTS, snowfall=0.002, temperature=274.15, meltRate=5e-4, step=0.1, repose=38.0)
    layers = _layers(bed=tg.bowl(6))
    fallen = melted = 0.0
    for n in range(30):
        before = _total(layers["snow"])
        water_before = _total(layers["water"])
        layers, lost = sn.step(layers, spec, 1.0, E, n, None)
        fallen += 0.002 * 0.1 * 36
        melted += (_total(layers["water"]) - water_before) / 0.3
        assert lost == 0.0
        assert _total(layers["snow"]) <= before + 0.002 * 0.1 * 36 + 1e-12
    assert _close(_total(layers["snow"]), fallen - melted, 1e-9)
    assert melted > 0.0


# ------------------------------------------------------------------------------------------------ avalanches


def test_avalanches_leave_no_snow_above_the_repose_angle_and_keep_the_mass():
    n = 9
    snow = [[0.0] * n for _ in range(n)]
    snow[4][4] = 6.0                                                             # a pile
    layers = {"bedrock": tg.flat(n, n, 0.0), "snow": snow}
    spec = dict(sn.DEFAULTS, repose=38.0, avalancheRate=0.5, step=0.1)
    for _ in range(400):
        layers = sn.avalanche_step(layers, spec, 1.0)
    assert _close(_total(layers["snow"]), 6.0, 1e-9)
    assert sn.max_slope(layers["snow"], 1.0) <= 38.0 + 1e-6
    assert min(v for row in layers["snow"] for v in row) >= 0.0
    # the bedrock did not move
    assert _total(layers["bedrock"]) == 0.0


def test_avalanche_moves_only_the_named_snow_layer():
    n = 5
    layers = {"bedrock": tg.pit(n), "snow": tg.flat(n, n, 0.0), "snow:powder": tg.flat(n, n, 0.0)}
    layers["snow:powder"][2][2] = 3.0
    spec = dict(sn.DEFAULTS, layer="snow:powder", repose=38.0, avalancheRate=0.5)
    out = sn.avalanche_step(layers, spec, 1.0)
    assert out["snow:powder"][2][2] < 3.0 and _close(_total(out["snow:powder"]), 3.0)
    assert out["snow"] == layers["snow"] and out["bedrock"] == layers["bedrock"]
    with pytest.raises(sn.SnowError):
        sn.avalanche_step(layers, dict(spec, layer="snow:ice"), 1.0)


# ------------------------------------------------------------------------------------------------------ drift


def test_drift_flux_has_a_threshold_and_grows_with_the_cube_of_the_excess():
    spec = dict(sn.DEFAULTS, driftRate=1e-4, driftThreshold=5.0)
    assert sn.drift_flux(spec, 4.0) == 0.0 and sn.drift_flux(spec, 5.0) == 0.0
    assert _close(sn.drift_flux(spec, 7.0), 1e-4 * 8.0)
    assert _close(sn.drift_flux(spec, 9.0), 1e-4 * 64.0)


def test_exposure_is_higher_on_windward_slopes():
    assert sn.exposure(0.1, 0.0, (8.0, 0.0), 1.0) > 1.0                           # rising along the wind
    assert sn.exposure(-0.1, 0.0, (8.0, 0.0), 1.0) < 1.0                          # falling along the wind
    assert sn.exposure(0.0, 0.0, (8.0, 0.0), 1.0) == 1.0
    assert sn.exposure(0.0, 0.0, (0.0, 0.0), 1.0) == 1.0
    assert sn.exposure(-5.0, 0.0, (8.0, 0.0), 1.0) == 0.0 and sn.exposure(5.0, 0.0, (8.0, 0.0), 1.0) == 2.0


def test_wind_grid_reads_the_wind_at_the_cell_centres_in_physics_space():
    doc = _wind_doc(8.0, 90.0)                                                      # toward +y in physics: up the grid
    grid = sn.wind_grid(doc, "w1", 0.0, 3, 2, 10.0)
    assert len(grid) == 2 and len(grid[0]) == 3
    wx, wy = grid[1][2]
    assert _close(wx, 0.0) and _close(wy, -8.0)                                     # grid j points down
    assert sn.wind_grid(_wind_doc(8.0, 0.0), "w1", 0.0, 3, 2, 10.0)[0][0] == pytest.approx((8.0, 0.0))


def test_drift_moves_snow_downwind_and_the_lost_snow_is_accounted():
    n = 6
    layers = _layers(n, snow=0.5, water=False)
    spec = dict(sn.DEFAULTS, driftRate=1e-3, driftThreshold=5.0, step=0.1)
    winds = [[(8.0, 0.0)] * n for _ in range(n)]
    out, lost = sn.drift_step(layers, spec, 1.0, winds, 0.1)
    assert lost > 0.0                                                                # the downwind edge column loses
    assert _close(_total(out["snow"]) + lost, 0.5 * n * n, 1e-9)
    assert out["snow"][2][0] < 0.5                                                   # the upwind edge thins
    assert out["snow"][2][3] == 0.5                                                  # interior: in equals out
    assert min(v for row in out["snow"] for v in row) >= 0.0
    # a calm wind moves nothing
    calm, lost0 = sn.drift_step(layers, spec, 1.0, [[(1.0, 0.0)] * n for _ in range(n)], 0.1)
    assert calm["snow"] == layers["snow"] and lost0 == 0.0


def test_drift_piles_snow_in_the_lee_of_a_ridge():
    n = 9
    bed = [[5.0 if i == 4 else 0.0 for i in range(n)] for _ in range(n)]
    layers = {"bedrock": bed, "snow": tg.flat(n, n, 0.3)}
    spec = dict(sn.DEFAULTS, driftRate=1e-3, driftThreshold=5.0, exposureGain=1.0, repose=89.0, step=0.1)
    winds = [[(9.0, 0.0)] * n for _ in range(n)]
    for _ in range(20):
        layers, _ = sn.drift_step(layers, spec, 1.0, winds, 0.1)
    assert layers["snow"][4][5] > layers["snow"][4][3]                             # the lee holds more than the windward foot
    assert layers["snow"][4][3] < 0.3


def test_drift_never_takes_more_than_the_cell_holds():
    n = 4
    layers = _layers(n, snow=1e-6, water=False)
    spec = dict(sn.DEFAULTS, driftRate=1.0, driftThreshold=0.0, step=1.0)
    out, lost = sn.drift_step(layers, spec, 1.0, [[(20.0, 0.0)] * n for _ in range(n)], 1.0)
    assert min(v for row in out["snow"] for v in row) >= 0.0
    assert _close(_total(out["snow"]) + lost, 1e-6 * n * n, 1e-15)


# -------------------------------------------------------------------------------------------------- glaciers


def test_shallow_ice_diffusivity():
    a = 1e-16
    d = sn.ice_diffusivity(100.0, 0.1, a)
    assert _close(d, 2.0 * a / 5.0 * (917.0 * 9.81) ** 3 * 100.0 ** 5 * 0.1 ** 2, 1e-9 * d)
    assert sn.ice_diffusivity(0.0, 0.1, a) == 0.0 and sn.ice_diffusivity(100.0, 0.0, a) == 0.0
    assert sn.GLEN_N == 3 and sn.ICE_DENSITY == 917.0


def test_an_ice_dome_spreads_and_keeps_its_mass():
    n, dx = 41, 100.0
    half = (n - 1) / 2.0
    ice = [[max(0.0, 100.0 * (1.0 - ((i - half) / 12.0) ** 2)) for i in range(n)]]
    layers = {"bedrock": tg.flat(n, 1, 0.0), "ice": ice}
    spec = dict(sn.DEFAULTS, iceFlow=1e-16, iceTimeScale=1.0)
    out, substeps = sn.ice_step(layers, spec, dx, 10.0)
    assert substeps >= 2
    assert _close(_total(out["ice"]), _total(ice), 1e-9 * _total(ice))
    assert out["ice"][0][20] < 100.0
    assert out["ice"][0][33] > 0.0 and ice[0][33] == 0.0                           # beyond the old margin
    assert min(out["ice"][0]) >= 0.0
    assert out["bedrock"] == layers["bedrock"]


def test_ice_substeps_are_bounded():
    n, dx = 41, 10.0                                                                # the dome on 10 m cells
    ice = [[max(0.0, 100.0 * (1.0 - ((i - 20.0) / 12.0) ** 2)) for i in range(n)]]
    layers = {"bedrock": tg.flat(n, 1, 0.0), "ice": ice}
    spec = dict(sn.DEFAULTS, iceFlow=1e-16, iceTimeScale=1.0)
    with pytest.raises(sn.SnowError):
        sn.ice_step(layers, spec, dx, 1e4)
    assert sn.MAX_ICE_SUBSTEPS == 1000
    # a spike on a closed grid flattens and the flow stops: it ends within the bound
    spike = {"bedrock": tg.flat(11, 1, 0.0), "ice": [[500.0 if i == 5 else 0.0 for i in range(11)]]}
    out, substeps = sn.ice_step(spike, spec, 1.0, 1e6)
    assert substeps < sn.MAX_ICE_SUBSTEPS and max(out["ice"][0]) - min(out["ice"][0]) < 1e-3


def test_ice_flows_down_the_bed_too():
    n, dx = 21, 100.0
    bed = [[float(500 - 10 * i) for i in range(n)]]                                 # falling toward +x
    layers = {"bedrock": bed, "ice": [[50.0 if 8 <= i <= 12 else 0.0 for i in range(n)]]}
    out, _ = sn.ice_step(layers, dict(sn.DEFAULTS, iceFlow=1e-16, iceTimeScale=1.0), dx, 20.0)
    centre = sum(i * v for i, v in enumerate(out["ice"][0])) / sum(out["ice"][0])
    assert centre > 10.0


# ------------------------------------------------------------------------------------------------ the element


def test_run_counts_steps_and_writes_the_layers():
    doc = sn.example_document()
    out = sn.run(doc, 0.5)
    assert out["steps"] == 25
    assert _total(out["layers"]["snow:"]) > 0.0
    assert out["lost"] >= 0.0
    assert out["digest"] == sn.run(doc, 0.5)["digest"]
    assert sn.run(doc, 0.0)["steps"] == 0


def test_steps_are_bounded_and_the_step_positive():
    assert sn.steps_for(0.5, 0.02, 100000) == 25
    assert sn.steps_for(10.0, 0.02, 100) == 100
    with pytest.raises(sn.SnowError):
        sn.steps_for(1.0, 0.0, 10)


def test_validation_lists_the_rules():
    assert sn.validate_document(sn.example_document()) == []
    assert sn.validate_document(sn.bad_document()) == ["SN1", "SN2", "SN3", "SN4", "SN5"]
    doc = sn.example_document()
    doc["version"] = "1.7"
    assert sn.validate_document(doc) == ["V17"]


def test_validation_rules_one_at_a_time():
    def with_(**kw):
        doc = sn.example_document()
        doc["snowpack"].update(kw)
        return doc

    for kw in (dict(snowfall=-1.0), dict(snowfallVariation=1.5), dict(temperature=0.0), dict(meltRate=-1.0),
               dict(density=0.0), dict(density=1.5), dict(repose=90.0), dict(avalancheRate=2.0), dict(driftRate=-1.0),
               dict(driftThreshold=-1.0), dict(exposureGain=-1.0), dict(iceFlow=-1.0), dict(iceTimeScale=-1.0),
               dict(step=0.0), dict(maxSteps=0)):
        assert sn.validate_document(with_(**kw)) == ["SN1"], kw
    assert sn.validate_document(with_(layer="snow:deep")) == ["SN2"]
    assert sn.validate_document(with_(layer="bedrock")) == ["SN2"]
    assert sn.validate_document(with_(wind="w9")) == ["SN3"]
    doc = sn.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "ice"]
    assert sn.validate_document(doc) == ["SN4"]
    doc = sn.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "water"]
    assert sn.validate_document(doc) == ["SN5"]
    doc["snowpack"]["meltRate"] = 0.0
    assert sn.validate_document(doc) == []


def test_constants():
    d = sn.DEFAULTS
    assert d["layer"] == "snow" and d["snowfall"] == 0.0 and d["snowfallVariation"] == 0.0
    assert d["temperature"] == 268.15 and d["meltRate"] == 1e-5 and d["density"] == 0.3
    assert d["repose"] == 38.0 and d["avalancheRate"] == 0.5 and d["wind"] is None
    assert d["driftRate"] == 1e-4 and d["driftThreshold"] == 5.0 and d["exposureGain"] == 1.0
    assert d["iceFlow"] == 1e-16 and d["iceTimeScale"] == 0.0 and d["step"] == 0.02 and d["maxSteps"] == 100000
    assert sn.FREEZING == 273.15 and sn.GRAVITY == 9.81


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
    for word in ("SR-106", "SR-100", "SR-101", "SREP 12", "SREP 14", "`snowpack`", "snowfall", "snowfallVariation",
                 "temperature", "meltRate", "density", "repose", "avalancheRate", "wind", "driftRate", "driftThreshold",
                 "exposureGain", "iceFlow", "iceTimeScale", "step", "maxSteps", "SN1", "SN2", "SN3", "SN4", "SN5",
                 "V17", "snow_reference.py", "terrain-grid", "random-streams", "pack(i, j, 0)", "Cordonnier",
                 "Fearing", "Musgrave", "shallow-ice", "Glen", "Hutter", "degree-day", "Pomeroy", "saltation",
                 "`snow`", "`ice`", "`water`", "`temperature`", "exposure", "lee", "mass balance", "Vialov",
                 "2³¹ + 2¹⁶"):
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
    assert len(sn.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in sn.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = sn.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert sn._same(value, want), (name, value, want)
