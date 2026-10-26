"""Writes the kit cases of the planets draft and measures an engine's renders of them.

The draft (srep/srep-0000-planets.md, Kit cases) describes ten cases that join conformance/srep_cases/ once the
SREP has a number. `--write DIR` writes them now as srep-0000-planet-*.xml with their synthetic textures under
DIR/assets/ (marks at known longitudes, a uniform white night map, a one-texel cloud, the draft's STRIP ring);
`--engine BIN` writes them, renders each with scene-render and measures the frames. A case that compares two
views or settings (Saturn's radii, the phase angles, the Sun's centre, the ring lit beside its shadow and its
two shadows) has companion documents named with a suffix. Radiance is read from linear EXR frames (`scene-render encode`, the document's
exr-sequence output); the seek case compares PNG frames of `scene-render render`. Every expectation comes from
planets_reference.py (and physical_sky_reference.py for the atmosphere shell), none is written here as a number.

The body frame of the reference (x toward the prime meridian, z toward the north pole, km) is the kit's: the
planet sits at the scene's origin, `scene_from_body` and `pixelsPerMeter` place the camera, and the reference's
pinhole `camera` and `project` give every pixel position. The physical-sky kit's `aim`, `project` and `unproject`
describe the engine's camera (yaw about y toward +x, positive pitch up) and the directional light, which travels
along its own +z the same way.
"""
import argparse
import functools
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import physical_sky_kit as pk  # noqa: E402
import physical_sky_reference as ps  # noqa: E402
import planets_reference as pl  # noqa: E402
import star_fields_kit as sk  # noqa: E402

NAMES = ["planet-limb", "planet-terminator", "planet-phase", "planet-texture", "planet-night", "planet-sun",
         "planet-clouds", "planet-rings", "planet-atmosphere", "planet-seek"]
# the documents of each case: the case's own and its companions (suffix: what differs)
DOCUMENTS = {
    "planet-limb": ["planet-limb", "planet-limb-saturn"],
    "planet-terminator": ["planet-terminator"],
    "planet-phase": ["planet-phase", "planet-phase-60", "planet-phase-90", "planet-phase-120"],
    "planet-texture": ["planet-texture"],
    "planet-night": ["planet-night"],
    "planet-sun": ["planet-sun", "planet-sun-centre"],
    "planet-clouds": ["planet-clouds"],
    "planet-rings": ["planet-rings", "planet-rings-lit", "planet-rings-ground"],
    "planet-atmosphere": ["planet-atmosphere"],
    "planet-seek": ["planet-seek"],
}
W, H = 640, 360
DEFAULT_FOV = 60.0                    # horizontal, the camera's schema default: the reference's F
PHASE_FOV = 1.2                       # the disc from 200 radii fills 150 px of radius
CLOUD_FOV = 2.0                       # 0.02 degrees on the ground is 2 px
ATMOSPHERE_FOV = 10.0                 # one column is 1/64 degree, as the physical-sky kit's orbit case
SEGMENTS = 256                        # the schema's most: the mesh's sag is 7.5e-5 of the radius
SECTORS = 36                          # the limb is read over this many sectors of the disc
PPM = {399: 1e-6, 699: 1e-7, 10: 1e-8}  # pixels per metre: the Earth 6.378, Saturn 6.027, the Sun 6.96 scene units
EARTH, SATURN, SUN = pl.RADII[399][0], pl.RADII[699][0], pl.RADII[10][0]
ORIGIN = (0.0, 0.0, 0.0)
UP = (0.0, 0.0, 1.0)                  # the body's pole: the scene's up (-y)
EYE_RADII = 4.0                       # the limb, terminator, texture, night and seek cameras
PHASE_RADII = 200.0
PHASES = (0.0, 60.0, 90.0, 120.0)
SUN45 = pl.SUN45                      # the terminator case's sun, 45 degrees from the line of sight
POLE_SUN = (0.0, 0.0, 1.0)            # the night and cloud cases' sun, over the north pole
ISOPHOTE = 0.1                        # the Lambert weight whose isophote the terminator case reads
CONE_INSET_PX = 3.0                   # the cusps are read on the circle this far inside the limb
LIT = 1e-3                            # a lit pixel: luminance above this fraction of the frame's peak
TEXTURE = (1024, 512)
MARK = 4                              # texels; a mark is centred on a texel corner at its longitude and latitude
MARKS = {"red": (0.0, 0.0), "green": (90.0, 0.0), "blue": (45.0, 45.0)}   # channel: (longitude, latitude)
TEXTURE_EYE_LONGITUDE = 45.0          # the camera over the meridian between the equatorial marks
CLOUD_TEXTURE = (4096, 2048)
CLOUD_LATITUDE = 45.0                 # the one-texel cloud's texel holds this latitude on the prime meridian: the shadow
                                      # (0.23 degrees, 73 px toward the equator) clears the cloud's bilinear fringe
CLOUD_HEIGHT = 0.004
CLOUD_GROUND = "#808080FF"            # the ground under the cloud is grey, the cloud white: the shadow and the cloud stand out
TWILIGHT = 6.0
NIGHT_LATITUDES = tuple(range(-12, 13))   # along the prime meridian, the sun over the pole: elevation = latitude
NIGHT_FULL = -8.0                     # latitudes at or below this are full night (weight 1): the emissive scale
SUN_RADIUS_PX = 1500.0                # the Sun's disc under the orthographic camera
SUN_CENTRE_RHO = 0.8                  # the frame's centre, in radii from the disc's centre: the limb at column 620
SUN_MUS = (0.5, 0.25, 0.1)
SUN_DISTANCE_RADII = 3.0
RING_INNER, RING_OUTER = 1.239, 2.269
RING_EDGE_T = (-60.0, -55.0, -50.0, -45.0, -40.0, -35.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0)  # the ellipse's parameter, degrees
RING_EDGE_SPAN = 0.08                 # the edge is read along the radius from 0.92 to 1.08 of the edge point
RING_LATITUDES = (-20.0, -5.0)        # the noon meridian: shadowed by the ring, and clear (the reference says 1)
RING_EYE_ELEVATION, RING_EYE_RADII, RING_AIM = 45.0, 6.0, -1.6   # above the plane on the shadow's side, aimed along -x
RING_GROUND_ELEVATION, RING_GROUND_RADII = -30.0, 4.0            # below the plane on the noon side
ATMOSPHERE_ALTITUDE_M = 400000.0
ATMOSPHERE_HEIGHT_M = 100000.0
ATMOSPHERE_SUN = pl.unit((1.0, -0.5, 1.0))   # scene direction toward the sun: 48 degrees from the camera's zenith
SEEK_FRAMES = 600
SEEK_FPS = 24
SEEK_RATE = 60.0                      # scene seconds per real second
SEEK_CLOUD_ROTATION = 0.01            # degrees of longitude per scene second: 15 degrees by frame 600
SEEK_DURATION = 26.0                  # 624 frames: frame 600 exists
SEEK_EPOCH = "2451545.0"              # J2000 as a Julian day (timeScale tdb), the approximate elements
WINDOW = 1                            # half-width of the 3 x 3 window a sample is averaged over
# tolerances
LIMB_TOL_PX = 0.5
TERMINATOR_TOL_PX = 1.0
PHASE_TOL = 0.01                      # of the illuminated fraction
DISC_TOL = 0.02                       # the full disc's pixel count against pi r^2
TEXTURE_TOL_PX = 1.0
NIGHT_TOL = 0.02
SUN_TOL = 0.02
CLOUD_TOL_DEG = 0.02
CLOUD_POSITION_TOL_PX = 1.0
RING_EDGE_TOL_PX = 1.0
RING_LIT_FLOOR = 1e-4                 # of the lit companion's profile peak: below it there is no ring to divide by
RING_LIGHT_TOL = 0.02
ATMOSPHERE_TOL_DEG = 0.1
LUMA = sk.LUMA

