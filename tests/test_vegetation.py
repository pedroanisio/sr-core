"""Tests for the draft SREP "Add scattering and vegetation to the terrain grid" (G1 of SREP 12) and its reference."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODULE = os.path.join(ROOT, "conformance", "tools", "vegetation_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-vegetation.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vg = _load(MODULE, "vegetation_reference")
tg = vg.terrain()
rs = vg.streams()


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _flat_doc(n=20, dx=5.0, radius=8.0, mask=None, seed=3, **scatter):
    doc = {"version": "1.8", "project": 7, "id": "field", "x": 0.0, "y": 0.0, "width": n * dx, "height": n * dx,
           "cells": n, "metersPerCell": dx, "seed": 11, "display": "none",
           "layers": [{"kind": "bedrock", "value": 0.0}], "masks": [], "materials": [], "assets": {},
           "trees": [], "scatters": [dict({"id": "s1", "radius": radius, "seed": seed}, **scatter)], "ecosystem": None}
    if mask is not None:
        doc["masks"].append(mask)
        doc["scatters"][0]["mask"] = mask["id"]
    return doc


# ------------------------------------------------------------------------------------------- Poisson-disk scattering


def test_no_two_points_closer_than_the_radius():
    doc = _flat_doc()
    pts = vg.scatter(doc, doc["scatters"][0])["points"]
    assert len(pts) > 20
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            assert _dist(pts[a]["position"], pts[b]["position"]) >= 8.0 - 1e-9


def test_the_sampling_is_maximal():
    """Bridson's sampling is maximal: no point of the domain is farther than 2 r from a sample (every empty disk of
    radius r would have been found by the k attempts), checked on a grid of probes at r / 2."""
    doc = _flat_doc(n=20, dx=5.0, radius=8.0)
    pts = [p["position"] for p in vg.scatter(doc, doc["scatters"][0])["points"]]
    probes = [(x, y) for x in range(4, 100, 4) for y in range(4, 100, 4)]
    farthest = max(min(_dist(q, p) for p in pts) for q in probes)
    assert farthest < 2.0 * 8.0


def test_points_lie_on_the_grid_and_on_the_surface():
    doc = _flat_doc(n=10, dx=10.0, radius=12.0)
    doc["layers"] = [{"kind": "bedrock", "value": 30.0}]
    out = vg.scatter(doc, doc["scatters"][0])
    for p in out["points"]:
        x, y = p["position"]
        assert 0.0 <= x < 100.0 and 0.0 <= y < 100.0
        assert p["height"] == 30.0
        assert 0.0 <= p["yaw"] < 360.0
        assert p["scale"] == 1.0


def test_the_scatter_is_a_function_of_the_seed():
    a = vg.scatter(_flat_doc(seed=3), _flat_doc(seed=3)["scatters"][0])
    b = vg.scatter(_flat_doc(seed=3), _flat_doc(seed=3)["scatters"][0])
    c = vg.scatter(_flat_doc(seed=4), _flat_doc(seed=4)["scatters"][0])
    assert a["points"] == b["points"] and a["digest"] == b["digest"]
    assert a["points"] != c["points"]


def test_the_mask_gates_the_points():
    """A slope mask over a flat terrain is zero everywhere: no points; an altitude mask passing half the grid keeps
    the points on that half only, and a feathered mask thins them where it is low."""
    doc = _flat_doc(mask={"id": "steep", "kind": "slope", "min": 20.0})
    assert vg.scatter(doc, doc["scatters"][0])["points"] == []
    doc = _flat_doc(n=20, dx=5.0, radius=6.0, mask={"id": "high", "kind": "altitude", "min": 10.0})
    doc["layers"] = [{"kind": "bedrock", "value": 0.0}, {"kind": "loose", "value": 0.0}]
    bed = [[20.0 if i >= 10 else 0.0 for i in range(20)] for _ in range(20)]
    layers = {"bedrock": bed, "loose": tg.flat(20, 20, 0.0)}
    pts = vg.scatter_on(doc, doc["scatters"][0], layers)["points"]
    assert len(pts) > 10 and all(p["position"][0] >= 50.0 for p in pts)
    half = vg.scatter_on(doc, dict(doc["scatters"][0], density=0.3), layers)["points"]
    assert 0 < len(half) < len(pts)


def test_the_scatter_draws_from_the_element_streams():
    doc = _flat_doc()
    spec = doc["scatters"][0]
    e = vg.scatter_seed(doc, spec)
    assert e == rs.E(7, "s1", 3, "scatter")
    first = vg.first_point(spec, e, 100.0, 100.0)
    assert first == (rs.S(e, vg.SCATTER_PURPOSE, 0, 0) * 100.0, rs.S(e, vg.SCATTER_PURPOSE, 0, 1) * 100.0)


def test_scale_and_rotation_options():
    doc = _flat_doc(scaleMin=0.5, scaleMax=1.5, rotate=False)
    pts = vg.scatter(doc, doc["scatters"][0])["points"]
    assert all(0.5 <= p["scale"] <= 1.5 for p in pts) and any(p["scale"] != 1.0 for p in pts)
    assert all(p["yaw"] == 0.0 for p in pts)


def test_the_point_count_is_bounded():
    doc = _flat_doc(maxPoints=10)
    assert len(vg.scatter(doc, doc["scatters"][0])["points"]) == 10


def test_bridson_candidates_lie_in_the_annulus():
    e = rs.E(7, "s1", 3, "scatter")
    for n in range(1, 50):
        c = vg.candidate((50.0, 50.0), 8.0, e, n)
        d = _dist(c, (50.0, 50.0))
        assert 8.0 <= d <= 16.0


# ------------------------------------------------------------------------------------------- exchange


def test_point_instancer_round_trip():
    doc = _flat_doc(n=8, dx=10.0, radius=15.0, scaleMin=0.8, scaleMax=1.2)
    out = vg.scatter(doc, doc["scatters"][0])
    text = vg.to_point_instancer(out["points"], "trees")
    assert 'def PointInstancer "trees"' in text and "point3f[] positions" in text and "quath[] orientations" in text
    assert "float3[] scales" in text and "int[] protoIndices" in text
    back = vg.from_point_instancer(text)
    assert len(back) == len(out["points"])
    for p, q in zip(out["points"], back):
        assert vg.same_point(p, q)


def test_gltf_instancing_round_trip():
    doc = _flat_doc(n=8, dx=10.0, radius=15.0, scaleMin=0.8, scaleMax=1.2)
    out = vg.scatter(doc, doc["scatters"][0])
    g = vg.to_gltf_instancing(out["points"], "trees")
    assert "EXT_mesh_gpu_instancing" in g["extensionsUsed"]
    node = g["nodes"][0]
    attrs = node["extensions"]["EXT_mesh_gpu_instancing"]["attributes"]
    assert set(attrs) == {"TRANSLATION", "ROTATION", "SCALE"}
    assert g["accessors"][attrs["TRANSLATION"]]["count"] == len(out["points"])
    assert g["accessors"][attrs["TRANSLATION"]]["type"] == "VEC3"
    assert g["accessors"][attrs["ROTATION"]]["type"] == "VEC4"
    assert g["buffers"][0]["uri"].startswith("data:application/octet-stream;base64,")
    json.dumps(g)
    back = vg.from_gltf_instancing(g)
    assert len(back) == len(out["points"])
    for p, q in zip(out["points"], back):
        assert vg.same_point(p, q, tol=1e-5)


def test_exchange_axes():
    """The terrain's (x, y) on the grid and its height z map to the y-up frame of USD and glTF: (x, z, y)."""
    pt = {"position": (3.0, 4.0), "height": 5.0, "yaw": 90.0, "scale": 2.0}
    t, r, s = vg.instance_transform(pt)
    assert t == (3.0, 5.0, 4.0) and s == (2.0, 2.0, 2.0)
    assert math.isclose(r[1], math.sin(math.radians(45.0))) and math.isclose(r[3], math.cos(math.radians(45.0)))
    assert r[0] == 0.0 and r[2] == 0.0


