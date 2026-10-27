"""The orbits draft's kit: writes its eight cases as 1.8 documents, renders them with an engine and measures each
frame against `orbits_reference`.

Every case is seen by an orthographic camera at the scene origin with `orthoHeight` equal to the frame's height,
so one scene unit is one pixel and a point at scene (x, y) lands on pixel (W / 2 + x, H / 2 + y); the bodies are
unlit spheres of one pure colour each, read as the centroid of the pixels lit in that channel alone. Orbits and
pairs lie in the space x-z plane (an inclination of 90 degrees), which the time-frames axes map to the scene's
x-y plane. `python orbits_kit.py --write DIR` writes the documents; `--engine BIN` renders and measures them.
"""
import argparse
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import orbits_reference as ob  # noqa: E402

W, H = 640, 360
FPS = 24
EPOCH = "2451545.0"                       # J2000 as a Julian day, timeScale tdb
NAMES = ["orbit-ellipse", "orbit-hyperbola", "nbody-pair", "nbody-eight", "nbody-cluster", "nbody-adaptive",
         "trail", "nbody-seek"]
DOCUMENTS = {name: [name] for name in NAMES}
DOCUMENTS["nbody-pair"] = [f"nbody-pair-{i}" for i in ob.INTEGRATORS]

MU = 1e20                                 # m^3/s^2, the ellipse's, hyperbola's and trail's central parameter
A_M = 1e9                                 # the ellipse's semi-major axis: 100 px at ORBIT_PPM
ORBIT_PPM = 1e-7
ELLIPSE_E = 0.3
HYPERBOLA_E = 1.5
HYPERBOLA_A_M = 5e8                       # |a| is 50 px: the leg to the frame's edge nears the asymptote
HYPERBOLA_NU0 = -110.0                    # the true anomaly at the epoch (incoming)
HYPERBOLA_NU1 = 118.0                     # the true anomaly at frame 24 (leaving through the top edge)
INCLINATION = 90.0                        # the orbit plane is the space x-z plane: the scene's x-y plane
ORBIT_FRAMES = 24                         # one period, or the hyperbola's passage, over one second of playback
PAIR_PPM = 100.0                          # the pair's unit separation is 100 px
PAIR_STEPS_PER_ORBIT = 24                 # one step per frame at 24 fps: OR3's whole number of steps
PAIR_ORBITS = 20
PAIR_FRAMES = (0, 240, 480)
EIGHT_STEPS_PER_FRAME = 20                # 480 steps per period
ADAPTIVE_E = 0.9
ADAPTIVE_TOLERANCE = 1e-9
ADAPTIVE_FIRST_STEP_FRACTION = 1.0 / 240.0
ADAPTIVE_FRAMES = (0, 12, 24)             # apocentre, pericentre, apocentre
CLUSTER = dict(count=400, mass=2e32, scale=1e12, seed=42, prefix="c", radius=1)
CLUSTER_PPM = 4e-11                       # the Plummer radius is 40 px
CLUSTER_MARGIN_PX = 3.0                   # bodies expected this close to the frame's edge are not read
CLUSTER_ISOLATION_PX = 6.0                # a body read alone has no other within this distance
CLUSTER_WINDOW_PX = 3.0
TRAIL_SAMPLES = 16
TRAIL_WIDTH = 3
TRAIL_FRAME = 12                          # half a period: the trail covers the quarter before it
TRAIL_WINDOW_PX = 1.5                     # the ribbon is read within this of each sample (its half-width)
TRAIL_LEVEL_TOL = 0.06                    # of the linear opacity 1 - (1 - alpha)^2: the tube seen through both walls
SEEK_FRAMES = 600
SEEK_DURATION = 26.0
RADIUS = {"centre": 6, "body": 4, "small": 3}

