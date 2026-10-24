"""Reference implementation of the draft SREP "Add time scales, celestial frames and JPL ephemerides"
(srep/srep-0000-time-frames.md; SP1 of SREP 12, SRC-44).

Standard library only. The module gives:

- the calendar and the time scales UTC, TAI, TT and TDB (leap seconds from NAIF's naif0012.tls, the TDB
  formula and constants of the same file) and the frame clock of a `space` element;
- a reader for JPL SPK files in the DAF format (type 2 Chebyshev segments, either byte order) pinned by a
  sha256 digest, with the chain of centres to the solar system barycentre, velocities and light time; a writer
  of excerpts (the kit's fixture conformance/assets/de440s-excerpt.bsp is one);
- the approximate Keplerian elements of Standish and Williams (JPL) as the fallback;
- the ICRF, the ecliptic of J2000 and the body-fixed frames of the IAU 2009 rotation elements (pck00010.tpc),
  and the mapping of positions into scene pixels (SREP 14 rule 4);
- `main()` prints the draft's numeric table.
"""
import datetime
import hashlib
import json
import math
import os
import re
import struct

MAX_SEGMENTS = 4096
MAX_KEPLER_ITERATIONS = 50
MAX_LIGHT_TIME_ITERATIONS = 5
C_KM_S = 299792.458
AU_KM = 149597870.7
OBLIQUITY_J2000 = 23.43928
J2000_JD = 2451545.0
TT_MINUS_TAI = 32.184
TDB_K = 1.657e-3
TDB_EB = 1.671e-2
TDB_M0 = 6.239996
TDB_M1 = 1.99096871e-7
DE440S_DIGEST = "c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2"
EXCERPT_DIGEST = "d113bb5117946244cf63de9d06287d5aac008acd1a561d28b760bcc7d4c3d1fd"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXCERPT_PATH = os.path.join(ROOT, "conformance", "assets", "de440s-excerpt.bsp")
HORIZONS_PATH = os.path.join(ROOT, "conformance", "assets", "horizons-vectors.json")


class FrameError(ValueError):
    """A document value or file the draft rejects."""


# ------------------------------------------------------------------------------------ rule 1: calendar and time scales


def julian_day(year, month, day, hour=0, minute=0, second=0.0):
    """The Julian day of a proleptic Gregorian date (Meeus, chapter 7)."""
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100.0)
    b = 2 - a + math.floor(a / 4.0)
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + day + b - 1524.5
            + (hour + minute / 60.0 + second / 3600.0) / 24.0)