# ------------------------------------------------------------------------------------------- L-systems


def test_fibonacci_algae_lengths():
    spec = {"axiom": "A", "rules": [{"from": "A", "to": "AB"}, {"from": "B", "to": "A"}]}
    assert [len(vg.lsystem_string(spec, n)) for n in range(8)] == [1, 2, 3, 5, 8, 13, 21, 34]


def test_koch_curve_has_five_to_the_n_segments():
    spec = {"axiom": "F", "rules": [{"from": "F", "to": "F+F-F-F+F"}], "angle": 90.0}
    for n in range(5):
        s = vg.lsystem_string(spec, n)
        assert s.count("F") == 5 ** n
        segs = vg.turtle(s, spec)
        assert len(segs) == 5 ** n


def test_the_turtle_draws_in_three_dimensions():
    spec = {"axiom": "F[&F][^F][+F][-F]F", "rules": [], "angle": 30.0, "length": 1.0}
    segs = vg.turtle(vg.lsystem_string(spec, 0), spec)
    assert len(segs) == 6
    trunk = segs[0]
    assert trunk["start"] == (0.0, 0.0, 0.0) and trunk["end"] == (0.0, 0.0, 1.0)
    ends = [s["end"] for s in segs[1:5]]
    # the four branches leave the trunk's top in four different directions, each a unit long
    assert len({tuple(round(v, 9) for v in e) for e in ends}) == 4
    for s in segs[1:5]:
        assert math.isclose(math.dist(s["start"], s["end"]), 1.0)
        assert s["start"] == (0.0, 0.0, 1.0)
    # the trunk continues straight up after the branches are popped
    assert segs[5]["start"] == (0.0, 0.0, 1.0) and segs[5]["end"] == (0.0, 0.0, 2.0)


