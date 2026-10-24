"""Reference implementation of the draft SREP "Add star fields from the Bright Star Catalogue"
(srep/srep-0000-star-fields.md; SP2 of SREP 12, SRC-45).

Standard library only. The module gives:

- the catalogue asset: the Yale Bright Star Catalogue, 5th revised edition (Hoffleit and Warren 1991, CDS V/50)
  compacted to the columns a star field needs and pinned by its sha256 digest; the compaction is here too, so the
  fixture can be rebuilt from the distributed file byte for byte;
- magnitude to flux (five magnitudes are a factor of one hundred);
- B-V to temperature by Ballesteros (2012), the Planck spectrum against the CIE 1931 2-degree colour-matching
  functions, XYZ to linear sRGB normalised to unit luminance;
- ICRF directions with proper motion from J2000, and the scene mapping of the time-frames draft;
- the constellation of a position by Roman's (1987) table of Delporte's boundaries with Herget's precession
  to equinox 1875;
- the star field as a pure function of catalogue, limit, epoch and zero point, and `main()` prints the
  draft's numeric table.
"""
import csv
import gzip
import hashlib
import io
import math
import os
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE_PATH = os.path.join(HERE, "..", "assets", "bsc5-compact.csv.gz")
CATALOGUE_DIGEST = "cd18b1c9b8c009d922edfed020ba718aa14a577416fb625bf01ddd9cbdaab617"
CATALOGUE_SKIPPED = 14  # records of the 9110 without a J2000 position (novae and non-stellar entries)
COLUMNS = ("HR", "Name", "RA", "Dec", "V", "B-V", "pmRA", "pmDE", "SpType")
MAX_STARS = 16384
MAX_YEARS = 10000.0
JULIAN_YEAR_S = 31557600.0
BV_RANGE = (-0.4, 2.0)
SCENE_FROM_ICRF_AXES = ((1, 0, 0), (0, 0, -1), (0, 1, 0))  # scene (x, y, z) = ICRF (x, -z, y), as in the time-frames draft
# the B-V a spectral class stands in for when the catalogue has no colour; "" is every other case (the Sun's colour)
CLASS_BV = {"O": -0.3, "B": -0.2, "A": 0.0, "F": 0.4, "G": 0.65, "K": 1.0, "M": 1.5, "": 0.65}
# IEC 61966-2-1 XYZ (D65) to linear sRGB
XYZ_TO_SRGB = ((3.2406, -1.5372, -0.4986), (-0.9689, 1.8758, 0.0415), (0.0557, -0.2040, 1.0570))
PLANCK_C1 = 2.0 * 6.62607015e-34 * 299792458.0 ** 2  # 2 h c^2, W m^2 sr^-1
PLANCK_C2 = 6.62607015e-34 * 299792458.0 / 1.380649e-23  # h c / k, m K

Star = namedtuple("Star", "hr name ra dec vmag bv pm_ra pm_dec sptype")


class StarError(ValueError):
    """A document value, catalogue or record the draft rejects."""


# ------------------------------------------------------------------------------------ vectors