def calendar(jd):
    """The proleptic Gregorian date of a Julian day: (year, month, day, hour, minute, second)."""
    z = math.floor(jd + 0.5)
    f = jd + 0.5 - z
    alpha = math.floor((z - 1867216.25) / 36524.25)
    a = z + 1 + alpha - math.floor(alpha / 4.0)
    b = a + 1524
    c = math.floor((b - 122.1) / 365.25)
    d = math.floor(365.25 * c)
    e = math.floor((b - d) / 30.6001)
    day = int(b - d - math.floor(30.6001 * e))
    month = int(e - 1 if e < 14 else e - 13)
    year = int(c - 4716 if month > 2 else c - 4715)
    seconds = f * 86400.0
    hour = int(seconds // 3600.0)
    minute = int((seconds - hour * 3600.0) // 60.0)
    return (year, month, day, hour, minute, seconds - hour * 3600.0 - minute * 60.0)


_UTC = re.compile(r"^(-?\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:\d{2})$")


def parse_utc(text):
    """`YYYY-MM-DDThh:mm:ss[.f](Z|+hh:mm)` into the UTC (year, month, day, hour, minute, second)."""
    m = _UTC.match(text or "")
    if not m:
        raise FrameError("a UTC epoch is YYYY-MM-DDThh:mm:ss with Z or a +hh:mm offset: %r" % (text,))
    y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
    s = float(m.group(6))
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 0 <= h <= 23 and 0 <= mi <= 59 and 0.0 <= s < 60.0):
        raise FrameError("the epoch has a field out of range: %r" % (text,))
    z = m.group(7)
    offset = 0 if z == "Z" else (1 if z[0] == "+" else -1) * (int(z[1:3]) * 60 + int(z[4:6]))
    try:
        local = datetime.datetime(y, mo, d, h, mi)
    except ValueError as exc:
        raise FrameError("the epoch is not a calendar date: %r" % (text,)) from exc
    utc = local - datetime.timedelta(minutes=offset)
    return (utc.year, utc.month, utc.day, utc.hour, utc.minute, s)


# NAIF naif0012.tls, DELTET/DELTA_AT: TAI - UTC after each leap second, from 1972-01-01.
LEAP_SECONDS = (
    (10, (1972, 1, 1)), (11, (1972, 7, 1)), (12, (1973, 1, 1)), (13, (1974, 1, 1)), (14, (1975, 1, 1)),
    (15, (1976, 1, 1)), (16, (1977, 1, 1)), (17, (1978, 1, 1)), (18, (1979, 1, 1)), (19, (1980, 1, 1)),
    (20, (1981, 7, 1)), (21, (1982, 7, 1)), (22, (1983, 7, 1)), (23, (1985, 7, 1)), (24, (1988, 1, 1)),
    (25, (1990, 1, 1)), (26, (1991, 1, 1)), (27, (1992, 7, 1)), (28, (1993, 7, 1)), (29, (1994, 7, 1)),
    (30, (1996, 1, 1)), (31, (1997, 7, 1)), (32, (1999, 1, 1)), (33, (2006, 1, 1)), (34, (2009, 1, 1)),
    (35, (2012, 7, 1)), (36, (2015, 7, 1)), (37, (2017, 1, 1)),
)
_LEAP_JD = tuple((julian_day(*date), n) for n, date in LEAP_SECONDS)


def leap_seconds(jd_utc):
    """TAI - UTC in whole seconds at a UTC Julian day; dates before 1972 are refused."""
    if jd_utc < _LEAP_JD[0][0]:
        raise FrameError("UTC with leap seconds starts on 1972-01-01")
    out = _LEAP_JD[0][1]
    for start, n in _LEAP_JD:
        if jd_utc >= start:
            out = n
    return out


def tai_from_utc(jd_utc):
    return jd_utc + leap_seconds(jd_utc) / 86400.0


def tt_from_tai(jd_tai):
    return jd_tai + TT_MINUS_TAI / 86400.0


def _tdb_minus_tt_seconds(tt_seconds):
    """NAIF's formula (naif0012.tls): K sin(E), E = M + EB sin M, M = M0 + M1 t, t seconds of TT past J2000."""
    m = TDB_M0 + TDB_M1 * tt_seconds
    return TDB_K * math.sin(m + TDB_EB * math.sin(m))


def tdb_minus_tt(jd_tt):
    """TDB - TT in seconds at a TT Julian day."""
    return _tdb_minus_tt_seconds((jd_tt - J2000_JD) * 86400.0)


def tdb_from_tt(jd_tt):
    return jd_tt + tdb_minus_tt(jd_tt) / 86400.0


def ephemeris_time(jd_tdb):
    """Seconds of TDB past J2000 (the SPK time argument)."""
    return (jd_tdb - J2000_JD) * 86400.0


def _utc_seconds(year, month, day, hour, minute, second):
    """Seconds past 2000-01-01T12:00:00 UTC without leap seconds, exact to the float."""
    try:
        days = (datetime.date(year, month, day) - datetime.date(2000, 1, 1)).days
    except ValueError as exc:
        raise FrameError("not a calendar date") from exc
    return days * 86400.0 + hour * 3600.0 + minute * 60.0 + second - 43200.0


def et_from_utc(text):
    """Ephemeris time (TDB seconds past J2000) of a UTC epoch string."""
    parts = parse_utc(text)
    leap = leap_seconds(julian_day(*parts))
    tt = _utc_seconds(*parts) + leap + TT_MINUS_TAI
    return tt + _tdb_minus_tt_seconds(tt)


FRAMES = ("icrf", "eclipticJ2000", "bodyFixed")
TIME_SCALES = ("utc", "tt", "tdb")


def space(epoch, time_scale="utc", rate=1.0, origin=0, frame="icrf", frame_body=None):
    """The `space` element: the frame clock's epoch (UTC text, or a Julian day in TT or TDB), its rate in
    seconds of ephemeris time per second of scene time, the origin body and the frame."""
    if time_scale not in TIME_SCALES:
        raise FrameError("timeScale is one of utc, tt, tdb")
    if time_scale == "utc":
        et0 = et_from_utc(epoch)
    else:
        try:
            jd = float(epoch)
        except (TypeError, ValueError) as exc:
            raise FrameError("a TT or TDB epoch is a Julian day") from exc
        tt = (jd - J2000_JD) * 86400.0
        et0 = tt + _tdb_minus_tt_seconds(tt) if time_scale == "tt" else tt
    if not (rate >= 0.0) or not math.isfinite(rate):
        raise FrameError("rate is a finite non-negative number")
    if frame not in FRAMES:
        raise FrameError("frame is one of icrf, eclipticJ2000, bodyFixed")
    if frame == "bodyFixed" and frame_body not in ROTATION:
        raise FrameError("bodyFixed needs a frameBody with rotation elements")
    if not isinstance(origin, int):
        raise FrameError("origin is a NAIF body id")
    return {"et0": et0, "rate": float(rate), "origin": origin, "frame": frame, "frame_body": frame_body}


def frame_time(sp, frame, fps):
    """Ephemeris time of a frame: epoch + frame / fps * rate."""
    if not isinstance(frame, int) or frame < 0:
        raise FrameError("the frame is a non-negative integer")
    if not (fps > 0.0):
        raise FrameError("fps is positive")
    return sp["et0"] + frame / fps * sp["rate"]


# ------------------------------------------------------------------------------------ rules 2 and 3: SPK files

_RECORD = 1024
_FTPSTR = b"FTPSTR:\r:\n:\r\n:\r\x00:\x81:\x10\xce:ENDFTP"


def _order(fmt):
    if fmt == "LTL-IEEE":
        return "<"
    if fmt == "BIG-IEEE":
        return ">"
    raise FrameError("the DAF byte order is LTL-IEEE or BIG-IEEE, not %r" % (fmt,))


def _parse_daf(data):
    if len(data) < 2 * _RECORD:
        raise FrameError("the file is shorter than a DAF file record and a summary record")
    ident = data[:8].decode("latin1")
    if ident != "DAF/SPK ":
        raise FrameError("not an SPK file: %r" % (ident,))
    fmt = data[88:96].decode("latin1")
    bo = _order(fmt)
    nd, ni = struct.unpack(bo + "ii", data[8:16])
    if (nd, ni) != (2, 6):
        raise FrameError("an SPK summary has 2 doubles and 6 integers, not %d and %d" % (nd, ni))
    fward, bward, free = struct.unpack(bo + "iii", data[76:88])
    ifname = data[16:76].decode("latin1").strip()
    segments = []
    offsets = []
    centers = {}
    rec = fward
    visited = 0
    while rec > 0:
        visited += 1
        if visited > MAX_SEGMENTS:
            raise FrameError("the summary records loop")
        base = (rec - 1) * _RECORD
        if base + 2 * _RECORD > len(data):
            raise FrameError("summary record %d is beyond the file" % rec)
        nxt, prv, nsum = struct.unpack(bo + "ddd", data[base:base + 24])
        nsum = int(nsum)
        if not (0 <= nsum <= 25):
            raise FrameError("a summary record holds 0 to 25 summaries")
        for i in range(nsum):
            off = base + 24 + i * 40
            start, end = struct.unpack(bo + "dd", data[off:off + 16])
            target, center, frame, kind, begin, finish = struct.unpack(bo + "6i", data[off + 16:off + 40])
            if kind != 2:
                raise FrameError("segment type %d is not the Chebyshev position type 2" % kind)
            if frame != 1:
                raise FrameError("segment frame %d is not J2000/ICRF (1)" % frame)
            if begin < 1 or finish * 8 > len(data) or finish - begin < 3:
                raise FrameError("a segment's addresses are outside the file")
            if len(segments) >= MAX_SEGMENTS:
                raise FrameError("more than %d segments" % MAX_SEGMENTS)
            name = data[base + _RECORD + i * 40:base + _RECORD + (i + 1) * 40].decode("latin1").strip()
            segments.append({"start": start, "end": end, "target": target, "center": center, "frame": frame,
                             "type": kind, "begin": begin, "finish": finish, "name": name})
            offsets.append(off)
            if centers.setdefault(target, center) != center:
                raise FrameError("body %d has segments about two centres" % target)
        rec = int(nxt)
    if not segments:
        raise FrameError("the SPK file has no segments")
    return {"id": ident.strip(), "nd": nd, "ni": ni, "format": fmt, "order": bo, "ifname": ifname, "fward": fward,
            "bward": bward, "free": free, "segments": segments, "summary_offsets": offsets, "centers": centers,
            "data": data, "digest": hashlib.sha256(data).hexdigest()}


def read_daf(path):
    """Parse an SPK file's file record and segment summaries."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        raise FrameError("cannot read %s" % path) from exc
    return _parse_daf(data)


def open_ephemeris(path, digest):
    """Read an SPK file and check its sha256 digest (`sha256:` prefix optional; None skips the check)."""
    spk = read_daf(path)
    if digest is not None:
        want = digest[7:] if digest.startswith("sha256:") else digest
        if not re.fullmatch(r"[0-9a-f]{64}", want):
            raise FrameError("the digest is 64 hex digits of sha256")
        if want != spk["digest"]:
            raise FrameError("ephemeris digest mismatch: document %s, file %s" % (want, spk["digest"]))
    return spk


def _doubles(spk, address, n):
    off = (address - 1) * 8
    if off < 0 or off + n * 8 > len(spk["data"]):
        raise FrameError("address %d is outside the file" % address)
    return struct.unpack(spk["order"] + "%dd" % n, spk["data"][off:off + n * 8])


def _trailer(spk, seg):
    if "trailer" not in seg:
        init, intlen, rsize, n = _doubles(spk, seg["finish"] - 3, 4)
        if not (intlen > 0.0 and rsize >= 5 and n >= 1 and (int(rsize) - 2) % 3 == 0):
            raise FrameError("segment trailer is not a type 2 trailer")
        seg["trailer"] = (init, intlen, int(rsize), int(n))
    return seg["trailer"]


def chebyshev(coeffs, t):
    """Sum c_k T_k(t) by Clenshaw's recurrence for t in [-1, 1]."""
    if not (-1.0 - 1e-12 <= t <= 1.0 + 1e-12):
        raise FrameError("the Chebyshev argument is in [-1, 1]")
    b1 = b2 = 0.0
    for c in reversed(coeffs[1:]):
        b1, b2 = 2.0 * t * b1 - b2 + c, b1
    return t * b1 - b2 + coeffs[0]


def chebyshev_derivative(coeffs, t):
    """d/dt of the Chebyshev sum, by the recurrence T'_{k+1} = 2 T_k + 2 t T'_k - T'_{k-1}."""
    if not (-1.0 - 1e-12 <= t <= 1.0 + 1e-12):
        raise FrameError("the Chebyshev argument is in [-1, 1]")
    t0, t1 = 1.0, t
    d0, d1 = 0.0, 1.0
    out = coeffs[1] * d1 if len(coeffs) > 1 else 0.0
    for c in coeffs[2:]:
        t2 = 2.0 * t * t1 - t0
        d2 = 2.0 * t1 + 2.0 * t * d1 - d0
        out += c * d2
        t0, t1, d0, d1 = t1, t2, d1, d2
    return out


def _segment_state(spk, target, et):
    """Position (km) and velocity (km/s) of a body about its own centre from its segment covering et."""
    found = [s for s in spk["segments"] if s["target"] == target and s["start"] <= et <= s["end"]]
    if not found:
        if target not in spk["centers"]:
            raise FrameError("body %d is not in the ephemeris" % target)
        raise FrameError("body %d has no segment at ephemeris time %r" % (target, et))
    seg = found[0]
    init, intlen, rsize, n = _trailer(spk, seg)
    i = int(math.floor((et - init) / intlen))
    i = max(0, min(n - 1, i))
    rec = _doubles(spk, seg["begin"] + i * rsize, rsize)
    mid, radius = rec[0], rec[1]
    if radius <= 0.0 or not (mid - radius - 1e-6 <= et <= mid + radius + 1e-6):
        raise FrameError("record %d of body %d does not cover ephemeris time %r" % (i, target, et))
    nc = (rsize - 2) // 3
    t = max(-1.0, min(1.0, (et - mid) / radius))
    pos = []
    vel = []
    for k in range(3):
        c = rec[2 + k * nc:2 + (k + 1) * nc]
        pos.append(chebyshev(c, t))
        vel.append(chebyshev_derivative(c, t) / radius)
    return tuple(pos), tuple(vel)


def _chain_state(spk, body, et):
    """State of a body relative to the solar system barycentre through the chain of centres."""
    pos = [0.0, 0.0, 0.0]
    vel = [0.0, 0.0, 0.0]
    hops = 0
    while body != 0:
        if body not in spk["centers"]:
            raise FrameError("body %d is not in the ephemeris" % body)
        p, v = _segment_state(spk, body, et)
        pos = [a + b for a, b in zip(pos, p)]
        vel = [a + b for a, b in zip(vel, v)]
        body = spk["centers"][body]
        hops += 1
        if hops > 16:
            raise FrameError("the chain of centres does not reach the barycentre")
    return tuple(pos), tuple(vel)


def state(spk, target, center, et):
    """Position (km) and velocity (km/s) of target relative to center at ephemeris time et, ICRF axes."""
    if target == center:
        if target != 0 and target not in spk["centers"]:
            raise FrameError("body %d is not in the ephemeris" % target)
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    pt, vt = _chain_state(spk, target, et)
    pc, vc = _chain_state(spk, center, et)
    return tuple(a - b for a, b in zip(pt, pc)), tuple(a - b for a, b in zip(vt, vc))


def position(spk, target, center, et):
    return state(spk, target, center, et)[0]


def velocity(spk, target, center, et):
    return state(spk, target, center, et)[1]


def apparent_position(spk, target, observer, et):
    """The target's position when the light now arriving left it: bounded light-time iteration."""
    obs = position(spk, observer, 0, et)
    lt = 0.0
    p = None
    for _ in range(MAX_LIGHT_TIME_ITERATIONS):
        tgt = position(spk, target, 0, et - lt)
        p = tuple(a - b for a, b in zip(tgt, obs))
        lt = math.sqrt(sum(x * x for x in p)) / C_KM_S
    return p, lt


def write_excerpt(src, dst, windows, bodies, fmt="LTL-IEEE"):
    """Write a new SPK holding, for each body and each (et0, et1) window, the records of the source's segment
    that cover the window. Summaries are packed 25 to a record, as the DAF format states."""
    bo = _order(fmt)
    if not bodies:
        raise FrameError("the excerpt needs at least one body")
    for et0, et1 in windows:
        if not (et0 < et1):
            raise FrameError("an excerpt window is (start, end) with start before end")
    if len(windows) * len(bodies) > MAX_SEGMENTS:
        raise FrameError("more than %d excerpt segments" % MAX_SEGMENTS)
    source = read_daf(src)
    new = []
    for body in bodies:
        if body not in source["centers"]:
            raise FrameError("body %d is not in %s" % (body, src))
        for et0, et1 in windows:
            segs = [s for s in source["segments"] if s["target"] == body and s["start"] <= et0 and et1 <= s["end"]]
            if not segs:
                raise FrameError("body %d has no segment covering the window" % body)
            seg = segs[0]
            init, intlen, rsize, n = _trailer(source, seg)
            i0 = max(0, min(n - 1, int(math.floor((et0 - init) / intlen))))
            i1 = max(0, min(n - 1, int(math.floor((et1 - init) / intlen))))
            records = _doubles(source, seg["begin"] + i0 * rsize, (i1 - i0 + 1) * rsize)
            new.append({"target": body, "center": seg["center"], "name": seg["name"], "init": init + i0 * intlen,
                        "intlen": intlen, "rsize": rsize, "n": i1 - i0 + 1, "records": records})
    per = 25
    nrec = (len(new) + per - 1) // per
    data_rec = 2 + 2 * nrec
    address = (data_rec - 1) * 128 + 1
    body_bytes = bytearray()
    for s in new:
        s["begin"] = address
        values = list(s["records"]) + [s["init"], s["intlen"], float(s["rsize"]), float(s["n"])]
        body_bytes += struct.pack(bo + "%dd" % len(values), *values)
        address += len(values)
        s["finish"] = address - 1
    free = address
    out = bytearray()
    head = bytearray(_RECORD)
    head[0:8] = b"DAF/SPK "
    head[8:16] = struct.pack(bo + "ii", 2, 6)
    ifname = (b"sr-core excerpt of " + os.path.basename(src).encode("latin1"))[:60].ljust(60, b" ")
    head[16:76] = ifname
    head[76:88] = struct.pack(bo + "iii", 2, 2 * nrec, free)
    head[88:96] = fmt.encode("latin1")
    head[699:699 + len(_FTPSTR)] = _FTPSTR
    out += head
    for r in range(nrec):
        chunk = new[r * per:(r + 1) * per]
        srec = bytearray(_RECORD)
        nxt = 2 + 2 * (r + 1) if r + 1 < nrec else 0
        prv = 2 + 2 * (r - 1) if r > 0 else 0
        srec[0:24] = struct.pack(bo + "ddd", float(nxt), float(prv), float(len(chunk)))
        nrec_bytes = bytearray(b" " * _RECORD)
        for i, s in enumerate(chunk):
            off = 24 + i * 40
            start = s["init"]
            end = s["init"] + s["n"] * s["intlen"]
            srec[off:off + 40] = struct.pack(bo + "dd6i", start, end, s["target"], s["center"], 1, 2, s["begin"],
                                             s["finish"])
            nrec_bytes[i * 40:(i + 1) * 40] = s["name"].encode("latin1")[:40].ljust(40, b" ")
        out += srec + nrec_bytes
    out += body_bytes
    pad = (-len(out)) % _RECORD
    out += bytes(pad)
    with open(dst, "wb") as f:
        f.write(bytes(out))
    return len(new)


_EXCERPT = {}


def excerpt():
    """The kit's fixture, opened once and checked against its digest."""
    if "spk" not in _EXCERPT:
        _EXCERPT["spk"] = open_ephemeris(EXCERPT_PATH, EXCERPT_DIGEST)
    return _EXCERPT["spk"]


def _horizons():
    with open(HORIZONS_PATH, encoding="utf-8") as f:
        return json.load(f)["bodies"]


def horizons_worst():
    """The largest distance (km) between the excerpt's positions and the Horizons vectors."""
    spk = excerpt()
    worst = 0.0
    for body, rows in _horizons().items():
        target = 4 if body == "499" else int(body)
        for r in rows:
            p = position(spk, target, 0, (r["jd"] - J2000_JD) * 86400.0)
            worst = max(worst, math.dist(p, (r["x"], r["y"], r["z"])))
    return worst


def horizons_test():
    w = horizons_worst()
    return (w < 1.0, w < 0.01)


# ------------------------------------------------------------------------------------ rule 4: approximate elements
# Standish and Williams (JPL, ssd.jpl.nasa.gov/planets/approx_pos.html): a (au), e, I, L, long. peri., long. node
# (degrees) and their rates per Julian century, mean ecliptic and equinox of J2000.

ELEMENTS_1800_2050 = {
    "Mercury": (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593,
                0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081),
    "Venus": (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255,
              0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418),
    "EM Bary": (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0,
                0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0),
    "Mars": (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891,
             0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343),
    "Jupiter": (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909,
                -0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106),
    "Saturn": (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448,
               -0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794),
    "Uranus": (19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503,
               -0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589),
    "Neptune": (30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574,
                0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664),
}
ELEMENTS_3000BC_3000AD = {
    "Mercury": (0.38709843, 0.20563661, 7.00559432, 252.25166724, 77.45771895, 48.33961819,
                0.00000000, 0.00002123, -0.00590158, 149472.67486623, 0.15940013, -0.12214182),
    "Venus": (0.72332102, 0.00676399, 3.39777545, 181.97970850, 131.76755713, 76.67261496,
              -0.00000026, -0.00005107, 0.00043494, 58517.81560260, 0.05679648, -0.27274174),
    "EM Bary": (1.00000018, 0.01673163, -0.00054346, 100.46691572, 102.93005885, -5.11260389,
                -0.00000003, -0.00003661, -0.01337178, 35999.37306329, 0.31795260, -0.24123856),
    "Mars": (1.52371243, 0.09336511, 1.85181869, -4.56813164, -23.91744784, 49.71320984,
             0.00000097, 0.00009149, -0.00724757, 19140.29934243, 0.45223625, -0.26852431),
    "Jupiter": (5.20248019, 0.04853590, 1.29861416, 34.33479152, 14.27495244, 100.29282654,
                -0.00002864, 0.00018026, -0.00322699, 3034.90371757, 0.18199196, 0.13024619),
    "Saturn": (9.54149883, 0.05550825, 2.49424102, 50.07571329, 92.86136063, 113.63998702,
               -0.00003065, -0.00032044, 0.00451969, 1222.11494724, 0.54179478, -0.25015002),
    "Uranus": (19.18797948, 0.04685740, 0.77298127, 314.20276625, 172.43404441, 73.96250215,
               -0.00020455, -0.00001550, -0.00180155, 428.49512595, 0.09266985, 0.05739699),
    "Neptune": (30.06952752, 0.00895439, 1.77005520, 304.22289287, 46.68158724, 131.78635853,
                0.00006447, 0.00000818, 0.00022400, 218.46515314, 0.01009938, -0.00606302),
}
# Table 2b: b, c, s, f for the mean anomaly of the outer planets over 3000 BC to 3000 AD.
OUTER_CORRECTIONS = {
    "Jupiter": (-0.00012452, 0.06064060, -0.35635438, 38.35125000),
    "Saturn": (0.00025899, -0.13434469, 0.87320147, 38.35125000),
    "Uranus": (0.00058331, -0.97731848, 0.17689245, 7.67025000),
    "Neptune": (-0.00041348, 0.68346318, -0.10162547, 7.67025000),
}
BODY_NAMES = {1: "Mercury", 2: "Venus", 3: "EM Bary", 4: "Mars", 5: "Jupiter", 6: "Saturn", 7: "Uranus", 8: "Neptune"}
ELEMENT_TABLES = {"1800-2050": (ELEMENTS_1800_2050, 1800, 2050, False),
                  "3000BC-3000AD": (ELEMENTS_3000BC_3000AD, -3000, 3000, True)}


def solve_kepler(mean_anomaly, e):
    """E - e* sin E = M in degrees, Newton's iterations from E0 = M + e* sin M, bounded."""
    if not (0.0 <= e < 1.0):
        raise FrameError("the eccentricity is in [0, 1)")
    m = (mean_anomaly + 180.0) % 360.0 - 180.0
    e_star = math.degrees(e)
    big_e = m + e_star * math.sin(math.radians(m))
    for _ in range(MAX_KEPLER_ITERATIONS):
        dm = m - (big_e - e_star * math.sin(math.radians(big_e)))
        de = dm / (1.0 - e * math.cos(math.radians(big_e)))
        big_e += de
        if abs(de) < 1e-11:
            return big_e
    raise FrameError("Kepler's equation did not converge")


def approximate_position(body, et, table="1800-2050"):
    """Heliocentric ICRF position (km) of a planet or the Earth-Moon barycentre from the Keplerian elements."""
    if table not in ELEMENT_TABLES:
        raise FrameError("the element table is 1800-2050 or 3000BC-3000AD")
    if body not in BODY_NAMES:
        raise FrameError("the approximate elements cover bodies 1 to 8, not %r" % (body,))
    elements, y0, y1, outer = ELEMENT_TABLES[table]
    year = calendar(J2000_JD + et / 86400.0)[0]
    if not (y0 <= year <= y1):
        raise FrameError("the table %s does not cover the year %d" % (table, year))
    name = BODY_NAMES[body]
    row = elements[name]
    t = et / (86400.0 * 36525.0)
    a, e, inc, big_l, peri, node = (row[i] + row[i + 6] * t for i in range(6))
    omega = peri - node
    m = big_l - peri
    if outer and name in OUTER_CORRECTIONS:
        b, c, s, f = OUTER_CORRECTIONS[name]
        m += b * t * t + c * math.cos(math.radians(f * t)) + s * math.sin(math.radians(f * t))
    big_e = math.radians(solve_kepler(m, e))
    xp = a * (math.cos(big_e) - e)
    yp = a * math.sqrt(1.0 - e * e) * math.sin(big_e)
    cw, sw = math.cos(math.radians(omega)), math.sin(math.radians(omega))
    co, so = math.cos(math.radians(node)), math.sin(math.radians(node))
    ci, si = math.cos(math.radians(inc)), math.sin(math.radians(inc))
    x = (cw * co - sw * so * ci) * xp + (-sw * co - cw * so * ci) * yp
    y = (cw * so + sw * co * ci) * xp + (-sw * so + cw * co * ci) * yp
    z = (sw * si) * xp + (cw * si) * yp
    ce, se = math.cos(math.radians(OBLIQUITY_J2000)), math.sin(math.radians(OBLIQUITY_J2000))
    return (x * AU_KM, (ce * y - se * z) * AU_KM, (se * y + ce * z) * AU_KM)


def _angle_between(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))))


