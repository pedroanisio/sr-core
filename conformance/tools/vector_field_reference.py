"""Reference for the draft SREP "Add vector-field layers to the map" (M4 of SREP 12).

A `uvGrid` asset names GRIB2 or classic NetCDF files holding the two horizontal components of a wind or current
field; the resolve step pairs them by valid time into one flow cache (a classic NetCDF file, 64-bit offset
variant) whose SHA-256 the document pins. A `flow` map child advects particles through the cache after
webgl-wind (ISC, Mapbox and Vladimir Agafonkin; the formulas are re-derived here, no code is copied): fade the
trail, paint the particles, move them by a midpoint step in metres, drop and respawn from the element's random
streams. Frame k is the replay of frames 0 to k, so a seek gives the frame playback gives (the seek check).

The GRIB2 writer and reader cover edition 2 with grid template 3.0 (latitude-longitude), product template 4.0,
data template 5.0 (simple packing) and section 6 bitmaps; the NetCDF writer and reader cover the classic and
64-bit offset formats of the Unidata specification. Prints the draft's numeric table when run as a script.
"""
import datetime
import hashlib
import importlib.util
import math
import os
import re
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_MODULES = {}


def _module(name):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


_rs = _module("random_streams_reference")
_ts = _module("time_series_reference")

R = 6378137.0
TILE = 256
DEG = 180.0 / math.pi

GRIB_UGRD = (0, 2, 2)
GRIB_VGRD = (0, 2, 3)
PARAMETERS = {"UGRD": GRIB_UGRD, "VGRD": GRIB_VGRD}
TIME_UNITS = {0: 60.0, 1: 3600.0, 2: 86400.0, 10: 10800.0, 11: 21600.0, 12: 43200.0, 13: 1.0}

# webgl-wind's default colour ramp (speed fraction -> colour).
DEFAULT_RAMP = ((0.0, "#3288bd"), (0.1, "#66c2a5"), (0.2, "#abdda4"), (0.3, "#e6f598"), (0.4, "#fee08b"),
                (0.5, "#fdae61"), (0.6, "#f46d43"), (1.0, "#d53e4f"))

FLOW_DEFAULTS = {"particles": 65536, "speedup": 6000.0, "fade": 0.996, "dropRate": 0.003, "dropBump": 0.01,
                 "strokeWidth": 1.0, "opacity": 1.0, "seed": 0, "timeOrigin": 0, "time": 0, "colors": DEFAULT_RAMP}
UVGRID_DEFAULTS = {"format": "auto", "u": "UGRD", "v": "VGRD", "surface": "103:10"}
PURPOSES = {"spawnX": 1, "spawnY": 2, "drop": 3}
MAX_PARTICLES = 1_000_000

KNOWN_FLOW = {"kind", "id", "grid", *FLOW_DEFAULTS}
KNOWN_UVGRID = {"kind", "id", "src", "cache", "cacheSha256", "credit", "data", *UVGRID_DEFAULTS}
FORMATS = ("auto", "grib2", "netcdf")
CODE_ORDER = ("VF1", "VF2", "VF3", "VF4", "V17")


class VectorFieldError(ValueError):
    """A file, document or value that the draft rejects."""


digest = _ts.digest
animated_number = _ts.animated


def parse_time(value):
    """A time as seconds: a finite number or an ISO 8601 date-time with seconds and a zone (time-series draft)."""
    try:
        return _ts.parse_time(value)
    except _ts.TimeSeriesError as e:
        raise VectorFieldError(str(e)) from None


def animated(value, t):
    try:
        return _ts.animated(value, t)
    except _ts.TimeSeriesError as e:
        raise VectorFieldError(str(e)) from None


def data_time(origin, time):
    """The data time T: the origin (a time) plus the element's `time` in seconds."""
    return parse_time(origin) + float(time)


def colour(value):
    try:
        return _ts.colour(value)
    except _ts.TimeSeriesError as e:
        raise VectorFieldError(str(e)) from None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------------------- streams


H = _rs.H
U = _rs.U


def element_seed(project, element_id, seed, purpose):
    """E(project, id, seed, purpose): CRC-32 of "project:id:seed:purpose" (random-streams draft)."""
    return _rs.E(project, element_id, seed, purpose)


def stream(e, purpose, step, index):
    """S(e, p, t, i) = U(e, p + t 2^32, i): the draw of purpose p at step t for particle i."""
    return _rs.S(e, purpose, step, index)


# ------------------------------------------------------------------------------------------------------------ GRIB2


_EPOCH = datetime.datetime(1970, 1, 1)


def _u(data, start, n):
    if start + n > len(data):
        raise VectorFieldError(f"truncated: {start + n} octets needed, {len(data)} present")
    return int.from_bytes(data[start:start + n], "big")


def sign_magnitude(data, nbits):
    """An integer in GRIB2 sign-magnitude form: the top bit is the sign, the rest the magnitude."""
    n = nbits // 8
    v = int.from_bytes(bytes(data[:n]), "big")
    sign = 1 << (nbits - 1)
    return -(v & (sign - 1)) if v & sign else v


