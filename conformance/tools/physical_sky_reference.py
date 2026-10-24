"""Reference implementation of the draft SREP "Add the physical sun, moon and sky to dome lights"
(srep/srep-0000-physical-sky.md; A1 of SREP 12, SRC-43).

Standard library only. The module gives:

- the Solar Position Algorithm of Reda and Andreas (2004, 2008 revision) written from the report's
  equations (sections 3.1 to 3.14): Julian day and the time scales, the Earth's heliocentric longitude,
  latitude and radius from the report's periodic terms (its Table A4.2, the VSOP87 abridgement), the IAU
  1980 nutation from its 63 terms (Table A4.3), obliquity, aberration, sidereal time, the geocentric and
  topocentric sun, refraction, zenith, azimuth and incidence; NREL's own code is not used;
- a low-precision moon (Montenbruck and Pfleger's series) with the Almanac's horizontal parallax, placed
  topocentrically by the same observer, with its phase;
- the atmosphere of Hillaire (2020) on the model of Bruneton and Neyret (2008): Rayleigh, Mie and ozone
  layers, transmittance by composite Gauss-Legendre quadrature, single scattering, the isotropic
  multiple-scattering estimate as a lazily filled table, the sun disc, aerial perspective and height fog;
- `main()` prints the draft's numeric table.
"""
import math
import re

MAX_SAMPLES = 65536
AU_KM = 149597870.7
EARTH_RADIUS_KM = 6378.14
MOON_RADIUS_KM = 1737.4
SUN_RADIUS_DEG = 0.26667
DEFAULT_DELTA_T = 69.0
DELTA_T_RANGE = (-8000.0, 8000.0)
DELTA_T_FREE_YEARS = (1900, 2100)
SPA_YEARS = (-2000, 6000)


class SkyError(ValueError):
    """A document value the draft rejects."""


# ------------------------------------------------------------------------------------ vectors


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def unit(a):
    n = _norm(a)
    if n == 0.0:
        raise SkyError("a zero direction has no unit")
    return (a[0] / n, a[1] / n, a[2] / n)


def march(p, d, length):
    return _add(p, _mul(d, length))


def _limit360(x):
    x = x % 360.0
    return x + 360.0 if x < 0 else x


# ------------------------------------------------------------------------------------ rules 1 and 2: time

_DT = re.compile(r"^(-?\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:\d{2})$")


def parse_datetime(text):
    """`YYYY-MM-DDThh:mm:ss[.f](Z|+hh:mm)` into (year, month, day, hour, minute, second, timezone hours)."""
    m = _DT.match(text or "")
    if not m:
        raise SkyError("date is YYYY-MM-DDThh:mm:ss with a Z or +hh:mm offset: %r" % (text,))
    y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
    s = float(m.group(6))
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 0 <= h <= 23 and 0 <= mi <= 59 and 0.0 <= s < 61.0):
        raise SkyError("date has a field out of range: %r" % (text,))
    z = m.group(7)
    tz = 0.0 if z == "Z" else (1.0 if z[0] == "+" else -1.0) * (int(z[1:3]) + int(z[4:6]) / 60.0)
    return (y, mo, d, h, mi, s, tz)


def julian_day(year, month, day, hour, minute, second, timezone):
    """Report section 3.1: the Julian day of a civil date and time with its timezone (hours east)."""
    d = day + (hour + minute / 60.0 + second / 3600.0 - timezone) / 24.0
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d - 1524.5
    if jd > 2299160.0:
        a = math.floor(y / 100.0)
        jd += 2 - a + math.floor(a / 4.0)
    return jd


def time_scales(jd, delta_t):
    """Report 3.1.2 to 3.1.5: ephemeris day, Julian century, ephemeris century and millennium."""
    jde = jd + delta_t / 86400.0
    jc = (jd - 2451545.0) / 36525.0
    jce = (jde - 2451545.0) / 36525.0
    return {"jd": jd, "jde": jde, "jc": jc, "jce": jce, "jme": jce / 10.0}


# ------------------------------------------------------------------------------------ rules 3 to 6: the sun
# The periodic terms of the report's Table A4.2 (A, B, C per row; the VSOP87 abridgement of Bretagnon and
# Simon as printed by Meeus) and the nutation terms of Table A4.3; the values were cross-checked against
# pvlib's BSD-3-Clause spa module.

L0 = (
    (175347046.0, 0.0, 0.0), (3341656.0, 4.6692568, 6283.07585), (34894.0, 4.6261, 12566.1517),
    (3497.0, 2.7441, 5753.3849), (3418.0, 2.8289, 3.5231), (3136.0, 3.6277, 77713.7715),
    (2676.0, 4.4181, 7860.4194), (2343.0, 6.1352, 3930.2097), (1324.0, 0.7425, 11506.7698),
    (1273.0, 2.0371, 529.691), (1199.0, 1.1096, 1577.3435), (990.0, 5.233, 5884.927),
    (902.0, 2.045, 26.298), (857.0, 3.508, 398.149), (780.0, 1.179, 5223.694),
    (753.0, 2.533, 5507.553), (505.0, 4.583, 18849.228), (492.0, 4.205, 775.523),
    (357.0, 2.92, 0.067), (317.0, 5.849, 11790.629), (284.0, 1.899, 796.298),
    (271.0, 0.315, 10977.079), (243.0, 0.345, 5486.778), (206.0, 4.806, 2544.314),
    (205.0, 1.869, 5573.143), (202.0, 2.458, 6069.777), (156.0, 0.833, 213.299),
    (132.0, 3.411, 2942.463), (126.0, 1.083, 20.775), (115.0, 0.645, 0.98),
    (103.0, 0.636, 4694.003), (102.0, 0.976, 15720.839), (102.0, 4.267, 7.114),
    (99.0, 6.21, 2146.17), (98.0, 0.68, 155.42), (86.0, 5.98, 161000.69),
    (85.0, 1.3, 6275.96), (85.0, 3.67, 71430.7), (80.0, 1.81, 17260.15),
    (79.0, 3.04, 12036.46), (75.0, 1.76, 5088.63), (74.0, 3.5, 3154.69),
    (74.0, 4.68, 801.82), (70.0, 0.83, 9437.76), (62.0, 3.98, 8827.39),
    (61.0, 1.82, 7084.9), (57.0, 2.78, 6286.6), (56.0, 4.39, 14143.5),
    (56.0, 3.47, 6279.55), (52.0, 0.19, 12139.55), (52.0, 1.33, 1748.02),
    (51.0, 0.28, 5856.48), (49.0, 0.49, 1194.45), (41.0, 5.37, 8429.24),
    (41.0, 2.4, 19651.05), (39.0, 6.17, 10447.39), (37.0, 6.04, 10213.29),
    (37.0, 2.57, 1059.38), (36.0, 1.71, 2352.87), (36.0, 1.78, 6812.77),
    (33.0, 0.59, 17789.85), (30.0, 0.44, 83996.85), (30.0, 2.74, 1349.87),
    (25.0, 3.16, 4690.48),
)

