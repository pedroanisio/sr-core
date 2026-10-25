"""Tests for the draft SREP "Add 3D Tiles to the map" (M5 of SREP 12) and its reference module."""
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import zipfile

import pytest

np = pytest.importorskip("numpy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "tiles3d_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-tiles3d.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t3 = _load(MODULE, "tiles3d_reference")

R = 6378137.0
B = 6356752.314245179


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list, np.ndarray)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------------------------------------- geodesy


def test_ecef_of_the_reference_points():
    assert _close(t3.ecef(0.0, 0.0, 0.0), (R, 0.0, 0.0))
    assert _close(t3.ecef(90.0, 0.0, 0.0), (0.0, R, 0.0))
    assert _close(t3.ecef(0.0, 90.0, 0.0), (0.0, 0.0, B))
    assert _close(t3.ecef(0.0, 0.0, 100.0), (R + 100.0, 0.0, 0.0))


@pytest.mark.parametrize("lon, lat, h", [(24.94, 60.17, 35.5), (-75.6, -32.1, -120.0), (179.9, 89.0, 8848.0),
                                         (0.0, 0.0, 0.0), (-180.0, 45.0, 1.0)])
def test_geodetic_inverts_ecef(lon, lat, h):
    x, y, z = t3.ecef(lon, lat, h)
    lon2, lat2, h2 = t3.geodetic(x, y, z)
    assert abs(((lon2 - lon + 180.0) % 360.0) - 180.0) < 1e-9
    assert abs(lat2 - lat) < 1e-9 and abs(h2 - h) < 1e-6


def test_the_east_north_up_frame_is_orthonormal_and_placed():
    m = t3.enu_matrix(0.0, 0.0, 0.0)
    assert _close(m[:3, 0], (0.0, 1.0, 0.0)) and _close(m[:3, 1], (0.0, 0.0, 1.0)) and _close(m[:3, 2], (1.0, 0.0, 0.0))
    assert _close(m[:3, 3], (R, 0.0, 0.0)) and _close(m[3], (0.0, 0.0, 0.0, 1.0))
    m = t3.enu_matrix(24.94, 60.17, 20.0)
    assert np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3), atol=1e-12)
    assert _close(t3.apply(m, (0.0, 0.0, 0.0)), t3.ecef(24.94, 60.17, 20.0))
    assert _close(t3.geodetic(*t3.apply(m, (0.0, 0.0, 10.0)))[2], 30.0)


def test_matrices_are_column_major_and_compose_parent_first():
    m = t3.mat4([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 6, 7, 1])
    assert _close(t3.apply(m, (0.0, 0.0, 0.0)), (5.0, 6.0, 7.0))
    s = t3.mat4([2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1])
    assert _close(t3.apply(t3.compose(m, s), (1.0, 1.0, 1.0)), (7.0, 8.0, 9.0))
    assert _close(t3.apply(t3.compose(s, m), (1.0, 1.0, 1.0)), (12.0, 14.0, 16.0))
    assert _close(t3.apply(t3.Y_UP_TO_Z_UP, (0.0, 1.0, 0.0)), (0.0, 0.0, 1.0))
    assert _close(t3.apply(t3.Y_UP_TO_Z_UP, (0.0, 0.0, 1.0)), (0.0, -1.0, 0.0))
    with pytest.raises(t3.TilesError):
        t3.mat4([1.0] * 15)


# --------------------------------------------------------------------------------------------------- implicit tiling


def test_morton_indices_follow_the_specification_examples():
    assert t3.morton(0b11, 0b00) == 0b0101
    assert t3.morton(0b1010, 0b0011) == 0b01001110
    assert t3.morton(0b001, 0b010, 0b100) == 0b100010001
    assert t3.demorton(0b01001110, 2) == (0b1010, 0b0011)
    assert t3.demorton(0b100010001, 3) == (0b001, 0b010, 0b100)
    for i in range(64):
        assert t3.morton(*t3.demorton(i, 2)) == i
        assert t3.morton(*t3.demorton(i, 3)) == i


def test_availability_indices_add_the_level_offset():
    assert t3.level_offset(0, 4) == 0 and t3.level_offset(2, 4) == 5 and t3.level_offset(3, 4) == 21
    assert t3.level_offset(3, 8) == 73
    assert t3.availability_index((2, 1, 2)) == 5 + t3.morton(1, 2)
    assert t3.availability_index((1, 1, 0, 1)) == 1 + t3.morton(1, 0, 1)


def test_implicit_children_come_in_morton_order():
    assert t3.child_coords((0, 0, 0)) == [(1, 0, 0), (1, 1, 0), (1, 0, 1), (1, 1, 1)]
    assert t3.child_coords((1, 1, 0))[:2] == [(2, 2, 0), (2, 3, 0)]
    kids = t3.child_coords((0, 0, 0, 0))
    assert len(kids) == 8 and kids[0] == (1, 0, 0, 0) and kids[1] == (1, 1, 0, 0) and kids[4] == (1, 0, 0, 1)


def test_implicit_bounds_halve_the_root_volume():
    box = ("box", [0.5, 0.5, 0.5, 0.5, 0, 0, 0, 0.5, 0, 0, 0, 0.5])
    kind, v = t3.implicit_bounds(box, (1, 1, 0))
    assert kind == "box" and _close(v, [0.75, 0.25, 0.5, 0.25, 0, 0, 0, 0.25, 0, 0, 0, 0.5])
    kind, v = t3.implicit_bounds(box, (1, 1, 0, 1))
    assert _close(v, [0.75, 0.25, 0.75, 0.25, 0, 0, 0, 0.25, 0, 0, 0, 0.25])
    region = ("region", [0.0, 0.0, 1.0, 1.0, 0.0, 10.0])
    assert _close(t3.implicit_bounds(region, (1, 0, 1))[1], [0.0, 0.5, 0.5, 1.0, 0.0, 10.0])
    assert _close(t3.implicit_bounds(region, (1, 0, 0, 1))[1], [0.0, 0.0, 0.5, 0.5, 5.0, 10.0])
    assert _close(t3.implicit_bounds(region, (2, 3, 0))[1], [0.75, 0.0, 1.0, 0.25, 0.0, 10.0])
    assert t3.implicit_error(32.0, 3) == 4.0
    with pytest.raises(t3.TilesError):
        t3.implicit_bounds(("sphere", [0, 0, 0, 1]), (1, 0, 0))