def test_the_turtle_shortens_and_thins_by_depth():
    spec = {"axiom": "F[+F[+F]]", "rules": [], "angle": 20.0, "length": 2.0, "lengthRatio": 0.5, "radius": 0.2,
            "radiusRatio": 0.6}
    segs = vg.turtle(vg.lsystem_string(spec, 0), spec)
    lengths = [math.dist(s["start"], s["end"]) for s in segs]
    assert [round(v, 9) for v in lengths] == [2.0, 1.0, 0.5]
    assert [round(s["radius"], 9) for s in segs] == [0.2, 0.12, 0.072]


def test_the_lsystem_is_bounded():
    with pytest.raises(vg.VegetationError):
        vg.lsystem_string({"axiom": "F", "rules": [{"from": "F", "to": "FF"}]}, 13)
    with pytest.raises(vg.VegetationError):
        vg.lsystem_string({"axiom": "F", "rules": [{"from": "F", "to": "FFFFFFFFFF"}], "maxSymbols": 1000}, 4)


def test_stochastic_rules_draw_from_the_streams():
    """Two rules for one symbol are chosen by weight with S(e, LSYSTEM_PURPOSE, iteration, position)."""
    spec = {"axiom": "F", "rules": [{"from": "F", "to": "F[+F]F", "weight": 0.5}, {"from": "F", "to": "F[-F]F",
                                                                                 "weight": 0.5}]}
    e = rs.E(7, "t1", 5, "tree")
    a = vg.lsystem_string(spec, 3, e)
    b = vg.lsystem_string(spec, 3, e)
    c = vg.lsystem_string(spec, 3, rs.E(7, "t1", 6, "tree"))
    assert a == b and a != c and "+" in a and "-" in a


def test_lsystem_tree_prototype():
    doc = vg.example_document()
    tree = next(t for t in doc["trees"] if t["method"] == "lsystem")
    out = vg.tree(doc, tree)
    assert out["segments"] and out["height"] > 0.0 and out["method"] == "lsystem"
    assert all(s["radius"] > 0.0 for s in out["segments"])


# ------------------------------------------------------------------------------------------- space colonisation


def test_space_colonisation_consumes_the_attractors():
    """Runions et al. 2007: a node within the kill distance of an attractor removes it; the algorithm stops when no
    attractor is within the influence distance of any node. Every attractor ends killed or out of reach."""
    spec = {"id": "t2", "method": "colonisation", "attractors": 200, "crownRadius": 3.0, "crownHeight": 4.0,
            "crownBase": 3.0, "influence": 2.0, "kill": 0.6, "segment": 0.3, "maxIterations": 400, "seed": 2}
    out = vg.colonise({"project": 7}, spec)
    nodes = out["nodes"]
    assert len(nodes) > 20
    for a in out["attractors"]:
        if a["alive"]:
            assert all(math.dist(a["position"], n) > 2.0 - 1e-9 for n in nodes)
        else:
            assert any(math.dist(a["position"], n) <= 0.6 + 1e-9 for n in nodes)
    assert out["killed"] + sum(1 for a in out["attractors"] if a["alive"]) == 200


