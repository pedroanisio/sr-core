"""Writes the kit cases of the time-frames draft and measures an engine's renders of them.

The draft (srep/srep-0000-time-frames.md, Kit cases) describes nine cases that join conformance/srep_cases/ once
the SREP has a number. `--write DIR` writes them now as srep-0000-space-*.xml, with the ephemeris excerpt copied to
DIR/assets/; `--engine BIN` writes them, renders each with scene-render and measures the frames: the centroid of
the lit pixels against the reference module's place_body, the PSNR between frames of the orientation case, the
seek check of SREP 14, and the refusal (its code in the diagnostics) of the two invalid documents. Every
expectation comes from time_frames_reference.py, none is written here as a number.
"""
import argparse
import math
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import time_frames_reference as tf  # noqa: E402

NAMES = ["space-earth-moon", "space-digest", "space-no-asset", "space-mars", "space-approximate",
         "space-body-fixed", "space-rate", "space-orientation", "space-seek"]
FRAME = {name: (640, 360) for name in NAMES}
FRAME.update({"space-mars": (480, 480), "space-approximate": (480, 480)})
SCALE = {"space-earth-moon": 1e-6, "space-digest": 1e-6, "space-no-asset": 1e-6, "space-mars": 5e-10,
         "space-approximate": 5e-10, "space-body-fixed": 1e-9, "space-rate": 1e-6, "space-orientation": 1e-6,
         "space-seek": 1e-6}
J2000 = "2451545.0"
MARS_EPOCH = "2460977.5"            # inside the excerpt's 2025 window; the `mars error arcsec 2025` row
BODY_FIXED_EPOCH = "2451545.25"     # six hours after J2000: the Earth-fixed frame has turned about 90 degrees
RATE_FRAMES = 48                    # two hours at rate 3600 and 24 fps
SIDEREAL_RATE = "86164.0962"        # one rotation of the Earth in 24 frames at 24 fps
EXCERPT = "assets/de440s-excerpt.bsp"
DIGEST = "sha256:" + tf.EXCERPT_DIGEST
WRONG_DIGEST = DIGEST[:-1] + ("0" if DIGEST[-1] != "0" else "1")
REFUSED = {"space-digest": "TF1", "space-no-asset": "TF5"}
FPS = 24.0
CENTRE_TOL = 1.0
APPROXIMATE_TOL = 2.0
PSNR_SAME = 60.0
PSNR_DIFFERENT = 20.0
BOX = (200.0, 100.0, 50.0)           # the Earth's box: width, height, depth
WIDTH_TOL = 2.0
ORIENTATION_FRAMES = ("0", "6", "24")


def _doc(name, space, objects, duration=1, digest=DIGEST, asset=True):
    w, h = FRAME[name]
    assets = f'<assets><ephemeris id="de440" src="{EXCERPT}" digest="{digest}"/></assets>\n' if asset else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="1.8"><project width="{w}" height="{h}" fps="24" duration="{duration}" background="#000000FF"/>'
            f'<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'{assets}'
            f'<materials><material id="white" baseColor="#FFFFFFFF" unlit="true"/></materials>\n'
            f'<composition><camera id="cam" projection="orthographic" orthoHeight="{h}" x="0" y="0" z="-1000"/>\n'
            f'{objects}\n</composition>\n'
            f'<physics pixelsPerMeter="{SCALE[name]}"/>\n'
            f'<space {space}/></scene>\n')


MOON = '<object3D id="moon" primitive="sphere" radius="8" material="white" body="301" positionFrom="ephemeris"/>'
MARS = '<object3D id="mars" primitive="sphere" radius="8" material="white" body="4" positionFrom="ephemeris"/>'
SUN = '<object3D id="sun" primitive="sphere" radius="8" material="white" body="10" positionFrom="ephemeris"/>'
EARTH = ('<object3D id="earth" primitive="box" width="200" height="100" depth="50" material="white" body="399" '
         'orientation="bodyFixed"/>')