def test_subtree_roots_and_local_coordinates():
    assert t3.subtree_root((5, 13, 6), 3) == (3, 3, 1)
    assert t3.local_coord((5, 13, 6), (3, 3, 1)) == (2, 1, 2)
    assert t3.subtree_root((2, 3, 1), 3) == (0, 0, 0)
    assert t3.subtree_root((6, 5, 2, 7), 3) == (6, 5, 2, 7)
    assert t3.template("subtrees/{level}.{x}.{y}.subtree", (2, 1, 3)) == "subtrees/2.1.3.subtree"
    assert t3.template("c/{level}__{x}_{y}_{z}.glb", (1, 0, 1, 1)) == "c/1__0_1_1.glb"


SAMPLE_TILES = {(0, 0, 0), (1, 1, 0), (1, 0, 1)} | {(2,) + t3.demorton(m, 2) for m in (4, 7, 8, 11)}
SAMPLE_CHILDREN = {(3,) + t3.demorton(m, 2) for m in (1, 2, 13, 14, 17, 18, 29, 30)}


def test_the_subtree_writer_reproduces_the_sample_bitstreams():
    """The availability of the CesiumGS sample SparseImplicitQuadtree's root subtree (7 tiles, no content, 8 child
    subtrees): its bitstreams are 0d 32 01 and 06 60 06 60 00 00 00 00."""
    data = t3.subtree_write("QUADTREE", 3, SAMPLE_TILES, set(), SAMPLE_CHILDREN)
    magic, version, json_length, binary_length = struct.unpack("<4sIQQ", data[:24])
    assert magic == b"subt" and version == 1 and json_length % 8 == 0 and binary_length % 8 == 0
    assert len(data) == 24 + json_length + binary_length
    header = json.loads(data[24:24 + json_length])
    assert header["tileAvailability"]["availableCount"] == 7
    assert header["contentAvailability"] == [{"constant": 0, "availableCount": 0}]
    assert header["childSubtreeAvailability"]["availableCount"] == 8
    views = header["bufferViews"]
    binary = data[24 + json_length:]
    tiles = views[header["tileAvailability"]["bitstream"]]
    kids = views[header["childSubtreeAvailability"]["bitstream"]]
    assert binary[tiles["byteOffset"]:tiles["byteOffset"] + tiles["byteLength"]] == bytes.fromhex("0d3201")
    assert binary[kids["byteOffset"]:kids["byteOffset"] + kids["byteLength"]] == bytes.fromhex("0660066000000000")
    assert all(v["byteOffset"] % 8 == 0 for v in views)


def test_subtrees_round_trip_and_constants_stand_for_full_bitstreams():
    data = t3.subtree_write("QUADTREE", 3, SAMPLE_TILES, {(1, 1, 0)}, SAMPLE_CHILDREN)
    sub = t3.subtree_read(data)
    assert {c for c in t3.all_coords(3, 2) if t3.tile_available(sub, c)} == SAMPLE_TILES
    assert {c for c in t3.all_coords(3, 2) if t3.content_available(sub, c)} == {(1, 1, 0)}
    assert {c for c in t3.child_coords_at(3, 2) if t3.child_available(sub, c)} == SAMPLE_CHILDREN
    everything = set(t3.all_coords(2, 2))
    data = t3.subtree_write("QUADTREE", 2, everything, everything, set())
    header = json.loads(data[24:24 + struct.unpack("<Q", data[8:16])[0]])
    assert header["tileAvailability"] == {"constant": 1} and header["contentAvailability"] == [{"constant": 1}]
    assert header["childSubtreeAvailability"] == {"constant": 0, "availableCount": 0}
    assert struct.unpack("<Q", data[16:24])[0] == 0 and "buffers" not in header
    with pytest.raises(t3.TilesError):
        t3.subtree_read(b"subx" + data[4:])
    with pytest.raises(t3.TilesError):
        t3.subtree_read(data[:40])
    with pytest.raises(t3.TilesError):
        t3.subtree_write("QUADTREE", 2, {(0, 0, 0)}, {(1, 0, 0)}, set())


# ------------------------------------------------------------------------------------------------------ the tileset


def _tileset(root, version="1.1", error=100.0):
    return {"asset": {"version": version}, "geometricError": error, "root": root}


def _box(cx=0.0, cy=0.0, cz=0.0, hx=5.0, hy=5.0, hz=5.0):
    return {"box": [cx, cy, cz, hx, 0, 0, 0, hy, 0, 0, 0, hz]}


def test_a_tileset_parses_with_inherited_refinement_and_composed_transforms():
    ts = _tileset({"boundingVolume": _box(), "geometricError": 10.0, "refine": "REPLACE",
                   "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1],
                   "content": {"uri": "low.glb"},
                   "children": [{"boundingVolume": _box(), "geometricError": 1.0,
                                 "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 5, 0, 1],
                                 "content": {"uri": "mid.glb"},
                                 "children": [{"boundingVolume": {"region": [0, 0, 0.1, 0.1, 0, 20]},
                                               "geometricError": 0.0, "refine": "ADD",
                                               "contents": [{"uri": "a.glb"}, {"uri": "b.b3dm"}]}]}]})
    root = t3.parse_tileset(ts, base="city/")
    assert root["refine"] == "REPLACE" and root["contents"] == ["city/low.glb"] and root["error"] == 10.0
    child = root["children"][0]
    assert child["refine"] == "REPLACE" and _close(t3.apply(child["matrix"], (0, 0, 0)), (10.0, 5.0, 0.0))
    leaf = child["children"][0]
    assert leaf["refine"] == "ADD" and leaf["contents"] == ["city/a.glb", "city/b.b3dm"]
    assert leaf["volume"][0] == "region" and leaf["children"] == []
    assert t3.parse_tileset(json.dumps(ts).encode())["contents"] == ["low.glb"]