def test_space_colonisation_segments_and_tree_shape():
    spec = {"id": "t2", "method": "colonisation", "attractors": 150, "crownRadius": 3.0, "crownHeight": 4.0,
            "crownBase": 3.0, "influence": 2.0, "kill": 0.6, "segment": 0.3, "maxIterations": 400, "seed": 2}
    out = vg.colonise({"project": 7}, spec)
    for s in out["segments"]:
        assert math.isclose(math.dist(s["start"], s["end"]), 0.3, rel_tol=1e-9)
    # a tree: every node but the root has one parent, which is an earlier node
    parents = out["parents"]
    assert parents[0] is None and all(0 <= parents[k] < k for k in range(1, len(parents)))
    # the trunk starts at the origin and the crown stays inside the attractor volume plus one segment
    assert out["nodes"][0] == (0.0, 0.0, 0.0)
    for x, y, z in out["nodes"]:
        assert math.hypot(x, y) <= 3.0 + 0.3 + 1e-9 and z <= 3.0 + 4.0 + 0.3 + 1e-9
    # the radii follow Murray's law from the leaves (da Vinci exponent 2: r^2 = sum of the children's r^2)
    radii = out["radii"]
    children = {}
    for k, p in enumerate(parents):
        if p is not None:
            children.setdefault(p, []).append(k)
    for k, kids in children.items():
        assert math.isclose(radii[k] ** 2, sum(radii[c] ** 2 for c in kids), rel_tol=1e-9)
    assert all(math.isclose(radii[k], spec.get("tipRadius", 0.01)) for k in range(len(radii)) if k not in children)


def test_space_colonisation_attractors_draw_from_the_streams():
    spec = {"id": "t2", "method": "colonisation", "attractors": 5, "crownRadius": 3.0, "crownHeight": 4.0,
            "crownBase": 3.0, "seed": 2}
    e = rs.E(7, "t2", 2, "tree")
    pts = vg.attractors(spec, e)
    assert len(pts) == 5
    for k, (x, y, z) in enumerate(pts):
        u = (rs.S(e, vg.ATTRACTOR_PURPOSE, k, 0), rs.S(e, vg.ATTRACTOR_PURPOSE, k, 1), rs.S(e, vg.ATTRACTOR_PURPOSE, k, 2))
        assert vg.attractor_point(u, spec) == (x, y, z)
        assert (x / 3.0) ** 2 + (y / 3.0) ** 2 + ((z - 3.0 - 2.0) / 2.0) ** 2 <= 1.0 + 1e-9


def test_space_colonisation_is_bounded_and_deterministic():
    spec = {"id": "t2", "method": "colonisation", "attractors": 100, "crownRadius": 3.0, "crownHeight": 4.0,
            "crownBase": 30.0, "influence": 2.0, "kill": 0.6, "segment": 0.3, "maxIterations": 5, "seed": 2}
    out = vg.colonise({"project": 7}, spec)
    assert out["iterations"] == 5 and len(out["nodes"]) <= 6
    again = vg.colonise({"project": 7}, spec)
    assert out["nodes"] == again["nodes"]


# ------------------------------------------------------------------------------------------- Weber–Penn


def test_weber_penn_shape_ratios():
    for shape, ratio, want in (("conical", 0.5, 0.6), ("spherical", 0.5, 1.0), ("hemispherical", 1.0, 1.0),
                               ("cylindrical", 0.3, 1.0), ("taperedCylindrical", 0.5, 0.75),
                               ("inverseConical", 0.5, 0.6), ("flame", 0.7, 1.0), ("flame", 0.9, 1.0 / 3.0),
                               ("tendFlame", 0.7, 1.0), ("tendFlame", 1.0, 0.5)):
        assert math.isclose(vg.shape_ratio(shape, ratio), want), (shape, ratio)


def test_weber_penn_stem_counts_and_radii():
    spec = {"id": "t3", "method": "parametric", "levels": 3, "scale": 10.0, "baseSize": 0.3, "ratio": 0.015,
            "ratioPower": 1.2, "shape": "conical",
            "length": [1.0, 0.5, 0.4], "branches": [1, 6, 4], "downAngle": [0.0, 60.0, 45.0],
            "rotate": [0.0, 140.0, 140.0], "curve": [0.0, 0.0, 0.0], "curveRes": [5, 4, 3], "seed": 9}
    out = vg.weber_penn({"project": 7}, spec)
    stems = out["stems"]
    assert [sum(1 for s in stems if s["level"] == lv) for lv in range(3)] == [1, 6, 24]
    assert len(out["segments"]) == 1 * 5 + 6 * 4 + 24 * 3
    trunk = stems[0]
    assert math.isclose(trunk["length"], 10.0) and math.isclose(trunk["radius"], 10.0 * 0.015)
    for s in stems[1:]:
        parent = stems[s["parent"]]
        assert s["length"] < parent["length"]
        assert math.isclose(s["radius"], parent["radius"] * (s["length"] / parent["length"]) ** 1.2)
        assert s["offset"] >= 0.3 * parent["length"] - 1e-9 if parent["level"] == 0 else s["offset"] >= 0.0
    assert out["height"] > 8.0


