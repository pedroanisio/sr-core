"""Tests of the draft SREP "Add star fields from the Bright Star Catalogue" (srep/srep-0000-star-fields.md) and of
its reference implementation conformance/tools/star_fields_reference.py (SP2 of SREP 12, SRC-45).

The module is loaded by path so the test needs no package; every numeric row of the draft's table is evaluated in
the module's namespace and compared to the expected value printed there.
"""
import gzip
import hashlib
import importlib.util
import math
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "star_fields_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-star-fields.md")
CATALOGUE = os.path.join(ROOT, "conformance", "assets", "bsc5-compact.csv.gz")
TIME_FRAMES = os.path.join(ROOT, "conformance", "tools", "time_frames_reference.py")

_spec = importlib.util.spec_from_file_location("star_fields_reference", MODULE)
sf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sf)

# Two records of the catalogue as distributed (V/50, 197-byte lines): HR 1 and HR 2491 (Sirius).
RECORD_1 = ("   1          BD+44 4550      3 36042          46           000001.1+444022000509.9+451345114.44-16.88"
            " 6.70  +0.07 +0.08         A1Vn               -0.012-0.018      -018      195  4.2  21.6AC   3")


def _close(a, b, tol=1e-9):
    if isinstance(a, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


@pytest.fixture(scope="module")
def catalogue():
    return sf.load_catalogue()


# ------------------------------------------------------------------------------------ rule 1: the catalogue asset


def test_the_fixture_is_pinned_by_its_digest():
    with open(CATALOGUE, "rb") as f:
        raw = f.read()
    assert hashlib.sha256(raw).hexdigest() == sf.CATALOGUE_DIGEST
    assert gzip.decompress(raw).startswith(b"HR,Name,RA,Dec,V,B-V,pmRA,pmDE,SpType\n")


def test_the_catalogue_loads_with_its_counts(catalogue):
    assert len(catalogue) == 9096
    assert sf.CATALOGUE_SKIPPED == 14
    assert catalogue[0].hr == 1 and catalogue[-1].hr == 9110
    assert sum(1 for s in catalogue if s.bv is None) == 310
    assert all(0.0 <= s.ra < 360.0 and -90.0 <= s.dec <= 90.0 for s in catalogue)
    assert all(s.hr == i + 1 or s.hr > i + 1 for i, s in enumerate(catalogue))


def test_a_raw_record_parses_to_the_compact_row():
    star = sf.parse_record(RECORD_1)
    assert star.hr == 1 and star.name == ""
    assert _close(star.ra, (0 + 5 / 60 + 9.9 / 3600) * 15.0) and _close(star.dec, 45 + 13 / 60 + 45 / 3600)
    assert star.vmag == 6.70 and star.bv == 0.07 and star.pm_ra == -0.012 and star.pm_dec == -0.018
    assert star.sptype == "A1Vn"
    assert sf.parse_record(RECORD_1[:75] + " " * 122) is None  # no J2000 position: skipped
    with pytest.raises(sf.StarError):
        sf.parse_record("not a record")


def test_a_wrong_digest_or_a_bad_row_is_rejected(tmp_path):
    with pytest.raises(sf.StarError):
        sf.load_catalogue(CATALOGUE, "0" * 64)
    with pytest.raises(sf.StarError):
        sf.load_catalogue(os.path.join(ROOT, "conformance", "assets", "horizons-vectors.json"), None)
    bad = tmp_path / "bad.csv.gz"
    with gzip.open(bad, "wt", encoding="ascii") as f:
        f.write("HR,Name,RA,Dec,V,B-V,pmRA,pmDE,SpType\n1,,400.0,0.0,1.0,0.0,0.0,0.0,A0\n")
    with pytest.raises(sf.StarError):
        sf.load_catalogue(str(bad), None)
    with gzip.open(bad, "wt", encoding="ascii") as f:
        f.write("HR,Name,RA,Dec,V,B-V,pmRA,pmDE,SpType,Extra\n1,,0.0,0.0,1.0,0.0,0.0,0.0,A0,1\n")
    with pytest.raises(sf.StarError):
        sf.load_catalogue(str(bad), None)


def test_the_compaction_of_raw_records_is_the_fixture_format(tmp_path):
    src = tmp_path / "catalog"
    src.write_text(RECORD_1 + "\n" + RECORD_1[:75] + " " * 122 + "\n", encoding="ascii")
    dst = tmp_path / "compact.csv.gz"
    count, skipped = sf.compact_catalogue(str(src), str(dst))
    assert (count, skipped) == (1, 1)
    text = gzip.decompress(dst.read_bytes()).decode("ascii")
    assert text == "HR,Name,RA,Dec,V,B-V,pmRA,pmDE,SpType\n1,,1.29125,45.22917,6.70,0.07,-0.012,-0.018,A1Vn\n"
    count2, _ = sf.compact_catalogue(str(src), str(tmp_path / "again.csv.gz"))
    assert (tmp_path / "again.csv.gz").read_bytes() == dst.read_bytes()  # deterministic bytes (no gzip mtime)


# ------------------------------------------------------------------------------------ rule 2: magnitude and flux


def test_five_magnitudes_are_a_flux_ratio_of_one_hundred():
    assert _close(sf.flux(0.0) / sf.flux(5.0), 100.0, 1e-12)
    assert _close(sf.flux(1.0) / sf.flux(2.0), 100.0 ** 0.2, 1e-12)
    assert _close(sf.flux(0.0), 1.0) and _close(sf.flux(0.0, zero=2.0), 2.0)
    assert _close(sf.magnitude(sf.flux(3.21)), 3.21, 1e-12)
    assert _close(sf.flux(-1.46) / sf.flux(6.5), 10 ** (0.4 * 7.96), 1e-9)
    with pytest.raises(sf.StarError):
        sf.magnitude(0.0)
    with pytest.raises(sf.StarError):
        sf.flux(0.0, zero=-1.0)


def test_the_brightest_stars_and_the_counts(catalogue):
    top = sf.brightest(catalogue, 3)
    assert [s.hr for s in top] == [2491, 2326, 5340]  # Sirius, Canopus, Arcturus
    assert top[0].vmag == -1.46
    assert sf.count_to(catalogue, 6.5) == 8404
    assert sf.count_to(catalogue, 6.0) == 5080
    assert sf.count_to(catalogue, -2.0) == 0
    with pytest.raises(sf.StarError):
        sf.brightest(catalogue, 0)


# ------------------------------------------------------------------------------------ rule 3: colour


def test_ballesteros_temperature():
    assert _close(sf.temperature(0.65), 4600.0 * (1 / (0.92 * 0.65 + 1.7) + 1 / (0.92 * 0.65 + 0.62)))
    assert 5700.0 < sf.temperature(0.65) < 5850.0  # the Sun
    assert _close(sf.temperature(0.0), 4600.0 * (1 / 1.7 + 1 / 0.62))
    assert sf.temperature(-0.2) > sf.temperature(0.0) > sf.temperature(1.0) > sf.temperature(2.0)
    assert sf.temperature(3.0) == sf.temperature(2.0) and sf.temperature(-1.0) == sf.temperature(-0.4)  # clamped
    with pytest.raises(sf.StarError):
        sf.temperature(float("nan"))


def test_the_cie_table_and_planck():
    assert len(sf.CMF) == 95 and sf.CMF[0][0] == 360 and sf.CMF[-1][0] == 830
    assert all(b[0] - a[0] == 5 for a, b in zip(sf.CMF, sf.CMF[1:]))
    assert _close(sf.CMF[44][1:], (0.916300, 0.870000, 0.001650001), 1e-9)  # 580 nm
    assert _close(sf.CMF[48][1:], (1.062200, 0.631000, 0.000800), 1e-9)  # 600 nm
    # Planck's law: the peak of the 5800 K spectrum is near Wien's 500 nm and the radiance grows with T.
    peak = max(range(300, 1000), key=lambda nm: sf.planck(nm, 5800.0))
    assert abs(peak - 2.897771955e6 / 5800.0) <= 1
    assert sf.planck(500, 6000.0) > sf.planck(500, 5000.0) > 0.0
    with pytest.raises(sf.StarError):
        sf.planck(500, 0.0)


def test_blackbody_chromaticity_and_colour():
    x, y = sf.chromaticity(sf.blackbody_xyz(5778.0))
    assert _close((x, y), (0.3255, 0.3359), 2e-3)  # the Planckian locus near the Sun's temperature
    x65, y65 = sf.chromaticity(sf.blackbody_xyz(6504.0))
    assert _close((x65, y65), (0.3135, 0.3237), 2e-3)
    sun = sf.colour(5778.0)
    assert _close(sun[0] * 0.2126 + sun[1] * 0.7152 + sun[2] * 0.0722, 1.0, 2e-3)  # Y = 1 (four-digit IEC matrix)
    assert sun[0] > sun[1] > sun[2] > 0.0
    hot = sf.colour(20000.0)
    assert hot[2] > hot[1] > hot[0] > 0.0
    cool = sf.colour(3200.0)
    assert cool[0] > 1.0 and cool[2] < 0.5
    for t in (sf.temperature(-0.4), sf.temperature(2.0), 4000.0, 10000.0):
        assert min(sf.colour(t)) >= 0.0  # the locus stays inside sRGB over the clamped range
    assert _close(sf.xyz_to_linear_srgb((0.95047, 1.0, 1.08883)), (1.0, 1.0, 1.0), 2e-3)  # D65 is white


def test_star_colour_uses_bv_then_spectral_class(catalogue):
    by_hr = {s.hr: s for s in catalogue}
    assert sf.star_temperature(by_hr[2061]) == sf.temperature(1.85)  # Betelgeuse
    assert sf.star_temperature(by_hr[7001]) == sf.temperature(0.0)  # Vega
    no_bv = next(s for s in catalogue if s.bv is None)
    assert sf.star_temperature(no_bv) == sf.temperature(sf.CLASS_BV[sf.spectral_class(no_bv.sptype)])
    assert sf.spectral_class("gG9") == "G" and sf.spectral_class("A1Vn") == "A" and sf.spectral_class("kA2hA5mA7V") == "A"
    assert sf.spectral_class("") == "" and sf.spectral_class("C5,4") == "" and sf.CLASS_BV[""] == 0.65
    assert sf.CLASS_BV["O"] < sf.CLASS_BV["B"] < sf.CLASS_BV["A"] < sf.CLASS_BV["F"] < sf.CLASS_BV["G"] < sf.CLASS_BV["K"] < sf.CLASS_BV["M"]


# ------------------------------------------------------------------------------------ rule 4: directions and proper motion


def test_directions_round_trip():
    for ra, dec in ((0.0, 0.0), (90.0, 0.0), (0.0, 90.0), (101.28708, -16.71611), (359.9, -89.9)):
        d = sf.direction(ra, dec)
        assert _close(sf.norm(d), 1.0)
        r, e = sf.radec(d)
        assert _close((r, e), (ra, dec), 1e-9)
    assert _close(sf.direction(0.0, 0.0), (1.0, 0.0, 0.0)) and _close(sf.direction(90.0, 0.0), (0.0, 1.0, 0.0))
    assert _close(sf.direction(0.0, 90.0), (0.0, 0.0, 1.0))
    with pytest.raises(sf.StarError):
        sf.direction(0.0, 91.0)
    with pytest.raises(sf.StarError):
        sf.radec((0.0, 0.0, 0.0))


def test_proper_motion_moves_the_star_by_its_rate(catalogue):
    by_hr = {s.hr: s for s in catalogue}
    equator = sf.Star(0, "", 10.0, 0.0, 5.0, 0.5, 1.0, -2.0, "G0")
    ra, dec = sf.radec(sf.moved(equator, 1.0))
    assert _close(dec, -2.0 / 3600.0, 1e-9) and _close(ra, 10.0 + 1.0 / 3600.0, 1e-9)
    ra60, dec60 = sf.radec(sf.moved(sf.Star(0, "", 10.0, 60.0, 5.0, 0.5, 1.0, 0.0, "G0"), 1.0))
    assert _close(ra60, 10.0 + 1.0 / 3600.0 / math.cos(math.radians(60.0)), 1e-7)  # pmRA is cos(Dec) dRA/dt
    assert sf.moved(equator, 0.0) == sf.direction(10.0, 0.0)
    g1830 = by_hr[4550]  # Groombridge 1830, the catalogue's largest proper motion
    assert _close(sf.total_motion(g1830), math.hypot(4.003, 5.813), 1e-9)
    assert sf.largest_motion(catalogue).hr == 4550
    moved = sf.moved(g1830, 100.0)
    assert _close(math.degrees(sf.angle(sf.direction(g1830.ra, g1830.dec), moved)), 100.0 * sf.total_motion(g1830) / 3600.0, 1e-6)
    with pytest.raises(sf.StarError):
        sf.moved(equator, sf.MAX_YEARS + 1.0)
    assert _close(sf.years_since_j2000(31557600.0), 1.0)


# ------------------------------------------------------------------------------------ rule 5: constellations


def test_herget_precession_is_small_and_reversible():
    ra, dec = sf.precess(101.28708, -16.71611, 2000.0, 1875.0)
    assert abs(ra - 101.28708) < 2.0 and abs(dec + 16.71611) < 0.2  # 125 years of general precession
    back = sf.precess(ra, dec, 1875.0, 2000.0)
    assert _close(back, (101.28708, -16.71611), 1e-6)
    assert sf.precess(10.0, 20.0, 2000.0, 2000.0) == (10.0, 20.0)
    # one Julian century of general precession in longitude is about 1.4 degrees; at RA 0, Dec 0 it shows in RA
    ra2, dec2 = sf.precess(0.0, 0.0, 1900.0, 2000.0)
    assert 1.2 < ra2 < 1.35 and 0.5 < dec2 < 0.6


def test_romans_examples_at_equinox_1950():
    for ra_h, dec, want in ((9.0, 65.0, "UMa"), (23.5, -20.0, "Aqr"), (5.12, 9.12, "Ori"), (9.4555, -19.9, "Hya"),
                            (12.8888, 22.0, "Com"), (15.6687, -12.1234, "Lib"), (19.0, -40.0, "CrA"),
                            (6.2222, -81.1234, "Men")):
        assert sf.constellation(ra_h * 15.0, dec, 1950.0) == want, (ra_h, dec)


def test_the_table_and_the_lookup_of_known_stars(catalogue):
    assert len(sf.BOUNDARIES) == 357
    assert sf.BOUNDARIES[0] == (0.0, 24.0, 88.0, "UMi") and sf.BOUNDARIES[-1][3] == "Oct"
    assert all(b[2] <= a[2] for a, b in zip(sf.BOUNDARIES, sf.BOUNDARIES[1:]))  # sorted by declination, descending
    assert len({row[3] for row in sf.BOUNDARIES}) == 88  # Serpens' two parts share the abbreviation Ser
    by_hr = {s.hr: s for s in catalogue}
    assert sf.star_constellation(by_hr[2491]) == "CMa" and sf.star_constellation(by_hr[424]) == "UMi"
    assert sf.star_constellation(by_hr[2061]) == "Ori" and sf.star_constellation(by_hr[7001]) == "Lyr"
    assert sf.constellation(0.0, -90.0) == "Oct" and sf.constellation(0.0, 90.0) == "UMi"
    assert sf.constellation(236.0, 7.0) == "Ser"  # Serpens Caput
    assert sf.constellation(272.0, -5.0) == "Ser"  # Serpens Cauda
    assert sf.constellation(360.0 - 1e-9, 0.0) == sf.constellation(0.0, 0.0)
    with pytest.raises(sf.StarError):
        sf.constellation(0.0, 95.0)


def test_named_stars_mostly_agree_with_the_lookup(catalogue):
    named, agree = sf.name_agreement(catalogue)
    assert named > 3000
    assert agree / named > 0.99  # the few differences are Delporte's 1930 boundaries against older names
    assert sf.name_constellation("  9Alp CMa") == "CMa" and sf.name_constellation("33    Psc") == "Psc"
    assert sf.name_constellation("") is None and sf.name_constellation("BD+44 4550") is None


# ------------------------------------------------------------------------------------ rule 6: the field and the seek check


def test_the_field_is_a_pure_function_of_its_inputs(catalogue):
    field = sf.star_field(catalogue, limit_magnitude=6.5, years=25.0, magnitude_zero=1.0)
    assert len(field) == 8404
    again = sf.star_field(catalogue, limit_magnitude=6.5, years=25.0, magnitude_zero=1.0)
    assert field == again
    assert field != sf.star_field(catalogue, limit_magnitude=6.5, years=26.0, magnitude_zero=1.0)
    first = field[0]
    assert set(first) == {"hr", "direction", "flux", "colour", "constellation"}
    assert _close(sf.norm(first["direction"]), 1.0)
    sirius = next(s for s in field if s["hr"] == 2491)
    assert _close(sirius["flux"], sf.flux(-1.46))
    assert sirius["constellation"] == "CMa"
    assert sf.seek_test(catalogue) is True
    with pytest.raises(sf.StarError):
        sf.star_field(catalogue, limit_magnitude=6.5, years=25.0, magnitude_zero=0.0)
    with pytest.raises(sf.StarError):
        sf.star_field(catalogue, limit_magnitude=float("inf"), years=0.0, magnitude_zero=1.0)


def test_the_field_respects_the_limit_and_the_star_bound(catalogue):
    assert len(sf.star_field(catalogue, limit_magnitude=1.0, years=0.0, magnitude_zero=1.0)) == sf.count_to(catalogue, 1.0)
    assert len(sf.star_field(catalogue, limit_magnitude=20.0, years=0.0, magnitude_zero=1.0)) == 9096
    assert sf.MAX_STARS >= 9110
    with pytest.raises(sf.StarError):
        sf.star_field(catalogue * 2, limit_magnitude=20.0, years=0.0, magnitude_zero=1.0)


def test_scene_directions_follow_the_time_frames_mapping():
    spec = importlib.util.spec_from_file_location("time_frames_reference", TIME_FRAMES)
    tf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tf)
    assert sf.SCENE_FROM_ICRF_AXES == tf.SCENE_FROM_ICRF_AXES
    assert sf.scene_direction((1.0, 2.0, 3.0)) == (1.0, -3.0, 2.0)
    assert _close(sf.norm(sf.scene_direction(sf.direction(10.0, 20.0))), 1.0)


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
    assert "SR-88" in draft
    for word in ("starField", "catalogue", "limitMagnitude", "magnitudeZero", "pointSize", "properMotion",
                 "constellations", "Bright Star Catalogue", "Hoffleit", "Ballesteros", "CIE 1931", "Planck",
                 "sRGB", "Roman", "Delporte", "Herget", "1875", "proper motion", "SF1", "V17", "seek check",
                 "star_fields_reference.py", "bsc5-compact.csv.gz", sf.CATALOGUE_DIGEST, "Hipparcos", "Gaia",
                 "SREP 14", "pixelsPerMeter"):
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
    s = sf.scope()
    got = eval(expr, s)
    want = eval(expected, s)
    assert got == want or sf._same(got, want), f"{name}: {got!r} != {want!r}"


