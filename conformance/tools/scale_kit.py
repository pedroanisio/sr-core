"""The scale draft's kit: writes its eight cases as 1.8 documents, renders them with an engine and measures each
frame against `scale_reference`.

The perspective cases are seen by a camera of horizontal `fov` 60 over a frame W pixels wide, whose focal length
is `focal_pixels(60, W)`: a point at (x, y, z) in the camera's frame lands on pixel (W / 2 + focal x / z,
H / 2 + focal y / z), y down the frame. The spheres are unlit, of one pure colour each and single-sided, so a
camera inside a sphere sees nothing of it; a sphere of radius r on the axis at distance d is a disc of radius
`sphere_pixels(r, d, focal)` = focal r / √(d² − r²). Scale bars are read from the engine's `--stats` line of
each frame (`scale_bars`: camera, measured, depth, pixels, label) and from their pixels. `python scale_kit.py
--write DIR` writes the documents; `--engine BIN` renders and measures them.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import scale_reference as sc  # noqa: E402

W, H = 640, 360
FPS = 24
FOV = 60.0
PPM = 100.0                               # pixelsPerMeter: the schema's default, stated in every document
INVALID = ("sc1", "sc2", "sc3", "sc4", "v17")
NAMES = ["scale-depth", "scale-depth-log", "scale-powers", "scale-bar", "scale-bar-ortho", "scale-origin",
         "scale-seek", "scale-invalid"]
DOCUMENTS = {
    "scale-depth": ["scale-depth"],
    "scale-depth-log": ["scale-depth", "scale-depth-log"],
    "scale-powers": ["scale-powers"],
    "scale-bar": ["scale-bar"],
    "scale-bar-ortho": ["scale-bar-ortho"],
    "scale-origin": ["scale-origin-here", "scale-origin-far"],
    "scale-seek": ["scale-powers"],
    "scale-invalid": [f"scale-invalid-{c}" for c in INVALID],
}

DEPTH_NEAR, DEPTH_FAR = 0.1, 1e19         # SC1's full ratio of 1e20
DEPTH_DECADES = tuple(range(19))          # a pair of spheres at 10^k pixels for k = 0 … 18
DEPTH_SIZE = 0.04                         # a sphere's radius over its distance: 2.3 degrees, a 22 pixel disc
DEPTH_GAP = 1e-4                          # the farther sphere of a pair sits this much farther, one part in 1e4
DEPTH_COLUMNS = (-240, -120, 0, 120, 240) # the pairs' pixel centres about the frame's centre: 5 columns by 4 rows
DEPTH_ROWS = (-120, -40, 40, 120)
DEPTH_WINDOW_PX = 12.0                    # each pair is read within this radius of its centre: all the nearer colour
DEPTH_FRAMES = (0,)
LOG_LEVEL_TOL = 1.0                       # the logarithmic image equals the reversed one within this 8-bit level

POWERS_T0, POWERS_T1 = 2.0, 40.0
POWERS_D0, POWERS_D1 = 10.0, 1e20         # the camera's distance keyed geometric from 10 to 1e20 pixels
POWERS_NEAR, POWERS_FAR = 1.0, 1e20
POWERS_DURATION = 41.0
POWERS_RADIUS = 2.0                       # the concentric spheres' radii are 2 × 10^k, k = 0 … 18
POWERS_DECADES = tuple(range(19))
POWERS_FRAMES = tuple(48 + 48 * k for k in POWERS_DECADES)   # the camera 10^(k + 1) pixels away: a sphere a fifth
POWERS_TOL_PX = 1.5                       # a disc's radius against the reference (the sphere's tessellation)
POWERS_SPREAD_PX = 0.5                    # the radii of the 19 frames against each other (rule 2)

BAR_W, BAR_H = 1920, 1080
BAR_FRAMES = (0, 96, 480, 960)
BAR_MAX_WIDTH = 200
BAR_X, BAR_Y, BAR_THICKNESS = 24, 24, 2   # the schema's defaults
BAR_REL_TOL = 1e-9                        # the reported bar against the reference
BAR_RUN_TOL_PX = 1.0                      # the drawn run's end against the reported length
ORTHO_W, ORTHO_H = 640, 1080
ORTHO_HEIGHT = 2000.0
ORTHO_Z = -100.0

ORIGIN_X = 1e20
ORIGIN_Z = -200000.0
ORIGIN_HALF = 2.0 ** 16                   # the spheres are 2^17 pixels apart
ORIGIN_RADIUS = 2.0 ** 14
ORIGIN_NEAR, ORIGIN_FAR = 10.0, 1e7
ORIGIN_FRAMES = (0, 12)
ORIGIN_TOL_PX = 0.5                       # against the camera at the origin
ORIGIN_MOTION_PX = 0.05                   # between frames

SEEK_FRAMES = 960

LIT = 127.0                               # an 8-bit channel above this is lit
DARK = 64.0                               # the other channels below this: the colour is pure
COLOURS = {"red": "#FF0000FF", "green": "#00FF00FF", "grey": "#404040FF"}
CHANNEL = {"red": 0, "green": 1}
PARITY = ("red", "green")                 # the concentric spheres' colours by k


# ------------------------------------------------------------------------------------ geometry


def focal(width=W):
    return sc.focal_pixels(FOV, width)


def pixel(p, width=W, height=H):
    """The pixel a point (x, y, z) in the camera's frame lands on."""
    x, y, z = p
    if not z > 0.0:
        raise ValueError("the point is in front of the camera")
    f = focal(width)
    return (width / 2.0 + f * x / z, height / 2.0 + f * y / z)


