"""Tests of the draft SREP "Add time scales, celestial frames and JPL ephemerides" (srep/srep-0000-time-frames.md)
and of its reference implementation conformance/tools/time_frames_reference.py (SP1 of SREP 12, SRC-44).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there. The ephemeris fixture
conformance/assets/de440s-excerpt.bsp is an SPK excerpt of JPL's de440s.bsp written by the module; the Horizons
vectors in conformance/assets/horizons-vectors.json are the positions it is held to.
"""
import hashlib
import importlib.util
import json
import math
import os
import re
import struct

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "time_frames_reference.py")
SKY = os.path.join(ROOT, "conformance", "tools", "physical_sky_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-time-frames.md")
EXCERPT = os.path.join(ROOT, "conformance", "assets", "de440s-excerpt.bsp")
VECTORS = os.path.join(ROOT, "conformance", "assets", "horizons-vectors.json")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tf = _load("time_frames_reference", MODULE)
sky = _load("physical_sky_reference", SKY)


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@pytest.fixture(scope="module")
def spk():
    return tf.open_ephemeris(EXCERPT, tf.EXCERPT_DIGEST)


@pytest.fixture(scope="module")
def horizons():
    with open(VECTORS, encoding="utf-8") as f:
        return json.load(f)["bodies"]


# ------------------------------------------------------------------------------------ rule 1: calendar and time scales


def test_julian_day_and_calendar_round_trip():
    assert tf.julian_day(2000, 1, 1, 12, 0, 0.0) == 2451545.0
    assert tf.calendar(2451545.0) == (2000, 1, 1, 12, 0, 0.0)
    assert tf.julian_day(1972, 1, 1, 0, 0, 0.0) == 2441317.5
    y, m, d, h, mi, s = tf.calendar(tf.julian_day(2026, 10, 24, 23, 59, 59.5))
    assert (y, m, d, h, mi) == (2026, 10, 24, 23, 59) and abs(s - 59.5) < 1e-4, "a Julian day double resolves 40 microseconds"


def test_parse_utc_accepts_offsets_and_rejects_bad_dates():
    assert tf.parse_utc("2003-10-17T12:30:30-07:00") == (2003, 10, 17, 19, 30, 30.0)
    assert tf.parse_utc("2003-10-17T19:30:30Z") == (2003, 10, 17, 19, 30, 30.0)
    assert tf.parse_utc("2003-10-17T23:30:30-01:00") == (2003, 10, 18, 0, 30, 30.0)
    for bad in ("2003-10-17", "2003-10-17T12:30:30", "2003-13-01T00:00:00Z", "2003-10-17T24:00:00Z", "", None):
        with pytest.raises(tf.FrameError):
            tf.parse_utc(bad)


def test_leap_seconds_follow_the_naif_table():
    assert tf.leap_seconds(tf.julian_day(1972, 1, 1, 0, 0, 0.0)) == 10
    assert tf.leap_seconds(tf.julian_day(1972, 6, 30, 23, 59, 59.0)) == 10
    assert tf.leap_seconds(tf.julian_day(1972, 7, 1, 0, 0, 0.0)) == 11
    assert tf.leap_seconds(tf.julian_day(2016, 12, 31, 23, 59, 59.0)) == 36
    assert tf.leap_seconds(tf.julian_day(2017, 1, 1, 0, 0, 0.0)) == 37
    assert tf.leap_seconds(tf.julian_day(2026, 10, 24, 0, 0, 0.0)) == 37
    assert len(tf.LEAP_SECONDS) == 28
    with pytest.raises(tf.FrameError):
        tf.leap_seconds(tf.julian_day(1971, 12, 31, 0, 0, 0.0))