STRIP = pl.STRIP
QSTRIP = tuple(tuple(round(v * 255) / 255.0 for v in texel) for texel in STRIP)   # the 8-bit PNG's values


# ------------------------------------------------------------------------------------ the camera and the scene


def focal(fov):
    return pk.zoom(fov)


def scale(body):
    """Scene units per km under the body's pixelsPerMeter."""
    return 1000.0 * PPM[body]


def scene(p_km, body):
    return pl.mul(pl.scene_from_body(p_km), scale(body))


def view(eye, target, fov):
    """The reference camera at `eye` looking at `target` (body frame, km) and the engine's yaw and pitch."""
    cam = pl.camera(eye, target, UP, focal(fov))
    yaw, pitch = pk.aim(pl.scene_from_body(pl.unit(pl.sub(target, eye))))
    return cam, yaw, pitch


def at(cam, p):
    """Continuous frame coordinates (pixel i covers [i, i + 1)) of a body-frame point."""
    dx, dy = pl.project(cam, p)
    return (W / 2.0 + dx, H / 2.0 + dy)


def light_aim(sun):
    """The directional light's yaw and pitch: it travels along its +z, away from the sun direction."""
    return pk.aim(pl.scene_from_body(pl.mul(pl.unit(sun), -1.0)))


def elevated(elevation, radii, radius, longitude=0.0):
    """An eye `radii` radii from the centre, `elevation` degrees above the equatorial plane on a meridian."""
    e, lo = math.radians(elevation), math.radians(longitude)
    return pl.mul((math.cos(e) * math.cos(lo), math.cos(e) * math.sin(lo), math.sin(e)), radii * radius)


def cloud_texel():
    """The one-texel cloud's column, row and the longitude and latitude of its centre."""
    u, v = pl.texture_uv(0.0, CLOUD_LATITUDE)
    col, row = int(u * CLOUD_TEXTURE[0]), int(v * CLOUD_TEXTURE[1])
    lon = ((col + 0.5) / CLOUD_TEXTURE[0] - 0.5) * 360.0
    lat = 90.0 - (row + 0.5) / CLOUD_TEXTURE[1] * 180.0
    return col, row, lon, lat


