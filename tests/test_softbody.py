"""Tests of the draft SREP "Add cloth and soft bodies in 3D" (srep/srep-0000-softbody.md) and of its reference
module conformance/tools/softbody_reference.py: the cloth sheet's springs and their projected Hessians, the
stable neo-Hookean tetrahedra, Vertex Block Descent with a fixed iteration count (free fall exact, the
hanging-sheet rest shape, no energy gain without forces, the block at rest and under gravity), offset contact
(vertex-triangle and edge-edge distances, a vertex stopped at the offset, zero self-intersections in the
twisting test), XPBD rods (a rope hanging straight, bounded stretch, straightening), the seek check, the
bounds, and the SREP's numeric table against the module.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "softbody_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-softbody.md")

spec = importlib.util.spec_from_file_location("softbody_reference", MODULE)
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)

H = 1.0 / 60.0
G = (0.0, -9.80665, 0.0)
ZERO = (0.0, 0.0, 0.0)


def _close(a, b, tol=1e-9):
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= tol
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


def _norm(v):
    return math.sqrt(sum(c * c for c in v))


# ------------------------------------------------------------------------------------ springs

def test_spring_energy_force_and_hessian():
    a, b = (0.0, 0.0, 0.0), (2.0, 0.0, 0.0)
    assert _close(sb.spring_energy(a, b, 1.0, 10.0), 5.0)
    assert _close(sb.spring_energy(a, b, 2.0, 10.0), 0.0)
    f = sb.spring_force(a, b, 1.0, 10.0)
    assert _close(f, (10.0, 0.0, 0.0))
    Hm = sb.spring_hessian(a, b, 1.0, 10.0)
    assert _close(Hm, ((10.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 0.0, 5.0)))
    Hc = sb.spring_hessian(a, (0.5, 0.0, 0.0), 1.0, 10.0)
    assert _close(Hc, ((10.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
    assert sb.is_psd(Hc)
    with pytest.raises(ValueError):
        sb.spring_energy(a, a, 1.0, 10.0)


def test_the_three_by_three_solve():
    A = ((4.0, 1.0, 0.0), (1.0, 3.0, 1.0), (0.0, 1.0, 2.0))
    x = sb.solve3(A, (1.0, 2.0, 3.0))
    back = tuple(sum(A[i][j] * x[j] for j in range(3)) for i in range(3))
    assert _close(back, (1.0, 2.0, 3.0), 1e-12)
    with pytest.raises(ValueError):
        sb.solve3(((1.0, 2.0, 3.0), (2.0, 4.0, 6.0), (0.0, 0.0, 1.0)), (1.0, 1.0, 1.0))


# ------------------------------------------------------------------------------------ the sheet

def test_the_sheet_mesh():
    sheet = sb.sheet(3, 4, 1.0, 1.5)
    assert len(sheet["positions"]) == 12
    assert len(sheet["triangles"]) == 2 * 2 * 3
    assert len(sheet["edges"]) == 3 * 3 + 2 * 4 + 6
    assert len(sheet["bends"]) == 6 + 3 * 2 + 1 * 4
    assert _close(sheet["positions"][0], (0.0, 0.0, 0.0))
    assert _close(sheet["positions"][11], (1.5, 0.0, -1.0))
    assert all(len(set(t)) == 3 for t in sheet["triangles"])
    assert sheet["masses"] == [1.0 / 12.0] * 12
    with pytest.raises(ValueError):
        sb.sheet(1, 4, 1.0, 1.0)
    with pytest.raises(ValueError):
        sb.sheet(sb.MAX_SIDE + 1, 2, 1.0, 1.0)


def test_pins():
    sheet = sb.sheet(3, 3, 1.0, 1.0)
    assert sb.pins(sheet, "top") == {0, 1, 2}
    assert sb.pins(sheet, "corners") == {0, 2}
    assert sb.pins(sheet, "none") == set()
    assert sb.pins(sheet, "ends") == {0, 1, 2, 6, 7, 8}
    with pytest.raises(ValueError):
        sb.pins(sheet, "middle")


# ------------------------------------------------------------------------------------ VBD

def test_free_fall_is_exact():
    body = sb.body(positions=[(0.0, 1.0, 0.0)], masses=[1.0], edges=[], bends=[], tets=[], pinned=set())
    state = sb.initial(body)
    for _ in range(10):
        state = sb.vbd_step(body, state, H, G, iterations=1)
    x, v = (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)
    for _ in range(10):
        x_new = tuple(x[k] + H * v[k] + H * H * G[k] for k in range(3))
        v = tuple((x_new[k] - x[k]) / H for k in range(3))
        x = x_new
    assert _close(state["positions"][0], x, 1e-12)
    assert _close(state["velocities"][0], v, 1e-12)


def test_a_pinned_vertex_does_not_move():
    body = sb.cloth_body(sb.sheet(2, 2, 1.0, 1.0), stiffness=50.0, bending=1.0, pin="top")
    state = sb.initial(body)
    for _ in range(20):
        state = sb.vbd_step(body, state, H, G, iterations=4)
    assert state["positions"][0] == body["positions"][0]
    assert state["positions"][1] == body["positions"][1]
    assert state["velocities"][0] == ZERO
    assert state["positions"][2][1] < 0.0


def test_the_hanging_sheet_comes_to_rest():
    body = sb.cloth_body(sb.sheet(5, 5, 1.0, 1.0), stiffness=200.0, bending=0.5, pin="top", damping=0.05)
    state = sb.run(body, 400, H, G, iterations=8)
    speed = max(_norm(v) for v in state["velocities"])
    assert speed < 1e-3
    residual = sb.residual(body, state, G)
    assert residual < 1e-2 * sb.weight(body, G)
    pins = sb.pins(sb.sheet(5, 5, 1.0, 1.0), "top")
    for i in pins:
        assert state["positions"][i] == body["positions"][i]
    bottom = [state["positions"][i] for i in range(20, 25)]
    assert all(p[1] < -0.5 for p in bottom)
    assert abs(bottom[2][1] - bottom[0][1]) < 1e-2  # the bottom row is level within 1 % of the height
    for row in range(5):
        left, right = state["positions"][row * 5], state["positions"][row * 5 + 4]
        assert abs(left[1] - right[1]) < 1e-4
        assert abs((left[0] - body["positions"][row * 5][0]) + (right[0] - body["positions"][row * 5 + 4][0])) < 1e-4


def test_no_energy_gain_without_forces():
    body = sb.cloth_body(sb.sheet(4, 4, 1.0, 1.0), stiffness=100.0, bending=0.5, pin="none")
    state = sb.initial(body)
    state["positions"] = [(1.2 * p[0], p[1] + 0.05 * math.sin(3.0 * p[0]), 1.1 * p[2]) for p in state["positions"]]
    energies = [sb.total_energy(body, state)]
    for _ in range(200):
        state = sb.vbd_step(body, state, H, ZERO, iterations=16)
        energies.append(sb.total_energy(body, state))
    assert energies[0] > 0.0
    assert all(b <= a * (1.0 + 1e-9) + 1e-12 for a, b in zip(energies, energies[1:]))
    assert energies[-1] < 0.1 * energies[0]
    assert sb.energy_gain(energies) <= 0.0


def test_iterations_and_substeps_are_bounded():
    body = sb.cloth_body(sb.sheet(2, 2, 1.0, 1.0), stiffness=50.0, bending=1.0, pin="top")
    state = sb.initial(body)
    with pytest.raises(ValueError):
        sb.vbd_step(body, state, H, G, iterations=0)
    with pytest.raises(ValueError):
        sb.vbd_step(body, state, H, G, iterations=sb.MAX_ITERATIONS + 1)
    with pytest.raises(ValueError):
        sb.run(body, 1, H, G, iterations=4, substeps=sb.MAX_SUBSTEPS + 1)
    with pytest.raises(ValueError):
        sb.run(body, sb.MAX_FRAMES + 1, H, G, iterations=4)


def test_the_run_is_a_function_of_the_frame():
    body = sb.cloth_body(sb.sheet(3, 3, 1.0, 1.0), stiffness=100.0, bending=0.5, pin="corners")
    whole = sb.run(body, 30, H, G, iterations=4, substeps=2)
    first = sb.run(body, 15, H, G, iterations=4, substeps=2)
    rest = sb.run(body, 15, H, G, iterations=4, substeps=2, state=first)
    assert whole == rest
    assert sb.run(body, 30, H, G, iterations=4, substeps=2) == whole


# ------------------------------------------------------------------------------------ neo-Hookean

def test_the_stable_neo_hookean_energy():
    mu, lam = 1.0, 10.0
    I3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    rest = sb.snh_energy(I3, mu, lam)
    assert _close(sb.snh_stress(I3, mu, lam), ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), 1e-12)
    for F in (((1.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
              ((1.0, 0.3, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
              ((0.5, 0.0, 0.0), (0.0, 0.5, 0.0), (0.0, 0.0, 0.5)),
              ((-0.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))):
        assert sb.snh_energy(F, mu, lam) > rest
        assert math.isfinite(sb.snh_energy(F, mu, lam))
    Fx = ((1.5, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    P = sb.snh_stress(Fx, mu, lam)
    eps = 1e-6
    Fp = ((1.5 + eps, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    Fm = ((1.5 - eps, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    assert abs(P[0][0] - (sb.snh_energy(Fp, mu, lam) - sb.snh_energy(Fm, mu, lam)) / (2.0 * eps)) < 1e-6
    assert _close(sb.lame(1000.0, 0.3), (1000.0 / 2.6, 1000.0 * 0.3 / (1.3 * 0.4)), 1e-9)
    with pytest.raises(ValueError):
        sb.lame(1000.0, 0.5)


def test_the_cube_of_tetrahedra():
    block = sb.block(1.0, 1.0, 1.0)
    assert len(block["positions"]) == 8 and len(block["tets"]) == 6
    assert _close(sum(sb.tet_volume(*(block["positions"][i] for i in t)) for t in block["tets"]), 1.0, 1e-12)
    assert all(sb.tet_volume(*(block["positions"][i] for i in t)) > 0.0 for t in block["tets"])
    assert _close(sum(block["masses"]), 1.0, 1e-12)


def test_the_block_at_rest_stays_and_recovers():
    body = sb.solid_body(sb.block(1.0, 1.0, 1.0), youngs=200.0, poisson=0.3, density=1.0, pin="none")
    state = sb.initial(body)
    for _ in range(5):
        state = sb.vbd_step(body, state, H, ZERO, iterations=4)
    assert all(_close(p, q, 1e-12) for p, q in zip(state["positions"], body["positions"]))
    state = sb.initial(body)
    state["positions"] = [(1.3 * p[0], 0.9 * p[1], p[2]) for p in state["positions"]]
    energies = [sb.total_energy(body, state)]
    for _ in range(300):
        state = sb.vbd_step(body, state, H, ZERO, iterations=8)
        energies.append(sb.total_energy(body, state))
    assert all(b <= a * (1.0 + 1e-9) + 1e-12 for a, b in zip(energies, energies[1:]))
    for i, j in ((0, 1), (0, 2), (0, 4), (6, 7)):
        rest = _norm(tuple(body["positions"][i][k] - body["positions"][j][k] for k in range(3)))
        now = _norm(tuple(state["positions"][i][k] - state["positions"][j][k] for k in range(3)))
        assert abs(now - rest) < 2e-3, (i, j)


def test_the_block_under_gravity_keeps_its_volume():
    body = sb.solid_body(sb.block(1.0, 1.0, 1.0), youngs=400.0, poisson=0.45, density=1.0, pin="bottom")
    state = sb.run(body, 240, H, G, iterations=8, damping=0.1)
    volume = sum(sb.tet_volume(*(state["positions"][i] for i in t)) for t in body["tets"])
    assert 0.97 < volume < 1.0
    top = [state["positions"][i][1] for i in range(4, 8)]
    assert all(0.9 < y < 1.0 for y in top)
    assert max(_norm(v) for v in state["velocities"]) < 1e-2


# ------------------------------------------------------------------------------------ contact

def test_point_triangle_distance():
    tri = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert _close(sb.point_triangle_distance((0.2, 0.5, 0.2), *tri)[0], 0.5)
    assert _close(sb.point_triangle_distance((-1.0, 0.0, 0.0), *tri)[0], 1.0)
    assert _close(sb.point_triangle_distance((2.0, 0.0, 2.0), *tri)[0], math.sqrt(2.0) * 1.5)
    d, closest = sb.point_triangle_distance((0.2, -0.3, 0.2), *tri)
    assert _close(d, 0.3) and _close(closest, (0.2, 0.0, 0.2))


def test_edge_edge_distance():
    d, p, q = sb.edge_edge_distance((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.5, 1.0, -1.0), (0.5, 1.0, 1.0))
    assert _close(d, 1.0) and _close(p, (0.5, 0.0, 0.0)) and _close(q, (0.5, 1.0, 0.0))
    d, p, q = sb.edge_edge_distance((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0))
    assert _close(d, 1.0)
    d, p, q = sb.edge_edge_distance((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (1.0, 2.0, 0.0))
    assert _close(d, 2.0)


def test_triangle_intersection():
    a = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    b = ((0.2, -0.5, 0.2), (0.3, 0.5, 0.2), (0.2, 0.5, 0.3))
    c = ((0.2, 0.5, 0.2), (0.3, 1.5, 0.2), (0.2, 1.5, 0.3))
    assert sb.triangles_intersect(a, b)
    assert not sb.triangles_intersect(a, c)
    assert sb.segment_triangle_intersects((0.2, -1.0, 0.2), (0.2, 1.0, 0.2), *a)
    assert not sb.segment_triangle_intersects((2.0, -1.0, 2.0), (2.0, 1.0, 2.0), *a)


def test_contact_stops_a_vertex_at_the_offset():
    base = sb.sheet(2, 2, 1.0, 1.0)
    positions = list(base["positions"]) + [(0.5, 0.3, -0.5)]
    body = sb.body(positions=positions, masses=[1.0] * 5, edges=[], bends=[], tets=[], pinned={0, 1, 2, 3},
                   triangles=base["triangles"], thickness=0.05, contact_stiffness=1e4)
    state = sb.initial(body)
    state["velocities"][4] = (0.0, -2.0, 0.0)
    lowest = 1.0
    for _ in range(60):
        state = sb.vbd_step(body, state, H, ZERO, iterations=8)
        lowest = min(lowest, state["positions"][4][1])
    assert lowest > 0.02
    assert state["positions"][4][1] > 0.0
    free = sb.body(positions=positions, masses=[1.0] * 5, edges=[], bends=[], tets=[], pinned={0, 1, 2, 3},
                   triangles=base["triangles"], thickness=0.0, contact_stiffness=0.0)
    state = sb.initial(free)
    state["velocities"][4] = (0.0, -2.0, 0.0)
    for _ in range(60):
        state = sb.vbd_step(free, state, H, ZERO, iterations=8)
    assert state["positions"][4][1] < 0.0


def test_the_twisting_strip_has_no_self_intersections():
    strip = sb.sheet(13, 3, 1.2, 0.3)
    body = sb.cloth_body(strip, stiffness=300.0, bending=0.2, pin="ends", thickness=0.03, contact_stiffness=2e3)
    result = sb.twist_test(body, turns=1.5, frames=90, H=H, iterations=6)
    assert result["intersections"] == 0
    assert result["contacts"] > 0
    assert result["max_stretch"] < 1.5
    assert result["frames"] == 90


# ------------------------------------------------------------------------------------ rods

def test_xpbd_distance_constraint():
    a, b = (0.0, 0.0, 0.0), (2.0, 0.0, 0.0)
    pa, pb, _ = sb.xpbd_distance(a, b, 1.0, 1.0, 1.0, 0.0, 0.0, H)
    assert _close(pa, (0.5, 0.0, 0.0)) and _close(pb, (1.5, 0.0, 0.0))
    pa, pb, _ = sb.xpbd_distance(a, b, 1.0, 1.0, 1.0, 0.0, 1.0, H)
    assert pa[0] < 0.5 and pb[0] > 1.5
    pa, pb, _ = sb.xpbd_distance(a, b, 1.0, 0.0, 1.0, 0.0, 0.0, H)
    assert pa == a and _close(pb, (1.0, 0.0, 0.0))


def test_a_rope_hangs_straight():
    rope = sb.rope(10, 1.0)
    assert len(rope["positions"]) == 10
    body = sb.rope_body(rope, stiffness=1e4, bending=0.0, pin="top", damping=0.1)
    state = sb.run_rope(body, 600, H, G, iterations=8, substeps=4)
    pin = state["positions"][0]
    assert pin == body["positions"][0]
    for p in state["positions"][1:]:
        assert abs(p[0] - pin[0]) < 1e-3 and abs(p[2] - pin[2]) < 1e-3
        assert p[1] < pin[1]
    length = sum(_norm(tuple(a[k] - b[k] for k in range(3))) for a, b in zip(state["positions"], state["positions"][1:]))
    assert 1.0 <= length < 1.02
    assert max(_norm(v) for v in state["velocities"]) < 1e-3


def test_bending_straightens_a_rod():
    rope = sb.rope(6, 1.0)
    body = sb.rope_body(rope, stiffness=1e4, bending=50.0, pin="top", damping=0.2)
    state = sb.initial(body)
    state["positions"] = [(0.2 * math.sin(2.0 * i), -i / 5.0, 0.0) for i in range(6)]
    state["positions"][0] = body["positions"][0]
    before = sb.rod_curvature(state["positions"])
    state = sb.run_rope(body, 200, H, ZERO, iterations=8, substeps=2, state=state)
    assert sb.rod_curvature(state["positions"]) < 0.2 * before
    assert sb.rod_curvature([(0.0, -i, 0.0) for i in range(4)]) == 0.0


def test_the_rope_run_is_a_function_of_the_frame():
    body = sb.rope_body(sb.rope(5, 1.0), stiffness=1e4, bending=1.0, pin="top")
    whole = sb.run_rope(body, 20, H, G, iterations=4, substeps=2)
    first = sb.run_rope(body, 10, H, G, iterations=4, substeps=2)
    rest = sb.run_rope(body, 10, H, G, iterations=4, substeps=2, state=first)
    assert whole == rest
    with pytest.raises(ValueError):
        sb.rope(1, 1.0)
    with pytest.raises(ValueError):
        sb.rope(sb.MAX_VERTICES + 1, 1.0)


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
    assert "SR-81" in draft
    for word in ("softBody3D", "cloth", "solid", "rope", "Vertex Block Descent", "neo-Hookean", "XPBD",
                 "thickness", "iterations", "V17", "seek check", "softbody_reference.py", "Smith", "Chen",
                 "hanging", "twisting", "energy"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [m.groups() for m in ROW.finditer(f.read())]
    rows = [r for r in rows if r[0] not in ("Test",)]
    return rows or [("empty table", "0", "1")]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 30


@pytest.mark.parametrize("name,expr,expected", _draft_rows(), ids=[r[0] for r in _draft_rows()])
def test_the_table_rows_hold(name, expr, expected):
    scope = sb.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert sb._same(got, want), (name, got, want)


def test_the_table_is_what_the_module_prints(draft, capsys):
    sb.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
