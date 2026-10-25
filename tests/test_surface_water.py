"""Tests for the draft SREP "Add shallow-water flow to the terrain grid" (T2 of SREP 12) and its reference module."""
from __future__ import annotations

import importlib.util
import math
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "surface_water_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-surface-water.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load(MODULE, "surface_water_reference")
tg = sw.terrain()


def _close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def _total(rows):
    return sum(v for row in rows for v in row)


def _l1(a, b):
    num = sum(abs(x - y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))
    den = sum(abs(y) for rb in b for y in rb)
    return num / den


# ------------------------------------------------------------------------------------------- the scheme's pieces


def test_hydrostatic_reconstruction_keeps_a_lake_level_and_dries_an_island():
    # two wet cells at the same surface over different beds: equal reconstructed depths, zero flux
    left, right = sw.reconstruct(2.0, 0.5, 2.0, 1.0)
    assert _close(left, 1.0) and _close(right, 1.0)
    # a dry cell above the water: the wet side sees a wall at its own surface, the dry side nothing
    left, right = sw.reconstruct(2.0, 0.5, 3.0, 3.0)
    assert left == 0.0 and right == 0.0


def test_central_upwind_flux_is_the_exact_flux_for_equal_states_and_zero_for_still_water():
    h, u, v = 1.5, 0.7, -0.2
    f = sw.flux_x(h, u, v, h, u, v, 9.81)
    assert _close(f[0], h * u) and _close(f[1], h * u * u + 0.5 * 9.81 * h * h) and _close(f[2], h * u * v)
    f = sw.flux_x(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 9.81)
    assert f[0] == 0.0 and _close(f[1], 0.5 * 9.81) and f[2] == 0.0
    # a dry right state: the wave speeds come from the left only
    f = sw.flux_x(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81)
    assert f[0] > 0.0


def test_velocity_desingularisation_and_dry_cells():
    assert sw.velocity(1.0, 2.0, 1e-6) == 2.0
    assert sw.velocity(0.0, 0.0, 1e-6) == 0.0
    assert sw.velocity(1e-9, 1e-7, 1e-6) == 0.0            # under the tolerance, no velocity


def test_manning_friction_slows_the_flow_and_never_reverses_it():
    hu = sw.friction(1.0, 2.0, 0.03, 0.1, 9.81)
    assert 0.0 < hu < 2.0
    assert sw.friction(1.0, 2.0, 0.0, 0.1, 9.81) == 2.0
    assert sw.friction(1.0, -2.0, 0.03, 0.1, 9.81) == -hu


def test_minmod_limiter():
    assert sw.minmod(1.0, 2.0) == 1.0 and sw.minmod(-1.0, -3.0) == -1.0 and sw.minmod(1.0, -1.0) == 0.0


def test_substeps_follow_the_cfl_number():
    spec = dict(sw.DEFAULTS, step=0.1, cfl=0.5)
    state = sw.initial_state({"bedrock": tg.flat(10, 1, 0.0), "water": tg.flat(10, 1, 1.0)}, 1.0)
    n = sw.substeps(state, spec, 1.0)
    speed = math.sqrt(9.81)                                         # still water: the gravity wave only
    assert n == math.ceil(0.1 * speed / (0.5 * 1.0))
    assert sw.substeps(state, dict(spec, step=0.001), 1.0) == 1


# ------------------------------------------------------------------------------------------------- lake at rest


@pytest.mark.parametrize("order", [1, 2])
def test_lake_at_rest_over_a_bump_with_an_island_is_exact(order):
    nx, ny = 24, 6
    bed = [[0.2 * math.exp(-((i - 8) ** 2 + (j - 3) ** 2) / 6.0) + (1.5 if 16 <= i <= 18 and 2 <= j <= 3 else 0.0)
            for i in range(nx)] for j in range(ny)]
    water = [[max(0.0, 1.0 - bed[j][i]) for i in range(nx)] for j in range(ny)]
    spec = dict(sw.DEFAULTS, kind="shallowWater", order=order, step=0.05, manning=0.0)
    state = sw.initial_state({"bedrock": bed, "water": water, "flow": [[(0.0, 0.0)] * nx for _ in range(ny)]}, 1.0)
    for _ in range(40):
        state = sw.step(state, spec, 1.0)
    for j in range(ny):
        for i in range(nx):
            h = state["h"][j][i]
            if water[j][i] > 0.0:
                assert _close(h + bed[j][i], 1.0, 1e-12), (i, j)
            else:
                assert h == 0.0, (i, j)
            assert abs(state["hu"][j][i]) < 1e-12 and abs(state["hv"][j][i]) < 1e-12


# --------------------------------------------------------------------------------------------- Ritter dam break


def _ritter_case(order, nx=400):
    length, h_l = 20.0, 1.0
    dx = length / nx
    bed = tg.flat(nx, 1, 0.0)
    water = [[h_l if (i + 0.5) * dx < length / 2 else 0.0 for i in range(nx)]]
    spec = dict(sw.DEFAULTS, kind="shallowWater", order=order, step=0.01, manning=0.0, boundary="closed")
    state = sw.initial_state({"bedrock": bed, "water": water}, dx)
    for _ in range(100):                                            # t = 1 s
        state = sw.step(state, spec, dx)
    exact = [[sw.ritter((i + 0.5) * dx, 1.0, length / 2, h_l, 9.81)[0] for i in range(nx)]]
    return state, exact, dx, h_l, length