L1 = (
    (628331966747.0, 0.0, 0.0), (206059.0, 2.678235, 6283.07585), (4303.0, 2.6351, 12566.1517),
    (425.0, 1.59, 3.523), (119.0, 5.796, 26.298), (109.0, 2.966, 1577.344),
    (93.0, 2.59, 18849.23), (72.0, 1.14, 529.69), (68.0, 1.87, 398.15),
    (67.0, 4.41, 5507.55), (59.0, 2.89, 5223.69), (56.0, 2.17, 155.42),
    (45.0, 0.4, 796.3), (36.0, 0.47, 775.52), (29.0, 2.65, 7.11),
    (21.0, 5.34, 0.98), (19.0, 1.85, 5486.78), (19.0, 4.97, 213.3),
    (17.0, 2.99, 6275.96), (16.0, 0.03, 2544.31), (16.0, 1.43, 2146.17),
    (15.0, 1.21, 10977.08), (12.0, 2.83, 1748.02), (12.0, 3.26, 5088.63),
    (12.0, 5.27, 1194.45), (12.0, 2.08, 4694.0), (11.0, 0.77, 553.57),
    (10.0, 1.3, 6286.6), (10.0, 4.24, 1349.87), (9.0, 2.7, 242.73),
    (9.0, 5.64, 951.72), (8.0, 5.3, 2352.87), (6.0, 2.65, 9437.76),
    (6.0, 4.67, 4690.48),
)

L2 = (
    (52919.0, 0.0, 0.0), (8720.0, 1.0721, 6283.0758), (309.0, 0.867, 12566.152),
    (27.0, 0.05, 3.52), (16.0, 5.19, 26.3), (16.0, 3.68, 155.42),
    (10.0, 0.76, 18849.23), (9.0, 2.06, 77713.77), (7.0, 0.83, 775.52),
    (5.0, 4.66, 1577.34), (4.0, 1.03, 7.11), (4.0, 3.44, 5573.14),
    (3.0, 5.14, 796.3), (3.0, 6.05, 5507.55), (3.0, 1.19, 242.73),
    (3.0, 6.12, 529.69), (3.0, 0.31, 398.15), (3.0, 2.28, 553.57),
    (2.0, 4.38, 5223.69), (2.0, 3.75, 0.98),
)

L3 = (
    (289.0, 5.844, 6283.076), (35.0, 0.0, 0.0), (17.0, 5.49, 12566.15),
    (3.0, 5.2, 155.42), (1.0, 4.72, 3.52), (1.0, 5.3, 18849.23),
    (1.0, 5.97, 242.73),
)

L4 = (
    (114.0, 3.142, 0.0), (8.0, 4.13, 6283.08), (1.0, 3.84, 12566.15),
)

L5 = (
    (1.0, 3.14, 0.0),
)

B0 = (
    (280.0, 3.199, 84334.662), (102.0, 5.422, 5507.553), (80.0, 3.88, 5223.69),
    (44.0, 3.7, 2352.87), (32.0, 4.0, 1577.34),
)

B1 = (
    (9.0, 3.9, 5507.55), (6.0, 1.73, 5223.69),
)

R0 = (
    (100013989.0, 0.0, 0.0), (1670700.0, 3.0984635, 6283.07585), (13956.0, 3.05525, 12566.1517),
    (3084.0, 5.1985, 77713.7715), (1628.0, 1.1739, 5753.3849), (1576.0, 2.8469, 7860.4194),
    (925.0, 5.453, 11506.77), (542.0, 4.564, 3930.21), (472.0, 3.661, 5884.927),
    (346.0, 0.964, 5507.553), (329.0, 5.9, 5223.694), (307.0, 0.299, 5573.143),
    (243.0, 4.273, 11790.629), (212.0, 5.847, 1577.344), (186.0, 5.022, 10977.079),
    (175.0, 3.012, 18849.228), (110.0, 5.055, 5486.778), (98.0, 0.89, 6069.78),
    (86.0, 5.69, 15720.84), (86.0, 1.27, 161000.69), (65.0, 0.27, 17260.15),
    (63.0, 0.92, 529.69), (57.0, 2.01, 83996.85), (56.0, 5.24, 71430.7),
    (49.0, 3.25, 2544.31), (47.0, 2.58, 775.52), (45.0, 5.54, 9437.76),
    (43.0, 6.01, 6275.96), (39.0, 5.36, 4694.0), (38.0, 2.39, 8827.39),
    (37.0, 0.83, 19651.05), (37.0, 4.9, 12139.55), (36.0, 1.67, 12036.46),
    (35.0, 1.84, 2942.46), (33.0, 0.24, 7084.9), (32.0, 0.18, 5088.63),
    (32.0, 1.78, 398.15), (28.0, 1.21, 6286.6), (28.0, 1.9, 6279.55),
    (26.0, 4.59, 10447.39),
)

R1 = (
    (103019.0, 1.10749, 6283.07585), (1721.0, 1.0644, 12566.1517), (702.0, 3.142, 0.0),
    (32.0, 1.02, 18849.23), (31.0, 2.84, 5507.55), (25.0, 1.32, 5223.69),
    (18.0, 1.42, 1577.34), (10.0, 5.91, 10977.08), (9.0, 1.42, 6275.96),
    (9.0, 0.27, 5486.78),
)

R2 = (
    (4359.0, 5.7846, 6283.0758), (124.0, 5.579, 12566.152), (12.0, 3.14, 0.0),
    (9.0, 3.63, 77713.77), (6.0, 1.87, 5573.14), (3.0, 5.47, 18849.23),
)

R3 = (
    (145.0, 4.273, 6283.076), (7.0, 3.92, 12566.15),
)

R4 = (
    (4.0, 2.56, 6283.08),
)

NUTATION_Y = (
    (0, 0, 0, 0, 1), (-2, 0, 0, 2, 2), (0, 0, 0, 2, 2), (0, 0, 0, 0, 2),
    (0, 1, 0, 0, 0), (0, 0, 1, 0, 0), (-2, 1, 0, 2, 2), (0, 0, 0, 2, 1),
    (0, 0, 1, 2, 2), (-2, -1, 0, 2, 2), (-2, 0, 1, 0, 0), (-2, 0, 0, 2, 1),
    (0, 0, -1, 2, 2), (2, 0, 0, 0, 0), (0, 0, 1, 0, 1), (2, 0, -1, 2, 2),
    (0, 0, -1, 0, 1), (0, 0, 1, 2, 1), (-2, 0, 2, 0, 0), (0, 0, -2, 2, 1),
    (2, 0, 0, 2, 2), (0, 0, 2, 2, 2), (0, 0, 2, 0, 0), (-2, 0, 1, 2, 2),
    (0, 0, 0, 2, 0), (-2, 0, 0, 2, 0), (0, 0, -1, 2, 1), (0, 2, 0, 0, 0),
    (2, 0, -1, 0, 1), (-2, 2, 0, 2, 2), (0, 1, 0, 0, 1), (-2, 0, 1, 0, 1),
    (0, -1, 0, 0, 1), (0, 0, 2, -2, 0), (2, 0, -1, 2, 1), (2, 0, 1, 2, 2),
    (0, 1, 0, 2, 2), (-2, 1, 1, 0, 0), (0, -1, 0, 2, 2), (2, 0, 0, 2, 1),
    (2, 0, 1, 0, 0), (-2, 0, 2, 2, 2), (-2, 0, 1, 2, 1), (2, 0, -2, 0, 1),
    (2, 0, 0, 0, 1), (0, -1, 1, 0, 0), (-2, -1, 0, 2, 1), (-2, 0, 0, 0, 1),
    (0, 0, 2, 2, 1), (-2, 0, 2, 0, 1), (-2, 1, 0, 2, 1), (0, 0, 1, -2, 0),
    (-1, 0, 1, 0, 0), (-2, 1, 0, 0, 0), (1, 0, 0, 0, 0), (0, 0, 1, 2, 0),
    (0, 0, -2, 2, 2), (-1, -1, 1, 0, 0), (0, 1, 1, 0, 0), (0, -1, 1, 2, 2),
    (2, -1, -1, 2, 2), (0, 0, 3, 2, 2), (2, -1, 0, 2, 2),
)

