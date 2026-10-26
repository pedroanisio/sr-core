"""Writes the kit cases of the physical-sky draft and measures an engine's renders of them.

The draft (srep/srep-0000-physical-sky.md, Kit cases) describes eight cases that join conformance/srep_cases/ once
the SREP has a number. `--write DIR` writes them now as srep-0000-sky-*.xml; `--engine BIN` writes them, renders
each with scene-render and measures the frames. A case that compares two settings or views has companion
documents named with a suffix. Radiance is read from linear EXR frames (`scene-render encode`, the document's
exr-sequence output); the seek case compares PNG frames of `scene-render render`. Every expectation comes from
physical_sky_reference.py: the sun and moon of each document's date and observer, the sky's radiance, the aerial
perspective and the fog; the grey of a wall is read from a near box of the same material in the same frame, so
the material's colour encoding never enters an expectation.
"""
import argparse
import importlib.util
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ps = _load("physical_sky_reference")
sk = _load("star_fields_kit")          # the EXR reader and writer, the PNG loader and the frame helpers

NAMES = ["sky-spa", "sky-day", "sky-sunset", "sky-orbit", "sky-aerial", "sky-fog", "sky-moon", "sky-seek"]
DOCUMENTS = {
    "sky-spa": ["sky-spa"],
    "sky-day": ["sky-day", "sky-day-horizon"],
    "sky-sunset": ["sky-sunset", "sky-sunset-noon", "sky-sunset-below"],
    "sky-orbit": ["sky-orbit"],
    "sky-aerial": ["sky-aerial", "sky-aerial-default"],
    "sky-fog": ["sky-fog", "sky-fog-high", "sky-fog-aerial"],
    "sky-moon": ["sky-moon", "sky-moon-new"],
    "sky-seek": ["sky-seek"],
}
W, H = 640, 360
DEFAULT_FOV = 60.0                    # the camera's schema default, kept by the default-camera companion
FOV = {"sky-spa": 20.0, "sky-day": 20.0, "sky-day-horizon": 20.0, "sky-sunset": 10.0, "sky-sunset-noon": 10.0,
       "sky-sunset-below": 10.0, "sky-orbit": 10.0, "sky-aerial": 10.0, "sky-aerial-default": DEFAULT_FOV,
       "sky-fog": 10.0, "sky-fog-high": 10.0, "sky-fog-aerial": 10.0, "sky-moon": 10.0, "sky-moon-new": 10.0,
       "sky-seek": 60.0}

# Observers and dates. The report's example (Golden, Colorado) for the SPA case; the equator and prime meridian
# for the others, at the June solstice noon (the sun 23.4 degrees north of the zenith) and the March equinox noon
# (the sun 1.9 degrees from the zenith); the sunset times are solved from the reference (`sunset_date`).
GOLDEN = {"date": "2003-10-17T12:30:30-07:00", "latitude": 39.742476, "longitude": -105.1786, "altitude": 1830.14,
          "pressure": 820.0, "temperature": 11.0, "deltaT": 67.0}
EQUATOR = {"latitude": 0.0, "longitude": 0.0}
DAY_DATE = "2026-06-21T12:00:00Z"
NOON_DATE = "2026-03-20T12:00:00Z"
SUNSET_DAY = "2026-03-20"
SUNSET_ELEVATION = 1.0                # degrees above the horizon for the sunset disc
BELOW_ELEVATION = -1.0                # the disc wholly below the horizon (its radius is 0.265 degrees)
FULL_MOON = "2003-11-09T01:13:00Z"
NEW_MOON = "2003-10-25T12:50:00Z"
ORBIT_ALTITUDE = 400000.0
DAY_PITCH = 89.0                      # the zenith camera, a degree off the pole so the camera's up stays defined
HORIZON_PITCH = 1.0                   # the horizon camera looks a degree above the horizon, away from the sun
SEEK_FRAMES = 40                      # the frame compared: 20 hours in, 14:00 UTC, the sun 37 degrees from the zenith
SEEK_FPS = 24
SEEK_DURATION = 2.0                   # 48 frames; a day runs across them, one key per frame (strings are discrete)
SEEK_START = (2026, 6, 20, 18)        # 2026-06-20T18:00:00Z; the keys step 30 minutes a frame to 2026-06-21T18:00:00Z
SEEK_STEP_MINUTES = 30