def shadowed_ground(c, sun, radius, height, lon):
    """The ground point on the meridian `lon` whose cloud shadow comes from the shell point `c`: the latitude
    where the reference's `cloud_shadow_point` reaches c, by bisection."""
    lat_c = math.degrees(math.asin(c[2] / pl.norm(c)))

    def miss(lat):
        q = pl.cloud_shadow_point(pl.mul(pl.body_direction(lon, lat), radius), sun, radius, height)
        return math.degrees(math.asin(q[2] / pl.norm(q))) - lat_c

    lo, hi = lat_c - 2.0, lat_c + 2.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if miss(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    return pl.mul(pl.body_direction(lon, (lo + hi) / 2.0), radius)


def ring_edge_point(axes, t):
    """A point of the planet's shadow edge on the ring plane: the half-ellipse on the side away from the sun."""
    along, across = axes
    return (-along * math.cos(math.radians(t)), across * math.sin(math.radians(t)), 0.0)


def to_atmosphere(d):
    """A scene vector in the atmosphere case's axes: the observer on the equator at longitude 0 lies on the
    scene's +x, which is the physical-sky reference's z (through the observer); a rotation."""
    return (d[2], -d[1], d[0])


def geometry():
    """Every document's body, radii, camera and sun (the body frame, km), the source of documents, expectations
    and measurements."""
    g = {}
    for key, body, extra in (("planet-limb", 399, ""), ("planet-limb-saturn", 699, ' radius="1"')):
        a, c = pl.RADII[body]
        eye = (0.0, -EYE_RADII * a, 0.0)
        cam, yaw, pitch = view(eye, ORIGIN, DEFAULT_FOV)
        g[key] = {"body": body, "a": a, "c": c, "f": pl.flattening(body), "eye": eye, "cam": cam, "yaw": yaw,
                  "pitch": pitch, "fov": DEFAULT_FOV, "attrs": f'body="{body}"{extra}', "sun": None}
    eye = (0.0, -EYE_RADII * EARTH, 0.0)
    cam, yaw, pitch = view(eye, ORIGIN, DEFAULT_FOV)
    g["planet-terminator"] = {"body": 399, "a": EARTH, "c": EARTH, "f": 0.0, "eye": eye, "cam": cam, "yaw": yaw,
                              "pitch": pitch, "fov": DEFAULT_FOV, "attrs": f'radius="{EARTH * scale(399)!r}"',
                              "sun": SUN45}
    eye = (0.0, -PHASE_RADII * EARTH, 0.0)
    cam, yaw, pitch = view(eye, ORIGIN, PHASE_FOV)
    for key, phase in zip(DOCUMENTS["planet-phase"], PHASES):
        i = math.radians(phase)
        g[key] = {"body": 399, "a": EARTH, "c": EARTH, "f": 0.0, "eye": eye, "cam": cam, "yaw": yaw, "pitch": pitch,
                  "fov": PHASE_FOV, "attrs": f'radius="{EARTH * scale(399)!r}"', "sun": (math.sin(i), -math.cos(i), 0.0),
                  "phase": phase}
    eye = elevated(0.0, EYE_RADII, EARTH, TEXTURE_EYE_LONGITUDE)
    cam, yaw, pitch = view(eye, ORIGIN, DEFAULT_FOV)
    g["planet-texture"] = {"body": 399, "a": EARTH, "c": pl.RADII[399][1], "f": pl.flattening(399), "eye": eye,
                           "cam": cam, "yaw": yaw, "pitch": pitch, "fov": DEFAULT_FOV, "attrs": 'body="399"', "sun": None}
    eye = elevated(0.0, EYE_RADII, EARTH)
    cam, yaw, pitch = view(eye, ORIGIN, DEFAULT_FOV)
    g["planet-night"] = {"body": 399, "a": EARTH, "c": pl.RADII[399][1], "f": pl.flattening(399), "eye": eye,
                         "cam": cam, "yaw": yaw, "pitch": pitch, "fov": DEFAULT_FOV,
                         "attrs": f'body="399" twilight="{TWILIGHT:g}"', "sun": POLE_SUN}
    for key, rho in (("planet-sun", SUN_CENTRE_RHO), ("planet-sun-centre", 0.0)):
        g[key] = {"body": 10, "a": SUN, "c": SUN, "f": 0.0, "eye": (rho * SUN, -SUN_DISTANCE_RADII * SUN, 0.0),
                  "cam": None, "yaw": 0.0, "pitch": 0.0, "fov": None, "rho": rho,
                  "ortho_height": H * SUN / SUN_RADIUS_PX, "attrs": 'body="10" limbDarkening="solar"', "sun": None}
    col, row, lon, lat = cloud_texel()
    ground = pl.mul(pl.body_direction(lon, lat), EARTH)
    eye = pl.add(ground, pl.mul(pl.body_direction(lon, lat), (EYE_RADII - 1.0) * EARTH))
    cam, yaw, pitch = view(eye, ground, CLOUD_FOV)
    g["planet-clouds"] = {"body": 399, "a": EARTH, "c": EARTH, "f": 0.0, "eye": eye, "cam": cam, "yaw": yaw,
                          "pitch": pitch, "fov": CLOUD_FOV, "sun": POLE_SUN, "texel": (col, row, lon, lat),
                          "ground": ground,
                          "attrs": f'radius="{EARTH * scale(399)!r}" cloudMap="assets/planet-cloud.png" '
                                   f'cloudHeight="{CLOUD_HEIGHT:g}" cloudShadow="true"'}
    ring_attrs = (f'body="699" ringMap="assets/planet-strip.png" ringInner="{RING_INNER:g}" '
                  f'ringOuter="{RING_OUTER:g}"')
    eye = elevated(RING_EYE_ELEVATION, RING_EYE_RADII, SATURN, 180.0)
    cam, yaw, pitch = view(eye, (RING_AIM * SATURN, 0.0, 0.0), DEFAULT_FOV)
    g["planet-rings"] = {"body": 699, "a": SATURN, "c": pl.RADII[699][1], "f": pl.flattening(699), "eye": eye,
                         "cam": cam, "yaw": yaw, "pitch": pitch, "fov": DEFAULT_FOV, "attrs": ring_attrs,
                         "sun": pl.SATURN_SUN}
    # the sun's azimuth turned by 180 degrees puts the planet's shadow on the near half: the same pixels lit
    g["planet-rings-lit"] = dict(g["planet-rings"], sun=(-pl.SATURN_SUN[0], pl.SATURN_SUN[1], pl.SATURN_SUN[2]))
    eye = elevated(RING_GROUND_ELEVATION, RING_GROUND_RADII, SATURN)
    cam, yaw, pitch = view(eye, ORIGIN, DEFAULT_FOV)
    g["planet-rings-ground"] = {"body": 699, "a": SATURN, "c": pl.RADII[699][1], "f": pl.flattening(699),
                                "eye": eye, "cam": cam, "yaw": yaw, "pitch": pitch, "fov": DEFAULT_FOV,
                                "attrs": ring_attrs, "sun": pl.SATURN_SUN}
    band = pl.shell_band(EARTH + ATMOSPHERE_ALTITUDE_M / 1000.0, EARTH, ATMOSPHERE_HEIGHT_M / 1000.0)
    middle = math.radians((band["planet"] + band["shell"]) / 2.0)
    eye = (EARTH + ATMOSPHERE_ALTITUDE_M / 1000.0, 0.0, 0.0)
    look = (-math.cos(middle), math.sin(middle), 0.0)                 # from the nadir toward the body's +y
    cam, yaw, pitch = view(eye, pl.add(eye, pl.mul(look, EARTH)), ATMOSPHERE_FOV)
    sun_body = (ATMOSPHERE_SUN[0], ATMOSPHERE_SUN[2], -ATMOSPHERE_SUN[1])   # scene (x, y, z) = body (x, -z, y)
    g["planet-atmosphere"] = {"body": 399, "a": EARTH, "c": pl.RADII[399][1], "f": pl.flattening(399), "eye": eye,
                              "cam": cam, "yaw": yaw, "pitch": pitch, "fov": ATMOSPHERE_FOV, "band": band,
                              "attrs": f'body="399" atmosphere="earth" atmosphereHeight="{ATMOSPHERE_HEIGHT_M:g}"',
                              "sun": sun_body}
    eye = (0.0, -EYE_RADII * EARTH, 0.0)
    cam, yaw, pitch = view(eye, ORIGIN, DEFAULT_FOV)
    g["planet-seek"] = {"body": 399, "a": EARTH, "c": pl.RADII[399][1], "f": pl.flattening(399), "eye": eye,
                        "cam": cam, "yaw": yaw, "pitch": pitch, "fov": DEFAULT_FOV, "sun": None,
                        "attrs": f'body="399" orientation="bodyFixed" cloudMap="assets/planet-marks.png" '
                                 f'cloudRotation="{SEEK_CLOUD_ROTATION:g}"'}
    return g


# ------------------------------------------------------------------------------------ documents and textures


UNLIT_WHITE = '<material id="m" baseColor="#FFFFFFFF" unlit="true"/>'
LAMBERT = '<material id="m" baseColor="{colour}" metallic="0" roughness="1" specular="0"/>'
NIGHT = ('<material id="m" baseColor="#000000FF" metallic="0" roughness="1" specular="0" emissive="#FFFFFFFF" '
         'emissiveMap="assets/planet-white.png"/>')
PHOTOSPHERE = '<material id="m" baseColor="#000000FF" metallic="0" roughness="1" specular="0" emissive="#FFFFFFFF"/>'
TEXTURED = '<material id="m" baseColor="#FFFFFFFF" unlit="true" baseColorMap="assets/planet-marks.png"/>'
MATERIALS = {
    "planet-limb": UNLIT_WHITE, "planet-limb-saturn": UNLIT_WHITE,
    "planet-terminator": LAMBERT.format(colour="#FFFFFFFF"),
    "planet-texture": TEXTURED, "planet-night": NIGHT, "planet-sun": PHOTOSPHERE, "planet-sun-centre": PHOTOSPHERE,
    "planet-clouds": LAMBERT.format(colour=CLOUD_GROUND),
    "planet-rings": LAMBERT.format(colour="#FFFFFFFF"), "planet-rings-ground": LAMBERT.format(colour="#FFFFFFFF"),
    "planet-rings-lit": LAMBERT.format(colour="#000000FF"),     # a black planet: the ring over its disc blends with nothing
    "planet-atmosphere": '<material id="m" baseColor="#000000FF" unlit="true"/>', "planet-seek": TEXTURED,
}
for _key in DOCUMENTS["planet-phase"]:
    MATERIALS[_key] = LAMBERT.format(colour="#FFFFFFFF")


def _camera(g):
    x, y, z = (round(v, 12) or 0.0 for v in scene(g["eye"], g["body"]))   # 1e-12 scene units; -0.0 is written 0.0
    if g["cam"] is None:                                      # the Sun: orthographic, looking along +z
        return (f'<camera id="cam" projection="orthographic" orthoHeight="{round(g["ortho_height"] * scale(g["body"]), 12)!r}" '
                f'x="{x!r}" y="{y!r}" z="{z!r}"/>')
    return (f'<camera id="cam" fov="{g["fov"]:g}" x="{x!r}" y="{y!r}" z="{z!r}" yaw="{g["yaw"]:.7f}" '
            f'pitch="{g["pitch"]:.7f}"/>')


def _doc(key, g, fps=1, duration=1.0, space=""):
    lights = ""
    if g["sun"] is not None:
        yaw, pitch = light_aim(g["sun"])
        lights = f'<lights><light id="sun" type="directional" intensity="1" yaw="{yaw:.7f}" pitch="{pitch:.7f}"/></lights>\n'
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="1.8"><project width="{W}" height="{H}" fps="{fps}" duration="{duration:g}" '
            f'background="#000000FF"/>\n'
            f'<output id="exr" path="out/{key}_%04d.exr" codec="exr-sequence"/>\n'
            f'<materials>{MATERIALS[key]}</materials>\n'
            f'<composition>{_camera(g)}'
            f'<object3D id="planet" primitive="planet" {g["attrs"]} material="m" segments="{SEGMENTS}"/></composition>\n'
            f'{lights}'
            f'<physics pixelsPerMeter="{PPM[g["body"]]!r}"/>\n'
            f'{space}</scene>\n')