@pytest.mark.parametrize("patch, words", [
    (lambda ts: ts["asset"].update(version="0.9"), "version"),
    (lambda ts: ts["root"].pop("refine"), "refine"),
    (lambda ts: ts["root"].update(refine="MERGE"), "refine"),
    (lambda ts: ts["root"].update(boundingVolume={"box": [0.0] * 11}), "box"),
    (lambda ts: ts["root"].update(boundingVolume={"region": [0, 0.5, 0.1, 0.1, 0, 20]}), "region"),
    (lambda ts: ts["root"].update(boundingVolume={"sphere": [0, 0, 0, -1]}), "sphere"),
    (lambda ts: ts["root"].update(boundingVolume={}), "boundingVolume"),
    (lambda ts: ts["root"].update(geometricError=-1.0), "geometricError"),
    (lambda ts: ts["root"].update(transform=[1.0] * 15), "transform"),
    (lambda ts: ts["root"].update(content={"url": "x.glb"}), "uri"),
    (lambda ts: ts["root"].update(implicitTiling={"subdivisionScheme": "TRIANGLE", "subtreeLevels": 2,
                                                  "availableLevels": 3, "subtrees": {"uri": "s/{level}.subtree"}}),
     "subdivisionScheme"),
    (lambda ts: ts["root"].update(boundingVolume={"sphere": [0, 0, 0, 1]},
                                  implicitTiling={"subdivisionScheme": "QUADTREE", "subtreeLevels": 2,
                                                  "availableLevels": 3, "subtrees": {"uri": "s/{level}.subtree"}}),
     "sphere"),
    (lambda ts: ts["root"].update(children=[{"boundingVolume": _box(), "geometricError": 0.0}],
                                  implicitTiling={"subdivisionScheme": "QUADTREE", "subtreeLevels": 2,
                                                  "availableLevels": 3, "subtrees": {"uri": "s/{level}.subtree"}}),
     "children"),
    (lambda ts: ts["root"].update(implicitTiling={"subdivisionScheme": "QUADTREE", "subtreeLevels": 4,
                                                  "availableLevels": 3, "subtrees": {"uri": "s/{level}.subtree"}}),
     "availableLevels"),
    (lambda ts: ts.pop("root"), "root"),
])
def test_malformed_tilesets_are_refused_with_tl4(patch, words):
    ts = _tileset({"boundingVolume": _box(), "geometricError": 10.0, "refine": "REPLACE", "content": {"uri": "a.glb"}})
    patch(ts)
    errors = t3.tileset_errors(ts)
    assert errors and all(code == "TL4" for code, _ in errors)
    assert any(words in message for _, message in errors)
    with pytest.raises(t3.TilesError):
        t3.parse_tileset(ts)


def test_content_kinds_follow_the_extension():
    assert t3.content_kind("a/b.glb") == "glb" and t3.content_kind("X.B3DM") == "b3dm"
    assert t3.content_kind("city/tileset.json") == "tileset"
    for uri in ("p.pnts", "t.i3dm", "c.cmpt", "m.gltf", "noext", "a.glb.txt"):
        assert t3.content_kind(uri) == "unsupported"


# --------------------------------------------------------------------------------------------------------- content


TRI = ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)])


def test_a_glb_round_trips_and_lands_z_up():
    data = t3.glb_write([TRI])
    assert data[:4] == b"glTF" and struct.unpack("<I", data[4:8])[0] == 2
    assert struct.unpack("<I", data[8:12])[0] == len(data) and len(data) % 4 == 0
    assert data[16:20] == b"JSON"
    meshes = t3.glb_read(data)
    assert len(meshes) == 1
    assert _close(meshes[0]["positions"].tolist(), [[0, 0, 0], [1, 0, 0], [0, 0, 1]])
    assert meshes[0]["indices"].tolist() == [[0, 1, 2]]


def test_glb_node_transforms_apply_before_the_axis_change():
    data = t3.glb_write([TRI], node_translation=(0.0, 2.0, 0.0))
    meshes = t3.glb_read(data)
    assert _close(meshes[0]["positions"][0].tolist(), [0.0, 0.0, 2.0])
    data = t3.glb_write([TRI], node_matrix=[2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 1])
    assert _close(t3.glb_read(data)[0]["positions"][2].tolist(), [0.0, 0.0, 2.0])


@pytest.mark.parametrize("index_type", [5121, 5123, 5125])
def test_glb_index_types_and_unindexed_triangles(index_type):
    data = t3.glb_write([TRI], index_type=index_type)
    assert t3.glb_read(data)[0]["indices"].tolist() == [[0, 1, 2]]
    data = t3.glb_write([(TRI[0], None)])
    assert t3.glb_read(data)[0]["indices"].tolist() == [[0, 1, 2]]


def test_malformed_glbs_are_refused():
    data = t3.glb_write([TRI])
    with pytest.raises(t3.TilesError):
        t3.glb_read(b"gltF" + data[4:])
    with pytest.raises(t3.TilesError):
        t3.glb_read(data[:-8])
    with pytest.raises(t3.TilesError):
        t3.glb_read(data[:12] + b"\x00" * 4 + b"JUNK" + data[20:])
    header = json.loads(data[20:20 + struct.unpack("<I", data[12:16])[0]])
    header["accessors"][0]["sparse"] = {"count": 1}
    with pytest.raises(t3.TilesError):
        t3.glb_read(t3.glb_pack(header, t3.glb_binary(data)))