# Geometry of the surface cases, in scene pixels; `physics pixelsPerMeter="1"` makes a pixel a metre.
GREY = "#808080FF"
NEAR = 10.0                           # the near box that gives the material's grey: its air shifts it by 1e-5
NEAR_SIZE = 0.15                      # 55 pixels across at fov 10
AERIAL_DISTANCES = (100.0, 5000.0, 10000.0, 20000.0, 50000.0)
AERIAL_AZIMUTHS = (-4.0, -2.0, 0.0, 2.0, 4.0)       # degrees off the camera axis, so no box hides another
AERIAL_SIZE = 0.015                                 # a box's side as a fraction of its distance: 0.86 degrees
AERIAL_FAR = 60000.0                                # past the farthest box (the camera's default far is 10,000 px)
NEAR_RISE = -0.3                                    # the near box sits 1.7 degrees above the row, hiding no box
BOX_DEPTH = 10.0
DEFAULT_EYE = (W / 2.0, H / 2.0, -(W / 2.0) / math.tan(math.radians(DEFAULT_FOV) / 2.0))   # (320, 180, -554.2563)
DEFAULT_FAR = 600000.0
DEFAULT_WALL_Y = 330.0
DEFAULT_WALL_DISTANCE = 500000.0                    # pixels: 5 km at the default 100 pixels per metre
DEFAULT_WALL_SIZE = (20000.0, 20000.0)             # 22 px across through the 60-degree lens: covers the window
DEFAULT_NEAR = (40.0, 20.0, 100.0)                  # the near box's offset from the default eye, in pixels
DEFAULT_NEAR_SIZE = 10.0
FOG_DISTANCE = 1000.0
FOG_HIGH_Y = -500.0
FOG_WALL_SIZE = 200.0
FOG = {"fogDensity": 0.001, "fogHeight": 100.0}
SUN_SIZE = 0.53                                     # the schema default, the disc's angular diameter

# Tolerances.
SKY_TOL = 0.02                        # per channel, against the reference's radiance
SPA_TOL_DEG = 0.1
MOON_TOL_DEG = 0.2
MOON_DIAMETER_TOL_DEG = 0.02
ORBIT_EDGE_TOL_DEG = 0.2
ORBIT_CUTOFF = 0.01                   # the shell's edge: where the radiance falls to this fraction of its peak
ORBIT_DARK = 1e-4                     # above the top's grazing direction, relative to the shell's peak
DISC_PEAK = 20.0                      # a drawn disc: the window's peak over its median
NO_DISC_PEAK = 3.0                    # no disc: the window's peak within this of its median
BELOW_DISC = 0.01                     # the disc below the horizon: the window's peak over the drawn disc's peak
WINDOW = 2                            # half-width of the window a pixel's radiance is averaged over
DISC_LEVEL = 0.5                      # a disc pixel: luminance above this fraction of the frame's peak
LUMA = sk.LUMA

# ------------------------------------------------------------------------------------ the camera


def zoom(fov):
    return (W / 2.0) / math.tan(math.radians(fov) / 2.0)


def aim(d):
    """Camera yaw and pitch (degrees) that look along the scene direction d (the engine's camera looks along +z
    with y down, yaw turns about y toward +x and positive pitch looks up)."""
    x, y, z = d
    return (math.degrees(math.atan2(x, z)), math.degrees(math.asin(max(-1.0, min(1.0, -y)))))


def project(fov, yaw, pitch, d):
    """Continuous frame coordinates (pixel i covers [i, i + 1)) of the scene direction d."""
    ya, pa = math.radians(yaw), math.radians(pitch)
    x, y, z = d
    x1, z1 = math.cos(ya) * x - math.sin(ya) * z, math.sin(ya) * x + math.cos(ya) * z
    y2, z2 = math.cos(pa) * y + math.sin(pa) * z1, -math.sin(pa) * y + math.cos(pa) * z1
    if z2 <= 0.0:
        return (math.nan, math.nan)
    k = zoom(fov)
    return (W / 2.0 + k * x1 / z2, H / 2.0 + k * y2 / z2)


def unproject(fov, yaw, pitch, at):
    """The unit scene direction through the continuous frame coordinates `at`: the inverse of `project`."""
    k = zoom(fov)
    x, y, z = at[0] - W / 2.0, at[1] - H / 2.0, k
    pa, ya = math.radians(pitch), math.radians(yaw)
    y, z = math.cos(pa) * y - math.sin(pa) * z, math.sin(pa) * y + math.cos(pa) * z
    x, z = math.cos(ya) * x + math.sin(ya) * z, -math.sin(ya) * x + math.cos(ya) * z
    return ps.unit((x, y, z))


def pixels_per_degree(fov):
    return zoom(fov) * math.tan(math.radians(1.0))


def to_atmosphere(d):
    """A scene direction (x east, y down, z north) in the atmosphere's axes (x, z, up): rule 10's mapping."""
    return (d[0], d[2], -d[1])


def to_scene(d):
    return (d[0], -d[2], d[1])


def centre_of(px):
    """The continuous coordinates of the centre of the pixel containing px (the window's middle pixel)."""
    return (math.floor(px[0]) + 0.5, math.floor(px[1]) + 0.5)


# ------------------------------------------------------------------------------------ the sun and moon