def elements_error_arcsec(body, et, table="1800-2050"):
    """Angle (arcseconds) between the approximate heliocentric direction and the excerpt's."""
    return 3600.0 * _angle_between(approximate_position(body, et, table), position(excerpt(), body, 10, et))


def elements_test():
    return (elements_error_arcsec(3, 0.0) < 60.0, elements_error_arcsec(5, 0.0, "3000BC-3000AD") < 1800.0)


# ------------------------------------------------------------------------------------ rule 5: frames
# IAU 2009 rotation elements as NAIF's pck00010.tpc states them: (ra0, ra1), (dec0, dec1), (w0, w1, w2) in
# degrees with T Julian centuries and d days of TDB past J2000; the Moon's nutation-precession series
# (BODY3_NUT_PREC_ANGLES, BODY301_NUT_PREC_*) is included, the small series of Mercury and Jupiter are not.

ROTATION = {
    10: ((286.13, 0.0), (63.87, 0.0), (84.176, 14.18440, 0.0)),
    199: ((281.0097, -0.0328), (61.4143, -0.0049), (329.5469, 6.1385025, 0.0)),
    299: ((272.76, 0.0), (67.16, 0.0), (160.20, -1.4813688, 0.0)),
    399: ((0.0, -0.641), (90.0, -0.557), (190.147, 360.9856235, 0.0)),
    499: ((317.68143, -0.1061), (52.88650, -0.0609), (176.630, 350.89198226, 0.0)),
    599: ((268.056595, -0.006499), (64.495303, 0.002413), (284.95, 870.5360000, 0.0)),
    699: ((40.589, -0.036), (83.537, -0.004), (38.90, 810.7939024, 0.0)),
    799: ((257.311, 0.0), (-15.175, 0.0), (203.81, -501.1600928, 0.0)),
    899: ((299.36, 0.0), (43.46, 0.0), (253.18, 536.3128492, 0.0)),
    301: ((269.9949, 0.0031), (66.5392, 0.0130), (38.3213, 13.17635815, -1.4e-12)),
}
MOON_ANGLES = ((125.045, -1935.5364525), (250.089, -3871.072905), (260.008, 475263.3328725), (176.625, 487269.629985),
               (357.529, 35999.0509575), (311.589, 964468.49931), (134.963, 477198.869325), (276.617, 12006.300765),
               (34.226, 63863.5132425), (15.134, -5806.6093575), (119.743, 131.84064), (239.961, 6003.1503825),
               (25.053, 473327.79642))