def direction(px, py, width=W, height=H):
    """The unit direction through a pixel."""
    f = focal(width)
    u, v = (px - width / 2.0) / f, (py - height / 2.0) / f
    n = math.sqrt(1.0 + u * u + v * v)
    return (u / n, v / n, 1.0 / n)


def sphere_pixels(r, d, f):
    """The pixel radius of a sphere of radius r on the axis at distance d."""
    if not 0.0 < r < d:
        raise ValueError("the camera is outside the sphere")
    return f * r / math.sqrt(d * d - r * r)


def depth_slots():
    """The pixel centres of the 19 pairs, by decade."""
    centres = [(W / 2.0 + c, H / 2.0 + r) for r in DEPTH_ROWS for c in DEPTH_COLUMNS]
    return {k: centres[i] for i, k in enumerate(DEPTH_DECADES)}


def depth_pair(k):
    """The nearer and farther sphere of decade k: centres and radius, in the camera's frame."""
    px, py = depth_slots()[k]
    u = direction(px, py)
    d = 10.0 ** k
    r = DEPTH_SIZE * d
    far = d + (d + r) * DEPTH_GAP
    return {"near": tuple(d * c for c in u), "far": tuple(far * c for c in u), "radius": r, "distance": d}


def powers_distance(frame):
    return sc.frame_distance(frame, FPS, POWERS_T0, POWERS_T1, POWERS_D0, POWERS_D1)


def geometry():
    g = {}
    g["scale-depth"] = {"pairs": {k: depth_pair(k) for k in DEPTH_DECADES}, "frames": DEPTH_FRAMES,
                        "near": DEPTH_NEAR, "far": DEPTH_FAR}
    g["scale-depth-log"] = dict(g["scale-depth"])
    f = focal()
    radii = {k: POWERS_RADIUS * 10.0 ** k for k in POWERS_DECADES}
    g["scale-powers"] = {"radii": radii, "frames": POWERS_FRAMES,
                         "distances": {fr: powers_distance(fr) for fr in POWERS_FRAMES},
                         "pixels": {fr: sphere_pixels(radii[k], powers_distance(fr), f)
                                    for k, fr in zip(POWERS_DECADES, POWERS_FRAMES)}}
    fb = focal(BAR_W)
    g["scale-bar"] = {"frames": BAR_FRAMES, "focal": fb,
                      "bars": {fr: sc.scale_bar_frame(fr, FPS, POWERS_T0, POWERS_T1, POWERS_D0, POWERS_D1, fb, PPM,
                                                      BAR_MAX_WIDTH) for fr in BAR_FRAMES},
                      "rows": (BAR_H - BAR_Y - BAR_THICKNESS, BAR_H - BAR_Y)}
    g["scale-bar-ortho"] = {"frames": (0,), "bar": sc.scale_bar(sc.pixels_per_metre_ortho(ORTHO_HEIGHT, ORTHO_H, PPM),
                                                                BAR_MAX_WIDTH),
                            "rows": (ORTHO_H - BAR_Y - BAR_THICKNESS, ORTHO_H - BAR_Y)}
    here = [pixel((s * ORIGIN_HALF, 0.0, -ORIGIN_Z)) for s in (-1.0, 1.0)]
    g["scale-origin"] = {"frames": ORIGIN_FRAMES, "centres": here,
                         "pixel_radius": sphere_pixels(ORIGIN_RADIUS, -ORIGIN_Z, f)}
    g["scale-seek"] = {"frames": (SEEK_FRAMES,)}
    g["scale-invalid"] = {"documents": DOCUMENTS["scale-invalid"]}
    return g


