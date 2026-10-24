"""Tests for the draft SREP "Add computed masks and depth" (LA2 of SREP 12) and its reference module."""
import hashlib
import importlib.util
import json
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "computed_masks_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-computed-masks.md")


def _load():
    spec = importlib.util.spec_from_file_location("computed_masks_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cm = _load()


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ synthetic plates and IoU


def test_synthetic_matte_plates_have_a_moving_shape_and_a_truth_matte():
    frames, truth = cm.synthetic_matte_plate(64, 48, {"kind": "disc", "cx": 20.0, "cy": 24.0, "radius": 10.0,
                                                      "vx": 2.0, "vy": 0.5}, frames=6, seed=3, background="key")
    assert len(frames) == 6 and len(truth) == 6
    assert len(frames[0]) == 48 and len(frames[0][0]) == 64 and len(frames[0][0][0]) == 3
    assert all(0.0 <= c <= 1.0 for row in frames[0] for px in row for c in px)
    # the truth matte is 1 inside the disc and 0 outside, anti-aliased on the edge
    assert truth[0][24][20] == 1.0 and truth[0][24][50] == 0.0
    assert 0.0 < truth[0][24][30] < 1.0 or truth[0][24][30] in (0.0, 1.0)
    area = sum(sum(r) for r in truth[0])
    assert abs(area - math.pi * 100.0) < 8.0
    # the disc moves by (vx, vy) per frame
    assert truth[5][24 + 2][20 + 10] == 1.0 and truth[5][24][20 - 5] == 0.0
    # a key background is the key colour everywhere outside the shape
    assert frames[0][24][50] == cm.KEY_COLOUR
    tex, _ = cm.synthetic_matte_plate(64, 48, {"kind": "disc", "cx": 20.0, "cy": 24.0, "radius": 10.0, "vx": 0.0, "vy": 0.0},
                                      frames=1, seed=3, background="texture")
    assert tex[0][24][50] != cm.KEY_COLOUR
    with pytest.raises(cm.MaskError):
        cm.synthetic_matte_plate(64, 48, {"kind": "blob"}, frames=1, seed=3)


def test_iou_is_the_intersection_over_the_union_of_the_thresholded_mattes():
    a = [[1.0, 1.0, 0.0, 0.0]]
    b = [[0.0, 1.0, 1.0, 0.0]]
    assert _close(cm.iou(a, b), 1.0 / 3.0)
    assert _close(cm.iou(a, a), 1.0)
    assert cm.iou([[0.0, 0.0]], [[0.0, 0.0]]) == 1.0
    assert _close(cm.iou([[0.6, 0.4]], [[1.0, 0.0]]), 1.0)  # thresholded at 0.5
    assert _close(cm.soft_iou([[0.5, 0.5]], [[1.0, 0.0]]), 0.5 / 1.5)


# ------------------------------------------------------------------------------------ keys


def test_the_chroma_key_follows_the_engine_formula():
    key = (0.0, 1.0, 0.0)
    assert cm.chroma_key_coverage((0.0, 1.0, 0.0), key, 0.2, 0.1) == 0.0
    assert cm.chroma_key_coverage((1.0, 0.0, 0.0), key, 0.2, 0.1) == 1.0
    # the engine measures the distance in the Cb-Cr plane over 0.7 and keeps smoothstep(tol, tol + soft, d):
    # a pixel at chroma distance 0.25 from the key is half-way up the 0.2 .. 0.3 ramp
    unit = cm.chroma_distance((1.0 / math.sqrt(2.0), 0.0, 1.0 / math.sqrt(2.0)), (0.0, 0.0, 0.0))
    s = 0.25 / unit
    px = (s / math.sqrt(2.0), 1.0, s / math.sqrt(2.0))
    assert _close(cm.chroma_distance(px, key), 0.25, 1e-9)
    assert _close(cm.chroma_key_coverage(px, key, 0.2, 0.1), 0.5, 1e-9)
    assert _close(cm.chroma_distance((0.0, 1.0, 1.0), key), math.hypot(0.5, -0.0458) / 0.7, 1e-9)
    frames, truth = cm.synthetic_matte_plate(64, 48, {"kind": "disc", "cx": 30.0, "cy": 24.0, "radius": 12.0, "vx": 1.0, "vy": 0.0},
                                             frames=4, seed=5, background="key")
    masks = cm.segment(frames, {"method": "chroma", "keyColor": cm.KEY_COLOUR, "tolerance": 0.5, "softness": 0.2})
    assert len(masks) == 4
    for m, t in zip(masks, truth):
        assert cm.iou(m, t) >= cm.MIN_IOU


def test_the_difference_key_uses_a_clean_plate():
    # a keyer reads a mixed edge pixel as foreground once it is past the tolerance, so the matte is a fraction of a
    # pixel fat; the IoU floor holds from about a 30 px shape upwards, as the draft states
    frames, truth = cm.synthetic_matte_plate(128, 96, {"kind": "ellipse", "cx": 60.0, "cy": 48.0, "rx": 28.0, "ry": 18.0, "vx": 0.5, "vy": 1.0},
                                             frames=4, seed=8, background="texture")
    clean = cm.clean_plate(128, 96, seed=8)
    assert clean[10][10] == frames[0][10][10]  # the background is the clean plate
    masks = cm.segment(frames, {"method": "difference", "tolerance": 0.1, "softness": 0.1}, clean=clean)
    for m, t in zip(masks, truth):
        assert cm.iou(m, t) >= cm.MIN_IOU
    with pytest.raises(cm.MaskError):
        cm.segment(frames, {"method": "difference", "tolerance": 0.1, "softness": 0.1})  # needs the clean plate


# ------------------------------------------------------------------------------------ region growing and roto


def test_region_growing_follows_the_shape_from_seeds_and_reseeds_at_the_centroid():
    frames, truth = cm.synthetic_matte_plate(64, 48, {"kind": "disc", "cx": 20.0, "cy": 24.0, "radius": 10.0, "vx": 3.0, "vy": 1.0},
                                             frames=5, seed=4, background="texture", foreground="flat")
    masks = cm.segment(frames, {"method": "region", "seeds": [(20.0, 24.0)], "tolerance": 0.15})
    for m, t in zip(masks, truth):
        assert cm.iou(m, t) >= cm.MIN_IOU
    cx, cy = cm.centroid(masks[4])
    assert abs(cx - 32.0) < 1.0 and abs(cy - 28.0) < 1.0
    assert cm.centroid([[0.0, 0.0]]) is None
    with pytest.raises(cm.MaskError):
        cm.segment(frames, {"method": "region", "seeds": [], "tolerance": 0.15})
    with pytest.raises(cm.MaskError):
        cm.segment(frames, {"method": "region", "seeds": [(200.0, 24.0)], "tolerance": 0.15})  # outside the frame


def test_roto_polygons_interpolate_between_key_frames_and_rasterise_with_coverage():
    keys = [{"frame": 0, "points": [(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)]},
            {"frame": 4, "points": [(14.0, 10.0), (34.0, 10.0), (34.0, 30.0), (14.0, 30.0)]}]
    assert _close(cm.roto_polygon(keys, 2), [(12.0, 10.0), (32.0, 10.0), (32.0, 30.0), (12.0, 30.0)])
    assert _close(cm.roto_polygon(keys, 9), keys[1]["points"])  # clamped after the last key
    assert _close(cm.roto_polygon(keys, -1), keys[0]["points"])
    mask = cm.rasterise(keys[0]["points"], 40, 40)
    assert mask[20][20] == 1.0 and mask[5][5] == 0.0
    # pixel 10 straddles the edge at x = 10 (its centre is at 10, its span 9.5..10.5): half covered
    assert _close(mask[20][10], 0.5, 0.01)
    assert _close(sum(sum(r) for r in mask), 400.0, 0.5)
    with pytest.raises(cm.MaskError):
        cm.roto_polygon([keys[0], {"frame": 4, "points": keys[0]["points"][:3]}], 2)  # point counts differ
    frames, truth = cm.synthetic_matte_plate(64, 48, {"kind": "polygon", "points": [(10.0, 10.0), (30.0, 12.0), (26.0, 34.0), (8.0, 30.0)],
                                                      "vx": 1.0, "vy": 0.0}, frames=5, seed=1, background="texture")
    moved = [(x + 4.0, y) for x, y in [(10.0, 10.0), (30.0, 12.0), (26.0, 34.0), (8.0, 30.0)]]
    masks = cm.segment(frames, {"method": "roto", "keys": [{"frame": 0, "points": [(10.0, 10.0), (30.0, 12.0), (26.0, 34.0), (8.0, 30.0)]},
                                                         {"frame": 4, "points": moved}]})
    for m, t in zip(masks, truth):
        assert cm.iou(m, t) >= 0.98


def test_expansion_and_feather_change_the_matte_as_mask_type_does():
    mask = cm.rasterise([(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)], 40, 40)
    grown = cm.expand(mask, 2)
    shrunk = cm.expand(mask, -2)
    assert grown[20][9] == 1.0 and mask[20][9] == 0.0 and grown[20][8] == 0.5
    assert shrunk[20][11] == 0.0 and mask[20][11] == 1.0 and shrunk[20][12] == 0.5
    assert _close(sum(sum(r) for r in grown), 24.0 * 24.0, 2.0)
    assert _close(sum(sum(r) for r in shrunk), 16.0 * 16.0, 2.0)
    soft = cm.feather(mask, 3)
    assert 0.0 < soft[20][10] < 1.0 and soft[20][20] == 1.0 and soft[1][1] == 0.0
    assert _close(sum(sum(r) for r in soft), sum(sum(r) for r in mask), 1.0)  # a blur keeps the total
    assert cm.feather(mask, 0) == mask and cm.expand(mask, 0) == mask
    with pytest.raises(cm.MaskError):
        cm.feather(mask, cm.MAX_FEATHER + 1)


# ------------------------------------------------------------------------------------ depth


def test_plane_depth_is_the_ray_plane_intersection_through_the_solved_camera():
    K = cm.intrinsics(64, 48, 60.0)
    R = cm.euler_to_rotation(0.0, 0.0, 0.0)
    depth = cm.plane_depth(K, R, (0.0, 0.0, 2.0), 64, 48)
    assert len(depth) == 48 and len(depth[0]) == 64
    assert all(_close(v, 2.0, 1e-9) for row in depth for v in row)  # a frontal plane at 2 m is 2 m everywhere
    tilted = cm.plane_depth(K, cm.euler_to_rotation(0.0, 30.0, 0.0), (0.0, 0.0, 2.0), 64, 48)
    assert tilted[24][0] != tilted[24][63]
    assert all(v > 0.0 for row in tilted for v in row)
    # a plane seen edge-on or from behind gives no depth: the far value
    edge = cm.plane_depth(K, cm.euler_to_rotation(0.0, 90.0, 0.0), (0.0, 0.0, 2.0), 64, 48)
    assert edge[24][32] == cm.DEPTH_FAR


def test_stereo_block_matching_recovers_the_depth_within_two_percent():
    K = cm.intrinsics(96, 64, 60.0)
    left, right, truth = cm.synthetic_stereo(96, 64, K, baseline=0.3, near=2.0, far=4.0, seed=6)
    assert len(left) == 64 and len(left[0]) == 96 and len(right) == 64 and len(truth) == 64
    assert truth[32][48] == 2.0 and truth[4][4] == 4.0
    # the right image is the left shifted by f B / Z: the background by half the disc's disparity
    d_far = K[0][0] * 0.3 / 4.0
    assert abs(right[4][40] - cm.bilinear(left, 40.0 + d_far, 4.0)) < 0.02
    disparity = cm.stereo_disparity(left, right, window=7, max_disparity=32)
    depth = cm.disparity_to_depth(disparity, K[0][0], 0.3)
    assert len(depth) == 64 and len(depth[0]) == 96
    # the leftmost columns have no match within the disparity range and read far: the margin passes them
    rel = cm.depth_error(depth, truth, margin=16)
    assert rel < 0.02
    assert cm.unmatched_fraction(depth, truth, margin=16) < 0.01
    assert depth[32][4] == cm.DEPTH_FAR
    # the background just left of the disc is hidden in the right view: the consistency check leaves it unmatched
    assert depth[22][31] == cm.DEPTH_FAR and truth[22][31] == 4.0
    assert cm.disparity_to_depth([[0.0]], K[0][0], 0.3) == [[cm.DEPTH_FAR]]
    with pytest.raises(cm.MaskError):
        cm.stereo_disparity(left, right, window=4, max_disparity=16)  # even window
    with pytest.raises(cm.MaskError):
        cm.stereo_disparity(left, right[:-1], window=7, max_disparity=16)  # sizes differ


def test_estimate_depth_runs_the_plane_and_stereo_methods():
    K = cm.intrinsics(96, 64, 60.0)
    left, right, truth = cm.synthetic_stereo(96, 64, K, baseline=0.3, near=2.0, far=4.0, seed=6)
    depths = cm.estimate_depth([left], {"method": "stereo", "fov": 60.0, "baseline": 0.3, "window": 7, "maxDisparity": 32},
                               right=[right])
    assert len(depths) == 1 and cm.depth_error(depths[0], truth, margin=16) < 0.02
    cams = [{"frame": 0, "tx": 0.0, "ty": 0.0, "tz": 2.0, "rx": 0.0, "ry": 0.0, "rz": 0.0, "fov": 60.0}]
    planes = cm.estimate_depth([left], {"method": "plane", "fov": 60.0}, cameras=cams)
    assert all(_close(v, 2.0, 1e-9) for row in planes[0] for v in row)
    with pytest.raises(cm.MaskError):
        cm.estimate_depth([left], {"method": "plane", "fov": 60.0})  # needs the camera track
    with pytest.raises(cm.MaskError):
        cm.estimate_depth([left], {"method": "stereo", "fov": 60.0, "baseline": 0.3})  # needs the right footage


# ------------------------------------------------------------------------------------ the cache


def test_pgm16_round_trips_and_is_canonical():
    mask = [[0.0, 0.5, 1.0], [0.25, 0.75, 1.0]]
    data = cm.pgm16(mask, 1.0)
    assert data.startswith(b"P5\n3 2\n65535\n")
    assert len(data) == len(b"P5\n3 2\n65535\n") + 2 * 3 * 2
    back = cm.read_pgm16(data, 1.0)
    assert all(abs(a - b) <= 0.5 / 65535.0 for ra, rb in zip(mask, back) for a, b in zip(ra, rb))
    depth = [[1.234, 65.535, 100.0]]
    d = cm.read_pgm16(cm.pgm16(depth, cm.DEPTH_FAR), cm.DEPTH_FAR)
    assert _close(d[0][0], 1.234, 1e-9) and _close(d[0][1], 65.535, 1e-9)  # one unit is DEPTH_SCALE, 1 mm
    assert cm.pgm16([[cm.DEPTH_SCALE]], cm.DEPTH_FAR)[-2:] == b"\x00\x01"
    assert d[0][2] == cm.DEPTH_FAR  # clipped to the far value
    assert cm.pgm16(mask, 1.0) == cm.pgm16(mask, 1.0)
    with pytest.raises(cm.MaskError):
        cm.read_pgm16(b"P6\n1 1\n255\n\x00\x00\x00", 1.0)


def test_the_manifest_lists_every_frame_and_pins_it():
    masks = [[[0.0, 1.0]], [[1.0, 0.0]]]
    frames, manifest = cm.frame_cache("mattes/shot_%04d.pgm", 10, masks, 1.0, 24, "matte")
    assert [f[0] for f in frames] == ["mattes/shot_0010.pgm", "mattes/shot_0011.pgm"]
    doc = json.loads(manifest)
    assert list(doc) == ["fps", "frames", "kind", "scale"]
    assert doc["kind"] == "matte" and doc["fps"] == 24 and doc["scale"] == 1.0
    assert doc["frames"][0] == {"file": "mattes/shot_0010.pgm", "sha256": hashlib.sha256(frames[0][1]).hexdigest()}
    assert manifest.endswith("\n") and "  " not in manifest
    assert cm.frame_path("mattes/shot_####.pgm", 7) == "mattes/shot_0007.pgm"
    assert cm.frame_path("m_%02d.pgm", 7) == "m_07.pgm"
    with pytest.raises(cm.MaskError):
        cm.frame_path("mattes/shot.pgm", 7)  # no frame number in the pattern
    digest = cm.cache_digest(manifest)
    assert cm.verify_cache(manifest, digest) is True
    with pytest.raises(cm.MaskError):
        cm.verify_cache(manifest + " ", digest)


def test_resolve_writes_the_matte_cache_and_is_deterministic():
    frames, truth = cm.synthetic_matte_plate(48, 32, {"kind": "disc", "cx": 20.0, "cy": 16.0, "radius": 8.0, "vx": 1.0, "vy": 0.0},
                                             frames=3, seed=2, background="key")
    doc = {"id": "roto", "provider": "masks", "footage": "plate", "src": "mattes/roto_%04d.pgm", "first": 0, "fps": 24,
           "segment": {"method": "chroma", "keyColor": cm.KEY_COLOUR, "tolerance": 0.5, "softness": 0.2, "feather": 1}}
    a = cm.resolve(doc, frames)
    b = cm.resolve(doc, frames)
    assert a == b
    manifest, digest, files = a
    assert digest == cm.cache_digest(manifest) and len(files) == 3
    for (name, data), t in zip(files, truth):
        assert cm.iou(cm.read_pgm16(data, 1.0), t) >= cm.MIN_IOU
    assert json.loads(manifest)["frames"][2]["file"] == "mattes/roto_0002.pgm"


def test_resolve_writes_the_depth_cache():
    K = cm.intrinsics(96, 64, 60.0)
    left, right, truth = cm.synthetic_stereo(96, 64, K, baseline=0.3, near=2.0, far=4.0, seed=6)
    doc = {"id": "z", "provider": "depth", "footage": "left", "src": "depth/z_####.pgm", "first": 1, "fps": 24,
           "estimate": {"method": "stereo", "fov": 60.0, "baseline": 0.3, "window": 7, "maxDisparity": 32, "right": "right"}}
    manifest, digest, files = cm.resolve(doc, [left], right=[right])
    m = json.loads(manifest)
    assert m["kind"] == "depth" and m["scale"] == cm.DEPTH_FAR and m["frames"][0]["file"] == "depth/z_0001.pgm"
    depth = cm.read_pgm16(files[0][1], cm.DEPTH_FAR)
    assert cm.depth_error(depth, truth, margin=16) < 0.02


def test_seek_check():
    assert cm.seek_test() is True


# ------------------------------------------------------------------------------------ validation


def test_validation_rules_md1_to_md4():
    good_matte = {"id": "m", "provider": "masks", "footage": "plate", "src": "m_%04d.pgm", "first": 0, "fps": 24,
                  "segment": {"method": "chroma", "keyColor": (0.0, 1.0, 0.0), "tolerance": 0.2, "softness": 0.1}}
    good_depth = {"id": "d", "provider": "depth", "footage": "plate", "src": "d_%04d.pgm", "first": 0, "fps": 24,
                  "estimate": {"method": "plane", "fov": 60.0, "camera": "cam"}}
    assert cm.validate_asset(good_matte) is True
    assert cm.validate_asset(good_depth) is True
    assert cm.validate_asset({"id": "plain", "src": "a_%04d.png", "first": 0, "last": 9, "fps": 24}) is True  # imported, as today
    for bad in ({**good_matte, "footage": None},  # MD1 footage
                {**good_matte, "src": "m.pgm"},  # MD1 a frame pattern
                {**good_matte, "provider": "roto"},  # MD1 provider
                {k: v for k, v in good_matte.items() if k != "segment"},  # MD1 the child
                {**good_matte, "estimate": good_depth["estimate"]},  # MD1 one child
                {**good_matte, "segment": {"method": "magic"}},  # MD2 method
                {**good_matte, "segment": {"method": "chroma", "keyColor": (0.0, 1.0, 0.0), "tolerance": 1.5, "softness": 0.1}},  # MD2
                {**good_matte, "segment": {"method": "region", "seeds": [], "tolerance": 0.1}},  # MD2 seeds
                {**good_matte, "segment": {"method": "roto", "keys": [{"frame": 0, "points": [(0, 0), (1, 0)]}]}},  # MD2 three points
                {**good_matte, "segment": {"method": "roto", "keys": [{"frame": 3, "points": [(0, 0), (1, 0), (1, 1)]},
                                                                      {"frame": 1, "points": [(0, 0), (1, 0), (1, 1)]}]}},  # MD2 key order
                {**good_matte, "segment": {**good_matte["segment"], "feather": cm.MAX_FEATHER + 1}},  # MD2 feather
                {**good_matte, "segment": {**good_matte["segment"], "expansion": -cm.MAX_EXPANSION - 1}},  # MD2 expansion
                {**good_depth, "estimate": {"method": "plane", "fov": 60.0}},  # MD3 camera
                {**good_depth, "estimate": {"method": "stereo", "fov": 60.0, "right": "r"}},  # MD3 baseline
                {**good_depth, "estimate": {"method": "stereo", "fov": 60.0, "baseline": 0.1}},  # MD3 right footage
                {**good_depth, "estimate": {"method": "stereo", "fov": 60.0, "baseline": 0.1, "right": "r", "window": 8}},  # MD3 odd window
                {**good_depth, "estimate": {"method": "stereo", "fov": 60.0, "baseline": 0.1, "right": "r", "maxDisparity": cm.MAX_DISPARITY + 1}},  # MD3
                {**good_depth, "estimate": {"method": "plane", "fov": 180.0, "camera": "cam"}},  # MD3 fov
                {**good_depth, "estimate": {"method": "plane", "fov": 60.0, "camera": "cam"}, "depthScale": 0.0},  # MD4 scale
                {**good_depth, "estimate": {"method": "plane", "fov": 60.0, "camera": "cam"}, "sha256": "abc"},  # MD4 digest
                ):
        with pytest.raises(cm.MaskError):
            cm.validate_asset(bad)


def test_constants():
    assert cm.MASK_PROVIDER == "masks" and cm.DEPTH_PROVIDER == "depth"
    assert cm.SEGMENT_METHODS == ("chroma", "difference", "region", "roto")
    assert cm.DEPTH_METHODS == ("plane", "stereo")
    assert cm.MIN_IOU == 0.95
    assert cm.MAX_FEATHER == 64 and cm.MAX_EXPANSION == 64 and cm.MAX_DISPARITY == 256
    assert cm.DEPTH_SCALE == 0.001 and cm.DEPTH_FAR == 65.535
    assert cm.KEY_COLOUR == (0.0, 1.0, 0.0)
    assert cm.SUPERSAMPLE == 4


# ------------------------------------------------------------------------------------ the draft and its table


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
    for word in ("SR-98", "SREP 9", "SREP 14", "imageSequence", "provider", "masks", "depth", "segment", "estimate",
                 "footage", "src", "sha256", "manifest", "PGM", "chroma", "difference", "region", "roto", "keyColor",
                 "tolerance", "softness", "seeds", "keys", "feather", "expansion", "plane", "stereo", "baseline",
                 "maxDisparity", "depthScale", "intersection over union", "0.95", "2 %", "MD1", "MD2", "MD3", "MD4",
                 "V17", "seek check", "computed_masks_reference.py", "resolve step", "pinned", "monocular",
                 "computed-tracking"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 24


def test_the_table_is_what_the_module_prints(draft):
    assert len(cm.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(cm.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = cm.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or cm._same(got, want), f"{name}: {got!r} != {want!r}"