def documents():
    """The seventeen documents of the ten cases, by document key."""
    g = geometry()
    docs = {}
    for key in (k for keys in DOCUMENTS.values() for k in keys):
        if key == "planet-seek":
            space = (f'<space epoch="{SEEK_EPOCH}" timeScale="tdb" origin="10" rate="{SEEK_RATE:g}"/>\n')
            docs[key] = _doc(key, g[key], fps=SEEK_FPS, duration=SEEK_DURATION, space=space)
        else:
            docs[key] = _doc(key, g[key])
    return docs


def textures():
    """The synthetic textures, by file name: (h, w, 4) uint8 arrays."""
    marks = np.zeros((TEXTURE[1], TEXTURE[0], 4), dtype=np.uint8)
    for channel, (lon, lat) in MARKS.items():
        u, v = pl.texture_uv(lon, lat)
        col, row = round(u * TEXTURE[0]), round(v * TEXTURE[1])
        block = marks[row - MARK // 2:row + MARK // 2, col - MARK // 2:col + MARK // 2]
        block[..., "rgb".index(channel[0])] = 255
        block[..., 3] = 255
    white = np.full((4, 8, 4), 255, dtype=np.uint8)
    cloud = np.zeros((CLOUD_TEXTURE[1], CLOUD_TEXTURE[0], 4), dtype=np.uint8)
    col, row, _, _ = cloud_texel()
    cloud[row, col] = 255
    strip = np.array([[[round(v * 255) for v in texel] for texel in STRIP]], dtype=np.uint8)
    return {"planet-marks.png": marks, "planet-white.png": white, "planet-cloud.png": cloud, "planet-strip.png": strip}


def write(out_dir):
    """Write the documents and their textures under out_dir; returns the documents' paths by key."""
    assets = os.path.join(out_dir, "assets")
    os.makedirs(assets, exist_ok=True)
    for name, pixels in textures().items():
        Image.fromarray(pixels, "RGBA").save(os.path.join(assets, name))
    paths = {}
    for key, text in documents().items():
        path = os.path.join(out_dir, f"srep-0000-{key}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        paths[key] = path
    return paths


# ------------------------------------------------------------------------------------ expectations


def _ellipse_sectors(w, h, n=SECTORS, sub=100):
    """The root-mean-square radius of the ellipse with half-extents w (along x) and h (along y) over each of n
    sectors of 360 / n degrees, the k-th centred on (k + 1/2) 360 / n (see `sector_radii`)."""
    out = []
    for k in range(n):
        total = 0.0
        for j in range(sub):
            t = math.radians((k + 0.5) * 360.0 / n + (j + 0.5 - sub / 2.0) * 360.0 / n / sub)
            total += (w * h) ** 2 / ((h * math.cos(t)) ** 2 + (w * math.sin(t)) ** 2)
        out.append(math.sqrt(total / sub))
    return out


@functools.lru_cache(maxsize=None)
def _atmosphere_expectation():
    """The shell's luminance along the frame's middle row, every other column: slow, so computed once."""
    c = geometry()["planet-atmosphere"]
    a_m = c["a"] * 1000.0
    atm = ps.atmosphere(planet_radius=a_m, top_radius=a_m + ATMOSPHERE_HEIGHT_M)
    obs = (0.0, 0.0, a_m + ATMOSPHERE_ALTITUDE_M)
    sun = to_atmosphere(ATMOSPHERE_SUN)
    cols = list(range(0, W, 2)) + [W - 1]
    angles, lum = [], []
    for col in cols:
        d = pk.unproject(c["fov"], c["yaw"], c["pitch"], (col + 0.5, H / 2.0 + 0.5))
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, -d[0])))))       # from the nadir, scene -x
        da = to_atmosphere(d)
        t = _ray_distance(obs, da, a_m)
        radiance = (ps.sky_radiance(atm, obs, da, sun) if t is None
                    else ps.aerial_perspective(atm, obs, da, t, (0.0, 0.0, 0.0), sun))
        lum.append(sum(v * k for v, k in zip(radiance, LUMA)))
    peak = max(lum)
    jumps = [b - a for a, b in zip(lum, lum[1:])]
    limb_col = jumps.index(max(jumps)) + 1
    return {"columns": cols, "angles": angles, "luminance": lum, "peak": peak, "peak_angle": angles[lum.index(peak)],
            "edge": pk._edge(angles, lum, peak * pk.ORBIT_CUTOFF),
            "limb_angle": (angles[limb_col] + angles[limb_col - 1]) / 2.0,
            "ground": c["band"]["planet"], "top": c["band"]["shell"]}