# ------------------------------------------------------------------------------------ documents


def _materials(*names):
    return "".join(f'<material id="{n}" baseColor="{COLOURS[n]}" unlit="true"/>' for n in names)


def _sphere(id_, colour, radius, x=0.0, y=0.0, z=0.0):
    return (f'<object3D id="{id_}" primitive="sphere" radius="{radius!r}" x="{x!r}" y="{y!r}" z="{z!r}" '
            f'material="{colour}"/>')


def _doc(width, height, duration, materials, composition, version="1.8"):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}"><project width="{width}" height="{height}" fps="{FPS}" '
            f'duration="{duration:g}" background="#000000FF"/>\n'
            f'<materials>{materials}</materials>\n'
            f'<composition>{composition}</composition>\n'
            f'<physics pixelsPerMeter="{PPM!r}"/></scene>\n')


def _powers_camera(extra="", near=POWERS_NEAR, far=POWERS_FAR):
    return (f'<camera id="eye" x="0" y="0" near="{near!r}" far="{far!r}"{extra}>'
            f'<animate property="z"><key time="{POWERS_T0:g}" value="{-POWERS_D0!r}" interpolation="geometric"/>'
            f'<key time="{POWERS_T1:g}" value="{-POWERS_D1!r}"/></animate>')


def _depth_doc(mode):
    spheres = []
    for k in DEPTH_DECADES:
        p = depth_pair(k)
        spheres.append(_sphere(f"near{k}", "red", p["radius"], *p["near"]))
        spheres.append(_sphere(f"far{k}", "green", p["radius"], *p["far"]))
    camera = f'<camera id="eye" x="0" y="0" z="0" near="{DEPTH_NEAR!r}" far="{DEPTH_FAR!r}" depth="{mode}"/>'
    return _doc(W, H, 1, _materials("red", "green"), camera + "\n" + "\n".join(spheres))


def _powers_doc():
    spheres = "\n".join(_sphere(f"s{k}", PARITY[k % 2], POWERS_RADIUS * 10.0 ** k) for k in POWERS_DECADES)
    return _doc(W, H, POWERS_DURATION, _materials("red", "green"), _powers_camera() + "</camera>\n" + spheres)


def _bar_doc():
    camera = _powers_camera(' target="ball"') + "<scaleBar/></camera>"
    return _doc(BAR_W, BAR_H, POWERS_DURATION, _materials("grey"), camera + "\n" + _sphere("ball", "grey", 1.0))


def _ortho_doc():
    camera = (f'<camera id="eye" x="0" y="0" z="{ORTHO_Z!r}" projection="orthographic" '
              f'orthoHeight="{ORTHO_HEIGHT!r}"><scaleBar/></camera>')
    return _doc(ORTHO_W, ORTHO_H, 1, _materials("grey"), camera + "\n" + _sphere("ball", "grey", 10.0))


def _origin_doc(x):
    camera = f'<camera id="eye" x="{x!r}" y="0" z="{ORIGIN_Z!r}" near="{ORIGIN_NEAR!r}" far="{ORIGIN_FAR!r}"/>'
    spheres = (_sphere("a", "red", ORIGIN_RADIUS, x - ORIGIN_HALF) + "\n"
               + _sphere("b", "red", ORIGIN_RADIUS, x + ORIGIN_HALF))
    return _doc(W, H, 1, _materials("red"), camera + "\n" + spheres)


def _invalid_docs():
    ball = _sphere("ball", "grey", 10.0, z=1000.0)
    plain = '<camera id="eye" x="0" y="0" z="0" near="1" far="1e6">'
    return {
        "sc1": _doc(W, H, 1, _materials("grey"),
                    '<camera id="eye" x="0" y="0" z="0" near="0.1" far="2e19"/>' + ball),
        "sc2": _doc(W, H, 1, _materials("grey"),
                    '<camera id="eye" x="0" y="0" near="1" far="1e6"><animate property="z">'
                    '<key time="0" value="-1" interpolation="geometric"/><key time="1" value="10"/>'
                    '</animate></camera>' + ball),
        "sc3": _doc(W, H, 1, _materials("grey"), plain + f'<scaleBar maxWidth="{W + 60}"/></camera>' + ball),
        "sc4": _doc(W, H, 1, _materials("grey"), plain + '<scaleBar distance="2e6"/></camera>' + ball),
        "v17": _doc(W, H, 1, _materials("grey"), plain + '<scaleBar/></camera>' + ball, version="1.7"),
    }