NUTATION_ABCD = (
    (-171996.0, -174.2, 92025.0, 8.9), (-13187.0, -1.6, 5736.0, -3.1), (-2274.0, -0.2, 977.0, -0.5),
    (2062.0, 0.2, -895.0, 0.5), (1426.0, -3.4, 54.0, -0.1), (712.0, 0.1, -7.0, 0.0),
    (-517.0, 1.2, 224.0, -0.6), (-386.0, -0.4, 200.0, 0.0), (-301.0, 0.0, 129.0, -0.1),
    (217.0, -0.5, -95.0, 0.3), (-158.0, 0.0, 0.0, 0.0), (129.0, 0.1, -70.0, 0.0),
    (123.0, 0.0, -53.0, 0.0), (63.0, 0.0, 0.0, 0.0), (63.0, 0.1, -33.0, 0.0),
    (-59.0, 0.0, 26.0, 0.0), (-58.0, -0.1, 32.0, 0.0), (-51.0, 0.0, 27.0, 0.0),
    (48.0, 0.0, 0.0, 0.0), (46.0, 0.0, -24.0, 0.0), (-38.0, 0.0, 16.0, 0.0),
    (-31.0, 0.0, 13.0, 0.0), (29.0, 0.0, 0.0, 0.0), (29.0, 0.0, -12.0, 0.0),
    (26.0, 0.0, 0.0, 0.0), (-22.0, 0.0, 0.0, 0.0), (21.0, 0.0, -10.0, 0.0),
    (17.0, -0.1, 0.0, 0.0), (16.0, 0.0, -8.0, 0.0), (-16.0, 0.1, 7.0, 0.0),
    (-15.0, 0.0, 9.0, 0.0), (-13.0, 0.0, 7.0, 0.0), (-12.0, 0.0, 6.0, 0.0),
    (11.0, 0.0, 0.0, 0.0), (-10.0, 0.0, 5.0, 0.0), (-8.0, 0.0, 3.0, 0.0),
    (7.0, 0.0, -3.0, 0.0), (-7.0, 0.0, 0.0, 0.0), (-7.0, 0.0, 3.0, 0.0),
    (-7.0, 0.0, 3.0, 0.0), (6.0, 0.0, 0.0, 0.0), (6.0, 0.0, -3.0, 0.0),
    (6.0, 0.0, -3.0, 0.0), (-6.0, 0.0, 3.0, 0.0), (-6.0, 0.0, 3.0, 0.0),
    (5.0, 0.0, 0.0, 0.0), (-5.0, 0.0, 3.0, 0.0), (-5.0, 0.0, 3.0, 0.0),
    (-5.0, 0.0, 3.0, 0.0), (4.0, 0.0, 0.0, 0.0), (4.0, 0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0, 0.0), (-4.0, 0.0, 0.0, 0.0), (-4.0, 0.0, 0.0, 0.0),
    (-4.0, 0.0, 0.0, 0.0), (3.0, 0.0, 0.0, 0.0), (-3.0, 0.0, 0.0, 0.0),
    (-3.0, 0.0, 0.0, 0.0), (-3.0, 0.0, 0.0, 0.0), (-3.0, 0.0, 0.0, 0.0),
    (-3.0, 0.0, 0.0, 0.0), (-3.0, 0.0, 0.0, 0.0), (-3.0, 0.0, 0.0, 0.0),
)


def _series(table, x):
    return sum(a * math.cos(b + c * x) for a, b, c in table)


def heliocentric_longitude(jme):
    """Report 3.2.1 to 3.2.4, degrees in [0, 360)."""
    l = sum(_series(t, jme) * jme ** i for i, t in enumerate((L0, L1, L2, L3, L4, L5))) / 1e8
    return _limit360(math.degrees(l))


def heliocentric_latitude(jme):
    """Report 3.2.7, degrees."""
    b = (_series(B0, jme) + _series(B1, jme) * jme) / 1e8
    return math.degrees(b)


def earth_radius_vector(jme):
    """Report 3.2.8, astronomical units."""
    return sum(_series(t, jme) * jme ** i for i, t in enumerate((R0, R1, R2, R3, R4))) / 1e8


def nutation(jce):
    """Report 3.4: nutation in longitude and obliquity, degrees."""
    x = (
        297.85036 + 445267.111480 * jce - 0.0019142 * jce ** 2 + jce ** 3 / 189474.0,
        357.52772 + 35999.050340 * jce - 0.0001603 * jce ** 2 - jce ** 3 / 300000.0,
        134.96298 + 477198.867398 * jce + 0.0086972 * jce ** 2 + jce ** 3 / 56250.0,
        93.27191 + 483202.017538 * jce - 0.0036825 * jce ** 2 + jce ** 3 / 327270.0,
        125.04452 - 1934.136261 * jce + 0.0020708 * jce ** 2 + jce ** 3 / 450000.0,
    )
    dpsi = 0.0
    deps = 0.0
    for y, (a, b, c, d) in zip(NUTATION_Y, NUTATION_ABCD):
        arg = math.radians(sum(yi * xi for yi, xi in zip(y, x)))
        dpsi += (a + b * jce) * math.sin(arg)
        deps += (c + d * jce) * math.cos(arg)
    return dpsi / 36000000.0, deps / 36000000.0


def true_obliquity(jme, deps):
    """Report 3.5, degrees."""
    u = jme / 10.0
    e0 = (84381.448 - 4680.93 * u - 1.55 * u ** 2 + 1999.25 * u ** 3 - 51.38 * u ** 4 - 249.67 * u ** 5
          - 39.05 * u ** 6 + 7.12 * u ** 7 + 27.87 * u ** 8 + 5.79 * u ** 9 + 2.45 * u ** 10)
    return e0 / 3600.0 + deps


def sidereal_time(jd, jc, dpsi, eps):
    """Report 3.8: apparent sidereal time at Greenwich, degrees."""
    nu0 = _limit360(280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * jc ** 2 - jc ** 3 / 38710000.0)
    return nu0 + dpsi * math.cos(math.radians(eps))


def _equatorial(lam, beta, eps):
    """Report 3.9 and 3.10: right ascension (degrees in [0, 360)) and declination from ecliptic coordinates."""
    lr, br, er = math.radians(lam), math.radians(beta), math.radians(eps)
    alpha = math.atan2(math.sin(lr) * math.cos(er) - math.tan(br) * math.sin(er), math.cos(lr))
    delta = math.asin(math.sin(br) * math.cos(er) + math.cos(br) * math.sin(er) * math.sin(lr))
    return _limit360(math.degrees(alpha)), math.degrees(delta)


def _topocentric(alpha, delta, h, latitude, elevation, xi):
    """Report 3.12: the parallax shift of a body of equatorial horizontal parallax xi (degrees)."""
    phi = math.radians(latitude)
    u = math.atan(0.99664719 * math.tan(phi))
    x = math.cos(u) + elevation / 6378140.0 * math.cos(phi)
    y = 0.99664719 * math.sin(u) + elevation / 6378140.0 * math.sin(phi)
    xr, hr, dr = math.radians(xi), math.radians(h), math.radians(delta)
    dalpha = math.atan2(-x * math.sin(xr) * math.sin(hr), math.cos(dr) - x * math.sin(xr) * math.cos(hr))
    delta_t = math.atan2((math.sin(dr) - y * math.sin(xr)) * math.cos(dalpha),
                         math.cos(dr) - x * math.sin(xr) * math.cos(hr))
    return alpha + math.degrees(dalpha), math.degrees(delta_t), h - math.degrees(dalpha)