def _ray_distance(origin, direction, radius):
    """The distance along a unit ray to a sphere about the origin, or None when the ray misses it."""
    b = 2.0 * pl.dot(origin, direction)
    disc = b * b - 4.0 * (pl.dot(origin, origin) - radius * radius)
    if disc < 0.0:
        return None
    t = (-b - math.sqrt(disc)) / 2.0
    return t if t > 0.0 else None


def expectations():
    """Every case's expected values from the reference."""
    g = geometry()
    exp = {}
    limb = {}
    for key in DOCUMENTS["planet-limb"]:
        c = g[key]
        w, h = pl.limb_pixel_extents(c["cam"], c["eye"], c["a"], c["c"])
        limb[key] = {"half_extents": (w, h), "sectors": _ellipse_sectors(w, h)}
    exp["planet-limb"] = limb
    c = g["planet-terminator"]
    s = pl.unit(c["sun"])
    r = pl.limb_pixel_radius(c["cam"], c["eye"], c["a"])
    subsolar = pl.mul(s, c["a"])
    points = []
    for p in pl.isophote_points(s, c["a"], 72, ISOPHOTE):
        if not pl.visible(c["eye"], p, c["a"]):
            continue
        x, y = pl.project(c["cam"], p)
        if pl.disc_mu(c["cam"], c["eye"], c["a"], x, y) < 0.3:
            continue
        towards = pl.unit(pl.sub(pl.project(c["cam"], subsolar) + (0.0,), (x, y, 0.0)))
        points.append({"at": (W / 2.0 + x, H / 2.0 + y), "towards": towards[:2], "point": p})
    cone = math.degrees(math.atan((r - CONE_INSET_PX) / c["cam"]["focal"]))
    cusps = pl.cusps(c["eye"], s, c["a"], ISOPHOTE, cone)
    exp["planet-terminator"] = {"subsolar_at": at(c["cam"], subsolar), "radius_px": r, "points": points,
                                "cone_radius_px": r - CONE_INSET_PX, "cusps_at": [at(c["cam"], q) for q in cusps],
                                "level": ISOPHOTE}
    phase = {}
    for key in DOCUMENTS["planet-phase"]:
        c = g[key]
        phase[key] = {"phase": c["phase"], "fraction": pl.illuminated_fraction(c["phase"]),
                      "sampled": pl.lit_fraction(c["eye"], c["sun"], c["a"], 200),
                      "radius_px": pl.limb_pixel_radius(c["cam"], c["eye"], c["a"])}
    exp["planet-phase"] = phase
    c = g["planet-texture"]
    exp["planet-texture"] = {channel: at(c["cam"], pl.surface_point(c["a"], c["f"], lon, lat))
                             for channel, (lon, lat) in MARKS.items()}
    c = g["planet-night"]
    rows = []
    for lat in NIGHT_LATITUDES:
        p = pl.surface_point(c["a"], c["f"], 0.0, float(lat))
        rows.append({"latitude": float(lat), "at": at(c["cam"], p),
                     "weight": pl.night_weight(pl.surface_normal(c["a"], c["f"], p), c["sun"], TWILIGHT)})
    exp["planet-night"] = {"rows": rows}
    exp["planet-sun"] = {"mus": [{"mu": mu, "column": W / 2.0 + (math.sqrt(1.0 - mu * mu) - SUN_CENTRE_RHO) * SUN_RADIUS_PX,
                                  "factor": pl.solar_disc(mu)} for mu in SUN_MUS],
                         "centre_at": (W / 2.0, H / 2.0), "limb_column": W / 2.0 + (1.0 - SUN_CENTRE_RHO) * SUN_RADIUS_PX}
    c = g["planet-clouds"]
    col, row, lon, lat = c["texel"]
    shell = pl.mul(pl.body_direction(lon, lat), c["a"] * (1.0 + CLOUD_HEIGHT))
    shadow = shadowed_ground(shell, c["sun"], c["a"], CLOUD_HEIGHT, lon)
    exp["planet-clouds"] = {"cloud_at": at(c["cam"], shell), "shadow_at": at(c["cam"], shadow),
                            "shift_deg": math.degrees(pl.angle(shadow, c["ground"])), "ground": c["ground"],
                            "shell": shell, "shadow": shadow}
    c = g["planet-rings"]
    axes = pl.planet_shadow_on_rings(c["sun"], c["a"], c["f"])
    edge = []
    for t in RING_EDGE_T:
        q = ring_edge_point(axes, t)
        rho = math.hypot(q[0], q[1])
        edge.append({"t": t, "point": q, "at": at(c["cam"], q),
                     "inside_at": at(c["cam"], pl.mul(q, 1.0 - RING_EDGE_SPAN)),
                     "outside_at": at(c["cam"], pl.mul(q, 1.0 + RING_EDGE_SPAN)),
                     "alpha": pl.ring_sample(QSTRIP, rho, RING_INNER * c["a"], RING_OUTER * c["a"])[3]})
    gr = g["planet-rings-ground"]
    ground = {}
    for lat in RING_LATITUDES:
        p = pl.surface_point(gr["a"], gr["f"], 0.0, lat)
        ground[lat] = {"at": at(gr["cam"], p),
                       "light": pl.ring_shadow(p, gr["sun"], QSTRIP, RING_INNER * gr["a"], RING_OUTER * gr["a"]),
                       "weight": pl.day_weight(pl.surface_normal(gr["a"], gr["f"], p), pl.unit(gr["sun"]))}
    shadowed, clear = (ground[lat] for lat in RING_LATITUDES)
    exp["planet-rings"] = {"axes": axes, "edge": edge, "ground": ground,
                           "ratio": shadowed["light"] * shadowed["weight"] / (clear["light"] * clear["weight"])}
    exp["planet-atmosphere"] = dict(_atmosphere_expectation())
    exp["planet-seek"] = {}
    return exp