def documents():
    """The eleven documents of the eight cases, by document key."""
    docs = {"scale-depth": _depth_doc("reversed"), "scale-depth-log": _depth_doc("logarithmic"),
            "scale-powers": _powers_doc(), "scale-bar": _bar_doc(), "scale-bar-ortho": _ortho_doc(),
            "scale-origin-here": _origin_doc(0.0), "scale-origin-far": _origin_doc(ORIGIN_X)}
    for code, text in _invalid_docs().items():
        docs[f"scale-invalid-{code}"] = text
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


def expectations():
    """What the reference says each case must measure."""
    return geometry()


# ------------------------------------------------------------------------------------ reading frames


def load(png):
    return np.asarray(Image.open(png).convert("RGB")).astype(np.float64)


def pure(rgb, colour):
    """The pixels lit in this channel alone."""
    c = CHANNEL[colour]
    lit = rgb[..., c] > LIT
    for other in range(3):
        if other != c:
            lit &= rgb[..., other] < DARK
    return lit


def white(rgb):
    """The pixels lit in every channel: the bar and its label."""
    return (rgb[..., 0] > LIT) & (rgb[..., 1] > LIT) & (rgb[..., 2] > LIT)


def centroid(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5)


def disc_radius(mask):
    """The radius of a disc with the mask's area."""
    return math.sqrt(float(mask.sum()) / math.pi)


def window(mask, at, radius):
    """The mask within a circle: (values inside, their count)."""
    h, w = mask.shape
    ys, xs = np.mgrid[0:h, 0:w]
    inside = (xs + 0.5 - at[0]) ** 2 + (ys + 0.5 - at[1]) ** 2 <= radius * radius
    return mask[inside], int(inside.sum())


def run_on_row(mask, row):
    """The first and last lit column of a row, and whether the lit columns are one run."""
    cols = np.nonzero(mask[row])[0]
    if len(cols) == 0:
        return None
    first, last = int(cols[0]), int(cols[-1])
    return first, last, len(cols) == last - first + 1


def paint_discs(points, radius, colour, frame=None, size=(H, W)):
    """A frame with discs of one pure colour at the points (for the kit's own tests)."""
    h, w = size
    rgb = np.zeros((h, w, 3), dtype=np.uint8) if frame is None else frame
    ys, xs = np.mgrid[0:h, 0:w]
    for px, py in points:
        inside = (xs + 0.5 - px) ** 2 + (ys + 0.5 - py) ** 2 <= radius * radius
        rgb[inside] = 0
        rgb[inside, CHANNEL[colour]] = 255
    return rgb


def paint_bar(frame, rows, x, pixels):
    """A white bar on the rows from column x over `pixels` columns, and a label above it."""
    r0, r1 = rows
    end = int(round(x + pixels))
    frame[r0:r1, x:end] = 255
    frame[r0 - 18:r0 - 6, x:x + 20] = 255
    return frame


def diagnostic_code(line):
    """The bracketed code of an engine's diagnostic ("error[SC1] …" gives "SC1"), else its first 60 characters."""
    m = re.search(r"\[([A-Za-z0-9]+)\]", line)
    return m.group(1) if m else line[:60]


def identical(a, b):
    return a.shape == b.shape and bool(np.array_equal(a, b))


def _r(v, n=3):
    return round(float(v), n)


# ------------------------------------------------------------------------------------ measuring