ORBIT_TOL_PX = 0.5
HYPERBOLA_TOL_DEG = 0.5
HYPERBOLA_TOL_PX = 1.0
HYPERBOLA_FAR_PX = 120.0                  # the chord is read between frames at least this far from the centre
PAIR_TOL_PX = 1.0
EIGHT_TOL_PX = 1.0
CLUSTER_TOL_PX = 1.0
ADAPTIVE_TOL_PX = 1.0
TRAIL_TOL_PX = 1.0
TRAIL_MONOTONE_SLACK = 0.02               # in linear light
LIT = 127.0                               # an 8-bit channel above this is lit
DARK = 64.0                               # the other channels below this: the colour is pure

COLOURS = {"red": "#FF0000FF", "green": "#00FF00FF", "blue": "#0000FFFF", "white": "#FFFFFFFF"}
CHANNEL = {"red": 0, "green": 1, "blue": 2}


# ------------------------------------------------------------------------------------ geometry


def swap(v):
    """The space x-y plane turned into the x-z plane: (x, y, z) -> (x, z, y)."""
    return (v[0], v[2], v[1])


def swapped(s):
    """A reference system turned into the x-z plane."""
    return ob.system(list(s["masses"]), [swap(p) for p in s["positions"]], [swap(v) for v in s["velocities"]],
                     G=s["G"], softening=s["softening"])


def hyperbola_time(mu, a, e, nu):
    """The time from pericentre of a hyperbola's true anomaly (seconds)."""
    if not (e > 1.0) or not (a < 0.0):
        raise ob.OrbitError("a hyperbola has e above 1 and a negative")
    half = math.radians(nu) / 2.0
    tanh_half = math.sqrt((e - 1.0) / (e + 1.0)) * math.tan(half)
    if abs(tanh_half) >= 1.0:
        raise ob.OrbitError("the true anomaly is inside the asymptotes")
    big_h = 2.0 * math.atanh(tanh_half)
    n = math.sqrt(mu / (-a) ** 3)
    return (e * math.sinh(big_h) - big_h) / n


def asymptote(mu, a, e, i, raan, argp):
    """The unit direction a hyperbola leaves along: the position's direction as the true anomaly nears its limit."""
    nu_inf = math.degrees(math.acos(-1.0 / e))
    r, _ = ob.state_from_elements(mu, a, e, i, raan, argp, nu_inf - 1e-7)
    return ob.unit(r)


def eccentric_pair(e=ADAPTIVE_E):
    """The adaptive case's pair: masses 1 and 1e-3, G 1, semi-major axis 1, at apocentre in the x-z plane."""
    m, mu = 1e-3, 1.0 + 1e-3
    r = 1.0 + e
    v = math.sqrt(mu * (1.0 - e) / (1.0 * (1.0 + e)))
    return ob.system([1.0, m], [(-m / mu * r, 0.0, 0.0), (1.0 / mu * r, 0.0, 0.0)],
                     [(0.0, 0.0, -m / mu * v), (0.0, 0.0, v / mu)], G=1.0)