def sunset_date(elevation, day=SUNSET_DAY):
    """The whole second of `day` (UTC) at which the sun's apparent elevation at the equator and prime meridian is
    nearest `elevation` degrees, searched between 17:00 and 19:00 by bisection on the reference."""
    def elev(seconds):
        h, m, s = int(seconds // 3600), int(seconds % 3600 // 60), int(seconds % 60)
        return 90.0 - ps.sun_from_document(f"{day}T{h:02d}:{m:02d}:{s:02d}Z", **EQUATOR)["zenith"]
    lo, hi = 17 * 3600, 19 * 3600
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if elev(mid) > elevation:
            lo = mid
        else:
            hi = mid
    best = min((lo, hi), key=lambda t: abs(elev(t) - elevation))
    return f"{day}T{best // 3600:02d}:{best % 3600 // 60:02d}:{best % 60:02d}Z"


def seek_date(frame):
    """The date of the seek case's frame: SEEK_START plus SEEK_STEP_MINUTES a frame, as the key is written."""
    import datetime
    t = datetime.datetime(*SEEK_START, tzinfo=datetime.timezone.utc) + datetime.timedelta(minutes=SEEK_STEP_MINUTES * frame)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def seek_key_time(frame):
    """The time of the seek case's key for a frame: half a frame before it (the first at 0), so the discrete string
    holds through the frame's own time however the engine forms it from the frame number and the rate."""
    return 0.0 if frame == 0 else (frame - 0.5) / SEEK_FPS


def _observer(light):
    """The reference's keyword arguments for a document's observer attributes."""
    out = {"date": light["date"], "latitude": light["latitude"], "longitude": light["longitude"]}
    for key, name in (("altitude", "altitude"), ("pressure", "pressure"), ("temperature", "temperature"),
                      ("deltaT", "delta_t")):
        if key in light:
            out[name] = light[key]
    return out


# ------------------------------------------------------------------------------------ documents


def _attrs(d):
    return "".join(f' {k}="{v}"' for k, v in d.items())


def lights():
    """The dome light attributes of every document, by document key."""
    eq = dict(EQUATOR)
    sunset, below = sunset_date(SUNSET_ELEVATION), sunset_date(BELOW_ELEVATION)
    fog = {"aerialPerspective": "false", **FOG}
    return {
        "sky-spa": {**GOLDEN},
        "sky-day": {"date": DAY_DATE, **eq},
        "sky-day-horizon": {"date": DAY_DATE, **eq},
        "sky-sunset": {"date": sunset, **eq},
        "sky-sunset-noon": {"date": NOON_DATE, **eq},
        "sky-sunset-below": {"date": below, **eq},
        "sky-orbit": {"date": NOON_DATE, **eq, "altitude": ORBIT_ALTITUDE},
        "sky-aerial": {"date": NOON_DATE, **eq, "altitude": 0.0},
        "sky-aerial-default": {"date": NOON_DATE, **eq, "altitude": 0.0},
        "sky-fog": {"date": NOON_DATE, **eq, "altitude": 0.0, **fog},
        "sky-fog-high": {"date": NOON_DATE, **eq, "altitude": 0.0, **fog},
        "sky-fog-aerial": {"date": NOON_DATE, **eq, "altitude": 0.0, "aerialPerspective": "true", **FOG},
        "sky-moon": {"date": FULL_MOON, **eq},
        "sky-moon-new": {"date": NEW_MOON, **eq},
        "sky-seek": {"date": seek_date(0), **eq},
    }


def cameras(light):
    """Each document's camera: (fov, yaw, pitch, position) with the position in scene pixels."""
    a = ps.atmosphere()
    sun = {key: ps.sun_from_document(**_observer(light[key]))["direction"]
           for key in ("sky-spa", "sky-sunset", "sky-sunset-noon", "sky-sunset-below")}
    moon = {key: ps.moon_from_document(**_observer(light[key]))["direction"] for key in ("sky-moon", "sky-moon-new")}
    orbit = (0.0, 0.0, a["planet_radius"] + ORBIT_ALTITUDE)
    gamma = (math.asin(a["planet_radius"] / ps._norm(orbit)) + math.asin(a["top_radius"] / ps._norm(orbit))) / 2.0
    limb_mid = to_scene((math.sin(gamma), 0.0, -math.cos(gamma)))
    origin = (0.0, 0.0, 0.0)
    out = {
        "sky-spa": (FOV["sky-spa"], *aim(sun["sky-spa"]), origin),
        "sky-day": (FOV["sky-day"], 0.0, DAY_PITCH, origin),
        "sky-day-horizon": (FOV["sky-day-horizon"], 180.0, HORIZON_PITCH, origin),
        "sky-sunset": (FOV["sky-sunset"], *aim(sun["sky-sunset"]), origin),
        "sky-sunset-noon": (FOV["sky-sunset-noon"], *aim(sun["sky-sunset-noon"]), origin),
        "sky-sunset-below": (FOV["sky-sunset-below"], *aim(sun["sky-sunset-below"]), origin),
        "sky-orbit": (FOV["sky-orbit"], *aim(limb_mid), origin),
        "sky-aerial": (FOV["sky-aerial"], 0.0, 0.0, origin),
        "sky-aerial-default": (DEFAULT_FOV, 0.0, 0.0, DEFAULT_EYE),
        "sky-fog": (FOV["sky-fog"], 0.0, 0.0, origin),
        "sky-fog-high": (FOV["sky-fog-high"], 0.0, 0.0, (0.0, FOG_HIGH_Y, 0.0)),
        "sky-fog-aerial": (FOV["sky-fog-aerial"], 0.0, 0.0, origin),
        "sky-moon": (FOV["sky-moon"], *aim(moon["sky-moon"]), origin),
        "sky-moon-new": (FOV["sky-moon-new"], *aim(moon["sky-moon-new"]), origin),
        "sky-seek": (FOV["sky-seek"], 0.0, 30.0, origin),
    }
    return out


def _box(key, x, y, z, w, h):
    return (f'<object3D id="{key}" primitive="box" width="{w!r}" height="{h!r}" depth="{BOX_DEPTH!r}" '
            f'x="{x!r}" y="{y!r}" z="{z!r}" material="grey"/>')


def surfaces():
    """The boxes of the surface cases by document key: the measured point of each box's front face (scene pixels)
    with the box's element, the near box first."""
    out = {}
    aerial = [("near", (0.0, NEAR_RISE, NEAR + BOX_DEPTH / 2.0), NEAR_SIZE, NEAR_SIZE)]
    for i, (dist, az) in enumerate(zip(AERIAL_DISTANCES, AERIAL_AZIMUTHS)):
        x = dist * math.tan(math.radians(az))
        aerial.append((f"box{i}", (x, 0.0, dist + BOX_DEPTH / 2.0), AERIAL_SIZE * dist, AERIAL_SIZE * dist))
    out["sky-aerial"] = [(name, (c[0], c[1], c[2] - BOX_DEPTH / 2.0), _box(name, *c, w, h)) for name, c, w, h in aerial]
    ex, ey, ez = DEFAULT_EYE
    near = (ex + DEFAULT_NEAR[0], ey + DEFAULT_NEAR[1], ez + DEFAULT_NEAR[2] + BOX_DEPTH / 2.0)
    wall = (ex, DEFAULT_WALL_Y, ez + DEFAULT_WALL_DISTANCE + BOX_DEPTH / 2.0)
    out["sky-aerial-default"] = [
        ("near", (near[0], near[1], near[2] - BOX_DEPTH / 2.0), _box("near", *near, DEFAULT_NEAR_SIZE, DEFAULT_NEAR_SIZE)),
        ("wall", (ex, ey, wall[2] - BOX_DEPTH / 2.0), _box("wall", *wall, *DEFAULT_WALL_SIZE))]
    for key, y in (("sky-fog", 0.0), ("sky-fog-high", FOG_HIGH_Y), ("sky-fog-aerial", 0.0)):
        near = (0.4, y + NEAR_RISE, NEAR + BOX_DEPTH / 2.0)
        wall = (0.0, y, FOG_DISTANCE + BOX_DEPTH / 2.0)
        out[key] = [("near", (near[0], near[1], near[2] - BOX_DEPTH / 2.0), _box("near", *near, NEAR_SIZE, NEAR_SIZE)),
                    ("wall", (0.0, y, FOG_DISTANCE), _box("wall", *wall, FOG_WALL_SIZE, FOG_WALL_SIZE))]
    return out


def _doc(key, light, camera, objects=(), physics=None, fps=1, duration=1, animate=""):
    fov, yaw, pitch, (x, y, z) = camera
    lens = f' far="{DEFAULT_FAR:g}"' if key == "sky-aerial-default" else f' fov="{fov:g}"'
    if key == "sky-aerial":
        lens += f' far="{AERIAL_FAR:g}"'
    cam = f'<camera id="cam"{lens} x="{x!r}" y="{y!r}" z="{z!r}" yaw="{yaw:.7f}" pitch="{pitch:.7f}"/>'
    materials = f'<materials><material id="grey" baseColor="{GREY}" unlit="true" doubleSided="true"/></materials>\n' if objects else ""
    body = "".join(objects)
    tail = f'<physics pixelsPerMeter="{physics:g}"/>\n' if physics else ""
    attrs = _attrs({k: (repr(v) if isinstance(v, float) else v) for k, v in light.items()})
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="1.8"><project width="{W}" height="{H}" fps="{fps}" duration="{duration:g}" '
            f'background="#000000FF"/>\n'
            f'<output id="exr" path="out/{key}_%04d.exr" codec="exr-sequence"/>\n'
            f'{materials}<composition>{cam}{body}</composition>\n'
            f'<lights><light id="dome" type="dome" sky="physical" environmentVisible="true" moon="false"{attrs}>'
            f'{animate}</light></lights>\n'
            f'{tail}</scene>\n')