def test_b3dm_wraps_a_glb_with_a_feature_table():
    glb = t3.glb_write([TRI])
    b3dm = t3.b3dm_write(glb, rtc=(1.0, 2.0, 3.0))
    magic, version, length, ft_json, ft_bin, bt_json, bt_bin = struct.unpack("<4sIIIIII", b3dm[:28])
    assert magic == b"b3dm" and version == 1 and length == len(b3dm) and length % 8 == 0
    assert (28 + ft_json + ft_bin + bt_json + bt_bin) % 8 == 0 and bt_json == 0 and bt_bin == 0
    table = json.loads(b3dm[28:28 + ft_json])
    assert table["BATCH_LENGTH"] == 0 and table["RTC_CENTER"] == [1.0, 2.0, 3.0]
    inner, rtc = t3.b3dm_glb(b3dm)
    assert inner == glb and rtc == (1.0, 2.0, 3.0)
    meshes = t3.content_meshes("b3dm", b3dm)
    assert _close(meshes[0]["positions"][2].tolist(), [1.0, 2.0, 4.0])
    assert t3.b3dm_glb(t3.b3dm_write(glb))[1] is None
    with pytest.raises(t3.TilesError):
        t3.b3dm_glb(b"b3dm" + b"\x00" * 20)


def test_tile_meshes_apply_the_tile_matrix_after_the_content_frame():
    m = t3.enu_matrix(0.0, 0.0, 0.0)
    tile = {"matrix": m, "contents": ["a.glb"]}
    meshes = t3.tile_meshes(tile, {"a.glb": t3.glb_write([TRI])})
    assert _close(meshes[0]["positions"][2].tolist(), [R + 1.0, 0.0, 0.0])
    assert _close(meshes[0]["positions"][1].tolist(), [R, 1.0, 0.0])


# ---------------------------------------------------------------------------------------------- volumes and the view


def test_bounding_volume_corners():
    corners = t3.volume_corners(("box", [0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 3]), t3.IDENTITY)
    assert len(corners) == 8 and _close(np.max(corners, axis=0), (1, 2, 3)) and _close(np.min(corners, axis=0), (-1, -2, -3))
    corners = t3.volume_corners(("sphere", [1, 2, 3, 0.5]), t3.IDENTITY)
    assert _close(np.max(corners, axis=0), (1.5, 2.5, 3.5))
    shift = t3.mat4([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 100, 0, 0, 1])
    assert _close(np.max(t3.volume_corners(("sphere", [1, 2, 3, 0.5]), shift), axis=0), (101.5, 2.5, 3.5))
    region = ("region", [0.0, 0.0, math.radians(1.0), math.radians(1.0), 0.0, 10.0])
    corners = t3.volume_corners(region, shift)
    assert _close(corners[0], t3.ecef(0.0, 0.0, 0.0)) and _close(corners[-1], t3.ecef(1.0, 1.0, 10.0))


def test_screen_space_error_formulas():
    assert t3.focal_pixels(400, 90.0) == pytest.approx(200.0)
    assert t3.sse_perspective(2.0, 100.0, 200.0) == pytest.approx(4.0)
    assert t3.sse_perspective(1.0, 0.0, 200.0) == math.inf
    assert t3.sse_orthographic(10.0, 0.5) == pytest.approx(5.0)
    assert t3.pixels_per_metre(0, 0.0) == pytest.approx(256.0 / (2.0 * math.pi * R))
    assert t3.pixels_per_metre(10, 60.0) == pytest.approx(256.0 * 1024 / (2.0 * math.pi * R * 0.5))
    assert t3.distance_to_aabb((0.0, 0.0, 0.0), ((1.0, 1.0, 1.0), (2.0, 2.0, 2.0))) == pytest.approx(math.sqrt(3.0))
    assert t3.distance_to_aabb((1.5, 1.5, 1.5), ((1.0, 1.0, 1.0), (2.0, 2.0, 2.0))) == 0.0


def test_the_perspective_camera_basis_and_projection():
    view = {"kind": "perspective", "position": (0.0, 0.0, -10.0), "target": (0.0, 0.0, 0.0), "fov": 90.0,
            "width": 400, "height": 300}
    f, r, d = t3.camera_basis(view)
    assert _close(f, (0, 0, 1)) and _close(r, (1, 0, 0)) and _close(d, (0, 1, 0))
    assert _close(t3.project(view, (0.0, 0.0, 0.0)), (200.0, 150.0))
    assert _close(t3.project(view, (1.0, 0.0, 0.0)), (220.0, 150.0))
    assert _close(t3.project(view, (0.0, -1.0, 0.0)), (200.0, 130.0))
    assert t3.project(view, (0.0, 0.0, -10.0)) is None
    view["position"] = (0.0, -10.0, 0.0)
    f, r, d = t3.camera_basis(view)
    assert _close(f, (0, 1, 0)) and _close(r, (-1, 0, 0)) and _close(d, (0, 0, 1))
    view["position"] = (0.0, -10.0, -10.0)
    f, r, d = t3.camera_basis(view)
    assert _close(r, (-1, 0, 0)) and d[2] > 0 and d[1] < 0


def test_frustum_visibility():
    view = {"kind": "perspective", "position": (0.0, 0.0, -10.0), "target": (0.0, 0.0, 0.0), "fov": 90.0,
            "width": 400, "height": 400}
    assert t3.visible(((-1, -1, -1), (1, 1, 1)), view)
    assert not t3.visible(((100, -1, -1), (102, 1, 1)), view)
    assert not t3.visible(((-1, -1, -30), (1, 1, -20)), view)
    assert t3.visible(((-1000, -1000, -1), (1000, 1000, 1)), view)
    assert t3.visible(((-1, -1, -12), (1, 1, 1)), view)
    flat = {"kind": "map", "width": 160, "height": 120}
    assert t3.visible(((-10, -10, -5), (10, 10, 0)), flat)
    assert not t3.visible(((81, -10, -5), (90, 10, 0)), flat)
    assert not t3.visible(((-10, -100, -5), (10, -61, 0)), flat)


