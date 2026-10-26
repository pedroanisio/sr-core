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


# ------------------------------------------------------------------------------------ the engine's three gaps (SR-88)


def test_non_finite_or_runaway_catalogue_values_are_rejected(tmp_path):
    bad = tmp_path / "bad.csv.gz"
    header = "HR,Name,RA,Dec,V,B-V,pmRA,pmDE,SpType\n"
    for row in ("1,,0.0,0.0,1.0,nan,0.0,0.0,A0", "1,,0.0,0.0,1.0,inf,0.0,0.0,A0", "1,,0.0,0.0,1.0,0.0,inf,0.0,A0",
                "1,,0.0,0.0,1.0,0.0,nan,0.0,A0", "1,,0.0,0.0,1.0,0.0,0.0,-inf,A0", "1,,0.0,0.0,1.0,0.0,0.0,nan,A0",
                "1,,0.0,0.0,1.0,0.0,100.5,0.0,A0", "1,,0.0,0.0,1.0,0.0,0.0,-1e300,A0", "1,,nan,0.0,1.0,0.0,0.0,0.0,A0",
                "1,,0.0,inf,1.0,0.0,0.0,0.0,A0", "1,,0.0,0.0,nan,0.0,0.0,0.0,A0"):
        with gzip.open(bad, "wt", encoding="ascii") as f:
            f.write(header + row + "\n")
        with pytest.raises(sf.StarError):
            sf.load_catalogue(str(bad), None)
    with gzip.open(bad, "wt", encoding="ascii") as f:
        f.write(header + "1,,0.0,0.0,1.0,,100.0,-100.0,A0\n")
    cat = sf.load_catalogue(str(bad), None)
    assert (cat[0].bv, cat[0].pm_ra, cat[0].pm_dec) == (None, 100.0, -100.0)
    assert sf.MAX_PROPER_MOTION == 100.0