def test_weber_penn_children_leave_their_parent_at_the_down_angle():
    spec = {"id": "t3", "method": "parametric", "levels": 2, "scale": 10.0, "baseSize": 0.0, "ratio": 0.015,
            "ratioPower": 1.0, "shape": "cylindrical", "length": [1.0, 0.5], "branches": [1, 5],
            "downAngle": [0.0, 60.0], "rotate": [0.0, 72.0], "curve": [0.0, 0.0], "curveRes": [1, 1], "seed": 9}
    out = vg.weber_penn({"project": 7}, spec)
    for s in out["stems"][1:]:
        d = s["direction"]
        assert math.isclose(math.degrees(math.acos(d[2])), 60.0, abs_tol=1e-6)
    yaws = sorted(math.degrees(math.atan2(s["direction"][1], s["direction"][0])) % 360.0 for s in out["stems"][1:])
    gaps = [(b - a) % 360.0 for a, b in zip(yaws, yaws[1:] + yaws[:1])]
    assert all(math.isclose(g, 72.0, abs_tol=1e-6) for g in gaps)


def test_weber_penn_curve_bends_the_stem():
    spec = {"id": "t3", "method": "parametric", "levels": 1, "scale": 10.0, "ratio": 0.015, "shape": "cylindrical",
            "length": [1.0], "branches": [1], "downAngle": [0.0], "rotate": [0.0], "curve": [90.0], "curveRes": [9],
            "seed": 9}
    out = vg.weber_penn({"project": 7}, spec)
    segs = out["segments"]
    assert len(segs) == 9
    first = segs[0]["end"][2] - segs[0]["start"][2]
    last = segs[-1]["end"][2] - segs[-1]["start"][2]
    assert first > last > -1e-9           # the stem bends from vertical toward horizontal over 90 degrees
    straight = vg.weber_penn({"project": 7}, dict(spec, curve=[0.0]))
    assert math.isclose(straight["height"], 10.0)


def test_weber_penn_variation_draws_from_the_streams():
    base = {"id": "t3", "method": "parametric", "levels": 2, "scale": 10.0, "ratio": 0.015, "shape": "conical",
            "length": [1.0, 0.4], "lengthVariation": [0.0, 0.2], "branches": [1, 4], "downAngle": [0.0, 50.0],
            "downAngleVariation": [0.0, 10.0], "rotate": [0.0, 90.0], "curve": [0.0, 0.0], "curveRes": [2, 2],
            "seed": 9}
    a = vg.weber_penn({"project": 7}, base)
    b = vg.weber_penn({"project": 7}, base)
    c = vg.weber_penn({"project": 7}, dict(base, seed=10))
    assert a["segments"] == b["segments"] and a["segments"] != c["segments"]
    lengths = {round(s["length"], 6) for s in a["stems"] if s["level"] == 1}
    assert len(lengths) > 1


# ------------------------------------------------------------------------------------------- sway


def test_sway_follows_the_wind():
    tree = {"height": 10.0, "dragArea": 20.0, "stiffness": 2.0e6}
    assert vg.sway(tree, (0.0, 0.0)) == {"angle": 0.0, "direction": (1.0, 0.0), "deflection": 0.0}
    s = vg.sway(tree, (6.0, 0.0))
    # drag F = 1/2 rho Cd A U^2 at the crown; tip deflection F H^3 / (3 EI); angle atan(deflection / H)
    f = 0.5 * vg.AIR_DENSITY * vg.DRAG_COEFFICIENT * 20.0 * 36.0
    want = f * 1000.0 / (3.0 * 2.0e6)
    assert math.isclose(s["deflection"], want) and math.isclose(s["angle"], math.degrees(math.atan(want / 10.0)))
    assert s["direction"] == (1.0, 0.0)
    diag = vg.sway(tree, (3.0, 3.0))
    assert math.isclose(diag["direction"][0], diag["direction"][1])
    assert vg.sway(dict(tree, stiffness=4.0e6), (6.0, 0.0))["deflection"] < s["deflection"]
    assert math.isclose(vg.sway(tree, (12.0, 0.0))["deflection"], 4.0 * s["deflection"])