# ------------------------------------------------------------------------------------------------------- selection


def _lod_files(low=10.0, mid=1.0):
    ts = _tileset({"boundingVolume": _box(), "geometricError": low, "refine": "REPLACE", "content": {"uri": "low.glb"},
                   "children": [{"boundingVolume": _box(), "geometricError": mid, "content": {"uri": "medium.glb"},
                                 "children": [{"boundingVolume": _box(), "geometricError": 0.0,
                                               "content": {"uri": "high.glb"}}]}]})
    glb = t3.glb_write([TRI])
    return {"tileset.json": json.dumps(ts).encode(), "low.glb": glb, "medium.glb": glb, "high.glb": glb}


def _camera(z, width=400, height=300, fov=90.0):
    return {"kind": "perspective", "position": (0.0, 0.0, z), "target": (0.0, 0.0, 0.0), "fov": fov,
            "width": width, "height": height}


def test_discrete_levels_of_detail_follow_the_camera_distance():
    files = _lod_files()
    far = t3.select(files, _camera(-1000.0))
    assert [e["uri"] for e in far["tiles"]] == ["low.glb"]
    assert far["tiles"][0]["sse"] == pytest.approx(10.0 * 200.0 / 995.0)
    near = t3.select(files, _camera(-100.0))
    assert [e["uri"] for e in near["tiles"]] == ["medium.glb"]
    assert near["tiles"][0]["depth"] == 1 and near["tiles"][0]["kind"] == "glb"
    nearest = t3.select(files, _camera(-12.0))
    assert [e["uri"] for e in nearest["tiles"]] == ["high.glb"] and nearest["tiles"][0]["sse"] == 0.0
    assert nearest["visited"] == 3 and nearest["warnings"] == []
    assert [e["uri"] for e in t3.select(files, _camera(-100.0), max_error=1.0)["tiles"]] == ["high.glb"]
    assert [e["uri"] for e in t3.select(files, _camera(-12.0), max_depth=1)["tiles"]] == ["medium.glb"]


def test_additive_refinement_keeps_the_parent():
    ts = _tileset({"boundingVolume": _box(), "geometricError": 10.0, "refine": "ADD", "content": {"uri": "root.glb"},
                   "children": [{"boundingVolume": _box(-2.5, 0, 0, 2.5, 5, 5), "geometricError": 0.0,
                                 "content": {"uri": "c0.glb"}},
                                {"boundingVolume": _box(2.5, 0, 0, 2.5, 5, 5), "geometricError": 0.0,
                                 "content": {"uri": "c1.glb"}}]})
    glb = t3.glb_write([TRI])
    files = {"tileset.json": json.dumps(ts).encode(), "root.glb": glb, "c0.glb": glb, "c1.glb": glb}
    assert [e["uri"] for e in t3.select(files, _camera(-20.0))["tiles"]] == ["root.glb", "c0.glb", "c1.glb"]
    assert [e["uri"] for e in t3.select(files, _camera(-2000.0))["tiles"]] == ["root.glb"]
    bounded = t3.select(files, _camera(-20.0), max_tiles=2)
    assert [e["uri"] for e in bounded["tiles"]] == ["root.glb", "c0.glb"] and bounded["warnings"] == ["W-TL1"]


def test_a_request_volume_gates_the_tile_by_the_viewer_position():
    ts = _tileset({"boundingVolume": _box(), "geometricError": 0.0, "refine": "ADD", "content": {"uri": "near.glb"},
                   "viewerRequestVolume": {"sphere": [0, 0, 0, 15]}})
    files = {"tileset.json": json.dumps(ts).encode(), "near.glb": t3.glb_write([TRI])}
    assert [e["uri"] for e in t3.select(files, _camera(-10.0))["tiles"]] == ["near.glb"]
    assert t3.select(files, _camera(-20.0))["tiles"] == []


def test_tiles_outside_the_frustum_are_not_visited():
    ts = _tileset({"boundingVolume": _box(0, 0, 0, 20, 5, 5), "geometricError": 10.0, "refine": "REPLACE",
                   "children": [{"boundingVolume": _box(), "geometricError": 0.0, "content": {"uri": "here.glb"}},
                                {"boundingVolume": _box(10000.0), "geometricError": 0.0,
                                 "content": {"uri": "away.glb"}}]})
    glb = t3.glb_write([TRI])
    files = {"tileset.json": json.dumps(ts).encode(), "here.glb": glb, "away.glb": glb}
    out = t3.select(files, _camera(-10.0))
    assert [e["uri"] for e in out["tiles"]] == ["here.glb"] and out["visited"] == 3


def test_an_external_tileset_takes_the_place_of_the_tile():
    inner = _tileset({"boundingVolume": _box(), "geometricError": 0.0, "refine": "REPLACE",
                      "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 2, 1],
                      "content": {"uri": "a.glb"}})
    outer = _tileset({"boundingVolume": _box(0, 0, 0, 50, 50, 50), "geometricError": 10.0, "refine": "ADD",
                      "children": [{"boundingVolume": _box(), "geometricError": 5.0,
                                    "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 0, 0, 1],
                                    "content": {"uri": "ext/tileset.json"}}]})
    files = {"tileset.json": json.dumps(outer).encode(), "ext/tileset.json": json.dumps(inner).encode(),
             "ext/a.glb": t3.glb_write([TRI])}
    out = t3.select(files, _camera(-20.0))
    assert [e["uri"] for e in out["tiles"]] == ["ext/a.glb"] and out["tiles"][0]["depth"] == 2
    assert _close(out["tiles"][0]["aabb"][0], (-2.0, -5.0, -3.0))
    assert [e["uri"] for e in t3.select(files, _camera(-20.0), max_error=1000.0)["tiles"]] == ["ext/a.glb"]
    assert t3.select(files, _camera(-20.0), max_depth=1)["tiles"] == []
    files["ext/tileset.json"] = json.dumps(_tileset({"boundingVolume": _box(), "geometricError": 0.0})).encode()
    with pytest.raises(t3.TilesError):
        t3.select(files, _camera(-20.0))