def norm(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(a):
    n = norm(a)
    if n == 0.0:
        raise StarError("a zero vector has no direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def angle(a, b):
    """Angle in radians between two directions (stable for small angles)."""
    c = _unit(a)
    d = _unit(b)
    cross = (c[1] * d[2] - c[2] * d[1], c[2] * d[0] - c[0] * d[2], c[0] * d[1] - c[1] * d[0])
    return math.atan2(norm(cross), _dot(c, d))


# ------------------------------------------------------------------------------------ rule 1: the catalogue asset


def _field(line, start, end):
    return line[start - 1:end].strip()


def _float(text):
    return float(text) if text else None


def parse_record(line):
    """One 197-byte record of V/50 catalog -> Star, or None when the record has no J2000 position."""
    line = line.rstrip("\r\n")
    if len(line) < 147 or not _field(line, 1, 4).isdigit():
        raise StarError("not a Bright Star Catalogue record")
    hr = int(_field(line, 1, 4))
    rah, ram, ras = _field(line, 76, 77), _field(line, 78, 79), _field(line, 80, 83)
    if not (rah and ram and ras):
        return None
    sign = -1.0 if _field(line, 84, 84) == "-" else 1.0
    ded, dem, des = _field(line, 85, 86), _field(line, 87, 88), _field(line, 89, 90)
    ra = (int(rah) + int(ram) / 60.0 + float(ras) / 3600.0) * 15.0
    dec = sign * (int(ded) + int(dem) / 60.0 + int(des) / 3600.0)
    vmag = _float(_field(line, 103, 107))
    if vmag is None:
        return None
    bv = _float(_field(line, 110, 114))
    pm_ra = _float(_field(line, 149, 154)) or 0.0
    pm_dec = _float(_field(line, 155, 160)) or 0.0
    return Star(hr, _field(line, 5, 14), ra, dec, vmag, bv, pm_ra, pm_dec, _field(line, 128, 147))


def _row(star):
    """One CSV row; a field holding a comma (a carbon star's type such as C5,4) is quoted as csv does."""
    bv = "" if star.bv is None else f"{star.bv:.2f}"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow([star.hr, star.name, f"{star.ra:.5f}", f"{star.dec:.5f}",
                                                   f"{star.vmag:.2f}", bv, f"{star.pm_ra:.3f}", f"{star.pm_dec:.3f}",
                                                   star.sptype])
    return out.getvalue()


def compact_catalogue(src, dst):
    """Write the compact gzipped CSV from the distributed catalogue; returns (stars written, records skipped).
    The gzip member carries no name and a zero mtime, so the bytes depend on the records alone."""
    out = io.StringIO()
    out.write(",".join(COLUMNS) + "\n")
    count = skipped = 0
    with open(src, encoding="ascii", errors="strict") as f:
        for line in f:
            if not line.strip():
                continue
            star = parse_record(line)
            if star is None:
                skipped += 1
                continue
            out.write(_row(star))
            count += 1
    raw = out.getvalue().encode("ascii")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(raw)
    with open(dst, "wb") as f:
        f.write(buf.getvalue())
    return count, skipped


def _parse_compact(text):
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if tuple(header or ()) != COLUMNS:
        raise StarError(f"catalogue columns {header} are not {list(COLUMNS)}")
    stars = []
    last = 0
    for row in reader:
        if len(row) != len(COLUMNS):
            raise StarError(f"catalogue row {len(stars) + 1} has {len(row)} fields")
        try:
            hr = int(row[0])
            ra, dec, vmag = float(row[2]), float(row[3]), float(row[4])
            bv = float(row[5]) if row[5] else None
            pm_ra, pm_dec = float(row[6]), float(row[7])
        except ValueError as e:
            raise StarError(f"catalogue row {len(stars) + 1}: {e}") from None
        if hr <= last or not (0.0 <= ra < 360.0) or not (-90.0 <= dec <= 90.0) or not (-5.0 <= vmag <= 30.0):
            raise StarError(f"catalogue row {len(stars) + 1}: HR {hr} out of order or out of range")
        if len(stars) >= MAX_STARS:
            raise StarError(f"catalogue has more than {MAX_STARS} stars")
        stars.append(Star(hr, row[1], ra, dec, vmag, bv, pm_ra, pm_dec, row[8]))
        last = hr
    if not stars:
        raise StarError("catalogue is empty")
    return stars


def load_catalogue(path=CATALOGUE_PATH, digest=CATALOGUE_DIGEST):
    """Verify the asset's sha256 (None skips the pin) and parse it; every failure is a StarError."""
    with open(path, "rb") as f:
        raw = f.read()
    if digest is not None:
        want = digest[7:] if digest.startswith("sha256:") else digest
        got = hashlib.sha256(raw).hexdigest()
        if got != want:
            raise StarError(f"catalogue digest {got} is not the pinned {want}")
    try:
        text = gzip.decompress(raw).decode("ascii")
    except (OSError, EOFError, UnicodeDecodeError) as e:
        raise StarError(f"catalogue is not a gzipped ASCII CSV: {e}") from None
    return _parse_compact(text)


# ------------------------------------------------------------------------------------ rule 2: magnitude and flux


def flux(m, zero=1.0):
    """Flux of a star of magnitude m, with `zero` the flux of magnitude 0: zero * 10^(-0.4 m)."""
    if not (zero > 0.0) or not math.isfinite(m):
        raise StarError("the zero point is positive and the magnitude finite")
    return zero * 10.0 ** (-0.4 * m)


def magnitude(f, zero=1.0):
    if not (f > 0.0) or not (zero > 0.0):
        raise StarError("a magnitude needs a positive flux")
    return -2.5 * math.log10(f / zero)


def brightest(catalogue, n):
    if not isinstance(n, int) or n < 1:
        raise StarError("n is a positive count")
    return sorted(catalogue, key=lambda s: (s.vmag, s.hr))[:n]


def count_to(catalogue, limit_magnitude):
    return sum(1 for s in catalogue if s.vmag <= limit_magnitude)


# ------------------------------------------------------------------------------------ rule 3: colour

# CIE 1931 2-degree colour-matching functions, 360-830 nm at 5 nm (CVRL, cvrl.ucl.ac.uk, ciexyz31.csv): (nm, xbar, ybar, zbar).
CMF = (
    (360, 0.0001299, 3.917e-06, 0.0006061),
    (365, 0.0002321, 6.965e-06, 0.001086),
    (370, 0.0004149, 1.239e-05, 0.001946),
    (375, 0.0007416, 2.202e-05, 0.003486),
    (380, 0.001368, 3.9e-05, 0.006450001),
    (385, 0.002236, 6.4e-05, 0.01054999),
    (390, 0.004243, 0.00012, 0.02005001),
    (395, 0.00765, 0.000217, 0.03621),
    (400, 0.01431, 0.000396, 0.06785001),
    (405, 0.02319, 0.00064, 0.1102),
    (410, 0.04351, 0.00121, 0.2074),
    (415, 0.07763, 0.00218, 0.3713),
    (420, 0.13438, 0.004, 0.6456),
    (425, 0.21477, 0.0073, 1.0390501),
    (430, 0.2839, 0.0116, 1.3856),
    (435, 0.3285, 0.01684, 1.62296),
    (440, 0.34828, 0.023, 1.74706),
    (445, 0.34806, 0.0298, 1.7826),
    (450, 0.3362, 0.038, 1.77211),
    (455, 0.3187, 0.048, 1.7441),
    (460, 0.2908, 0.06, 1.6692),
    (465, 0.2511, 0.0739, 1.5281),
    (470, 0.19536, 0.09098, 1.28764),
    (475, 0.1421, 0.1126, 1.0419),
    (480, 0.09564, 0.13902, 0.8129501),
    (485, 0.05795001, 0.1693, 0.6162),
    (490, 0.03201, 0.20802, 0.46518),
    (495, 0.0147, 0.2586, 0.3533),
    (500, 0.0049, 0.323, 0.272),
    (505, 0.0024, 0.4073, 0.2123),
    (510, 0.0093, 0.503, 0.1582),
    (515, 0.0291, 0.6082, 0.1117),
    (520, 0.06327, 0.71, 0.07824999),
    (525, 0.1096, 0.7932, 0.05725001),
    (530, 0.1655, 0.862, 0.04216),
    (535, 0.2257499, 0.9148501, 0.02984),
    (540, 0.2904, 0.954, 0.0203),
    (545, 0.3597, 0.9803, 0.0134),
    (550, 0.4334499, 0.9949501, 0.008749999),
    (555, 0.5120501, 1, 0.005749999),
    (560, 0.5945, 0.995, 0.0039),
    (565, 0.6784, 0.9786, 0.002749999),
    (570, 0.7621, 0.952, 0.0021),
    (575, 0.8425, 0.9154, 0.0018),
    (580, 0.9163, 0.87, 0.001650001),
    (585, 0.9786, 0.8163, 0.0014),
    (590, 1.0263, 0.757, 0.0011),
    (595, 1.0567, 0.6949, 0.001),
    (600, 1.0622, 0.631, 0.0008),
    (605, 1.0456, 0.5668, 0.0006),
    (610, 1.0026, 0.503, 0.00034),
    (615, 0.9384, 0.4412, 0.00024),
    (620, 0.8544499, 0.381, 0.00019),
    (625, 0.7514, 0.321, 0.0001),
    (630, 0.6424, 0.265, 4.999999e-05),
    (635, 0.5419, 0.217, 3e-05),
    (640, 0.4479, 0.175, 2e-05),
    (645, 0.3608, 0.1382, 1e-05),
    (650, 0.2835, 0.107, 0),
    (655, 0.2187, 0.0816, 0),
    (660, 0.1649, 0.061, 0),
    (665, 0.1212, 0.04458, 0),
    (670, 0.0874, 0.032, 0),
    (675, 0.0636, 0.0232, 0),
    (680, 0.04677, 0.017, 0),
    (685, 0.0329, 0.01192, 0),
    (690, 0.0227, 0.00821, 0),
    (695, 0.01584, 0.005723, 0),
    (700, 0.01135916, 0.004102, 0),
    (705, 0.008110916, 0.002929, 0),
    (710, 0.005790346, 0.002091, 0),
    (715, 0.004109457, 0.001484, 0),
    (720, 0.002899327, 0.001047, 0),
    (725, 0.00204919, 0.00074, 0),
    (730, 0.001439971, 0.00052, 0),
    (735, 0.0009999493, 0.0003611, 0),
    (740, 0.0006900786, 0.0002492, 0),
    (745, 0.0004760213, 0.0001719, 0),
    (750, 0.0003323011, 0.00012, 0),
    (755, 0.0002348261, 8.48e-05, 0),
    (760, 0.0001661505, 6e-05, 0),
    (765, 0.000117413, 4.24e-05, 0),
    (770, 8.307527e-05, 3e-05, 0),
    (775, 5.870652e-05, 2.12e-05, 0),
    (780, 4.150994e-05, 1.499e-05, 0),
    (785, 2.935326e-05, 1.06e-05, 0),
    (790, 2.067383e-05, 7.4657e-06, 0),
    (795, 1.455977e-05, 5.2578e-06, 0),
    (800, 1.025398e-05, 3.7029e-06, 0),
    (805, 7.221456e-06, 2.6078e-06, 0),
    (810, 5.085868e-06, 1.8366e-06, 0),
    (815, 3.581652e-06, 1.2934e-06, 0),
    (820, 2.522525e-06, 9.1093e-07, 0),
    (825, 1.776509e-06, 6.4153e-07, 0),
    (830, 1.251141e-06, 4.5181e-07, 0),
)

# Roman (1987, VI/42 data.dat): the southern boundaries of the constellations at equinox 1875, sorted by declination
# then by the eastern end of each arc: (RA_low hours, RA_up hours, Dec_low degrees, constellation).
BOUNDARIES = (
    (0, 24, 88, 'UMi'),
    (8, 14.5, 86.5, 'UMi'),
    (21, 23, 86.1667, 'UMi'),
    (18, 21, 86, 'UMi'),
    (0, 8, 85, 'Cep'),
    (9.1667, 10.6667, 82, 'Cam'),
    (0, 5, 80, 'Cep'),
    (10.6667, 14.5, 80, 'Cam'),
    (17.5, 18, 80, 'UMi'),
    (20.1667, 21, 80, 'Dra'),
    (0, 3.5083, 77, 'Cep'),
    (11.5, 13.5833, 77, 'Cam'),
    (16.5333, 17.5, 75, 'UMi'),
    (20.1667, 20.6667, 75, 'Cep'),
    (7.9667, 9.1667, 73.5, 'Cam'),
    (9.1667, 11.3333, 73.5, 'Dra'),
    (13, 16.5333, 70, 'UMi'),
    (3.1, 3.4167, 68, 'Cas'),
    (20.4167, 20.6667, 67, 'Dra'),
    (11.3333, 12, 66.5, 'Dra'),
    (0, 0.3333, 66, 'Cep'),
    (14, 15.6667, 66, 'UMi'),
    (23.5833, 24, 66, 'Cep'),
    (12, 13.5, 64, 'Dra'),
    (13.5, 14.4167, 63, 'Dra'),
    (23.1667, 23.5833, 63, 'Cep'),
    (6.1, 7, 62, 'Cam'),
    (20, 20.4167, 61.5, 'Dra'),
    (20.5367, 20.6, 60.9167, 'Cep'),
    (7, 7.9667, 60, 'Cam'),
    (7.9667, 8.4167, 60, 'UMa'),
    (19.7667, 20, 59.5, 'Dra'),
    (20, 20.5367, 59.5, 'Cep'),
    (22.8667, 23.1667, 59.0833, 'Cep'),
    (0, 2.4333, 58.5, 'Cas'),
    (19.4167, 19.7667, 58, 'Dra'),
    (1.7, 1.9083, 57.5, 'Cas'),
    (2.4333, 3.1, 57, 'Cas'),
    (3.1, 3.1667, 57, 'Cam'),
    (22.3167, 22.8667, 56.25, 'Cep'),
    (5, 6.1, 56, 'Cam'),
    (14.0333, 14.4167, 55.5, 'UMa'),
    (14.4167, 19.4167, 55.5, 'Dra'),
    (3.1667, 3.3333, 55, 'Cam'),
    (22.1333, 22.3167, 55, 'Cep'),
    (20.6, 21.9667, 54.8333, 'Cep'),
    (0, 1.7, 54, 'Cas'),
    (6.1, 6.5, 54, 'Lyn'),
    (12.0833, 13.5, 53, 'UMa'),
    (15.25, 15.75, 53, 'Dra'),
    (21.9667, 22.1333, 52.75, 'Cep'),
    (3.3333, 5, 52.5, 'Cam'),
    (22.8667, 23.3333, 52.5, 'Cas'),
    (15.75, 17, 51.5, 'Dra'),
    (2.0417, 2.5167, 50.5, 'Per'),
    (17, 18.2333, 50.5, 'Dra'),
    (0, 1.3667, 50, 'Cas'),
    (1.3667, 1.6667, 50, 'Per'),
    (6.5, 6.8, 50, 'Lyn'),
    (23.3333, 24, 50, 'Cas'),
    (13.5, 14.0333, 48.5, 'UMa'),
    (0, 1.1167, 48, 'Cas'),
    (23.5833, 24, 48, 'Cas'),
    (18.175, 18.2333, 47.5, 'Her'),
    (18.2333, 19.0833, 47.5, 'Dra'),
    (19.0833, 19.1667, 47.5, 'Cyg'),
    (1.6667, 2.0417, 47, 'Per'),
    (8.4167, 9.1667, 47, 'UMa'),
    (0.1667, 0.8667, 46, 'Cas'),
    (12, 12.0833, 45, 'UMa'),
    (6.8, 7.3667, 44.5, 'Lyn'),
    (21.9083, 21.9667, 44, 'Cyg'),
    (21.875, 21.9083, 43.75, 'Cyg'),
    (19.1667, 19.4, 43.5, 'Cyg'),
    (9.1667, 10.1667, 42, 'UMa'),
    (10.1667, 10.7833, 40, 'UMa'),
    (15.4333, 15.75, 40, 'Boo'),
    (15.75, 16.3333, 40, 'Her'),
    (9.25, 9.5833, 39.75, 'Lyn'),
    (0, 2.5167, 36.75, 'And'),
    (2.5167, 2.5667, 36.75, 'Per'),
    (19.3583, 19.4, 36.5, 'Lyr'),
    (4.5, 4.6917, 36, 'Per'),
    (21.7333, 21.875, 36, 'Cyg'),
    (21.875, 22, 36, 'Lac'),
    (6.5333, 7.3667, 35.5, 'Aur'),
    (7.3667, 7.75, 35.5, 'Lyn'),
    (0, 2, 35, 'And'),
    (22, 22.8167, 35, 'Lac'),
    (22.8167, 22.8667, 34.5, 'Lac'),
    (22.8667, 23.5, 34.5, 'And'),
    (2.5667, 2.7167, 34, 'Per'),
    (10.7833, 11, 34, 'UMa'),
    (12, 12.3333, 34, 'CVn'),
    (7.75, 9.25, 33.5, 'Lyn'),
    (9.25, 9.8833, 33.5, 'LMi'),
    (0.7167, 1.4083, 33, 'And'),
    (15.1833, 15.4333, 33, 'Boo'),
    (23.5, 23.75, 32.0833, 'And'),
    (12.3333, 13.25, 32, 'CVn'),
    (23.75, 24, 31.3333, 'And'),
    (13.9583, 14.0333, 30.75, 'CVn'),
    (2.4167, 2.7167, 30.6667, 'Tri'),
    (2.7167, 4.5, 30.6667, 'Per'),
    (4.5, 4.75, 30, 'Aur'),
    (18.175, 19.3583, 30, 'Lyr'),
    (11, 12, 29, 'UMa'),
    (19.6667, 20.9167, 29, 'Cyg'),
    (4.75, 5.8833, 28.5, 'Aur'),
    (9.8833, 10.5, 28.5, 'LMi'),
    (13.25, 13.9583, 28.5, 'CVn'),
    (0, 0.0667, 28, 'And'),
    (1.4083, 1.6667, 28, 'Tri'),
    (5.8833, 6.5333, 28, 'Aur'),
    (7.8833, 8, 28, 'Gem'),
    (20.9167, 21.7333, 28, 'Cyg'),
    (19.2583, 19.6667, 27.5, 'Cyg'),
    (1.9167, 2.4167, 27.25, 'Tri'),
    (16.1667, 16.3333, 27, 'CrB'),
    (15.0833, 15.1833, 26, 'Boo'),
    (15.1833, 16.1667, 26, 'CrB'),
    (18.3667, 18.8667, 26, 'Lyr'),
    (10.75, 11, 25.5, 'LMi'),
    (18.8667, 19.2583, 25.5, 'Lyr'),
    (1.6667, 1.9167, 25, 'Tri'),
    (0.7167, 0.85, 23.75, 'Psc'),
    (10.5, 10.75, 23.5, 'LMi'),
    (21.25, 21.4167, 23.5, 'Vul'),
    (5.7, 5.8833, 22.8333, 'Tau'),
    (0.0667, 0.1417, 22, 'And'),
    (15.9167, 16.0333, 22, 'Ser'),
    (5.8833, 6.2167, 21.5, 'Gem'),
    (19.8333, 20.25, 21.25, 'Vul'),
    (18.8667, 19.25, 21.0833, 'Vul'),
    (0.1417, 0.85, 21, 'And'),
    (20.25, 20.5667, 20.5, 'Vul'),
    (7.8083, 7.8833, 20, 'Gem'),
    (20.5667, 21.25, 19.5, 'Vul'),
    (19.25, 19.8333, 19.1667, 'Vul'),
    (3.2833, 3.3667, 19, 'Ari'),
    (18.8667, 19, 18.5, 'Sge'),
    (5.7, 5.7667, 18, 'Ori'),
    (6.2167, 6.3083, 17.5, 'Gem'),
    (19, 19.8333, 16.1667, 'Sge'),
    (4.9667, 5.3333, 16, 'Tau'),
    (15.9167, 16.0833, 16, 'Her'),
    (19.8333, 20.25, 15.75, 'Sge'),
    (4.6167, 4.9667, 15.5, 'Tau'),
    (5.3333, 5.6, 15.5, 'Tau'),
    (12.8333, 13.5, 15, 'Com'),
    (17.25, 18.25, 14.3333, 'Her'),
    (11.8667, 12.8333, 14, 'Com'),
    (7.5, 7.8083, 13.5, 'Gem'),
    (16.75, 17.25, 12.8333, 'Her'),
    (0, 0.1417, 12.5, 'Peg'),
    (5.6, 5.7667, 12.5, 'Tau'),
    (7, 7.5, 12.5, 'Gem'),
    (21.1167, 21.3333, 12.5, 'Peg'),
    (6.3083, 6.9333, 12, 'Gem'),
    (18.25, 18.8667, 12, 'Her'),
    (20.875, 21.05, 11.8333, 'Del'),
    (21.05, 21.1167, 11.8333, 'Peg'),
    (11.5167, 11.8667, 11, 'Leo'),
    (6.2417, 6.3083, 10, 'Ori'),
    (6.9333, 7, 10, 'Gem'),
    (7.8083, 7.925, 10, 'Cnc'),
    (23.8333, 24, 10, 'Peg'),
    (1.6667, 3.2833, 9.9167, 'Ari'),
    (20.1417, 20.3, 8.5, 'Del'),
    (13.5, 15.0833, 8, 'Boo'),
    (22.75, 23.8333, 7.5, 'Peg'),
    (7.925, 9.25, 7, 'Cnc'),
    (9.25, 10.75, 7, 'Leo'),
    (18.25, 18.6622, 6.25, 'Oph'),
    (18.6622, 18.8667, 6.25, 'Aql'),
    (20.8333, 20.875, 6, 'Del'),
    (7, 7.0167, 5.5, 'CMi'),
    (18.25, 18.425, 4.5, 'Ser'),
    (16.0833, 16.75, 4, 'Her'),
    (18.25, 18.425, 3, 'Oph'),
    (21.4667, 21.6667, 2.75, 'Peg'),
    (0, 2, 2, 'Psc'),
    (18.5833, 18.8667, 2, 'Ser'),
    (20.3, 20.8333, 2, 'Del'),
    (20.8333, 21.3333, 2, 'Equ'),
    (21.3333, 21.4667, 2, 'Peg'),
    (22, 22.75, 2, 'Peg'),
    (21.6667, 22, 1.75, 'Peg'),
    (7.0167, 7.2, 1.5, 'CMi'),
    (3.5833, 4.6167, 0, 'Tau'),
    (4.6167, 4.6667, 0, 'Ori'),
    (7.2, 8.0833, 0, 'CMi'),
    (14.6667, 15.0833, 0, 'Vir'),
    (17.8333, 18.25, 0, 'Oph'),
    (2.65, 3.2833, -1.75, 'Cet'),
    (3.2833, 3.5833, -1.75, 'Tau'),
    (15.0833, 16.2667, -3.25, 'Ser'),
    (4.6667, 5.0833, -4, 'Ori'),
    (5.8333, 6.2417, -4, 'Ori'),
    (17.8333, 17.9667, -4, 'Ser'),
    (18.25, 18.5833, -4, 'Ser'),
    (18.5833, 18.8667, -4, 'Aql'),
    (22.75, 23.8333, -4, 'Psc'),
    (10.75, 11.5167, -6, 'Leo'),
    (11.5167, 11.8333, -6, 'Vir'),
    (0, 0.3333, -7, 'Psc'),
    (23.8333, 24, -7, 'Psc'),
    (14.25, 14.6667, -8, 'Vir'),
    (15.9167, 16.2667, -8, 'Oph'),
    (20, 20.5333, -9, 'Aql'),
    (21.3333, 21.8667, -9, 'Aqr'),
    (17.1667, 17.9667, -10, 'Oph'),
    (5.8333, 8.0833, -11, 'Mon'),
    (4.9167, 5.0833, -11, 'Eri'),
    (5.0833, 5.8333, -11, 'Ori'),
    (8.0833, 8.3667, -11, 'Hya'),
    (9.5833, 10.75, -11, 'Sex'),
    (11.8333, 12.8333, -11, 'Vir'),
    (17.5833, 17.6667, -11.6667, 'Oph'),
    (18.8667, 20, -12.0333, 'Aql'),
    (4.8333, 4.9167, -14.5, 'Eri'),
    (20.5333, 21.3333, -15, 'Aqr'),
    (17.1667, 18.25, -16, 'Ser'),
    (18.25, 18.8667, -16, 'Sct'),
    (8.3667, 8.5833, -17, 'Hya'),
    (16.2667, 16.375, -18.25, 'Oph'),
    (8.5833, 9.0833, -19, 'Hya'),
    (10.75, 10.8333, -19, 'Crt'),
    (16.2667, 16.375, -19.25, 'Sco'),
    (15.6667, 15.9167, -20, 'Lib'),
    (12.5833, 12.8333, -22, 'Crv'),
    (12.8333, 14.25, -22, 'Vir'),
    (9.0833, 9.75, -24, 'Hya'),
    (1.6667, 2.65, -24.3833, 'Cet'),
    (2.65, 3.75, -24.3833, 'Eri'),
    (10.8333, 11.8333, -24.5, 'Crt'),
    (11.8333, 12.5833, -24.5, 'Crv'),
    (14.25, 14.9167, -24.5, 'Lib'),
    (16.2667, 16.75, -24.5833, 'Oph'),
    (0, 1.6667, -25.5, 'Cet'),
    (21.3333, 21.8667, -25.5, 'Cap'),
    (21.8667, 23.8333, -25.5, 'Aqr'),
    (23.8333, 24, -25.5, 'Cet'),
    (9.75, 10.25, -26.5, 'Hya'),
    (4.7, 4.8333, -27.25, 'Eri'),
    (4.8333, 6.1167, -27.25, 'Lep'),
    (20, 21.3333, -28, 'Cap'),
    (10.25, 10.5833, -29.1667, 'Hya'),
    (12.5833, 14.9167, -29.5, 'Hya'),
    (14.9167, 15.6667, -29.5, 'Lib'),
    (15.6667, 16, -29.5, 'Sco'),
    (4.5833, 4.7, -30, 'Eri'),
    (16.75, 17.6, -30, 'Oph'),
    (17.6, 17.8333, -30, 'Sgr'),
    (10.5833, 10.8333, -31.1667, 'Hya'),
    (6.1167, 7.3667, -33, 'CMa'),
    (12.25, 12.5833, -33, 'Hya'),
    (10.8333, 12.25, -35, 'Hya'),
    (3.5, 3.75, -36, 'For'),
    (8.3667, 9.3667, -36.75, 'Pyx'),
    (4.2667, 4.5833, -37, 'Eri'),
    (17.8333, 19.1667, -37, 'Sgr'),
    (21.3333, 23, -37, 'PsA'),
    (23, 23.3333, -37, 'Scl'),
    (3, 3.5, -39.5833, 'For'),
    (9.3667, 11, -39.75, 'Ant'),
    (0, 1.6667, -40, 'Scl'),
    (1.6667, 3, -40, 'For'),
    (3.8667, 4.2667, -40, 'Eri'),
    (23.3333, 24, -40, 'Scl'),
    (14.1667, 14.9167, -42, 'Cen'),
    (15.6667, 16, -42, 'Lup'),
    (16, 16.4208, -42, 'Sco'),
    (4.8333, 5, -43, 'Cae'),
    (5, 6.5833, -43, 'Col'),
    (8, 8.3667, -43, 'Pup'),
    (3.4167, 3.8667, -44, 'Eri'),
    (16.4208, 17.8333, -45.5, 'Sco'),
    (17.8333, 19.1667, -45.5, 'CrA'),
    (19.1667, 20.3333, -45.5, 'Sgr'),
    (20.3333, 21.3333, -45.5, 'Mic'),
    (3, 3.4167, -46, 'Eri'),
    (4.5, 4.8333, -46.5, 'Cae'),
    (15.3333, 15.6667, -48, 'Lup'),
    (0, 2.3333, -48.1667, 'Phe'),
    (2.6667, 3, -49, 'Eri'),
    (4.0833, 4.2667, -49, 'Hor'),
    (4.2667, 4.5, -49, 'Cae'),
    (21.3333, 22, -50, 'Gru'),
    (6, 8, -50.75, 'Pup'),
    (8, 8.1667, -50.75, 'Vel'),
    (2.4167, 2.6667, -51, 'Eri'),
    (3.8333, 4.0833, -51, 'Hor'),
    (0, 1.8333, -51.5, 'Phe'),
    (6, 6.1667, -52.5, 'Car'),
    (8.1667, 8.45, -53, 'Vel'),
    (3.5, 3.8333, -53.1667, 'Hor'),
    (3.8333, 4, -53.1667, 'Dor'),
    (0, 1.5833, -53.5, 'Phe'),
    (2.1667, 2.4167, -54, 'Eri'),
    (4.5, 5, -54, 'Pic'),
    (15.05, 15.3333, -54, 'Lup'),
    (8.45, 8.8333, -54.5, 'Vel'),
    (6.1667, 6.5, -55, 'Car'),
    (11.8333, 12.8333, -55, 'Cen'),
    (14.1667, 15.05, -55, 'Lup'),
    (15.05, 15.3333, -55, 'Nor'),
    (4, 4.3333, -56.5, 'Dor'),
    (8.8333, 11, -56.5, 'Vel'),
    (11, 11.25, -56.5, 'Cen'),
    (17.5, 18, -57, 'Ara'),
    (18, 20.3333, -57, 'Tel'),
    (22, 23.3333, -57, 'Gru'),
    (3.2, 3.5, -57.5, 'Hor'),
    (5, 5.5, -57.5, 'Pic'),
    (6.5, 6.8333, -58, 'Car'),
    (0, 1.3333, -58.5, 'Phe'),
    (1.3333, 2.1667, -58.5, 'Eri'),
    (23.3333, 24, -58.5, 'Phe'),
    (4.3333, 4.5833, -59, 'Dor'),
    (15.3333, 16.4208, -60, 'Nor'),
    (20.3333, 21.3333, -60, 'Ind'),
    (5.5, 6, -61, 'Pic'),
    (15.1667, 15.3333, -61, 'Cir'),
    (16.4208, 16.5833, -61, 'Ara'),
    (14.9167, 15.1667, -63.5833, 'Cir'),
    (16.5833, 16.75, -63.5833, 'Ara'),
    (6, 6.8333, -64, 'Pic'),
    (6.8333, 9.0333, -64, 'Car'),
    (11.25, 11.8333, -64, 'Cen'),
    (11.8333, 12.8333, -64, 'Cru'),
    (12.8333, 14.5333, -64, 'Cen'),
    (13.5, 13.6667, -65, 'Cir'),
    (16.75, 16.8333, -65, 'Ara'),
    (2.1667, 3.2, -67.5, 'Hor'),
    (3.2, 4.5833, -67.5, 'Ret'),
    (14.75, 14.9167, -67.5, 'Cir'),
    (16.8333, 17.5, -67.5, 'Ara'),
    (17.5, 18, -67.5, 'Pav'),
    (22, 23.3333, -67.5, 'Tuc'),
    (4.5833, 6.5833, -70, 'Dor'),
    (13.6667, 14.75, -70, 'Cir'),
    (14.75, 17, -70, 'TrA'),
    (0, 1.3333, -75, 'Tuc'),
    (3.5, 4.5833, -75, 'Hyi'),
    (6.5833, 9.0333, -75, 'Vol'),
    (9.0333, 11.25, -75, 'Car'),
    (11.25, 13.6667, -75, 'Mus'),
    (18, 21.3333, -75, 'Pav'),
    (21.3333, 23.3333, -75, 'Ind'),
    (23.3333, 24, -75, 'Tuc'),
    (0.75, 1.3333, -76, 'Tuc'),
    (0, 3.5, -82.5, 'Hyi'),
    (7.6667, 13.6667, -82.5, 'Cha'),
    (13.6667, 18, -82.5, 'Aps'),
    (3.5, 7.6667, -85, 'Men'),
    (0, 24, -90, 'Oct'),
)


def temperature(bv):
    """Ballesteros (2012): T = 4600 (1 / (0.92 (B-V) + 1.7) + 1 / (0.92 (B-V) + 0.62)), B-V clamped to BV_RANGE."""
    if not math.isfinite(bv):
        raise StarError("B-V is finite")
    bv = min(max(bv, BV_RANGE[0]), BV_RANGE[1])
    return 4600.0 * (1.0 / (0.92 * bv + 1.7) + 1.0 / (0.92 * bv + 0.62))


def planck(wavelength_nm, t):
    """Spectral radiance of a blackbody, W sr^-1 m^-3, at a wavelength in nanometres."""
    if not (t > 0.0) or not (wavelength_nm > 0.0):
        raise StarError("Planck's law needs a positive temperature and wavelength")
    lam = wavelength_nm * 1e-9
    return PLANCK_C1 / (lam ** 5 * math.expm1(PLANCK_C2 / (lam * t)))


def blackbody_xyz(t):
    """CIE XYZ of the Planck spectrum (relative; the integration step is the table's 5 nm)."""
    x = y = z = 0.0
    for nm, xb, yb, zb in CMF:
        b = planck(nm, t)
        x += b * xb
        y += b * yb
        z += b * zb
    return (x, y, z)


def chromaticity(xyz):
    s = xyz[0] + xyz[1] + xyz[2]
    if s <= 0.0:
        raise StarError("a black colour has no chromaticity")
    return (xyz[0] / s, xyz[1] / s)


def xyz_to_linear_srgb(xyz):
    return tuple(sum(m[j] * xyz[j] for j in range(3)) for m in XYZ_TO_SRGB)


def colour(t):
    """Linear sRGB of a blackbody at t kelvin, normalised to Y = 1 and clipped at 0."""
    xyz = blackbody_xyz(t)
    if xyz[1] <= 0.0:
        raise StarError("the spectrum has no luminance")
    rgb = xyz_to_linear_srgb((xyz[0] / xyz[1], 1.0, xyz[2] / xyz[1]))
    return tuple(max(c, 0.0) for c in rgb)


def spectral_class(sptype):
    """The first class letter O B A F G K M of a spectral type, skipping luminosity and peculiarity prefixes
    (gG9 -> G, kA2hA5mA7V -> A); "" when the type names none."""
    for ch in sptype:
        if ch in "OBAFGKM":
            return ch
    return ""


def star_temperature(star):
    bv = star.bv if star.bv is not None else CLASS_BV[spectral_class(star.sptype)]
    return temperature(bv)


# ------------------------------------------------------------------------------------ rule 4: directions and proper motion


def direction(ra_deg, dec_deg):
    """ICRF unit vector of a right ascension and declination in degrees."""
    if not (-90.0 <= dec_deg <= 90.0) or not math.isfinite(ra_deg):
        raise StarError("declination is within [-90, 90] and right ascension finite")
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    return (math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec))


def radec(d):
    u = _unit(d)
    ra = math.degrees(math.atan2(u[1], u[0])) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, u[2]))))
    return (ra, dec)