def documents():
    """The nine documents of the draft's kit table, by case name."""
    earth = f'epoch="{J2000}" timeScale="tdb" origin="399" ephemeris="de440"'
    rate = f'epoch="{J2000}" timeScale="tdb" origin="399" rate="3600" ephemeris="de440"'
    return {
        "space-earth-moon": _doc("space-earth-moon", earth, MOON),
        "space-digest": _doc("space-digest", earth, MOON, digest=WRONG_DIGEST),
        "space-no-asset": _doc("space-no-asset", f'epoch="{J2000}" timeScale="tdb" origin="399" ephemeris="de441"',
                               MOON, asset=False),
        "space-mars": _doc("space-mars", f'epoch="{MARS_EPOCH}" timeScale="tdb" origin="10" ephemeris="de440"', MARS),
        "space-approximate": _doc("space-approximate", f'epoch="{MARS_EPOCH}" timeScale="tdb" origin="10"', MARS,
                                  asset=False),
        "space-body-fixed": _doc("space-body-fixed", f'epoch="{BODY_FIXED_EPOCH}" timeScale="tdb" origin="399" '
                                 f'frame="bodyFixed" frameBody="399" ephemeris="de440"', SUN),
        "space-rate": _doc("space-rate", rate, MOON, duration=3),
        "space-orientation": _doc("space-orientation", f'epoch="{J2000}" timeScale="tdb" origin="399" '
                                  f'rate="{SIDEREAL_RATE}" ephemeris="de440"', EARTH, duration=2),
        "space-seek": _doc("space-seek", rate, MOON, duration=3),
    }


def expectations():
    """The reference's pixel positions for each measured case: scene (x, y) at the frame's centre."""
    spk = tf.excerpt()

    def centre(name, sp, body, frame=0):
        w, h = FRAME[name]
        p = tf.place_body(spk, sp, body, frame, FPS, SCALE[name])["position"]
        return (w / 2 + p[0], h / 2 + p[1])
    exp = {}
    exp["space-earth-moon"] = {"centre": centre("space-earth-moon", tf.space(J2000, "tdb", origin=399), 301)}
    exp["space-mars"] = {"centre": centre("space-mars", tf.space(MARS_EPOCH, "tdb", origin=10), 4)}
    exp["space-approximate"] = {"reference": exp["space-mars"]["centre"]}
    exp["space-body-fixed"] = {"centre": centre("space-body-fixed", tf.space(BODY_FIXED_EPOCH, "tdb", origin=399,
                                                                            frame="bodyFixed", frame_body=399), 10)}
    sp = tf.space(J2000, "tdb", rate=3600.0, origin=399)
    c0 = centre("space-rate", sp, 301, 0)
    c1 = centre("space-rate", sp, 301, RATE_FRAMES)
    exp["space-rate"] = {"centre": c0, "arc": (c1[0] - c0[0], c1[1] - c0[1])}
    exp["space-seek"] = {"centre": c0}
    sp = tf.space(J2000, "tdb", rate=float(SIDEREAL_RATE), origin=399)
    exp["space-orientation"] = {"widths": {f: box_width(tf.place_body(spk, sp, 399, int(f), FPS, SCALE["space-orientation"])["orientation"])
                                           for f in ORIENTATION_FRAMES}}
    return exp


def box_width(orientation):
    """The width of the box's silhouette along scene x: its columns are the body axes in scene coordinates, so
    the extent along x is the sum of each half-size times the x component of its axis."""
    return sum(size * abs(orientation[0][k]) for k, size in enumerate(BOX))


# ------------------------------------------------------------------------------------------- measurements


def lit(rgb):
    return rgb.max(axis=2) > 127.0


def centroid(rgb):
    """The centre of the lit pixels in continuous frame coordinates (a pixel i covers [i, i + 1))."""
    ys, xs = np.nonzero(lit(rgb))
    if len(xs) == 0:
        return (math.nan, math.nan)
    return (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5)


def psnr(a, b):
    mse = float(np.mean((a - b) ** 2))
    return math.inf if mse == 0.0 else 10.0 * math.log10(255.0 ** 2 / mse)


def identical(a, b):
    return a.shape == b.shape and bool(np.array_equal(a, b))


def silhouette_width(rgb):
    ys, xs = np.nonzero(lit(rgb))
    return float(xs.max() - xs.min() + 1) if len(xs) else math.nan


def _load(png):
    return np.asarray(Image.open(png).convert("RGB")).astype(float)


def _off(measured, expected):
    return math.dist(measured, expected) if all(map(math.isfinite, measured)) else math.inf


def _r(v):
    return tuple(round(x, 2) for x in v)