def test_time_scales_chain_utc_tai_tt_tdb():
    jd_utc = tf.julian_day(2017, 1, 1, 0, 0, 0.0)
    tai = tf.tai_from_utc(jd_utc)
    assert _close((tai - jd_utc) * 86400.0, 37.0, 1e-4), "a Julian day double resolves 40 microseconds"
    tt = tf.tt_from_tai(tai)
    assert _close((tt - tai) * 86400.0, 32.184, 1e-4)
    tdb = tf.tdb_from_tt(tt)
    assert abs(tdb - tt) * 86400.0 < 0.0017
    assert tf.ephemeris_time(tt) == (tt - 2451545.0) * 86400.0
    # The NAIF formula at its own constants: K sin(E), E = M + EB sin M.
    assert _close(tf.tdb_minus_tt(2451545.0), 0.001657 * math.sin(6.239996 + 0.01671 * math.sin(6.239996)), 1e-9)
    assert _close(tf.et_from_utc("2000-01-01T11:58:55.816Z"), tf.tdb_minus_tt(2451545.0), 1e-6)


def test_the_frame_clock_is_linear_in_the_frame_number():
    space = tf.space(epoch="2026-10-24T00:00:00Z", rate=60.0)
    e0 = tf.frame_time(space, 0, 24.0)
    e1 = tf.frame_time(space, 24, 24.0)
    e2 = tf.frame_time(space, 48, 24.0)
    assert _close(e1 - e0, 60.0, 1e-9) and _close(e2 - e1, 60.0, 1e-9)
    assert tf.frame_time(tf.space(epoch="2026-10-24T00:00:00Z", rate=0.0), 500, 24.0) == e0
    assert tf.frame_time(tf.space(epoch="2451545.0", time_scale="tdb"), 0, 24.0) == 0.0
    assert _close(tf.frame_time(tf.space(epoch="2451545.0", time_scale="tt"), 0, 24.0), tf.tdb_minus_tt(2451545.0), 1e-9)
    with pytest.raises(tf.FrameError):
        tf.space(epoch="2026-10-24T00:00:00Z", rate=-1.0)
    with pytest.raises(tf.FrameError):
        tf.space(epoch="2026-10-24T00:00:00Z", time_scale="gps")
    with pytest.raises(tf.FrameError):
        tf.space(epoch="not a date")
    with pytest.raises(tf.FrameError):
        tf.frame_time(space, -1, 24.0)
    with pytest.raises(tf.FrameError):
        tf.frame_time(space, 0, 0.0)


# ------------------------------------------------------------------------------------ rules 2 and 3: the SPK file


def test_the_excerpt_is_pinned_by_digest_and_a_wrong_digest_is_refused(spk):
    with open(EXCERPT, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert digest == tf.EXCERPT_DIGEST
    assert spk["digest"] == digest
    with pytest.raises(tf.FrameError):
        tf.open_ephemeris(EXCERPT, "0" * 64)
    with pytest.raises(tf.FrameError):
        tf.open_ephemeris(EXCERPT, "sha256:" + "0" * 64)
    assert tf.open_ephemeris(EXCERPT, "sha256:" + digest)["digest"] == digest


def test_the_excerpt_is_a_daf_spk_with_type_2_segments(spk):
    assert spk["id"] == "DAF/SPK"
    assert spk["nd"] == 2 and spk["ni"] == 6
    assert spk["format"] in ("LTL-IEEE", "BIG-IEEE")
    bodies = sorted({s["target"] for s in spk["segments"]})
    assert bodies == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 199, 299, 301, 399]
    assert all(s["type"] == 2 and s["frame"] == 1 for s in spk["segments"])
    assert {s["center"] for s in spk["segments"] if s["target"] in (301, 399)} == {3}
    assert len(spk["segments"]) > 25, "the summaries span more than one summary record"