def documents():
    """The fifteen documents of the eight cases, by document key."""
    light = lights()
    cam = cameras(light)
    boxes = surfaces()
    docs = {}
    for key in (k for keys in DOCUMENTS.values() for k in keys):
        objects = [element for _, _, element in boxes.get(key, [])]
        physics = 1.0 if key in ("sky-orbit", "sky-aerial", "sky-fog", "sky-fog-high", "sky-fog-aerial") else None
        attrs = dict(light[key])
        if key in ("sky-moon", "sky-moon-new"):
            attrs["moon"] = "true"
        if key == "sky-seek":
            keys = "".join(f'<key time="{seek_key_time(i):.6f}" value="{seek_date(i)}"/>'
                           for i in range(int(SEEK_FPS * SEEK_DURATION) + 1))
            animate = f'<animate property="date">{keys}</animate>'
            docs[key] = _doc(key, attrs, cam[key], fps=SEEK_FPS, duration=SEEK_DURATION, animate=animate)
        else:
            docs[key] = _doc(key, attrs, cam[key], objects, physics)
    for key in ("sky-moon", "sky-moon-new"):
        docs[key] = docs[key].replace(' moon="false"', "", 1)
    return docs


# ------------------------------------------------------------------------------------ expectations


def _sun_atm(light):
    return to_atmosphere(ps.sun_from_document(**_observer(light))["direction"])


