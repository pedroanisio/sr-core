"""Tests for the draft SREP "Add vector-field layers to the map" (M4 of SREP 12) and its reference module."""
import hashlib
import importlib.util
import math
import os
import re
import struct
import zlib

import pytest

np = pytest.importorskip("numpy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "conformance", "tools", "vector_field_reference.py")
DRAFT = os.path.join(ROOT, "srep", "srep-0000-vector-field.md")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vf = _load(MODULE, "vector_field_reference")


def _close(a, b, tol=1e-6):
    if isinstance(a, (tuple, list, np.ndarray)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------------------------------------- streams


def test_the_element_seed_is_the_crc32_of_the_random_streams_draft():
    assert vf.element_seed(0, "flow", 7, "stream") == zlib.crc32(b"0:flow:7:stream")
    assert vf.element_seed(3, "", None, "stream") == zlib.crc32(b"3:::stream")
    assert vf.element_seed(0, "flow", 7, "stream") != vf.element_seed(0, "flow", 8, "stream")


def test_stream_draws_are_addressed_not_sequenced():
    e = vf.element_seed(0, "flow", 7, "stream")
    a = vf.stream(e, 1, 5, 9)
    for _ in range(3):
        vf.stream(e, 2, 0, 0)
    assert vf.stream(e, 1, 5, 9) == a
    assert 0.0 <= a < 1.0
    assert vf.stream(e, 1, 5, 9) != vf.stream(e, 1, 6, 9) != vf.stream(e, 1, 5, 10)
    # S(e, p, t, i) = U(e, p + t * 2^32, i)
    assert vf.stream(e, 1, 5, 9) == vf.U(e, 1 + 5 * 2 ** 32, 9)
    assert vf.U(0, 0, 0) == (vf.H(0, 0, 0) >> 11) / 2.0 ** 53


# ------------------------------------------------------------------------------------------------------------ GRIB2


GRID = dict(la1=50.0, lo1=-10.0, la2=30.0, lo2=10.0, di=0.25, dj=0.25)


def _field(nj=81, ni=81):
    y, x = np.mgrid[0:nj, 0:ni]
    return 5.0 * np.sin(x / 7.0) - 3.0 * np.cos(y / 5.0) + 0.01 * x


def test_a_grib2_message_round_trips_through_the_writer_and_the_reader():
    values = _field()
    msg = vf.encode_grib2(values, GRID, parameter=(0, 2, 2), surface=(103, 10.0),
                          reference="2026-10-24T00:00:00Z", forecast=10800.0, bits=16)
    assert msg[:4] == b"GRIB" and msg[-4:] == b"7777" and msg[7] == 2
    assert struct.unpack(">Q", msg[8:16])[0] == len(msg)
    out = vf.grib2_messages(msg)
    assert len(out) == 1
    m = out[0]
    assert (m["discipline"], m["category"], m["number"]) == (0, 2, 2)
    assert m["surface"] == (103, 10.0)
    assert m["reference"] == vf.parse_time("2026-10-24T00:00:00Z") and m["forecast"] == 10800.0
    assert m["grid"] == {"ni": 81, "nj": 81, "la1": 50.0, "lo1": -10.0, "la2": 30.0, "lo2": 10.0, "di": 0.25,
                         "dj": 0.25, "scan": 0}
    assert m["values"].shape == (81, 81)
    step = (values.max() - values.min()) / (2 ** 16 - 1)
    assert np.abs(m["values"] - values).max() <= step


def test_simple_packing_follows_regulation_92_9_4():
    # Y = (R + X * 2^E) / 10^D, with E and D in sign-magnitude form
    packed = vf.pack_bits([0, 1, 2, 3], 2)
    assert packed == bytes([0b00011011])
    assert vf.unpack_bits(packed, 2, 4) == [0, 1, 2, 3]
    assert vf.simple_values(np.array([0, 1, 2, 3]), reference=1.5, binary_scale=-1, decimal_scale=0).tolist() == \
        [1.5, 2.0, 2.5, 3.0]
    assert vf.simple_values(np.array([0, 10]), reference=100.0, binary_scale=0, decimal_scale=2).tolist() == [1.0, 1.1]
    assert vf.sign_magnitude(b"\x80\x05", 16) == -5 and vf.sign_magnitude(b"\x00\x05", 16) == 5
    assert vf.to_sign_magnitude(-5, 16) == b"\x80\x05" and vf.to_sign_magnitude(7, 32) == b"\x00\x00\x00\x07"
    assert vf.sign_magnitude(vf.to_sign_magnitude(-123456, 32), 32) == -123456


def test_negative_coordinates_decimal_scaling_and_constant_fields_decode():
    values = np.full((3, 4), -2.5)
    grid = dict(la1=-10.0, lo1=-170.0, la2=-12.0, lo2=-167.0, di=1.0, dj=1.0)
    msg = vf.encode_grib2(values, grid, parameter=(0, 2, 3), surface=(103, 10.0), reference=0.0, forecast=0.0,
                          bits=8, decimal_scale=2)
    m = vf.grib2_messages(msg)[0]
    assert m["grid"]["la1"] == -10.0 and m["grid"]["lo1"] == -170.0 and m["grid"]["lo2"] == -167.0
    assert np.allclose(m["values"], -2.5)
    assert m["bits"] == 0  # a constant field packs no bits
    msg = vf.encode_grib2(np.array([[1.234, 5.678]]), dict(la1=0.0, lo1=0.0, la2=0.0, lo2=1.0, di=1.0, dj=1.0),
                          parameter=(0, 2, 2), surface=(103, 10.0), reference=0.0, forecast=0.0, bits=12,
                          decimal_scale=3)
    m = vf.grib2_messages(msg)[0]
    assert np.abs(m["values"] - [[1.234, 5.678]]).max() <= 0.002


def test_scanning_modes_are_normalised_to_north_to_south_west_to_east():
    values = np.arange(12, dtype=float).reshape(3, 4)
    for scan in (0, 0x80, 0x40, 0xC0):
        msg = vf.encode_grib2(values, dict(la1=2.0, lo1=0.0, la2=0.0, lo2=3.0, di=1.0, dj=1.0), parameter=(0, 2, 2),
                              surface=(103, 10.0), reference=0.0, forecast=0.0, bits=8, scan=scan)
        m = vf.grib2_messages(msg)[0]
        assert m["grid"]["scan"] == scan
        assert np.allclose(m["values"], values), scan
        assert m["grid"]["la1"] == 2.0 and m["grid"]["lo1"] == 0.0
    with pytest.raises(vf.VectorFieldError):
        vf.encode_grib2(values, dict(la1=2.0, lo1=0.0, la2=0.0, lo2=3.0, di=1.0, dj=1.0), parameter=(0, 2, 2),
                        surface=(103, 10.0), reference=0.0, forecast=0.0, bits=8, scan=0x20)


def test_a_bitmap_marks_missing_points():
    values = np.arange(6, dtype=float).reshape(2, 3)
    mask = np.array([[True, False, True], [True, True, False]])
    msg = vf.encode_grib2(values, dict(la1=1.0, lo1=0.0, la2=0.0, lo2=2.0, di=1.0, dj=1.0), parameter=(0, 2, 2),
                          surface=(103, 10.0), reference=0.0, forecast=0.0, bits=8, present=mask)
    m = vf.grib2_messages(msg)[0]
    assert np.isnan(m["values"][0, 1]) and np.isnan(m["values"][1, 2])
    assert np.allclose(m["values"][mask], values[mask])


def test_forecast_time_units_and_several_messages():
    a = vf.encode_grib2(np.zeros((2, 2)), dict(la1=1.0, lo1=0.0, la2=0.0, lo2=1.0, di=1.0, dj=1.0),
                        parameter=(0, 2, 2), surface=(103, 10.0), reference=0.0, forecast=3 * 3600.0, bits=8)
    b = vf.encode_grib2(np.ones((2, 2)), dict(la1=1.0, lo1=0.0, la2=0.0, lo2=1.0, di=1.0, dj=1.0),
                        parameter=(0, 2, 3), surface=(103, 10.0), reference=0.0, forecast=6 * 3600.0, bits=8)
    out = vf.grib2_messages(a + b)
    assert [m["number"] for m in out] == [2, 3] and [m["forecast"] for m in out] == [10800.0, 21600.0]
    assert vf.TIME_UNITS == {0: 60.0, 1: 3600.0, 2: 86400.0, 10: 10800.0, 11: 21600.0, 12: 43200.0, 13: 1.0}
    assert vf.forecast_seconds(1, 3) == 10800.0 and vf.forecast_seconds(13, 90) == 90.0
    with pytest.raises(vf.VectorFieldError):
        vf.forecast_seconds(5, 1)


def test_malformed_grib2_is_refused():
    good = vf.encode_grib2(np.zeros((2, 2)), dict(la1=1.0, lo1=0.0, la2=0.0, lo2=1.0, di=1.0, dj=1.0),
                           parameter=(0, 2, 2), surface=(103, 10.0), reference=0.0, forecast=0.0, bits=8)
    for bad in (b"GRIB" + b"\x00" * 20, good[:40], b"NOPE" + good[4:], good[:7] + b"\x01" + good[8:],
                good[:-4] + b"7776"):
        with pytest.raises(vf.VectorFieldError):
            vf.grib2_messages(bad)
    # an unsupported grid template (3.30 Lambert) is refused, not guessed
    lambert = bytearray(good)
    i = 16 + struct.unpack(">I", good[16:20])[0]  # section 3 follows section 1
    assert lambert[i + 4] == 3
    lambert[i + 12:i + 14] = (30).to_bytes(2, "big")
    with pytest.raises(vf.VectorFieldError):
        vf.grib2_messages(bytes(lambert))


def test_parameter_names_map_to_grib2_numbers():
    assert vf.parameter("UGRD") == (0, 2, 2) and vf.parameter("VGRD") == (0, 2, 3)
    assert vf.parameter("0:2:2") == (0, 2, 2) and vf.parameter("10:1:2") == (10, 1, 2)
    assert vf.surface("103:10") == (103, 10.0) and vf.surface("1") == (1, 0.0)
    for bad in ("TMP:X", "0:2", "", None):
        with pytest.raises(vf.VectorFieldError):
            vf.parameter(bad)


# ----------------------------------------------------------------------------------------------------------- NetCDF


TINY = bytes.fromhex(
    "43444601" "00000000" "0000000a" "00000001" "00000003" "64696d00" "00000005" "00000000" "00000000"
    "0000000b" "00000001" "00000002" "76780000" "00000001" "00000000" "00000000" "00000000" "00000003"
    "0000000c" "00000050" "0003" "0001" "0004" "0001" "0005" "8001")


def test_the_writer_reproduces_the_specifications_examples_byte_for_byte():
    assert vf.netcdf_write({}, [], {}, version=1) == b"CDF\x01" + b"\x00" * 28
    tiny = vf.netcdf_write({"dim": 5}, [{"name": "vx", "dims": ["dim"], "type": "short", "data": [3, 1, 4, 1, 5]}], {},
                           version=1)
    assert len(TINY) == 92 and tiny == TINY


def test_the_reader_reads_the_tiny_file_and_both_versions():
    nc = vf.netcdf_read(TINY)
    assert nc["dims"] == {"dim": 5} and nc["attributes"] == {}
    assert nc["variables"]["vx"]["type"] == "short" and nc["variables"]["vx"]["dims"] == ["dim"]
    assert nc["variables"]["vx"]["data"].tolist() == [3, 1, 4, 1, 5]
    v2 = vf.netcdf_write({"dim": 5}, [{"name": "vx", "dims": ["dim"], "type": "short", "data": [3, 1, 4, 1, 5]}], {},
                         version=2)
    assert v2[:4] == b"CDF\x02" and len(v2) == 96
    assert vf.netcdf_read(v2)["variables"]["vx"]["data"].tolist() == [3, 1, 4, 1, 5]


def test_attributes_record_variables_and_packed_values_round_trip():
    u = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    packed = {"name": "s", "dims": ["time", "lat", "lon"], "type": "short", "data": [[[1, 2, 3, 4]] * 3] * 2,
              "attributes": {"scale_factor": 0.5, "add_offset": 10.0, "_FillValue": 4, "units": "m s-1"}}
    data = vf.netcdf_write({"time": 0, "lat": 3, "lon": 4},
                           [{"name": "lat", "dims": ["lat"], "type": "float", "data": [1.0, 0.0, -1.0]},
                            {"name": "time", "dims": ["time"], "type": "double", "data": [0.0, 3600.0]},
                            {"name": "u", "dims": ["time", "lat", "lon"], "type": "float", "data": u}, packed],
                           {"title": "flow cache", "steps": 2, "ratio": 0.25})
    nc = vf.netcdf_read(data)
    assert nc["dims"] == {"time": 2, "lat": 3, "lon": 4}
    assert nc["attributes"] == {"title": "flow cache", "steps": 2, "ratio": 0.25}
    assert nc["variables"]["time"]["data"].tolist() == [0.0, 3600.0]
    assert np.array_equal(nc["variables"]["u"]["data"], u)
    assert nc["variables"]["s"]["attributes"]["units"] == "m s-1"
    values = vf.netcdf_values(nc["variables"]["s"])
    assert values.shape == (2, 3, 4) and values[0, 0, :3].tolist() == [10.5, 11.0, 11.5] and np.isnan(values[0, 0, 3])
    for bad in (b"CDF\x03" + b"\x00" * 28, b"HDF\x01" + b"\x00" * 28, TINY[:60], b""):
        with pytest.raises(vf.VectorFieldError):
            vf.netcdf_read(bad)


# -------------------------------------------------------------------------------------------- the resolved cache


def _steps():
    lons = np.arange(-20.0, 20.1, 4.0)
    lats = np.arange(16.0, -16.1, -4.0)
    y, x = np.meshgrid(lats, lons, indexing="ij")
    return {"lons": lons, "lats": lats, "times": [0.0, 3600.0],
            "u": np.stack([5.0 + 0.0 * x, 2.5 + 0.0 * x]), "v": np.stack([0.1 * x, 0.05 * x])}


def test_the_flow_cache_is_a_classic_netcdf_file_the_reader_reads_back():
    steps = _steps()
    data = vf.flow_cache(steps, credit="synthetic")
    assert data[:4] == b"CDF\x02"
    nc = vf.netcdf_read(data)
    assert nc["dims"] == {"time": 2, "lat": 9, "lon": 11}
    assert nc["attributes"]["credit"] == "synthetic" and nc["attributes"]["Conventions"] == "CF-1.8"
    assert nc["variables"]["u"]["attributes"]["units"] == "m s-1"
    back = vf.read_flow_cache(data)
    assert back["times"] == [0.0, 3600.0]
    assert np.allclose(back["lons"], steps["lons"]) and np.allclose(back["lats"], steps["lats"])
    assert np.allclose(back["u"], steps["u"]) and np.allclose(back["v"], steps["v"])
    assert vf.sha256(data) == hashlib.sha256(data).hexdigest()
    assert vf.flow_cache(steps, credit="synthetic") == data  # the writer is deterministic


def test_resolve_pairs_u_and_v_messages_by_forecast_time():
    grid = dict(la1=16.0, lo1=-20.0, la2=-16.0, lo2=20.0, di=4.0, dj=4.0)
    steps = _steps()
    files = {}
    for k, hours in enumerate((0, 1)):
        files[f"f{hours}.grib2"] = (
            vf.encode_grib2(steps["u"][k], grid, parameter=(0, 2, 2), surface=(103, 10.0),
                            reference="2026-10-24T00:00:00Z", forecast=hours * 3600.0, bits=16) +
            vf.encode_grib2(steps["v"][k], grid, parameter=(0, 2, 3), surface=(103, 10.0),
                            reference="2026-10-24T00:00:00Z", forecast=hours * 3600.0, bits=16))
    files["f2.grib2"] = vf.encode_grib2(steps["u"][1], grid, parameter=(0, 2, 2), surface=(103, 10.0),
                                        reference="2026-10-24T00:00:00Z", forecast=7200.0, bits=16)
    asset = {"kind": "uvGrid", "id": "wind", "src": ["f0.grib2", "f1.grib2", "f2.grib2"], "format": "grib2",
             "u": "UGRD", "v": "VGRD", "surface": "103:10", "cache": "wind.nc"}
    result = vf.resolve(asset, files)
    assert result["warnings"] == ["W-VF2"]
    cache = vf.read_flow_cache(result["cache"])
    t0 = vf.parse_time("2026-10-24T00:00:00Z")
    assert cache["times"] == [t0, t0 + 3600.0]
    assert np.abs(cache["u"] - steps["u"]).max() < 1e-3 and np.abs(cache["v"] - steps["v"]).max() < 1e-3
    assert result["cacheSha256"] == hashlib.sha256(result["cache"]).hexdigest()
    with pytest.raises(vf.VectorFieldError):
        vf.resolve(dict(asset, src=["f2.grib2"]), files)  # no complete step


def test_resolve_reads_a_netcdf_source_with_named_variables():
    steps = _steps()
    source = vf.netcdf_write(
        {"time": 0, "latitude": 9, "longitude": 11},
        [{"name": "longitude", "dims": ["longitude"], "type": "float", "data": steps["lons"]},
         {"name": "latitude", "dims": ["latitude"], "type": "float", "data": steps["lats"][::-1]},
         {"name": "time", "dims": ["time"], "type": "double", "data": [0.0, 1.0 / 24.0],
          "attributes": {"units": "days since 2020-01-01 00:00:00"}},
         {"name": "uo", "dims": ["time", "latitude", "longitude"], "type": "float", "data": steps["u"][:, ::-1, :]},
         {"name": "vo", "dims": ["time", "latitude", "longitude"], "type": "float", "data": steps["v"][:, ::-1, :]}],
        {})
    asset = {"kind": "uvGrid", "id": "cur", "src": ["oscar.nc"], "format": "netcdf", "u": "uo", "v": "vo",
             "cache": "cur.nc"}
    result = vf.resolve(asset, {"oscar.nc": source})
    cache = vf.read_flow_cache(result["cache"])
    t0 = vf.parse_time("2020-01-01T00:00:00Z")
    assert cache["times"] == [t0, t0 + 3600.0]
    assert np.allclose(cache["lats"], steps["lats"])  # rows north to south
    assert np.allclose(cache["u"], steps["u"]) and np.allclose(cache["v"], steps["v"])
    assert vf.time_units("hours since 1970-01-01T00:00:00Z") == (3600.0, 0.0)
    assert vf.time_units("seconds since 2000-01-01 12:00:00") == (1.0, vf.parse_time("2000-01-01T12:00:00Z"))
    with pytest.raises(vf.VectorFieldError):
        vf.time_units("fortnights since 2000-01-01")


# --------------------------------------------------------------------------------------------------------- sampling


def test_the_sampler_is_bilinear_in_space_and_linear_in_time():
    s = vf.sampler(_steps())
    assert _close(s(0.0, 0.0, 0.0), (5.0, 0.0))
    assert _close(s(4.0, 0.0, 0.0), (5.0, 0.4))
    assert _close(s(2.0, 2.0, 0.0), (5.0, 0.2))
    assert _close(s(2.0, 2.0, 1800.0), (3.75, 0.15))
    assert _close(s(2.0, 2.0, 7200.0), (2.5, 0.1))  # clamped to the last step
    assert _close(s(2.0, 2.0, -5.0), (5.0, 0.2))
    assert s(25.0, 0.0, 0.0) is None and s(0.0, 17.0, 0.0) is None


def test_a_global_grid_wraps_in_longitude_and_fill_values_drop():
    lons = np.arange(0.0, 360.0, 90.0)
    lats = np.array([45.0, -45.0])
    u = np.array([[[0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.0, 3.0]]])
    v = np.zeros((1, 2, 4))
    s = vf.sampler({"lons": lons, "lats": lats, "times": [0.0], "u": u, "v": v})
    assert _close(s(315.0, 0.0, 0.0), (1.5, 0.0))  # between 270 and 360 (= 0)
    assert _close(s(-45.0, 0.0, 0.0), (1.5, 0.0))
    assert vf.wraps(lons) is True and vf.wraps(_steps()["lons"]) is False
    u2 = u.copy()
    u2[0, 0, 1] = np.nan
    s2 = vf.sampler({"lons": lons, "lats": lats, "times": [0.0], "u": u2, "v": v})
    assert s2(100.0, 10.0, 0.0) is None and _close(s2(100.0, -45.0, 0.0), (1.0 + 1.0 / 9.0, 0.0))


# -------------------------------------------------------------------------------------------------------- advection


def test_particles_in_a_solid_body_field_follow_the_analytic_circle():
    omega = 1e-3
    field = vf.solid_body(omega)
    p = (1000.0, 0.0)
    h = 10.0
    n = 100
    for _ in range(n):
        p = vf.plane_step(p, field, h)
    r = math.hypot(*p)
    assert abs(r - 1000.0) / 1000.0 < 1e-6
    assert abs(math.atan2(p[1], p[0]) - omega * n * h) < 1e-4
    # the midpoint rule, not Euler: one Euler step grows the radius by sqrt(1 + (omega h)^2)
    euler = (1000.0 * 1.0, 1000.0 * omega * h)
    assert math.hypot(*euler) > 1000.0 * (1.0 + 1e-6)


def test_the_sphere_step_moves_by_metres_over_the_local_scale():
    lon, lat = vf.sphere_step((0.0, 60.0), lambda lon_, lat_, t: (10.0, 0.0), 1000.0, 0.0)
    assert _close(lon, 10000.0 / (vf.R * math.cos(math.radians(60.0))) * 180.0 / math.pi, 1e-9)
    assert _close(lat, 60.0, 1e-9)
    lon, lat = vf.sphere_step((0.0, 0.0), lambda lon_, lat_, t: (0.0, -10.0), 1000.0, 0.0)
    assert _close(lat, -10000.0 / vf.R * 180.0 / math.pi, 1e-9) and _close(lon, 0.0, 1e-12)
    # a solid-body field on the sphere stays near its circle
    centre = (10.0, 20.0)
    field = vf.solid_body_sphere(2e-5, centre)
    p = (10.0 + 0.1, 20.0)
    for _ in range(50):
        p = vf.sphere_step(p, field, 100.0, 0.0)
    assert abs(vf.ground_distance(p, centre) - vf.ground_distance((10.1, 20.0), centre)) < 20.0
    assert vf.sphere_step((0.0, 0.0), lambda lon_, lat_, t: None, 1.0, 0.0) is None


# ---------------------------------------------------------------------------------------------------------- drawing


def test_the_colour_ramp_is_webgl_winds_default():
    assert vf.DEFAULT_RAMP[0] == (0.0, "#3288bd") and vf.DEFAULT_RAMP[-1] == (1.0, "#d53e4f")
    assert len(vf.DEFAULT_RAMP) == 8
    assert _close(vf.ramp_colour(vf.DEFAULT_RAMP, 0.0), (0x32 / 255, 0x88 / 255, 0xBD / 255, 1.0))
    mid = vf.ramp_colour(vf.DEFAULT_RAMP, 0.05)
    assert _close(mid, tuple((a + b) / 2 for a, b in zip((0x32 / 255, 0x88 / 255, 0xBD / 255, 1.0),
                                                        (0x66 / 255, 0xC2 / 255, 0xA5 / 255, 1.0))))
    assert _close(vf.ramp_colour(vf.DEFAULT_RAMP, 1.5), (0xD5 / 255, 0x3E / 255, 0x4F / 255, 1.0))
    assert vf.speed_fraction(3.0, 4.0, 10.0) == 0.5 and vf.speed_fraction(30.0, 40.0, 10.0) == 1.0
    with pytest.raises(vf.VectorFieldError):
        vf.ramp_stops([(0.5, "#fff"), (0.2, "#000")])
    with pytest.raises(vf.VectorFieldError):
        vf.ramp_stops([(0.0, "nope")])


def test_the_trail_fades_by_the_quantised_rule():
    buf = np.full((2, 2, 4), 1.0)
    out = vf.fade_buffer(buf, 0.996)
    assert np.allclose(out, 253.0 / 255.0)
    small = np.full((1, 1, 4), 1.0 / 255.0)
    assert vf.fade_buffer(small, 0.996).sum() == 0.0
    assert np.array_equal(vf.fade_buffer(np.zeros((1, 1, 4)), 0.5), np.zeros((1, 1, 4)))


def test_particles_paint_the_pixel_that_holds_them():
    buf = np.zeros((4, 4, 4))
    vf.paint(buf, [(1.7, 2.2), (3.99, 0.01)], [(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0)], 1.0)
    assert np.allclose(buf[2, 1], (1.0, 0.0, 0.0, 1.0)) and np.allclose(buf[0, 3], (0.0, 1.0, 0.0, 1.0))
    assert (buf[..., 3] > 0).sum() == 2
    buf = np.zeros((7, 7, 4))
    vf.paint(buf, [(3.5, 3.5)], [(1.0, 1.0, 1.0, 1.0)], 3.0)
    assert (buf[..., 3] > 0).sum() == 9  # pixel centres within 1.5 of the particle
    buf = np.zeros((4, 4, 4))
    vf.paint(buf, [(-1.0, 1.0), (1.0, 9.0)], [(1.0, 1.0, 1.0, 1.0)] * 2, 1.0)
    assert buf.sum() == 0.0


# ----------------------------------------------------------------------------------------------------- the document


def test_the_example_document_runs_and_seeks():
    doc = vf.example_document()
    out = vf.run(doc, 12)
    assert out["T"] == 2400.0
    assert out["particles"] == 256
    assert out["respawned"] >= 1 and out["respawned"] < 256
    assert 0.0 < out["speed"]["mean"] <= out["speed"]["max"]
    assert out["covered"] > 100
    assert out["warnings"] == []
    assert re.fullmatch(r"[0-9a-f]{12}", out["digest"]) and re.fullmatch(r"[0-9a-f]{12}", out["positions"])
    again = vf.run(doc, 12)
    assert again == out
    trace = vf.trace(doc, 12)
    assert len(trace) == 13 and trace[12] == out["digest"] and trace[5] == vf.run(doc, 5)["digest"]
    assert len(set(trace)) == 13
    end = vf.run(doc, 36)
    assert end["T"] == 7200.0 and end["warnings"] == ["W-VF1"]


def test_frame_zero_and_the_data_time():
    doc = vf.example_document()
    start = vf.run(doc, 0)
    assert start["T"] == 0.0 and start["respawned"] == 0 and start["covered"] <= 256
    assert vf.frame_time(doc["map"]["children"][0], 30.0, doc["project"]["fps"]) == 6000.0
    assert vf.data_time(0.0, 10.0) == 10.0 and vf.data_time("1970-01-01T01:00:00Z", 0.0) == 3600.0


def test_the_example_document_is_valid_and_the_bad_one_lists_every_code():
    assert vf.validate_document(vf.example_document()) == []
    codes = [c for c, _ in vf.validate_document(vf.bad_document())]
    assert codes == ["VF1", "VF2", "VF3", "VF4", "V17"]


def test_validation_one_at_a_time():
    def only(**patch):
        doc = vf.example_document()
        doc["map"]["children"][0].update(patch)
        return [c for c, _ in vf.validate_document(doc)]

    assert only(particles=0) == ["VF2"] and only(particles=2_000_000) == ["VF2"]
    assert only(speedup=0.0) == ["VF2"] and only(fade=1.0) == ["VF2"] and only(dropRate=1.5) == ["VF2"]
    assert only(colors=[(0.0, "#fff"), (0.0, "#000")]) == ["VF2"]
    assert only(grid="nowhere") == ["VF3"]
    assert only(timeOrigin="noon") == ["VF4"]
    assert only(glow=1) == ["V17"]
    doc = vf.example_document()
    doc["assets"]["wind"]["u"] = "TMP:X"
    assert [c for c, _ in vf.validate_document(doc)] == ["VF1"]
    doc = vf.example_document()
    del doc["assets"]["wind"]["cacheSha256"]
    assert [c for c, _ in vf.validate_document(doc)] == ["VF1"]
    doc = vf.example_document()
    doc["assets"]["wind"]["format"] = "csv"
    assert [c for c, _ in vf.validate_document(doc)] == ["VF1"]


def test_constants_and_defaults():
    assert vf.FLOW_DEFAULTS["particles"] == 65536 and vf.FLOW_DEFAULTS["speedup"] == 6000.0
    assert vf.FLOW_DEFAULTS["fade"] == 0.996 and vf.FLOW_DEFAULTS["dropRate"] == 0.003
    assert vf.FLOW_DEFAULTS["dropBump"] == 0.01 and vf.FLOW_DEFAULTS["strokeWidth"] == 1.0
    assert vf.FLOW_DEFAULTS["opacity"] == 1.0 and vf.FLOW_DEFAULTS["seed"] == 0
    assert vf.UVGRID_DEFAULTS == {"format": "auto", "u": "UGRD", "v": "VGRD", "surface": "103:10"}
    assert vf.PURPOSES == {"spawnX": 1, "spawnY": 2, "drop": 3}
    assert vf.R == 6378137.0 and vf.TILE == 256
    assert vf.GRIB_UGRD == (0, 2, 2) and vf.GRIB_VGRD == (0, 2, 3)


# ---------------------------------------------------------------------------------------------------------- the draft


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
    for word in ("SR-115", "SREP 9", "SREP 12", "SREP 14", "`uvGrid`", "`flow`", "webgl-wind", "ISC", "Agafonkin",
                 "GRIB2", "NetCDF", "GFS", "OSCAR", "ecCodes", "Apache-2.0", "netCDF-C", "simple packing",
                 "template 5.0", "sign-magnitude", "`cache`", "`cacheSha256`", "resolve step", "`particles`",
                 "`speedup`", "`fade`", "`dropRate`", "`dropBump`", "`colors`", "`seed`", "`strokeWidth`",
                 "`opacity`", "`timeOrigin`", "`time`", "stream", "purpose", "midpoint", "solid-body",
                 "analytic circle", "bilinear", "cos", "floor(255", "seek check", "VF1", "VF2", "VF3", "VF4",
                 "W-VF1", "W-VF2", "V17", "vector_field_reference.py", "numpy", "public domain", "CDF",
                 "64-bit offset", "`_FillValue`", "`scale_factor`", "CF-1.8", "random-streams"):
        assert word in draft, word


ROW = re.compile(r"\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def _draft_rows():
    if not os.path.exists(DRAFT):
        return [("missing draft", "0", "1")]
    with open(DRAFT, encoding="utf-8") as f:
        rows = [ROW.match(line) for line in f]
    return [(m.group(1), m.group(2), m.group(3)) for m in rows if m and m.group(1) != "Test"]


def test_the_table_has_enough_rows():
    assert len(_draft_rows()) >= 20
    assert len(vf.TABLE) == len(_draft_rows())


def test_the_table_is_what_the_module_prints(draft):
    printed = {(name, expr): literal for name, expr, literal in vf.TABLE}
    assert {(n, e): v for n, e, v in _draft_rows()} == printed


@pytest.mark.parametrize("name,expr,expected", _draft_rows())
def test_the_table_rows_hold(name, expr, expected):
    scope = vf.scope()
    value = eval(expr, scope)
    want = eval(expected, scope)
    assert vf._same(value, want), (name, value, want)