def test_a_truncated_or_foreign_file_is_refused(tmp_path):
    with open(EXCERPT, "rb") as f:
        data = f.read()
    short = tmp_path / "short.bsp"
    short.write_bytes(data[:3000])
    with pytest.raises(tf.FrameError):
        tf.read_daf(str(short))
    other = tmp_path / "other.bsp"
    other.write_bytes(b"DAF/CK  " + data[8:])
    with pytest.raises(tf.FrameError):
        tf.read_daf(str(other))
    bad_type = bytearray(data)
    # Flip the first summary's type integer (the 4th integer after the two doubles of the first summary).
    rec = tf.read_daf(EXCERPT)
    first = rec["summary_offsets"][0]
    bad_type[first + 16 + 12:first + 16 + 16] = struct.pack("<i", 9)
    weird = tmp_path / "type9.bsp"
    weird.write_bytes(bytes(bad_type))
    with pytest.raises(tf.FrameError):
        tf.read_daf(str(weird))


def test_chebyshev_evaluation_matches_a_direct_sum():
    coeffs = (1.0, -0.5, 0.25, 0.125, -0.0625)
    for t in (-1.0, -0.3, 0.0, 0.7, 1.0):
        direct = sum(c * math.cos(k * math.acos(t)) for k, c in enumerate(coeffs))
        assert _close(tf.chebyshev(coeffs, t), direct, 1e-12)
    # The derivative of T_k at t is k U_{k-1}(t); check against a finite difference.
    h = 1e-6
    fd = (tf.chebyshev(coeffs, 0.3 + h) - tf.chebyshev(coeffs, 0.3 - h)) / (2 * h)
    assert _close(tf.chebyshev_derivative(coeffs, 0.3), fd, 1e-6)
    with pytest.raises(tf.FrameError):
        tf.chebyshev(coeffs, 1.5)


def test_positions_match_horizons_within_a_kilometre(spk, horizons):
    worst = 0.0
    for body, rows in horizons.items():
        target = 4 if body == "499" else int(body)
        for r in rows:
            et = (r["jd"] - 2451545.0) * 86400.0
            p = tf.position(spk, target, 0, et)
            d = _dist(p, (r["x"], r["y"], r["z"]))
            worst = max(worst, d)
            assert d < 1.0, (body, r["jd"], d)
    assert worst < 0.01, "the DE440 excerpt reproduces Horizons to ten metres"
    assert tf.horizons_test() == (True, True)


def test_velocities_match_horizons(spk, horizons):
    for body in ("3", "301", "399", "4", "5"):
        for r in horizons[body]:
            et = (r["jd"] - 2451545.0) * 86400.0
            v = tf.velocity(spk, int(body), 0, et)
            assert _dist(v, (r["vx"], r["vy"], r["vz"])) < 1e-5, (body, r["jd"])


def test_relative_positions_chain_through_the_centres(spk):
    et = 0.0
    earth = tf.position(spk, 399, 0, et)
    moon = tf.position(spk, 301, 0, et)
    geo = tf.position(spk, 301, 399, et)
    assert _close(geo, tuple(m - e for m, e in zip(moon, earth)), 1e-6)
    assert 356000.0 < _dist(geo, (0.0, 0.0, 0.0)) < 407000.0
    assert tf.position(spk, 399, 399, et) == (0.0, 0.0, 0.0)
    sun = tf.position(spk, 10, 399, et)
    assert 1.47e8 < _dist(sun, (0.0, 0.0, 0.0)) < 1.53e8


def test_times_outside_the_excerpt_and_unknown_bodies_are_refused(spk):
    with pytest.raises(tf.FrameError):
        tf.position(spk, 399, 0, 86400.0 * 365.0 * 3)
    with pytest.raises(tf.FrameError):
        tf.position(spk, 499, 0, 0.0)
    with pytest.raises(tf.FrameError):
        tf.position(spk, 399, 499, 0.0)


def test_light_time_to_the_sun_is_about_499_seconds(spk):
    p, lt = tf.apparent_position(spk, 10, 399, 0.0)
    assert 490.0 < lt < 510.0
    geometric = tf.position(spk, 10, 399, 0.0)
    assert 0.0 < _dist(p, geometric) < 10000.0, "the light-time shift is kilometres, not nothing and not the orbit"
    assert tf.MAX_LIGHT_TIME_ITERATIONS >= 3