def geometry():
    """Every case's numbers, by case name."""
    g = {}
    period = ob.period(MU, A_M)
    g["orbit-ellipse"] = dict(mu=MU, a=A_M, e=ELLIPSE_E, period=period, rate=period, ppm=ORBIT_PPM,
                              frames=tuple(range(ORBIT_FRAMES + 1)))
    t0 = hyperbola_time(MU, -HYPERBOLA_A_M, HYPERBOLA_E, HYPERBOLA_NU0)
    t1 = hyperbola_time(MU, -HYPERBOLA_A_M, HYPERBOLA_E, HYPERBOLA_NU1)
    g["orbit-hyperbola"] = dict(mu=MU, a=-HYPERBOLA_A_M, e=HYPERBOLA_E, nu0=HYPERBOLA_NU0, rate=t1 - t0, ppm=ORBIT_PPM,
                                frames=tuple(range(ORBIT_FRAMES + 1)), pericentre_frame=-t0 / (t1 - t0) * FPS,
                                asymptote=asymptote(MU, -HYPERBOLA_A_M, HYPERBOLA_E, INCLINATION, 0.0, 0.0))
    pair = swapped(ob._pair())
    step = ob.TWO_PI / PAIR_STEPS_PER_ORBIT
    g["nbody-pair"] = dict(system=pair, step=step, rate=ob.TWO_PI, ppm=PAIR_PPM, frames=PAIR_FRAMES,
                           duration=PAIR_ORBITS + 1)
    eight = swapped(ob._eight())
    g["nbody-eight"] = dict(system=eight, step=ob.EIGHT_PERIOD / FPS / EIGHT_STEPS_PER_FRAME, rate=ob.EIGHT_PERIOD,
                            ppm=PAIR_PPM, frames=(0, ORBIT_FRAMES), duration=2)
    g["nbody-cluster"] = dict(ppm=CLUSTER_PPM, frames=(0,), **CLUSTER)
    pair_e = eccentric_pair()
    p = ob.period(1.0 + 1e-3, 1.0)
    g["nbody-adaptive"] = dict(system=pair_e, period=p, step=p * ADAPTIVE_FIRST_STEP_FRACTION, rate=p, ppm=PAIR_PPM,
                               tolerance=ADAPTIVE_TOLERANCE, frames=ADAPTIVE_FRAMES, duration=2)
    g["trail"] = dict(g["orbit-ellipse"], length=period / 4.0, samples=TRAIL_SAMPLES, width=TRAIL_WIDTH,
                      frames=(TRAIL_FRAME,))
    seek_rate = ob.TWO_PI / 10.0
    g["nbody-seek"] = dict(system=pair, step=ob.TWO_PI / 240.0, rate=seek_rate, ppm=PAIR_PPM, frames=(SEEK_FRAMES,),
                           duration=SEEK_DURATION)
    return g


# ------------------------------------------------------------------------------------ documents


def _materials(*names):
    return "".join(f'<material id="{n}" baseColor="{COLOURS[n]}" unlit="true"/>' for n in names)


def _sphere(id_, colour, radius, extra=""):
    return f'<object3D id="{id_}" primitive="sphere" radius="{radius}" material="{colour}"{extra}/>'


def _orbit(id_, colour, radius, mu, a, e, anomaly=0.0, trail=""):
    children = (f'<orbit around="centre" mu="{mu!r}" a="{a!r}" e="{e!r}" i="{INCLINATION:g}" anomaly="{anomaly:g}"/>'
                + trail)
    return f'<object3D id="{id_}" primitive="sphere" radius="{radius}" material="{colour}">{children}</object3D>'


def _members(s, ids):
    return "".join(f'<member ref="{i}" mass="{m!r}" x="{p[0]!r}" y="{p[1]!r}" z="{p[2]!r}" '
                   f'vx="{v[0]!r}" vy="{v[1]!r}" vz="{v[2]!r}"/>'
                   for i, m, p, v in zip(ids, s["masses"], s["positions"], s["velocities"]))


def _doc(materials, objects, ppm, rate, duration=2, nbody=""):
    space = (f'<space epoch="{EPOCH}" timeScale="tdb" rate="{rate!r}">{nbody}</space>' if nbody
             else f'<space epoch="{EPOCH}" timeScale="tdb" rate="{rate!r}"/>')
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="1.8"><project width="{W}" height="{H}" fps="{FPS}" duration="{duration:g}" '
            f'background="#000000FF"/>\n'
            f'<materials>{materials}</materials>\n'
            f'<composition><camera id="cam" projection="orthographic" orthoHeight="{H}" x="0" y="0" z="-1000"/>\n'
            f'{objects}\n</composition>\n'
            f'<physics pixelsPerMeter="{ppm!r}"/>\n'
            f'{space}</scene>\n')