def test_sway_is_capped():
    tree = {"height": 10.0, "dragArea": 20.0, "stiffness": 1.0}
    s = vg.sway(tree, (30.0, 0.0))
    assert s["deflection"] == vg.MAX_DEFLECTION * 10.0 and math.isclose(s["angle"], math.degrees(math.atan(vg.MAX_DEFLECTION)))


def test_instances_sway_in_the_wind_field_at_their_positions():
    doc = vg.example_document()
    doc["physics"] = {"winds": [{"id": "w1", "speed": 8.0, "direction": 0.0, "turbulence": 0.3, "seed": 3}]}
    doc["scatters"][0]["wind"] = "w1"
    out = vg.instances(doc, 10.0)
    inst = out["instances"]
    assert inst and all(i["sway"]["angle"] > 0.0 for i in inst)
    assert len({round(i["sway"]["angle"], 9) for i in inst}) > 1       # turbulence varies the sway by position
    calm = dict(doc)
    calm["scatters"] = [dict(doc["scatters"][0], wind=None)]
    assert all(i["sway"]["angle"] == 0.0 for i in vg.instances(calm, 10.0)["instances"])


# ------------------------------------------------------------------------------------------- ecosystem


def _eco_doc(n=20, dx=5.0, years=0.0, **eco):
    doc = _flat_doc(n=n, dx=dx, radius=3.0)
    doc["trees"] = [{"id": "oak", "method": "lsystem", "axiom": "F", "rules": [], "length": 8.0, "radius": 0.3}]
    doc["scatters"][0]["prototype"] = "oak"
    doc["ecosystem"] = dict({"scatter": "s1", "species": [
        {"prototype": "oak", "growth": 0.5, "maxRadius": 6.0, "maxAge": 200, "offspring": 1, "spread": 3.0}],
        "yearsPerSecond": 1.0, "maxYears": 1000}, **eco)
    return doc


def test_the_ecosystem_starts_from_the_scatter():
    doc = _eco_doc()
    start = vg.ecosystem(doc, 0.0)
    pts = vg.scatter(doc, doc["scatters"][0])["points"]
    assert len(start["plants"]) == len(pts)
    assert all(p["radius"] == vg.SEEDLING_RADIUS and p["age"] == 0 for p in start["plants"])
    assert start["years"] == 0


def test_plants_grow_logistically_and_die_of_age():
    doc = _eco_doc(species=[{"prototype": "oak", "growth": 0.5, "maxRadius": 6.0, "maxAge": 10, "offspring": 0,
                             "spread": 3.0}])
    one = vg.ecosystem(doc, 1.0)["plants"]
    r0 = vg.SEEDLING_RADIUS
    assert all(math.isclose(p["radius"], r0 + 0.5 * (1.0 - r0 / 6.0)) for p in one)
    assert all(p["age"] == 1 for p in one)
    assert vg.ecosystem(doc, 10.0)["plants"] == []


def test_self_thinning_leaves_no_overlap_and_fewer_larger_plants():
    """Deussen et al. 1998: when two plants' circles overlap the weaker (smaller) one dies. A dense stand thins as
    it grows: fewer plants, larger on average, none overlapping."""
    doc = _eco_doc(species=[{"prototype": "oak", "growth": 0.5, "maxRadius": 6.0, "maxAge": 500, "offspring": 0,
                             "spread": 3.0}])
    states = [vg.ecosystem(doc, t) for t in (0.0, 5.0, 10.0, 20.0)]
    counts = [len(s["plants"]) for s in states]
    assert counts[0] > counts[1] > counts[2] >= counts[3] > 0
    means = [sum(p["radius"] for p in s["plants"]) / len(s["plants"]) for s in states]
    assert means[0] < means[1] < means[2] <= means[3]
    for s in states:
        plants = s["plants"]
        for a in range(len(plants)):
            for b in range(a + 1, len(plants)):
                assert _dist(plants[a]["position"], plants[b]["position"]) >= plants[a]["radius"] + plants[b]["radius"] - 1e-9