def test_the_excerpt_writer_round_trips_and_is_bounded(tmp_path, spk):
    out = str(tmp_path / "again.bsp")
    tf.write_excerpt(EXCERPT, out, [(-10.0, 10.0)], [3, 399], fmt="BIG-IEEE")
    again = tf.open_ephemeris(out, None)
    assert again["format"] == "BIG-IEEE"
    assert sorted({s["target"] for s in again["segments"]}) == [3, 399]
    assert _close(tf.position(again, 399, 0, 0.0), tf.position(spk, 399, 0, 0.0), 1e-9)
    with pytest.raises(tf.FrameError):
        tf.write_excerpt(EXCERPT, out, [(10.0, -10.0)], [3])
    with pytest.raises(tf.FrameError):
        tf.write_excerpt(EXCERPT, out, [(-10.0, 10.0)], [])
    with pytest.raises(tf.FrameError):
        tf.write_excerpt(EXCERPT, out, [(-10.0, 10.0)] * (tf.MAX_SEGMENTS + 1), [3])


# ------------------------------------------------------------------------------------ rule 4: the approximate elements


def test_the_approximate_elements_are_the_published_tables():
    assert len(tf.ELEMENTS_1800_2050) == 8 and len(tf.ELEMENTS_3000BC_3000AD) == 8
    assert tf.ELEMENTS_1800_2050["EM Bary"][0] == 1.00000261
    assert tf.ELEMENTS_1800_2050["Mars"][6] == 0.00001847
    assert tf.ELEMENTS_3000BC_3000AD["Jupiter"][0] == 5.20248019
    assert tf.OUTER_CORRECTIONS["Jupiter"] == (-0.00012452, 0.06064060, -0.35635438, 38.35125000)
    assert tf.BODY_NAMES[3] == "EM Bary" and tf.BODY_NAMES[4] == "Mars"


def test_kepler_solver_converges_and_is_bounded():
    for e in (0.0, 0.0167, 0.2056, 0.9):
        for m in (-170.0, -30.0, 0.0, 45.0, 179.0):
            big_e = tf.solve_kepler(m, e)
            assert abs(big_e - math.degrees(e) * math.sin(math.radians(big_e)) - m) < 1e-6
    assert tf.MAX_KEPLER_ITERATIONS >= 10
    with pytest.raises(tf.FrameError):
        tf.solve_kepler(10.0, 1.0)


def test_approximate_positions_are_within_the_stated_errors(spk):
    # Heliocentric ICRF positions from the elements against DE440 at J2000 and in 2025, within the page's
    # longitude errors (arcseconds) with a margin for the barycentre-to-centre difference.
    for et, table in ((0.0, "1800-2050"), ((2460977.5 - 2451545.0) * 86400.0, "1800-2050"), (0.0, "3000BC-3000AD")):
        for body, limit_arcsec in ((1, 15.0), (2, 20.0), (3, 20.0), (4, 40.0), (5, 400.0), (6, 600.0), (7, 50.0), (8, 10.0)):
            approx = tf.approximate_position(body, et, table)
            exact = tf.position(spk, body, 10, et)
            angle = math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(approx, exact))
                                                            / (_dist(approx, (0, 0, 0)) * _dist(exact, (0, 0, 0)))))))
            assert angle * 3600.0 < 3.0 * limit_arcsec + 60.0, (body, et, table, angle * 3600.0)
    assert tf.elements_test() == (True, True)


def test_approximate_positions_refuse_the_moon_and_dates_off_the_table():
    with pytest.raises(tf.FrameError):
        tf.approximate_position(301, 0.0)
    with pytest.raises(tf.FrameError):
        tf.approximate_position(3, (tf.julian_day(1700, 1, 1, 0, 0, 0.0) - 2451545.0) * 86400.0, "1800-2050")
    with pytest.raises(tf.FrameError):
        tf.approximate_position(3, 0.0, "1600-1700")


# ------------------------------------------------------------------------------------ rule 5: frames