def _implicit_files():
    root = {"boundingVolume": {"box": [0, 0, 0, 8, 0, 0, 0, 8, 0, 0, 0, 1]}, "geometricError": 8.0, "refine": "ADD",
            "content": {"uri": "content/{level}_{x}_{y}.glb"},
            "implicitTiling": {"subdivisionScheme": "QUADTREE", "subtreeLevels": 2, "availableLevels": 3,
                               "subtrees": {"uri": "subtrees/{level}.{x}.{y}.subtree"}}}
    glb = t3.glb_write([TRI])
    tiles = {(0, 0, 0), (1, 1, 0), (1, 0, 1)}
    files = {"tileset.json": json.dumps(_tileset(root)).encode(),
             "subtrees/0.0.0.subtree": t3.subtree_write("QUADTREE", 2, tiles, tiles, {(2, 2, 0), (2, 3, 1)}),
             "subtrees/2.2.0.subtree": t3.subtree_write("QUADTREE", 2, {(0, 0, 0)}, {(0, 0, 0)}, set()),
             "subtrees/2.3.1.subtree": t3.subtree_write("QUADTREE", 2, {(0, 0, 0)}, {(0, 0, 0)}, set())}
    for c in ((0, 0, 0), (1, 1, 0), (1, 0, 1), (2, 2, 0), (2, 3, 1)):
        files[t3.template("content/{level}_{x}_{y}.glb", c)] = glb
    return files


def test_implicit_quadtrees_expand_from_their_subtrees():
    files = _implicit_files()
    out = t3.select(files, _camera(-10.0))
    assert [e["uri"] for e in out["tiles"]] == ["content/0_0_0.glb", "content/1_1_0.glb", "content/2_2_0.glb",
                                                 "content/2_3_1.glb", "content/1_0_1.glb"]
    assert out["tiles"][2]["coord"] == (2, 2, 0) and out["tiles"][2]["error"] == 2.0
    assert _close(out["tiles"][2]["aabb"][0], (0.0, -8.0, -1.0)) and _close(out["tiles"][2]["aabb"][1], (4.0, -4.0, 1.0))
    assert [e["uri"] for e in t3.select(files, _camera(-10.0), max_error=1e9)["tiles"]] == ["content/0_0_0.glb"]
    del files["subtrees/2.3.1.subtree"]
    with pytest.raises(t3.TilesError):
        t3.select(files, _camera(-10.0))


def test_unsupported_legacy_content_is_listed_and_warned():
    ts = _tileset({"boundingVolume": _box(), "geometricError": 0.0, "refine": "ADD",
                   "contents": [{"uri": "a.glb"}, {"uri": "points.pnts"}]})
    files = {"tileset.json": json.dumps(ts).encode(), "a.glb": t3.glb_write([TRI])}
    out = t3.select(files, _camera(-20.0))
    assert [(e["uri"], e["kind"]) for e in out["tiles"]] == [("a.glb", "glb"), ("points.pnts", "unsupported")]
    assert out["warnings"] == ["W-TL2"]


def test_a_map_view_selects_by_the_orthographic_error():
    files = _lod_files(low=10.0, mid=0.4)
    centre = (24.94, 60.17)
    placement = t3.MapPlacement(centre[0], centre[1], zoom=12, width=160, height=120)
    view = {"kind": "map", "width": 160, "height": 120}
    m = t3.enu_matrix(centre[0], centre[1], 0.0)
    ts = json.loads(files["tileset.json"])
    ts["root"]["transform"] = [float(v) for v in np.asarray(m).T.flatten()]
    files["tileset.json"] = json.dumps(ts).encode()
    ppm = t3.pixels_per_metre(12, centre[1])
    out = t3.select(files, view, placement=placement)
    assert [e["uri"] for e in out["tiles"]] == ["low.glb"] and out["tiles"][0]["sse"] == pytest.approx(10.0 * ppm)
    fine = t3.MapPlacement(centre[0], centre[1], zoom=17, width=160, height=120)
    out = t3.select(files, view, placement=fine)
    assert [e["uri"] for e in out["tiles"]] == ["medium.glb"]
    assert [e["uri"] for e in t3.select(files, view, placement=t3.MapPlacement(centre[0], centre[1], zoom=22,
                                                                                 width=160, height=120))["tiles"]] == ["high.glb"]
    elsewhere = t3.MapPlacement(centre[0] + 1.0, centre[1], zoom=17, width=160, height=120)
    assert t3.select(files, view, placement=elsewhere)["tiles"] == []


# ------------------------------------------------------------------------------------------------- resolve and cache


def test_the_resolve_step_pins_the_union_of_the_views_in_a_deterministic_archive():
    files = _lod_files()
    asset = {"kind": "tileset3d", "id": "t", "src": "https://example.org/t/tileset.json", "cache": "t.3tz"}
    out = t3.resolve(asset, files, [_camera(-1000.0), _camera(-100.0)])
    assert out["files"] == ["low.glb", "medium.glb", "tileset.json"]
    assert out["cacheSha256"] == hashlib.sha256(out["cache"]).hexdigest()
    assert out["cache"] == t3.resolve(asset, files, [_camera(-100.0), _camera(-1000.0)])["cache"]
    with zipfile.ZipFile(__import__("io").BytesIO(out["cache"])) as z:
        infos = z.infolist()
        assert [i.filename for i in infos] == out["files"]
        assert all(i.compress_type == zipfile.ZIP_STORED and i.date_time == (1980, 1, 1, 0, 0, 0) for i in infos)
    assert t3.read_archive(out["cache"]) == {k: files[k] for k in out["files"]}
    assert out["warnings"] == []
    del files["medium.glb"]
    with pytest.raises(t3.TilesError):
        t3.resolve(asset, files, [_camera(-100.0)])