def expectations():
    """Every case's expected values from the reference; the surface cases' colours wait for the measured grey."""
    a = ps.atmosphere()
    r = a["planet_radius"]
    light = lights()
    cam = cameras(light)
    ground = (0.0, 0.0, r)
    exp = {}
    sun = ps.sun_from_document(**_observer(light["sky-spa"]))
    exp["sky-spa"] = {"zenith": sun["zenith"], "azimuth": sun["azimuth"], "direction": sun["direction"],
                      "at": project(*cam["sky-spa"][:3], sun["direction"])}
    sun_day = _sun_atm(light["sky-day"])
    zenith_dir = unproject(*cam["sky-day"][:3], centre_of((W / 2.0, H / 2.0)))
    horizon_dir = unproject(*cam["sky-day-horizon"][:3], centre_of((W / 2.0, H / 2.0)))
    exp["sky-day"] = {"zenith": ps.sky_radiance(a, ground, to_atmosphere(zenith_dir), sun_day),
                      "horizon": ps.sky_radiance(a, ground, to_atmosphere(horizon_dir), sun_day),
                      "zenith_direction": zenith_dir, "horizon_direction": horizon_dir}
    discs = {}
    for key in ("sky-sunset", "sky-sunset-noon", "sky-sunset-below"):
        s = ps.sun_from_document(**_observer(light[key]))
        discs[key] = {"elevation": 90.0 - s["zenith"], "at": project(*cam[key][:3], s["direction"]),
                      "disc": ps.sun_disc_radiance(a, ground, to_atmosphere(s["direction"]), SUN_SIZE)
                      if s["zenith"] < 90.0 else (0.0, 0.0, 0.0)}
    exp["sky-sunset"] = discs
    orbit = (0.0, 0.0, r + ORBIT_ALTITUDE)
    sun_orbit = _sun_atm(light["sky-orbit"])
    fov, yaw, pitch, _ = cam["sky-orbit"]
    rows = list(range(0, H, 4)) + [H - 1]
    angles, radiance = [], []
    for row in rows:
        d = unproject(fov, yaw, pitch, (W / 2.0 + 0.5, row + 0.5))
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, d[1])))))        # from the nadir, scene +y
        radiance.append(ps.sky_radiance(a, orbit, to_atmosphere(d), sun_orbit))
    lum = [sum(v * k for v, k in zip(c, LUMA)) for c in radiance]
    peak = max(lum)
    g_ground = math.degrees(math.asin(r / ps._norm(orbit)))
    g_top = math.degrees(math.asin(a["top_radius"] / ps._norm(orbit)))
    exp["sky-orbit"] = {"rows": rows, "angles": angles, "luminance": lum, "peak": peak,
                        "peak_angle": angles[lum.index(peak)], "edge": _edge(angles, lum, peak * ORBIT_CUTOFF),
                        "ground": g_ground, "top": g_top}
    boxes = surfaces()
    exp["sky-aerial"] = {key: _segments(a, cam[key], boxes[key], 1.0 if key == "sky-aerial" else 100.0, light[key])
                         for key in DOCUMENTS["sky-aerial"]}
    exp["sky-fog"] = {key: _segments(a, cam[key], boxes[key], 1.0, light[key]) for key in DOCUMENTS["sky-fog"]}
    moons = {}
    for key in ("sky-moon", "sky-moon-new"):
        m = ps.moon_from_document(**_observer(light[key]))
        moons[key] = {"zenith": m["zenith"], "azimuth": m["azimuth"], "direction": m["direction"],
                      "angular_diameter": m["angular_diameter"], "illuminated": m["illuminated"],
                      "at": project(*cam[key][:3], m["direction"]),
                      "radiance": ps.moon_radiance(a, ground, m)}
    exp["sky-moon"] = moons
    exp["sky-seek"] = {}
    return exp


def _edge(angles, lum, level):
    """The largest angle at which the luminance (sampled at the angles, increasing or decreasing) still reaches
    `level`, by linear interpolation between samples."""
    pairs = sorted(zip(angles, lum))
    edge = None
    for (a0, l0), (a1, l1) in zip(pairs, pairs[1:]):
        if l0 >= level > l1:
            edge = a0 + (a1 - a0) * (l0 - level) / (l0 - l1)
        elif l1 >= level:
            edge = a1
    return edge