def measure(name, pngs, exp):
    """Measure a rendered case: pngs maps the frame label ("0", "48", "seq30"...) to a file."""
    if name in ("space-earth-moon", "space-mars", "space-body-fixed"):
        c = centroid(_load(pngs["0"]))
        off = _off(c, exp[name]["centre"])
        return {"pass": off <= CENTRE_TOL, "centre": _r(c), "off_px": round(off, 3)}
    if name == "space-approximate":
        c = centroid(_load(pngs["0"]))
        off = _off(c, exp[name]["reference"])
        return {"pass": off <= APPROXIMATE_TOL, "centre": _r(c), "off_px": round(off, 3)}
    if name == "space-rate":
        c0 = centroid(_load(pngs["0"]))
        c1 = centroid(_load(pngs[str(RATE_FRAMES)]))
        arc = (c1[0] - c0[0], c1[1] - c0[1])
        off0 = _off(c0, exp[name]["centre"])
        off = _off(arc, exp[name]["arc"])
        return {"pass": off <= CENTRE_TOL and off0 <= CENTRE_TOL, "arc_px": _r(arc), "arc_off_px": round(off, 3),
                "start_off_px": round(off0, 3)}
    if name == "space-orientation":
        f0, f6, f24 = (_load(pngs[k]) for k in ORIENTATION_FRAMES)
        same, different = psnr(f24, f0), psnr(f6, f0)
        widths = {"0": silhouette_width(f0), "6": silhouette_width(f6)}
        width_off = max(abs(widths[f] - exp[name]["widths"][f]) for f in widths)
        return {"pass": same >= PSNR_SAME and different < PSNR_DIFFERENT and width_off <= WIDTH_TOL,
                "psnr_24_vs_0": round(same, 2), "psnr_6_vs_0": round(different, 2),
                "widths_px": (widths["0"], widths["6"]), "width_off_px": round(width_off, 2)}
    if name == "space-seek":
        alone, played = _load(pngs["30"]), _load(pngs["seq30"])
        return {"pass": identical(alone, played), "identical": identical(alone, played)}
    raise ValueError(name)


# ------------------------------------------------------------------------------------------- writing and running


def write(out_dir):
    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
    shutil.copyfile(tf.EXCERPT_PATH, os.path.join(out_dir, "assets", "de440s-excerpt.bsp"))
    paths = {}
    for name, xml in documents().items():
        path = os.path.join(out_dir, f"srep-0000-{name}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        paths[name] = path
    return paths


def _render(engine, doc, png, exec, frame="0", frames=None):
    cmd = [engine, "render", doc] + (["--frames", frames] if frames else ["-f", frame]) + ["-o", png]
    r = exec(cmd, capture_output=True, text=True)
    text = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0:
        err = text.strip().splitlines()
        return err[0] if err else f"exit {r.returncode}", text
    return None, text


FRAMES = {"space-rate": ("0", str(RATE_FRAMES)), "space-orientation": ORIENTATION_FRAMES, "space-seek": ("30",)}


def run(engine, out_dir, exec=subprocess.run):
    """Write the cases, render each with the engine and measure it; a case the engine refuses reports its first
    diagnostic line under "error", and the two documents that must be refused pass only when they are, with
    their code in the diagnostics."""
    exp = expectations()
    report = {}
    for name, doc in write(out_dir).items():
        if name in REFUSED:
            err, text = _render(engine, doc, os.path.join(out_dir, f"{name}.png"), exec)
            code = REFUSED[name]
            report[name] = {"pass": err is not None and code in text, "refused": err is not None,
                            "code": code if code in text else "absent"}
            continue
        pngs = {}
        failed = None
        for frame in FRAMES.get(name, ("0",)):
            png = os.path.join(out_dir, f"{name}-f{frame}.png")
            failed, _ = _render(engine, doc, png, exec, frame=frame)
            if failed:
                break
            pngs[frame] = png
        if not failed and name == "space-seek":
            pattern = os.path.join(out_dir, f"{name}-seq-%04d.png")
            failed, _ = _render(engine, doc, pattern, exec, frames="0..=30")
            pngs["seq30"] = pattern % 30
        if failed:
            report[name] = {"pass": False, "error": failed}
            continue
        report[name] = measure(name, pngs, exp)
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
    ap.add_argument("--out", default=os.path.join(CONF, "out", "time-frames-kit"), help="where documents and frames go")
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
