"""Tests for the draft SREP "Add plate integration" (LA3 of SREP 12) and its reference module."""
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "plate_integration_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-plate-integration.md")


def _load():
    spec = importlib.util.spec_from_file_location("plate_integration_reference", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pi = _load()
ct = pi.tracking()


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ------------------------------------------------------------------------------------ the engine's camera


def test_engine_orientation_is_yaw_pitch_roll_about_y_x_z():
    # the engine's pose3: T(x, y, z) · Ry(yaw) · Rx(pitch) · Rz(roll); the camera looks along +z with y down
    M = pi.engine_orientation(90.0, 0.0, 0.0)
    # yaw 90 turns +z towards +x
    assert _close(pi.apply(M, (0.0, 0.0, 1.0)), (1.0, 0.0, 0.0))
    M = pi.engine_orientation(0.0, 90.0, 0.0)
    # positive pitch turns +z towards -y, which is up in a y-down scene
    assert _close(pi.apply(M, (0.0, 0.0, 1.0)), (0.0, -1.0, 0.0))
    M = pi.engine_orientation(0.0, 0.0, 90.0)
    assert _close(pi.apply(M, (1.0, 0.0, 0.0)), (0.0, 1.0, 0.0))
    Ry, Rx, Rz = pi.rotation_y(20.0), pi.rotation_x(-10.0), pi.rotation_z(5.0)
    assert _close(pi.engine_orientation(20.0, -10.0, 5.0), ct.matmul(Ry, ct.matmul(Rx, Rz)))


def test_engine_euler_inverts_the_orientation():
    for yaw, pitch, roll in ((0.0, 0.0, 0.0), (20.0, -10.0, 5.0), (-170.0, 60.0, 90.0), (33.0, -89.0, 12.0)):
        got = pi.engine_euler(pi.engine_orientation(yaw, pitch, roll))
        assert _close(pi.engine_orientation(*got), pi.engine_orientation(yaw, pitch, roll), 1e-9), (yaw, pitch, roll)
    assert _close(pi.engine_euler(pi.engine_orientation(20.0, -10.0, 5.0)), (20.0, -10.0, 5.0), 1e-9)
    # the gimbal lock branch still returns a decomposition
    yaw, pitch, roll = pi.engine_euler(pi.engine_orientation(30.0, 90.0, 0.0))
    assert _close(pitch, 90.0, 1e-6) and roll == 0.0


def test_engine_zoom_is_the_focal_length_in_pixels():
    assert _close(pi.engine_zoom(96, 60.0), ct.intrinsics(96, 72, 60.0)[0][0])
    assert _close(pi.engine_zoom(1920, 90.0), 960.0)
    with pytest.raises(pi.PlateError):
        pi.engine_zoom(96, 0.0)
    with pytest.raises(pi.PlateError):
        pi.engine_zoom(96, 180.0)


def test_engine_project_is_the_pinhole_with_y_down_and_z_forward():
    cam = {"x": 48.0, "y": 36.0, "z": -pi.engine_zoom(96, 60.0), "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": 60.0}
    # the default camera puts the z = 0 plane at pixel scale
    assert _close(pi.engine_project(cam, (48.0, 36.0, 0.0), 96, 72), (48.0, 36.0))
    assert _close(pi.engine_project(cam, (0.0, 0.0, 0.0), 96, 72), (0.0, 0.0))
    assert _close(pi.engine_project(cam, (96.0, 72.0, 0.0), 96, 72), (96.0, 72.0))
    # a point twice as far from the eye projects at half the offset
    z = pi.engine_zoom(96, 60.0)
    assert _close(pi.engine_project(cam, (96.0, 72.0, z), 96, 72), (72.0, 54.0))
    # behind the eye is an error
    with pytest.raises(pi.PlateError):
        pi.engine_project(cam, (0.0, 0.0, -2.0 * z), 96, 72)


def test_camera_from_row_places_the_engine_camera_at_the_solved_pose():
    motion = ct.camera_motion()
    R, t = ct.camera_pose(motion, 0)
    rx, ry, rz = ct.rotation_to_euler(R)
    row = {"frame": 0, "tx": t[0], "ty": t[1], "tz": t[2], "rx": rx, "ry": ry, "rz": rz, "fov": 60.0}
    cam = pi.camera_from_row(row, 100.0)
    assert set(cam) == {"x", "y", "z", "yaw", "pitch", "roll", "fov"}
    # the frame-0 camera looks down z at the target from tz metres, so the eye sits at -100 tz scene units
    assert _close((cam["x"], cam["y"], cam["z"]), (0.0, 0.0, -100.0 * t[2]))
    assert _close((cam["yaw"], cam["pitch"], cam["roll"]), (0.0, 0.0, 0.0))
    assert cam["fov"] == 60.0
    # the target corner (-0.24, -0.18) m lands at (24, 18): the plate position the synthetic plate was built from
    assert _close(pi.engine_project(cam, (-24.0, -18.0, 0.0), 96, 72), (24.0, 18.0), 1e-6)
    with pytest.raises(pi.PlateError):
        pi.camera_from_row(row, 0.0)
    with pytest.raises(pi.PlateError):
        pi.camera_from_row({"frame": 0, "tx": 0.0}, 100.0)


def test_the_engine_projection_agrees_with_the_tracking_pinhole_at_every_frame():
    motion = ct.camera_motion()
    K = ct.intrinsics(96, 72, 60.0)
    corners = ct.planar_target_points(0.48, 0.36)
    worst = 0.0
    for frame in range(8):
        R, t = ct.camera_pose(motion, frame)
        rx, ry, rz = ct.rotation_to_euler(R)
        row = {"frame": frame, "tx": t[0], "ty": t[1], "tz": t[2], "rx": rx, "ry": ry, "rz": rz, "fov": 60.0}
        cam = pi.camera_from_row(row, 100.0)
        for X, Y in corners:
            a = ct.project(K, R, t, (X, Y, 0.0))
            b = pi.engine_project(cam, (100.0 * X, 100.0 * Y, 0.0), 96, 72)
            worst = max(worst, math.dist(a, b))
    assert worst < 1e-6
    assert pi.pinhole_agreement() < 1e-6


def test_a_solved_camera_reprojects_the_target_onto_its_plate_positions():
    # SREP 12's LA3 test: the camera solved by the computed-tracking draft, written as the engine's camera,
    # re-projects the scene points anchored on the target onto their plate positions
    worst = pi.reprojection_run()
    assert worst < pi.REPROJECTION_TOLERANCE
    assert worst > 0.0


def test_camera_at_frame_holds_the_row_and_refuses_an_empty_track():
    rows = [{"frame": 0, "tx": 0.0, "ty": 0.0, "tz": 1.0, "rx": 0.0, "ry": 0.0, "rz": 0.0, "fov": 60.0},
            {"frame": 2, "tx": 0.1, "ty": 0.0, "tz": 1.0, "rx": 0.0, "ry": 0.0, "rz": 0.0, "fov": 60.0}]
    # rows hold until the next one; before the first row the first row applies
    assert pi.camera_at(rows, 1, 100.0)["x"] == pi.camera_at(rows, 0, 100.0)["x"]
    assert _close(pi.camera_at(rows, 2, 100.0)["x"], -10.0)
    assert _close(pi.camera_at(rows, 7, 100.0)["x"], -10.0)
    assert pi.camera_at(rows, -1, 100.0)["x"] == pi.camera_at(rows, 0, 100.0)["x"]
    with pytest.raises(pi.PlateError):
        pi.camera_at([], 0, 100.0)


# ------------------------------------------------------------------------------------ the lens


def test_normalised_coordinates_follow_the_post_shader():
    # three_post.wgsl: p = (uv - 0.5) * (w / h, 1): the vertical half-height is 0.5
    assert _close(pi.normalised((48.0, 36.0), 96, 72), (0.0, 0.0))
    assert _close(pi.normalised((96.0, 0.0), 96, 72), (96.0 / 72.0 * 0.5, -0.5))
    assert _close(pi.pixel_of(pi.normalised((17.0, 61.0), 96, 72), 96, 72), (17.0, 61.0))


def test_source_of_and_output_of_are_the_shader_warp_and_its_inverse():
    p = (0.6, -0.5)
    r2 = 0.61
    assert _close(pi.source_of(p, 0.08), (0.6 * (1.0 + 0.08 * r2), -0.5 * (1.0 + 0.08 * r2)))
    assert _close(pi.source_of(p, 0.0), p)
    q = pi.output_of(pi.source_of(p, 0.08), 0.08)
    assert _close(q, p, 1e-9)
    q = pi.output_of(pi.source_of(p, -0.05), -0.05)
    assert _close(q, p, 1e-9)
    assert _close(pi.output_of((0.0, 0.0), 0.3), (0.0, 0.0))
    # beyond the fold of a strong negative k1 there is no output pixel
    with pytest.raises(pi.PlateError):
        pi.output_of((0.9, 0.0), -0.5)


def test_distort_and_undistort_pixels_round_trip_and_positive_k1_is_barrel():
    d = pi.distort_pixel((90.0, 10.0), 0.08, 96, 72)
    # barrel: an off-centre source pixel appears nearer the centre
    assert math.dist(d, (48.0, 36.0)) < math.dist((90.0, 10.0), (48.0, 36.0))
    assert _close(pi.undistort_pixel(d, 0.08, 96, 72), (90.0, 10.0), 1e-9)
    # pincushion: farther out
    d = pi.distort_pixel((90.0, 10.0), -0.05, 96, 72)
    assert math.dist(d, (48.0, 36.0)) > math.dist((90.0, 10.0), (48.0, 36.0))
    # the centre never moves and k1 = 0 is the identity
    assert _close(pi.distort_pixel((48.0, 36.0), 0.2, 96, 72), (48.0, 36.0))
    assert _close(pi.distort_pixel((90.0, 10.0), 0.0, 96, 72), (90.0, 10.0))


def test_engine_project_with_lens_distortion_is_the_distorted_pinhole():
    cam = {"x": 48.0, "y": 36.0, "z": -pi.engine_zoom(96, 60.0), "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": 60.0,
           "lensDistortion": 0.08}
    plain = dict(cam, lensDistortion=0.0)
    for point in ((0.0, 0.0, 0.0), (90.0, 10.0, 0.0), (48.0, 36.0, 0.0)):
        want = pi.distort_pixel(pi.engine_project(plain, point, 96, 72), 0.08, 96, 72)
        assert _close(pi.engine_project(cam, point, 96, 72), want, 1e-9)


def test_line_residual_is_zero_for_straight_points_and_positive_for_bent_ones():
    straight = [(float(x), 2.0 + 0.5 * x) for x in range(9)]
    assert pi.line_residual(straight) < 1e-12
    bent = [(float(x), 0.1 * (x - 4) ** 2) for x in range(9)]
    assert pi.line_residual(bent) > 0.1
    with pytest.raises(pi.PlateError):
        pi.line_residual([(0.0, 0.0)])


def test_synthetic_lines_are_straight_in_the_pinhole_and_bent_in_the_output():
    lines = pi.synthetic_lines(96, 72, 0.0)
    assert len(lines) >= pi.MIN_PLUMB_LINES and all(len(l) >= pi.MIN_LINE_POINTS for l in lines)
    assert all(pi.line_residual(l) < 1e-9 for l in lines)
    bent = pi.synthetic_lines(96, 72, 0.08)
    assert max(pi.line_residual(l) for l in bent) > 0.1
    # undistorting with the right k1 straightens them again
    assert all(pi.line_residual([pi.undistort_pixel(p, 0.08, 96, 72) for p in l]) < 1e-9 for l in bent)


def test_plumb_line_k1_recovers_the_distortion():
    for truth in (0.08, -0.05, 0.0, 0.2):
        got = pi.plumb_line_k1(pi.synthetic_lines(96, 72, truth), 96, 72)
        assert abs(got - truth) < pi.K1_TOLERANCE, (truth, got)
    # a little noise on the points keeps the estimate close
    noisy = [[(x + 0.05 * math.sin(7.0 * k), y + 0.05 * math.cos(5.0 * k)) for k, (x, y) in enumerate(l)]
             for l in pi.synthetic_lines(96, 72, 0.08)]
    assert abs(pi.plumb_line_k1(noisy, 96, 72) - 0.08) < 0.01
    with pytest.raises(pi.PlateError):
        pi.plumb_line_k1(pi.synthetic_lines(96, 72, 0.08)[:1], 96, 72)
    with pytest.raises(pi.PlateError):
        pi.plumb_line_k1([l[:3] for l in pi.synthetic_lines(96, 72, 0.08)], 96, 72)


def test_undistorting_the_tracked_corners_before_the_pose_fit_removes_the_lens_error():
    with_fix = pi.lens_run(0.15)
    without = pi.lens_run(0.15, correct=False)
    assert with_fix < pi.REPROJECTION_TOLERANCE
    assert without > pi.REPROJECTION_TOLERANCE
    assert pi.lens_run(0.0) < 1e-6


# ------------------------------------------------------------------------------------ the shadow catcher


def test_catcher_alpha_follows_srep_41():
    # three.wgsl: black with alpha = opacity (1 - lit_sh / lit_un), kept = 1 without light
    assert pi.catcher_alpha(0.0, 1.0, 1.0) == 1.0
    assert _close(pi.catcher_alpha(0.5, 1.0, 1.0), 0.5)
    assert pi.catcher_alpha(0.0, 0.0, 1.0) == 0.0
    assert _close(pi.catcher_alpha(0.0, 1.0, 0.4), 0.4)
    assert pi.catcher_alpha(1.0, 1.0, 1.0) == 0.0
    assert _close(pi.composite_catcher((0.5, 0.4, 0.3), 0.5), (0.25, 0.2, 0.15))
    assert _close(pi.luma((1.0, 1.0, 1.0)), 1.0)
    assert _close(pi.luma((0.0, 1.0, 0.0)), 0.7152)


def test_sphere_shadow_on_the_tracked_plane():
    # the plane is the tracked target z = 0 with its normal towards the camera (-z); a sphere hangs above it
    sphere = ((0.0, 0.0, -0.2), 0.1)
    light = (0.0, 0.0, 1.0)  # light travelling along +z, straight down onto the plane
    assert pi.sphere_shadow((0.0, 0.0, 0.0), sphere, light)
    assert pi.sphere_shadow((0.09, 0.0, 0.0), sphere, light)
    assert not pi.sphere_shadow((0.11, 0.0, 0.0), sphere, light)
    # a light coming at 45 degrees shifts the footprint
    slanted = pi.unit((1.0, 0.0, 1.0))
    assert pi.sphere_shadow((0.2, 0.0, 0.0), sphere, slanted)
    assert not pi.sphere_shadow((-0.2, 0.0, 0.0), sphere, slanted)
    assert not pi.sphere_shadow((0.0, 0.0, 0.0), sphere, slanted)
    # a light from below the plane never shadows it (the plane faces -z)
    assert not pi.sphere_shadow((0.0, 0.0, 0.0), sphere, (0.0, 0.0, -1.0))


def test_shadow_alpha_shares_the_light_the_casters_take_away():
    sphere = ((0.0, 0.0, -0.2), 0.1)
    down = {"direction": (0.0, 0.0, 1.0), "colour": (1.0, 1.0, 1.0)}
    side = {"direction": pi.unit((1.0, 0.0, 1.0)), "colour": (1.0, 1.0, 1.0)}
    scene = {"sphere": sphere, "lights": [down], "opacity": 1.0}
    assert _close(pi.shadow_alpha_at((0.0, 0.0, 0.0), scene), 1.0)
    assert _close(pi.shadow_alpha_at((0.3, 0.0, 0.0), scene), 0.0)
    # two lights of equal luma: the straight-down one is blocked at the origin, the slanted one is not;
    # the slanted light arrives at cos 45 degrees, so the share taken away is 1 / (1 + cos 45)
    scene = {"sphere": sphere, "lights": [down, side], "opacity": 1.0}
    assert _close(pi.shadow_alpha_at((0.0, 0.0, 0.0), scene), 1.0 / (1.0 + math.cos(math.pi / 4.0)))
    scene = {"sphere": sphere, "lights": [down], "opacity": 0.5}
    assert _close(pi.shadow_alpha_at((0.0, 0.0, 0.0), scene), 0.5)
    # no light at all leaves the plate untouched
    assert pi.shadow_alpha_at((0.0, 0.0, 0.0), {"sphere": sphere, "lights": [], "opacity": 1.0}) == 0.0


def test_the_shadow_footprint_lands_under_the_sphere_on_the_plate():
    # through the frame-0 camera the plane point under the sphere is the plate centre; the catcher darkens it
    row = pi.frame_zero_row()
    cam = pi.camera_from_row(row, 100.0)
    scene = {"sphere": ((0.0, 0.0, -0.2), 0.1), "lights": [{"direction": (0.0, 0.0, 1.0), "colour": (1.0, 1.0, 1.0)}],
             "opacity": 1.0}
    plate = pi.catcher_plate(cam, scene, 96, 72, (0.5, 0.5, 0.5))
    assert len(plate) == 72 and len(plate[0]) == 96
    assert _close(plate[36][48], (0.0, 0.0, 0.0))
    assert _close(plate[36][90], (0.5, 0.5, 0.5))
    # the footprint radius is 0.1 m = 10 scene units at the plate's scale
    assert _close(plate[36][48 + 9], (0.0, 0.0, 0.0))
    assert _close(plate[36][48 + 11], (0.5, 0.5, 0.5))
    assert _close(pi.footprint_radius(plate, (0.5, 0.5, 0.5)), 10.0, 1.0)


# ------------------------------------------------------------------------------------ anchoring


def test_object_from_pose_uses_the_engine_z_y_x_order():
    # local3: T(x, y, z) · Rz(rotation) · Ry(rotationY) · Rx(rotationX) · S
    R = ct.euler_to_rotation(10.0, -20.0, 30.0)
    obj = pi.object_from_pose(R, (1.0, 2.0, 3.0))
    assert set(obj) == {"x", "y", "z", "rotation", "rotationY", "rotationX"}
    assert _close((obj["x"], obj["y"], obj["z"]), (1.0, 2.0, 3.0))
    assert _close((obj["rotationX"], obj["rotationY"], obj["rotation"]), (10.0, -20.0, 30.0), 1e-9)


def test_anchor_from_plane_places_the_plane_in_the_world_through_the_camera():
    # the plane pose (R_p, t_p) is the plane's frame in camera coordinates; the camera's frame in the world is
    # (M, eye): the plane's frame in the world is (M R_p, eye + scale M t_p)
    row = pi.frame_zero_row()
    cam = pi.camera_from_row(row, 100.0)
    R, t = ct.camera_pose(ct.camera_motion(), 0)
    obj = pi.anchor_from_plane(cam, {"R": R, "t": t}, 100.0)
    # the tracked plane is the world origin, so the anchored object sits there
    assert _close((obj["x"], obj["y"], obj["z"]), (0.0, 0.0, 0.0), 1e-6)
    assert _close((obj["rotation"], obj["rotationY"], obj["rotationX"]), (0.0, 0.0, 0.0), 1e-6)
    # a plane half a metre nearer the camera sits 50 units towards the eye
    obj = pi.anchor_from_plane(cam, {"R": R, "t": (t[0], t[1], t[2] - 0.5)}, 100.0)
    assert _close((obj["x"], obj["y"], obj["z"]), (0.0, 0.0, -50.0), 1e-6)


def test_the_anchored_plane_stays_at_the_world_origin_over_the_solved_track():
    drift = pi.anchor_drift()
    assert drift["position"] < 1.0  # scene units, a centimetre at pixelsPerMeter 100
    assert drift["degrees"] < 3.0  # a 48 px target constrains the tilt weakly (the planar-pose ambiguity)
    assert drift["position"] > 0.0


# ------------------------------------------------------------------------------------ validation


def _doc():
    return {"version": "1.8", "tracks": {"cam": "camera", "plane": "planar", "pt": "point"},
            "cameras": [{"id": "c1", "track": "cam", "trackScale": 100.0}],
            "objects": [{"id": "o1", "anchor": "plane", "anchorName": "a", "shadowCatcher": True}],
            "solves": [{"kind": "camera", "lens": "plumb"}]}


def test_validation_rules_pi1_to_pi4_and_v17():
    pi.validate_document(_doc())
    d = _doc()
    d["cameras"][0]["track"] = "pt"
    with pytest.raises(pi.PlateError, match="PI1"):
        pi.validate_document(d)
    d = _doc()
    d["cameras"][0]["track"] = "missing"
    with pytest.raises(pi.PlateError, match="PI1"):
        pi.validate_document(d)
    d = _doc()
    d["cameras"][0]["x"] = 3.0
    # explicit pose attributes on a tracked camera are ignored with a warning, not refused
    assert pi.validate_document(d) == ["PI1: camera c1 has track and x; x is ignored"]
    d = _doc()
    d["cameras"][0]["trackScale"] = 0.0
    with pytest.raises(pi.PlateError, match="PI2"):
        pi.validate_document(d)
    d = _doc()
    d["objects"][0]["anchor"] = "cam"
    with pytest.raises(pi.PlateError, match="PI3"):
        pi.validate_document(d)
    d = _doc()
    d["solves"][0]["lens"] = "zoom"
    with pytest.raises(pi.PlateError, match="PI4"):
        pi.validate_document(d)
    d = _doc()
    d["cameras"][0]["lensDistortion"] = 0.75
    with pytest.raises(pi.PlateError, match="PI4"):
        pi.validate_document(d)
    d = _doc()
    d["version"] = "1.7"
    with pytest.raises(pi.PlateError, match="V17"):
        pi.validate_document(d)
    # a 1.7 document without the new attributes stays valid
    assert pi.validate_document({"version": "1.7", "tracks": {}, "cameras": [{"id": "c"}], "objects": [], "solves": []}) == []


def test_constants():
    assert pi.DEFAULT_PIXELS_PER_METER == 100.0
    assert pi.REPROJECTION_TOLERANCE == 0.5
    assert pi.K1_TOLERANCE == 0.001
    assert pi.MAX_K1 == 0.5
    assert pi.LENS_MODES == ("none", "plumb")
    assert pi.MIN_PLUMB_LINES == 2 and pi.MIN_LINE_POINTS == 5
    assert pi.LUMA == (0.2126, 0.7152, 0.0722)


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
    for word in ("SR-99", "SR-97", "SREP 41", "SREP 12", "camera", "track", "trackScale", "pixelsPerMeter", "yaw",
                 "pitch", "roll", "fov", "lensDistortion", "object3D", "anchor", "anchorName", "shadowCatcher",
                 "opacity", "lens", "plumb", "k1", "three_post.wgsl", "barrel", "rotation", "rotationY", "rotationX",
                 "0.5 px", "PI1", "PI2", "PI3", "PI4", "V17", "plate_integration_reference.py", "computed-tracking",
                 "y down", "z forward", "horizontal", "vertical", "re-project"):
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
    assert len(pi.TABLE) == len(_draft_rows())
    for (name, expr, _value), (dname, dexpr, _dvalue) in zip(pi.TABLE, _draft_rows()):
        assert name == dname and expr == dexpr


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = pi.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or pi._same(got, want), f"{name}: {got!r} != {want!r}"