MOON_RA = (-3.8787, -0.1204, 0.0700, -0.0172, 0.0, 0.0072, 0.0, 0.0, 0.0, -0.0052, 0.0, 0.0, 0.0043)
MOON_DEC = (1.5419, 0.0239, -0.0278, 0.0068, 0.0, -0.0029, 0.0009, 0.0, 0.0, 0.0008, 0.0, 0.0, -0.0009)
MOON_PM = (3.5610, 0.1208, -0.0642, 0.0158, 0.0252, -0.0066, -0.0047, -0.0046, 0.0028, 0.0052, 0.0040, 0.0019, -0.0044)


def rotation_elements(body, et):
    """(right ascension, declination, prime meridian angle W) in degrees at ephemeris time et."""
    if body not in ROTATION:
        raise FrameError("no rotation elements for body %r" % (body,))
    (ra0, ra1), (dec0, dec1), (w0, w1, w2) = ROTATION[body]
    d = et / 86400.0
    t = d / 36525.0
    ra, dec, w = ra0 + ra1 * t, dec0 + dec1 * t, w0 + w1 * d + w2 * d * d
    if body == 301:
        for (a0, a1), cr, cd, cw in zip(MOON_ANGLES, MOON_RA, MOON_DEC, MOON_PM):
            ang = math.radians(a0 + a1 * t)
            ra += cr * math.sin(ang)
            dec += cd * math.cos(ang)
            w += cw * math.sin(ang)
    return ra, dec, w