def refraction_correction(zenith, pressure, temperature, refraction=0.5667):
    """Report 3.14.1 and 3.14.2: the atmospheric refraction added to the elevation, degrees; zero below the
    horizon (by more than the sun's radius plus `refraction`) and at zero pressure."""
    e0 = 90.0 - zenith
    if pressure <= 0.0 or e0 < -(SUN_RADIUS_DEG + refraction):
        return 0.0
    return (pressure / 1010.0) * (283.0 / (273.0 + temperature)) * 1.02 / (
        60.0 * math.tan(math.radians(e0 + 10.3 / (e0 + 5.11))))


def _horizontal(delta_t, h_t, latitude, pressure, temperature, refraction):
    """Report 3.14 and 3.15: topocentric zenith and azimuth (degrees, azimuth from north eastward)."""
    phi, dr, hr = math.radians(latitude), math.radians(delta_t), math.radians(h_t)
    e0 = math.degrees(math.asin(math.sin(phi) * math.sin(dr) + math.cos(phi) * math.cos(dr) * math.cos(hr)))
    e = e0 + refraction_correction(90.0 - e0, pressure, temperature, refraction)
    zenith = 90.0 - e
    gamma = _limit360(math.degrees(math.atan2(math.sin(hr), math.cos(hr) * math.sin(phi) - math.tan(dr) * math.cos(phi))))
    return zenith, _limit360(gamma + 180.0), gamma


def sun_position(year, month, day, hour, minute, second, timezone, longitude, latitude, elevation=0.0,
                 pressure=1013.25, temperature=10.0, delta_t=DEFAULT_DELTA_T, slope=0.0, azimuth_rotation=0.0,
                 refraction=0.5667):
    """The report's algorithm end to end; the dict holds every intermediate the report's example lists."""
    jd = julian_day(year, month, day, hour, minute, second, timezone)
    t = time_scales(jd, delta_t)
    l_h = heliocentric_longitude(t["jme"])
    b_h = heliocentric_latitude(t["jme"])
    r = earth_radius_vector(t["jme"])
    theta = _limit360(l_h + 180.0)
    beta = -b_h
    dpsi, deps = nutation(t["jce"])
    eps = true_obliquity(t["jme"], deps)
    dtau = -20.4898 / (3600.0 * r)
    lam = theta + dpsi + dtau
    nu = sidereal_time(jd, t["jc"], dpsi, eps)
    alpha, delta = _equatorial(lam, beta, eps)
    h = _limit360(nu + longitude - alpha)
    xi = 8.794 / (3600.0 * r)
    alpha_t, delta_t_, h_t = _topocentric(alpha, delta, h, latitude, elevation, xi)
    zenith, azimuth, gamma = _horizontal(delta_t_, h_t, latitude, pressure, temperature, refraction)
    zr, wr = math.radians(zenith), math.radians(slope)
    incidence = math.degrees(math.acos(max(-1.0, min(1.0, math.cos(zr) * math.cos(wr) + math.sin(wr) * math.sin(zr)
                                                       * math.cos(math.radians(gamma - azimuth_rotation))))))
    return {"jd": jd, "jde": t["jde"], "jc": t["jc"], "jce": t["jce"], "jme": t["jme"], "heliocentric_longitude": l_h,
            "heliocentric_latitude": b_h, "radius": r, "geocentric_longitude": theta, "geocentric_latitude": beta,
            "nutation_longitude": dpsi, "nutation_obliquity": deps, "obliquity": eps, "aberration": dtau,
            "apparent_longitude": lam, "sidereal_time": nu, "right_ascension": alpha, "declination": delta,
            "hour_angle": h, "topocentric_right_ascension": alpha_t, "topocentric_declination": delta_t_,
            "topocentric_hour_angle": h_t, "zenith": zenith, "azimuth": azimuth, "incidence": incidence}


def sun_direction(zenith, azimuth):
    """The unit direction toward a body in scene axes (+x east, -y up, +z north) from zenith and azimuth
    (degrees, azimuth from north eastward)."""
    zr, ar = math.radians(zenith), math.radians(azimuth)
    return (math.sin(zr) * math.sin(ar), -math.cos(zr), math.sin(zr) * math.cos(ar))


def _check_observer(date, latitude, longitude, altitude, pressure, temperature, delta_t):
    parts = parse_datetime(date)
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        raise SkyError("latitude is -90 to 90 and longitude -180 to 180")
    if not (pressure >= 0.0) or not math.isfinite(pressure) or not math.isfinite(temperature) or temperature <= -273.0:
        raise SkyError("pressure is at least 0 hPa and temperature above absolute zero")
    if not (SPA_YEARS[0] <= parts[0] <= SPA_YEARS[1]):
        raise SkyError("the solar position algorithm covers the years -2000 to 6000")
    if delta_t is None:
        if not (DELTA_T_FREE_YEARS[0] <= parts[0] <= DELTA_T_FREE_YEARS[1]):
            raise SkyError("deltaT must be given for dates outside 1900 to 2100")
        delta_t = DEFAULT_DELTA_T
    if not (DELTA_T_RANGE[0] <= delta_t <= DELTA_T_RANGE[1]):
        raise SkyError("deltaT is -8000 to 8000 seconds")
    if not math.isfinite(altitude):
        raise SkyError("altitude is a finite number of metres")
    return parts, delta_t


def sun_from_document(date, latitude, longitude, altitude=0.0, pressure=1013.25, temperature=10.0, delta_t=None):
    """The sun of a dome light with `sky="physical"` and a `date` (rule 6)."""
    (y, mo, d, h, mi, s, tz), delta_t = _check_observer(date, latitude, longitude, altitude, pressure, temperature,
                                                      delta_t)
    out = sun_position(y, mo, d, h, mi, s, tz, longitude, latitude, altitude, pressure, temperature, delta_t)
    out["direction"] = sun_direction(out["zenith"], out["azimuth"])
    return out


# ------------------------------------------------------------------------------------ rule 7: the moon

_ARCS = 3600.0 * 180.0 / math.pi


def _frac(x):
    return x - math.floor(x)


def moon_position(jde):
    """Geocentric ecliptic longitude and latitude (degrees, of the date) by the low-precision series of
    Montenbruck and Pfleger, and the distance (km) from the Almanac's horizontal parallax."""
    t = (jde - 2451545.0) / 36525.0
    two_pi = 2.0 * math.pi
    l0 = _frac(0.606433 + 1336.855225 * t)
    l = two_pi * _frac(0.374897 + 1325.552410 * t)
    ls = two_pi * _frac(0.993133 + 99.997361 * t)
    d = two_pi * _frac(0.827361 + 1236.853086 * t)
    f = two_pi * _frac(0.259086 + 1342.227825 * t)
    sin = math.sin
    dl = (22640 * sin(l) - 4586 * sin(l - 2 * d) + 2370 * sin(2 * d) + 769 * sin(2 * l) - 668 * sin(ls)
          - 412 * sin(2 * f) - 212 * sin(2 * l - 2 * d) - 206 * sin(l + ls - 2 * d) + 192 * sin(l + 2 * d)
          - 165 * sin(ls - 2 * d) - 125 * sin(d) - 110 * sin(l + ls) + 148 * sin(l - ls) - 55 * sin(2 * f - 2 * d))
    s = f + (dl + 412 * sin(2 * f) + 541 * sin(ls)) / _ARCS
    h = f - 2 * d
    n = (-526 * sin(h) + 44 * sin(l + h) - 31 * sin(-l + h) - 23 * sin(ls + h) + 11 * sin(-ls + h)
         - 25 * sin(-2 * l + f) + 21 * sin(-l + f))
    lon = two_pi * _frac(l0 + dl / 1296000.0)
    lat = (18520 * sin(s) + n) / _ARCS
    parallax = 0.9508 + 0.0518 * math.cos(l) + 0.0095 * math.cos(l - 2 * d) + 0.0078 * math.cos(2 * d) + 0.0028 * math.cos(2 * l)
    distance = EARTH_RADIUS_KM / math.sin(math.radians(parallax))
    return {"longitude": math.degrees(lon), "latitude": math.degrees(lat), "distance": distance,
            "parallax": parallax}