def test_the_resolve_step_collects_subtrees_and_external_tilesets_but_not_unsupported_content():
    files = _implicit_files()
    out = t3.resolve({"kind": "tileset3d", "id": "g", "src": "g/tileset.json", "cache": "g.3tz"}, files,
                     [_camera(-10.0)])
    assert set(out["files"]) == set(files)
    ts = _tileset({"boundingVolume": _box(), "geometricError": 0.0, "refine": "ADD",
                   "contents": [{"uri": "a.glb"}, {"uri": "points.pnts"}]})
    files = {"tileset.json": json.dumps(ts).encode(), "a.glb": t3.glb_write([TRI])}
    out = t3.resolve({"kind": "tileset3d", "id": "p", "src": "p/tileset.json", "cache": "p.3tz"}, files,
                     [_camera(-20.0)])
    assert out["files"] == ["a.glb", "tileset.json"] and out["warnings"] == ["W-TL2"]


# ----------------------------------------------------------------------------------------------------------- raster


def test_shading_and_back_faces():
    up = (0.0, 0.0, -1.0)
    assert t3.shade(up) == pytest.approx(0.4 + 0.6 * 2.0 / math.sqrt(6.0))
    assert t3.shade((-1.0, 0.0, 0.0)) == pytest.approx(0.4 + 0.6 / math.sqrt(6.0))
    assert t3.shade((1.0, 0.0, 0.0)) == pytest.approx(0.4)
    buf = np.zeros((8, 8, 4))
    height = np.full((8, 8), -math.inf)
    # the ground frame is right-handed with z into the ground: a face seen from above is wound so that
    # (b - a) x (c - a) points up, toward -z
    square = np.array([[-2, -2, -3], [2, -2, -3], [2, 2, -3], [-2, 2, -3]], dtype=float)
    t3.raster_top(buf, height, square, [(0, 2, 1), (0, 3, 2)], (1.0, 1.0, 1.0), 1.0, 8, 8)
    assert int((buf[..., 3] > 0).sum()) == 16 and float(height[4, 4]) == 3.0
    higher = np.array([[-1, -1, -5], [1, -1, -5], [1, 1, -5], [-1, 1, -5]], dtype=float)
    t3.raster_top(buf, height, higher, [(0, 2, 1), (0, 3, 2)], (1.0, 0.0, 0.0), 1.0, 8, 8)
    assert float(height[4, 4]) == 5.0 and _close(buf[4, 4, :3], (t3.shade(up), 0.0, 0.0))
    assert _close(buf[2, 2, :3], (t3.shade(up),) * 3)
    down = np.zeros((8, 8, 4))
    t3.raster_top(down, np.full((8, 8), -math.inf), square, [(0, 1, 2), (0, 2, 3)], (1.0, 1.0, 1.0), 1.0, 8, 8)
    assert int((down[..., 3] > 0).sum()) == 0


def test_the_ground_placement_follows_srep_10():
    p = t3.MapPlacement(24.94, 60.17, zoom=15, width=160, height=120)
    assert _close(p.scene(t3.ecef(24.94, 60.17, 0.0)), (0.0, 0.0, 0.0), 1e-6)
    s = t3.pixels_per_metre(15, 60.17)
    assert _close(p.scene(t3.ecef(24.94, 60.17, 100.0))[2], -100.0 * s, 1e-6)
    x, y, _ = p.scene(t3.ecef(24.95, 60.17, 0.0))
    assert x > 0 and abs(y) < 1e-6
    x, y, _ = p.scene(t3.ecef(24.94, 60.18, 0.0))
    assert y < 0 and abs(x) < 1e-6
    raised = t3.MapPlacement(24.94, 60.17, zoom=15, width=160, height=120, height_offset=10.0)
    assert _close(raised.scene(t3.ecef(24.94, 60.17, 0.0))[2], -10.0 * s, 1e-6)


# ------------------------------------------------------------------------------------------------------ the document


def test_the_example_document_runs_and_seeks():
    doc = t3.example_document()
    out = t3.run(doc, 0)
    assert set(out) >= {"zoom", "selected", "drawn", "covered", "maxHeight", "digest", "warnings"}
    assert out["covered"] > 0 and re.fullmatch(r"[0-9a-f]{12}", out["digest"])
    assert out["warnings"] == [] and out["drawn"] == 4
    last = t3.run(doc, 48)
    assert last["zoom"] == 17.0 and out["zoom"] == 15.0
    assert len(last["selected"]) > len(out["selected"]) and last["warnings"] == ["W-TL2"]
    assert any(u.endswith(".b3dm") for u in last["selected"])
    assert any(u.startswith("grid/kiosk_1_") for u in last["selected"])
    assert not any(u.startswith("grid/kiosk_2_") for u in last["selected"])
    assert last["covered"] > out["covered"]
    assert t3.trace(doc, 12) == [t3.run(doc, k)["digest"] for k in range(13)]
    assert last["maxHeight"] == pytest.approx(40.0)


def test_the_example_document_refuses_a_cache_that_differs_and_warns_about_a_tile_it_lacks():
    doc = t3.example_document()
    data = doc["assets"]["hki"]["data"]
    doc["assets"]["hki"]["data"] = data[:-1] + bytes([data[-1] ^ 1])
    assert ("TL1", ) in {(c,) for c, _ in t3.validate_document(doc)}
    with pytest.raises(t3.TilesError):
        t3.run(doc, 0)
    doc = t3.example_document()
    files = t3.read_archive(doc["assets"]["hki"]["data"])
    missing = [k for k in files if k.endswith("b3dm")][0]
    del files[missing]
    data = t3.archive(files)
    doc["assets"]["hki"].update(data=data, cacheSha256=hashlib.sha256(data).hexdigest())
    out = t3.run(doc, 48)
    assert "W-TL3" in out["warnings"] and missing in out["selected"]