def prime_meridian(body, et):
    return rotation_elements(body, et)[2]


def pole_icrf(body, et):
    ra, dec, _ = rotation_elements(body, et)
    r, d = math.radians(ra), math.radians(dec)
    return (math.cos(d) * math.cos(r), math.cos(d) * math.sin(r), math.sin(d))


def _rz(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))


def _rx(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c))


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


def apply(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def determinant(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def body_fixed_from_icrf(body, et):
    """The matrix taking ICRF components to the body-fixed frame: Rz(W) Rx(90 - dec) Rz(90 + ra)."""
    ra, dec, w = rotation_elements(body, et)
    return matmul(_rz(w), matmul(_rx(90.0 - dec), _rz(90.0 + ra)))


def ecliptic_from_icrf():
    """ICRF to the ecliptic and equinox of J2000: a rotation about x by the obliquity."""
    return _rx(OBLIQUITY_J2000)


_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# ICRF (x, y, z) to scene axes: scene x = x, scene y = -z (up is -y), scene z = y.
SCENE_FROM_ICRF_AXES = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))


def frame_matrix(sp, et):
    if sp["frame"] == "icrf":
        return _IDENTITY
    if sp["frame"] == "eclipticJ2000":
        return ecliptic_from_icrf()
    return body_fixed_from_icrf(sp["frame_body"], et)