def moon_from_document(date, latitude, longitude, altitude=0.0, pressure=1013.25, temperature=10.0, delta_t=None,
                       topocentric=True):
    """The moon placed by the same observer as the sun (rule 7): zenith, azimuth, angular diameter and the
    illuminated fraction."""
    (y, mo, d, h, mi, s, tz), delta_t = _check_observer(date, latitude, longitude, altitude, pressure, temperature,
                                                      delta_t)
    sun = sun_position(y, mo, d, h, mi, s, tz, longitude, latitude, altitude, pressure, temperature, delta_t)
    m = moon_position(sun["jde"])
    lam = m["longitude"] + sun["nutation_longitude"]
    alpha, delta = _equatorial(lam, m["latitude"], sun["obliquity"])
    hour = _limit360(sun["sidereal_time"] + longitude - alpha)
    if topocentric:
        alpha_t, delta_t_, h_t = _topocentric(alpha, delta, hour, latitude, altitude, m["parallax"])
    else:
        alpha_t, delta_t_, h_t = alpha, delta, hour
    zenith, azimuth, _ = _horizontal(delta_t_, h_t, latitude, pressure, temperature, 0.5667)
    # Phase: the elongation from the sun and the phase angle with the two distances (Meeus 48.2 and 48.3).
    psi = math.acos(max(-1.0, min(1.0, math.cos(math.radians(m["latitude"]))
                                  * math.cos(math.radians(m["longitude"] - sun["geocentric_longitude"])))))
    r_sun = sun["radius"] * AU_KM
    i = math.atan2(r_sun * math.sin(psi), m["distance"] - r_sun * math.cos(psi))
    return {"zenith": zenith, "azimuth": azimuth, "distance": m["distance"],
            "angular_diameter": math.degrees(2.0 * math.asin(MOON_RADIUS_KM / m["distance"])),
            "illuminated": (1.0 + math.cos(i)) / 2.0, "phase_angle": math.degrees(i),
            "direction": sun_direction(zenith, azimuth)}


# ------------------------------------------------------------------------------------ rules 8 to 10: the atmosphere


def atmosphere(planet_radius=6360000.0, top_radius=6460000.0, rayleigh_scattering=(5.802e-6, 13.558e-6, 33.1e-6),
               rayleigh_scale=8000.0, mie_scattering=3.996e-6, mie_absorption=4.4e-6, mie_scale=1200.0,
               mie_anisotropy=0.8, ozone_absorption=(0.650e-6, 1.881e-6, 0.085e-6), ozone_centre=25000.0,
               ozone_width=15000.0, aerosol=1.0, ozone=1.0, ground_albedo=0.3, sun_irradiance=(1.0, 1.0, 1.0)):
    """Hillaire's Earth (rule 8): the values are per metre; `aerosol` and `ozone` scale the Mie and ozone
    layers."""
    if not (planet_radius > 0.0) or not (top_radius > planet_radius):
        raise SkyError("the planet radius is positive and the atmosphere's top radius larger")
    if not (aerosol >= 0.0) or not (ozone >= 0.0) or not (rayleigh_scale > 0.0) or not (mie_scale > 0.0):
        raise SkyError("aerosol, ozone and the scale heights are non-negative")
    if not (-1.0 < mie_anisotropy < 1.0):
        raise SkyError("the Mie anisotropy is strictly between -1 and 1")
    if not (0.0 <= ground_albedo <= 1.0) or not (ozone_width > 0.0):
        raise SkyError("the ground albedo is 0 to 1 and the ozone width positive")
    return {"planet_radius": float(planet_radius), "top_radius": float(top_radius),
            "rayleigh_scattering": tuple(rayleigh_scattering), "rayleigh_scale": float(rayleigh_scale),
            "mie_scattering": mie_scattering * aerosol, "mie_absorption": mie_absorption * aerosol,
            "mie_scale": float(mie_scale), "mie_anisotropy": float(mie_anisotropy),
            "ozone_absorption": tuple(o * ozone for o in ozone_absorption), "ozone_centre": float(ozone_centre),
            "ozone_width": float(ozone_width), "ground_albedo": float(ground_albedo),
            "sun_irradiance": tuple(sun_irradiance)}


def _height(a, p):
    return _norm(p) - a["planet_radius"]


def rayleigh_density(a, h):
    top = a["top_radius"] - a["planet_radius"]
    return math.exp(-h / a["rayleigh_scale"]) if 0.0 <= h <= top else 0.0


def mie_density(a, h):
    top = a["top_radius"] - a["planet_radius"]
    return math.exp(-h / a["mie_scale"]) if 0.0 <= h <= top else 0.0


def ozone_density(a, h):
    return max(0.0, 1.0 - abs(h - a["ozone_centre"]) / a["ozone_width"])


def _extinction(a, h):
    r, m, o = rayleigh_density(a, h), mie_density(a, h), ozone_density(a, h)
    return tuple(a["rayleigh_scattering"][c] * r + (a["mie_scattering"] + a["mie_absorption"]) * m
                 + a["ozone_absorption"][c] * o for c in range(3))


def _scattering(a, h):
    """(Rayleigh, Mie) scattering coefficients per channel at height h."""
    r, m = rayleigh_density(a, h), mie_density(a, h)
    return tuple(a["rayleigh_scattering"][c] * r for c in range(3)), a["mie_scattering"] * m


def _sphere_hit(p, d, radius):
    """The distance along d from p to the sphere about the origin of the radius: the nearest positive root,
    or None."""
    b = _dot(p, d)
    c = _dot(p, p) - radius * radius
    disc = b * b - c
    if disc < 0.0:
        return None
    s = math.sqrt(disc)
    t0, t1 = -b - s, -b + s
    if t1 < 0.0:
        return None
    return t0 if t0 >= 0.0 else t1


def hits_ground(a, p, d):
    """Whether the ray from p along d meets the planet before leaving the atmosphere."""
    return _path_end(a, p, d)[2]


def _path_end(a, p, d):
    """The distance along the ray to the atmosphere, the length of the ray inside it, and whether it ends
    on the ground. A ray that starts on the ground and heads inward has length 0 and ends on the ground."""
    r = _norm(p)
    if r < a["planet_radius"] - 1e-6:
        raise SkyError("the observer is below the ground")
    if r > a["top_radius"]:
        t_in = _sphere_hit(p, d, a["top_radius"])
        if t_in is None:
            return 0.0, 0.0, False
        start = t_in
    else:
        start = 0.0
    q = march(p, d, start)
    if _dot(q, d) < 0.0:
        tg = _sphere_hit(q, d, a["planet_radius"])
        if tg is not None:
            return start, tg, True
    # The far exit from the top sphere.
    b = _dot(q, d)
    c = _dot(q, q) - a["top_radius"] ** 2
    disc = max(0.0, b * b - c)
    return start, -b + math.sqrt(disc), False


_GL = ((-0.8611363115940526, 0.3478548451374538), (-0.3399810435848563, 0.6521451548625461),
       (0.3399810435848563, 0.6521451548625461), (0.8611363115940526, 0.3478548451374538))