def test_rotation_matrices_are_proper():
    for body in (10, 199, 299, 399, 499, 599, 699, 799, 899, 301):
        m = tf.body_fixed_from_icrf(body, 12345.0)
        for i in range(3):
            for j in range(3):
                dot = sum(m[i][k] * m[j][k] for k in range(3))
                assert _close(dot, 1.0 if i == j else 0.0, 1e-12)
        assert _close(tf.determinant(m), 1.0, 1e-12)


def test_earth_rotation_matches_the_sidereal_time_of_the_sun_module():
    # The Earth's prime meridian angle W of the IAU 2009 elements is Greenwich mean sidereal time to the model's
    # precision; the SPA's apparent sidereal time differs by the equation of the equinoxes (under 0.005 deg).
    jd_ut = sky.julian_day(2003, 10, 17, 12, 30, 30.0, -7.0)
    t = sky.time_scales(jd_ut, 67.0)
    dpsi, deps = sky.nutation(t["jce"])
    gast = sky.sidereal_time(jd_ut, t["jc"], dpsi, sky.true_obliquity(t["jme"], deps))
    et = (t["jde"] - 2451545.0) * 86400.0
    ra, dec, w = tf.rotation_elements(399, et)
    assert w == tf.prime_meridian(399, et)
    # The prime meridian's right ascension is the node (ra + 90) plus W; the IAU expression for the Earth is an
    # approximation the report itself flags, a third of a degree from the sidereal time.
    assert abs((ra + 90.0 + w - gast + 180.0) % 360.0 - 180.0) < 0.5
    period = 360.0 / tf.ROTATION[399][2][1] * 86400.0
    assert abs(period - 86164.0905) < 0.01, "one sidereal day"


def test_body_fixed_frames_place_the_prime_meridian_and_pole():
    et = 0.0
    m = tf.body_fixed_from_icrf(399, et)
    pole = tf.pole_icrf(399, et)
    # The pole maps to the body-fixed z axis; the prime meridian direction to the x axis.
    assert _close(tf.apply(m, pole), (0.0, 0.0, 1.0), 1e-12)
    ra, dec, w = tf.rotation_elements(399, et)
    assert _close(dec, 90.0 - 0.557 * 0.0, 1e-12) and _close(w % 360.0, 190.147, 1e-9)
    meridian = tf.apply(tf.transpose(m), (1.0, 0.0, 0.0))
    # It lies in the equator (perpendicular to the pole) and W degrees east of the node.
    assert abs(sum(a * b for a, b in zip(meridian, pole))) < 1e-12
    node = (math.cos(math.radians(ra + 90.0)), math.sin(math.radians(ra + 90.0)), 0.0)
    assert _close(math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(meridian, node)))))), 360.0 - w % 360.0, 1e-6)
    with pytest.raises(tf.FrameError):
        tf.body_fixed_from_icrf(1234, et)