def scene_from_icrf(sp, p_km, origin_km, pixels_per_meter, et=0.0):
    """A position in km (ICRF axes) about the origin's position into scene pixels through the space's frame
    and `physics/@pixelsPerMeter` (SREP 14 rule 4)."""
    if not (pixels_per_meter > 0.0) or not math.isfinite(pixels_per_meter):
        raise FrameError("pixelsPerMeter is positive")
    rel = tuple(a - b for a, b in zip(p_km, origin_km))
    q = apply(frame_matrix(sp, et), rel)
    scale = 1000.0 * pixels_per_meter
    return (q[0] * scale, -q[2] * scale, q[1] * scale)


def place_body(spk, sp, body, frame, fps, pixels_per_meter):
    """Rule 6: a body's position and body-fixed orientation in the space at a frame."""
    et = frame_time(sp, frame, fps)
    p = position(spk, body, sp["origin"], et)
    pos = scene_from_icrf(sp, p, (0.0, 0.0, 0.0), pixels_per_meter, et)
    if body in ROTATION:
        axes = matmul(frame_matrix(sp, et), transpose(body_fixed_from_icrf(body, et)))
    else:
        axes = frame_matrix(sp, et)
    orientation = matmul(SCENE_FROM_ICRF_AXES, matmul(axes, transpose(SCENE_FROM_ICRF_AXES)))
    return {"et": et, "position": pos, "orientation": orientation}