# ------------------------------------------------------------------------------------ frames


def sample(lum, x, y):
    """Bilinear luminance at continuous frame coordinates (pixel centres at i + 0.5)."""
    h, w = lum.shape
    fx, fy = x - 0.5, y - 0.5
    x0, y0 = int(math.floor(fx)), int(math.floor(fy))
    tx, ty = fx - x0, fy - y0
    x0, x1 = max(0, min(w - 1, x0)), max(0, min(w - 1, x0 + 1))
    y0, y1 = max(0, min(h - 1, y0)), max(0, min(h - 1, y0 + 1))
    return float((1 - tx) * (1 - ty) * lum[y0, x0] + tx * (1 - ty) * lum[y0, x1]
                 + (1 - tx) * ty * lum[y1, x0] + tx * ty * lum[y1, x1])


def crossings(values, level):
    """The fractional sample indices where a sampled profile crosses `level`, by linear interpolation."""
    out = []
    for i, (a, b) in enumerate(zip(values, values[1:])):
        if (a < level <= b) or (b < level <= a):
            out.append(i + (level - a) / (b - a))
    return out


def window_mean(rgb, pos, half=WINDOW):
    return pk.window_mean(rgb, pos, half)


def bilinear_mean(rgb, pos, half_x=WINDOW, half_y=WINDOW):
    """The mean colour of bilinear samples on a lattice of unit steps about the continuous position `pos`:
    exact on a linear ramp wherever `pos` falls, where a window of whole pixels reads up to half a pixel off."""
    out = []
    for channel in range(3):
        plane = rgb[..., channel]
        values = [sample(plane, pos[0] + dx, pos[1] + dy)
                  for dx in range(-half_x, half_x + 1) for dy in range(-half_y, half_y + 1)]
        out.append(sum(values) / len(values))
    return tuple(out)


def _luminance_of(rgb):
    return sum(v * k for v, k in zip(rgb, LUMA))


def centroid(weights):
    """The weighted centre of a (h, w) array of non-negative weights, in continuous frame coordinates."""
    total = float(weights.sum())
    if total <= 0.0:
        return (math.nan, math.nan)
    ys, xs = np.mgrid[0:weights.shape[0], 0:weights.shape[1]]
    return (float(((xs + 0.5) * weights).sum() / total), float(((ys + 0.5) * weights).sum() / total))


def sector_radii(mask, centre=(W / 2.0, H / 2.0), n=SECTORS):
    """The radius of a disc-like pixel mask over n sectors about `centre`: the root of twice each sector's
    pixel count over its angle, so a sector's count matches the ellipse it is compared with. The sectors are
    bounded by the multiples of 360 / n degrees, lines that hold no pixel centre of a frame whose centre is a
    pixel corner (the diagonals would, and a sector centred on a multiple of 10 degrees has them as edges)."""
    ys, xs = np.nonzero(mask)
    dx, dy = xs + 0.5 - centre[0], ys + 0.5 - centre[1]
    angles = np.degrees(np.arctan2(dy, dx))
    step = 360.0 / n
    out = []
    for k in range(n):
        off = (angles - (k + 0.5) * step + 180.0) % 360.0 - 180.0
        count = int(((off >= -step / 2.0) & (off < step / 2.0)).sum())   # half-open: a boundary pixel counts once
        out.append(math.sqrt(2.0 * count / math.radians(step)))
    return out


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _line_profile(lum, start, end, step=0.25):
    length = _dist(start, end)
    n = max(2, int(length / step))
    pts = [(start[0] + (end[0] - start[0]) * k / n, start[1] + (end[1] - start[1]) * k / n) for k in range(n + 1)]
    return [sample(lum, x, y) for x, y in pts], length / n