def _segments(a, camera, boxes, pixels_per_meter, light):
    """For each box of a surface document: the window pixel of its measured point, the camera's atmosphere
    position, the ray's atmosphere direction and the segment length in metres, with the document's sun, fog and
    horizon radiance."""
    fov, yaw, pitch, eye = camera
    altitude = float(light.get("altitude", 0.0))
    obs = ps.atmosphere_position(a, eye, altitude, pixels_per_meter)
    sun = _sun_atm(light)
    fog = ps.fog(float(light["fogDensity"]), float(light["fogHeight"])) if "fogDensity" in light else None
    aerial = light.get("aerialPerspective", "true") == "true"
    out = {"observer": obs, "sun": sun, "fog": fog, "aerial": aerial, "boxes": {}}
    for name, point, _ in boxes:
        v = tuple(p - e for p, e in zip(point, eye))
        length = math.sqrt(sum(x * x for x in v)) / pixels_per_meter
        d = to_atmosphere(ps.unit(v))
        horizon = ps.horizon_radiance(a, obs, d, sun) if fog is not None else None
        out["boxes"][name] = {"at": project(fov, yaw, pitch, ps.unit(v)), "direction": d, "length": length,
                              "h0": ps.scene_altitude(eye[1], altitude, pixels_per_meter),
                              "h1": ps.scene_altitude(point[1], altitude, pixels_per_meter), "horizon": horizon}
    return out


def seen(a, seg, box, colour):
    """The colour a box of the outgoing `colour` is seen with, by rule 10 and 11 for the segment."""
    if seg["fog"] is None:
        return ps.aerial_perspective(a, seg["observer"], box["direction"], box["length"], colour, seg["sun"])
    if seg["aerial"]:
        return ps.aerial_perspective(a, seg["observer"], box["direction"], box["length"], colour, seg["sun"],
                                     fog=seg["fog"], horizon=box["horizon"])
    return ps.fogged(colour, seg["fog"], box["h0"], box["h1"], box["length"], box["horizon"])


def material_grey(a, seg, near_measured):
    """The material's outgoing grey from the near box's measured colour: `seen` is affine in the colour, so the
    colour is (measured - seen(0)) / (seen(1) - seen(0)) per channel."""
    zero = seen(a, seg, seg["boxes"]["near"], (0.0, 0.0, 0.0))
    one = seen(a, seg, seg["boxes"]["near"], (1.0, 1.0, 1.0))
    return tuple((m - z) / (o - z) for m, z, o in zip(near_measured, zero, one))


# ------------------------------------------------------------------------------------ frames


def window_mean(rgb, at, half=WINDOW):
    x, y = int(math.floor(at[0])), int(math.floor(at[1]))
    return tuple(float(v) for v in rgb[max(0, y - half):y + half + 1, max(0, x - half):x + half + 1].reshape(-1, 3).mean(axis=0))


def _within(rgb, at, radius_px):
    """The luminances within the radius of the frame position `at`."""
    lum = sk.luminance(rgb)
    ys, xs = np.mgrid[0:lum.shape[0], 0:lum.shape[1]]
    return lum[(xs + 0.5 - at[0]) ** 2 + (ys + 0.5 - at[1]) ** 2 <= radius_px ** 2]


def window_peak(rgb, at, radius_px):
    values = _within(rgb, at, radius_px)
    return float(values.max()) if values.size else math.nan


def window_peak_over_median(rgb, at, radius_px):
    """The peak luminance within the radius of `at` over the median luminance there."""
    values = _within(rgb, at, radius_px)
    if values.size == 0:
        return math.inf
    median = float(np.median(values))
    return float(values.max()) / median if median > 0 else math.inf


def disc(rgb, level=DISC_LEVEL):
    """The luminance-weighted centre (continuous coordinates) and the pixel count of the pixels at or above the
    fraction `level` of the frame's peak luminance."""
    lum = sk.luminance(rgb)
    peak = float(lum.max())
    if peak <= 0.0:
        return (math.nan, math.nan), 0
    mask = lum >= level * peak
    ys, xs = np.nonzero(mask)
    w = lum[mask]
    return ((float((xs + 0.5) @ w / w.sum()), float((ys + 0.5) @ w / w.sum())), int(mask.sum()))


def angle_between(d, e):
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(d, e))))))


def _r(v, n=4):
    return tuple(round(float(x), n) for x in v)


def _rel(measured, expected):
    return abs(measured - expected) / abs(expected) if expected else math.inf


def _worst(measured, expected):
    return max(_rel(m, e) for m, e in zip(measured, expected))


# ------------------------------------------------------------------------------------ measurement