def seek_test():
    sp = space(epoch="2025-10-28T00:00:00Z", rate=3600.0, origin=0, frame="eclipticJ2000")
    first = place_body(excerpt(), sp, 4, 40, 24.0, 1e-9)
    place_body(excerpt(), sp, 4, 1000, 24.0, 1e-9)
    again = place_body(excerpt(), sp, 4, 40, 24.0, 1e-9)
    return (first == again, first["et"] == sp["et0"] + 40.0 / 24.0 * 3600.0)


# ------------------------------------------------------------------------------------ the numeric table


def _sun_longitude_earth_fixed():
    sp = space(epoch="2451545.0", time_scale="tdb", origin=399, frame="bodyFixed", frame_body=399)
    x, y, z = place_body(excerpt(), sp, 10, 0, 24.0, 1e-6)["position"]
    return math.degrees(math.atan2(z, x))


def _earth_meridian_vs_gast():
    """IAU prime-meridian right ascension minus the SPA's apparent sidereal time for the SPA example."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("physical_sky_reference",
                                                  os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                               "physical_sky_reference.py"))
    sky = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sky)
    jd_ut = sky.julian_day(2003, 10, 17, 12, 30, 30.0, -7.0)
    t = sky.time_scales(jd_ut, 67.0)
    dpsi, deps = sky.nutation(t["jce"])
    gast = sky.sidereal_time(jd_ut, t["jc"], dpsi, sky.true_obliquity(t["jme"], deps))
    ra, dec, w = rotation_elements(399, (t["jde"] - J2000_JD) * 86400.0)
    return (ra + 90.0 + w - gast + 180.0) % 360.0 - 180.0


TABLE = (
    ("J2000", "julian_day(2000, 1, 1, 12, 0, 0.0)", "2451545.0"),
    ("calendar", "calendar(2451545.0)", "(2000, 1, 1, 12, 0, 0.0)"),
    ("1972", "julian_day(1972, 1, 1)", "2441317.5"),
    ("parse utc", "parse_utc('2003-10-17T12:30:30-07:00')", "(2003, 10, 17, 19, 30, 30.0)"),
    ("leap seconds 1972", "leap_seconds(julian_day(1972, 1, 1))", "10"),
    ("leap seconds 2017", "leap_seconds(julian_day(2017, 1, 1))", "37"),
    ("leap table", "len(LEAP_SECONDS)", "28"),
    ("tt minus tai", "TT_MINUS_TAI", "32.184"),
    ("tdb minus tt at J2000", "round(tdb_minus_tt(2451545.0), 9)", "0.0"),
    ("tdb minus tt bound", "max(abs(tdb_minus_tt(2451545.0 + d)) for d in range(0, 366, 5)) < 0.0017", "True"),
    ("et of 2000-01-01T11:58:55.816Z", "round(et_from_utc('2000-01-01T11:58:55.816Z') - tdb_minus_tt(2451545.0), 6)", "0.0"),
    ("frame clock", "frame_time(space(epoch='2026-10-24T00:00:00Z', rate=60.0), 24, 24.0) - frame_time(space(epoch='2026-10-24T00:00:00Z', rate=60.0), 0, 24.0)", "60.0"),
    ("frozen clock", "frame_time(space(epoch='2451545.0', time_scale='tdb', rate=0.0), 500, 24.0)", "0.0"),
    ("excerpt digest", "excerpt()['digest'] == EXCERPT_DIGEST", "True"),
    ("excerpt format", "(excerpt()['id'], excerpt()['format'], excerpt()['nd'], excerpt()['ni'])", "('DAF/SPK', 'LTL-IEEE', 2, 6)"),
    ("excerpt segments", "len(excerpt()['segments'])", "0"),
    ("excerpt bodies", "sorted({s['target'] for s in excerpt()['segments']})", "[]"),
    ("chebyshev", "round(chebyshev((1.0, -0.5, 0.25), 0.5), 12)", "0.0"),
    ("chebyshev derivative", "round(chebyshev_derivative((1.0, -0.5, 0.25), 0.5), 12)", "0.0"),
    ("earth at J2000", "tuple(round(x, 3) for x in position(excerpt(), 399, 0, 0.0))", "(0.0, 0.0, 0.0)"),
    ("moon distance at J2000", "round(math.dist(position(excerpt(), 301, 399, 0.0), (0.0, 0.0, 0.0)), 3)", "0.0"),
    ("earth speed at J2000", "round(math.dist(velocity(excerpt(), 399, 0, 0.0), (0.0, 0.0, 0.0)), 6)", "0.0"),
    ("horizons worst km", "round(horizons_worst(), 6)", "0.0"),
    ("horizons test", "horizons_test()", "(True, True)"),
    ("light time to the sun", "round(apparent_position(excerpt(), 10, 399, 0.0)[1], 3)", "0.0"),
    ("kepler", "round(solve_kepler(45.0, 0.2), 9)", "0.0"),
    ("em bary error arcsec", "round(elements_error_arcsec(3, 0.0), 3)", "0.0"),
    ("mars error arcsec 2025", "round(elements_error_arcsec(4, (2460977.5 - 2451545.0) * 86400.0), 3)", "0.0"),
    ("jupiter error arcsec table 2", "round(elements_error_arcsec(5, 0.0, '3000BC-3000AD'), 3)", "0.0"),
    ("elements test", "elements_test()", "(True, True)"),
    ("earth elements at J2000", "tuple(round(x, 6) for x in rotation_elements(399, 0.0))", "(0.0, 90.0, 190.147)"),
    ("earth rotation determinant", "round(determinant(body_fixed_from_icrf(399, 12345.0)), 12)", "1.0"),
    ("moon pole at J2000", "tuple(round(x, 6) for x in pole_icrf(301, 0.0))", "(0.0, 0.0, 0.0)"),
    ("sidereal day", "round(360.0 / ROTATION[399][2][1] * 86400.0, 4)", "0.0"),
    ("meridian minus gast", "round(_earth_meridian_vs_gast(), 4)", "0.0"),
    ("ecliptic pole", "tuple(round(x, 9) for x in apply(ecliptic_from_icrf(), (0.0, 0.0, 1.0)))", "(0.0, 0.0, 0.0)"),
    ("scene mapping", "scene_from_icrf(space(epoch='2451545.0', time_scale='tdb'), (1.0, 2.0, 3.0), (0.0, 0.0, 0.0), 1e-6)", "(0.001, -0.003, 0.002)"),
    ("scene handedness", "round(determinant(SCENE_FROM_ICRF_AXES), 12)", "1.0"),
    ("sun longitude earth-fixed", "round(_sun_longitude_earth_fixed(), 3)", "0.0"),
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