def total_motion(star):
    """Total proper motion in arcsec per year (pmRA is already cos(Dec) dRA/dt)."""
    return math.hypot(star.pm_ra, star.pm_dec)


def largest_motion(catalogue):
    return max(catalogue, key=lambda s: (total_motion(s), -s.hr))


def years_since_j2000(et_seconds):
    return et_seconds / JULIAN_YEAR_S


def moved(star, years):
    """Direction of the star `years` Julian years after J2000: the J2000 direction displaced along the local east
    and north unit vectors by pmRA and pmDE times the years, then renormalised."""
    if not math.isfinite(years) or abs(years) > MAX_YEARS:
        raise StarError(f"the proper-motion span is within {MAX_YEARS} years of J2000")
    d = direction(star.ra, star.dec)
    if years == 0.0 or (star.pm_ra == 0.0 and star.pm_dec == 0.0):
        return d
    ra = math.radians(star.ra)
    dec = math.radians(star.dec)
    east = (-math.sin(ra), math.cos(ra), 0.0)
    north = (-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec))
    e = math.radians(star.pm_ra / 3600.0 * years)
    n = math.radians(star.pm_dec / 3600.0 * years)
    # the displacement is small (below a degree over the bound for every catalogue star), so the tangent-plane
    # step followed by renormalisation is the great-circle motion to second order
    return _unit((d[0] + e * east[0] + n * north[0], d[1] + e * east[1] + n * north[1], d[2] + e * east[2] + n * north[2]))