def test_ritter_solution_is_the_textbook_profile():
    g, h_l, x0, t = 9.81, 1.0, 10.0, 1.0
    c0 = math.sqrt(g * h_l)
    assert sw.ritter(x0 - 2.0 * c0 * t, t, x0, h_l, g) == (h_l, 0.0)             # still water behind
    assert sw.ritter(x0 + 3.0 * c0 * t, t, x0, h_l, g) == (0.0, 0.0)             # dry ahead of the front
    h, u = sw.ritter(x0, t, x0, h_l, g)
    assert _close(h, 4.0 / 9.0 * h_l) and _close(u, 2.0 / 3.0 * c0)              # the dam site
    assert _close(sw.ritter(x0 + 2.0 * c0 * t - 1e-9, t, x0, h_l, g)[0], 0.0, 1e-6)


@pytest.mark.parametrize("order,bound", [(1, 0.02), (2, 0.01)])
def test_ritter_dam_break_matches_the_analytic_solution(order, bound):
    state, exact, dx, h_l, length = _ritter_case(order)
    assert _l1(state["h"], exact) < bound
    assert _close(_total(state["h"]) * dx, h_l * length / 2, 1e-9)              # closed: mass kept
    front = max(i for i in range(len(state["h"][0])) if state["h"][0][i] > 1e-6) * dx
    exact_front = length / 2 + 2.0 * math.sqrt(9.81 * h_l)
    assert abs(front - exact_front) < 1.0
    assert min(state["h"][0]) >= 0.0


def test_second_order_is_closer_than_first_on_the_dam_break():
    s1, exact, *_ = _ritter_case(1)
    s2, *_ = _ritter_case(2)
    assert _l1(s2["h"], exact) < _l1(s1["h"], exact)


# ------------------------------------------------------------------------------------------------ Thacker bowl


def test_thacker_planar_solution_conserves_mass_and_oscillates():
    case = sw.thacker_case()
    omega = math.sqrt(2.0 * 9.81 * case["h0"]) / case["a"]
    assert _close(sw.thacker_period(case), 2.0 * math.pi / omega)
    xs = [(i + 0.5) * case["dx"] for i in range(case["nx"])]
    vol0 = sw.thacker_volume(0.0, case)
    for t in (0.3, 1.1, sw.thacker_period(case) / 4.0):
        assert _close(sw.thacker_volume(t, case), vol0, 1e-12 * vol0)           # the solution conserves mass
        assert _close(sum(sw.thacker(x, t, case)[0] for x in xs) * case["dx"], vol0, 1e-2 * vol0)
    assert all(sw.thacker(x, 0.0, case)[1] == 0.0 for x in xs)                 # starts at rest
    u_quarter = sw.thacker(case["L"] / 2.0, sw.thacker_period(case) / 4.0, case)[1]
    assert abs(u_quarter) > 0.1
    assert sw.thacker(0.01, sw.thacker_period(case) / 4.0, case) == (0.0, 0.0)  # dry at the rim


