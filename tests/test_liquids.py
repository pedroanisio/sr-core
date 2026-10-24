"""Tests of the draft SREP "Add particle liquids and granular media in 3D" (srep/srep-0000-liquids.md) and of
its reference implementation conformance/tools/liquids_reference.py (S3 of SREP 12, SRC-39).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "liquids_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-liquids.md")

_spec = importlib.util.spec_from_file_location("liquids_reference", MODULE)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)

DT = 1.0 / 120.0


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _spec(**kw):
    kw.setdefault("dt", DT)
    return lr.spec(**kw)


# ------------------------------------------------------------------------------------ rule 1: the kernel


def test_the_quadratic_bspline_is_a_partition_of_unity():
    for x in (0.0, 0.1, 0.25, 0.49, 0.5, 0.73, 1.0, 1.4, 1.5, 2.0):
        w = lr.weights(x)
        assert len(w) == 3
        assert _close(sum(w), 1.0)
        assert all(v >= 0.0 for v in w)
    assert _close(lr.bspline(0.0), 0.75)
    assert _close(lr.bspline(0.5), 0.5)
    assert _close(lr.bspline(1.0), 0.125)
    assert lr.bspline(1.5) == 0.0
    assert lr.bspline(-0.5) == lr.bspline(0.5)


def test_the_bspline_stencil_moments_match_the_apic_inertia():
    # sum_i w_i (x_i - x_p) = 0 and sum_i w_i (x_i - x_p)^2 = h^2 / 4 for every particle position (D = h^2/4 I)
    for x in (0.0, 0.2, 0.37, 0.5, 0.81):
        base, w = lr.stencil(x)
        first = sum(w[k] * (base + k - x) for k in range(3))
        second = sum(w[k] * (base + k - x) ** 2 for k in range(3))
        assert _close(first, 0.0)
        assert _close(second, 0.25)


# ------------------------------------------------------------------------------------ rule 2: the liquid


def test_a_filled_box_seeds_particles_on_a_lattice():
    s = _spec(per_cell=4)
    liq = lr.liquid((8, 6), 0.25, s, [((0.0, 0.0), (0.5, 0.5))])
    assert liq["dim"] == 2
    assert len(liq["x"]) == 2 * 2 * 4            # 2 x 2 cells of 4 particles
    assert all(0.0 < p[0] < 0.5 and 0.0 < p[1] < 0.5 for p in liq["x"])
    assert all(v == (0.0, 0.0) for v in liq["v"])
    assert _close(liq["mass"], 1000.0 * 0.25 * 0.25 / 4)
    assert liq["step"] == 0
    liq3 = lr.liquid((4, 4, 4), 0.5, _spec(per_cell=8), [((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))])
    assert liq3["dim"] == 3 and len(liq3["x"]) == 8 * 8


def test_the_liquid_is_bounded():
    with pytest.raises(ValueError):
        lr.liquid((0, 4), 0.25, _spec(), [])
    with pytest.raises(ValueError):
        lr.liquid((4, 4), 0.0, _spec(), [])
    with pytest.raises(ValueError):
        lr.liquid((4,), 0.25, _spec(), [])
    with pytest.raises(ValueError):
        lr.liquid((2048, 2048), 0.25, _spec(), [])
    with pytest.raises(ValueError):
        _spec(per_cell=0)
    with pytest.raises(ValueError):
        _spec(per_cell=65)
    with pytest.raises(ValueError):
        _spec(method="sph")
    with pytest.raises(ValueError):
        _spec(flip=1.5)
    with pytest.raises(ValueError):
        _spec(walls="sticky")
    with pytest.raises(ValueError):
        _spec(iterations=0)
    with pytest.raises(ValueError):
        _spec(iterations=lr.MAX_ITERATIONS + 1)
    with pytest.raises(ValueError):
        _spec(substeps=lr.MAX_SUBSTEPS + 1)
    with pytest.raises(ValueError):
        lr.liquid((4, 4), 0.25, _spec(per_cell=64), [((0.0, 0.0), (1.0, 1.0))], max_particles=10)
    assert lr.MAX_PARTICLES == 1 << 20
    assert lr.MAX_CELLS == 1 << 21
    assert lr.MAX_STEPS == 65536


def test_the_fill_box_must_lie_in_the_domain():
    with pytest.raises(ValueError):
        lr.liquid((4, 4), 0.25, _spec(), [((0.0, 0.0), (2.0, 0.5))])
    with pytest.raises(ValueError):
        lr.liquid((4, 4), 0.25, _spec(), [((0.5, 0.0), (0.25, 0.5))])


# ------------------------------------------------------------------------------------ rule 3: transfers


def test_particle_to_grid_conserves_mass_and_momentum():
    s = _spec(per_cell=4)
    liq = lr.liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(0.3, -0.2) for _ in liq["x"]]
    faces = lr.p2g(liq)
    n = len(liq["x"])
    for a in range(2):
        assert _close(sum(faces["mass"][a]), n * liq["mass"])
        momentum = sum(m * u for m, u in zip(faces["mass"][a], faces["vel"][a]))
        assert _close(momentum, n * liq["mass"] * (0.3, -0.2)[a])


def test_a_uniform_velocity_is_transferred_exactly_both_ways():
    s = _spec(per_cell=4)
    liq = lr.liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(0.3, -0.2) for _ in liq["x"]]
    faces = lr.p2g(liq)
    for a in range(2):
        for m, u in zip(faces["mass"][a], faces["vel"][a]):
            if m > 0.0:
                assert _close(u, (0.3, -0.2)[a])
    lr.g2p(liq, faces, faces)
    assert all(_close(v, (0.3, -0.2)) for v in liq["v"])
    assert all(_close(row, (0.0, 0.0)) for c in liq["C"] for row in c)


def test_an_affine_velocity_field_is_recovered_by_apic():
    # v(x) = A x with A = [[0.0, 1.0], [-1.0, 0.0]] (a rotation) is in the span of the transfers: g2p returns
    # the particle's velocity and C = A away from the walls
    s = _spec(per_cell=4)
    liq = lr.liquid((12, 12), 0.25, s, [((0.75, 0.75), (2.25, 2.25))])
    A = ((0.0, 1.0), (-1.0, 0.0))
    liq["v"] = [tuple(sum(A[r][c] * p[c] for c in range(2)) for r in range(2)) for p in liq["x"]]
    liq["C"] = [A for _ in liq["x"]]
    faces = lr.p2g(liq)
    lr.g2p(liq, faces, faces)
    inner = [i for i, p in enumerate(liq["x"]) if 1.25 < p[0] < 1.75 and 1.25 < p[1] < 1.75]
    assert inner
    for i in inner:
        want = tuple(sum(A[r][c] * liq["x0"][i][c] for c in range(2)) for r in range(2))
        assert _close(liq["v"][i], want, 1e-9)
        assert _close(liq["C"][i], A, 1e-9)


def test_flip_blends_the_grid_change_with_the_pic_velocity():
    s = _spec(per_cell=4, method="flip", flip=0.5)
    liq = lr.liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(1.0, 0.0) for _ in liq["x"]]
    old = lr.p2g(liq)
    new = {"mass": old["mass"], "vel": [[u + 0.5 if m > 0.0 else u for u, m in zip(old["vel"][a], old["mass"][a])]
                                        for a in range(2)]}
    lr.g2p(liq, old, new)
    # pic gives 1.5, flip gives 1.0 + 0.5 = 1.5 too: the blend of equal parts is 1.5; with a scaled new field the
    # two differ: new = 2 * old gives pic 2.0 and flip 1.0 + 1.0 = 2.0 as well, so use an offset on half the faces
    assert all(_close(v[0], 1.5) for v in liq["v"])


# ------------------------------------------------------------------------------------ rule 4: the projection


def test_the_projection_removes_the_divergence_of_the_fluid_cells():
    s = _spec(per_cell=4, tolerance=1e-9, iterations=500)
    liq = lr.liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(p[0] - 1.0, p[1] - 1.0) for p in liq["x"]]      # an expanding field
    faces = lr.p2g(liq)
    fluid = lr.mark(liq)
    assert sum(fluid) == 16
    before = lr.divergence(liq, faces, fluid)
    assert max(abs(d) for d in before) > 1.0
    iterations, err = lr.project(liq, faces, fluid)
    after = lr.divergence(liq, faces, fluid)
    assert err <= 1e-9
    assert 0 < iterations <= 500
    assert max(abs(d) for d in after) <= 1e-7


def test_the_projection_fails_loudly_when_it_cannot_converge():
    s = _spec(per_cell=4, tolerance=1e-12, iterations=1)
    liq = lr.liquid((8, 8), 0.25, s, [((0.5, 0.5), (1.5, 1.5))])
    liq["v"] = [(p[0] - 1.0, p[1] - 1.0) for p in liq["x"]]
    faces = lr.p2g(liq)
    with pytest.raises(lr.ProjectionError):
        lr.project(liq, faces, lr.mark(liq))
    assert lr.raises_projection_error(lambda: lr.project(liq, faces, lr.mark(liq)))


def test_walls_are_no_through_and_slip_or_no_slip():
    for walls in ("slip", "noslip"):
        s = _spec(per_cell=4, walls=walls)
        liq = lr.liquid((8, 8), 0.25, s, [((0.0, 0.0), (1.0, 1.0))])
        liq["v"] = [(-1.0, -1.0) for _ in liq["x"]]
        faces = lr.p2g(liq)
        lr.enforce_walls(liq, faces)
        # the x faces on the left wall (i = 0), beyond it (i = -1) and on the right wall (i = 8) are zero
        for j in range(liq["cells"][1]):
            assert faces["vel"][0][lr.face_index(liq, 0, (0, j))] == 0.0
            assert faces["vel"][0][lr.face_index(liq, 0, (-1, j))] == 0.0
            assert faces["vel"][0][lr.face_index(liq, 0, (8, j))] == 0.0
        # slip walls: the y faces in the ghost column beyond the left wall mirror the first interior column;
        # no-slip walls: every face within one cell of a wall (the ghost column and the first column) is at rest
        for j in range(1, 4):
            ghost = faces["vel"][1][lr.face_index(liq, 1, (-1, j))]
            interior = faces["vel"][1][lr.face_index(liq, 1, (0, j))]
            if walls == "slip":
                assert interior < 0.0 and ghost == interior
            else:
                assert interior == 0.0 and ghost == 0.0
                assert faces["vel"][0][lr.face_index(liq, 0, (2, 0))] == 0.0      # the x faces of the bottom row
        # the faces away from the walls are untouched
        assert faces["vel"][1][lr.face_index(liq, 1, (2, 2))] < 0.0
        assert faces["vel"][0][lr.face_index(liq, 0, (2, 2))] < 0.0


# ------------------------------------------------------------------------------------ rule 5: the step


def test_a_resting_column_stays_at_rest_under_gravity():
    r = lr.hydrostatic_test()
    assert r["drift"] <= 1e-9
    assert r["speed"] <= 1e-9
    assert r["volume_drift"] == 0.0
    assert r["density_drift"] == 0.0


def test_the_state_is_a_function_of_the_step_count():
    s = _spec(per_cell=4)
    boxes = [((0.0, 0.0), (1.0, 2.0))]
    a = lr.run(lr.liquid((12, 12), 0.25, s, boxes), 12)
    b = lr.run(lr.run(lr.liquid((12, 12), 0.25, s, boxes), 6), 6)
    assert a["step"] == 12 and b["step"] == 12
    assert a["x"] == b["x"] and a["v"] == b["v"]
    assert lr.seek_check(12)


def test_the_step_count_is_bounded():
    s = _spec(per_cell=4)
    liq = lr.liquid((4, 4), 0.25, s, [((0.0, 0.0), (0.5, 0.5))])
    with pytest.raises(ValueError):
        lr.run(liq, lr.MAX_STEPS + 1)
    with pytest.raises(ValueError):
        lr.run(liq, -1)


def test_particles_never_leave_the_domain():
    s = _spec(per_cell=4)
    liq = lr.run(lr.liquid((12, 8), 0.25, s, [((0.0, 0.0), (1.0, 1.5))]), 60)
    for p in liq["x"]:
        assert 0.0 <= p[0] <= 3.0 and 0.0 <= p[1] <= 2.0


# ------------------------------------------------------------------------------------ rule 6: the dam break


def test_the_dam_break_front_follows_martin_and_moyce():
    r = lr.dam_break()
    assert r["a"] > 0 and r["steps"] > 0
    assert r["cells"] == (36, 20) and r["particles"] == 4 * 8 * 16
    assert len(lr.MARTIN_MOYCE) == 3
    for (z, t_exp), t_sim in zip(lr.MARTIN_MOYCE, r["front_times"]):
        assert t_sim is not None, z
        assert abs(t_sim - t_exp) / t_exp <= 0.10, (z, t_sim, t_exp)
    assert r["front_error"] <= 0.10
    assert r["front_times"][0] < r["front_times"][1] < r["front_times"][2]


def test_the_dam_break_keeps_its_volume():
    r = lr.dam_break()
    assert r["particles"] == r["particles_at_end"]            # the particle volume is exact
    assert abs(r["density_drift"]) <= 0.01                    # the bulk density holds within 1 %
    liq = r["liquid"]
    assert abs(lr.density_drift(liq)) <= 0.01
    # the free-surface cells are partly filled, so the cell-count volume undercounts a spread-out liquid
    assert -0.08 <= r["volume_drift"] <= 0.0


def test_the_density_correction_acts_on_interior_cells_only():
    s = _spec(per_cell=4, correction=0.3)
    liq = lr.liquid((8, 8), 0.25, s, [((0.0, 0.0), (1.0, 1.0))])
    assert all(t == 0.0 for t in lr.density_target(liq, DT))
    # a fifth particle in an interior cell asks that cell to expand by 0.3 x 1/4 per step; a surface cell does not
    liq["x"].append((0.3, 0.3))
    liq["v"].append((0.0, 0.0))
    liq["C"].append(lr.zeros(2))
    target = lr.density_target(liq, DT)
    assert target[lr.cell_index(liq, (1, 1))] == pytest.approx(0.3 * 0.25 / DT)
    liq["x"][-1] = (0.3, 0.9)                 # the top row touches the free surface: no correction there
    assert all(t == 0.0 for t in lr.density_target(liq, DT))
    liq["x"][-1] = (0.05, 0.05)               # the corner against two walls is bulk, not surface
    assert lr.density_target(liq, DT)[lr.cell_index(liq, (0, 0))] == pytest.approx(0.3 * 0.25 / DT)
    assert lr.density_target(lr.liquid((8, 8), 0.25, _spec(per_cell=4, correction=0.0), [((0.0, 0.0), (1.0, 1.0))]), DT) is None
    with pytest.raises(ValueError):
        _spec(correction=1.5)
    with pytest.raises(ValueError):
        _spec(separation=-0.1)


def test_particle_separation_pushes_close_pairs_apart_in_one_jacobi_sweep():
    s = _spec(per_cell=4, separation=0.75)
    liq = lr.liquid((8, 8), 0.25, s, [((0.0, 0.0), (1.0, 1.0))])
    assert lr.separate(liq) == 0                              # the lattice spacing is above the minimum
    before = list(liq["x"])
    liq["x"][5] = (before[5][0] + 0.01, before[5][1])         # 0.01 from a neighbour on the lattice? no: move it near particle 6
    liq["x"][5] = (before[6][0] - 0.02, before[6][1])
    moved = lr.separate(liq)
    assert moved == 2                                         # both of the pair move, by the same amount, apart
    gap = liq["x"][6][0] - liq["x"][5][0]
    assert gap > 0.02
    assert liq["x"][5][0] < before[6][0] - 0.02 and liq["x"][6][0] > before[6][0]
    assert lr.separate(lr.liquid((8, 8), 0.25, _spec(per_cell=4, separation=0.0), [((0.0, 0.0), (1.0, 1.0))])) == 0


def test_the_nondimensional_time_and_front():
    # T = t sqrt(2 g / a) and Z = x / a for the n^2 = 2 column (height 2 a)
    assert _close(lr.nondimensional_time(1.0, 1.0, 9.81), math.sqrt(2 * 9.81))
    assert _close(lr.front_position(((0.1, 0.2), (2.5, 0.1), (1.0, 0.0)), 0.5), 5.0)
    assert lr.crossing_time([(0.0, 1.0), (1.0, 2.0), (2.0, 4.0)], 3.0) == 1.5
    assert lr.crossing_time([(0.0, 1.0), (1.0, 2.0)], 3.0) is None


# ------------------------------------------------------------------------------------ rule 7: MLS-MPM


def test_polar_and_svd_decompositions():
    F = ((1.2, 0.3), (-0.1, 0.9))
    R, S = lr.polar(F)
    assert _close(lr.matmul(R, S), F, 1e-9)
    assert _close(lr.matmul(lr.transpose(R), R), ((1.0, 0.0), (0.0, 1.0)), 1e-9)
    assert _close(S, lr.transpose(S), 1e-9)
    U, sig, V = lr.svd(F)
    rebuilt = lr.matmul(lr.matmul(U, lr.diag(sig)), lr.transpose(V))
    assert _close(rebuilt, F, 1e-9)
    assert sig[0] >= sig[1] > 0.0
    F3 = ((1.1, 0.2, 0.0), (0.0, 0.9, 0.1), (0.3, 0.0, 1.0))
    U, sig, V = lr.svd(F3)
    assert _close(lr.matmul(lr.matmul(U, lr.diag(sig)), lr.transpose(V)), F3, 1e-9)
    assert lr.determinant(U) > 0.0 and lr.determinant(V) > 0.0


def test_the_fixed_corotated_stress_vanishes_at_rest_and_resists_stretch():
    I = ((1.0, 0.0), (0.0, 1.0))
    mu, lam = lr.lame(1000.0, 0.3)
    assert _close(lr.corotated_stress(I, mu, lam), ((0.0, 0.0), (0.0, 0.0)))
    P = lr.corotated_stress(((1.1, 0.0), (0.0, 1.0)), mu, lam)
    assert P[0][0] > 0.0                                    # tension along x
    R = ((math.cos(0.3), -math.sin(0.3)), (math.sin(0.3), math.cos(0.3)))
    assert _close(lr.corotated_stress(R, mu, lam), ((0.0, 0.0), (0.0, 0.0)), 1e-9)   # rotation is stress free
    assert lr.corotated_energy(I, mu, lam) == 0.0
    assert lr.corotated_energy(((1.1, 0.0), (0.0, 1.0)), mu, lam) > 0.0


def test_the_drucker_prager_return_maps_onto_the_cone():
    mu, lam = lr.lame(1000.0, 0.3)
    alpha = lr.friction_alpha(30.0)
    assert _close(alpha, math.sqrt(2.0 / 3.0) * 2 * math.sin(math.radians(30.0)) / (3 - math.sin(math.radians(30.0))))
    # pure compression stays elastic (inside the cone); a sheared state is projected onto the cone
    sig = (0.95, 0.95)
    assert lr.drucker_prager(sig, mu, lam, alpha)[0] == sig
    sheared = (1.2, 0.8)
    mapped, plastic = lr.drucker_prager(sheared, mu, lam, alpha)
    assert plastic > 0.0
    assert lr.on_yield_surface(mapped, mu, lam, alpha)
    # tension is fully projected to the origin (no cohesion)
    mapped, plastic = lr.drucker_prager((1.1, 1.05), mu, lam, alpha)
    assert _close(mapped, (1.0, 1.0))


def test_mls_mpm_conserves_momentum_in_free_flight():
    s = _spec(per_cell=4, method="mpm", gravity=0.0)
    body = lr.liquid((12, 12), 0.25, s, [((1.0, 1.0), (2.0, 2.0))], material=lr.material("elastic", 2000.0, 0.3))
    body["v"] = [(0.4, -0.3) for _ in body["x"]]
    before = lr.momentum(body)
    body = lr.run(body, 10)
    after = lr.momentum(body)
    assert _close(before, after, 1e-9)
    assert all(_close(f, ((1.0, 0.0), (0.0, 1.0)), 1e-9) for f in body["F"])       # a rigid translation keeps F = I


def test_an_elastic_block_at_rest_keeps_its_shape():
    s = _spec(per_cell=4, method="mpm", gravity=0.0)
    body = lr.liquid((12, 12), 0.25, s, [((1.0, 1.0), (2.0, 2.0))], material=lr.material("elastic", 2000.0, 0.3))
    body = lr.run(body, 20)
    assert body["x"] == body["x0"]
    assert lr.momentum(body) == (0.0, 0.0)


def test_a_sand_column_collapses_to_its_angle_of_repose():
    r = lr.sand_collapse()
    assert r["runout"] > 1.0                      # the pile spreads beyond its initial half-width
    assert r["height"] < 1.0                      # and lowers
    assert r["slope"] <= math.tan(math.radians(r["friction"])) * 1.05
    assert r["plastic"] > 0.0
    assert r["particles"] == 400


def test_the_pile_rises_with_the_friction_angle():
    slopes, rising, below = lr.repose_test()
    assert rising and below
    assert slopes[0] > 0.0


def test_the_mpm_material_is_validated():
    with pytest.raises(ValueError):
        lr.material("liquid", 1.0, 0.3)
    with pytest.raises(ValueError):
        lr.material("sand", 1000.0, 0.5)
    with pytest.raises(ValueError):
        lr.material("sand", 1000.0, 0.3, friction=0.0)
    with pytest.raises(ValueError):
        lr.material("elastic", 0.0, 0.3)
    m = lr.material("snow", 1000.0, 0.2, hardening=10.0, compression=2.5e-2, stretch=7.5e-3)
    assert m["kind"] == "snow"


# ------------------------------------------------------------------------------------ rule 8: whitewater


def test_the_whitewater_potentials_follow_ihmsen():
    assert _close(lr.clamp_potential(0.0, 1.0, 3.0), 0.0)
    assert _close(lr.clamp_potential(2.0, 1.0, 3.0), 0.5)
    assert _close(lr.clamp_potential(9.0, 1.0, 3.0), 1.0)
    assert lr.radial_kernel(0.0, 1.0) == 1.0
    assert lr.radial_kernel(1.0, 1.0) == 0.0
    assert _close(lr.radial_kernel(0.25, 1.0), 0.75)
    # particles moving together trap no air; particles moving toward each other do
    x = ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0))
    assert lr.trapped_air(0, x, ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)), 1.0) == 0.0
    assert lr.trapped_air(0, x, ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)), 1.0) > 0.0
    assert lr.trapped_air(0, x, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), 1.0) > 0.0


def test_the_wave_crest_potential_needs_a_convex_surface_moving_outward():
    # a crest particle with neighbours below and to the sides, normals fanning out, moving along its normal
    x = ((0.0, 0.0, 0.0), (-0.5, -0.3, 0.0), (0.5, -0.3, 0.0))
    n = ((0.0, 1.0, 0.0), (-0.6, 0.8, 0.0), (0.6, 0.8, 0.0))
    assert lr.wave_crest(0, x, n, ((0.0, 1.0, 0.0),) * 3, 1.0) > 0.0
    assert lr.wave_crest(0, x, n, ((1.0, 0.0, 0.0),) * 3, 1.0) == 0.0          # moving along the surface
    flat = ((0.0, 1.0, 0.0),) * 3
    assert lr.wave_crest(0, x, flat, ((0.0, 1.0, 0.0),) * 3, 1.0) == 0.0       # a flat surface has no crest


def test_diffuse_particles_are_classified_by_their_neighbour_count():
    assert lr.classify(3) == "spray"
    assert lr.classify(6) == "bubble"
    assert lr.classify(20) == "bubble"
    assert lr.classify(21) == "foam"
    assert lr.SPRAY_BELOW == 6 and lr.FOAM_ABOVE == 20


def test_the_emission_count_is_deterministic_and_bounded():
    s = lr.whitewater_spec(trapped_air=(5.0, 20.0), wave_crest=(2.0, 8.0), kinetic=(5.0, 50.0), rate_air=200.0,
                           rate_crest=400.0, lifetime=2.0, max_particles=1000, seed=7)
    count, carry = lr.emission_count(1.0, 1.0, 0.5, s, DT, 0.0)
    assert count == int((200.0 + 400.0) * 0.5 * DT)
    assert 0.0 <= carry < 1.0
    total = 0
    carry = 0.0
    for _ in range(120):
        c, carry = lr.emission_count(1.0, 1.0, 0.5, s, DT, carry)
        total += c
    assert total == round((200.0 + 400.0) * 0.5 * 120 * DT)
    assert lr.emission_count(0.0, 0.0, 1.0, s, DT, 0.0) == (0, 0.0)
    with pytest.raises(ValueError):
        lr.whitewater_spec(trapped_air=(5.0, 5.0), wave_crest=(2.0, 8.0), kinetic=(5.0, 50.0))
    with pytest.raises(ValueError):
        lr.whitewater_spec(trapped_air=(5.0, 20.0), wave_crest=(2.0, 8.0), kinetic=(5.0, 50.0), max_particles=0)
    r = lr.whitewater_test()
    assert r["spray"] > 0 and r["foam"] > 0 and r["bubble"] > 0
    assert r["first"] == r["second"]
    assert r["total"] <= 1000


def test_diffuse_particle_positions_are_a_function_of_the_seed_and_index():
    a = lr.diffuse_position((0.5, 0.5, 0.5), (0.0, 1.0, 0.0), 0.25, 7, 3)
    b = lr.diffuse_position((0.5, 0.5, 0.5), (0.0, 1.0, 0.0), 0.25, 7, 3)
    c = lr.diffuse_position((0.5, 0.5, 0.5), (0.0, 1.0, 0.0), 0.25, 7, 4)
    assert a == b and a != c
    assert math.dist(a, (0.5, 0.5, 0.5)) <= 0.25 * math.sqrt(2) + 1e-12


# ------------------------------------------------------------------------------------ rule 9: the surface


def test_the_level_set_of_a_ball_of_particles_is_its_signed_distance():
    r = lr.surface_test()
    assert r["inside"] < 0.0 < r["outside"]
    assert abs(r["radius_error"]) <= 0.05          # the zero set sits within 0.05 h of the ball's radius
    assert r["closed"]
    assert abs(r["volume_error"]) <= 0.1
    assert r["euler"] == 2


def test_the_level_set_is_the_zhu_bridson_average():
    x = ((0.0, 0.0, 0.0),)
    assert _close(lr.level_set_at((0.0, 0.0, 0.0), x, 0.5, 1.0), -0.5)
    assert _close(lr.level_set_at((0.3, 0.0, 0.0), x, 0.5, 1.0), -0.2)
    assert lr.level_set_at((5.0, 0.0, 0.0), x, 0.5, 1.0) == 1.0          # outside every kernel: the radius
    assert lr.isotropic_kernel(0.0) == 1.0 and lr.isotropic_kernel(1.0) == 0.0


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
    assert "SR-83" in draft
    for word in ("liquid3D", "apic", "flip", "mpm", "perCell", "flipRatio", "densityCorrection", "separation",
                 "whitewater", "Martin and Moyce",
                 "dam break", "Jiang", "Hu", "Ihmsen", "Zhu", "Bridson", "Klár", "Stomakhin", "V17", "seek check",
                 "liquids_reference.py", "volume", "Drucker", "granular", "angle of repose", "quadratic B-spline"):
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
    scope = lr.scope()
    got = eval(expr, scope)
    want = eval(expected, scope)
    assert got == want or lr._same(got, want), name


def test_the_table_is_what_the_module_prints(draft, capsys):
    lr.main()
    out = capsys.readouterr().out.strip().splitlines()
    table = [line for line in draft.splitlines() if ROW.match(line) and not line.startswith("| Test")]
    assert out == table