def _segments(length, samples, cluster):
    """Segment ends along a path: uniform, or quadratically clustered toward the start."""
    if cluster:
        return [length * (i / samples) ** 2 for i in range(samples + 1)]
    return [length * i / samples for i in range(samples + 1)]


def _depth(a, p, d, s0, s1):
    """Optical depth of the segment [s0, s1] along d from p by 4-point Gauss-Legendre."""
    half = (s1 - s0) / 2.0
    mid = (s1 + s0) / 2.0
    out = [0.0, 0.0, 0.0]
    for x, w in _GL:
        e = _extinction(a, _height(a, march(p, d, mid + half * x)))
        for c in range(3):
            out[c] += w * e[c]
    return tuple(o * half for o in out)


def transmittance(a, p, d, samples=64, length=None, cluster=True):
    """Rule 9: exp of minus the optical depth from p along d to the top of the atmosphere (or over
    `length`); zero when the ray meets the ground first."""
    if not (1 <= samples <= MAX_SAMPLES):
        raise SkyError("samples is 1 to %d" % MAX_SAMPLES)
    start, total, ground = _path_end(a, p, d)
    if ground and (length is None or length >= start + total):
        return (0.0, 0.0, 0.0)
    if length is not None:
        total = max(0.0, min(total, length - start))
    if total <= 0.0:
        return (1.0, 1.0, 1.0)
    q = march(p, d, start)
    ends = _segments(total, samples, cluster)
    depth = [0.0, 0.0, 0.0]
    for i in range(samples):
        seg = _depth(a, q, d, ends[i], ends[i + 1])
        for c in range(3):
            depth[c] += seg[c]
    return tuple(math.exp(-x) for x in depth)


def rayleigh_phase(mu):
    return 3.0 / (16.0 * math.pi) * (1.0 + mu * mu)


def hg_phase(mu, g):
    return (1.0 - g * g) / (4.0 * math.pi * (1.0 + g * g - 2.0 * g * mu) ** 1.5)


def integrate_phase(f, n=2000):
    """2 pi times the Simpson integral of f over mu in [-1, 1]."""
    h = 2.0 / n
    s = f(-1.0) + f(1.0)
    for i in range(1, n):
        s += (4.0 if i % 2 else 2.0) * f(-1.0 + i * h)
    return 2.0 * math.pi * s * h / 3.0


def _fibonacci_sphere(n):
    out = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n):
        z = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - z * z))
        t = golden * i
        out.append((r * math.cos(t), r * math.sin(t), z))
    return out

_MS_CACHE = {}
MS_HEIGHTS = 8
MS_COSINES = 8
MS_DIRECTIONS = 32
MS_SAMPLES = 6


def _ms_key(a):
    return tuple(sorted((k, v) for k, v in a.items()))


def _ms_cell(a, h, mu_s):
    """Hillaire's isotropic multiple-scattering estimate at height h and sun cosine mu_s: the second-order
    radiance L2 over (1 - f), f the fraction scattered again, both integrated over the sphere of directions
    with the uniform phase 1 / 4 pi (per channel), including a Lambertian ground."""
    p = (0.0, 0.0, a["planet_radius"] + h)
    sun = (math.sqrt(max(0.0, 1.0 - mu_s * mu_s)), 0.0, mu_s)
    l2 = [0.0, 0.0, 0.0]
    f = [0.0, 0.0, 0.0]
    dw = 4.0 * math.pi / MS_DIRECTIONS
    for d in _fibonacci_sphere(MS_DIRECTIONS):
        start, total, ground = _path_end(a, p, d)
        if total <= 0.0:
            continue
        q = march(p, d, start)
        ends = _segments(total, MS_SAMPLES, True)
        trans = [1.0, 1.0, 1.0]
        for i in range(MS_SAMPLES):
            s0, s1 = ends[i], ends[i + 1]
            seg = _depth(a, q, d, s0, s1)
            mid = march(q, d, (s0 + s1) / 2.0)
            t_mid = [trans[c] * math.exp(-seg[c] / 2.0) for c in range(3)]
            hm = _height(a, mid)
            sr, sm = _scattering(a, hm)
            t_sun = transmittance(a, mid, sun, samples=8)
            for c in range(3):
                sig = sr[c] + sm
                f[c] += t_mid[c] * sig / (4.0 * math.pi) * (s1 - s0) * dw
                l2[c] += t_mid[c] * sig / (4.0 * math.pi) * a["sun_irradiance"][c] * t_sun[c] * (s1 - s0) * dw
            for c in range(3):
                trans[c] *= math.exp(-seg[c])
        if ground:
            g = march(q, d, total)
            n = unit(g)
            cos_sun = max(0.0, _dot(n, sun))
            t_sun = transmittance(a, g, sun, samples=8) if cos_sun > 0.0 else (0.0, 0.0, 0.0)
            for c in range(3):
                l2[c] += trans[c] * a["ground_albedo"] / math.pi * a["sun_irradiance"][c] * t_sun[c] * cos_sun / (4.0 * math.pi) * dw
    return tuple(l2[c] / (1.0 - f[c]) for c in range(3)), tuple(f)


def _ms_lookup(a, h, mu_s):
    """Bilinear interpolation of the lazily filled (height, sun cosine) table."""
    key = _ms_key(a)
    table = _MS_CACHE.setdefault(key, {})
    top = a["top_radius"] - a["planet_radius"]
    hf = max(0.0, min(1.0, h / top)) * (MS_HEIGHTS - 1)
    mf = (max(-1.0, min(1.0, mu_s)) + 1.0) / 2.0 * (MS_COSINES - 1)
    i0, j0 = int(math.floor(hf)), int(math.floor(mf))
    i1, j1 = min(i0 + 1, MS_HEIGHTS - 1), min(j0 + 1, MS_COSINES - 1)
    ti, tj = hf - i0, mf - j0
    out = [0.0, 0.0, 0.0]
    for i, wi in ((i0, 1.0 - ti), (i1, ti)):
        for j, wj in ((j0, 1.0 - tj), (j1, tj)):
            if wi * wj == 0.0:
                continue
            if (i, j) not in table:
                table[(i, j)] = _ms_cell(a, top * i / (MS_HEIGHTS - 1), -1.0 + 2.0 * j / (MS_COSINES - 1))
            psi = table[(i, j)][0]
            for c in range(3):
                out[c] += wi * wj * psi[c]
    return tuple(out)


def multiple_scattering_factor(a, h, mu_s):
    """The fraction f of light scattered once more, per channel, at the table cell nearest (h, mu_s)."""
    return _ms_cell(a, h, mu_s)[1]