def test_offspring_spread_from_their_parents_by_the_streams():
    doc = _eco_doc(n=40, dx=5.0, species=[{"prototype": "oak", "growth": 0.5, "maxRadius": 2.0, "maxAge": 500,
                                            "maturity": 1, "offspring": 2, "spread": 4.0}])
    doc["scatters"][0].update(maxPoints=3, radius=40.0)
    before = vg.ecosystem(doc, 0.0)["plants"]
    after = vg.ecosystem(doc, 3.0)["plants"]
    assert len(after) > len(before)
    assert vg.SPECIES_DEFAULTS["maturity"] == 5
    late = json.loads(json.dumps(doc))
    late["ecosystem"]["species"][0]["maturity"] = 10
    assert len(vg.ecosystem(late, 3.0)["plants"]) == len(before)
    young = [p for p in after if p["age"] < 3]
    assert young
    for p in young:
        assert p["parent"] is not None
    plants_by_id = {p["id"]: p for p in after}
    for p in young:
        if p["parent"] in plants_by_id:
            parent = plants_by_id[p["parent"]]
            assert _dist(p["position"], parent["position"]) <= parent["radius"] + 4.0 + 1e-9
    assert vg.ecosystem(doc, 3.0)["plants"] == after


def test_the_ecosystem_respects_the_mask_and_the_grid():
    doc = _eco_doc(n=20, dx=5.0, species=[{"prototype": "oak", "growth": 0.5, "maxRadius": 2.0, "maxAge": 500,
                                            "maturity": 2, "offspring": 3, "spread": 6.0}])
    doc["layers"] = [{"kind": "bedrock", "value": 0.0}]
    doc["masks"] = [{"id": "high", "kind": "altitude", "min": 10.0}]
    doc["scatters"][0]["mask"] = "high"
    bed = [[20.0 if i >= 10 else 0.0 for i in range(20)] for _ in range(20)]
    state = vg.ecosystem_on(doc, 20.0, {"bedrock": bed})
    assert state["plants"]
    for p in state["plants"]:
        x, y = p["position"]
        assert 50.0 <= x < 100.0 and 0.0 <= y < 100.0


def test_every_frame_alone_and_bounded():
    doc = _eco_doc(yearsPerSecond=2.0, maxYears=7)
    assert vg.years_for(3.0, 2.0, 7) == 6 and vg.years_for(100.0, 2.0, 7) == 7
    a = vg.ecosystem(doc, 3.0)
    b = vg.ecosystem(doc, 3.0)
    assert a == b and a["years"] == 6
    assert vg.ecosystem(doc, 100.0)["years"] == 7


def test_ecosystem_instances_replace_the_scatter():
    doc = vg.example_document()
    out = vg.instances(doc, 30.0)
    assert out["years"] == 30 and out["instances"]
    assert all(i["prototype"] in {t["id"] for t in doc["trees"]} for i in out["instances"])
    assert all(i["scale"] > 0.0 for i in out["instances"])


# ------------------------------------------------------------------------------------------- the run and validation


def test_run_outputs():
    doc = vg.example_document()
    out = vg.run(doc, 30.0)
    assert out["shape"] == (16, 12)
    assert out["trees"] and all(t["segments"] for t in out["trees"].values())
    assert out["instances"] and all({"position", "height", "yaw", "scale", "prototype", "sway"} <= set(i) for i in out["instances"])
    assert out["digest"] == vg.run(doc, 30.0)["digest"]
    assert out["digest"] != vg.run(doc, 0.0)["digest"]


