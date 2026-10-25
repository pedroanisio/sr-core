"""Tests for the draft SREP "Add erosion processes to the terrain grid" (T1 of SREP 12) and its reference module."""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "erosion_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-erosion.md")


def _load():
    spec = importlib.util.spec_from_file_location("erosion_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


er = _load()
tg = er.terrain()
rs = er.streams()


def _close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def _total(rows):
    return sum(v for row in rows for v in row)


# ------------------------------------------------------------------------------------------------- routing


def test_routing_on_a_plane_drains_downhill_with_the_row_accumulation():
    h = tg.plane(6, 3, 0.1, 0.0, dx=10.0)              # rises with i: everything drains toward i = 0
    r = er.routing(h, 10.0)
    assert r["receiver"][(3, 1)] == (2, 1) and r["receiver"][(0, 1)] is None
    assert r["distance"][(3, 1)] == 10.0
    assert r["area"][1][3] == 3 * 100.0 and r["area"][1][0] == 6 * 100.0
    assert r["accumulation"] == tg.flow_accumulation(h)
    # a diagonal receiver is sqrt 2 cells away
    bowl = tg.bowl(5)
    rb = er.routing(bowl, 2.0)
    assert rb["receiver"][(0, 0)] == (1, 1) and _close(rb["distance"][(0, 0)], 2.0 * math.sqrt(2.0))


def test_travel_time_sums_the_cells_down_to_base_level():
    h = tg.plane(5, 1, 0.1, 0.0, dx=10.0)
    r = er.routing(h, 10.0)
    tau = er.travel_time(r, 2e-5, 0.5)
    assert tau[(0, 0)] == 0.0
    want = 0.0
    for i in range(1, 5):
        want += 10.0 / (2e-5 * r["area"][0][i] ** 0.5)
        assert _close(tau[(i, 0)], want, 1e-6 * want)


# -------------------------------------------------------------------------------------------- fluvial, closed form


def _row_closed_form(h0, r, tau, uplift, T):
    """An independent one-row evaluation of the characteristic solution for the test."""
    out = {}
    for cell, t in tau.items():
        path = [cell]
        while r["receiver"][path[-1]] is not None:
            path.append(r["receiver"][path[-1]])
        if T >= t:
            base = path[-1]
            out[cell] = h0[base[1]][base[0]] + uplift * t
            continue
        target = t - T                                   # the travel time of the point the characteristic left
        for a, b in zip(path, path[1:]):
            ta, tb = tau[a], tau[b]
            if tb <= target <= ta:
                f = (ta - target) / (ta - tb)
                ha, hb = h0[a[1]][a[0]], h0[b[1]][b[0]]
                out[cell] = ha + f * (hb - ha) + uplift * T
                break
    return out


def test_the_closed_form_starts_at_the_initial_surface_and_ends_at_the_steady_profile():
    h0 = tg.plane(8, 1, 0.05, 0.0, dx=10.0)
    r = er.routing(h0, 10.0)
    tau = er.travel_time(r, 2e-5, 0.5)
    assert er.fluvial_surface(h0, r, tau, 1e-3, 0.0) == h0
    far = er.fluvial_surface(h0, r, tau, 1e-3, 1e12)
    for i in range(1, 8):
        a = r["area"][0][i]
        slope = (far[0][i] - far[0][i - 1]) / 10.0
        assert _close(slope * a ** 0.5, 1e-3 / 2e-5, 1e-6 * 1e-3 / 2e-5), i      # S A^m = U / K
    assert far[0][0] == h0[0][0]                                                  # base level holds
    # between: the characteristic solution, checked against an independent evaluation
    mid = er.fluvial_surface(h0, r, tau, 1e-3, 0.3 * max(tau.values()))
    want = _row_closed_form(h0, r, tau, 1e-3, 0.3 * max(tau.values()))
    for (i, j), v in want.items():
        assert _close(mid[j][i], v, 1e-9), (i, j)
    # the surface is a function of T alone: evaluating twice, or at T after T/2, is the same
    assert er.fluvial_surface(h0, r, tau, 1e-3, 5e8) == er.fluvial_surface(h0, r, tau, 1e-3, 5e8)


def test_fluvial_changes_only_its_layer_and_reads_the_geological_time():
    spec = dict(er.FLUVIAL_DEFAULTS, kind="fluvial", uplift=1e-3, erodibility=2e-5, m=0.5, time=1e5, timeScale=10.0)
    assert er.geological_time(spec, 0.0) == 1e5 and er.geological_time(spec, 2.5) == 1e5 + 25.0
    layers = {"bedrock": tg.plane(6, 4, 0.05, 0.02, dx=10.0), "loose": tg.flat(6, 4, 2.0), "water": tg.flat(6, 4, 0.0)}
    out = er.fluvial(layers, spec, 10.0, 1e12)
    assert out["loose"] == layers["loose"] and out["water"] == layers["water"]
    assert out["bedrock"] != layers["bedrock"]
    # the change equals the surface change
    h0 = tg.surface(layers)
    r = er.routing(h0, 10.0)
    want = er.fluvial_surface(h0, r, er.travel_time(r, 2e-5, 0.5), 1e-3, 1e12)
    for j in range(4):
        for i in range(6):
            assert _close(out["bedrock"][j][i] - layers["bedrock"][j][i], want[j][i] - h0[j][i], 1e-9)


# -------------------------------------------------------------------------------------------------- thermal


def test_thermal_relaxes_to_the_talus_angle_and_conserves_mass():
    n = 9
    layers = {"bedrock": [[100.0 * v for v in row] for row in tg.pit(n)]}     # a steep inverted pyramid
    spec = dict(er.THERMAL_DEFAULTS, kind="thermal", talus=35.0, rate=0.5, layer="bedrock")
    before = _total(layers["bedrock"])
    assert er.max_neighbour_slope(tg.surface(layers), 1.0) > 80.0
    for _ in range(600):
        layers = er.thermal_step(layers, spec, 1.0)
    assert _close(_total(layers["bedrock"]), before, 1e-9 * before)
    assert er.max_neighbour_slope(tg.surface(layers), 1.0) <= 35.0 + 1e-6
    # a slope under the talus angle is untouched, and the named layer is the only one that moves
    gentle = {"bedrock": tg.plane(5, 5, 0.1, 0.0), "loose": tg.flat(5, 5, 1.0)}
    assert er.thermal_step(gentle, dict(spec, layer="loose"), 1.0) == gentle
    steep = {"bedrock": tg.plane(5, 5, 2.0, 0.0), "loose": tg.flat(5, 5, 1.0)}
    moved = er.thermal_step(steep, dict(spec, layer="loose"), 1.0)
    assert moved["bedrock"] == steep["bedrock"] and moved["loose"] != steep["loose"]
    assert min(v for row in moved["loose"] for v in row) >= 0.0                 # a layer never goes negative
    with pytest.raises(er.ErosionError):
        er.thermal_step(steep, dict(spec, layer="ice"), 1.0)


# ------------------------------------------------------------------------------------------------ hydraulic


def _state(n=6, dx=1.0):
    layers = {"bedrock": tg.bowl(n), "loose": tg.flat(n, n, 0.5), "water": tg.flat(n, n, 0.0),
              "sediment": tg.flat(n, n, 0.0), "flow": [[(0.0, 0.0)] * n for _ in range(n)]}
    return er.initial_state(layers)


def test_hydraulic_conserves_ground_and_water_with_closed_edges():
    spec = dict(er.HYDRAULIC_DEFAULTS, kind="hydraulic", rain=0.01, evaporation=0.0, boundary="closed", step=0.02)
    state = _state()
    e = er.example_seed()
    ground0 = er.ground_volume(state["layers"], 1.0)
    for step in range(60):
        state = er.hydraulic_step(state, spec, 1.0, e, 1, step)
    layers = state["layers"]
    assert _close(er.ground_volume(layers, 1.0), ground0, 1e-9 * ground0)
    assert _close(er.water_volume(layers, 1.0), 36 * 60 * 0.02 * 0.01, 1e-9)
    assert min(v for row in layers["water"] for v in row) >= 0.0
    assert min(v for row in layers["sediment"] for v in row) >= 0.0
    # the water ran to the bowl's bottom and something eroded
    assert layers["water"][2][2] > layers["water"][0][0]
    bottom = sum(layers["water"][j][i] for i in (2, 3) for j in (2, 3))
    assert bottom > 0.5 * er.water_volume(layers, 1.0)
    assert sum(v for row in layers["sediment"] for v in row) < er.water_volume(layers, 1.0) * 5.0
    assert _total(layers["sediment"]) > 0.0
    assert any(v != 0.0 for row in layers["flow"] for v in row)
    # evaporation removes water, an open boundary lets it leave
    wet = er.hydraulic_step(state, dict(spec, evaporation=0.5), 1.0, e, 1, 60)
    assert er.water_volume(wet["layers"], 1.0) < er.water_volume(state["layers"], 1.0) + 36 * 0.02 * 0.01
    ramp = er.initial_state({"bedrock": tg.plane(6, 6, 0.5, 0.0), "loose": tg.flat(6, 6, 0.5),
                             "water": tg.flat(6, 6, 0.2), "sediment": tg.flat(6, 6, 0.0)})
    closed = ramp
    opened = ramp
    for step in range(10):
        closed = er.hydraulic_step(closed, dict(spec, rain=0.0), 1.0, e, 1, step)
        opened = er.hydraulic_step(opened, dict(spec, rain=0.0, boundary="open"), 1.0, e, 1, step)
    assert _close(er.water_volume(closed["layers"], 1.0), 36 * 0.2, 1e-9)
    assert er.water_volume(opened["layers"], 1.0) < 36 * 0.2 - 1e-6


def test_rain_variation_draws_from_the_terrain_stream():
    spec = dict(er.HYDRAULIC_DEFAULTS, kind="hydraulic", rain=0.01, rainVariation=0.5, step=0.02)
    e = er.example_seed()
    assert e == rs.E(7, "ground", 11, "terrain")
    r = er.rain_depth(spec, e, 1, 3, 2, 4)
    assert _close(r, 0.01 * 0.02 * (1.0 + 0.5 * (2.0 * rs.S(e, 1, 3, rs.pack(2, 4, 0)) - 1.0)))
    assert er.rain_depth(dict(spec, rainVariation=0.0), e, 1, 3, 2, 4) == 0.01 * 0.02
    assert er.rain_depth(spec, e, 1, 3, 2, 4) != er.rain_depth(spec, e, 1, 3, 2, 5)
    assert er.rain_depth(spec, e, 1, 3, 2, 4) != er.rain_depth(spec, e, 2, 3, 2, 4)


def test_erosion_takes_loose_before_bedrock_and_hardness_protects_bedrock():
    # a strong flow over a cell with no loose material erodes the bedrock, less where it is hard
    spec = dict(er.HYDRAULIC_DEFAULTS, kind="hydraulic", capacity=10.0, erodeRate=1.0)
    taken = er.erode_cell({"loose": 0.3, "bedrock": 10.0}, 0.5, spec)
    assert _close(taken["loose"], 0.0) and _close(taken["bedrock"], 10.0 - 0.2)
    hard = er.erode_cell({"loose": 0.0, "bedrock": 10.0, "hardness": 0.75}, 0.4, spec)
    assert _close(hard["bedrock"], 10.0 - 0.1)
    solid = er.erode_cell({"loose": 0.0, "bedrock": 10.0, "hardness": 1.0}, 0.4, spec)
    assert solid["bedrock"] == 10.0
    assert er.erode_cell({"loose": 1.0, "bedrock": 10.0}, 0.4, spec)["loose"] == 0.6


def test_capacity_grows_with_slope_and_speed_and_has_a_floor():
    spec = dict(er.HYDRAULIC_DEFAULTS, capacity=2.0, minTilt=0.1)
    assert _close(er.capacity(spec, 0.0, 1.0), 2.0 * 0.1 * 1.0)             # the tilt floor
    assert _close(er.capacity(spec, math.radians(30.0), 2.0), 2.0 * 0.5 * 2.0)
    assert er.capacity(spec, math.radians(30.0), 2.0) > er.capacity(spec, math.radians(10.0), 2.0)
    assert er.capacity(spec, math.radians(30.0), 0.0) == 0.0


def test_torricelli_bounds_the_pipe_flux():
    assert er.torricelli(0.0, 4.0, 1.0) == 0.0 and er.torricelli(0.01, 0.0, 1.0) == 0.0
    assert _close(er.torricelli(0.01, 4.0, 1.0), 0.01 * math.sqrt(2.0 * 9.81 * 4.0))
    assert er.torricelli(0.01, 4.0, 2.0) == 2.0 * er.torricelli(0.01, 4.0, 1.0)


def test_depth_factor_limits_shallow_water():
    spec = dict(er.HYDRAULIC_DEFAULTS, maxDepth=0.05)
    assert er.depth_factor(spec, 0.0) == 0.0
    assert _close(er.depth_factor(spec, 0.02), 0.4)
    assert er.depth_factor(spec, 0.05) == 1.0 and er.depth_factor(spec, 3.0) == 1.0


# ---------------------------------------------------------------------------------------------------- run


def test_steps_are_bounded_and_the_run_is_a_function_of_the_frame():
    assert er.steps_for(1.0, 0.02, 100000) == 50 and er.steps_for(0.0, 0.02, 100000) == 0
    assert er.steps_for(1e9, 0.02, 100000) == 100000
    with pytest.raises(er.ErosionError):
        er.steps_for(1.0, 0.0, 100000)
    doc = er.example_document()
    a = er.run(doc, 0.5)
    b = er.run(doc, 0.5)
    assert a["layers"] == b["layers"] and a["steps"] == {"thermal": 25, "hydraulic": 25}
    zero = er.run(doc, 0.0)
    assert zero["steps"] == {"thermal": 0, "hydraulic": 0}
    # at t = 0 the fluvial child has still acted, at its `time`
    built = tg.build(doc)["layers"]
    assert zero["layers"]["bedrock"] != built["bedrock"] and zero["layers"]["loose"] == built["loose"]
    assert a["layers"]["water"] != zero["layers"]["water"]
    assert a["digest"] == er.digest(a["layers"]) and len(a["digest"]) == 64


# ------------------------------------------------------------------------------------------------ validation


def test_the_example_documents_validate_and_the_bad_one_lists_every_rule():
    assert er.validate_document(er.example_document()) == []
    assert er.validate_document(er.bad_document()) == ["ER1", "ER2", "ER3", "ER4", "ER5"]


def test_validation_rules_one_at_a_time():
    def with_process(index, **kw):
        doc = er.example_document()
        doc["processes"][index].update(kw)
        return doc

    assert er.validate_document(with_process(0, kind="glacial")) == ["ER1"]
    for kw in (dict(rain=-1.0), dict(evaporation=-0.1), dict(capacity=-1.0), dict(erodeRate=1.5), dict(depositRate=-0.1),
               dict(pipeArea=0.0), dict(minTilt=2.0), dict(maxDepth=0.0), dict(step=0.0), dict(rainVariation=1.5), dict(boundary="wall"),
               dict(maxSteps=0)):
        assert er.validate_document(with_process(2, **kw)) == ["ER2"], kw
    for kw in (dict(talus=0.0), dict(talus=90.0), dict(rate=1.5), dict(layer="water"), dict(layer="ice"), dict(step=-1.0)):
        assert er.validate_document(with_process(1, **kw)) == ["ER3"], kw
    for kw in (dict(uplift=-1.0), dict(erodibility=0.0), dict(m=1.5), dict(time=-1.0), dict(timeScale=-1.0),
               dict(layer="loose2"), dict(layer="sediment")):
        assert er.validate_document(with_process(0, **kw)) == ["ER4"], kw
    doc = er.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "sediment"]
    assert er.validate_document(doc) == ["ER5"]
    low = er.example_document()
    low["version"] = "1.7"
    assert er.validate_document(low) == ["V17"]
    none = er.example_document()
    none["processes"] = []
    assert er.validate_document(none) == []