def test_the_draft_settles_the_engine_vendoring_gaps(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("B−V empty or finite, pmRA and pmDE finite and at most 100 arcseconds per Julian year in magnitude",
                   "every catalogue is read as J2000",
                   "a written `epoch` is ignored with a warning",
                   "SF1–SF4, V17",
                   "b206136"):
        assert phrase in text, phrase
    assert "**SF5**" not in draft          # withdrawn; the History line records why


# ------------------------------------------------------------------------------------ rule 5's four points (SR-88)


def test_a_label_sits_at_the_centroid_of_every_star_the_lookup_gives_it(catalogue):
    ra, dec = sf.label_centroid(catalogue, "CMa", 0.0)
    assert sf.constellation(ra, dec) == "CMa"
    members = [s for s in catalogue if sf.star_constellation(s) == "CMa"]
    total = [0.0, 0.0, 0.0]
    for s in members:                                     # every member, whatever the magnitude limit
        d = sf.direction(s.ra, s.dec)
        total = [total[0] + d[0], total[1] + d[1], total[2] + d[2]]
    assert _close((ra, dec), sf.radec(tuple(total)), 1e-9)
    assert any(s.vmag > 6.5 for s in members)
    ra2, dec2 = sf.label_centroid(catalogue, "CMa", 100.0)   # moved to the frame's epoch by rule 4
    assert (ra2, dec2) != (ra, dec) and abs(ra2 - ra) < 0.01 and abs(dec2 - dec) < 0.01
    for abbreviation, years in (("Xyz", 0.0), ("CMa", float("nan")), ("CMa", 1e5)):
        with pytest.raises(sf.StarError):
            sf.label_centroid(catalogue, abbreviation, years)


def test_a_boundary_is_drawn_in_the_icrf_precessed_from_1875_only():
    d = sf.boundary_direction(81.875, -11.0)              # the middle of Orion's southern arc
    assert _close(d, sf.direction(*sf.precess(81.875, -11.0, 1875.0, 2000.0)))
    assert not _close(d, sf.direction(81.875, -11.0), 1e-4)
    ra, dec = sf.radec(d)
    assert sf.constellation(ra, dec - 0.01) == "Lep" and sf.constellation(ra, dec + 0.01) == "Ori"
    with pytest.raises(sf.StarError):
        sf.boundary_direction(0.0, 91.0)


def test_the_label_grey_follows_the_dome_gain():
    assert (sf.LABEL_HEIGHT_PX, sf.LABEL_GREY, sf.BOUNDARY_WIDTH_PX) == (14, 0.18, 1)
    assert sf.label_value(1.0, 0.0, (1.0, 1.0, 1.0)) == 0.18
    assert _close(sf.label_value(2.0, 1.0, (1.0, 0.5, 0.5)), 0.72)
    assert _close(sf.label_value(1.0, -1.0, (0.5, 0.25, 0.0)), 0.045)
    for bad in ((-1.0, 0.0, (1.0, 1.0, 1.0)), (1.0, float("nan"), (1.0, 1.0, 1.0)), (1.0, 0.0, (1.0, -1.0, 1.0)),
                (1.0, 0.0, (0.0, 0.0, 0.0)), (float("inf"), 0.0, (1.0, 1.0, 1.0))):
        with pytest.raises(sf.StarError):
            sf.label_value(*bad)


def test_the_draft_settles_rule_5(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("`label_centroid(catalogue, abbreviation, years)`", "whatever `limitMagnitude` says",
                   "`LABEL_HEIGHT_PX` (14)", "`LABEL_GREY` (0.18)", "`BOUNDARY_WIDTH_PX` (1)",
                   "`label_value(intensity, exposure, color)`", "`boundary_direction`",
                   "precessed from 1875 to J2000 and no further", "the locus at which `constellation` changes",
                   "`srep-<n>-stars-boundaries.xml`", "c64c4bf"):
        assert phrase in text, phrase
    assert "precessed from 1875 to the frame's epoch" not in text


# ------------------------------------------------------------------------------------ the kit (SR-88)

KIT = os.path.join(ROOT, "conformance", "tools", "star_fields_kit.py")
_kspec = importlib.util.spec_from_file_location("star_fields_kit", KIT)
sk = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(sk)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ALL_KEYS = sorted(k for keys in sk.DOCUMENTS.values() for k in keys)


def test_the_kit_camera_aims_and_projects():
    for ra, dec in ((90.0, 0.0), (101.28708, -16.71611), (279.23458, 38.78361), (178.245, 37.71861), (10.0, -80.0)):
        d = sf.scene_direction(sf.direction(ra, dec))
        yaw, pitch = sk.aim(d)
        w, h = sk.FRAME["stars-sirius"]
        assert _close(sk.project("stars-sirius", yaw, pitch, d), (w / 2.0, h / 2.0), 1e-6)
    yaw, pitch = sk.aim(sf.scene_direction(sf.direction(90.0, 0.0)))
    east = sk.project("stars-scale", yaw, pitch, sf.scene_direction(sf.direction(91.0, 0.0)))
    w, h = sk.FRAME["stars-scale"]
    assert _close(east, (w / 2.0 - sk.pixels_per_degree("stars-scale"), h / 2.0), 1e-6)   # right ascension grows leftward
    north = sk.project("stars-scale", yaw, pitch, sf.scene_direction(sf.direction(90.0, 1.0)))
    assert north[1] < h / 2.0 and _close(north[0], w / 2.0, 1e-6)                          # north is up the frame
    assert math.isnan(sk.project("stars-scale", yaw, pitch, sf.scene_direction(sf.direction(270.0, 0.0)))[0])


def test_the_kit_writes_the_cases_the_draft_names(tmp_path, catalogue):
    import xml.etree.ElementTree as ET
    paths = sk.write(str(tmp_path), catalogue)
    assert sorted(paths) == ALL_KEYS and len(ALL_KEYS) == 18
    assert all(name in sk.DOCUMENTS and sk.DOCUMENTS[name][0] == name for name in sk.NAMES)
    for key, path in paths.items():
        assert os.path.basename(path) == f"srep-0000-{key}.xml"
        root = ET.parse(path).getroot()
        assert root.tag == "scene" and root.get("version") == "1.8"
        asset = root.find("assets/catalogue")
        with open(os.path.join(tmp_path, asset.get("src")), "rb") as f:
            assert asset.get("digest") == "sha256:" + hashlib.sha256(f.read()).hexdigest()
        field = root.find("lights/light/starField")
        assert field.get("catalogue") == asset.get("id") and root.find("lights/light").get("type") == "dome"
        assert root.find("output").get("codec") == "exr-sequence"
        assert root.find("composition/camera").get("projection") is None
    docs = {k: ET.parse(p).getroot() for k, p in paths.items()}
    assert docs["stars-sirius"].find("lights/light/starField").get("limitMagnitude") == "-1"
    assert docs["stars-scale-4px"].find("lights/light/starField").get("pointSize") == "4"
    assert docs["stars-motion-2100"].find("lights/light/starField").get("epoch") == "2100"
    assert docs["stars-space"].find("space").get("timeScale") == "tt" and docs["stars-space"].find("space").get("epoch") == sk.SPACE_EPOCH_TT
    assert docs["stars-space"].find("lights/light/starField").get("epoch") is None
    assert all(docs[k].find("lights/light/starField").get("constellations") == "labels" for k in sk.LABELS)
    assert docs["stars-labels-limit3"].find("lights/light/starField").get("limitMagnitude") == "3"
    assert docs["stars-boundaries-none"].find("lights/light/starField").get("constellations") == "none"
    assert docs["stars-sky"].find("lights/light").get("sky") == "physical" and docs["stars-sky-none"].find("lights/light").get("sky") is None
    assert docs["stars-sky-noon"].find("lights/light").get("date") == sk.SKY_NOON
    assert docs["stars-seek"].find("space").get("rate") == f"{sk.SEEK_RATE:.0f}" and docs["stars-seek"].find("project").get("fps") == "24"
    assert sk.synthetic_catalogues() == sk.synthetic_catalogues()       # deterministic bytes
    with gzip.open(os.path.join(tmp_path, "assets", "stars-colour.csv.gz"), "rt") as f:
        rows = f.read().splitlines()
    assert rows[0] == ",".join(sf.COLUMNS) and len(rows) == 4 and rows[2].split(",")[5] == "0.65"


def test_the_kit_expectations_come_from_the_reference(catalogue):
    exp = sk.expectations(catalogue)
    sirius = next(s for s in catalogue if s.hr == sk.SIRIUS)
    assert exp["stars-sirius"]["flux"] == sf.flux(sirius.vmag, sk.SIRIUS_ZERO) and exp["stars-sirius"]["centre"] == (160.0, 120.0)
    assert _close(exp["stars-scale"]["ratio"], 100.0, 1e-9)
    assert abs(exp["stars-scale"]["at"][0][0] - exp["stars-scale"]["at"][1][0] - sk.pixels_per_degree("stars-scale")) < 0.01
    assert exp["stars-colour"]["colours"] == [sf.colour(sf.temperature(bv)) for bv in sk.COLOUR_BV]
    assert abs(exp["stars-motion"]["shift_deg"] - 0.196) < 0.0005                   # the draft's century of HR 4550
    assert _close(exp["stars-motion"]["at"][0.0], (320.0, 240.0), 1e-6)
    assert abs(exp["stars-motion"]["shift_px"] - 0.196 * sk.pixels_per_degree("stars-motion")) < 0.1
    for key in sk.LABELS:
        assert _close(exp["stars-labels"]["centres"][key], (240.0, 240.0), 1e-6)
    a = sk.ps.atmosphere()
    vega = next(s for s in catalogue if s.hr == sk.VEGA)
    e = math.radians(vega.dec)
    assert exp["stars-sky"]["transmittance"] == sk.ps.transmittance(a, sk.ps._ground_observer(a), (math.cos(e), 0.0, math.sin(e)))
    assert 0.6 < exp["stars-sky"]["transmittance"][2] < exp["stars-sky"]["transmittance"][0] < 0.95


def test_exr_frames_round_trip(tmp_path):
    rng = np.random.default_rng(7)
    rgb = rng.random((5, 9, 3)).astype(np.float32) * 3.0
    path = str(tmp_path / "f.exr")
    sk.write_exr(path, rgb)
    back = sk.read_exr(path)
    assert back.shape == (5, 9, 3) and np.array_equal(back, rgb.astype(np.float64))
    with open(path, "r+b") as f:
        f.seek(0)
        f.write(b"\0\0\0\0")
    with pytest.raises(ValueError):
        sk.read_exr(path)


def _splat(frame, at, rgb):
    """Spread rgb over the four pixels about a continuous position so the weighted centroid is exactly `at`."""
    x, y = at[0] - 0.5, at[1] - 0.5
    i, j = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - i, y - j
    for di, wx in ((0, 1.0 - fx), (1, fx)):
        for dj, wy in ((0, 1.0 - fy), (1, fy)):
            frame[j + dj, i + di] += np.asarray(rgb) * wx * wy


def _ink_box(frame, centre, size=(30, 14), value=sk.sf.LABEL_GREY):
    cx, cy = centre
    x0, y0 = int(round(cx - size[0] / 2.0)), int(round(cy - size[1] / 2.0))
    frame[y0:y0 + size[1], x0:x0 + size[0]] = value


def _frames(exp, transmittance=None):
    """Synthetic frames of every document from the expectations (what a correct engine renders)."""
    f = {}

    def blank(name):
        w, h = sk.FRAME[name]
        return np.zeros((h, w, 3))
    e = exp["stars-sirius"]
    f["stars-sirius"] = blank("stars-sirius")
    _splat(f["stars-sirius"], e["centre"], (e["flux"],) * 3)
    for key in ("stars-scale", "stars-scale-4px"):
        f[key] = blank("stars-scale")
        for at, flux in zip(exp["stars-scale"]["at"], (1.0, 0.01)):
            _splat(f[key], at, (flux,) * 3)
    f["stars-colour"] = blank("stars-colour")
    for at, colour in zip(exp["stars-colour"]["at"], exp["stars-colour"]["colours"]):
        _splat(f["stars-colour"], at, colour)
    for key, years in (("stars-motion", 0.0), ("stars-motion-2100", sk.MOTION_YEARS)):
        f[key] = blank("stars-motion")
        _splat(f[key], exp["stars-motion"]["at"][years], (0.002,) * 3)
        _splat(f[key], (100.0, 100.0), (0.001,) * 3)                     # another star that does not move
    f["stars-space"] = f["stars-motion-2100"].copy()
    for key in sk.LABELS:
        f[key] = blank("stars-labels")
        _ink_box(f[key], exp["stars-labels"]["centres"][key])
    _splat(f["stars-labels-limit3"], (100.0, 300.0), (0.004, 0.005, 0.006))  # a faint star beside the label
    for key in ("stars-boundaries", "stars-boundaries-2100", "stars-boundaries-none"):
        f[key] = blank("stars-boundaries")
        if key != "stars-boundaries-none":
            w, h = sk.FRAME["stars-boundaries"]
            f[key][:, w // 2 - 1] = sk.sf.LABEL_GREY
    t = transmittance or exp["stars-sky"]["transmittance"]
    w, h = sk.FRAME["stars-sky"]
    star = tuple(sk.SKY_ZERO * 0.97 * c for c in (1.0, 1.0, 1.0))
    f["stars-sky-none"] = blank("stars-sky")
    _splat(f["stars-sky-none"], (w / 2.0, h / 2.0), star)
    f["stars-sky"] = blank("stars-sky")
    _splat(f["stars-sky"], (w / 2.0, h / 2.0), tuple(s * k for s, k in zip(star, t)))
    f["stars-sky-noon"] = np.full((h, w, 3), 0.03)
    _splat(f["stars-sky-noon"], (w / 2.0, h / 2.0), tuple(s * k for s, k in zip(star, t)))
    seek = np.zeros((sk.FRAME["stars-seek"][1], sk.FRAME["stars-seek"][0], 4), np.uint8)
    seek[10:12, 20:22] = 255
    f["seek-alone"], f["seek-played"] = seek.astype(np.float64), seek.astype(np.float64)
    return f


def test_the_kit_measures_each_case(catalogue):
    exp = sk.expectations(catalogue)
    frames = _frames(exp)
    for name in sk.NAMES:
        r = sk.measure(name, frames, exp)
        assert r["pass"], (name, r)
    bad = dict(frames)
    bad["stars-sirius"] = frames["stars-sirius"] * 0.98
    assert not sk.measure("stars-sirius", bad, exp)["pass"]
    bad["stars-scale-4px"] = frames["stars-scale-4px"] * 1.02
    assert not sk.measure("stars-scale", bad, exp)["pass"]
    bad["stars-colour"] = frames["stars-colour"] * np.array([1.0, 1.0, 1.05])
    assert not sk.measure("stars-colour", bad, exp)["pass"]
    bad["stars-motion-2100"] = np.roll(frames["stars-motion-2100"], 1, axis=1)
    assert not sk.measure("stars-motion", bad, exp)["pass"]
    assert not sk.measure("stars-space", bad, exp)["pass"]
    bad["stars-labels-ori"] = np.roll(frames["stars-labels-ori"], 40, axis=0)
    assert not sk.measure("stars-labels", bad, exp)["pass"]
    bad["stars-boundaries-none"] = frames["stars-boundaries"]
    assert not sk.measure("stars-boundaries", bad, exp)["pass"]
    assert not sk.measure("stars-sky", dict(frames, **{"stars-sky": frames["stars-sky-none"]}), exp)["pass"]
    assert not sk.measure("stars-sky", dict(frames, **{"stars-sky-noon": frames["stars-sky-noon"] + frames["stars-sky-none"] * 400}), exp)["pass"]
    bad["seek-played"] = np.roll(frames["seek-played"], 1, axis=1)
    assert not sk.measure("stars-seek", bad, exp)["pass"]
    with pytest.raises(ValueError):
        sk.measure("stars-nothing", frames, exp)


def _fake_engine(frames, refuse=()):
    """An exec that writes the synthetic frame of each document the kit encodes or renders, and refuses the named
    documents with the given code."""
    def exec(cmd, capture_output, text):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        doc = cmd[2]
        key = os.path.basename(doc)[len("srep-0000-"):-len(".xml")]
        if key in refuse:
            R.returncode, R.stderr = 1, "error[%s] (dome): refused\n" % refuse[key]
            return R
        if cmd[1] == "encode":
            out_dir = cmd[cmd.index("--out-dir") + 1]
            os.makedirs(os.path.join(out_dir, "out"), exist_ok=True)
            sk.write_exr(os.path.join(out_dir, "out", f"{key}_0000.exr"), frames[key])
            return R
        assert cmd[1] == "render" and key == "stars-seek"
        out = cmd[cmd.index("-o") + 1]
        if "-f" in cmd:
            targets = [out]
        else:
            last = int(cmd[cmd.index("--frames") + 1].split("..=")[1])
            targets = [out % f for f in range(last + 1)]
        img = Image.fromarray(frames["seek-alone"].astype(np.uint8), "RGBA")
        for path in targets:
            img.save(path)
        return R
    return exec


def test_the_kit_runs_an_engine_and_reports_every_case(tmp_path, catalogue):
    exp = sk.expectations(catalogue)
    frames = _frames(exp)
    report = sk.run("engine", str(tmp_path / "ok"), exec=_fake_engine(frames), catalogue=catalogue)
    assert list(report) == sk.NAMES and all(r["pass"] for r in report.values()), report
    assert os.path.exists(tmp_path / "ok" / "stars-seek-seq-0600.png")
    refused = sk.run("engine", str(tmp_path / "refused"), exec=_fake_engine(frames, refuse={"stars-sky": "S06", "stars-seek": "S01"}),
                     catalogue=catalogue)
    assert not refused["stars-sky"]["pass"] and "S06" in refused["stars-sky"]["error"]
    assert not refused["stars-seek"]["pass"] and "S01" in refused["stars-seek"]["error"]
    assert sum(r["pass"] for r in refused.values()) == 7
    text = sk.table(report)
    assert text.splitlines()[0] == "| Case | Measured | Pass |" and "| stars-sirius |" in text and text.count("| yes |") == 9


def test_the_draft_describes_the_kit(draft):
    text = re.sub(r"\n +", " ", draft)
    for phrase in ("`conformance/tools/star_fields_kit.py`", "`scene-render encode`", "exr-sequence", "clips at 1.0",
                   "`stars-scale-4px`", "`stars-motion-2100`", "`stars-labels-limit3`", "`stars-boundaries-none`",
                   "`stars-sky-noon`", "`stars-sky-none`", "yaw and pitch", "`aim`", "`project`", "ced8ff0", "SR-86"):
        assert phrase in text, phrase


KIT_ROW = re.compile(r"^\| `srep-<n>-stars-([a-z]+)\.xml` \| (?:[^|]|\\\|)* \| ([^|]*) \|$")
ENGINE_COMMIT = "ced8ff0"


def _kit_rows(draft):
    return {m.group(1): m.group(2) for m in (KIT_ROW.match(line) for line in draft.splitlines()) if m}


def test_the_draft_records_every_kit_case_measured_on_one_engine_commit(draft):
    rows = _kit_rows(draft)
    assert sorted(rows) == sorted(name[len("stars-"):] for name in sk.NAMES)
    prefix = f"measured on scene-render feat/sr-67-fields {ENGINE_COMMIT} (0.8.0, llvmpipe): "
    for name, status in rows.items():
        assert status.startswith(prefix) or (name == "sky" and ENGINE_COMMIT in status), (name, status)
        if name == "sky":
            assert "S06" in status and "SR-86" in status and status.endswith("; not measured"), status
        else:
            assert status.endswith("; pass"), (name, status)
    assert "0.7671" in rows["sirius"] and "100.46" in rows["scale"] and "31.40" in rows["motion"] and "0.017°" in rows["labels"]