def scene_direction(d):
    """Scene direction of an ICRF direction: (x, -z, y), the axes of the time-frames draft."""
    return tuple(sum(SCENE_FROM_ICRF_AXES[i][j] * d[j] for j in range(3)) for i in range(3))


# ------------------------------------------------------------------------------------ rule 5: constellations


def precess(ra_deg, dec_deg, epoch1, epoch2):
    """Herget's precession (Publ. Cincinnati Obs. 24, as in Roman's program.f) of a mean place in degrees from
    epoch1 to epoch2 in years AD."""
    if epoch1 == epoch2:
        return (ra_deg, dec_deg)
    x1 = direction(ra_deg, dec_deg)
    csr = math.radians(1.0) / 3600.0
    t = 0.001 * (epoch2 - epoch1)
    st = 0.001 * (epoch1 - 1900.0)
    a = csr * t * (23042.53 + st * (139.75 + 0.06 * st) + t * (30.23 - 0.27 * st + 18.0 * t))
    b = csr * t * t * (79.27 + 0.66 * st + 0.32 * t) + a
    c = csr * t * (20046.85 - st * (85.33 + 0.37 * st) + t * (-42.67 - 0.37 * st - 41.8 * t))
    sa, sb, sc, ca, cb, cc = math.sin(a), math.sin(b), math.sin(c), math.cos(a), math.cos(b), math.cos(c)
    r = ((ca * cb * cc - sa * sb, -ca * sb - sa * cb * cc, -cb * sc),
         (sa * cb + ca * sb * cc, ca * cb - sa * sb * cc, -sb * sc),
         (ca * sc, -sa * sc, cc))
    x2 = tuple(sum(r[i][j] * x1[j] for j in range(3)) for i in range(3))
    return radec(x2)