def measure(name, frames, exp, cam=None):
    """Measure a rendered case: frames maps each document key (and "seek-alone", "seek-played") to its frame."""
    if name not in NAMES:
        raise ValueError(name)
    cam = cam or cameras(lights())
    a = ps.atmosphere()
    e = exp[name]
    if name == "sky-spa":
        centre, count = disc(frames["sky-spa"])
        fov, yaw, pitch, _ = cam["sky-spa"]
        off = angle_between(unproject(fov, yaw, pitch, centre), e["direction"]) if count else math.inf
        return {"pass": off <= SPA_TOL_DEG, "centre": _r(centre, 2), "off_deg": round(off, 4), "disc_pixels": count,
                "expected_at": _r(e["at"], 2)}
    if name == "sky-day":
        zenith = window_mean(frames["sky-day"], (W / 2.0, H / 2.0))
        horizon = window_mean(frames["sky-day-horizon"], (W / 2.0, H / 2.0))
        ratio = lambda c: c[2] / c[0] if c[0] > 0 else math.inf  # noqa: E731
        lum = lambda c: sum(v * k for v, k in zip(c, LUMA))      # noqa: E731
        worst = _worst(zenith, e["zenith"])
        return {"pass": ratio(zenith) > ratio(horizon) and lum(horizon) > lum(zenith) and worst <= SKY_TOL,
                "zenith": _r(zenith, 6), "expected_zenith": _r(e["zenith"], 6), "worst_rel": round(worst, 4),
                "horizon": _r(horizon, 6), "blue_over_red": (round(ratio(zenith), 3), round(ratio(horizon), 3))}
    if name == "sky-sunset":
        radius = SUN_SIZE * pixels_per_degree(FOV["sky-sunset"])
        peaks = {key: window_peak_over_median(frames[key], e[key]["at"], radius) for key in ("sky-sunset", "sky-sunset-noon")}
        sums = {key: window_mean(frames[key], e[key]["at"], WINDOW) for key in ("sky-sunset", "sky-sunset-noon")}
        ratio = {key: (c[0] / c[2] if c[2] > 0 else math.inf) for key, c in sums.items()}
        drawn = window_peak(frames["sky-sunset"], e["sky-sunset"]["at"], radius)
        below = window_peak(frames["sky-sunset-below"], e["sky-sunset-below"]["at"], radius) / drawn if drawn > 0 else math.inf
        return {"pass": peaks["sky-sunset"] >= DISC_PEAK and peaks["sky-sunset-noon"] >= DISC_PEAK
                and below <= BELOW_DISC and ratio["sky-sunset"] > ratio["sky-sunset-noon"],
                "red_over_blue": (round(ratio["sky-sunset"], 3), round(ratio["sky-sunset-noon"], 3)),
                "peak_over_median": {k: round(v, 1) for k, v in peaks.items()}, "below_over_drawn": round(below, 6),
                "elevations": {k: round(e[k]["elevation"], 3) for k in DOCUMENTS["sky-sunset"]}}
    if name == "sky-orbit":
        rgb = frames["sky-orbit"]
        fov, yaw, pitch, _ = cam["sky-orbit"]
        lum = sk.luminance(rgb)[:, W // 2 - WINDOW:W // 2 + WINDOW + 1].mean(axis=1)
        angles = [math.degrees(math.acos(max(-1.0, min(1.0, unproject(fov, yaw, pitch, (W / 2.0 + 0.5, row + 0.5))[1]))))
                  for row in range(H)]
        peak = float(lum.max())
        peak_angle = angles[int(lum.argmax())]
        edge = _edge(angles, [float(v) for v in lum], peak * ORBIT_CUTOFF)
        above = [float(v) for ang, v in zip(angles, lum) if ang >= e["top"] + ORBIT_EDGE_TOL_DEG]
        dark = (max(above) / peak) if above and peak > 0 else math.inf
        edge_off = abs(edge - e["edge"]) if edge is not None and e["edge"] is not None else math.inf
        peak_off = abs(peak_angle - e["peak_angle"])
        return {"pass": edge_off <= ORBIT_EDGE_TOL_DEG and peak_off <= ORBIT_EDGE_TOL_DEG and dark <= ORBIT_DARK and peak > 0,
                "peak_deg": round(peak_angle, 3), "peak_off_deg": round(peak_off, 3),
                "edge_deg": None if edge is None else round(edge, 3),
                "expected_edge_deg": None if e["edge"] is None else round(e["edge"], 3),
                "edge_off_deg": round(edge_off, 3), "above_top_over_peak": round(dark, 6),
                "ground_deg": round(e["ground"], 3), "top_deg": round(e["top"], 3)}
    if name in ("sky-aerial", "sky-fog"):
        out, ok = {}, True
        for key in DOCUMENTS[name]:
            seg, rgb = e[key], frames[key]
            grey = material_grey(a, seg, window_mean(rgb, seg["boxes"]["near"]["at"]))
            worst, colours, distances = 0.0, {}, []
            for box_name, box in seg["boxes"].items():
                if box_name == "near":
                    continue
                measured = window_mean(rgb, box["at"])
                expected = seen(a, seg, box, grey)
                worst = max(worst, _worst(measured, expected))
                colours[box_name] = {"measured": _r(measured, 5), "expected": _r(expected, 5)}
                if key == "sky-aerial":
                    sky = ps.sky_radiance(a, seg["observer"], (box["direction"][0], box["direction"][1], 0.0), seg["sun"])
                    distances.append(math.dist(measured, sky))
            closer = all(x > y for x, y in zip(distances, distances[1:])) if distances else True
            ok = ok and worst <= SKY_TOL and closer
            out[key] = {"grey": _r(grey, 4), "worst_rel": round(worst, 4), "boxes": colours}
            if distances:
                out[key]["to_horizon_sky"] = _r(distances, 5)
                out[key]["closer_each_step"] = closer
        return {"pass": ok, **out}
    if name == "sky-moon":
        full, new = e["sky-moon"], e["sky-moon-new"]
        centre, count = disc(frames["sky-moon"])
        fov, yaw, pitch, _ = cam["sky-moon"]
        off = angle_between(unproject(fov, yaw, pitch, centre), full["direction"]) if count else math.inf
        diameter = 2.0 * math.sqrt(count / math.pi) / pixels_per_degree(fov)
        diameter_off = abs(diameter - full["angular_diameter"])
        lum = sk.luminance(frames["sky-moon"])
        lit = frames["sky-moon"][lum >= DISC_LEVEL * float(lum.max())] if count else np.zeros((0, 3))
        radiance = tuple(float(v) for v in lit.mean(axis=0)) if count else (math.nan,) * 3
        radius = (new["angular_diameter"] / 2.0 + 0.25) * pixels_per_degree(FOV["sky-moon-new"])
        new_peak = window_peak_over_median(frames["sky-moon-new"], new["at"], radius)
        return {"pass": off <= MOON_TOL_DEG and diameter_off <= MOON_DIAMETER_TOL_DEG and new_peak <= NO_DISC_PEAK,
                "off_deg": round(off, 4), "diameter_deg": round(diameter, 4),
                "expected_diameter_deg": round(full["angular_diameter"], 4), "radiance": _r(radiance, 5),
                "expected_radiance": _r(full["radiance"], 5), "new_moon_peak_over_median": round(new_peak, 2)}
    if name == "sky-seek":
        alone, played = frames["seek-alone"], frames["seek-played"]
        same = sk.identical(alone, played)
        return {"pass": same, "identical": same}
    raise ValueError(name)


# ------------------------------------------------------------------------------------ writing and running


def write(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for key, xml in documents().items():
        path = os.path.join(out_dir, f"srep-0000-{key}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        paths[key] = path
    return paths


def _run(cmd, exec):
    r = exec(cmd, capture_output=True, text=True)
    text = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0:
        err = text.strip().splitlines()
        return err[0] if err else f"exit {r.returncode}", text
    return None, text


def run(engine, out_dir, exec=subprocess.run):
    """Write the cases, render each document with the engine and measure every case; a case with a document the
    engine refuses reports that document's first diagnostic line under "error"."""
    exp = expectations()
    cam = cameras(lights())
    paths = write(out_dir)
    report, frames, errors = {}, {}, {}
    for key, doc in paths.items():
        if key == "sky-seek":
            continue
        err, _ = _run([engine, "encode", doc, "--out-dir", out_dir], exec)
        if err:
            errors[key] = err
            continue
        frames[key] = sk.read_exr(os.path.join(out_dir, "out", f"{key}_0000.exr"))
    alone = os.path.join(out_dir, "sky-seek-alone.png")
    err, _ = _run([engine, "render", paths["sky-seek"], "-f", str(SEEK_FRAMES), "-o", alone], exec)
    if not err:
        pattern = os.path.join(out_dir, "sky-seek-seq-%04d.png")
        err, _ = _run([engine, "render", paths["sky-seek"], "--frames", f"0..={SEEK_FRAMES}", "-o", pattern], exec)
        if not err:
            frames["seek-alone"], frames["seek-played"] = sk._load_png(alone), sk._load_png(pattern % SEEK_FRAMES)
    if err:
        errors["sky-seek"] = err
    for name in NAMES:
        needed = ["seek-alone", "seek-played"] if name == "sky-seek" else DOCUMENTS[name]
        missing = [k for k in needed if k not in frames]
        if missing:
            error = errors.get("sky-seek") if name == "sky-seek" else "; ".join(
                f"{k}: {errors.get(k, 'no frame')}" for k in missing)
            report[name] = {"pass": False, "error": error or "no frame"}
            continue
        report[name] = measure(name, frames, exp, cam)
    return report


def table(report):
    rows = ["| Case | Measured | Pass |", "|---|---|---|"]
    for name, r in report.items():
        values = ", ".join(f"{k} {v}" for k, v in r.items() if k != "pass")
        rows.append(f"| {name} | {values} | {'yes' if r['pass'] else 'no'} |")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--engine", help="the scene-render binary to render with")
    ap.add_argument("--out", default=os.path.join(CONF, "out", "physical-sky-kit"), help="where documents and frames go")
    ap.add_argument("--write", metavar="DIR", help="write the documents to DIR and stop")
    a = ap.parse_args(argv)
    if a.write:
        for p in write(a.write).values():
            print(p)
        return 0
    if not a.engine:
        ap.error("--engine BIN or --write DIR")
    report = run(a.engine, a.out)
    print(table(report))
    return 0 if all(r["pass"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
