"""Tests of the draft SREP "Add combustion and sparse tiles to pyro" (srep/srep-0000-pyro-combustion.md) and of its
reference implementation conformance/tools/pyro_reference.py (S2 of SREP 12, SRC-38).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "pyro_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-pyro-combustion.md")

_spec = importlib.util.spec_from_file_location("pyro_reference", MODULE)
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

DT = 1.0 / 60.0


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _small(**kw):
    return pr.spec(dt=DT, **kw)


# ------------------------------------------------------------------------------------ the grid


def test_the_grid_is_cell_centred_with_face_velocities():
    g = pr.grid(4, 6, 5, 0.5)
    assert g["cells"] == (4, 6, 5)
    assert len(g["density"]) == 120 and len(g["temperature"]) == 120 and len(g["fuel"]) == 120
    assert len(g["velocity"][0]) == 5 * 6 * 5
    assert len(g["velocity"][1]) == 4 * 7 * 5
    assert len(g["velocity"][2]) == 4 * 6 * 6
    assert all(t == 300.0 for t in g["temperature"])
    assert g["step"] == 0
    assert pr.index((1, 2, 3), (4, 6, 5)) == 1 + 4 * (2 + 6 * 3)
    assert pr.coords(pr.index((1, 2, 3), (4, 6, 5)), (4, 6, 5)) == (1, 2, 3)


def test_the_grid_is_bounded():
    with pytest.raises(ValueError):
        pr.grid(0, 4, 4, 0.5)
    with pytest.raises(ValueError):
        pr.grid(4, 4, 4, 0.0)
    with pytest.raises(ValueError):
        pr.grid(2048, 2048, 2048, 0.5)
    pr.grid(1, 1, 1, 0.5)


def test_trilinear_sampling_reproduces_a_linear_field():
    g = pr.grid(4, 4, 4, 1.0)
    g["density"] = [float(pr.coords(k, g["cells"])[0]) for k in range(64)]
    assert _close(pr.sample(g, g["density"], (1.75, 2.0, 2.0)), 1.25)
    assert _close(pr.sample(g, g["density"], (-3.0, 2.0, 2.0)), 0.0)
    assert _close(pr.sample(g, g["density"], (9.0, 2.0, 2.0)), 3.0)


def test_face_velocities_interpolate_to_cell_centres():
    g = pr.grid(3, 3, 3, 1.0)
    g["velocity"][0] = [1.0] * len(g["velocity"][0])
    assert _close(pr.velocity_at(g, (1.5, 1.5, 1.5)), (1.0, 0.0, 0.0))
    assert _close(pr.velocity_at(g, (0.0, 1.5, 1.5)), (1.0, 0.0, 0.0))


# ------------------------------------------------------------------------------------ the spec


def test_spec_defaults_and_validation():
    s = pr.spec()
    assert s["dt"] == DT and s["boundary"] == "closed" and s["advection"] == "semilagrangian"
    assert s["iterations"] == 200 and s["tolerance"] == 1e-6 and s["combustion"] is None and s["tile"] == 0
    for bad in (dict(dt=0.0), dict(boundary="sealed"), dict(advection="bfecc"), dict(iterations=0),
                dict(iterations=pr.MAX_ITERATIONS + 1), dict(tolerance=0.0), dict(buoyancy=-1.0),
                dict(vorticity=-1.0), dict(dissipation=-1.0), dict(cooling=-1.0), dict(tile=2),
                dict(tile=pr.MAX_TILE * 2), dict(tile=8, margin=-1), dict(threshold=0.0)):
        with pytest.raises(ValueError):
            pr.spec(**bad)


def test_combustion_validation():
    c = pr.combustion(ignition=600.0, rate=20.0, heat=2000.0, expansion=0.5, soot=0.2)
    assert c["ignition"] == 600.0
    for bad in (dict(ignition=0.0), dict(rate=-1.0), dict(heat=-1.0), dict(expansion=-1.0), dict(soot=-1.0)):
        kw = dict(ignition=600.0, rate=20.0, heat=2000.0, expansion=0.5, soot=0.2)
        kw.update(bad)
        with pytest.raises(ValueError):
            pr.combustion(**kw)


def test_source_shapes_and_timing():
    s = pr.source(("sphere", (1.0, 1.0, 1.0), 0.5), density_rate=1.0)
    assert pr.inside(s, (1.2, 1.0, 1.0)) and not pr.inside(s, (1.6, 1.0, 1.0))
    b = pr.source(("box", (0.0, 0.0, 0.0), (1.0, 2.0, 3.0)), fuel_rate=1.0, start=1.0, end=2.0)
    assert pr.inside(b, (0.5, 1.5, 2.5)) and not pr.inside(b, (1.5, 1.5, 2.5))
    assert not pr.active(b, 0.5) and pr.active(b, 1.0) and pr.active(b, 1.5) and not pr.active(b, 2.0)
    with pytest.raises(ValueError):
        pr.source(("cone", (0.0, 0.0, 0.0), 1.0))
    with pytest.raises(ValueError):
        pr.source(("sphere", (0.0, 0.0, 0.0), 1.0), density_rate=-1.0)


# ------------------------------------------------------------------------------------ advection


def test_semi_lagrangian_translates_a_blob():
    g = pr.grid(12, 4, 4, 1.0)
    g["density"][pr.index((3, 1, 1), g["cells"])] = 1.0
    g["velocity"][0] = [60.0] * len(g["velocity"][0])
    out = pr.advect(g, _small())
    assert _close(out["density"][pr.index((4, 1, 1), g["cells"])], 1.0)
    assert _close(out["density"][pr.index((3, 1, 1), g["cells"])], 0.0)


def test_maccormack_creates_no_new_extremum():
    g = pr.grid(12, 4, 4, 1.0)
    for i in range(3, 7):
        g["density"][pr.index((i, 1, 1), g["cells"])] = 1.0
    g["velocity"][0] = [20.0] * len(g["velocity"][0])
    out = pr.advect(g, _small(advection="maccormack"))
    assert max(out["density"]) <= 1.0 + 1e-12 and min(out["density"]) >= -1e-12
    plain = pr.advect(g, _small())
    assert sum(abs(a - b) for a, b in zip(out["density"], plain["density"])) > 0.0


def test_dissipation_and_cooling_decay_exponentially():
    g = pr.grid(4, 4, 4, 1.0)
    k = pr.index((1, 1, 1), g["cells"])
    g["density"][k] = 1.0
    g["temperature"][k] = 500.0
    out = pr.advect(g, _small(dissipation=3.0, cooling=6.0))
    assert _close(out["density"][k], math.exp(-3.0 * DT))
    assert _close(out["temperature"][k], 300.0 + 200.0 * math.exp(-6.0 * DT))


# ------------------------------------------------------------------------------------ sources and combustion


def test_sources_add_rates_over_the_step():
    g = pr.grid(8, 8, 8, 1.0)
    src = pr.source(("sphere", (4.0, 4.0, 4.0), 1.2), density_rate=3.0, temperature_rate=600.0, fuel_rate=1.5,
                    expansion=0.5)
    target = pr.apply_sources(g, _small(), [src], 0.0)
    k = pr.index((4, 4, 4), g["cells"])
    assert _close(g["density"][k], 3.0 * DT) and _close(g["temperature"][k], 300.0 + 600.0 * DT)
    assert _close(g["fuel"][k], 1.5 * DT) and _close(target[k], 0.5)
    assert g["density"][pr.index((0, 0, 0), g["cells"])] == 0.0 and target[pr.index((0, 0, 0), g["cells"])] == 0.0


def test_combustion_burns_only_hot_fuel():
    g = pr.grid(4, 4, 4, 1.0)
    c = pr.combustion(ignition=600.0, rate=20.0, heat=2000.0, expansion=0.5, soot=0.2)
    hot, cold = pr.index((1, 1, 1), g["cells"]), pr.index((2, 2, 2), g["cells"])
    g["fuel"][hot] = g["fuel"][cold] = 1.0
    g["temperature"][hot] = 700.0
    target = [0.0] * 64
    pr.burn(g, _small(combustion=c), target)
    burnt = 1.0 - math.exp(-20.0 * DT)
    assert _close(g["fuel"][hot], 1.0 - burnt)
    assert _close(g["temperature"][hot], 700.0 + 2000.0 * burnt)
    assert _close(g["density"][hot], 0.2 * burnt)
    assert _close(target[hot], 0.5 * burnt / DT)
    assert g["fuel"][cold] == 1.0 and g["temperature"][cold] == 300.0 and g["density"][cold] == 0.0


def test_combustion_conserves_fuel_plus_burnt():
    r = pr.combustion_test(steps=40)
    assert r["fuel_left"] + r["burnt"] == pytest.approx(r["fuel_added"], rel=1e-9)
    assert r["burnt"] > 0.5 * r["fuel_added"]
    assert r["peak_temperature"] > 1000.0
    assert r["soot"] == pytest.approx(0.2 * r["burnt"], rel=1e-9)


def test_without_combustion_fuel_is_only_carried():
    r = pr.combustion_test(steps=20, burn_fuel=False)
    assert r["burnt"] == 0.0 and r["fuel_left"] == pytest.approx(r["fuel_added"], rel=1e-9)


# ------------------------------------------------------------------------------------ forces


def test_buoyancy_accelerates_hot_cells_against_y():
    g = pr.grid(4, 6, 4, 1.0)
    k = pr.index((1, 3, 1), g["cells"])
    g["temperature"][k] = 400.0
    pr.forces(g, _small(buoyancy=2.0), (0.0, 0.0, 0.0))
    faces = g["velocity"][1]
    lo = faces[pr.index((1, 3, 1), (4, 7, 4))]
    hi = faces[pr.index((1, 4, 1), (4, 7, 4))]
    assert lo < 0.0 and hi < 0.0 and _close(lo, -2.0 * 100.0 * DT * 0.5) and _close(hi, lo)
    assert all(v == 0.0 for v in g["velocity"][0]) and all(v == 0.0 for v in g["velocity"][2])


def test_vorticity_confinement_is_zero_in_rigid_rotation_and_rest():
    g = pr.grid(6, 6, 6, 1.0)
    pr.forces(g, _small(vorticity=1.0), (0.0, 0.0, 0.0))
    assert all(v == 0.0 for axis in g["velocity"] for v in axis)
    curl = pr.curl(g)
    assert all(c == (0.0, 0.0, 0.0) for c in curl)


def test_vorticity_confinement_pushes_toward_the_vortex_core():
    r = pr.confinement_test()
    assert r["curl_peak"] > 0.0
    assert r["confined_peak"] > r["plain_peak"]


# ------------------------------------------------------------------------------------ projection


def test_divergence_of_a_uniform_field_is_zero():
    g = pr.grid(4, 4, 4, 0.5)
    g["velocity"][0] = [1.0] * len(g["velocity"][0])
    assert all(d == 0.0 for d in pr.divergence(g))


def test_projection_removes_divergence_to_the_tolerance():
    r = pr.divergence_test()
    assert r["before"] > 1.0
    assert r["after"] <= 1e-6
    assert r["iterations"] <= 200
    assert r["worst_cell"] <= 1e-5


def test_projection_meets_a_divergence_target():
    g = pr.grid(6, 6, 6, 1.0)
    target = [0.0] * 216
    target[pr.index((3, 3, 3), g["cells"])] = 2.0
    its, residual = pr.project(g, _small(boundary="open"), target)
    d = pr.divergence(g)
    assert _close(d[pr.index((3, 3, 3), g["cells"])], 2.0, 1e-5)
    assert residual <= 1e-6


def test_a_closed_domain_cannot_expand():
    g = pr.grid(4, 4, 4, 1.0)
    target = [1.0] * 64
    with pytest.raises(pr.ProjectionError):
        pr.project(g, _small(boundary="closed"), target)


def test_closed_walls_carry_no_flow():
    g = pr.grid(4, 4, 4, 1.0)
    g["velocity"][0] = [1.0] * len(g["velocity"][0])
    pr.project(g, _small(boundary="closed"), [0.0] * 64)
    dims = (5, 4, 4)
    for j in range(4):
        for k in range(4):
            assert g["velocity"][0][pr.index((0, j, k), dims)] == 0.0
            assert g["velocity"][0][pr.index((4, j, k), dims)] == 0.0


def test_the_projection_is_bounded():
    g = pr.grid(6, 6, 6, 1.0)
    g["velocity"][0] = [math.sin(float(i)) for i in range(len(g["velocity"][0]))]
    with pytest.raises(pr.ProjectionError):
        pr.project(g, _small(boundary="open", iterations=1, tolerance=1e-12), [0.0] * 216)


# ------------------------------------------------------------------------------------ the step and the plume


def test_the_step_is_a_function_of_the_count():
    g = pr.grid(6, 8, 6, 1.0)
    s = _small(buoyancy=0.05, vorticity=0.5, boundary="open")
    src = [pr.source(("sphere", (3.0, 1.5, 3.0), 1.1), density_rate=2.0, temperature_rate=300.0)]
    whole = pr.run(g, s, src, 12)
    half = pr.run(pr.run(g, s, src, 6), s, src, 6)
    assert whole == half
    assert whole["step"] == 12


def test_run_is_bounded():
    g = pr.grid(4, 4, 4, 1.0)
    with pytest.raises(ValueError):
        pr.run(g, _small(), [], pr.MAX_STEPS + 1)
    with pytest.raises(ValueError):
        pr.run(g, _small(), [], -1)


def test_the_plume_rises_and_stays_symmetric():
    r = pr.symmetric_plume(steps=30)
    assert r["mirror_x"] <= 1e-7 * r["peak"]
    assert r["mirror_z"] <= 1e-7 * r["peak"]
    assert r["centroid_y"] < 10.0
    assert r["peak"] > 0.0


def test_the_step_with_maccormack_is_symmetric_too():
    r = pr.symmetric_plume(steps=20, advection="maccormack")
    assert r["mirror_x"] <= 1e-7 * r["peak"] and r["mirror_z"] <= 1e-7 * r["peak"]


def test_a_fire_rises_faster_than_smoke():
    r = pr.fire_test(steps=30)
    assert r["fire_centroid_y"] < r["smoke_centroid_y"]
    assert r["fire_peak_temperature"] > r["smoke_peak_temperature"]
    assert r["burnt"] > 0.0


# ------------------------------------------------------------------------------------ sparse tiles


def test_active_tiles_cover_the_smoke_and_its_margin():
    g = pr.grid(16, 16, 16, 1.0)
    s = _small(tile=4, margin=1)
    assert pr.active_tiles(g, s) == set()
    g["density"][pr.index((5, 5, 5), g["cells"])] = 1.0
    tiles = pr.active_tiles(g, s)
    assert (1, 1, 1) in tiles and (0, 0, 0) in tiles and (2, 2, 2) in tiles and (3, 3, 3) not in tiles
    assert len(tiles) == 27
    g2 = pr.grid(16, 16, 16, 1.0)
    g2["velocity"][1][pr.index((13, 13, 13), (16, 17, 16))] = 1.0
    assert pr.active_tiles(g2, s) == set()
    g3 = pr.grid(16, 16, 16, 1.0)
    g3["temperature"][pr.index((1, 1, 1), g3["cells"])] = 300.0 * (1.0 + 1e-7)
    g3["density"][pr.index((9, 9, 9), g3["cells"])] = 1e-7
    assert pr.active_tiles(g3, s) == set()
    g3["temperature"][pr.index((1, 1, 1), g3["cells"])] = 300.0 * (1.0 + 1e-5)
    assert (0, 0, 0) in pr.active_tiles(g3, s)


def test_the_sparse_step_clears_the_air_outside_its_tiles():
    g = pr.grid(16, 16, 16, 1.0)
    g["density"][pr.index((5, 5, 5), g["cells"])] = 1.0
    g["velocity"][0][pr.index((15, 15, 15), (17, 16, 16))] = 1.0
    out = pr.step(g, _small(tile=4, margin=1, boundary="open"), [])
    assert out["velocity"][0][pr.index((15, 15, 15), (17, 16, 16))] == 0.0


def test_tiles_divide_the_grid_or_the_spec_is_refused():
    g = pr.grid(12, 12, 12, 1.0)
    with pytest.raises(ValueError):
        pr.run(g, _small(tile=8), [], 1)
    pr.run(g, _small(tile=4), [], 1)


def test_the_sparse_step_matches_the_dense_step_inside_the_margin():
    r = pr.sparse_test(steps=12)
    assert r["active_fraction"] < 0.6
    assert r["max_difference"] <= 1e-3 * r["peak"]
    assert r["dense_peak"] == pytest.approx(r["peak"], rel=1e-3)


def test_the_sparse_run_is_a_function_of_the_count():
    g = pr.grid(16, 16, 16, 1.0)
    s = _small(tile=4, margin=1, boundary="open", buoyancy=0.05)
    src = [pr.source(("sphere", (8.0, 4.0, 8.0), 1.5), density_rate=2.0, temperature_rate=300.0)]
    assert pr.run(g, s, src, 6) == pr.run(pr.run(g, s, src, 3), s, src, 3)


# ------------------------------------------------------------------------------------ the draft


@pytest.fixture(scope="module")
def draft():
    assert os.path.exists(DRAFT), "the draft SREP is missing"
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    assert draft.startswith("```\nSREP:            0\n")
    assert "Status:          Draft" in draft
    assert "Schema-Version:  1.8" in draft
    for section in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Semantics",
                    "## Rationale", "## Rejected alternatives", "## Backwards compatibility", "## Engine impact",
                    "## Conformance", "### Numeric tests", "### Kit cases", "## Open issues", "## References",
                    "## History"):
        assert section in draft, section
    assert "... no" not in draft


def test_the_draft_names_the_engine_card_and_the_elements(draft):
    assert "SR-82" in draft
    for word in ("pyroCombustion", "fuelRate", "ignition", "tile", "margin", "MacCormack", "vorticity", "divergence",
                 "symmetric", "blackbody", "V17", "seek check", "pyro_reference.py", "Fedkiw", "Selle", "Bridson",
                 "Nguyen", "Setaluri"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows(), ids=[r[0] for r in _draft_rows()])
def test_the_table_rows_hold(name, expr, expected):
    scope = pr.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert got == want or pr._same(got, want), name


def test_the_table_is_what_the_module_prints(draft, capsys):
    pr.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