def documents():
    """The ten documents of the eight cases, by document key."""
    g = geometry()
    docs = {}
    c = g["orbit-ellipse"]
    centre = _sphere("centre", "red", RADIUS["centre"])
    docs["orbit-ellipse"] = _doc(_materials("red", "green"),
                                 centre + _orbit("body", "green", RADIUS["body"], c["mu"], c["a"], c["e"]),
                                 c["ppm"], c["rate"])
    h = g["orbit-hyperbola"]
    docs["orbit-hyperbola"] = _doc(_materials("red", "green"),
                                   centre + _orbit("body", "green", RADIUS["body"], h["mu"], h["a"], h["e"], h["nu0"]),
                                   h["ppm"], h["rate"])
    p = g["nbody-pair"]
    pair_objects = _sphere("a", "red", RADIUS["centre"]) + _sphere("b", "green", RADIUS["body"])
    for integrator in ob.INTEGRATORS:
        nbody = f'<nbody G="1" integrator="{integrator}" step="{p["step"]!r}">{_members(p["system"], ("a", "b"))}</nbody>'
        docs[f"nbody-pair-{integrator}"] = _doc(_materials("red", "green"), pair_objects, p["ppm"], p["rate"],
                                                duration=p["duration"], nbody=nbody)
    e = g["nbody-eight"]
    eight_objects = "".join(_sphere(i, colour, RADIUS["body"]) for i, colour in zip("abc", ("red", "green", "blue")))
    nbody = f'<nbody G="1" integrator="ias15" step="{e["step"]!r}">{_members(e["system"], "abc")}</nbody>'
    docs["nbody-eight"] = _doc(_materials("red", "green", "blue"), eight_objects, e["ppm"], e["rate"],
                               duration=e["duration"], nbody=nbody)
    k = g["nbody-cluster"]
    cluster = (f'<cluster count="{k["count"]}" mass="{k["mass"]!r}" scale="{k["scale"]!r}" seed="{k["seed"]}" '
               f'prefix="{k["prefix"]}" radius="{k["radius"]}"/>')
    docs["nbody-cluster"] = _doc(_materials("white"), "", k["ppm"], 0.0, duration=1, nbody=f"<nbody>{cluster}</nbody>")
    d = g["nbody-adaptive"]
    adaptive_objects = _sphere("a", "red", RADIUS["body"]) + _sphere("b", "green", RADIUS["small"])
    nbody = (f'<nbody G="1" integrator="ias15" step="{d["step"]!r}" tolerance="{d["tolerance"]!r}">'
             f'{_members(d["system"], ("a", "b"))}</nbody>')
    docs["nbody-adaptive"] = _doc(_materials("red", "green"), adaptive_objects, d["ppm"], d["rate"],
                                  duration=d["duration"], nbody=nbody)
    t = g["trail"]
    trail = f'<trail length="{t["length"]!r}" samples="{t["samples"]}" width="{t["width"]}" color="{COLOURS["blue"]}"/>'
    docs["trail"] = _doc(_materials("red", "green", "blue"),
                         centre + _orbit("body", "green", RADIUS["body"], t["mu"], t["a"], t["e"], trail=trail),
                         t["ppm"], t["rate"])
    s = g["nbody-seek"]
    nbody = f'<nbody G="1" integrator="leapfrog" step="{s["step"]!r}">{_members(s["system"], ("a", "b"))}</nbody>'
    docs["nbody-seek"] = _doc(_materials("red", "green"), pair_objects, s["ppm"], s["rate"], duration=s["duration"],
                              nbody=nbody)
    return docs