def constellation(ra_deg, dec_deg, epoch=2000.0):
    """Roman's lookup: precess to 1875, then the first boundary row at or below the declination whose arc holds
    the right ascension."""
    if not (-90.0 <= dec_deg <= 90.0):
        raise StarError("declination is within [-90, 90]")
    ra, dec = precess(ra_deg % 360.0, dec_deg, epoch, 1875.0)
    ra_h = (ra / 15.0) % 24.0
    for ra_low, ra_up, dec_low, name in BOUNDARIES:
        if dec_low <= dec and ra_low <= ra_h < ra_up:
            return name
    raise StarError(f"no constellation holds RA {ra_deg} Dec {dec_deg}")  # unreachable: Oct closes the table at -90


def star_constellation(star):
    return constellation(star.ra, star.dec, 2000.0)


_ABBREVIATIONS = frozenset(row[3] for row in BOUNDARIES)


def name_constellation(name):
    """The constellation abbreviation a Bayer or Flamsteed name ends with, else None."""
    tail = name[-3:]
    return tail if tail in _ABBREVIATIONS else None


def name_agreement(catalogue):
    """(named stars, those whose name's constellation is the lookup's)."""
    named = agree = 0
    for s in catalogue:
        c = name_constellation(s.name)
        if c is None:
            continue
        named += 1
        agree += star_constellation(s) == c
    return named, agree