def to_sign_magnitude(value, nbits):
    sign = 1 << (nbits - 1)
    m = abs(int(value))
    if m >= sign:
        raise VectorFieldError(f"{value} does not fit {nbits} bits in sign-magnitude form")
    return ((sign | m) if value < 0 else m).to_bytes(nbits // 8, "big")


def pack_bits(values, nbits):
    """Values packed most significant bit first into nbits each, zero-padded to whole octets."""
    out = bytearray()
    acc = 0
    n = 0
    for v in values:
        acc = (acc << nbits) | int(v)
        n += nbits
        while n >= 8:
            n -= 8
            out.append((acc >> n) & 0xFF)
        acc &= (1 << n) - 1
    if n:
        out.append((acc << (8 - n)) & 0xFF)
    return bytes(out)


def unpack_bits(data, nbits, count):
    """The first count values of nbits each in data, most significant bit first."""
    if nbits == 0:
        return [0] * count
    total = int.from_bytes(bytes(data), "big")
    width = len(data) * 8
    if count * nbits > width:
        raise VectorFieldError(f"{count} values of {nbits} bits do not fit {len(data)} octets")
    mask = (1 << nbits) - 1
    return [(total >> (width - (i + 1) * nbits)) & mask for i in range(count)]


def simple_values(X, reference, binary_scale, decimal_scale):
    """Regulation 92.9.4: Y = (R + X 2^E) / 10^D."""
    return (float(reference) + np.asarray(X, dtype=float) * 2.0 ** binary_scale) / 10.0 ** decimal_scale


def forecast_seconds(unit, n):
    if unit not in TIME_UNITS:
        raise VectorFieldError(f"unsupported forecast time unit {unit} (code table 4.4)")
    return TIME_UNITS[unit] * float(n)


def parameter(name):
    """A GRIB2 parameter as (discipline, category, number): UGRD, VGRD or "d:c:n"."""
    if not isinstance(name, str) or not name:
        raise VectorFieldError(f"a parameter is UGRD, VGRD or discipline:category:number: {name!r}")
    if name in PARAMETERS:
        return PARAMETERS[name]
    m = re.fullmatch(r"(\d+):(\d+):(\d+)", name.strip())
    if not m:
        raise VectorFieldError(f"a parameter is UGRD, VGRD or discipline:category:number: {name!r}")
    return tuple(int(g) for g in m.groups())


def surface(spec):
    """A GRIB2 first fixed surface as (type, value): "type" or "type:value"."""
    if isinstance(spec, tuple) and len(spec) == 2:
        return (int(spec[0]), float(spec[1]))
    if not isinstance(spec, str):
        raise VectorFieldError(f"a surface is type or type:value: {spec!r}")
    m = re.fullmatch(r"(\d+)(?::([-+]?\d+(?:\.\d+)?))?", spec.strip())
    if not m:
        raise VectorFieldError(f"a surface is type or type:value: {spec!r}")
    return (int(m.group(1)), float(m.group(2)) if m.group(2) else 0.0)


def _micro(v):
    return to_sign_magnitude(int(round(v * 1e6)), 32)


def _scaled(value):
    """A decimal scale factor and scaled integer for a surface value."""
    for s in range(7):
        scaled = value * 10 ** s
        if abs(scaled - round(scaled)) < 1e-9:
            return s, int(round(scaled))
    raise VectorFieldError(f"surface value {value} needs more than six decimals")


def _section(number, body):
    return struct.pack(">IB", 5 + len(body), number) + body


def _time_fields(seconds):
    dt = _EPOCH + datetime.timedelta(seconds=round(seconds))
    return struct.pack(">HBBBBB", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def encode_grib2(values, grid, parameter, surface, reference, forecast, bits=16, decimal_scale=0, scan=0,
                 present=None):
    """One GRIB2 message: values (nj, ni) north to south and west to east on the latitude-longitude grid
    (la1 north-west corner, la2 and lo2 south-east corner, di and dj in degrees); parameter (discipline,
    category, number); surface (type, value); reference a time; forecast in seconds; simple packing with `bits`
    and a decimal scale; `scan` writes the data in that scanning mode; `present` (or NaN) sets the bitmap."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 2:
        raise VectorFieldError("values are a 2-D array (nj, ni)")
    if scan & 0x30:
        raise VectorFieldError(f"scanning mode {scan:#04x} (consecutive j, alternating rows) is not supported")
    nj, ni = values.shape
    mask = np.ones(values.shape, dtype=bool) if present is None else np.asarray(present, dtype=bool)
    mask = mask & np.isfinite(values)
    la1, lo1, la2, lo2 = grid["la1"], grid["lo1"], grid["la2"], grid["lo2"]
    data, flags = values, mask
    if scan & 0x80:                      # -i: points scan from the east
        data, flags = data[:, ::-1], flags[:, ::-1]
        lo1, lo2 = lo2, lo1
    if scan & 0x40:                      # +j: points scan from the south
        data, flags = data[::-1, :], flags[::-1, :]
        la1, la2 = la2, la1
    disc, cat, num = parameter
    stype, svalue = surface
    ref = parse_time(reference)
    if forecast % 3600 == 0:
        unit, n = 1, int(forecast // 3600)
    elif forecast % 60 == 0:
        unit, n = 0, int(forecast // 60)
    else:
        unit, n = 13, int(round(forecast))
    sscale, sval = _scaled(svalue)

    s1 = _section(1, struct.pack(">HHBBB", 7, 0, 2, 1, 1) + _time_fields(ref) + bytes([0, 1]))
    s3 = _section(3, bytes([0]) + struct.pack(">IBBH", ni * nj, 0, 0, 0)
                  + bytes([6, 0]) + b"\x00" * 4 + bytes([0]) + b"\x00" * 4 + bytes([0]) + b"\x00" * 4
                  + struct.pack(">II", ni, nj) + struct.pack(">I", 0) + b"\xff\xff\xff\xff"
                  + _micro(la1) + _micro(lo1) + bytes([0x30]) + _micro(la2) + _micro(lo2)
                  + struct.pack(">II", int(round(grid["di"] * 1e6)), int(round(grid["dj"] * 1e6)))
                  + bytes([scan]))
    s4 = _section(4, struct.pack(">HH", 0, 0) + bytes([cat, num, 2, 0, 0]) + struct.pack(">HB", 0, 0)
                  + bytes([unit]) + struct.pack(">I", n) + bytes([stype]) + to_sign_magnitude(sscale, 8)
                  + to_sign_magnitude(sval, 32) + bytes([255, 255]) + b"\xff\xff\xff\xff")
    flat = data[flags]
    scaled = flat * 10.0 ** decimal_scale
    if flat.size == 0:
        ref_value, E, nbits, X = 0.0, 0, 0, []
    else:
        lo, hi = float(scaled.min()), float(scaled.max())
        ref_value = float(np.float32(lo))
        if hi == lo or bits == 0:
            E, nbits, X = 0, 0, []
        else:
            E = math.ceil(math.log2((hi - lo) / (2 ** bits - 1)))
            X = np.clip(np.round((scaled - ref_value) / 2.0 ** E), 0, 2 ** bits - 1).astype(np.int64)
            nbits = bits
    s5 = _section(5, struct.pack(">IH", int(flat.size), 0) + struct.pack(">f", ref_value)
                  + to_sign_magnitude(E, 16) + to_sign_magnitude(decimal_scale, 16) + bytes([nbits, 0]))
    if flags.all():
        s6 = _section(6, bytes([255]))
    else:
        s6 = _section(6, bytes([0]) + pack_bits(flags.ravel().astype(int), 1))
    s7 = _section(7, pack_bits(X, nbits) if nbits else b"")
    body = s1 + s3 + s4 + s5 + s6 + s7 + b"7777"
    return b"GRIB" + b"\x00\x00" + bytes([disc, 2]) + struct.pack(">Q", 16 + len(body)) + body


def _grid_section(sec):
    if len(sec) < 72:
        raise VectorFieldError("grid definition section too short")
    template = _u(sec, 12, 2)
    if template != 0:
        raise VectorFieldError(f"grid definition template 3.{template} is not supported (only 3.0)")
    scan = sec[71]
    if scan & 0x30:
        raise VectorFieldError(f"scanning mode {scan:#04x} (consecutive j, alternating rows) is not supported")
    return {"points": _u(sec, 6, 4), "ni": _u(sec, 30, 4), "nj": _u(sec, 34, 4),
            "la1": sign_magnitude(sec[46:50], 32) / 1e6, "lo1": sign_magnitude(sec[50:54], 32) / 1e6,
            "la2": sign_magnitude(sec[55:59], 32) / 1e6, "lo2": sign_magnitude(sec[59:63], 32) / 1e6,
            "di": _u(sec, 63, 4) / 1e6, "dj": _u(sec, 67, 4) / 1e6, "scan": scan}


def _product_section(sec):
    if len(sec) < 34:
        raise VectorFieldError("product definition section too short")
    template = _u(sec, 7, 2)
    if template != 0:
        raise VectorFieldError(f"product definition template 4.{template} is not supported (only 4.0)")
    scale = sign_magnitude(sec[23:24], 8)
    value = sign_magnitude(sec[24:28], 32)
    return {"category": sec[9], "number": sec[10], "forecast": forecast_seconds(sec[17], _u(sec, 18, 4)),
            "surface": (sec[22], value / 10.0 ** scale if sec[22] != 255 else 0.0)}


def _representation_section(sec):
    if len(sec) < 21:
        raise VectorFieldError("data representation section too short")
    template = _u(sec, 9, 2)
    if template != 0:
        raise VectorFieldError(f"data representation template 5.{template} is not supported (only 5.0)")
    return {"points": _u(sec, 5, 4), "reference": struct.unpack(">f", sec[11:15])[0],
            "binary_scale": sign_magnitude(sec[15:17], 16), "decimal_scale": sign_magnitude(sec[17:19], 16),
            "bits": sec[19]}


def _message(data, pos):
    if data[pos:pos + 4] != b"GRIB":
        raise VectorFieldError(f"no GRIB indicator at octet {pos}")
    if len(data) < pos + 16:
        raise VectorFieldError("truncated indicator section")
    if data[pos + 7] != 2:
        raise VectorFieldError(f"GRIB edition {data[pos + 7]} is not supported (only 2)")
    length = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
    if length < 20 or pos + length > len(data):
        raise VectorFieldError(f"message of {length} octets at {pos} exceeds the {len(data)} octets present")
    msg = data[pos:pos + length]
    if msg[-4:] != b"7777":
        raise VectorFieldError("message does not end with 7777")
    discipline = msg[6]
    sections = {}
    at = 16
    while at < length - 4:
        if at + 5 > length - 4:
            raise VectorFieldError("truncated section header")
        n = _u(msg, at, 4)
        number = msg[at + 4]
        if n < 5 or at + n > length - 4:
            raise VectorFieldError(f"section {number} of {n} octets overruns the message")
        if number not in (1, 2, 3, 4, 5, 6, 7):
            raise VectorFieldError(f"unknown section number {number}")
        sections[number] = msg[at:at + n]
        at += n
    for required in (1, 3, 4, 5, 6, 7):
        if required not in sections:
            raise VectorFieldError(f"section {required} is missing")
    s1 = sections[1]
    if len(s1) < 21:
        raise VectorFieldError("identification section too short")
    try:
        ref = (datetime.datetime(_u(s1, 12, 2), s1[14], s1[15], s1[16], s1[17], s1[18]) - _EPOCH).total_seconds()
    except ValueError as e:
        raise VectorFieldError(f"reference time is not a calendar date: {e}") from None
    grid = _grid_section(sections[3])
    product = _product_section(sections[4])
    rep = _representation_section(sections[5])
    ni, nj = grid["ni"], grid["nj"]
    if grid.pop("points") != ni * nj:
        raise VectorFieldError("the grid's point count does not equal Ni x Nj")
    s6 = sections[6]
    if s6[5] == 255:
        flags = np.ones(ni * nj, dtype=bool)
    elif s6[5] == 0:
        flags = np.array(unpack_bits(s6[6:], 1, ni * nj), dtype=bool)
    else:
        raise VectorFieldError(f"bitmap indicator {s6[5]} (a predefined bitmap) is not supported")
    count = int(flags.sum())
    if rep["points"] != count:
        raise VectorFieldError(f"{rep['points']} packed values for {count} present points")
    X = unpack_bits(sections[7][5:], rep["bits"], count)
    packed = simple_values(X, rep["reference"], rep["binary_scale"], rep["decimal_scale"])
    full = np.full(ni * nj, np.nan)
    full[flags] = packed
    values = full.reshape(nj, ni)
    scan = grid["scan"]
    if scan & 0x80:
        values = values[:, ::-1]
        grid["lo1"], grid["lo2"] = grid["lo2"], grid["lo1"]
    if scan & 0x40:
        values = values[::-1, :]
        grid["la1"], grid["la2"] = grid["la2"], grid["la1"]
    return {"discipline": discipline, "category": product["category"], "number": product["number"],
            "surface": product["surface"], "reference": ref, "forecast": product["forecast"],
            "grid": grid, "values": values, "bits": rep["bits"]}, pos + length


def grib2_messages(data):
    """Every message of a GRIB2 file, values normalised north to south and west to east, NaN where the bitmap
    marks a point missing; grid la1/lo1 is the north-west corner after normalisation and scan the file's mode."""
    data = bytes(data)
    if not data:
        raise VectorFieldError("empty GRIB2 file")
    out = []
    pos = 0
    while pos < len(data):
        m, pos = _message(data, pos)
        out.append(m)
    return out


# ----------------------------------------------------------------------------------------------------------- NetCDF


NC_TYPES = {"byte": (1, 1, ">i1"), "char": (2, 1, "S1"), "short": (3, 2, ">i2"), "int": (4, 4, ">i4"),
            "float": (5, 4, ">f4"), "double": (6, 8, ">f8")}
NC_NAMES = {code: name for name, (code, _, _) in NC_TYPES.items()}
NC_FILL = {"byte": b"\x81", "char": b"\x00", "short": b"\x80\x01", "int": b"\x80\x00\x00\x01",
           "float": b"\x7c\xf0\x00\x00", "double": b"\x47\x9e\x00\x00\x00\x00\x00\x00"}
NC_DIMENSION, NC_VARIABLE, NC_ATTRIBUTE = 0x0A, 0x0B, 0x0C


def _pad4(n):
    return (4 - n % 4) % 4


def _nc_name(name):
    b = name.encode("utf-8")
    return struct.pack(">I", len(b)) + b + b"\x00" * _pad4(len(b))


def _nc_type_of(value):
    """The NetCDF type and array of a Python or numpy value."""
    if isinstance(value, str):
        return "char", np.frombuffer(value.encode("utf-8"), dtype="S1")
    if isinstance(value, bytes):
        return "char", np.frombuffer(value, dtype="S1")
    arr = np.asarray(value)
    if arr.dtype.kind == "f":
        return ("float" if arr.dtype.itemsize == 4 else "double"), arr
    if arr.dtype.kind in "iu":
        size = arr.dtype.itemsize
        if size == 1:
            return "byte", arr
        if size == 2:
            return "short", arr
        if arr.size and (arr.max() > 2 ** 31 - 1 or arr.min() < -2 ** 31):
            return "double", arr.astype(float)
        return "int", arr
    if arr.dtype.kind == "S":
        return "char", arr
    raise VectorFieldError(f"no NetCDF type for {value!r}")


def _nc_values(typ, arr):
    arr = np.asarray(arr)
    if typ == "char":
        return arr.astype("S1").tobytes()
    return arr.astype(NC_TYPES[typ][2]).tobytes()


def _nc_attributes(attrs, var_type=None):
    out = b""
    for name, value in attrs.items():
        typ, arr = _nc_type_of(value)
        if name == "_FillValue" and var_type and var_type != "char":
            typ = var_type
        raw = _nc_values(typ, arr)
        n = len(raw) // NC_TYPES[typ][1]
        out += _nc_name(name) + struct.pack(">II", NC_TYPES[typ][0], n) + raw + b"\x00" * _pad4(len(raw))
    if not attrs:
        return struct.pack(">II", 0, 0)
    return struct.pack(">II", NC_ATTRIBUTE, len(attrs)) + out


def _layout(dims, variables):
    """Dimension ids, the record dimension, and each variable's dtype, shape, record flag and raw size."""
    names = list(dims)
    record = [n for n in names if dims[n] == 0]
    if len(record) > 1:
        raise VectorFieldError("at most one dimension is the record (unlimited) dimension")
    record = record[0] if record else None
    numrecs = 0
    plan = []
    for var in variables:
        typ = var["type"]
        if typ not in NC_TYPES:
            raise VectorFieldError(f"unknown NetCDF type {typ!r}")
        for d in var.get("dims", []):
            if d not in dims:
                raise VectorFieldError(f"variable {var['name']} uses undefined dimension {d!r}")
        is_record = bool(var.get("dims")) and var["dims"][0] == record
        if typ == "char" and isinstance(var.get("data"), str):
            arr = np.frombuffer(var["data"].encode("utf-8"), dtype="S1")
        else:
            arr = np.asarray(var.get("data", []))
        shape = [dims[d] for d in var.get("dims", [])]
        if is_record:
            n = int(arr.shape[0]) if arr.ndim else 0
            if numrecs and n != numrecs:
                raise VectorFieldError("record variables must hold the same number of records")
            numrecs = n
            shape[0] = n
        if list(arr.shape) != shape:
            if arr.size == int(np.prod(shape)) if shape else arr.size == 1:
                arr = arr.reshape(shape)
            else:
                raise VectorFieldError(f"variable {var['name']} data shape {arr.shape} is not {tuple(shape)}")
        unit = NC_TYPES[typ][1]
        per_record = unit * int(np.prod(shape[1:])) if is_record else unit * int(np.prod(shape))
        plan.append({"var": var, "type": typ, "arr": arr, "is_record": is_record, "raw": per_record,
                     "dimids": [names.index(d) for d in var.get("dims", [])]})
    record_vars = [p for p in plan if p["is_record"]]
    single_small = len(record_vars) == 1 and record_vars[0]["type"] in ("byte", "char", "short")
    for p in plan:
        p["vsize"] = p["raw"] if (p["is_record"] and single_small) else p["raw"] + _pad4(p["raw"])
    return names, record, numrecs, plan


def netcdf_write(dims, variables, attributes, version=2):
    """A classic (version 1, CDF\\x01) or 64-bit offset (version 2, CDF\\x02) NetCDF file. dims maps names to
    sizes (0 = the record dimension); variables are {name, dims, type, data, attributes}; header padding is
    zero bytes and data padding the type's fill value, as the specification lays out."""
    if version not in (1, 2):
        raise VectorFieldError("version is 1 (classic) or 2 (64-bit offset)")
    names, record, numrecs, plan = _layout(dims, variables)
    begin_fmt = ">i" if version == 1 else ">q"

    def header(begins):
        h = b"CDF" + bytes([version]) + struct.pack(">I", numrecs)
        if names:
            h += struct.pack(">II", NC_DIMENSION, len(names))
            for n in names:
                h += _nc_name(n) + struct.pack(">I", dims[n])
        else:
            h += struct.pack(">II", 0, 0)
        h += _nc_attributes(attributes)
        if plan:
            h += struct.pack(">II", NC_VARIABLE, len(plan))
            for p, b in zip(plan, begins):
                var = p["var"]
                h += _nc_name(var["name"]) + struct.pack(">I", len(p["dimids"]))
                h += b"".join(struct.pack(">I", d) for d in p["dimids"])
                h += _nc_attributes(var.get("attributes", {}), p["type"])
                h += struct.pack(">II", NC_TYPES[p["type"]][0], p["vsize"]) + struct.pack(begin_fmt, b)
        else:
            h += struct.pack(">II", 0, 0)
        return h

    size = len(header([0] * len(plan)))
    begins = []
    at = size
    for p in plan:
        if not p["is_record"]:
            begins.append(at)
            at += p["vsize"]
        else:
            begins.append(None)
    base = at
    offset = 0
    for i, p in enumerate(plan):
        if p["is_record"]:
            begins[i] = base + offset
            offset += p["vsize"]
    recsize = offset
    out = bytearray(header(begins))

    def padded(p, raw):
        fill = NC_FILL[p["type"]]
        pad = p["vsize"] - len(raw)
        return raw + (fill * (pad // len(fill) + 1))[:pad]

    for p in plan:
        if not p["is_record"]:
            out += padded(p, _nc_values(p["type"], p["arr"]))
    for r in range(numrecs):
        rec = bytearray()
        for p in plan:
            if p["is_record"]:
                rec += padded(p, _nc_values(p["type"], p["arr"][r]))
        if len(rec) != recsize:
            raise VectorFieldError("record size mismatch")
        out += rec
    return bytes(out)


class _Reader:
    def __init__(self, data):
        self.data = data
        self.at = 0

    def take(self, n):
        if self.at + n > len(self.data):
            raise VectorFieldError(f"truncated NetCDF header at octet {self.at}")
        b = self.data[self.at:self.at + n]
        self.at += n
        return b

    def u32(self):
        return struct.unpack(">I", self.take(4))[0]

    def name(self):
        n = self.u32()
        b = self.take(n)
        self.take(_pad4(n))
        return b.decode("utf-8")

    def attributes(self):
        tag, n = self.u32(), self.u32()
        if tag == 0 and n == 0:
            return {}
        if tag != NC_ATTRIBUTE:
            raise VectorFieldError(f"expected an attribute list, found tag {tag}")
        out = {}
        for _ in range(n):
            name = self.name()
            code, count = self.u32(), self.u32()
            if code not in NC_NAMES:
                raise VectorFieldError(f"unknown attribute type {code}")
            typ = NC_NAMES[code]
            raw = self.take(count * NC_TYPES[typ][1])
            self.take(_pad4(len(raw)))
            out[name] = _decode_attribute(typ, raw, count)
        return out


def _decode_attribute(typ, raw, count):
    if typ == "char":
        return raw.decode("utf-8", errors="replace")
    arr = np.frombuffer(raw, dtype=NC_TYPES[typ][2], count=count)
    if count == 1:
        return arr[0].item()
    return [x.item() for x in arr]


def netcdf_read(data):
    """The dimensions, global attributes and variables of a classic or 64-bit offset NetCDF file. Each variable
    is {type, dims, attributes, data}; the record dimension reports the number of records."""
    data = bytes(data)
    if len(data) < 32 or data[:3] != b"CDF":
        raise VectorFieldError("not a classic NetCDF file (no CDF magic; NetCDF-4/HDF5 files are not read here)")
    version = data[3]
    if version not in (1, 2):
        raise VectorFieldError(f"CDF version {version} is not supported (classic 1 and 64-bit offset 2 only)")
    rd = _Reader(data)
    rd.take(4)
    numrecs = rd.u32()
    tag, n = rd.u32(), rd.u32()
    dims = {}
    dim_names = []
    if tag == NC_DIMENSION:
        for _ in range(n):
            name = rd.name()
            size = rd.u32()
            dims[name] = size
            dim_names.append(name)
    elif not (tag == 0 and n == 0):
        raise VectorFieldError(f"expected a dimension list, found tag {tag}")
    record = next((d for d in dim_names if dims[d] == 0), None)
    attributes = rd.attributes()
    tag, n = rd.u32(), rd.u32()
    variables = {}
    plan = []
    if tag == NC_VARIABLE:
        for _ in range(n):
            name = rd.name()
            nd = rd.u32()
            dimids = [rd.u32() for _ in range(nd)]
            if any(d >= len(dim_names) for d in dimids):
                raise VectorFieldError(f"variable {name} names an undefined dimension")
            vattrs = rd.attributes()
            code, vsize = rd.u32(), rd.u32()
            begin = struct.unpack(">i" if version == 1 else ">q", rd.take(4 if version == 1 else 8))[0]
            if code not in NC_NAMES:
                raise VectorFieldError(f"unknown variable type {code}")
            plan.append((name, NC_NAMES[code], [dim_names[d] for d in dimids], vattrs, vsize, begin))
    elif not (tag == 0 and n == 0):
        raise VectorFieldError(f"expected a variable list, found tag {tag}")
    recsize = sum(p[4] for p in plan if p[2] and p[2][0] == record)
    for name, typ, vdims, vattrs, vsize, begin in plan:
        unit = NC_TYPES[typ][1]
        dtype = NC_TYPES[typ][2]
        is_record = bool(vdims) and vdims[0] == record
        shape = [numrecs if d == record else dims[d] for d in vdims]
        if is_record:
            per = unit * int(np.prod(shape[1:])) if len(shape) > 1 else unit
            chunks = []
            for r in range(numrecs):
                start = begin + r * recsize
                if start + per > len(data):
                    raise VectorFieldError(f"variable {name} record {r} lies beyond the end of the file")
                chunks.append(data[start:start + per])
            raw = b"".join(chunks)
        else:
            per = unit * int(np.prod(shape)) if shape else unit
            if begin + per > len(data):
                raise VectorFieldError(f"variable {name} lies beyond the end of the file")
            raw = data[begin:begin + per]
        arr = np.frombuffer(raw, dtype=dtype).reshape(shape) if shape else np.frombuffer(raw, dtype=dtype)[0]
        variables[name] = {"type": typ, "dims": vdims, "attributes": vattrs, "data": arr}
    if record is not None:
        dims[record] = numrecs
    return {"dims": dims, "attributes": attributes, "variables": variables}


def netcdf_values(var):
    """A variable's values as floats: _FillValue and missing_value become NaN, then scale_factor and
    add_offset apply (CF conventions)."""
    attrs = var.get("attributes", {})
    data = np.asarray(var["data"])
    if data.dtype.kind == "S":
        raise VectorFieldError("a character variable has no numeric values")
    out = data.astype(float)
    for key in ("_FillValue", "missing_value"):
        if key in attrs:
            out = np.where(data == attrs[key], np.nan, out)
    scale = float(attrs.get("scale_factor", 1.0))
    offset = float(attrs.get("add_offset", 0.0))
    return out * scale + offset


# -------------------------------------------------------------------------------------------- the resolved cache


def flow_cache(steps, credit=""):
    """The flow cache: a 64-bit offset NetCDF file with dims time, lat, lon; time in seconds since 1970; lat
    north to south; u and v in m s-1 as float; CF-1.8 and the source's credit as global attributes."""
    lons = np.asarray(steps["lons"], dtype=float)
    lats = np.asarray(steps["lats"], dtype=float)
    times = [float(t) for t in steps["times"]]
    u = np.asarray(steps["u"], dtype=np.float32)
    v = np.asarray(steps["v"], dtype=np.float32)
    if u.shape != (len(times), len(lats), len(lons)) or v.shape != u.shape:
        raise VectorFieldError("u and v are (time, lat, lon) arrays")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise VectorFieldError("cache times must increase")
    if any(b >= a for a, b in zip(lats, lats[1:])):
        raise VectorFieldError("cache latitudes run north to south")
    if any(b <= a for a, b in zip(lons, lons[1:])):
        raise VectorFieldError("cache longitudes increase")
    variables = [
        {"name": "time", "dims": ["time"], "type": "double", "data": np.asarray(times),
         "attributes": {"units": "seconds since 1970-01-01T00:00:00Z", "standard_name": "time"}},
        {"name": "lat", "dims": ["lat"], "type": "float", "data": lats.astype(np.float32),
         "attributes": {"units": "degrees_north", "standard_name": "latitude"}},
        {"name": "lon", "dims": ["lon"], "type": "float", "data": lons.astype(np.float32),
         "attributes": {"units": "degrees_east", "standard_name": "longitude"}},
        {"name": "u", "dims": ["time", "lat", "lon"], "type": "float", "data": u,
         "attributes": {"units": "m s-1", "standard_name": "eastward_velocity"}},
        {"name": "v", "dims": ["time", "lat", "lon"], "type": "float", "data": v,
         "attributes": {"units": "m s-1", "standard_name": "northward_velocity"}},
    ]
    return netcdf_write({"time": len(times), "lat": len(lats), "lon": len(lons)}, variables,
                        {"Conventions": "CF-1.8", "title": "scene-render flow cache", "credit": str(credit)})


def read_flow_cache(data):
    nc = netcdf_read(data)
    for name in ("time", "lat", "lon", "u", "v"):
        if name not in nc["variables"]:
            raise VectorFieldError(f"flow cache lacks variable {name}")
    V = nc["variables"]
    if V["u"]["dims"] != ["time", "lat", "lon"] or V["v"]["dims"] != ["time", "lat", "lon"]:
        raise VectorFieldError("flow cache u and v are (time, lat, lon)")
    return {"times": [float(t) for t in V["time"]["data"]], "lats": V["lat"]["data"].astype(float),
            "lons": V["lon"]["data"].astype(float), "u": netcdf_values(V["u"]), "v": netcdf_values(V["v"]),
            "credit": nc["attributes"].get("credit", "")}


_UNITS = {"s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0, "min": 60.0, "minute": 60.0, "minutes": 60.0,
          "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0, "d": 86400.0, "day": 86400.0,
          "days": 86400.0}


def time_units(text):
    """A CF time unit "unit since origin" as (seconds per unit, origin in seconds since 1970)."""
    m = re.fullmatch(r"\s*(\w+)\s+since\s+(.+?)\s*", str(text))
    if not m or m.group(1).lower() not in _UNITS:
        raise VectorFieldError(f"time units are seconds, minutes, hours or days since a date: {text!r}")
    origin = m.group(2).strip()
    d = re.fullmatch(r"(\d{4}-\d{1,2}-\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?)?\s*(Z|[+-]\d{2}:?\d{2}|UTC)?",
                     origin)
    if not d:
        raise VectorFieldError(f"time origin is a date or date-time: {origin!r}")
    y, mo, da = (int(x) for x in d.group(1).split("-"))
    hh, mm = int(d.group(2) or 0), int(d.group(3) or 0)
    ss = float(d.group(4) or 0)
    zone = d.group(5) or "Z"
    iso = f"{y:04d}-{mo:02d}-{da:02d}T{hh:02d}:{mm:02d}:{int(ss):02d}"
    if zone in ("Z", "UTC"):
        iso += "Z"
    else:
        iso += zone if ":" in zone else zone[:3] + ":" + zone[3:]
    return (_UNITS[m.group(1).lower()], parse_time(iso) + (ss - int(ss)))


def _sniff(data):
    if data[:4] == b"GRIB":
        return "grib2"
    if data[:3] == b"CDF":
        return "netcdf"
    if data[:8] == b"\x89HDF\r\n\x1a\n":
        raise VectorFieldError("NetCDF-4/HDF5 input is converted to classic NetCDF or GRIB2 before resolve")
    raise VectorFieldError("source is neither GRIB2 nor classic NetCDF")


def _grib_steps(asset, files, warnings):
    want_u, want_v = parameter(asset.get("u", UVGRID_DEFAULTS["u"])), parameter(asset.get("v", UVGRID_DEFAULTS["v"]))
    want_s = surface(asset.get("surface", UVGRID_DEFAULTS["surface"]))
    fields = {}
    grid = None
    for name in asset["src"]:
        for m in grib2_messages(files[name]):
            key = (m["discipline"], m["category"], m["number"])
            if key not in (want_u, want_v) or m["surface"] != want_s:
                continue
            g = {k: m["grid"][k] for k in ("ni", "nj", "la1", "lo1", "la2", "lo2", "di", "dj")}
            if grid is None:
                grid = g
            elif g != grid:
                raise VectorFieldError("every message of a uvGrid asset lies on the same grid")
            valid = m["reference"] + m["forecast"]
            fields.setdefault(valid, {})["u" if key == want_u else "v"] = m["values"]
    if grid is None:
        raise VectorFieldError("no message matches the asset's u, v and surface")
    complete = sorted(t for t, f in fields.items() if "u" in f and "v" in f)
    if len(complete) < len(fields):
        warnings.append("W-VF2")
    if not complete:
        raise VectorFieldError("no valid time holds both components")
    lons = grid["lo1"] + grid["di"] * np.arange(grid["ni"])
    lats = grid["la1"] - grid["dj"] * np.arange(grid["nj"])
    return {"lons": lons, "lats": lats, "times": complete,
            "u": np.stack([fields[t]["u"] for t in complete]), "v": np.stack([fields[t]["v"] for t in complete])}


def _coordinate(nc, dim, kinds):
    var = nc["variables"].get(dim)
    if var is None:
        raise VectorFieldError(f"dimension {dim} has no coordinate variable")
    units = str(var["attributes"].get("units", "")).lower()
    kind = None
    if "since" in units:
        kind = "time"
    elif units.startswith("degrees_north") or dim.lower() in ("lat", "latitude"):
        kind = "lat"
    elif units.startswith("degrees_east") or dim.lower() in ("lon", "longitude"):
        kind = "lon"
    if kind not in kinds:
        raise VectorFieldError(f"dimension {dim} is not a {'/'.join(kinds)} coordinate")
    return kind, var


def _netcdf_steps(asset, files, warnings):
    u_name, v_name = asset.get("u", UVGRID_DEFAULTS["u"]), asset.get("v", UVGRID_DEFAULTS["v"])
    parts = []
    for name in asset["src"]:
        nc = netcdf_read(files[name])
        if u_name not in nc["variables"] or v_name not in nc["variables"]:
            raise VectorFieldError(f"{name} lacks variables {u_name} and {v_name}")
        uvar, vvar = nc["variables"][u_name], nc["variables"][v_name]
        if uvar["dims"] != vvar["dims"] or len(uvar["dims"]) != 3:
            raise VectorFieldError("u and v are (time, lat, lon) variables on the same dimensions")
        kinds = [_coordinate(nc, d, ("time", "lat", "lon")) for d in uvar["dims"]]
        if [k for k, _ in kinds] != ["time", "lat", "lon"]:
            raise VectorFieldError("u and v dimensions are ordered time, lat, lon")
        tvar, latvar, lonvar = (v for _, v in kinds)
        per, origin = time_units(tvar["attributes"].get("units", ""))
        times = [origin + per * float(t) for t in np.asarray(tvar["data"], dtype=float)]
        lats = np.asarray(latvar["data"], dtype=float)
        lons = np.asarray(lonvar["data"], dtype=float)
        u, v = netcdf_values(uvar), netcdf_values(vvar)
        if len(lats) > 1 and lats[1] > lats[0]:
            lats, u, v = lats[::-1], u[:, ::-1, :], v[:, ::-1, :]
        parts.append({"lons": lons, "lats": lats, "times": times, "u": u, "v": v})
    first = parts[0]
    for p in parts[1:]:
        if not (np.allclose(p["lons"], first["lons"]) and np.allclose(p["lats"], first["lats"])):
            raise VectorFieldError("every file of a uvGrid asset lies on the same grid")
    by_time = {}
    for p in parts:
        for k, t in enumerate(p["times"]):
            by_time[t] = (p["u"][k], p["v"][k])
    times = sorted(by_time)
    return {"lons": first["lons"], "lats": first["lats"], "times": times,
            "u": np.stack([by_time[t][0] for t in times]), "v": np.stack([by_time[t][1] for t in times])}


def resolve(asset, files):
    """The resolve step of a uvGrid asset: read its sources (bytes by name), pair the components by valid time,
    and return the flow cache, its SHA-256 and the warnings."""
    warnings = []
    src = asset.get("src")
    if isinstance(src, str):
        src = [src]
    if not src:
        raise VectorFieldError("a uvGrid asset names at least one source")
    asset = dict(asset, src=src)
    fmt = asset.get("format", UVGRID_DEFAULTS["format"])
    if fmt not in FORMATS:
        raise VectorFieldError(f"format is auto, grib2 or netcdf: {fmt!r}")
    for name in src:
        if name not in files:
            raise VectorFieldError(f"source {name} is not available")
    if fmt == "auto":
        kinds = {_sniff(files[n]) for n in src}
        if len(kinds) != 1:
            raise VectorFieldError("all sources of a uvGrid asset share one format")
        fmt = kinds.pop()
    steps = _grib_steps(asset, files, warnings) if fmt == "grib2" else _netcdf_steps(asset, files, warnings)
    cache = flow_cache(steps, credit=asset.get("credit", ""))
    return {"cache": cache, "cacheSha256": sha256(cache), "warnings": warnings, "times": steps["times"]}


# --------------------------------------------------------------------------------------------------------- sampling


def wraps(lons):
    """True when the longitudes cover the globe: the step past the last one reaches the first plus 360."""
    lons = np.asarray(lons, dtype=float)
    if len(lons) < 2:
        return False
    step = lons[1] - lons[0]
    return bool(abs((lons[-1] + step) - (lons[0] + 360.0)) < 1e-6)


def sampler(cache):
    """f(lon, lat, T) -> (u, v): bilinear in longitude and latitude, linear in time and clamped to the cache's
    time span; None outside the grid or when a contributing corner is missing (NaN)."""
    lons = np.asarray(cache["lons"], dtype=float)
    lats = np.asarray(cache["lats"], dtype=float)
    times = [float(t) for t in cache["times"]]
    u = np.asarray(cache["u"], dtype=float)
    v = np.asarray(cache["v"], dtype=float)
    wrap = wraps(lons)
    nlon = len(lons)
    span = (lons[0] + 360.0 - lons[-1]) if wrap else None

    def lon_index(lon):
        if wrap:
            x = (lon - lons[0]) % 360.0 + lons[0]
        else:
            x = lon
            for shift in (0.0, 360.0, -360.0):
                if lons[0] <= lon + shift <= lons[-1]:
                    x = lon + shift
                    break
            else:
                return None
        if x >= lons[-1]:
            if not wrap:
                return (nlon - 2, 1.0) if nlon > 1 else None
            return (nlon - 1, (x - lons[-1]) / span)
        i = int(np.searchsorted(lons, x, side="right")) - 1
        i = max(0, min(i, nlon - 2))
        return (i, (x - lons[i]) / (lons[i + 1] - lons[i]))

    def lat_index(lat):
        if lat > lats[0] + 1e-9 or lat < lats[-1] - 1e-9:
            return None
        if len(lats) == 1:
            return (0, 0.0)
        if lat <= lats[-1]:
            return (len(lats) - 2, 1.0)
        j = int(np.searchsorted(-lats, -lat, side="right")) - 1
        j = max(0, min(j, len(lats) - 2))
        return (j, (lats[j] - lat) / (lats[j] - lats[j + 1]))

    def time_index(T):
        if len(times) == 1 or T <= times[0]:
            return (0, 0.0)
        if T >= times[-1]:
            return (len(times) - 2, 1.0)
        k = max(i for i in range(len(times) - 1) if times[i] <= T)
        return (k, (T - times[k]) / (times[k + 1] - times[k]))

    def sample(lon, lat, T):
        li = lon_index(lon)
        la = lat_index(lat)
        if li is None or la is None:
            return None
        i, fx = li
        j, fy = la
        i1 = (i + 1) % nlon
        j1 = min(j + 1, len(lats) - 1)
        k, ft = time_index(T)
        k1 = min(k + 1, len(times) - 1)
        corners = ((j, i, (1 - fx) * (1 - fy)), (j, i1, fx * (1 - fy)), (j1, i, (1 - fx) * fy), (j1, i1, fx * fy))
        out = [0.0, 0.0]
        for comp, field in enumerate((u, v)):
            total = 0.0
            for jj, ii, w in corners:
                if w <= 0.0:
                    continue
                a = field[k, jj, ii] * (1 - ft) + field[k1, jj, ii] * ft if ft > 0 else field[k, jj, ii]
                if not math.isfinite(a):
                    return None
                total += w * a
            out[comp] = total
        return (out[0], out[1])

    return sample


# -------------------------------------------------------------------------------------------------------- advection


def solid_body(omega):
    """The plane field u = -omega y, v = omega x (metres, seconds)."""
    return lambda p: (-omega * p[1], omega * p[0])


def plane_step(p, field, h):
    """One midpoint (RK2) step of h seconds in the plane."""
    k1 = field(p)
    mid = (p[0] + 0.5 * h * k1[0], p[1] + 0.5 * h * k1[1])
    k2 = field(mid)
    return (p[0] + h * k2[0], p[1] + h * k2[1])


def _advance(lon, lat, u, v, h):
    c = math.cos(math.radians(lat))
    if c < 1e-9:
        return None
    lon2 = lon + u * h / (R * c) * DEG
    lat2 = lat + v * h / R * DEG
    if not -90.0 <= lat2 <= 90.0:
        return None
    return (((lon2 + 180.0) % 360.0) - 180.0, lat2)


def sphere_step(p, fn, h, t):
    """One midpoint step of h seconds on the sphere: metres map to degrees through R and cos(latitude)
    (the half step at the start's latitude, the full step at the midpoint's). None when fn has no value."""
    lon, lat = p
    k1 = fn(lon, lat, t)
    if k1 is None:
        return None
    mid = _advance(lon, lat, k1[0], k1[1], 0.5 * h)
    if mid is None:
        return None
    k2 = fn(mid[0], mid[1], t)
    if k2 is None:
        return None
    c_mid = math.cos(math.radians(mid[1]))
    if c_mid < 1e-9:
        return None
    lon2 = lon + k2[0] * h / (R * c_mid) * DEG
    lat2 = lat + k2[1] * h / R * DEG
    if not -90.0 <= lat2 <= 90.0:
        return None
    return (((lon2 + 180.0) % 360.0) - 180.0, lat2)


def solid_body_sphere(omega, centre):
    """A solid-body rotation about centre in the local tangent plane (metres scaled by cos of the centre)."""
    clon, clat = centre
    scale = R * math.cos(math.radians(clat)) / DEG

    def fn(lon, lat, t):
        x = (lon - clon) * scale
        y = (lat - clat) * R / DEG
        return (-omega * y, omega * x)
    return fn


def ground_distance(a, b):
    """Great-circle distance in metres (haversine on R)."""
    lon1, lat1, lon2, lat2 = (math.radians(x) for x in (a[0], a[1], b[0], b[1]))
    s = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(s)))


# ---------------------------------------------------------------------------------------------------------- drawing


def ramp_stops(stops):
    """Validated colour stops: (t, colour) pairs with t strictly increasing within [0, 1]."""
    out = []
    try:
        for stop in stops:
            t, c = stop
            t = float(t)
            if not math.isfinite(t) or not 0.0 <= t <= 1.0:
                raise VectorFieldError(f"a stop position lies in 0..1: {t!r}")
            out.append((t, tuple(x / 255.0 for x in colour(c))))
    except (TypeError, ValueError) as e:
        if isinstance(e, VectorFieldError):
            raise
        raise VectorFieldError(f"colors are (position, colour) pairs: {stops!r}") from None
    if not out:
        raise VectorFieldError("colors need at least one stop")
    if any(b[0] <= a[0] for a, b in zip(out, out[1:])):
        raise VectorFieldError("stop positions must increase")
    return out


def ramp_colour(ramp, t):
    """The premultiplied colour of the ramp at t (clamped): straight RGBA interpolated linearly, then
    premultiplied, as MapLibre and webgl-wind's ramp texture do."""
    return _ramp_at(ramp_stops(ramp), t)


def _ramp_at(stops, t):
    t = min(1.0, max(0.0, float(t)))
    if t <= stops[0][0]:
        r, g, b, a = stops[0][1]
    elif t >= stops[-1][0]:
        r, g, b, a = stops[-1][1]
    else:
        i = max(k for k in range(len(stops) - 1) if stops[k][0] <= t)
        (t0, c0), (t1, c1) = stops[i], stops[i + 1]
        f = (t - t0) / (t1 - t0)
        r, g, b, a = (x + (y - x) * f for x, y in zip(c0, c1))
    return (r * a, g * a, b * a, a)


def speed_fraction(u, v, vmax):
    if vmax <= 0:
        return 0.0
    return min(1.0, math.hypot(u, v) / vmax)


def fade_buffer(buf, fade):
    """The trail after one frame: floor(255 c fade) / 255 per channel, so a trail reaches zero."""
    return np.floor(255.0 * np.asarray(buf, dtype=float) * fade) / 255.0


def paint(buf, positions, colours, width):
    """Paint particles over the buffer (premultiplied source-over): width <= 1 marks the pixel holding the
    position; larger widths mark every pixel whose centre lies within width / 2 of it."""
    h, w = buf.shape[:2]
    radius = width / 2.0
    for (x, y), c in zip(positions, colours):
        if width <= 1.0:
            px, py = math.floor(x), math.floor(y)
            if 0 <= px < w and 0 <= py < h:
                _over(buf, py, px, c)
            continue
        for py in range(max(0, math.floor(y - radius)), min(h, math.ceil(y + radius) + 1)):
            for px in range(max(0, math.floor(x - radius)), min(w, math.ceil(x + radius) + 1)):
                if math.hypot(px + 0.5 - x, py + 0.5 - y) <= radius:
                    _over(buf, py, px, c)


def _over(buf, py, px, c):
    a = c[3]
    buf[py, px, :] = np.asarray(c, dtype=float) + buf[py, px, :] * (1.0 - a)


# ----------------------------------------------------------------------------------------------------- the document


def world_pixel(lon, lat, zoom):
    return _ts.world_pixel(lon, lat, zoom)


def pixel_lonlat(x, y, zoom):
    """The inverse of world_pixel."""
    n = TILE * 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return (lon, lat)


def frame_time(child, frame, fps):
    """The data time of a frame: timeOrigin plus the animated `time` at frame / fps seconds."""
    return data_time(child.get("timeOrigin", FLOW_DEFAULTS["timeOrigin"]),
                     animated(child.get("time", FLOW_DEFAULTS["time"]), frame / float(fps)))


def _flow_child(doc):
    for child in doc["map"]["children"]:
        if child.get("kind") == "flow":
            return child
    raise VectorFieldError("the map has no flow child")


def _replay(doc, last):
    child = _flow_child(doc)
    asset = doc["assets"][child["grid"]]
    data = asset["data"]
    if sha256(data) != asset.get("cacheSha256"):
        raise VectorFieldError("the flow cache's SHA-256 differs from the asset's cacheSha256")
    cache = read_flow_cache(data)
    cfg = {k: child.get(k, d) for k, d in FLOW_DEFAULTS.items()}
    fps = float(doc["project"]["fps"])
    frame = _ts._frame(doc)
    w, h, zoom = frame["width"], frame["height"], frame["zoom"]
    ox, oy = frame["origin"]
    n = int(cfg["particles"])
    e = element_seed(doc["project"].get("seed", 0), child["id"], child.get("seed"), "stream")
    ramp = ramp_stops(cfg["colors"])
    opacity = float(cfg["opacity"])
    sample = sampler(cache)
    speeds = np.hypot(cache["u"], cache["v"])
    vmax = float(np.nanmax(speeds)) if np.isfinite(speeds).any() else 0.0
    h_step = float(cfg["speedup"]) / fps
    px, py = PURPOSES["spawnX"], PURPOSES["spawnY"]
    pos = [(stream(e, px, 0, i) * w, stream(e, py, 0, i) * h) for i in range(n)]
    buf = np.zeros((h, w, 4))
    digests = []
    respawned = 0
    speed = []
    for k in range(last + 1):
        T = frame_time(child, k, fps)
        samples = []
        for x, y in pos:
            lon, lat = pixel_lonlat(x + ox, y + oy, zoom)
            samples.append((lon, lat, sample(lon, lat, T)))
        buf = fade_buffer(buf, cfg["fade"])
        drawn, colours = [], []
        speed = []
        for (x, y), (lon, lat, s) in zip(pos, samples):
            if s is None:
                continue
            sp = math.hypot(s[0], s[1])
            speed.append(sp)
            c = _ramp_at(ramp, speed_fraction(s[0], s[1], vmax))
            drawn.append((x, y))
            colours.append(tuple(v * opacity for v in c))
        paint(buf, drawn, colours, float(cfg["strokeWidth"]))
        digests.append(digest(buf))
        if k == last:
            break
        respawned = 0
        new = []
        for i, ((x, y), (lon, lat, s)) in enumerate(zip(pos, samples)):
            moved = None
            if s is not None:
                q = sphere_step((lon, lat), lambda lo, la, t: sample(lo, la, T), h_step, T)
                if q is not None:
                    gx, gy = world_pixel(q[0], q[1], zoom)
                    nx, ny = gx - ox, gy - oy
                    if 0.0 <= nx < w and 0.0 <= ny < h:
                        moved = (nx, ny)
                drop = cfg["dropRate"] + speed_fraction(s[0], s[1], vmax) * cfg["dropBump"]
                if moved is not None and stream(e, PURPOSES["drop"], k, i) < drop:
                    moved = None
            if moved is None:
                moved = (stream(e, px, k + 1, i) * w, stream(e, py, k + 1, i) * h)
                respawned += 1
            new.append(moved)
        pos = new
    T = frame_time(child, last, fps)
    warnings = []
    if T < cache["times"][0] or T > cache["times"][-1]:
        warnings.append("W-VF1")
    return {"T": T, "particles": n, "respawned": respawned,
            "speed": {"mean": float(np.mean(speed)) if speed else 0.0, "max": float(max(speed)) if speed else 0.0},
            "covered": int((buf[..., 3] > 0).sum()), "warnings": warnings, "digest": digests[-1],
            "positions": digest([[round(x, 6), round(y, 6)] for x, y in pos]), "digests": digests}


def run(doc, frame):
    """The flow child at a frame: data time, particle count, respawns in the last update, speeds, covered
    pixels, warnings and the digests of the trail buffer and the positions."""
    out = _replay(doc, int(frame))
    del out["digests"]
    return out


def trace(doc, frame):
    """The trail digests of frames 0 to frame from one replay; trace(doc, k)[j] == run(doc, j)["digest"]."""
    return _replay(doc, int(frame))["digests"]


# ------------------------------------------------------------------------------------------------------- validation


def _is_number(v):
    return _ts._is_number(v)


def validate_document(doc):
    """The draft's validation: (code, message) pairs ordered VF1, VF2, VF3, VF4, V17."""
    errors = []
    assets = doc.get("assets", {})
    for aid, asset in assets.items():
        if asset.get("kind") != "uvGrid":
            continue
        for key in asset:
            if key not in KNOWN_UVGRID:
                errors.append(("V17", f"uvGrid {aid}: unknown attribute {key!r}"))
        fmt = asset.get("format", UVGRID_DEFAULTS["format"])
        if fmt not in FORMATS:
            errors.append(("VF1", f"uvGrid {aid}: format is auto, grib2 or netcdf, not {fmt!r}"))
            fmt = "auto"
        for comp in ("u", "v"):
            name = asset.get(comp, UVGRID_DEFAULTS[comp])
            ok = False
            if fmt in ("grib2", "auto"):
                try:
                    parameter(name)
                    ok = True
                except VectorFieldError:
                    ok = False
            if not ok and fmt in ("netcdf", "auto"):
                ok = isinstance(name, str) and re.fullmatch(r"[A-Za-z_][\w]*", name) is not None
            if not ok:
                errors.append(("VF1", f"uvGrid {aid}: {comp} is not a parameter or variable name: {name!r}"))
        try:
            surface(asset.get("surface", UVGRID_DEFAULTS["surface"]))
        except VectorFieldError as e:
            errors.append(("VF1", f"uvGrid {aid}: {e}"))
        src = asset.get("src")
        if not src or not (isinstance(src, str) or (isinstance(src, list) and all(isinstance(s, str) for s in src))):
            errors.append(("VF1", f"uvGrid {aid}: src names one or more files"))
        if not isinstance(asset.get("cache"), str) or not asset.get("cache"):
            errors.append(("VF1", f"uvGrid {aid}: cache names the flow cache file"))
        sha = asset.get("cacheSha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            errors.append(("VF1", f"uvGrid {aid}: cacheSha256 is the 64-digit SHA-256 of the cache"))
        elif "data" in asset and sha256(asset["data"]) != sha:
            errors.append(("VF1", f"uvGrid {aid}: the cache does not match cacheSha256"))
    for child in doc.get("map", {}).get("children", []):
        if child.get("kind") != "flow":
            continue
        cid = child.get("id", "?")
        for key in child:
            if key not in KNOWN_FLOW:
                errors.append(("V17", f"flow {cid}: unknown attribute {key!r}"))
        grid = child.get("grid")
        if grid not in assets or assets[grid].get("kind") != "uvGrid":
            errors.append(("VF3", f"flow {cid}: grid must name a uvGrid asset, not {grid!r}"))
        cfg = {k: child.get(k, d) for k, d in FLOW_DEFAULTS.items()}
        p = cfg["particles"]
        if not (isinstance(p, (int, np.integer)) and not isinstance(p, bool) and 1 <= p <= MAX_PARTICLES):
            errors.append(("VF2", f"flow {cid}: particles is an integer 1..{MAX_PARTICLES}"))
        if not (_is_number(cfg["speedup"]) and cfg["speedup"] > 0):
            errors.append(("VF2", f"flow {cid}: speedup is positive"))
        if not (_is_number(cfg["fade"]) and 0.0 <= cfg["fade"] < 1.0):
            errors.append(("VF2", f"flow {cid}: fade lies in [0, 1)"))
        if not (_is_number(cfg["dropRate"]) and 0.0 <= cfg["dropRate"] <= 1.0):
            errors.append(("VF2", f"flow {cid}: dropRate lies in [0, 1]"))
        if not (_is_number(cfg["dropBump"]) and 0.0 <= cfg["dropBump"] <= 1.0):
            errors.append(("VF2", f"flow {cid}: dropBump lies in [0, 1]"))
        if not (_is_number(cfg["strokeWidth"]) and cfg["strokeWidth"] > 0):
            errors.append(("VF2", f"flow {cid}: strokeWidth is positive"))
        if not (_is_number(cfg["opacity"]) and 0.0 <= cfg["opacity"] <= 1.0):
            errors.append(("VF2", f"flow {cid}: opacity lies in [0, 1]"))
        if not (isinstance(cfg["seed"], (int, np.integer)) and not isinstance(cfg["seed"], bool)):
            errors.append(("VF2", f"flow {cid}: seed is an integer"))
        try:
            ramp_stops(cfg["colors"])
        except VectorFieldError as e:
            errors.append(("VF2", f"flow {cid}: {e}"))
        try:
            parse_time(cfg["timeOrigin"])
        except VectorFieldError as e:
            errors.append(("VF4", f"flow {cid}: timeOrigin {e}"))
        try:
            animated(cfg["time"], 0.0)
        except VectorFieldError as e:
            errors.append(("VF4", f"flow {cid}: time {e}"))
    return sorted(errors, key=lambda c: CODE_ORDER.index(c[0]))


# ------------------------------------------------------------------------------------------------------ the example


def _example_cache():
    lons = np.arange(-20.0, 20.01, 2.5)
    lats = np.arange(15.0, -15.01, -2.5)
    times = [0.0, 3600.0, 6000.0]
    lat_g, lon_g = np.meshgrid(lats, lons, indexing="ij")
    u = np.stack([12.0 + 6.0 * np.sin(np.pi * lat_g / 15.0) * (1.0 + 0.1 * k) for k in range(3)])
    v = np.stack([4.0 * np.cos(np.pi * lon_g / 20.0) - 1.0 * k for k in range(3)])
    return flow_cache({"lons": lons, "lats": lats, "times": times, "u": u, "v": v}, credit="synthetic field")


def example_document():
    cache = _example_cache()
    return {
        "project": {"fps": 24, "seed": 0},
        "map": {"width": 160, "height": 120, "centerLon": 0.0, "centerLat": 0.0, "zoom": 3,
                "children": [{"kind": "flow", "id": "wind-flow", "grid": "wind", "particles": 256, "seed": 7,
                              "speedup": 60000.0, "dropRate": 0.05, "time": {"keys": [[0.0, 0.0], [1.5, 7200.0]]}}]},
        "assets": {"wind": {"kind": "uvGrid", "id": "wind", "src": ["gfs-000.grib2", "gfs-001.grib2"],
                            "format": "grib2", "u": "UGRD", "v": "VGRD", "surface": "103:10",
                            "cache": "wind.nc", "cacheSha256": sha256(cache), "data": cache}},
    }


def bad_document():
    doc = example_document()
    doc["map"]["children"][0].update({"particles": 0, "grid": "nowhere", "timeOrigin": "noon", "glow": 1})
    doc["assets"]["wind"]["format"] = "csv"
    return doc


# ------------------------------------------------------------------------------------------------- the numeric table


TINY = bytes.fromhex(
    "43444601" "00000000" "0000000a" "00000001" "00000003" "64696d00" "00000005" "00000000" "00000000"
    "0000000b" "00000001" "00000002" "76780000" "00000001" "00000000" "00000000" "00000000" "00000003"
    "0000000c" "00000050" "0003" "0001" "0004" "0001" "0005" "8001")
TINY_VAR = {"name": "vx", "dims": ["dim"], "type": "short", "data": [3, 1, 4, 1, 5]}

TABLE = (
    ("the element seed", "element_seed(0, 'flow', 7, 'stream')", "1330450823"),
    ("a stream draw", "round(stream(E0, 1, 5, 9), 6)", "0.973331"),
    ("two-bit packing", "pack_bits([0, 1, 2, 3], 2)", "b'\\x1b'"),
    ("simple unpacking", "simple_values(np.array([0, 1, 2, 3]), 1.5, -1, 0).tolist()", "[1.5, 2.0, 2.5, 3.0]"),
    ("a sign-magnitude short", "sign_magnitude(b'\\x80\\x05', 16)", "-5"),
    ("the test message's length", "len(MSG)", "377"),
    ("the round trip within one step", "float(np.abs(grib2_messages(MSG)[0]['values'] - FIELD).max()) <= STEP", "True"),
    ("the round trip's grid", "grib2_messages(MSG)[0]['grid']['la1']", "16.0"),
    ("three hours in seconds", "forecast_seconds(1, 3)", "10800.0"),
    ("the wind parameters", "(parameter('UGRD'), parameter('VGRD'))", "((0, 2, 2), (0, 2, 3))"),
    ("the specification's tiny file", "netcdf_write({'dim': 5}, [TINY_VAR], {}, version=1) == TINY", "True"),
    ("its length", "len(TINY)", "92"),
    ("packed values with a fill", "netcdf_values(NC['variables']['s'])[0, 0, :3].tolist()", "[10.5, 11.0, 11.5]"),
    ("the flow cache's magic", "CACHE[:4]", "b'CDF\\x02'"),
    ("the resolved warnings", "RESOLVED['warnings']", "['W-VF2']"),
    ("the resolved times", "RESOLVED['times']", "[0.0, 3600.0]"),
    ("a bilinear sample between steps", "tuple(round(c, 6) for c in SAMPLER(2.0, 2.0, 1800.0))", "(3.75, 0.15)"),
    ("a sample across the date line", "WRAP(315.0, 0.0, 0.0)", "(1.5, 0.0)"),
    ("the circle's radius after 100 steps", "round(math.hypot(*CIRCLE), 3)", "1000.0"),
    ("the circle's angle after 100 steps", "round(math.atan2(CIRCLE[1], CIRCLE[0]), 4)", "1.0"),
    ("a sphere step at 60 degrees north", "tuple(round(c, 6) for c in sphere_step((0.0, 60.0), EAST, 1000.0, 0.0))", "(0.179663, 60.0)"),
    ("the ramp between its first stops", "tuple(round(c, 4) for c in ramp_colour(DEFAULT_RAMP, 0.05))", "(0.298, 0.6471, 0.6941, 1.0)"),
    ("one frame of fade", "round(float(fade_buffer(np.ones((1, 1, 4)), 0.996)[0, 0, 0]), 6)", "0.992157"),
    ("pixels of a 3-px particle", "int((PAINTED[..., 3] > 0).sum())", "9"),
    ("the data time of frame 30", "frame_time(FLOW, 30, 24)", "6000.0"),
    ("the example at frame 12", "(RUN['T'], RUN['particles'], RUN['respawned'], RUN['covered'])", "(2400.0, 256, 11, 2953)"),
    ("the example's speeds", "(round(RUN['speed']['mean'], 3), round(RUN['speed']['max'], 3))", "(12.068, 18.662)"),
    ("the example's digest", "RUN['digest']", "'5ac9db93e777'"),
    ("the seek check", "trace(EXAMPLE, 12)[5] == run(EXAMPLE, 5)['digest']", "True"),
    ("the warning past the cache", "run(EXAMPLE, 36)['warnings']", "['W-VF1']"),
    ("the bad document's codes", "[c for c, _ in validate_document(bad_document())]", "['VF1', 'VF2', 'VF3', 'VF4', 'V17']"),
)

_SCOPE = {}


def scope():
    """The names the numeric table evaluates in; built once per process."""
    if _SCOPE:
        return dict(_SCOPE)
    s = {k: v for k, v in globals().items() if not k.startswith("__")}
    s["math"] = math
    s["np"] = np
    s["E0"] = element_seed(0, "flow", 7, "stream")
    y, x = np.mgrid[0:9, 0:11]
    field = 5.0 * np.sin(x / 3.0) - 3.0 * np.cos(y / 2.0)
    s["FIELD"] = field
    s["STEP"] = (field.max() - field.min()) / (2 ** 16 - 1)
    s["MSG"] = encode_grib2(field, dict(la1=16.0, lo1=-20.0, la2=-16.0, lo2=20.0, di=4.0, dj=4.0), GRIB_UGRD,
                            (103, 10.0), "2026-10-24T00:00:00Z", 10800.0, bits=16)
    s["NC"] = netcdf_read(netcdf_write(
        {"time": 0, "lat": 3, "lon": 4},
        [{"name": "s", "dims": ["time", "lat", "lon"], "type": "short", "data": [[[1, 2, 3, 4]] * 3] * 2,
          "attributes": {"scale_factor": 0.5, "add_offset": 10.0, "_FillValue": 4}}], {}))
    lons = np.arange(-20.0, 20.1, 4.0)
    lats = np.arange(16.0, -16.1, -4.0)
    lat_g, lon_g = np.meshgrid(lats, lons, indexing="ij")
    steps = {"lons": lons, "lats": lats, "times": [0.0, 3600.0],
             "u": np.stack([5.0 + 0.0 * lon_g, 2.5 + 0.0 * lon_g]), "v": np.stack([0.1 * lon_g, 0.05 * lon_g])}
    s["STEPS"] = steps
    s["CACHE"] = flow_cache(steps, credit="synthetic")
    s["SAMPLER"] = sampler(steps)
    grid = dict(la1=16.0, lo1=-20.0, la2=-16.0, lo2=20.0, di=4.0, dj=4.0)
    files = {}
    for k, hours in enumerate((0, 1)):
        files[f"f{hours}.grib2"] = (
            encode_grib2(steps["u"][k], grid, GRIB_UGRD, (103, 10.0), 0.0, hours * 3600.0)
            + encode_grib2(steps["v"][k], grid, GRIB_VGRD, (103, 10.0), 0.0, hours * 3600.0))
    files["f2.grib2"] = encode_grib2(steps["u"][1], grid, GRIB_UGRD, (103, 10.0), 0.0, 7200.0)
    s["RESOLVED"] = resolve({"kind": "uvGrid", "id": "wind", "src": list(files), "format": "grib2",
                             "cache": "wind.nc"}, files)
    s["WRAP"] = sampler({"lons": np.arange(0.0, 360.0, 90.0), "lats": np.array([45.0, -45.0]), "times": [0.0],
                         "u": np.array([[[0.0, 1.0, 2.0, 3.0]] * 2]), "v": np.zeros((1, 2, 4))})
    p = (1000.0, 0.0)
    f = solid_body(1e-3)
    for _ in range(100):
        p = plane_step(p, f, 10.0)
    s["CIRCLE"] = p
    s["EAST"] = lambda lon, lat, t: (10.0, 0.0)
    painted = np.zeros((7, 7, 4))
    paint(painted, [(3.5, 3.5)], [(1.0, 1.0, 1.0, 1.0)], 3.0)
    s["PAINTED"] = painted
    s["EXAMPLE"] = example_document()
    s["FLOW"] = s["EXAMPLE"]["map"]["children"][0]
    s["RUN"] = run(s["EXAMPLE"], 12)
    _SCOPE.update(s)
    return dict(s)


_same = _ts._same
_fmt = _ts._fmt


def main():
    s = scope()
    print("| Test | Expression | Value |")
    print("|---|---|---|")
    for name, expr, _ in TABLE:
        print(f"| {name} | `{expr}` | `{_fmt(eval(expr, s))}` |")


if __name__ == "__main__":
    main()