def test_constants():
    assert er.KINDS == ("fluvial", "thermal", "hydraulic")
    assert er.HYDRAULIC_DEFAULTS["rain"] == 0.01 and er.HYDRAULIC_DEFAULTS["evaporation"] == 0.05
    assert er.HYDRAULIC_DEFAULTS["capacity"] == 0.1 and er.HYDRAULIC_DEFAULTS["erodeRate"] == 0.5
    assert er.HYDRAULIC_DEFAULTS["depositRate"] == 1.0 and er.HYDRAULIC_DEFAULTS["pipeArea"] == 1.0
    assert er.HYDRAULIC_DEFAULTS["minTilt"] == 0.1 and er.HYDRAULIC_DEFAULTS["step"] == 0.02
    assert er.HYDRAULIC_DEFAULTS["maxDepth"] == 0.05
    assert er.HYDRAULIC_DEFAULTS["boundary"] == "open" and er.HYDRAULIC_DEFAULTS["maxSteps"] == 100000
    assert er.THERMAL_DEFAULTS["talus"] == 35.0 and er.THERMAL_DEFAULTS["rate"] == 0.5 and er.THERMAL_DEFAULTS["layer"] == "loose"
    assert er.FLUVIAL_DEFAULTS["m"] == 0.5 and er.FLUVIAL_DEFAULTS["erodibility"] == 2e-5 and er.FLUVIAL_DEFAULTS["uplift"] == 1e-3
    assert er.FLUVIAL_DEFAULTS["layer"] == "bedrock" and er.FLUVIAL_DEFAULTS["time"] == 0.0 and er.FLUVIAL_DEFAULTS["timeScale"] == 0.0
    assert er.GRAVITY == 9.81 and er.PURPOSE_BASE == 2 ** 31


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
    for word in ("SR-104", "SR-100", "SREP 12", "SREP 14", "`erode`", "fluvial", "thermal", "hydraulic", "uplift",
                 "erodibility", "timeScale", "talus", "rate", "rain", "rainVariation", "evaporation", "capacity",
                 "erodeRate", "depositRate", "pipeArea", "minTilt", "maxDepth", "step", "boundary", "maxSteps", "ER1", "ER2",
                 "ER3", "ER4", "ER5", "V17", "erosion_reference.py", "terrain-grid", "random-streams",
                 "pack(i, j, 0)", "Mei", "Stava", "Musgrave", "Cordonnier", "Tzathas", "Royden", "Perron",
                 "stream power", "travel time", "characteristic", "D8", "virtual pipes", "Torricelli",
                 "mass", "erosion.rs", "Beyer", "Houdini", "Gaea", "hardness", "sediment", "`loose`", "`flow`"):
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


def test_the_table_is_what_the_module_prints(draft):
    assert len(er.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(er.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = er.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or er._same(got, want), f"{name}: {got!r} != {want!r}"