# ------------------------------------------------------------------------------------ rule 6: the field and the seek check


def star_field(catalogue, limit_magnitude, years, magnitude_zero):
    """The stars to V <= limit at J2000 + years: hr, ICRF direction, flux, linear colour and constellation. A pure
    function of its arguments, so a seek lands on the same field as a play-through."""
    if not (magnitude_zero > 0.0):
        raise StarError("magnitudeZero is positive")
    if not math.isfinite(limit_magnitude):
        raise StarError("limitMagnitude is finite")
    if len(catalogue) > MAX_STARS:
        raise StarError(f"catalogue has more than {MAX_STARS} stars")
    field = []
    for s in catalogue:
        if s.vmag > limit_magnitude:
            continue
        field.append({"hr": s.hr, "direction": moved(s, years), "flux": flux(s.vmag, magnitude_zero),
                      "colour": colour(star_temperature(s)), "constellation": star_constellation(s)})
    return field


def _field_digest(field):
    h = hashlib.sha256()
    for s in field:
        h.update(repr((s["hr"], s["direction"], s["flux"], s["colour"], s["constellation"])).encode())
    return h.hexdigest()[:16]


def seek_test(catalogue):
    """Frame 600 at 24 fps with rate 1 Julian year per second reached directly equals the field reached after
    playing frames 0 to 599: the field depends on the epoch alone."""
    years_per_frame = 1.0 / 24.0
    played = None
    for frame in range(601):
        played = star_field(catalogue, 4.0, frame * years_per_frame, 1.0)
    sought = star_field(catalogue, 4.0, 600 * years_per_frame, 1.0)
    return played == sought


