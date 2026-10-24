"""Tests of the draft SREP "Add computed tracking" (srep/srep-0000-computed-tracking.md) and of its reference
implementation conformance/tools/computed_tracking_reference.py (LA1 of SREP 12, SRC-56).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import hashlib
import importlib.util
import json
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "computed_tracking_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-computed-tracking.md")

_spec = importlib.util.spec_from_file_location("computed_tracking_reference", MODULE)
ct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ct)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ homographies and plates


def test_homographies_compose_invert_and_map_corners():
    T = ct.homography_translate(3.0, -2.0)
    assert _close(ct.apply_homography(T, (10.0, 10.0)), (13.0, 8.0))
    R = ct.homography_rotate_scale(48.0, 36.0, 90.0, 2.0)
    assert _close(ct.apply_homography(R, (48.0, 36.0)), (48.0, 36.0), 1e-9)
    assert _close(ct.apply_homography(R, (49.0, 36.0)), (48.0, 38.0), 1e-9)  # +x turns to +y, doubled
    I = ct.compose(ct.homography_invert(R), R)
    assert all(_close(I[i][j], 1.0 if i == j else 0.0, 1e-12) for i in range(3) for j in range(3))
    src = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    dst = ((1.0, 1.0), (12.0, 0.5), (11.0, 12.0), (0.5, 9.0))
    H = ct.homography_from_corners(src, dst)
    assert all(_close(ct.apply_homography(H, s), d, 1e-9) for s, d in zip(src, dst))
    with pytest.raises(ct.TrackingError):
        ct.homography_from_corners(src, ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)))  # collinear


def test_textures_warps_and_plates_are_deterministic_and_bounded():
    tex = ct.texture(64, 48, seed=3)
    assert len(tex) == 48 and len(tex[0]) == 64
    assert all(0.0 <= v <= 1.0 for row in tex for v in row)
    assert max(max(row) for row in tex) - min(min(row) for row in tex) > 0.5  # enough contrast to track
    assert tex == ct.texture(64, 48, seed=3)
    assert tex != ct.texture(64, 48, seed=4)
    shifted = ct.warp(tex, ct.homography_translate(5.0, 0.0), 64, 48)
    assert _close(shifted[20][30], tex[20][25], 1e-12)  # integer shifts move pixels exactly
    assert shifted[20][2] == 0.0  # outside the source is black
    half = ct.warp(tex, ct.homography_translate(0.5, 0.0), 64, 48)
    assert _close(half[20][30], 0.5 * (tex[20][29] + tex[20][30]), 1e-12)  # bilinear
    frames, truth = ct.synthetic_plate(64, 48, {"kind": "translate", "vx": 1.5, "vy": -0.5}, frames=4, seed=3)
    assert len(frames) == 4 and len(truth) == 4
    assert _close(ct.apply_homography(truth[3], (10.0, 10.0)), (14.5, 8.5))
    assert _close(ct.sample(frames[0], 20.25, 10.5), ct.bilinear(frames[0], 20.25, 10.5))
    with pytest.raises(ct.TrackingError):
        ct.synthetic_plate(64, 48, {"kind": "spiral"}, frames=4, seed=3)


# ------------------------------------------------------------------------------------ point tracks


def test_ncc_peaks_at_the_true_offset_and_lk_refines_to_subpixel():
    tex = ct.texture(80, 60, seed=5)
    tpl = ct.window(tex, 40.0, 30.0, 11)
    assert len(tpl) == 11 and len(tpl[0]) == 11
    assert _close(ct.ncc(tpl, tex, 40.0, 30.0), 1.0, 1e-9)
    assert ct.ncc(tpl, tex, 40.0, 30.0) > ct.ncc(tpl, tex, 43.0, 30.0)
    moved = ct.warp(tex, ct.homography_translate(2.3, -1.4), 80, 60)
    best = ct.ncc_search(tpl, moved, 40.0, 30.0, search=5)
    assert best[:2] == (42, 29) or best[:2] == (42, 28)
    x, y, residual, iterations = ct.lucas_kanade(tpl, moved, float(best[0]), float(best[1]), iterations=20)
    assert abs(x - 42.3) < 0.05 and abs(y - 28.6) < 0.05
    assert residual < 1e-3
    assert 1 <= iterations <= 20


@pytest.mark.parametrize("motion", [
    {"kind": "translate", "vx": 1.7, "vy": -0.9},
    {"kind": "rotateScale", "cx": 48.0, "cy": 36.0, "degreesPerFrame": 1.5, "scalePerFrame": 1.01},
])
def test_a_point_track_follows_known_motion_below_half_a_pixel(motion):
    frames, truth = ct.synthetic_plate(96, 72, motion, frames=16, seed=11)
    solve = {"kind": "point", "x": 40.0, "y": 30.0, "window": 11, "search": 6,
             "template": "first" if motion["kind"] == "translate" else "previous"}
    track = ct.track_point(frames, solve)
    assert len(track) == 16
    assert track[0]["frame"] == 0 and _close((track[0]["x"], track[0]["y"]), (40.0, 30.0))
    assert all(t["status"] == "tracked" for t in track)
    err = ct.point_error(track, truth, (40.0, 30.0))
    assert err < 0.5, err
    assert all(t["confidence"] > 0.9 for t in track)


def test_a_point_that_leaves_the_frame_is_lost_and_stays_put():
    frames, truth = ct.synthetic_plate(64, 48, {"kind": "translate", "vx": 6.0, "vy": 0.0}, frames=12, seed=2)
    track = ct.track_point(frames, {"kind": "point", "x": 50.0, "y": 24.0, "window": 11, "search": 8})
    statuses = [t["status"] for t in track]
    assert "lost" in statuses
    first_lost = statuses.index("lost")
    assert all(s == "lost" for s in statuses[first_lost:])  # a lost track does not come back
    assert all(_close((t["x"], t["y"]), (track[first_lost]["x"], track[first_lost]["y"])) for t in track[first_lost:])
    assert track[first_lost]["confidence"] < ct.LOST_THRESHOLD or track[first_lost - 1]["x"] + 6.0 + 5.0 > 64.0


# ------------------------------------------------------------------------------------ planar tracks


def test_dlt_recovers_a_homography_and_ransac_rejects_outliers():
    H = ct.homography_from_corners(((0, 0), (40, 0), (40, 30), (0, 30)), ((2, 1), (43, 0.5), (41, 32), (1, 29)))
    src = [(5.0 + 7.0 * i, 4.0 + 5.0 * j) for i in range(5) for j in range(5)]
    dst = [ct.apply_homography(H, s) for s in src]
    F = ct.fit_homography(src, dst)
    assert all(_close(ct.apply_homography(F, s), d, 1e-7) for s, d in zip(src, dst))
    bad = list(dst)
    bad[3] = (bad[3][0] + 9.0, bad[3][1] - 7.0)
    bad[17] = (bad[17][0] - 12.0, bad[17][1])
    R, inliers = ct.ransac_homography(src, bad, threshold=1.0, iterations=100, seed=1)
    assert sorted(set(range(25)) - set(inliers)) == [3, 17]
    assert all(_close(ct.apply_homography(R, s), d, 1e-6) for k, (s, d) in enumerate(zip(src, dst)) if k not in (3, 17))
    with pytest.raises(ct.TrackingError):
        ct.fit_homography(src[:3], dst[:3])


def test_a_planar_track_keeps_its_corners_below_half_a_pixel():
    frames, truth = ct.synthetic_plate(96, 72, {"kind": "perspective", "drift": 0.4}, frames=12, seed=7)
    corners = ((20.0, 14.0), (72.0, 14.0), (72.0, 56.0), (20.0, 56.0))
    solve = {"kind": "planar", "corners": corners, "grid": 4, "window": 11, "search": 6}
    track = ct.track_plane(frames, solve)
    assert len(track) == 12 and len(track[0]["corners"]) == 4
    assert _close(track[0]["corners"], corners)
    err = ct.plane_error(track, truth, corners)
    assert err < 0.5, err
    assert all(t["inliers"] >= 10 for t in track[1:])
    with pytest.raises(ct.TrackingError):
        ct.track_plane(frames, {**solve, "corners": ((0, 0), (10, 0), (0, 10), (10, 10))})  # self-crossing


# ------------------------------------------------------------------------------------ camera solves


def test_intrinsics_projection_and_euler_round_trips():
    K = ct.intrinsics(1920, 1080, 90.0)
    assert _close(K[0][0], 960.0) and _close(K[1][1], 960.0) and _close(K[0][2], 960.0) and _close(K[1][2], 540.0)
    R = ct.euler_to_rotation(10.0, -20.0, 30.0)
    assert _close(ct.rotation_to_euler(R), (10.0, -20.0, 30.0), 1e-9)
    assert all(_close(sum(R[i][k] * R[j][k] for k in range(3)), 1.0 if i == j else 0.0, 1e-12) for i in range(3) for j in range(3))
    assert _close(ct.determinant(R), 1.0, 1e-12)
    t = (0.5, -0.2, 3.0)
    assert _close(ct.project(K, ct.euler_to_rotation(0, 0, 0), (0.0, 0.0, 0.0), (0.0, 0.0, 5.0)), (960.0, 540.0))
    assert _close(ct.project(K, ct.euler_to_rotation(0, 0, 0), (0.0, 0.0, 0.0), (1.0, 0.0, 2.0)), (1440.0, 540.0))
    rv = ct.rotation_vector(R)
    assert all(_close(ct.rotation_from_vector(rv)[i][j], R[i][j], 1e-9) for i in range(3) for j in range(3))
    with pytest.raises(ct.TrackingError):
        ct.intrinsics(1920, 1080, 180.0)
    with pytest.raises(ct.TrackingError):
        ct.project(K, ct.euler_to_rotation(0, 0, 0), (0.0, 0.0, 0.0), (0.0, 0.0, -1.0))  # behind the camera


def test_a_planar_target_gives_the_camera_pose_and_reprojects_below_half_a_pixel():
    K = ct.intrinsics(640, 480, 60.0)
    R = ct.euler_to_rotation(12.0, -25.0, 5.0)
    t = (0.1, -0.05, 2.5)
    target = ct.planar_target_points(0.8, 0.6)  # metres: corners TL, TR, BR, BL on the plane z = 0
    image = [ct.project(K, R, t, (X, Y, 0.0)) for X, Y in target]
    H = ct.homography_from_corners(target, image)
    pose = ct.planar_pose(H, K)
    assert all(_close(pose["R"][i][j], R[i][j], 1e-6) for i in range(3) for j in range(3))
    assert _close(pose["t"], t, 1e-6)
    noisy = [(x + 0.3 * ((-1) ** k), y - 0.2 * ((-1) ** k)) for k, (x, y) in enumerate(image)]
    pose2 = ct.refine_pose(ct.planar_pose(ct.homography_from_corners(target, noisy), K), K,
                           [(X, Y, 0.0) for X, Y in target], noisy)
    assert ct.reprojection_error(K, pose2["R"], pose2["t"], [(X, Y, 0.0) for X, Y in target], noisy) < 0.5
    assert ct.reprojection_error(K, pose2["R"], pose2["t"], [(X, Y, 0.0) for X, Y in target], image) < 0.5
    with pytest.raises(ct.TrackingError):
        ct.planar_target_points(0.0, 0.6)


def test_survey_points_give_the_camera_pose_by_dlt_and_refinement():
    K = ct.intrinsics(640, 480, 50.0)
    R = ct.euler_to_rotation(-8.0, 15.0, 40.0)
    t = (-0.3, 0.2, 4.0)
    world = [(x, y, z) for x in (-1.0, 0.0, 1.0) for y in (-0.5, 0.5) for z in (0.0, 0.7)]
    image = [ct.project(K, R, t, X) for X in world]
    pose = ct.pnp_dlt(world, image, K)
    assert ct.reprojection_error(K, pose["R"], pose["t"], world, image) < 1e-6
    jitter = [(x + 0.4 * math.sin(k), y + 0.4 * math.cos(k)) for k, (x, y) in enumerate(image)]
    pose2 = ct.refine_pose(ct.pnp_dlt(world, jitter, K), K, world, jitter)
    assert ct.reprojection_error(K, pose2["R"], pose2["t"], world, jitter) < 0.5
    assert all(abs(a - b) < 0.02 for a, b in zip(pose2["t"], t))
    with pytest.raises(ct.TrackingError):
        ct.pnp_dlt(world[:5], image[:5], K)
    with pytest.raises(ct.TrackingError):
        ct.pnp_dlt([(x, y, 0.0) for x, y, z in world], image, K)  # coplanar points need the planar solve


def test_a_camera_track_from_a_tracked_planar_target_matches_the_truth():
    # a real camera view of a 0.48 x 0.36 m target: at 60 degrees on 96 px the target fills (24, 18)-(72, 54)
    # when the camera is f / 100 m away; it then moves and turns a little every frame
    motion = ct.camera_motion()
    assert motion["kind"] == "camera" and abs(motion["tz"] - ct.intrinsics(96, 72, 60.0)[0][0] / 100.0) < 1e-12
    frames, truth = ct.synthetic_plate(96, 72, motion, frames=8, seed=9)
    corners = ((24.0, 18.0), (72.0, 18.0), (72.0, 54.0), (24.0, 54.0))
    assert all(_close(ct.apply_homography(truth[0], c), c, 1e-9) for c in corners)
    solve = {"kind": "camera", "target": "planar", "corners": corners, "width": 0.48, "height": 0.36,
             "fov": 60.0, "grid": 4, "window": 11, "search": 6}
    track = ct.solve_camera(frames, solve)
    assert len(track) == 8
    for t in track:
        assert set(t) >= {"frame", "tx", "ty", "tz", "rx", "ry", "rz", "fov", "error"}
        assert t["fov"] == 60.0
        assert t["error"] < 0.5
    assert track[0]["tz"] > 0.0
    # the plane's true corners re-project through the solved camera onto the plate within half a pixel
    K = ct.intrinsics(96, 72, 60.0)
    plane = [(X, Y, 0.0) for X, Y in ct.planar_target_points(0.48, 0.36)]
    for k, (t, H) in enumerate(zip(track, truth)):
        R = ct.euler_to_rotation(t["rx"], t["ry"], t["rz"])
        seen = [ct.apply_homography(H, c) for c in corners]
        assert ct.reprojection_error(K, R, (t["tx"], t["ty"], t["tz"]), plane, seen) < 0.5
        _R, true_t = ct.camera_pose(motion, k)
        assert all(abs(a - b) < 0.05 * true_t[2] for a, b in zip((t["tx"], t["ty"], t["tz"]), true_t))


# ------------------------------------------------------------------------------------ the cache and the resolve step


def test_the_cache_is_the_engine_json_canonical_and_pinned():
    points = {"p": [(0, 10.123456, 20.0), (1, 11.0, 21.5)]}
    planes = {"q": [(0, (0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0))]}
    cameras = {"c": [(0, 0.1, 0.2, 3.0, 1.0, 2.0, 3.0, 60.0)]}
    text = ct.cache_json(24, points, planes, cameras)
    doc = json.loads(text)
    assert doc["fps"] == 24
    assert doc["points"]["p"][0] == [0, 10.1235, 20.0]  # four decimals
    assert doc["planes"]["q"][0] == [0, 0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    assert doc["cameras"]["c"][0] == [0, 0.1, 0.2, 3.0, 1.0, 2.0, 3.0, 60.0]
    assert text.endswith("\n") and text == ct.cache_json(24, points, planes, cameras)
    assert list(doc) == ["cameras", "fps", "planes", "points"]  # sorted keys
    assert ct.cache_digest(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert ct.verify_cache(text, ct.cache_digest(text)) is True
    with pytest.raises(ct.TrackingError):
        ct.verify_cache(text, "0" * 64)
    assert _close(ct.frame_sample(doc, "p", 0.5), (10.56175, 20.75), 1e-9)  # linear between frames, like the engine
    assert _close(ct.frame_sample(doc, "p", 7.0), (11.0, 21.5))  # clamped
    assert _close(ct.frame_sample(doc, "q", 0.0), (0.5, 0.5))  # a plane answers with its centre
    with pytest.raises(ct.TrackingError):
        ct.frame_sample(doc, "missing", 0.0)


def test_the_resolve_step_is_deterministic_and_the_seek_check_holds():
    frames, _truth = ct.synthetic_plate(64, 48, {"kind": "translate", "vx": 1.0, "vy": 0.5}, frames=6, seed=4)
    doc = {"id": "boat", "kind": "point", "footage": "plate", "provider": "tracks", "src": "tracks/boat.json",
           "fps": 25, "solve": {"kind": "point", "x": 30.0, "y": 20.0, "window": 9, "search": 4}}
    text, digest = ct.resolve(doc, frames)
    again, digest2 = ct.resolve(doc, frames)
    assert text == again and digest == digest2 == ct.cache_digest(text)
    cache = json.loads(text)
    assert cache["fps"] == 25 and list(cache["points"]) == ["boat"] and len(cache["points"]["boat"]) == 6
    assert _close(ct.frame_sample(cache, "boat", 5.0), (35.0, 22.5), 0.5)
    assert ct.seek_test() is True
    planar = {**doc, "kind": "planar", "solve": {"kind": "planar", "corners": ((10, 8), (50, 8), (50, 38), (10, 38)),
                                                 "grid": 3, "window": 9, "search": 4}}
    ptext, _ = ct.resolve(planar, frames)
    assert list(json.loads(ptext)["planes"]) == ["boat"]
    with pytest.raises(ct.TrackingError):
        ct.resolve({**doc, "kind": "planar"}, frames)  # the solve kind must match the track kind


# ------------------------------------------------------------------------------------ validation


def test_validation_rules():
    good = {"id": "t", "kind": "point", "footage": "plate", "provider": "tracks", "src": "tracks/t.json",
            "solve": {"kind": "point", "x": 1.0, "y": 2.0, "window": 15, "search": 8}}
    assert ct.validate_track_data(good) is True
    assert ct.validate_track_data({"id": "t", "kind": "point", "src": "a.json"}) is True  # an imported track
    for bad in ({**good, "provider": "magic"},
                {k: v for k, v in good.items() if k != "footage"},
                {k: v for k, v in good.items() if k != "solve"},
                {**good, "kind": "mask"},
                {**good, "sha256": "abc"},
                {**good, "solve": {**good["solve"], "window": 4}},
                {**good, "solve": {**good["solve"], "window": 65}},
                {**good, "solve": {**good["solve"], "search": 0}},
                {**good, "solve": {**good["solve"], "template": "last"}},
                {**good, "kind": "planar", "solve": {"kind": "planar", "corners": ((0, 0), (1, 0), (1, 1))}},
                {**good, "kind": "planar", "solve": {"kind": "planar", "corners": ((0, 0), (1, 0), (0, 1), (1, 1))}},
                {**good, "kind": "camera", "solve": {"kind": "camera", "target": "planar",
                                                      "corners": ((0, 0), (1, 0), (1, 1), (0, 1)), "width": 0.0, "height": 1.0, "fov": 60.0}},
                {**good, "kind": "camera", "solve": {"kind": "camera", "target": "survey", "fov": 60.0,
                                                      "points": [{"x": 0, "y": 0, "X": 0, "Y": 0, "Z": 0}] * 5}},
                {**good, "kind": "camera", "solve": {"kind": "camera", "target": "orbit", "fov": 60.0}},
                {**good, "kind": "camera", "solve": {"kind": "camera", "target": "planar",
                                                      "corners": ((0, 0), (1, 0), (1, 1), (0, 1)), "width": 1.0, "height": 1.0, "fov": 0.0}}):
        with pytest.raises(ct.TrackingError):
            ct.validate_track_data(bad)
    assert ct.validate_track_data({**good, "kind": "camera", "solve": {"kind": "camera", "target": "survey", "fov": 60.0,
                                                                        "points": [{"x": k, "y": k * k, "X": k, "Y": 1.0, "Z": k % 2} for k in range(6)]}}) is True


def test_constants():
    assert ct.PROVIDER == "tracks"
    assert ct.TRACK_KINDS == ("point", "planar", "camera")
    assert ct.TEMPLATE_MODES == ("first", "previous")
    assert ct.CAMERA_TARGETS == ("planar", "survey")
    assert ct.MIN_WINDOW == 5 and ct.MAX_WINDOW == 63 and ct.MAX_SEARCH == 64
    assert ct.CACHE_DECIMALS == 4
    assert ct.MIN_SURVEY_POINTS == 6
    assert 0.0 < ct.LOST_THRESHOLD < 1.0


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
    for word in ("SR-97", "SREP 9", "SREP 14", "SREP 92", "trackData", "provider", "tracks", "solve", "footage",
                 "src", "sha256", "point", "planar", "camera", "window", "search", "template", "corners", "grid",
                 "target", "survey", "width", "height", "fov", "Lucas", "Kanade", "cross-correlation", "homography",
                 "DLT", "RANSAC", "Zhang", "Hartley", "Zisserman", "Gauss", "re-projection", "0.5 px", "lost",
                 "confidence", "CT1", "CT2", "CT3", "CT4", "V17", "seek check", "computed_tracking_reference.py",
                 "resolve step", "pinned"):
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


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = ct.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or ct._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    ct.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