@pytest.mark.parametrize("order,bound", [(1, 0.05), (2, 0.01)])
def test_thacker_bowl_after_one_period(order, bound):
    case = sw.thacker_case()
    state, exact = sw.thacker_run(case, order, periods=1.0)
    assert _l1(state["h"], exact) < bound
    assert min(state["h"][0]) >= 0.0
    wet = [i for i in range(case["nx"]) if exact[0][i] > 0.0]
    assert state["h"][0][wet[len(wet) // 2]] > 0.5 * case["h0"]


# ------------------------------------------------------------------------------------------ SWASHES bump


def test_subcritical_bump_steady_state_matches_bernoulli():
    case = sw.bump_case()
    exact = [sw.bump_depth(x, case) for x in case["xs"]]
    assert _close(exact[-1], case["h_out"], 1e-9)
    assert min(exact) < case["h_out"] - 0.05                                     # the surface dips over the bump
    state = sw.bump_run(case, order=1)
    assert _l1([state["h"][0]], [exact]) < 0.01
    q = [state["hu"][0][i] for i in range(case["nx"])]
    assert max(abs(v - case["q"]) for v in q[2:-2]) < 0.05 * case["q"]


# ------------------------------------------------------------------------------------------ the element


def test_rain_and_sources_add_water_and_a_closed_grid_keeps_it():
    nx, ny, dx = 8, 8, 2.0
    spec = dict(sw.DEFAULTS, kind="shallowWater", rain=0.001, step=0.1, boundary="closed",
                sources=[{"x": 8.0, "y": 8.0, "radius": 3.0, "rate": 0.01, "start": 0.0, "end": 1.0}])
    state = sw.initial_state({"bedrock": tg.bowl(nx), "water": tg.flat(nx, nx, 0.0)}, dx)
    for n in range(20):                                                          # t = 2 s; the source stops at 1 s
        state = sw.step(state, spec, dx, n)
    rain = 0.001 * 2.0 * nx * ny * dx * dx
    cells = sum(1 for j in range(ny) for i in range(nx) if math.hypot((i + 0.5) * dx - 8.0, (j + 0.5) * dx - 8.0) <= 3.0)
    source = 0.01 * 1.0 * cells * dx * dx
    assert _close(_total(state["h"]) * dx * dx, rain + source, 1e-9)
    assert cells == sw.source_cells(spec["sources"][0], nx, ny, dx)
    assert state["h"][4][4] > state["h"][0][0]


def test_open_boundary_lets_water_leave():
    nx, dx = 10, 1.0
    spec = dict(sw.DEFAULTS, kind="shallowWater", step=0.05, boundary="open")
    state = sw.initial_state({"bedrock": tg.plane(nx, 1, 0.1, 0.0), "water": tg.flat(nx, 1, 0.2)}, dx)
    for _ in range(40):
        state = sw.step(state, spec, dx)
    assert _total(state["h"]) * dx < 0.2 * nx * dx - 1e-6


def test_run_writes_the_water_and_flow_layers_and_counts_steps():
    doc = sw.example_document()
    out = sw.run(doc, 0.5)
    assert out["steps"] == 25
    assert out["layers"]["water"] is not None and len(out["layers"]["flow"]) == len(out["layers"]["water"])
    assert all(isinstance(v, tuple) and len(v) == 2 for row in out["layers"]["flow"] for v in row)
    assert min(v for row in out["layers"]["water"] for v in row) >= 0.0
    assert out["digest"] == sw.run(doc, 0.5)["digest"]
    assert sw.run(doc, 0.0)["steps"] == 0
    assert isinstance(out["substeps"], int) and out["substeps"] >= 25


def test_steps_are_bounded_and_the_step_positive():
    assert sw.steps_for(0.5, 0.02, 100000) == 25
    assert sw.steps_for(10.0, 0.02, 100) == 100
    with pytest.raises(sw.SurfaceWaterError):
        sw.steps_for(1.0, 0.0, 10)


def test_validation_lists_the_rules():
    assert sw.validate_document(sw.example_document()) == []
    assert sw.validate_document(sw.bad_document()) == ["SW1", "SW2", "SW3", "SW4", "SW5"]
    doc = sw.example_document()
    doc["version"] = "1.7"
    assert sw.validate_document(doc) == ["V17"]


def test_validation_rules_one_at_a_time():
    def with_(**kw):
        doc = sw.example_document()
        doc["shallowWater"].update(kw)
        return doc

    for kw in (dict(order=3), dict(manning=-0.1), dict(cfl=0.0), dict(cfl=1.5), dict(rain=-1.0), dict(dryTolerance=0.0),
               dict(step=0.0), dict(maxSteps=0)):
        assert sw.validate_document(with_(**kw)) == ["SW1"], kw
    assert sw.validate_document(with_(boundary="periodic")) == ["SW5"]
    doc = sw.example_document()
    doc["processes"] = [{"kind": "hydraulic"}]
    assert sw.validate_document(doc) == ["SW2"]
    for src in (dict(radius=0.0), dict(rate=-1.0), dict(x=-1.0), dict(end=0.0, start=1.0)):
        doc = sw.example_document()
        doc["shallowWater"]["sources"] = [dict(sw.example_document()["shallowWater"]["sources"][0], **src)]
        assert sw.validate_document(doc) == ["SW3"], src
    doc = sw.example_document()
    doc["layers"] = [layer for layer in doc["layers"] if layer["kind"] != "water"]
    assert sw.validate_document(doc) == ["SW4"]


def test_constants():
    assert sw.DEFAULTS["order"] == 1 and sw.DEFAULTS["manning"] == 0.03 and sw.DEFAULTS["cfl"] == 0.5
    assert sw.DEFAULTS["rain"] == 0.0 and sw.DEFAULTS["dryTolerance"] == 1e-6 and sw.DEFAULTS["step"] == 0.02
    assert sw.DEFAULTS["boundary"] == "closed" and sw.DEFAULTS["maxSteps"] == 100000
    assert sw.GRAVITY == 9.81 and sw.BOUNDARIES == ("open", "closed")


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
    for word in ("SR-105", "SR-100", "SREP 12", "SREP 14", "SREP 40", "`shallowWater`", "`source`", "order", "manning",
                 "cfl", "rain", "dryTolerance", "step", "boundary", "maxSteps", "radius", "rate", "SW1", "SW2", "SW3",
                 "SW4", "SW5", "V17", "surface_water_reference.py", "terrain-grid", "Kurganov", "Petrova", "Audusse",
                 "hydrostatic reconstruction", "central-upwind", "well-balanced", "Ritter", "Thacker", "SWASHES",
                 "Delestre", "CeCILL", "Manning", "minmod", "Heun", "`water`", "`flow`", "lake at rest", "positivity",
                 "ocean/", "Stoker"):
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
    assert len(sw.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in sw.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = sw.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert sw._same(value, want), (name, value, want)