def test_ecliptic_frame_is_the_j2000_obliquity():
    m = tf.ecliptic_from_icrf()
    eps = math.radians(tf.OBLIQUITY_J2000)
    # The celestial pole seen in ecliptic coordinates is at longitude 90 degrees, latitude 90 - obliquity.
    assert _close(tf.apply(m, (0.0, 0.0, 1.0)), (0.0, math.sin(eps), math.cos(eps)), 1e-12)
    assert _close(tf.apply(m, (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0), 1e-12)
    assert tf.OBLIQUITY_J2000 == 23.43928


def test_scene_mapping_is_right_handed_and_scaled_by_pixels_per_metre():
    space = tf.space(epoch="2451545.0", time_scale="tdb", origin=399, frame="icrf")
    # ICRF (x, y, z) km -> scene (x, -z, y) * 1000 * pixelsPerMeter, about the origin body.
    p = tf.scene_from_icrf(space, (1.0, 2.0, 3.0), (0.0, 0.0, 0.0), pixels_per_meter=1e-6)
    assert _close(p, (1.0e-3, -3.0e-3, 2.0e-3), 1e-15)
    basis = [tf.scene_from_icrf(space, e, (0.0, 0.0, 0.0), pixels_per_meter=1e-3) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    assert _close(tf.determinant(basis), 1.0, 1e-12)
    with pytest.raises(tf.FrameError):
        tf.scene_from_icrf(space, (1.0, 2.0, 3.0), (0.0, 0.0, 0.0), pixels_per_meter=0.0)


def test_a_body_is_placed_in_the_space_at_the_frame_time(spk):
    space = tf.space(epoch="2451545.0", time_scale="tdb", origin=399, frame="icrf")
    moon = tf.place_body(spk, space, 301, frame=0, fps=24.0, pixels_per_meter=1e-6)
    geo = tf.position(spk, 301, 399, 0.0)
    assert _close(moon["position"], tf.scene_from_icrf(space, geo, (0.0, 0.0, 0.0), 1e-6), 1e-9)
    assert _close(tf.determinant(moon["orientation"]), 1.0, 1e-12)
    fixed = tf.space(epoch="2451545.0", time_scale="tdb", origin=399, frame="bodyFixed", frame_body=399)
    sun = tf.place_body(spk, fixed, 10, frame=0, fps=24.0, pixels_per_meter=1e-6)
    # In the Earth-fixed frame the sun's longitude at 12:00 TDB on 2000-01-01 is near the Greenwich meridian.
    x, y, z = sun["position"]
    lon = math.degrees(math.atan2(z, x))
    assert abs(lon) < 5.0, lon
    with pytest.raises(tf.FrameError):
        tf.space(epoch="2451545.0", time_scale="tdb", frame="bodyFixed")
    with pytest.raises(tf.FrameError):
        tf.space(epoch="2451545.0", time_scale="tdb", frame="galactic")


def test_the_space_is_a_function_of_the_frame_alone(spk):
    space = tf.space(epoch="2025-10-28T00:00:00Z", rate=3600.0, origin=0, frame="eclipticJ2000")
    first = tf.place_body(spk, space, 4, frame=40, fps=24.0, pixels_per_meter=1e-9)
    tf.place_body(spk, space, 4, frame=1000, fps=24.0, pixels_per_meter=1e-9)
    again = tf.place_body(spk, space, 4, frame=40, fps=24.0, pixels_per_meter=1e-9)
    assert first == again
    assert tf.seek_test() == (True, True)


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
    assert "SR-87" in draft
    for word in ("space", "epoch", "timeScale", "rate", "origin", "frame", "ephemeris", "digest", "sha256",
                 "approximate", "body", "positionFrom", "orientation", "UTC", "TAI", "TT", "TDB", "leap second",
                 "ICRF", "eclipticJ2000", "bodyFixed", "DE440", "de440s.bsp", tf.DE440S_DIGEST, "DAF", "Chebyshev",
                 "type 2", "Standish", "Williams", "IAU", "pck00010.tpc", "naif0012.tls", "Horizons", "1 km",
                 "light time", "pixelsPerMeter", "SREP 14", "TF1", "V17", "seek check", "time_frames_reference.py",
                 "de440s-excerpt.bsp", "public domain", "physical sky"):
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


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    s = tf.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or tf._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    tf.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())


# ------------------------------------------------------------------------------------ the engine's four points (SR-87)


def test_a_utc_offset_is_bounded_and_1972_is_checked_after_it():
    assert tf.parse_utc("2000-01-01T00:00:00+23:59") == (1999, 12, 31, 0, 1, 0.0)
    for bad in ("2000-01-01T00:00:00+24:00", "2000-01-01T00:00:00+00:60", "2000-01-01T00:00:00+99:99"):
        with pytest.raises(tf.FrameError):
            tf.parse_utc(bad)
    assert tf.et_from_utc("1971-12-31T23:30:00-01:00") < 0.0      # 1972-01-01T00:30 UTC after the offset
    with pytest.raises(tf.FrameError):
        tf.et_from_utc("1972-01-01T00:30:00+01:00")                # 1971-12-31T23:30 UTC after the offset


def test_a_tt_or_tdb_epoch_is_a_decimal_lexical():
    for text, value in (("2451545.0", 2451545.0), ("+2451545", 2451545.0), ("2451545.", 2451545.0), (".5", 0.5),
                        ("-1.5", -1.5)):
        assert tf.parse_julian_day(text) == value, text
    for bad in ("nan", "inf", "-inf", "1e6", "1.2.3", "", " 2451545.0", "2451545.0 ", "0x10", "1_000", None):
        with pytest.raises(tf.FrameError):
            tf.parse_julian_day(bad)
    assert tf.space("2451545.0", "tdb")["et0"] == 0.0
    with pytest.raises(tf.FrameError):
        tf.space("nan", "tt")


def test_the_element_table_is_chosen_by_year_and_bounded():
    def et(year):
        return (tf.julian_day(year, 1, 1) - 2451545.0) * 86400.0
    assert tf.element_table(et(1800)) == "1800-2050" and tf.element_table(et(2050)) == "1800-2050"
    assert tf.element_table(et(1799)) == "3000BC-3000AD" and tf.element_table(et(2051)) == "3000BC-3000AD"
    assert tf.element_table(et(-3000)) == "3000BC-3000AD" and tf.element_table(et(3000)) == "3000BC-3000AD"
    for year in (-3001, 3001):
        with pytest.raises(tf.FrameError):
            tf.element_table(et(year))
    assert (tf.julian_day(-3000, 1, 1), tf.julian_day(3001, 1, 1)) == (625332.5, 2817152.5)
    assert tf.approximate_position(5, et(1500)) == tf.approximate_position(5, et(1500), "3000BC-3000AD")
    assert tf.approximate_position(5, 0.0) == tf.approximate_position(5, 0.0, "1800-2050")
    with pytest.raises(tf.FrameError):
        tf.approximate_position(5, et(1500), "1800-2050")


def test_the_approximate_origin_is_the_sun_or_a_planet():
    assert tf.approximate_relative(4, 0, 0.0) == tf.approximate_position(4, 0.0)
    assert tf.approximate_relative(4, 10, 0.0) == tf.approximate_position(4, 0.0)
    assert tf.approximate_relative(10, 0, 0.0) == (0.0, 0.0, 0.0)
    rel = tf.approximate_relative(4, 3, 0.0)
    assert _close(rel, tuple(a - b for a, b in zip(tf.approximate_position(4, 0.0), tf.approximate_position(3, 0.0))))
    for origin in (301, 399, 9):
        with pytest.raises(tf.FrameError):
            tf.approximate_relative(4, origin, 0.0)
    sp = tf.space("2451545.0", "tdb", origin=3)
    placed = tf.place_body("approximate", sp, 4, 0, 24.0, 1e-9)
    assert _close(placed["position"], tf.scene_from_icrf(sp, rel, (0.0, 0.0, 0.0), 1e-9), 1e-6)
    with pytest.raises(tf.FrameError):
        tf.place_body("approximate", tf.space("2451545.0", "tdb", origin=399), 4, 0, 24.0, 1e-9)


def test_the_draft_settles_the_engine_vendoring_points(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("`ephemeris` is `approximate` or the `id` of an `ephemeris` asset",
                   "with `approximate`, `origin` is 0, 10 or a body 1 to 8",
                   "the barycentre 0 is read as the Sun 10",
                   "its offset is at most 23:59",
                   "after the offset, is not before 1972-01-01 UTC",
                   "no exponent, `nan` or `inf`",
                   "Julian day is 625332.5 or more and under 2817152.5",
                   "`element_table(t)` chooses Table 1 when the year of t is 1800 to 2050",
                   "`approximate_relative(body, origin, t)`",
                   "`srep-<n>-space-no-asset.xml`",
                   "45ff742"):
        assert phrase in text, phrase