def test_the_table_is_what_the_module_prints(draft, capsys):
    sf.main()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("|")]
    assert printed, "the module prints its table"
    for line in printed:
        assert line in draft, line
    assert len(printed) == len(_draft_rows())


def test_the_field_digest_is_over_six_decimals(catalogue):
    """The digest must be the same wherever sine, cosine and the built-in sum differ in their last bit (CI's
    macOS and 3.10 jobs): it hashes each value written with six decimals, so a 1e-12 change leaves it and a
    1e-5 change moves it."""
    field = sf.star_field(catalogue, 4.0, 25.0, 1.0)
    d, f, c = field[0]["direction"], field[0]["flux"], field[0]["colour"]
    nudged = [dict(field[0], direction=(d[0] + 1e-12, d[1] - 1e-12, d[2]), flux=f * (1.0 + 1e-13),
                   colour=(c[0] + 1e-12, c[1], c[2]))] + field[1:]
    moved = [dict(field[0], direction=(d[0] + 1e-5, d[1], d[2]))] + field[1:]
    assert sf._field_digest(nudged) == sf._field_digest(field)
    assert sf._field_digest(moved) != sf._field_digest(field)


def test_the_digest_path_uses_no_built_in_float_sum():
    """Python 3.12 changed the rounding of the built-in sum over floats; the matrix products on the digest's path
    add their three terms explicitly."""
    import inspect
    for fn in (sf.xyz_to_linear_srgb, sf.scene_direction, sf.precess):
        assert "sum(" not in inspect.getsource(fn), fn.__name__