def measure(name, frames, exp, stats=None, refusals=None):
    """Measure one case from its frames (arrays by "key@frame"), the engine's stats (by the same key) and the
    refusals of the invalid documents (first diagnostic line by key, None when rendered); returns the readings
    with "pass"."""
    if name not in NAMES:
        raise ValueError(name)
    e = exp[name]
    stats = stats or {}
    if name == "scale-depth":
        rgb = frames["scale-depth@0"]
        green = int(pure(rgb, "green").sum())
        red = pure(rgb, "red")
        fill, drawn = 1.0, 0
        for k in DEPTH_DECADES:
            inside, count = window(red, depth_slots()[k], DEPTH_WINDOW_PX)
            fill = min(fill, float(inside.sum()) / count)
            drawn += int(inside.any())
        return {"pass": green == 0 and fill == 1.0 and drawn == len(DEPTH_DECADES),
                "decades": drawn, "farther_pixels": green, "worst_window_fill": _r(fill)}
    if name == "scale-depth-log":
        a, b = frames["scale-depth@0"], frames["scale-depth-log@0"]
        worst = float(np.abs(a - b).max()) if a.shape == b.shape else math.inf
        red = pure(b, "red")
        drawn = sum(int(window(red, depth_slots()[k], DEPTH_WINDOW_PX)[0].all()) for k in DEPTH_DECADES)
        green = int(pure(b, "green").sum())
        return {"pass": worst <= LOG_LEVEL_TOL and drawn == len(DEPTH_DECADES) and green == 0,
                "worst_level": _r(worst, 1), "decades": drawn, "farther_pixels": green}
    if name == "scale-powers":
        radii, centre_ok = {}, 0
        for k, fr in zip(POWERS_DECADES, POWERS_FRAMES):
            rgb = frames[f"scale-powers@{fr}"]
            mask = pure(rgb, PARITY[k % 2])
            radii[fr] = disc_radius(mask)
            centre_ok += int(mask[H // 2, W // 2])
        off = max(abs(radii[fr] - e["pixels"][fr]) for fr in POWERS_FRAMES)
        spread = max(radii.values()) - min(radii.values())
        return {"pass": off <= POWERS_TOL_PX and spread <= POWERS_SPREAD_PX and centre_ok == len(POWERS_FRAMES),
                "radius_px": (_r(min(radii.values()), 2), _r(max(radii.values()), 2)),
                "expected_px": _r(e["pixels"][POWERS_FRAMES[0]], 2), "worst_off_px": _r(off, 2),
                "spread_px": _r(spread, 2), "centre_hits": centre_ok}
    if name in ("scale-bar", "scale-bar-ortho"):
        key = "scale-bar" if name == "scale-bar" else "scale-bar-ortho"
        bars = e["bars"] if name == "scale-bar" else {0: e["bar"]}
        want_measured = "target" if name == "scale-bar" else "orthoHeight"
        r0, r1 = e["rows"]
        ok, labels, worst_rel, worst_run = True, [], 0.0, 0.0
        for fr, want in bars.items():
            reported = stats.get(f"{key}@{fr}") or []
            if len(reported) != 1 or reported[0].get("measured") != want_measured:
                ok = False
                labels.append(f"{fr}: {reported!r}")
                continue
            bar = reported[0]
            rel = abs(bar["pixels"] - want["pixels"]) / want["pixels"]
            worst_rel = max(worst_rel, rel)
            labels.append(f"{fr}: {bar['label']} {_r(bar['pixels'], 2)} px")
            ok &= bar["label"] == want["label"] and rel <= BAR_REL_TOL
            if name == "scale-bar":
                ok &= abs(bar["depth"] - powers_distance(fr)) <= BAR_REL_TOL * powers_distance(fr)
            else:
                ok &= bar["depth"] == ORTHO_HEIGHT
            lit = white(frames[f"{key}@{fr}"])
            for row in range(r0, r1):
                run = run_on_row(lit, row)
                if run is None or run[0] != BAR_X or not run[2]:
                    ok = False
                    continue
                worst_run = max(worst_run, abs(run[1] - (BAR_X + want["pixels"] - 1.0)))
            for row in (r0 - 2, r0 - 1, r1, r1 + 1):
                ok &= not lit[row].any()
        ok &= worst_run <= BAR_RUN_TOL_PX
        return {"pass": ok, "bars": "; ".join(labels), "worst_relative": f"{worst_rel:.1e}",
                "worst_run_end_px": _r(worst_run, 1)}
    if name == "scale-origin":
        def centres(rgb):
            red = pure(rgb, "red")
            left, right = red.copy(), red.copy()
            left[:, W // 2:] = False
            right[:, :W // 2] = False
            return [centroid(left), centroid(right)]
        here = centres(frames["scale-origin-here@0"])
        far = {fr: centres(frames[f"scale-origin-far@{fr}"]) for fr in ORIGIN_FRAMES}
        if any(c is None for c in here) or any(c is None for cs in far.values() for c in cs):
            return {"pass": False, "error": "a sphere is missing"}
        off = max(abs(a - b) for fr in ORIGIN_FRAMES for p, q in zip(here, far[fr]) for a, b in zip(p, q))
        motion = max(abs(a - b) for p, q in zip(far[ORIGIN_FRAMES[0]], far[ORIGIN_FRAMES[1]])
                     for a, b in zip(p, q))
        return {"pass": off <= ORIGIN_TOL_PX and motion <= ORIGIN_MOTION_PX,
                "centres_px": [(_r(x, 2), _r(y, 2)) for x, y in far[ORIGIN_FRAMES[0]]],
                "at_origin_px": [(_r(x, 2), _r(y, 2)) for x, y in here],
                "worst_off_px": _r(off, 2), "motion_px": _r(motion, 3)}
    if name == "scale-seek":
        same = identical(frames["seek-alone"], frames["seek-played"])
        return {"pass": same, "frame": SEEK_FRAMES, "identical": same}
    if name == "scale-invalid":
        refusals = refusals or {}
        lines = {}
        for code in INVALID:
            line = refusals.get(f"scale-invalid-{code}")
            lines[code] = "rendered" if line is None else diagnostic_code(line)
        refused = sum(1 for code in INVALID if refusals.get(f"scale-invalid-{code}") is not None)
        return {"pass": refused == len(INVALID), "refused": refused, **lines}
    raise ValueError(name)


# ------------------------------------------------------------------------------------ running an engine


def _run(cmd, exec):
    r = exec(cmd, capture_output=True, text=True)
    text = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0:
        err = [line for line in text.strip().splitlines() if not line.startswith("warning:")]
        return err[0] if err else f"exit {r.returncode}", text
    return None, text


def _render(engine, doc, png, exec, frame=None, frames=None, stats=False):
    cmd = [engine, "render", doc] + (["--frames", frames] if frames else ["-f", str(frame)]) + ["-o", png]
    if stats:
        cmd.append("--stats")
    return _run(cmd, exec)


def parse_stats(text):
    """The scale bars of each frame from an engine's --stats lines, by frame."""
    out = {}
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and "frame" in d and isinstance(d.get("stats"), dict):
            out[int(d["frame"])] = d["stats"].get("scale_bars", [])
    return out


def plan():
    """What each case renders: (document key, frames, mode) with mode one of "single" (one frame at a time, with
    stats), "sequence" (one run over the frames), "seek" (the last frame alone, then the run) and "refuse"."""
    out = {}
    for name in NAMES:
        if name == "scale-seek":
            out[name] = [("scale-powers", (SEEK_FRAMES,), "seek")]
        elif name == "scale-invalid":
            out[name] = [(key, (0,), "refuse") for key in DOCUMENTS[name]]
        elif name == "scale-origin":
            out[name] = [("scale-origin-here", (0,), "single"), ("scale-origin-far", ORIGIN_FRAMES, "single")]
        else:
            frames = geometry()[name]["frames"]
            out[name] = [(key, tuple(frames), "single") for key in DOCUMENTS[name]]
    return out


def run(engine, out_dir, exec=subprocess.run, only=None):
    """Write the cases, render each document's frames with the engine and measure every case (or those in
    `only`); a case with a document the engine refuses (other than the invalid ones) reports that document's
    first diagnostic line."""
    names = [n for n in NAMES if only is None or n in only]
    exp = expectations()
    paths = write(out_dir)
    report, frames, stats, refusals = {}, {}, {}, {}
    for name in names:
        error = None
        for key, wanted, mode in plan()[name]:
            if mode == "refuse":
                png = os.path.join(out_dir, f"{key}.png")
                refusals[key], _ = _render(engine, paths[key], png, exec, frame=0)
            elif mode == "seek":
                alone = os.path.join(out_dir, f"{key}-alone.png")
                error, _ = _render(engine, paths[key], alone, exec, frame=SEEK_FRAMES)
                if not error:
                    pattern = os.path.join(out_dir, f"{key}-seq-%04d.png")
                    error, _ = _render(engine, paths[key], pattern, exec, frames=f"0..={SEEK_FRAMES}")
                if not error:
                    frames["seek-alone"], frames["seek-played"] = load(alone), load(pattern % SEEK_FRAMES)
            else:
                for f in wanted:
                    if f"{key}@{f}" in frames:
                        continue
                    png = os.path.join(out_dir, f"{key}-f{f}.png")
                    error, text = _render(engine, paths[key], png, exec, frame=f, stats=True)
                    if error:
                        break
                    frames[f"{key}@{f}"] = load(png)
                    stats[f"{key}@{f}"] = parse_stats(text).get(f, [])
            if error:
                error = f"{key}: {error}"
                break
        report[name] = ({"pass": False, "error": error} if error
                        else measure(name, frames, exp, stats=stats, refusals=refusals))
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
    ap.add_argument("--out", default=os.path.join(CONF, "out", "scale-kit"), help="where documents and frames go")
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