def write(out_dir):
    """Write the documents under out_dir; returns their paths by key."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for key, text in documents().items():
        path = os.path.join(out_dir, f"srep-0000-{key}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        paths[key] = path
    return paths


# ------------------------------------------------------------------------------------ expectations


def pixel(p_m, ppm):
    """The pixel a space position lands on: the scene mapping about the origin, one unit per pixel."""
    s = ob.scene_position(p_m, ob.ZERO, ppm)
    return (W / 2.0 + s[0], H / 2.0 + s[1])


def frame_time(frame, rate):
    return frame / FPS * rate


def expectations():
    """The reference's pixel positions of every case, by case name."""
    g = geometry()
    exp = {}
    c = g["orbit-ellipse"]
    orb = ob.orbit(c["mu"], c["a"], c["e"], INCLINATION, 0.0, 0.0, 0.0, 0.0)
    exp["orbit-ellipse"] = {"body": {f: pixel(ob.orbit_state(orb, frame_time(f, c["rate"]))[0], c["ppm"])
                                     for f in c["frames"]}}
    h = g["orbit-hyperbola"]
    orb_h = ob.orbit(h["mu"], h["a"], h["e"], INCLINATION, 0.0, 0.0, h["nu0"], 0.0)
    exp["orbit-hyperbola"] = {"body": {f: pixel(ob.orbit_state(orb_h, frame_time(f, h["rate"]))[0], h["ppm"])
                                       for f in h["frames"]},
                              "asymptote": _direction_px(h["asymptote"]), "pericentre_frame": h["pericentre_frame"]}
    p = g["nbody-pair"]
    exp["nbody-pair"] = {i: {f: [pixel(q, p["ppm"]) for q in
                                 ob.integrate(p["system"], i, p["step"], frame_time(f, p["rate"]))["positions"]]
                             for f in p["frames"]} for i in ob.INTEGRATORS}
    e = g["nbody-eight"]
    exp["nbody-eight"] = {f: [pixel(q, e["ppm"]) for q in
                              ob.integrate(e["system"], "ias15", e["step"], frame_time(f, e["rate"]))["positions"]]
                          for f in e["frames"]}
    k = g["nbody-cluster"]
    cluster = ob.plummer(k["seed"], k["count"], k["mass"], k["scale"])
    exp["nbody-cluster"] = {"bodies": [pixel(q, k["ppm"]) for q in cluster["positions"]]}
    d = g["nbody-adaptive"]
    exp["nbody-adaptive"] = {f: [pixel(q, d["ppm"]) for q in
                                 ob.integrate_adaptive(d["system"], frame_time(f, d["rate"]), d["step"],
                                                       d["tolerance"])[0]["positions"]]
                             for f in d["frames"]}
    t = g["trail"]
    times = ob.trail_times(frame_time(TRAIL_FRAME, t["rate"]), t["length"], t["samples"])
    exp["trail"] = {"samples": [pixel(q, t["ppm"]) for q in ob.orbit_trail(orb, frame_time(TRAIL_FRAME, t["rate"]),
                                                                           t["length"], t["samples"])],
                    "alphas": [ob.trail_alpha(times[-1] - tk, t["length"]) for tk in times]}
    exp["nbody-seek"] = {}
    return exp


def _direction_px(d):
    """A space direction's direction on the frame (x right, y down)."""
    s = ob.scene_position(d, ob.ZERO, 1.0)
    n = math.hypot(s[0], s[1])
    return (s[0] / n, s[1] / n)


# ------------------------------------------------------------------------------------ measurements


def load(png):
    return np.asarray(Image.open(png).convert("RGB")).astype(float)


def pure(rgb, colour):
    """The pixels lit in one channel alone."""
    c = CHANNEL[colour]
    others = np.delete(rgb, c, axis=2).max(axis=2)
    return (rgb[..., c] > LIT) & (others < DARK)