def _inscatter(a, p, d, sun, samples, multiple, length=None):
    """The in-scattered radiance along d from p (to `length` or the atmosphere's end) and the transmittance
    to that end."""
    if not (1 <= samples <= MAX_SAMPLES):
        raise SkyError("samples is 1 to %d" % MAX_SAMPLES)
    start, total, ground = _path_end(a, p, d)
    if length is not None:
        total = max(0.0, min(total, length - start))
    if total <= 0.0:
        return (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    q = march(p, d, start)
    ends = _segments(total, samples, True)
    mu = _dot(d, sun)
    pr, pm = rayleigh_phase(mu), hg_phase(mu, a["mie_anisotropy"])
    trans = [1.0, 1.0, 1.0]
    out = [0.0, 0.0, 0.0]
    for i in range(samples):
        s0, s1 = ends[i], ends[i + 1]
        half, mid = (s1 - s0) / 2.0, (s1 + s0) / 2.0
        inner = [0.0, 0.0, 0.0]
        for x, w in _GL:
            # Transmittance from the segment start to the node, then the scattering at the node.
            s = mid + half * x
            node_depth = _depth(a, q, d, s0, s) if s > s0 else (0.0, 0.0, 0.0)
            y = march(q, d, s)
            hy = _height(a, y)
            sr, sm = _scattering(a, hy)
            t_sun = transmittance(a, y, sun, samples=8)
            mu_s = _dot(unit(y), sun)
            psi = _ms_lookup(a, hy, mu_s) if multiple else (0.0, 0.0, 0.0)
            for c in range(3):
                t_node = trans[c] * math.exp(-node_depth[c])
                single = (sr[c] * pr + sm * pm) * a["sun_irradiance"][c] * t_sun[c]
                inner[c] += w * t_node * (single + (sr[c] + sm) * psi[c])
        seg = _depth(a, q, d, s0, s1)
        for c in range(3):
            out[c] += inner[c] * half
            trans[c] *= math.exp(-seg[c])
    return tuple(out), tuple(trans)


def sky_radiance(a, obs, d, sun, multiple=True, samples=32):
    """Rule 9: the sky's radiance in the unit direction d from the observer; zero for directions that meet
    the ground (rule 10's aerial perspective covers what is seen there) or miss the atmosphere."""
    r = _norm(obs)
    if r < a["planet_radius"] - 1e-6:
        raise SkyError("the observer is below the ground")
    start, total, ground = _path_end(a, obs, d)
    if ground or total <= 0.0:
        return (0.0, 0.0, 0.0)
    return _inscatter(a, obs, d, sun, samples, multiple)[0]


def sun_radiance(a, obs, d):
    """The sun disc seen along d: the irradiance times the transmittance; zero through the ground."""
    t = transmittance(a, obs, d)
    return tuple(a["sun_irradiance"][c] * t[c] for c in range(3))


def sky_irradiance(a, obs, sun, zenith_steps=6, azimuth_steps=12):
    """Irradiance on the ground from the sky by a midpoint grid over the hemisphere."""
    out = [0.0, 0.0, 0.0]
    up = unit(obs)
    for i in range(zenith_steps):
        theta = (i + 0.5) / zenith_steps * (math.pi / 2.0)
        for j in range(azimuth_steps):
            phi = (j + 0.5) / azimuth_steps * 2.0 * math.pi
            d = (math.sin(theta) * math.cos(phi), math.sin(theta) * math.sin(phi), math.cos(theta))
            if up != (0.0, 0.0, 1.0):
                raise SkyError("the irradiance is evaluated at an observer on the z axis")
            l = sky_radiance(a, obs, d, sun, samples=16)
            w = math.cos(theta) * math.sin(theta) * (math.pi / 2.0 / zenith_steps) * (2.0 * math.pi / azimuth_steps)
            for c in range(3):
                out[c] += l[c] * w
    return tuple(out)


def aerial_perspective(a, obs, d, distance, colour, sun, samples=16):
    """Rule 10: a surface of the colour at the distance along d is seen through the atmosphere as colour
    times the transmittance plus the in-scattering up to it; at distance 0 the colour itself."""
    if distance <= 0.0:
        return tuple(colour)
    inscatter, trans = _inscatter(a, obs, d, sun, samples, True, length=distance)
    return tuple(colour[c] * trans[c] + inscatter[c] for c in range(3))


def limb_direction(a, obs, degrees=0.0):
    """From an observer on the z axis above the atmosphere: the unit direction in the x-z plane grazing
    the planet's limb (the ground horizon), turned `degrees` toward the nadir (positive) or away
    (negative). The atmosphere is seen between this direction and the one grazing its top."""
    r = _norm(obs)
    if r <= a["top_radius"]:
        raise SkyError("the limb is seen from above the atmosphere")
    gamma = math.asin(a["planet_radius"] / r) - math.radians(degrees)
    return (math.sin(gamma), 0.0, -math.cos(gamma))


# ------------------------------------------------------------------------------------ rule 11: height fog


def fog(density, height):
    if not (density >= 0.0) or not (height > 0.0) or not math.isfinite(density) or not math.isfinite(height):
        raise SkyError("fogDensity is non-negative and fogHeight positive")
    return {"density": float(density), "height": float(height)}


def fog_transmittance(f, h0, h1, length):
    """Transmittance of a segment of the length from altitude h0 to h1 through fog of density
    `density` e^(-h / height): closed form."""
    if length <= 0.0:
        return 1.0
    hs = f["height"]
    if h0 == h1:
        depth = f["density"] * length * math.exp(-h0 / hs)
    else:
        depth = f["density"] * length * hs / (h1 - h0) * (math.exp(-h0 / hs) - math.exp(-h1 / hs))
    return math.exp(-depth)


# ------------------------------------------------------------------------------------ the frame and the checks


def sky_frame(date, latitude, longitude, direction, altitude=0.0):
    """One frame's sky: the sun from the document and the radiance in the direction (rule 12)."""
    a = atmosphere()
    s = sun_from_document(date, latitude, longitude, altitude)
    sun = (s["direction"][0], s["direction"][2], -s["direction"][1])
    obs = (0.0, 0.0, a["planet_radius"] + max(0.0, altitude) + 1.0)
    return (s["zenith"], s["azimuth"], sky_radiance(a, obs, unit(direction), sun, samples=8))


EXAMPLE = dict(year=2003, month=10, day=17, hour=12, minute=30, second=30.0, timezone=-7.0, longitude=-105.1786,
               latitude=39.742476, elevation=1830.14, pressure=820.0, temperature=11.0, delta_t=67.0, slope=30.0,
               azimuth_rotation=-10.0, refraction=0.5667)


def spa_test():
    s = sun_position(**EXAMPLE)
    return (abs(s["zenith"] - 50.11162) <= 1e-3, abs(s["azimuth"] - 194.34024) <= 1e-3, abs(s["incidence"] - 25.18700) <= 1e-3)


def moon_test():
    m = moon_position(2448724.5)
    return (abs(m["longitude"] - 133.162655) <= 0.05, abs(m["latitude"] + 3.229126) <= 0.02,
            abs(m["distance"] - 368409.7) <= 3700.0)


def transmittance_test():
    a = atmosphere(ozone=0.0)
    t = transmittance(a, (0.0, 0.0, a["planet_radius"]), (0.0, 0.0, 1.0))
    out = []
    for c in range(3):
        depth = (a["rayleigh_scattering"][c] * a["rayleigh_scale"] * (1 - math.exp(-100000.0 / a["rayleigh_scale"]))
                 + (a["mie_scattering"] + a["mie_absorption"]) * a["mie_scale"] * (1 - math.exp(-100000.0 / a["mie_scale"])))
        out.append(abs(t[c] - math.exp(-depth)) <= 1e-6)
    return tuple(out)


def _ground_observer(a, h=1.0):
    return (0.0, 0.0, a["planet_radius"] + h)


def quadrature_test():
    a = atmosphere()
    sun = unit((1.0, 0.0, 0.5))
    d = unit((0.3, 0.4, 0.6))
    coarse = sky_radiance(a, _ground_observer(a), d, sun, multiple=False, samples=32)
    fine = sky_radiance(a, _ground_observer(a), d, sun, multiple=False, samples=512)
    return (all(abs(coarse[c] - fine[c]) <= 1e-3 * fine[c] for c in range(3)), fine[2] > fine[0] > 0.0)


def energy_test():
    a = atmosphere()
    f = multiple_scattering_factor(a, 1.0, 0.5)
    irr = sky_irradiance(a, _ground_observer(a), unit((1.0, 0.0, 0.5)))
    return (all(0.0 < x < 1.0 for x in f), all(0.0 < e < 1.0 for e in irr))


def aerial_test():
    a = atmosphere()
    sun = unit((1.0, 0.0, 0.5))
    d = (1.0, 0.0, 0.0)
    colour = (0.2, 0.4, 0.1)
    near = aerial_perspective(a, _ground_observer(a), d, 1000.0, colour, sun)
    far = aerial_perspective(a, _ground_observer(a), d, 50000.0, colour, sun)
    sky = sky_radiance(a, _ground_observer(a), d, sun)
    return (aerial_perspective(a, _ground_observer(a), d, 0.0, colour, sun) == colour,
            all(abs(far[c] - sky[c]) < abs(near[c] - sky[c]) for c in range(3)))


def fog_test():
    f = fog(0.001, 100.0)
    return (fog_transmittance(f, 0.0, 0.0, 1000.0) == math.exp(-1.0),
            abs(fog_transmittance(f, 0.0, 50.0, 1000.0) - math.exp(-0.001 * 1000.0 * 2.0 * (1 - math.exp(-0.5)))) <= 1e-12)


def seek_test():
    args = ("2003-10-17T12:30:30-07:00", 39.742476, -105.1786, (0.0, 0.0, 1.0))
    first = sky_frame(*args)
    sky_frame("2003-10-17T18:30:30-07:00", 39.742476, -105.1786, (0.0, 0.0, 1.0))
    return (first == sky_frame(*args), first[2][2] > 0.0)


def zenith_radiance():
    a = atmosphere()
    return sky_radiance(a, _ground_observer(a), (0.0, 0.0, 1.0), unit((1.0, 0.0, 1.0)))


# ------------------------------------------------------------------------------------ the numeric table

TABLE = (
    ("julian day", "round(julian_day(2003, 10, 17, 12, 30, 30.0, -7.0), 6)", "2452930.312847"),
    ("epoch", "julian_day(2000, 1, 1, 12, 0, 0.0, 0.0)", "2451545.0"),
    ("date", "parse_datetime('2003-10-17T12:30:30-07:00')", "(2003, 10, 17, 12, 30, 30.0, -7.0)"),
    ("heliocentric longitude", "round(heliocentric_longitude(time_scales(julian_day(2003, 10, 17, 12, 30, 30.0, -7.0), 67.0)['jme']), 7)", "24.0182617"),
    ("heliocentric latitude", "round(heliocentric_latitude(time_scales(julian_day(2003, 10, 17, 12, 30, 30.0, -7.0), 67.0)['jme']), 9)", "-0.000101122"),
    ("radius vector", "round(earth_radius_vector(time_scales(julian_day(2003, 10, 17, 12, 30, 30.0, -7.0), 67.0)['jme']), 9)", "0.996542297"),
    ("nutation", "tuple(round(x, 8) for x in nutation(time_scales(julian_day(2003, 10, 17, 12, 30, 30.0, -7.0), 67.0)['jce']))", "(-0.0039984, 0.00166657)"),
    ("obliquity", "round(sun_position(**EXAMPLE)['obliquity'], 6)", "23.440465"),
    ("apparent longitude", "round(sun_position(**EXAMPLE)['apparent_longitude'], 7)", "204.0085519"),
    ("right ascension", "round(sun_position(**EXAMPLE)['right_ascension'], 5)", "202.22741"),
    ("declination", "round(sun_position(**EXAMPLE)['declination'], 5)", "-9.31434"),
    ("hour angle", "round(sun_position(**EXAMPLE)['hour_angle'], 6)", "11.105902"),
    ("topocentric", "tuple(round(sun_position(**EXAMPLE)[k], 5) for k in ('topocentric_right_ascension', 'topocentric_declination', 'topocentric_hour_angle'))", "(202.22704, -9.31618, 11.10627)"),
    ("zenith", "round(sun_position(**EXAMPLE)['zenith'], 5)", "50.11162"),
    ("azimuth", "round(sun_position(**EXAMPLE)['azimuth'], 5)", "194.34024"),
    ("incidence", "round(sun_position(**EXAMPLE)['incidence'], 5)", "25.187"),
    ("spa test", "spa_test()", "(True, True, True)"),
    ("refraction", "round(refraction_correction(89.0, 1013.25, 10.0), 6)", "0.363564"),
    ("sun direction", "tuple(round(c, 12) for c in sun_direction(120.0, 0.0))", "(0.0, 0.5, 0.866025403784)"),
    ("moon longitude", "round(moon_position(2448724.5)['longitude'], 4)", "133.1571"),
    ("moon latitude", "round(moon_position(2448724.5)['latitude'], 4)", "-3.2268"),
    ("moon distance", "round(moon_position(2448724.5)['distance'], 1)", "368074.2"),
    ("moon test", "moon_test()", "(True, True, True)"),
    ("moon diameter", "round(moon_from_document('2003-10-17T12:30:30-07:00', 39.742476, -105.1786, altitude=1830.14, delta_t=67.0)['angular_diameter'], 4)", "0.4991"),
    ("full moon", "round(moon_from_document('2003-11-09T01:13:00Z', 0.0, 0.0)['illuminated'], 4)", "1.0"),
    ("new moon", "round(moon_from_document('2003-10-25T12:50:00Z', 0.0, 0.0)['illuminated'], 4)", "0.0002"),
    ("ozone profile", "(ozone_density(atmosphere(), 25000.0), ozone_density(atmosphere(), 17500.0), ozone_density(atmosphere(), 40000.0))", "(1.0, 0.5, 0.0)"),
    ("vertical transmittance", "tuple(round(x, 6) for x in transmittance(atmosphere(), (0.0, 0.0, 6360000.0), (0.0, 0.0, 1.0)))", "(0.935904, 0.863504, 0.7587)"),
    ("transmittance test", "transmittance_test()", "(True, True, True)"),
    ("ground", "transmittance(atmosphere(), (0.0, 0.0, 6360010.0), unit((1.0, 0.0, -0.1)))", "(0.0, 0.0, 0.0)"),
    ("rayleigh phase", "round(rayleigh_phase(0.0) * 16.0 * math.pi, 12)", "3.0"),
    ("hg normalisation", "round(integrate_phase(lambda mu: hg_phase(mu, 0.8)), 6)", "1.0"),
    ("zenith radiance", "tuple(round(x, 6) for x in zenith_radiance())", "(0.008623, 0.025027, 0.085859)"),
    ("quadrature test", "quadrature_test()", "(True, True)"),
    ("multiple scattering factor", "tuple(round(x, 4) for x in multiple_scattering_factor(atmosphere(), 1.0, 0.5))", "(0.073, 0.1338, 0.2306)"),
    ("energy test", "energy_test()", "(True, True)"),
    ("aerial test", "aerial_test()", "(True, True)"),
    ("fog", "round(fog_transmittance(fog(0.001, 100.0), 0.0, 50.0, 1000.0), 9)", "0.455236288"),
    ("fog test", "fog_test()", "(True, True)"),
    ("limb", "tuple(round(c, 6) for c in limb_direction(atmosphere(), (0.0, 0.0, 6760000.0)))", "(0.940828, 0.0, -0.338883)"),
    ("seek test", "seek_test()", "(True, True)"),
)


def scope():
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    return s


def _same(a, b, tol=1e-9):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def main():
    s = scope()
    for name, expr, expected in TABLE:
        got = eval(expr, s)
        if isinstance(got, float):
            got = repr(got)
        print("| %s | `%s` | `%s` |" % (name, expr, got))


if __name__ == "__main__":
    main()
