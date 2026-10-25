"""Tests for the draft SREP "Add pattern systems to the scene" (G2 of SREP 12) and its reference."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re

import pytest

np = pytest.importorskip("numpy")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "patterns_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-patterns.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pt = _load(MODULE, "patterns_reference")
rs = pt.streams()


def _doc(*elements):
    return {"version": "1.8", "project": 7, "patterns": list(elements)}


def _reaction(**kw):
    return dict({"kind": "reaction", "id": "r1", "width": 128.0, "height": 128.0, "resolution": 128, "seed": 3}, **kw)


def _lenia(**kw):
    return dict({"kind": "lenia", "id": "l1", "width": 64.0, "height": 64.0, "resolution": 64, "seed": 1}, **kw)


def _automaton(**kw):
    return dict({"kind": "automaton", "id": "a1", "width": 16.0, "height": 16.0, "resolution": 16, "seed": 1}, **kw)


def _aggregation(**kw):
    return dict({"kind": "aggregation", "id": "d1", "width": 256.0, "height": 256.0, "resolution": 256, "seed": 5},
                **kw)


def _growth(**kw):
    return dict({"kind": "growth", "id": "g1", "width": 100.0, "height": 100.0, "resolution": 100, "seed": 2}, **kw)


# ------------------------------------------------------------------------------------------- the common frame


def test_the_grid_follows_the_longer_side():
    assert pt.grid({"width": 200.0, "height": 100.0, "resolution": 64}) == (64, 32)
    assert pt.grid({"width": 100.0, "height": 300.0, "resolution": 90}) == (30, 90)
    assert pt.grid({"width": 100.0, "height": 100.0, "resolution": 8}) == (8, 8)


def test_the_step_count_is_owned_by_the_frame_time():
    spec = {"rate": 30.0, "prewarm": 10, "maxSteps": 100}
    assert pt.steps_at(spec, 0.0) == 10
    assert pt.steps_at(spec, 1.0) == 40
    assert pt.steps_at(spec, 0.999) == 39
    assert pt.steps_at(spec, 1000.0) == 100
    assert pt.steps_at({"rate": 30.0}, 2.0) == 60


def test_the_element_seed_is_the_streams():
    doc = _doc(_reaction())
    assert pt.element_seed(doc, doc["patterns"][0]) == rs.E(7, "r1", 3, "stream")
    assert pt.element_seed(doc, dict(doc["patterns"][0], seed=None)) == rs.E(7, "r1", None, "stream")


def test_the_initial_noise_is_indexed_by_cell():
    doc = _doc(_reaction(resolution=16, width=16.0, height=16.0))
    e = pt.element_seed(doc, doc["patterns"][0])
    noise = pt.noise_field(e, 16, 16)
    assert noise.shape == (16, 16)
    assert noise[0, 0] == rs.S(e, pt.INIT_PURPOSE, 0, 0)
    assert noise[3, 5] == rs.S(e, pt.INIT_PURPOSE, 0, 3 * 16 + 5)
    assert 0.0 <= noise.min() and noise.max() < 1.0


# ------------------------------------------------------------------------------------------- Gray-Scott


def test_the_nine_point_laplacian_is_zero_on_a_constant_and_periodic():
    a = np.full((8, 8), 0.7)
    assert np.allclose(pt.laplacian(a), 0.0)
    b = np.zeros((8, 8))
    b[0, 0] = 1.0
    lap = pt.laplacian(b)
    assert math.isclose(lap[0, 0], -1.0)
    assert math.isclose(lap[0, 1], 0.2) and math.isclose(lap[7, 0], 0.2) and math.isclose(lap[7, 7], 0.05)
    assert math.isclose(lap.sum(), 0.0, abs_tol=1e-12)


def test_the_reaction_starts_from_a_seeded_square_with_noise():
    doc = _doc(_reaction(resolution=64, width=64.0, height=64.0, spot=0.25))
    u, v = pt.reaction_initial(doc, doc["patterns"][0])
    assert u.shape == v.shape == (64, 64)
    centre = v[24:40, 24:40]
    assert centre.min() > 0.2 and centre.max() <= 0.26
    assert v[:8, :].max() < 0.02 and u[:8, :].min() > 0.98
    assert u[30, 30] < 0.6
    assert not np.array_equal(centre, np.full_like(centre, centre[0, 0]))  # the noise differs per cell


def test_a_fed_reaction_keeps_u_and_v_in_range_and_dies_without_v():
    doc = _doc(_reaction(resolution=32, width=32.0, height=32.0))
    u, v = pt.gray_scott(doc, doc["patterns"][0], 300)
    assert 0.0 <= u.min() and u.max() <= 1.0 and 0.0 <= v.min() and v.max() <= 1.0
    dead = dict(doc["patterns"][0], spot=0.0)
    u2, v2 = pt.gray_scott(doc, dead, 50)
    assert v2.max() == 0.0 and math.isclose(u2.min(), 1.0)


@pytest.mark.parametrize("feed,kill,expected", [(0.0367, 0.0649, "spots"), (0.055, 0.062, "labyrinth"),
                                                (0.030, 0.070, "extinct")])
def test_pearsons_pattern_classes(feed, kill, expected):
    doc = _doc(_reaction(feed=feed, kill=kill))
    u, v = pt.gray_scott(doc, doc["patterns"][0], 4000)
    assert pt.classify(v) == expected


def test_the_classifier_on_synthetic_fields():
    assert pt.classify(np.zeros((32, 32))) == "extinct"
    assert pt.classify(np.full((32, 32), 0.3)) == "uniform"
    spots = np.zeros((64, 64))
    for i in range(4, 64, 8):
        for j in range(4, 64, 8):
            spots[i - 1:i + 2, j - 1:j + 2] = 0.4
    assert pt.classify(spots) == "spots"
    stripes = np.zeros((64, 64))
    stripes[::6, :] = 0.4
    stripes[1::6, :] = 0.4
    assert pt.classify(stripes) == "labyrinth"
    assert pt.components(spots > 0.1) == 64
    assert pt.components(stripes > 0.1) == 11


def test_the_reaction_is_a_function_of_the_seed_and_the_step_count():
    doc = _doc(_reaction(resolution=32, width=32.0, height=32.0))
    a = pt.gray_scott(doc, doc["patterns"][0], 100)
    b = pt.gray_scott(doc, doc["patterns"][0], 100)
    c = pt.gray_scott(doc, dict(doc["patterns"][0], seed=4), 100)
    assert np.array_equal(a[1], b[1]) and not np.array_equal(a[1], c[1])
    d = pt.gray_scott(doc, doc["patterns"][0], 101)
    assert not np.array_equal(a[1], d[1])


# ------------------------------------------------------------------------------------------- Lenia


def test_the_kernel_core_and_the_growth_map():
    assert pt.kernel_core(0.5) == pytest.approx(1.0)
    assert pt.kernel_core(0.0) == 0.0 and pt.kernel_core(1.0) == 0.0
    assert pt.kernel_core(0.25) == pytest.approx(math.exp(4.0 - 1.0 / (0.25 * 0.75)))
    assert pt.growth_map(0.15, 0.15, 0.015) == pytest.approx(1.0)
    assert pt.growth_map(0.0, 0.15, 0.015) == pytest.approx(-1.0)
    assert pt.growth_map(0.165, 0.15, 0.015) == pytest.approx(2.0 * math.exp(-0.5) - 1.0)


def test_the_kernel_is_a_normalised_ring_of_radius_r():
    k = pt.lenia_kernel(13, (1.0,), 64, 64)
    assert k.shape == (64, 64)
    assert math.isclose(k.sum(), 1.0, rel_tol=1e-12)
    assert k[0, 0] == 0.0                      # the centre of the (shifted) kernel is empty
    assert k[0, 7] > k[0, 3] and k[0, 7] > k[0, 12]  # peak near r = R / 2
    assert k[0, 13] == 0.0 and k[0, 14] == 0.0      # nothing at or beyond R
    assert np.allclose(k, np.roll(np.flip(k, 0), 1, 0)) and np.allclose(k, np.roll(np.flip(k, 1), 1, 1))
    two = pt.lenia_kernel(13, (0.5, 1.0), 64, 64)
    assert two[0, 10] > two[0, 3]  # the outer ring is the heavier one


def test_the_orbium_cells_decode_to_the_published_shape():
    cells = pt.orbium()
    assert cells.shape == (20, 20)
    assert 0.0 <= cells.min() and cells.max() <= 1.0
    assert cells.max() == 1.0
    assert cells.sum() == pytest.approx(pt.ORBIUM_MASS, rel=1e-9)
    assert pt.decode_cells("3.A$pA2B!").tolist() == [[0.0, 0.0, 0.0, 1 / 255], [25 / 255, 2 / 255, 2 / 255, 0.0]]


def test_the_orbium_glider_keeps_its_mass_and_moves_at_a_steady_speed():
    doc = _doc(_lenia())
    track = pt.lenia_track(doc, doc["patterns"][0], 120, 20)
    masses = [m for _, m, _ in track]
    assert all(abs(m - masses[0]) / masses[0] < 0.1 for m in masses), masses
    speeds = [pt.displacement(track[i][2], track[i + 1][2], 64, 64) / 20.0 for i in range(len(track) - 1)]
    assert all(0.3 < s < 0.9 for s in speeds), speeds
    assert max(speeds) - min(speeds) < 0.1
    assert pt.lenia_speed(track, 64, 64) == pytest.approx(sum(speeds) / len(speeds), rel=1e-9)


def test_lenia_without_a_creature_from_noise_is_deterministic_and_bounded():
    doc = _doc(_lenia(creature="noise"))
    a = pt.lenia(doc, doc["patterns"][0], 10)
    b = pt.lenia(doc, doc["patterns"][0], 10)
    assert np.array_equal(a, b) and 0.0 <= a.min() and a.max() <= 1.0
    c = pt.lenia(doc, dict(doc["patterns"][0], seed=2), 10)
    assert not np.array_equal(a, c)


def test_a_lenia_grid_too_small_for_the_kernel_is_refused():
    doc = _doc(_lenia(resolution=16, width=16.0, height=16.0))
    with pytest.raises(pt.PatternError):
        pt.lenia(doc, doc["patterns"][0], 1)


# ------------------------------------------------------------------------------------------- cellular automata


def test_the_rule_string_parses_births_and_survivals():
    assert pt.parse_rule("B3/S23") == ({3}, {2, 3})
    assert pt.parse_rule("B36/S23") == ({3, 6}, {2, 3})
    assert pt.parse_rule("B/S") == (set(), set())
    for bad in ("B3S23", "B9/S23", "3/23", "B33/S2", "S23/B3"):
        with pytest.raises(pt.PatternError):
            pt.parse_rule(bad)


def test_the_run_length_encoding_parses_golly_patterns():
    glider = pt.parse_rle("bo$2bo$3o!")
    assert glider.tolist() == [[0, 1, 0], [0, 0, 1], [1, 1, 1]]
    assert pt.parse_rle("3o!").tolist() == [[1, 1, 1]]
    assert pt.parse_rle("2o$2o!").tolist() == [[1, 1], [1, 1]]
    assert pt.parse_rle("o2$o!").tolist() == [[1], [0], [1]]
    for bad in ("", "x!", "3!", "ob"):
        with pytest.raises(pt.PatternError):
            pt.parse_rle(bad)


def test_the_blinker_has_period_two():
    doc = _doc(_automaton(pattern="3o!"))
    cells0 = pt.automaton(doc, doc["patterns"][0], 0)
    cells1 = pt.automaton(doc, doc["patterns"][0], 1)
    cells2 = pt.automaton(doc, doc["patterns"][0], 2)
    assert cells0.sum() == cells1.sum() == cells2.sum() == 3
    assert not np.array_equal(cells0, cells1) and np.array_equal(cells0, cells2)
    assert pt.period(doc, doc["patterns"][0], 8) == (2, (0, 0))


def test_the_glider_has_period_four_and_moves_one_cell_diagonally():
    doc = _doc(_automaton(pattern="bo$2bo$3o!"))
    assert pt.period(doc, doc["patterns"][0], 8) == (4, (1, 1))
    cells4 = pt.automaton(doc, doc["patterns"][0], 4)
    assert np.array_equal(cells4, np.roll(pt.automaton(doc, doc["patterns"][0], 0), (1, 1), (0, 1)))


def test_the_block_is_still_and_the_torus_wraps():
    doc = _doc(_automaton(pattern="2o$2o!", x=15, y=15))
    cells = pt.automaton(doc, doc["patterns"][0], 0)
    assert cells[15, 15] == cells[15, 0] == cells[0, 15] == cells[0, 0] == 1 and cells.sum() == 4
    assert pt.period(doc, doc["patterns"][0], 4) == (1, (0, 0))
    assert np.array_equal(pt.automaton(doc, doc["patterns"][0], 7), cells)


def test_the_pattern_is_centred_by_default_and_a_random_start_draws_from_the_streams():
    doc = _doc(_automaton(pattern="3o!"))
    cells = pt.automaton(doc, doc["patterns"][0], 0)
    assert cells[8, 7] == cells[8, 8] == cells[8, 9] == 1
    e = pt.element_seed(doc, doc["patterns"][0])
    rnd = dict(doc["patterns"][0], pattern=None, density=0.5)
    cells = pt.automaton(doc, rnd, 0)
    expect = (pt.noise_field(e, 16, 16) < 0.5).astype(np.uint8)
    assert np.array_equal(cells, expect)
    assert 40 < cells.sum() < 216


def test_an_automaton_in_highlife_replicates_and_no_period_is_reported_when_none():
    doc = _doc(_automaton(pattern="3o!", rule="B36/S23"))
    assert pt.period(doc, doc["patterns"][0], 8) == (2, (0, 0))
    chaos = _doc(_automaton(pattern="bo$2bo$3o!", x=0, y=0, resolution=8, width=8.0, height=8.0))
    assert pt.period(chaos, dict(chaos["patterns"][0], pattern="2bo$2o$b2o!"), 3) is None


def test_a_pattern_larger_than_the_grid_is_refused():
    doc = _doc(_automaton(pattern="20o!"))
    with pytest.raises(pt.PatternError):
        pt.automaton(doc, doc["patterns"][0], 0)


# ------------------------------------------------------------------------------------------- aggregation


def test_a_walker_draws_its_steps_from_its_own_stream():
    doc = _doc(_aggregation())
    e = pt.element_seed(doc, doc["patterns"][0])
    angle0 = pt.walker_angle(e, 7, 0)
    assert angle0 == 2.0 * math.pi * rs.S(e, pt.WALK_PURPOSE, 7, 0)
    assert pt.walker_angle(e, 7, 1) != angle0 and pt.walker_angle(e, 8, 0) != angle0


def test_the_aggregate_grows_from_the_seed_particle_and_every_particle_touches_an_earlier_one():
    doc = _doc(_aggregation(particles=200))
    out = pt.aggregate(doc, doc["patterns"][0], 200)
    pts = out["positions"]
    assert len(pts) == 200 and pts[0] == (128, 128)
    occupied = {pts[0]}
    for p in pts[1:]:
        assert any((p[0] + dx, p[1] + dy) in occupied for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        assert p not in occupied
        occupied.add(p)
    assert out["radius"] > 10.0 and out["launched"] >= 200


def test_the_aggregate_is_a_prefix_sequence_and_a_function_of_the_seed():
    doc = _doc(_aggregation(particles=120))
    a = pt.aggregate(doc, doc["patterns"][0], 120)["positions"]
    b = pt.aggregate(doc, doc["patterns"][0], 60)["positions"]
    assert a[:60] == b
    c = pt.aggregate(doc, dict(doc["patterns"][0], seed=6), 60)["positions"]
    assert c != b


def test_the_gyration_fit_recovers_known_dimensions():
    """A disc and a line grown outward from their centre: Rg scales as N^(1/2) and as N."""
    disc = sorted(((x, y) for x in range(-40, 41) for y in range(-40, 41) if x * x + y * y <= 1600),
                  key=lambda p: (p[0] * p[0] + p[1] * p[1], p))
    assert pt.fractal_dimension(disc) == pytest.approx(2.0, abs=0.05)
    line = sorted(((x, 0) for x in range(-40, 41)), key=lambda p: (abs(p[0]), p))
    assert pt.fractal_dimension(line) == pytest.approx(1.0, abs=0.05)


def test_the_cluster_has_the_fractal_dimension_of_dla():
    doc = _doc(_aggregation())
    out = pt.aggregate(doc, doc["patterns"][0], 2000)
    assert abs(pt.fractal_dimension(out["positions"]) - 1.71) <= 0.05


def test_sticking_probability_below_one_makes_a_denser_cluster():
    doc = _doc(_aggregation(particles=400))
    loose = pt.aggregate(doc, doc["patterns"][0], 400)
    dense = pt.aggregate(doc, dict(doc["patterns"][0], stick=0.1), 400)
    assert dense["radius"] < loose["radius"]


def test_the_aggregate_stops_at_the_grid_and_at_the_particle_count():
    doc = _doc(_aggregation(particles=50, resolution=16, width=16.0, height=16.0))
    out = pt.aggregate(doc, doc["patterns"][0], 500)
    assert len(out["positions"]) <= 50
    assert all(0 <= x < 16 and 0 <= y < 16 for x, y in out["positions"])


# ------------------------------------------------------------------------------------------- differential growth


def test_the_curve_starts_as_a_circle_of_nodes():
    doc = _doc(_growth(nodes=12, radius=10.0))
    nodes = pt.growth_initial(doc, doc["patterns"][0])
    assert nodes.shape == (12, 2)
    assert np.allclose(np.hypot(nodes[:, 0] - 50.0, nodes[:, 1] - 50.0), 10.0)
    assert pt.curve_length(nodes) == pytest.approx(12 * 2 * 10.0 * math.sin(math.pi / 12))


def test_edges_longer_than_the_maximum_are_split_at_their_midpoint():
    nodes = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 1.0], [0.0, 1.0]])
    out = pt.split_edges(nodes, 2.5)
    assert out.shape == (6, 2)
    assert [2.0, 0.0] in out.tolist() and [2.0, 1.0] in out.tolist()
    assert out.tolist()[1] == [2.0, 0.0]


def test_the_curve_grows_stays_closed_and_bounded():
    doc = _doc(_growth(nodes=24, radius=8.0, maxNodes=300))
    n0 = pt.grow(doc, doc["patterns"][0], 0)
    n1 = pt.grow(doc, doc["patterns"][0], 30)
    n2 = pt.grow(doc, doc["patterns"][0], 300)
    assert len(n0) == 24 < len(n1) < len(n2) <= 300
    assert len(n1) >= 24 + 30
    assert pt.curve_length(n0) < pt.curve_length(n1) < pt.curve_length(n2)
    for nodes in (n1, n2):
        assert nodes[:, 0].min() >= 0.0 and nodes[:, 0].max() <= 100.0
        assert nodes[:, 1].min() >= 0.0 and nodes[:, 1].max() <= 100.0
    edges = np.hypot(*(np.roll(n1, -1, 0) - n1).T)
    assert edges.max() <= pt.GROWTH_DEFAULTS["maxEdge"] + 1e-9
    assert pt.self_intersections(n2) == 0


def test_repulsion_keeps_distant_nodes_apart():
    doc = _doc(_growth(nodes=16, radius=6.0, repulsion=4.0, maxNodes=400))
    nodes = pt.grow(doc, doc["patterns"][0], 200)
    d = np.hypot(nodes[:, None, 0] - nodes[None, :, 0], nodes[:, None, 1] - nodes[None, :, 1])
    n = len(nodes)
    idx = np.arange(n)
    ring = np.minimum((idx[:, None] - idx[None, :]) % n, (idx[None, :] - idx[:, None]) % n)
    far = d[ring >= 3]
    assert far.min() > 1.0


def test_the_jitter_draws_from_the_streams_and_the_growth_is_a_function_of_the_seed():
    doc = _doc(_growth())
    a = pt.grow(doc, doc["patterns"][0], 40)
    b = pt.grow(doc, doc["patterns"][0], 40)
    c = pt.grow(doc, dict(doc["patterns"][0], seed=9), 40)
    assert np.array_equal(a, b) and a.shape != c.shape or not np.array_equal(a, c)
    e = pt.element_seed(doc, doc["patterns"][0])
    j = pt.jitter(e, 5, 3)
    assert j == (rs.S(e, pt.JITTER_PURPOSE, 5, 6) - 0.5, rs.S(e, pt.JITTER_PURPOSE, 5, 7) - 0.5)
    assert pt.insertion_edge(e, 5, 40) == int(40 * rs.S(e, pt.JITTER_PURPOSE, 5, 80))


def test_self_intersections_are_counted():
    square = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    assert pt.self_intersections(square) == 0
    bow = np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0]])
    assert pt.self_intersections(bow) == 1


# ------------------------------------------------------------------------------------------- the run


def test_run_outputs_every_element_with_its_state_summary():
    doc = pt.example_document()
    out = pt.run(doc, 1.0)
    assert set(out["elements"]) == {p["id"] for p in doc["patterns"]}
    for p in doc["patterns"]:
        el = out["elements"][p["id"]]
        assert el["kind"] == p["kind"] and el["steps"] == pt.steps_at(p, 1.0)
    assert out["elements"]["coral"]["class"] in ("spots", "labyrinth", "extinct", "uniform", "mixed")
    assert out["elements"]["orbium"]["mass"] > 0.0
    assert out["elements"]["life"]["alive"] >= 0
    assert out["elements"]["frost"]["particles"] == pt.steps_at(next(p for p in doc["patterns"]
                                                                        if p["id"] == "frost"), 1.0)
    assert out["elements"]["vine"]["nodes"] >= 24
    assert isinstance(out["digest"], str) and len(out["digest"]) == 64
    assert out["digest"] != pt.run(doc, 2.0)["digest"]


def test_every_frame_alone():
    doc = pt.example_document()
    assert pt.run(doc, 2.0)["digest"] == pt.run(doc, 2.0)["digest"]
    small = _doc(_automaton(pattern="bo$2bo$3o!", rate=4.0))
    direct = pt.run(small, 3.0)
    assert direct["elements"]["a1"]["steps"] == 12
    assert np.array_equal(pt.automaton(small, small["patterns"][0], 12),
                          np.roll(pt.automaton(small, small["patterns"][0], 0), (3, 3), (0, 1)))


def test_the_colour_ramp_maps_the_field_through_color_low_and_color():
    spec = {"color": "#FFD27AFF", "colorLow": "#00000000"}
    assert pt.ramp(spec, 0.0) == (0, 0, 0, 0)
    assert pt.ramp(spec, 1.0) == (255, 210, 122, 255)
    assert pt.ramp(spec, 0.5) == (128, 105, 61, 128)
    assert pt.ramp(spec, 2.0) == (255, 210, 122, 255)


def test_validation_one_at_a_time():
    doc = pt.example_document()
    assert pt.validate_document(doc) == []
    bad = pt.bad_document()
    assert pt.validate_document(bad) == ["PT1", "PT2", "PT3", "PT4", "PT5"]

    def with_(index, **changes):
        d = json.loads(json.dumps(doc))
        d["patterns"][index].update(changes)
        return pt.validate_document(d)

    # PT1: the frame
    assert with_(0, resolution=4) == ["PT1"]
    assert with_(0, resolution=4096) == ["PT1"]
    assert with_(0, rate=0.0) == ["PT1"]
    assert with_(0, prewarm=-1) == ["PT1"]
    assert with_(0, maxSteps=0) == ["PT1"]
    assert with_(0, width=0.0) == ["PT1"]
    assert with_(0, prewarm=200000) == ["PT1"]
    # PT2: reaction and lenia parameters
    assert with_(0, feed=1.5) == ["PT2"]
    assert with_(0, kill=-0.1) == ["PT2"]
    assert with_(0, diffuseU=0.0) == ["PT2"]
    assert with_(0, diffuseU=0.4, diffuseV=0.5) == ["PT2"]
    assert with_(0, spot=1.5) == ["PT2"]
    assert with_(1, R=0) == ["PT2"]
    assert with_(1, T=0) == ["PT2"]
    assert with_(1, sigma=0.0) == ["PT2"]
    assert with_(1, beta=[]) == ["PT2"]
    assert with_(1, beta=[1.0, 1.5]) == ["PT2"]
    assert with_(1, creature="dragon") == ["PT2"]
    assert with_(1, R=40) == ["PT2"]
    # PT3: automaton rule and pattern
    assert with_(2, rule="B3S23") == ["PT3"]
    assert with_(2, pattern="x!") == ["PT3"]
    assert with_(2, pattern="40o!") == ["PT3"]
    assert with_(2, density=1.5) == ["PT3"]
    assert with_(2, x=-1) == ["PT3"]
    # PT4: aggregation
    assert with_(3, particles=0) == ["PT4"]
    assert with_(3, stick=0.0) == ["PT4"]
    assert with_(3, stick=1.5) == ["PT4"]
    assert with_(3, particles=10 ** 7) == ["PT4"]
    assert with_(3, launch=0.0) == ["PT4"]
    # PT5: growth
    assert with_(4, nodes=2) == ["PT5"]
    assert with_(4, radius=0.0) == ["PT5"]
    assert with_(4, maxEdge=0.0) == ["PT5"]
    assert with_(4, maxNodes=3) == ["PT5"]
    assert with_(4, repulsion=-1.0) == ["PT5"]
    assert with_(4, speed=0.0) == ["PT5"]
    assert with_(4, insert=-1) == ["PT5"]
    # V17 and unknown kinds
    d = json.loads(json.dumps(doc))
    d["version"] = "1.7"
    assert pt.validate_document(d) == ["V17"]
    d = json.loads(json.dumps(doc))
    d["patterns"][0]["kind"] = "fractal"
    assert pt.validate_document(d) == ["PT1"]
    plain = dict(doc)
    plain.pop("patterns")
    assert pt.validate_document(plain) == []


def test_constants_and_defaults():
    assert pt.KINDS == ("reaction", "lenia", "automaton", "aggregation", "growth")
    assert pt.COMMON_DEFAULTS["resolution"] == 128 and pt.COMMON_DEFAULTS["rate"] == 30.0
    assert pt.COMMON_DEFAULTS["prewarm"] == 0 and pt.COMMON_DEFAULTS["maxSteps"] == 100000
    assert pt.REACTION_DEFAULTS == {"feed": 0.055, "kill": 0.062, "diffuseU": 1.0, "diffuseV": 0.5, "spot": 0.1,
                                    "noise": 0.01}
    assert pt.LENIA_DEFAULTS == {"R": 13, "T": 10, "mu": 0.15, "sigma": 0.015, "beta": (1.0,), "creature": "orbium"}
    assert pt.AUTOMATON_DEFAULTS == {"rule": "B3/S23", "pattern": None, "density": 0.0, "x": None, "y": None}
    assert pt.AGGREGATION_DEFAULTS == {"particles": 2000, "stick": 1.0, "launch": 5.0}
    assert pt.GROWTH_DEFAULTS == {"nodes": 24, "radius": 5.0, "maxEdge": 1.5, "repulsion": 3.0, "attraction": 0.5,
                                  "alignment": 0.25, "repel": 0.75, "jitter": 0.05, "speed": 0.3, "insert": 1,
                                  "maxNodes": 5000}
    assert pt.INIT_PURPOSE == 1 and pt.WALK_PURPOSE == 2 and pt.JITTER_PURPOSE == 3
    assert pt.MAX_RESOLUTION == 2048 and pt.MIN_RESOLUTION == 8 and pt.MAX_PARTICLES == 1000000
    assert pt.CREATURES == ("orbium", "noise")
    assert pt.ORBIUM_PARAMS == {"R": 13, "T": 10, "mu": 0.15, "sigma": 0.015, "beta": (1.0,)}


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
    for word in ("SR-111", "SREP 12", "SREP 14", "SREP 67", "SREP 69", "`reaction`", "`lenia`", "`automaton`",
                 "`aggregation`", "`growth`", "`slime`", "`flock`", "resolution", "`rate`", "prewarm", "maxSteps",
                 "feed", "kill", "diffuseU", "diffuseV", "spot", "noise", "`R`", "`T`", "`mu`", "`sigma`", "`beta`",
                 "creature", "`rule`", "`pattern`", "density", "particles", "stick", "launch", "nodes", "radius",
                 "maxEdge", "repulsion", "attraction", "alignment", "repel", "jitter", "speed", "insert", "maxNodes",
                 "colorLow", "saturation", "PT1", "PT2", "PT3", "PT4", "PT5", "V17", "patterns_reference.py",
                 "random-streams", "Pearson", "Gray", "Scott", "Lenia", "Chan", "Orbium", "Conway", "Life",
                 "HighLife", "B3/S23", "Golly", "Witten", "Sander", "diffusion-limited", "1.71", "differential growth",
                 "Laplacian", "nine-point", "torus", "FFT", "MIT", "mass", "glider", "blinker", "period",
                 "radius of gyration", "numpy"):
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
    assert len(pt.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in pt.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = pt.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert pt._same(value, want), (name, value, want)