def test_validation_one_at_a_time():
    doc = vg.example_document()
    assert vg.validate_document(doc) == []
    assert vg.validate_document(vg.bad_document()) == ["VG1", "VG2", "VG3", "VG4", "VG5"]

    def with_(**changes):
        d = json.loads(json.dumps(doc))
        for path, value in changes.items():
            target = d
            keys = path.split(".")
            for k in keys[:-1]:
                target = target[int(k)] if k.isdigit() else target[k]
            target[keys[-1]] = value
        return d

    assert vg.validate_document(with_(**{"scatters.0.radius": 0.0})) == ["VG1"]
    assert vg.validate_document(with_(**{"scatters.0.attempts": 0})) == ["VG1"]
    assert vg.validate_document(with_(**{"scatters.0.scaleMin": 2.0})) == ["VG1"]
    assert vg.validate_document(with_(**{"scatters.0.density": 1.5})) == ["VG1"]
    assert vg.validate_document(with_(**{"scatters.0.mask": "nowhere"})) == ["VG2"]
    assert vg.validate_document(with_(**{"scatters.0.wind": "w9"})) == ["VG2"]
    assert vg.validate_document(with_(**{"scatters.0.prototype": "ghost"})) == ["VG3"]
    assert vg.validate_document(with_(**{"trees.0.iterations": 13})) == ["VG4"]
    assert vg.validate_document(with_(**{"trees.1.levels": 5})) == ["VG4"]
    assert vg.validate_document(with_(**{"trees.1.shape": "blob"})) == ["VG4"]
    assert vg.validate_document(with_(**{"trees.2.kill": 3.0})) == ["VG4"]
    assert vg.validate_document(with_(**{"trees.0.stiffness": 0.0})) == ["VG4"]
    assert vg.validate_document(with_(**{"ecosystem.species.0.growth": -1.0})) == ["VG5"]
    assert vg.validate_document(with_(**{"ecosystem.species.0.prototype": "ghost"})) == ["VG5"]
    assert vg.validate_document(with_(**{"ecosystem.scatter": "s9"})) == ["VG5"]
    assert vg.validate_document(with_(version="1.7")) == ["V17"]
    plain = dict(doc)
    plain.pop("trees")
    plain.pop("scatters")
    plain.pop("ecosystem")
    assert vg.validate_document(plain) == []


def test_constants_and_defaults():
    assert vg.SCATTER_DEFAULTS["attempts"] == 30 and vg.SCATTER_DEFAULTS["maxPoints"] == 100000
    assert vg.SCATTER_DEFAULTS["density"] == 1.0 and vg.SCATTER_DEFAULTS["rotate"] is True
    assert vg.LSYSTEM_DEFAULTS["angle"] == 25.0 and vg.LSYSTEM_DEFAULTS["iterations"] == 4
    assert vg.MAX_ITERATIONS == 12 and vg.LSYSTEM_DEFAULTS["maxSymbols"] == 1000000
    assert vg.COLONISATION_DEFAULTS["influence"] > vg.COLONISATION_DEFAULTS["kill"] > 0.0
    assert vg.PARAMETRIC_DEFAULTS["shape"] == "conical" and vg.PARAMETRIC_DEFAULTS["ratioPower"] == 1.2
    assert vg.SWAY_DEFAULTS["stiffness"] > 0.0 and vg.SWAY_DEFAULTS["dragArea"] > 0.0
    assert vg.AIR_DENSITY == 1.225 and vg.DRAG_COEFFICIENT == 0.5 and vg.MAX_DEFLECTION == 0.5
    assert vg.ECOSYSTEM_DEFAULTS["yearsPerSecond"] == 1.0 and vg.ECOSYSTEM_DEFAULTS["maxYears"] == 10000
    assert vg.SEEDLING_RADIUS == 0.25
    assert vg.SHAPES == ("conical", "spherical", "hemispherical", "cylindrical", "taperedCylindrical", "flame",
                         "inverseConical", "tendFlame")


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
    for word in ("SR-110", "SR-100", "SR-101", "SREP 12", "SREP 14", "SREP 26", "SREP 66", "`scatter`", "`tree`",
                 "`ecosystem`", "radius", "attempts", "maxPoints", "density", "scaleMin", "scaleMax", "rotate",
                 "prototype", "`mask`", "`wind`", "axiom", "rules", "iterations", "maxSymbols", "lengthRatio",
                 "radiusRatio", "attractors", "crownRadius", "crownHeight", "crownBase", "influence", "kill",
                 "segment", "maxIterations", "tipRadius", "levels", "baseSize", "ratioPower", "shape", "downAngle",
                 "curveRes", "lengthVariation", "stiffness", "dragArea", "species", "growth", "maxRadius", "maxAge",
                 "offspring", "spread", "maturity", "yearsPerSecond", "maxYears", "VG1", "VG2", "VG3", "VG4", "VG5", "V17",
                 "vegetation_reference.py", "terrain-grid", "wind-field", "random-streams", "Bridson", "Poisson-disk",
                 "PointInstancer", "EXT_mesh_gpu_instancing", "Lindenmayer", "Prusinkiewicz", "Fibonacci", "Koch",
                 "5ⁿ", "Runions", "space colonisation", "Weber", "Penn", "Murray", "Deussen", "self-thinning",
                 "cantilever", "drag", "turtle", "y-up", "Apache-2.0", "maximal", "annulus"):
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
    assert len(vg.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in vg.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = vg.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert vg._same(value, want), (name, value, want)