def test_the_example_tileset_loads_under_a_perspective_camera():
    doc = t3.example_document()
    files = t3.read_archive(doc["assets"]["hki"]["data"])
    out = t3.select_document(doc, t3.example_camera())
    assert [e["kind"] for e in out["tiles"]].count("glb") >= 4 and out["visited"] > 1
    # the archive was resolved for the map views alone, so the camera may select tiles it lacks (W-TL3 at render)
    assert any(e["uri"] in files for e in out["tiles"])
    assert all(e["kind"] in ("glb", "b3dm", "unsupported") for e in out["tiles"])


def test_validation_reports_each_code_once_in_order():
    assert [c for c, _ in t3.validate_document(t3.bad_document())] == ["TL1", "TL2", "TL3", "TL4", "V17"]
    assert t3.validate_document(t3.example_document()) == []


@pytest.mark.parametrize("patch, code", [
    (lambda d: d["assets"]["hki"].update(cacheSha256="abc"), "TL1"),
    (lambda d: d["assets"]["hki"].update(maxError=0), "TL2"),
    (lambda d: d["assets"]["hki"].update(maxTiles=0), "TL2"),
    (lambda d: d["map"]["children"][0].update(opacity=1.5), "TL2"),
    (lambda d: d["map"]["children"][0].update(heightOffset="high"), "TL2"),
    (lambda d: d["map"]["children"][0].update(color="#12"), "TL2"),
    (lambda d: d["map"]["children"][0].update(tileset="nowhere"), "TL3"),
    (lambda d: d["assets"]["hki"].update(data=t3.archive({"tileset.json": b"{}"}),
                                         cacheSha256=hashlib.sha256(t3.archive({"tileset.json": b"{}"})).hexdigest()),
     "TL4"),
    (lambda d: d["assets"]["hki"].update(data=t3.archive({"readme.txt": b"x"}),
                                         cacheSha256=hashlib.sha256(t3.archive({"readme.txt": b"x"})).hexdigest()),
     "TL4"),
    (lambda d: d["map"]["children"][0].update(glow=1), "V17"),
    (lambda d: d["assets"]["hki"].update(lod=1), "V17"),
])
def test_each_validation_rule_alone(patch, code):
    doc = t3.example_document()
    patch(doc)
    assert [c for c, _ in t3.validate_document(doc)] == [code]


def test_defaults_and_constants():
    assert t3.TILESET_DEFAULTS == {"maxError": 16.0, "maxTiles": 4096}
    assert t3.TILES_DEFAULTS == {"heightOffset": 0.0, "opacity": 1.0, "color": None}
    assert t3.MAX_DEPTH == 32 and t3.MAX_TILES == 1000000
    assert t3.DEFAULT_COLOUR == (0.86, 0.85, 0.83)
    assert _close(t3.LIGHT, (-1 / math.sqrt(6), -1 / math.sqrt(6), -2 / math.sqrt(6)))
    assert t3.CODE_ORDER == ("TL1", "TL2", "TL3", "TL4", "V17")
    assert set(t3.KNOWN_TILESET) == {"id", "src", "cache", "cacheSha256", "maxError", "maxTiles", "credit"}
    assert set(t3.KNOWN_TILES) == {"id", "tileset", "heightOffset", "opacity", "color"}


# -------------------------------------------------------------------------------------------------------- the draft


@pytest.fixture(scope="module")
def draft():
    with open(DRAFT, encoding="utf-8") as f:
        return f.read()


def test_the_draft_has_the_srep_sections(draft):
    for section in ("## Abstract", "## Motivation", "## Specification", "### Syntax", "### Validation",
                    "### Semantics", "## Rationale", "## Rejected alternatives", "## Backwards compatibility",
                    "## Engine impact", "## Conformance", "## Open issues", "## References", "## History"):
        assert section in draft, section
    assert draft.startswith("```\nSREP:            0\n")
    assert "Status:          Draft" in draft and "Schema-Version:  1.8" in draft
    assert "Requires:        9, 10, 12, 14" in draft


def test_the_draft_names_its_rules_sources_and_terms(draft):
    for word in ("screen-space error", "3D Tiles 1.1", "OGC 22-025r4", "Morton", "subtree", "cacheSha256",
                 "tileset3d", "tiles3d", "V17", "TL1", "TL2", "TL3", "TL4", "W-TL1", "W-TL2", "W-TL3",
                 "Helsinki", "3d-tiles-samples", "CC BY 4.0", "SR-116", "viewerRequestVolume", "REPLACE", "ADD",
                 "y-up", "b3dm", "glb", "ZIP", "Apache-2.0", "seek check", "0d 32 01"):
        assert word in draft, word
    for attribute in t3.KNOWN_TILESET + t3.KNOWN_TILES:
        assert f"| `{attribute}` |" in draft, attribute
    assert "Rendering MUST NOT access the network" in draft or "never fetches" in draft


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _rows(text):
    start = text.index("### Numeric tests")
    end = text.index("### Kit cases")
    return [(m.group(1), m.group(2), m.group(3)) for m in ROW.finditer(text[start:end])
            if m.group(1) not in ("Test",)]


def test_the_table_has_enough_rows(draft):
    rows = _rows(draft)
    assert len(rows) >= 24
    assert [r[:2] for r in rows] == [(n, e) for n, e, _ in t3.TABLE]


def test_the_table_is_what_the_module_prints(draft):
    rows = _rows(draft)
    scope = t3.scope()
    for name, expr, expected in rows:
        assert t3._same(t3._fmt(eval(expr, scope)), expected), name


@pytest.mark.parametrize("name, expr, expected", t3.TABLE)
def test_the_table_rows_hold(name, expr, expected):
    scope = t3.scope()
    assert t3._same(t3._fmt(eval(expr, scope)), expected), name