def measure(name, frames, exp):
    """Measure a rendered case: frames maps each document key (and "seek-alone", "seek-played") to its frame."""
    if name not in NAMES:
        raise ValueError(name)
    e = exp[name]
    if name == "planet-limb":
        out, ok = {}, True
        for key in DOCUMENTS[name]:
            lum = sk.luminance(frames[key])
            mask = lum > 0.5 * float(lum.max())
            radii = sector_radii(mask)
            offs = [abs(m - x) for m, x in zip(radii, e[key]["sectors"])]
            ys, xs = np.nonzero(mask)
            moments = (2.0 * math.sqrt(float(((xs + 0.5 - W / 2.0) ** 2).mean())),
                       2.0 * math.sqrt(float(((ys + 0.5 - H / 2.0) ** 2).mean()))) if xs.size else (math.nan, math.nan)
            worst = max(offs) if mask.any() else math.inf
            ok = ok and worst <= LIMB_TOL_PX
            out[key] = {"worst_off_px": round(worst, 3), "half_extents_px": _r(moments, 2),
                        "expected_half_extents_px": _r(e[key]["half_extents"], 2), "pixels": int(mask.sum())}
        return {"pass": ok, **out}
    if name == "planet-terminator":
        lum = sk.luminance(frames["planet-terminator"])
        peak = _luminance_of(window_mean(frames["planet-terminator"], e["subsolar_at"]))
        level = e["level"] * peak
        offs = []
        for pt in e["points"]:
            x, y = pt["at"]
            ux, uy = pt["towards"]
            span = 4.0
            values = [sample(lum, x + ux * s, y + uy * s) for s in np.arange(-span, span + 0.05, 0.1)]
            found = crossings(values, level)
            offs.append(min(abs(i * 0.1 - span) for i in found) if found else math.inf)
        cx, cy = W / 2.0, H / 2.0
        rc = e["cone_radius_px"]
        thetas = np.arange(0.0, 360.0, 0.1)
        ring = [sample(lum, cx + rc * math.cos(math.radians(t)), cy + rc * math.sin(math.radians(t))) for t in thetas]
        found = crossings(ring + ring[:1], level)
        found_at = [(cx + rc * math.cos(math.radians(i * 0.1)), cy + rc * math.sin(math.radians(i * 0.1))) for i in found]
        cusp_offs = [min((_dist(q, c) for c in found_at), default=math.inf) for q in e["cusps_at"]]
        worst, worst_cusp = (max(offs) if offs else math.inf), (max(cusp_offs) if cusp_offs else math.inf)
        return {"pass": peak > 0.0 and worst <= TERMINATOR_TOL_PX and worst_cusp <= TERMINATOR_TOL_PX
                and len(found) == 2,
                "points": len(offs), "worst_off_px": round(worst, 3), "cusps_off_px": _r(cusp_offs, 3),
                "crossings_on_cone": len(found), "peak": round(peak, 6)}
    if name == "planet-phase":
        counts = {}
        for key in DOCUMENTS[name]:
            lum = sk.luminance(frames[key])
            counts[key] = int((lum > LIT * float(lum.max())).sum()) if float(lum.max()) > 0.0 else 0
        disc = counts["planet-phase"]
        expected_disc = math.pi * e["planet-phase"]["radius_px"] ** 2
        disc_off = abs(disc - expected_disc) / expected_disc
        out, ok = {}, disc_off <= DISC_TOL and disc > 0
        for key in DOCUMENTS[name]:
            fraction = counts[key] / disc if disc else math.nan
            off = abs(fraction - e[key]["sampled"]) / e[key]["sampled"]   # what a camera at 200 radii sees
            ok = ok and off <= PHASE_TOL
            out[key] = {"phase": e[key]["phase"], "fraction": round(fraction, 4),
                        "expected": round(e[key]["sampled"], 4), "rule": round(e[key]["fraction"], 4),
                        "rel_off": round(off, 4)}
        return {"pass": ok, "disc_pixels": disc, "disc_rel_off": round(disc_off, 4), **out}
    if name == "planet-texture":
        rgb = frames["planet-texture"]
        out, ok = {}, True
        for channel, expected in e.items():
            chan = rgb[..., "rgb".index(channel[0])]
            peak = float(chan.max())
            weights = np.where(chan >= 0.5 * peak, chan, 0.0) if peak > 0.0 else np.zeros_like(chan)
            c = centroid(weights)
            off = _dist(c, expected) if peak > 0.0 else math.inf
            ok = ok and off <= TEXTURE_TOL_PX
            out[channel] = {"at": _r(c, 2), "expected_at": _r(expected, 2), "off_px": round(off, 3)}
        return {"pass": ok, **out}
    if name == "planet-night":
        rgb = frames["planet-night"]
        lums = [_luminance_of(bilinear_mean(rgb, row["at"])) for row in e["rows"]]
        full = [v for v, row in zip(lums, e["rows"]) if row["latitude"] <= NIGHT_FULL]
        scale_ = sum(full) / len(full) if full else 0.0
        if scale_ <= 0.0:
            return {"pass": False, "error": "no night light"}
        offs = [abs(v / scale_ - row["weight"]) for v, row in zip(lums, e["rows"])]
        worst = max(offs)
        return {"pass": worst <= NIGHT_TOL, "worst_off": round(worst, 4), "full_night": round(scale_, 6),
                "weights": [round(v / scale_, 3) for v in lums]}
    if name == "planet-sun":
        centre = window_mean(frames["planet-sun-centre"], e["centre_at"], 2)
        if min(centre) <= 0.0:
            return {"pass": False, "error": "a dark centre"}
        rgb = frames["planet-sun"]
        out, worst = {}, 0.0
        for row in e["mus"]:
            v = bilinear_mean(rgb, (row["column"], H / 2.0), 0, 2)
            ratio = tuple(a / b for a, b in zip(v, centre))
            off = max(abs(r - f) / f for r, f in zip(ratio, row["factor"]))
            worst = max(worst, off)
            out[f"mu_{row['mu']:g}"] = {"ratio": _r(ratio, 4), "expected": _r(row["factor"], 4), "worst_rel": round(off, 4)}
        return {"pass": worst <= SUN_TOL, "worst_rel": round(worst, 4), "centre": _r(centre, 5), **out}
    if name == "planet-clouds":
        rgb = frames["planet-clouds"]
        lum = sk.luminance(rgb)
        plateau = float(np.median(lum))
        if plateau <= 0.0:
            return {"pass": False, "error": "a dark ground"}
        dark = np.where(lum < 0.5 * plateau, plateau - lum, 0.0)
        bright = np.where(lum > 1.5 * plateau, lum - plateau, 0.0)
        shadow_at, cloud_at = centroid(dark), centroid(bright)
        g = geometry()["planet-clouds"]
        p = (pl.pixel_surface_point(g["cam"], g["eye"], g["a"], shadow_at[0] - W / 2.0, shadow_at[1] - H / 2.0)
             if not math.isnan(shadow_at[0]) else None)
        shift = math.degrees(pl.angle(p, e["ground"])) if p is not None else math.inf
        toward_equator = p is not None and p[2] < e["ground"][2]
        shift_off = abs(shift - e["shift_deg"])
        cloud_off = _dist(cloud_at, e["cloud_at"]) if not math.isnan(cloud_at[0]) else math.inf
        shadow_off = _dist(shadow_at, e["shadow_at"]) if not math.isnan(shadow_at[0]) else math.inf
        return {"pass": shift_off <= CLOUD_TOL_DEG and toward_equator and cloud_off <= CLOUD_POSITION_TOL_PX
                and shadow_off <= CLOUD_POSITION_TOL_PX,
                "shift_deg": round(shift, 4), "expected_shift_deg": round(e["shift_deg"], 4),
                "toward_equator": toward_equator, "shadow_at": _r(shadow_at, 2),
                "expected_shadow_at": _r(e["shadow_at"], 2), "cloud_off_px": round(cloud_off, 3),
                "shadow_off_px": round(shadow_off, 3),
                "shadow_pixels": int((dark > 0).sum()), "cloud_pixels": int((bright > 0).sum())}
    if name == "planet-rings":
        lum, lit = sk.luminance(frames["planet-rings"]), sk.luminance(frames["planet-rings-lit"])
        offs, tails = [], []
        for edge in e["edge"]:
            values, step = _line_profile(lum, edge["inside_at"], edge["outside_at"])
            lit_values, _ = _line_profile(lit, edge["inside_at"], edge["outside_at"])
            floor = RING_LIT_FLOOR * max(lit_values)
            # shadowed over lit: the strip's own radial ramp cancels, so the edge is where the ratio crosses one half
            ratio = [v / w if w > floor else 0.0 for v, w in zip(values, lit_values)]
            found = crossings(ratio, 0.5)
            expected = _dist(edge["inside_at"], edge["at"])
            offs.append(min((i * step - expected for i in found), key=abs) if found else math.inf)   # outward positive
            tails.extend(ratio[-len(ratio) // 4:])
        ground = frames["planet-rings-ground"]
        # read at the projected points: the shadow ramps across the rows, which a window of whole pixels misreads
        shadowed, clear = (_luminance_of(bilinear_mean(ground, e["ground"][lat]["at"])) for lat in RING_LATITUDES)
        ratio = shadowed / clear if clear > 0.0 else math.inf
        ratio_off = abs(ratio - e["ratio"]) / e["ratio"]
        worst = max(abs(v) for v in offs)
        mean = sum(offs) / len(offs) if worst < math.inf else math.inf   # a binary edge reads +-0.9 px per point
        return {"pass": worst <= RING_EDGE_TOL_PX and ratio_off <= RING_LIGHT_TOL, "edge_points": len(offs),
                "mean_edge_off_px": round(mean, 3), "lit_ratio_outside": (round(min(tails), 4), round(max(tails), 4)),
                "worst_edge_off_px": round(worst, 3), "light_ratio": round(ratio, 4),
                "expected_light_ratio": round(e["ratio"], 4), "light_rel_off": round(ratio_off, 4)}
    if name == "planet-atmosphere":
        rgb = frames["planet-atmosphere"]
        g = geometry()["planet-atmosphere"]
        lum = sk.luminance(rgb)[H // 2 - WINDOW:H // 2 + WINDOW + 1, :].mean(axis=0)
        angles = [math.degrees(math.acos(max(-1.0, min(1.0, -pk.unproject(g["fov"], g["yaw"], g["pitch"], (col + 0.5, H / 2.0 + 0.5))[0]))))
                  for col in range(W)]
        values = [float(v) for v in lum]
        peak = max(values)
        peak_angle = angles[values.index(peak)]
        edge = pk._edge(angles, values, peak * pk.ORBIT_CUTOFF)
        jumps = [b - a for a, b in zip(values, values[1:])]
        limb_col = jumps.index(max(jumps)) + 1
        limb_angle = (angles[limb_col] + angles[limb_col - 1]) / 2.0
        above = [v for ang, v in zip(angles, values) if ang >= e["top"] + ATMOSPHERE_TOL_DEG]
        dark = (max(above) / peak) if above and peak > 0 else math.inf
        peak_off = abs(peak_angle - e["peak_angle"])
        edge_off = abs(edge - e["edge"]) if edge is not None and e["edge"] is not None else math.inf
        limb_off = abs(limb_angle - e["ground"])
        return {"pass": peak > 0 and peak_off <= ATMOSPHERE_TOL_DEG and edge_off <= ATMOSPHERE_TOL_DEG
                and limb_off <= ATMOSPHERE_TOL_DEG and dark <= pk.ORBIT_DARK,
                "limb_deg": round(limb_angle, 3), "limb_off_deg": round(limb_off, 3),
                "peak_deg": round(peak_angle, 3), "peak_off_deg": round(peak_off, 3),
                "edge_deg": None if edge is None else round(edge, 3),
                "expected_edge_deg": None if e["edge"] is None else round(e["edge"], 3),
                "edge_off_deg": round(edge_off, 3), "above_top_over_peak": round(dark, 6),
                "ground_deg": round(e["ground"], 3), "top_deg": round(e["top"], 3)}
    if name == "planet-seek":
        same = sk.identical(frames["seek-alone"], frames["seek-played"])
        return {"pass": same, "identical": same}
    raise ValueError(name)


def _r(v, n=4):
    return tuple(round(float(x), n) for x in v)


# ------------------------------------------------------------------------------------ running


def _run(cmd, exec):
    r = exec(cmd, capture_output=True, text=True)
    text = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0:
        err = text.strip().splitlines()
        return err[0] if err else f"exit {r.returncode}", text
    return None, text


def run(engine, out_dir, exec=subprocess.run, only=None):
    """Write the cases, render each document with the engine and measure every case (or the cases in `only`);
    a case with a document the engine refuses reports that document's first diagnostic line under "error"."""
    names = [n for n in NAMES if only is None or n in only]
    exp = expectations()
    paths = write(out_dir)
    report, frames, errors = {}, {}, {}
    wanted = {k for n in names for k in DOCUMENTS[n]}
    for key, doc in paths.items():
        if key == "planet-seek" or key not in wanted:
            continue
        err, _ = _run([engine, "encode", doc, "--out-dir", out_dir], exec)
        if err:
            errors[key] = err
            continue
        frames[key] = sk.read_exr(os.path.join(out_dir, "out", f"{key}_0000.exr"))
    if "planet-seek" in names:
        alone = os.path.join(out_dir, "planet-seek-alone.png")
        err, _ = _run([engine, "render", paths["planet-seek"], "-f", str(SEEK_FRAMES), "-o", alone], exec)
        if not err:
            pattern = os.path.join(out_dir, "planet-seek-seq-%04d.png")
            err, _ = _run([engine, "render", paths["planet-seek"], "--frames", f"0..={SEEK_FRAMES}", "-o", pattern], exec)
            if not err:
                frames["seek-alone"], frames["seek-played"] = sk._load_png(alone), sk._load_png(pattern % SEEK_FRAMES)
        if err:
            errors["planet-seek"] = err
    for name in names:
        needed = ["seek-alone", "seek-played"] if name == "planet-seek" else DOCUMENTS[name]
        missing = [k for k in needed if k not in frames]
        if missing:
            error = errors.get("planet-seek") if name == "planet-seek" else "; ".join(
                f"{k}: {errors.get(k, 'no frame')}" for k in missing)
            report[name] = {"pass": False, "error": error or "no frame"}
            continue
        report[name] = measure(name, frames, exp)
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
    ap.add_argument("--out", default=os.path.join(CONF, "out", "planets-kit"), help="where documents and frames go")
    ap.add_argument("--write", metavar="DIR", help="write the documents and textures to DIR and stop")
    ap.add_argument("--only", metavar="CASE", action="append", help="measure these cases only (repeatable)")
    a = ap.parse_args(argv)
    if a.write:
        for p in write(a.write).values():
            print(p)
        return 0
    if not a.engine:
        ap.error("--engine BIN or --write DIR")
    report = run(a.engine, a.out, only=a.only)
    print(table(report))
    return 0 if all(r["pass"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