# ------------------------------------------------------------------------------------ the draft's numeric table

_CATALOGUE = None


def _cat():
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = load_catalogue()
    return _CATALOGUE


def _hr(hr):
    return next(s for s in _cat() if s.hr == hr)


TABLE = [
    ("catalogue digest", "CATALOGUE_DIGEST", "'cd18b1c9b8c009d922edfed020ba718aa14a577416fb625bf01ddd9cbdaab617'"),
    ("stars with a J2000 position", "len(cat)", '9096'),
    ("records skipped", "CATALOGUE_SKIPPED", '14'),
    ("stars without B-V", "sum(1 for s in cat if s.bv is None)", '310'),
    ("stars to V 6.5", "count_to(cat, 6.5)", '8404'),
    ("stars to V 6.0", "count_to(cat, 6.0)", '5080'),
    ("brightest star", "brightest(cat, 1)[0].hr, brightest(cat, 1)[0].vmag", '(2491, -1.46)'),
    ("five magnitudes", "flux(0.0) / flux(5.0)", '100'),
    ("one magnitude", "flux(0.0) / flux(1.0)", '2.51189'),
    ("Sirius to the limit", "flux(-1.46) / flux(6.5)", '1527.57'),
    ("zero point", "flux(0.0, zero=3.0)", '3'),
    ("magnitude round trip", "magnitude(flux(4.2))", '4.2'),
    ("Sun temperature (B-V 0.65)", "temperature(0.65)", '5778.42'),
    ("Vega temperature (B-V 0.00)", "temperature(0.0)", '10125.2'),
    ("Betelgeuse temperature (B-V 1.85)", "temperature(1.85)", '3333.2'),
    ("clamp at B-V 2.0", "temperature(5.74) == temperature(2.0)", 'True'),
    ("Wien peak at 5800 K (nm)", "max(range(300, 1000), key=lambda nm: planck(nm, 5800.0))", '500'),
    ("Sun chromaticity", "chromaticity(blackbody_xyz(5778.0))", '(0.32643, 0.335722)'),
    ("D65 chromaticity", "chromaticity(blackbody_xyz(6504.0))", '(0.313463, 0.323567)'),
    ("Sun linear sRGB (Y = 1)", "colour(5778.0)", '(1.11194, 0.975481, 0.913851)'),
    ("Vega linear sRGB (Y = 1)", "colour(temperature(0.0))", '(0.868294, 0.994718, 1.44071)'),
    ("Betelgeuse linear sRGB (Y = 1)", "colour(temperature(1.85))", '(1.62548, 0.878597, 0.361475)'),
    ("locus inside sRGB", "min(min(colour(temperature(bv / 10.0))) for bv in range(-4, 21))", '0.317665'),
    ("class G without B-V", "spectral_class('gG9'), CLASS_BV['G']", "('G', 0.65)"),
    ("Sirius direction", "direction(_hr(2491).ra, _hr(2491).dec)", '(-0.187454, 0.939218, -0.28763)'),
    ("direction round trip", "radec(direction(101.28708, -16.71611))", '(101.287, -16.7161)'),
    ("largest proper motion (HR, arcsec/yr)", "largest_motion(cat).hr, total_motion(largest_motion(cat))", '(4550, 7.05797)'),
    ("Groombridge 1830 over a century (deg)", "math.degrees(angle(direction(_hr(4550).ra, _hr(4550).dec), moved(_hr(4550), 100.0)))", '0.196054'),
    ("pmRA is projected", "radec(moved(Star(0, '', 10.0, 60.0, 5.0, 0.5, 1.0, 0.0, 'G0'), 1.0))[0] - 10.0", '0.000555556'),
    ("one Julian year", "years_since_j2000(JULIAN_YEAR_S)", '1'),
    ("scene axes", "scene_direction((1.0, 2.0, 3.0))", '(1, -3, 2)'),
    ("precession 1900 to 2000 at the origin", "precess(0.0, 0.0, 1900.0, 2000.0)", '(1.28057, 0.556692)'),
    ("precession round trip", "precess(*precess(101.28708, -16.71611, 2000.0, 1875.0), 1875.0, 2000.0)", '(101.287, -16.7161)'),
    ("boundary rows", "len(BOUNDARIES), len({r[3] for r in BOUNDARIES})", '(357, 88)'),
    ("Roman: 9h +65 (1950)", "constellation(9.0 * 15, 65.0, 1950.0)", "'UMa'"),
    ("Roman: 5.12h +9.12 (1950)", "constellation(5.12 * 15, 9.12, 1950.0)", "'Ori'"),
    ("Roman: 6.2222h -81.1234 (1950)", "constellation(6.2222 * 15, -81.1234, 1950.0)", "'Men'"),
    ("Sirius, Polaris, Vega", "star_constellation(_hr(2491)), star_constellation(_hr(424)), star_constellation(_hr(7001))", "('CMa', 'UMi', 'Lyr')"),
    ("Serpens' two parts", "constellation(236.0, 7.0), constellation(272.0, -5.0)", "('Ser', 'Ser')"),
    ("named stars agreeing with the lookup", "name_agreement(cat)", '(3143, 3143)'),
    ("field to V 6.5 at J2000 + 25 years", "len(star_field(cat, 6.5, 25.0, 1.0))", '8404'),
    ("field digest at J2000 + 25 years", "_field_digest(star_field(cat, 6.5, 25.0, 1.0))", "'c923002297bc0982'"),
    ("seek check", "seek_test(cat)", 'True'),
]


def scope():
    s = dict(globals())
    s["math"] = math
    s["cat"] = _cat()
    return s


def _same(a, b, rel=5e-4, abs_tol=5e-4):
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, rel, abs_tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)
    return a == b


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return repr(v)


def main():
    s = scope()
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