def centroid(mask):
    """The centre of the true pixels in continuous frame coordinates (pixel i covers [i, i + 1))."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return (math.nan, math.nan)
    return (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5)


def body_centroid(rgb, colour):
    return centroid(pure(rgb, colour))


def window(mask_or_values, at, radius):
    """The slice of a frame within `radius` pixels of a point: (rows, cols, the sub-array)."""
    x, y = at
    r = int(math.ceil(radius))
    rows = slice(max(0, int(y) - r), min(H, int(y) + r + 1))
    cols = slice(max(0, int(x) - r), min(W, int(x) + r + 1))
    return rows, cols, mask_or_values[rows, cols]


def local_centroid(mask, at, radius):
    """The centroid of the true pixels within `radius` of a point (nan without any)."""
    rows, cols, sub = window(mask, at, radius)
    ys, xs = np.nonzero(sub)
    if len(xs) == 0:
        return (math.nan, math.nan)
    inside = [(x, y) for x, y in zip(xs + cols.start + 0.5, ys + rows.start + 0.5)
              if math.hypot(x - at[0], y - at[1]) <= radius]
    if not inside:
        return (math.nan, math.nan)
    return (sum(p[0] for p in inside) / len(inside), sum(p[1] for p in inside) / len(inside))


def paint_discs(points, radius, value=255.0):
    """A synthetic frame with a disc at each point: the raster of the expected bodies."""
    frame = np.zeros((H, W), dtype=float)
    ys, xs = np.mgrid[0:H, 0:W]
    for x, y in points:
        if -radius - 1 <= x <= W + radius + 1 and -radius - 1 <= y <= H + radius + 1:
            frame[(xs + 0.5 - x) ** 2 + (ys + 0.5 - y) ** 2 <= radius * radius] = value
    return frame


def identical(a, b):
    return a.shape == b.shape and bool(np.array_equal(a, b))


def linear(v):
    """Linear light of 8-bit sRGB values (the engine's PNG encoding)."""
    c = np.asarray(v, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def tube_opacity(alpha):
    """The opacity of a trail's tube seen through both of its walls, each of vertex alpha `alpha`."""
    return 1.0 - (1.0 - alpha) ** 2


def off(measured, expected):
    return math.dist(measured, expected) if all(map(math.isfinite, measured)) else math.inf


def in_frame(at, margin):
    return margin <= at[0] <= W - margin and margin <= at[1] <= H - margin


def _r(v, n=3):
    return tuple(round(float(x), n) for x in v)


def measure(name, frames, exp):
    """Measure one case from its frames (by "document@frame") against the expectations."""
    if name not in NAMES:
        raise ValueError(name)
    e = exp[name]
    if name == "orbit-ellipse":
        offs = {f: off(body_centroid(frames[f"orbit-ellipse@{f}"], "green"), e["body"][f]) for f in e["body"]}
        first, last = (body_centroid(frames[f"orbit-ellipse@{f}"], "green") for f in (0, ORBIT_FRAMES))
        closure = off(first, last)
        worst = max(offs.values())
        return {"pass": worst <= ORBIT_TOL_PX and closure <= ORBIT_TOL_PX, "frames": len(offs),
                "worst_off_px": round(worst, 3), "closure_px": round(closure, 3),
                "frame_0": _r(first), "frame_24": _r(last)}
    if name == "orbit-hyperbola":
        seen = {}
        for f, want in e["body"].items():
            got = body_centroid(frames[f"orbit-hyperbola@{f}"], "green")
            if in_frame(want, RADIUS["body"] + 2) and all(map(math.isfinite, got)):
                seen[f] = (got, want)
        offs = {f: off(got, want) for f, (got, want) in seen.items()}
        # the chord from the first to the last frame of the outgoing leg that is far from the centre, measured
        # and expected; the expected chord's angle to the asymptote is reported
        leg = sorted(f for f, (got, want) in seen.items() if f > e["pericentre_frame"]
                     and math.hypot(want[0] - W / 2.0, want[1] - H / 2.0) >= HYPERBOLA_FAR_PX)
        if len(leg) < 2:
            return {"pass": False, "error": "fewer than two far outgoing frames in the frame", "frames": len(seen)}
        f1, f2 = leg[0], leg[-1]
        (g1, w1), (g2, w2) = seen[f1], seen[f2]
        measured = _angle(g1, g2)
        expected = _angle(w1, w2)
        asym = math.degrees(math.atan2(e["asymptote"][1], e["asymptote"][0]))
        chord_off = _angle_diff(measured, expected)
        worst = max(offs.values())
        return {"pass": chord_off <= HYPERBOLA_TOL_DEG and worst <= HYPERBOLA_TOL_PX, "frames": len(seen),
                "chord_frames": (f1, f2), "chord_deg": round(measured, 3), "expected_chord_deg": round(expected, 3),
                "chord_off_deg": round(chord_off, 3), "asymptote_deg": round(asym, 3),
                "chord_to_asymptote_deg": round(_angle_diff(expected, asym), 3), "worst_off_px": round(worst, 3)}
    if name == "nbody-pair":
        out, worst = {}, 0.0
        for i in ob.INTEGRATORS:
            offs = {}
            for f, want in e[i].items():
                rgb = frames[f"nbody-pair-{i}@{f}"]
                offs[f] = (round(off(body_centroid(rgb, "red"), want[0]), 3),
                           round(off(body_centroid(rgb, "green"), want[1]), 3))
            worst = max([worst] + [o for pair in offs.values() for o in pair])
            out[i] = offs
        return {"pass": worst <= PAIR_TOL_PX, "worst_off_px": round(worst, 3), **out}
    if name == "nbody-eight":
        f0, f1 = (frames[f"nbody-eight@{f}"] for f in (0, ORBIT_FRAMES))
        colours = ("red", "green", "blue")
        start = [body_centroid(f0, c) for c in colours]
        end = [body_centroid(f1, c) for c in colours]
        returns = [off(a, b) for a, b in zip(end, start)]
        offs = [off(a, b) for a, b in zip(end, e[ORBIT_FRAMES])] + [off(a, b) for a, b in zip(start, e[0])]
        return {"pass": max(returns) <= EIGHT_TOL_PX and max(offs) <= EIGHT_TOL_PX,
                "return_px": _r(returns), "worst_off_px": round(max(offs), 3), "start": [_r(p) for p in start]}
    if name == "nbody-cluster":
        rgb = frames["nbody-cluster@0"]
        lit = rgb.max(axis=2) > LIT
        bodies = e["bodies"]
        inside = [p for p in bodies if in_frame(p, CLUSTER_MARGIN_PX)]
        isolated = [j for j, p in enumerate(bodies) if in_frame(p, CLUSTER_MARGIN_PX)
                    and all(math.dist(p, q) >= CLUSTER_ISOLATION_PX for i2, q in enumerate(bodies) if i2 != j)]
        offs = {j: off(local_centroid(lit, bodies[j], CLUSTER_WINDOW_PX), bodies[j]) for j in isolated}
        worst = max(offs.values()) if offs else math.inf
        expected_centroid = centroid(paint_discs(inside, CLUSTER["radius"]) > 0.0)
        frame_centroid = centroid(lit)
        centre_off = off(frame_centroid, expected_centroid)
        body3 = offs.get(3)
        return {"pass": worst <= CLUSTER_TOL_PX and centre_off <= CLUSTER_TOL_PX and len(isolated) >= 10,
                "in_frame": len(inside), "isolated": len(isolated), "worst_off_px": round(worst, 3),
                "body_3": ("isolated, off_px %.3f" % body3) if body3 is not None else "not isolated",
                "centroid": _r(frame_centroid), "expected_centroid": _r(expected_centroid),
                "centroid_off_px": round(centre_off, 3), "lit_pixels": int(lit.sum())}
    if name == "nbody-adaptive":
        offs = {}
        for f, want in e.items():
            rgb = frames[f"nbody-adaptive@{f}"]
            offs[f] = (round(off(body_centroid(rgb, "red"), want[0]), 3),
                       round(off(body_centroid(rgb, "green"), want[1]), 3))
        worst = max(o for pair in offs.values() for o in pair)
        peri = body_centroid(frames[f"nbody-adaptive@{ADAPTIVE_FRAMES[1]}"], "green")
        return {"pass": worst <= ADAPTIVE_TOL_PX, "worst_off_px": round(worst, 3),
                "pericentre": _r(peri), "expected_pericentre": _r(e[ADAPTIVE_FRAMES[1]][1]), **offs}
    if name == "trail":
        rgb = frames[f"trail@{TRAIL_FRAME}"]
        blue = linear(rgb[..., 2]) * (rgb[..., 0] < DARK) * (rgb[..., 1] < DARK)
        levels, offs = [], []
        for k, at in enumerate(e["samples"][:-1]):             # the newest sample is under the body
            _, _, sub = window(blue, at, TRAIL_WINDOW_PX)
            levels.append(float(sub.max()) if sub.size else 0.0)
            if e["alphas"][k] >= 0.2:
                offs.append(off(local_centroid(blue > 0.05, at, TRAIL_WINDOW_PX), at))
        model = [tube_opacity(a) for a in e["alphas"][:-1]]
        level_offs = [abs(lv - m) for lv, m in zip(levels, model)]
        monotone = all(b >= a - TRAIL_MONOTONE_SLACK for a, b in zip(levels, levels[1:]))
        worst = max(offs) if offs else math.inf
        return {"pass": worst <= TRAIL_TOL_PX and max(level_offs) <= TRAIL_LEVEL_TOL and monotone,
                "worst_off_px": round(worst, 3), "read_samples": len(offs), "oldest": round(levels[0], 3),
                "newest": round(levels[-1], 3), "worst_level_off": round(max(level_offs), 3), "monotone": monotone,
                "levels": [round(v, 2) for v in levels]}
    if name == "nbody-seek":
        same = identical(frames["seek-alone"], frames["seek-played"])
        return {"pass": same, "identical": same}
    raise ValueError(name)


def _angle(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _angle_diff(a, b):
    d = (a - b + 180.0) % 360.0 - 180.0
    return abs(d)


# ------------------------------------------------------------------------------------ running


def _run(cmd, exec):
    r = exec(cmd, capture_output=True, text=True)
    text = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0:
        err = text.strip().splitlines()
        return err[0] if err else f"exit {r.returncode}", text
    return None, text


def _render(engine, doc, png, exec, frame=None, frames=None):
    cmd = [engine, "render", doc] + (["--frames", frames] if frames else ["-f", str(frame)]) + ["-o", png]
    return _run(cmd, exec)


def plan():
    """Which frames of which document each case needs: (document key, frames, as one sequence or one by one)."""
    g = geometry()
    out = {}
    for name in NAMES:
        frames = g[name]["frames"]
        sequence = name in ("orbit-ellipse", "orbit-hyperbola")
        out[name] = [(key, frames, sequence) for key in DOCUMENTS[name]]
    return out


def run(engine, out_dir, exec=subprocess.run, only=None):
    """Write the cases, render each document's frames with the engine and measure every case (or those in
    `only`); a case with a document the engine refuses reports that document's first diagnostic line."""
    names = [n for n in NAMES if only is None or n in only]
    exp = expectations()
    paths = write(out_dir)
    report, frames = {}, {}
    for name in names:
        error = None
        for key, wanted, sequence in plan()[name]:
            if name == "nbody-seek":
                alone = os.path.join(out_dir, f"{key}-alone.png")
                error, _ = _render(engine, paths[key], alone, exec, frame=SEEK_FRAMES)
                if not error:
                    pattern = os.path.join(out_dir, f"{key}-seq-%04d.png")
                    error, _ = _render(engine, paths[key], pattern, exec, frames=f"0..={SEEK_FRAMES}")
                if not error:
                    frames["seek-alone"], frames["seek-played"] = load(alone), load(pattern % SEEK_FRAMES)
            elif sequence:
                pattern = os.path.join(out_dir, f"{key}-seq-%04d.png")
                error, _ = _render(engine, paths[key], pattern, exec, frames=f"{min(wanted)}..={max(wanted)}")
                if not error:
                    for f in wanted:
                        frames[f"{key}@{f}"] = load(pattern % f)
            else:
                for f in wanted:
                    png = os.path.join(out_dir, f"{key}-f{f}.png")
                    error, _ = _render(engine, paths[key], png, exec, frame=f)
                    if error:
                        break
                    frames[f"{key}@{f}"] = load(png)
            if error:
                error = f"{key}: {error}"
                break
        report[name] = {"pass": False, "error": error} if error else measure(name, frames, exp)
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
    ap.add_argument("--out", default=os.path.join(CONF, "out", "orbits-kit"), help="where documents and frames go")
    ap.add_argument("--write", metavar="DIR", help="write the documents to DIR and stop")
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
