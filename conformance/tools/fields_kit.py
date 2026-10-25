#!/usr/bin/env python3
"""Writes the kit cases of the draft SREP "Add fields and flow" (srep/srep-0000-fields.md) and measures them
on an engine's render.

  python3 conformance/tools/fields_kit.py --engine BIN [--out DIR]     render the six cases and measure them
  python3 conformance/tools/fields_kit.py --write DIR                   write the documents only

The cases are the rows of the draft's Kit cases table, in order; the draft has no number yet, so they are
written as srep-0000-<case>.xml and join conformance/srep_cases/ when it has one. Each measurement is the
row's check read from the rendered pixels: horizontal line centroids (uniform), arrow directions from the
grid node to the glyph's centroid (vortex, poynting), the distance of the lit pixels from r = C sin²θ
(dipole), the winding of the rendered hue around a circle (portrait) and the spread of each row (lic). The
engine is run as `BIN render DOC -f 0 -o PNG` with the environment as given (set SR_GPU_BACKEND and
SR_GPU_ADAPTER as the kit's run.py does); the vortex case also renders frame 2 alone and frames 0..=2 for
the seek check of SREP 14. The printed table is what the draft's status column records, with the engine's
commit.
"""
import argparse
import colorsys
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)

NAMES = ["field-uniform", "field-vortex", "field-dipole", "field-portrait", "field-lic", "field-poynting"]

# the field box in the frame: x, y, width, height in pixels, then the data ranges
SQUARE = (40, 40, 400, 400, -1.0, 1.0, -1.0, 1.0)
PORTRAIT = (40, 40, 400, 400, -3.0, 3.0, -3.0, 3.0)
WIDE = (40, 40, 400, 200, -2.0, 2.0, -1.0, 1.0)
BOXES = {"field-uniform": SQUARE, "field-vortex": SQUARE, "field-dipole": SQUARE, "field-portrait": PORTRAIT,
         "field-lic": WIDE, "field-poynting": SQUARE}
DIPOLE_C = 0.5                                   # the seed (0.5, 0) on the equator: r = 0.5 sin²θ
DIPOLE_ANGLES = [30.0 + 120.0 * k / 19 for k in range(20)]
POYNTING_WINDOW = [(x, y) for x in (-0.5, -0.25, 0.0, 0.25, 0.5) for y in (-0.25, 0.0, 0.25)]


def _doc(box, field):
    x, y, w, h, x0, x1, y0, y1 = box
    fw, fh = w + 2 * x, h + 2 * y
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="1.8"><project width="{fw}" height="{fh}" fps="24" duration="1" background="#000000FF"/>'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n<composition>\n'
            f'<field id="f" x="{x}" y="{y}" width="{w}" height="{h}" xMin="{x0:g}" xMax="{x1:g}" yMin="{y0:g}" '
            f'yMax="{y1:g}" {field}</field>\n</composition></scene>\n')


def documents():
    """The six case documents, by name, in the order of the draft's table."""
    return {
        "field-uniform": _doc(SQUARE, 'u="1" v="0"><streamlines separation="80"/>'),
        "field-vortex": _doc(SQUARE, 'u="-y" v="x"><arrows cols="5" rows="5" scale="25" maxLength="40"/>'),
        "field-dipole": _doc(SQUARE, '><dipole x="0" y="0" mx="0" my="1"/>'
                                     '<streamlines separation="80" test="10" step="2" maxLines="1" seedX="0.5" seedY="0"/>'),
        "field-portrait": _doc(PORTRAIT, 'kind="complex" w="x - x / (x * x + y * y); y + y / (x * x + y * y)">'
                                         '<portrait modulus="false"/>'),
        "field-lic": _doc(WIDE, 'u="1" v="0"><lic resolution="4" seed="7" length="1000" step="50"/>'),
        "field-poynting": _doc(SQUARE, '><wire x1="-1" y1="0.5" x2="1" y2="0.5" q="1" i="1"/>'
                                       '<wire x1="1" y1="-0.5" x2="-1" y2="-0.5" q="-1" i="1"/>'
                                       '<arrows show="poynting" cols="9" rows="9" scale="4" maxLength="30"/>'),
    }


# ------------------------------------------------------------------------------------------------ measurements

def lit(rgb):
    """The pixels that are drawn: some channel above a quarter (antialiased edges count)."""
    return np.asarray(rgb)[..., :3].max(axis=2) > 64


def _centroid_y(mask, rows):
    ys = np.asarray(rows)
    w = mask[ys].sum(axis=1)
    return round(float((ys * w).sum() / w.sum()) + 0.5, 2)


def row_lines(mask):
    """The centroid y of each horizontal line: a maximal run of consecutive rows with lit pixels."""
    rows = np.nonzero(mask.any(axis=1))[0].tolist()
    out, run = [], []
    for r in rows:
        if run and r != run[-1] + 1:
            out.append(_centroid_y(mask, run))
            run = []
        run.append(r)
    if run:
        out.append(_centroid_y(mask, run))
    return out


def components(mask, min_px=4):
    """The 8-connected components of the lit pixels with at least min_px pixels, each an array of (y, x)."""
    ys, xs = np.nonzero(mask)
    pixels = set(zip(ys.tolist(), xs.tolist()))
    seen, comps = set(), []
    for start in sorted(pixels):
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    q = (y + dy, x + dx)
                    if q in pixels and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if len(comp) >= min_px:
            comps.append(np.array(comp, dtype=np.float64))
    return comps


def arrow_directions(mask, nodes, reach=6.0):
    """For each grid node (pixel x, y), the direction in degrees (y up) of the glyph that starts there (the
    component with a pixel within `reach` of the node): its principal axis, which a lateral offset of the
    rasterized stroke does not turn, pointed from the node toward the glyph's centroid; None without a glyph."""
    comps = components(mask)
    out = []
    for px, py in nodes:
        best, best_d = None, reach
        for c in comps:
            d = float(np.min(np.hypot(c[:, 1] + 0.5 - px, c[:, 0] + 0.5 - py)))
            if d < best_d:
                best, best_d = c, d
        if best is None:
            out.append(None)
            continue
        xs, ys = best[:, 1] + 0.5, -(best[:, 0] + 0.5)              # y up
        cx, cy = xs.mean(), ys.mean()
        cov = np.cov(np.vstack([xs - cx, ys - cy]))
        _, vecs = np.linalg.eigh(cov)
        ax = vecs[:, -1]                                          # the largest eigenvalue's axis
        if ax[0] * (cx - px) + ax[1] * (cy + py) < 0.0:           # toward the centroid from the node
            ax = -ax
        out.append(math.degrees(math.atan2(ax[1], ax[0])))
    return out


def hue_winding(rgb, centre, radius_px, samples=256):
    """The turns of the rendered hue around the circle of radius_px about centre (pixel x, y), traversed
    counterclockwise in data (clockwise on screen): the sum of the wrapped hue differences, rounded."""
    a = np.asarray(rgb)
    hues = []
    for k in range(samples):
        ang = 2.0 * math.pi * k / samples
        x = int(centre[0] + radius_px * math.cos(ang))
        y = int(centre[1] - radius_px * math.sin(ang))
        r, g, b = (float(v) / 255.0 for v in a[y, x, :3])
        hues.append(colorsys.rgb_to_hls(r, g, b)[0])
    total = 0.0
    for k in range(samples):
        d = hues[(k + 1) % samples] - hues[k]
        total += d - round(d)
    return int(round(total))


def row_spread(rgb, box):
    """Within the box (x, y, w, h): the largest max - min of a row's grey values (8-bit) and the number of
    distinct rows."""
    x, y, w, h = box
    region = np.asarray(rgb)[y:y + h, x:x + w, :3].astype(np.int64)
    grey = (region.sum(axis=2) + 1) // 3
    spread = int((grey.max(axis=1) - grey.min(axis=1)).max())
    return spread, int(len(np.unique(region.reshape(h, -1), axis=0)))


def curve_distance(mask, centre, ppu, c, angles_deg):
    """The largest distance in pixels from the points r = c sin²θ (θ from the +y axis, on the +x side) at the
    given angles to the nearest lit pixel."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return math.inf
    px, py = xs + 0.5, ys + 0.5
    worst = 0.0
    for deg in angles_deg:
        th = math.radians(deg)
        r = c * math.sin(th) ** 2
        x = centre[0] + r * math.sin(th) * ppu
        y = centre[1] - r * math.cos(th) * ppu
        worst = max(worst, float(np.min(np.hypot(px - x, py - y))))
    return worst


def _grid(box, cols, rows):
    x, y, w, h, x0, x1, y0, y1 = box
    return [(x + w * i / (cols - 1), y + h * (1 - j / (rows - 1)), x0 + (x1 - x0) * i / (cols - 1),
             y0 + (y1 - y0) * j / (rows - 1)) for j in range(rows) for i in range(cols)]


def measure(name, png, seq_png=None):
    """The draft's check for one case, read from its rendered frame: a dict with "pass" and the values."""
    rgb = np.asarray(Image.open(png).convert("RGB"))
    box = BOXES[name]
    x, y, w, h, x0, x1, y0, y1 = box
    ppu = w / (x1 - x0)
    centre = (x + w / 2.0, y + h / 2.0)
    mask = lit(rgb)
    if name == "field-uniform":
        lines = row_lines(mask)
        gaps = [round(b - a, 2) for a, b in zip(lines, lines[1:])]
        ok = len(lines) == 5 and all(abs(g - 80.0) <= 0.5 for g in gaps)
        return {"pass": ok, "lines": lines, "gaps": gaps}
    if name == "field-vortex":
        nodes = _grid(box, 5, 5)
        angles = arrow_directions(mask, [(px, py) for px, py, _, _ in nodes])
        devs = []
        for (px, py, dx, dy), a in zip(nodes, angles):
            if dx == 0.0 and dy == 0.0:
                continue                                        # F = 0 at the centre: no glyph
            if a is None:
                devs.append(None)
                continue
            radial = math.degrees(math.atan2(dy, dx))
            devs.append(round(abs(((a - radial) % 180.0) - 90.0), 3))
        seek = seq_png is not None and np.array_equal(rgb, np.asarray(Image.open(seq_png).convert("RGB")))
        found = [d for d in devs if d is not None]
        ok = len(found) == 24 and max(found) <= 1.0 and seek
        return {"pass": ok, "arrows": len(found), "worst_deg": max(found) if found else None, "seek": seek}
    if name == "field-dipole":
        worst = curve_distance(mask, centre, ppu, DIPOLE_C, DIPOLE_ANGLES)
        return {"pass": worst < 1.5, "worst_px": round(worst, 3)}
    if name == "field-portrait":
        outer, inner = hue_winding(rgb, centre, 2.0 * ppu), hue_winding(rgb, centre, 0.5 * ppu)
        return {"pass": outer == 1 and inner == -1, "winding_r2": outer, "winding_r05": inner}
    if name == "field-lic":
        spread, distinct = row_spread(rgb, (x, y, w, h))
        return {"pass": spread <= 1 and distinct >= 2, "spread": spread, "distinct_rows": distinct}
    if name == "field-poynting":
        nodes = [n for n in _grid(box, 9, 9) if (round(n[2], 6), round(n[3], 6)) in POYNTING_WINDOW]
        angles = arrow_directions(mask, [(px, py) for px, py, _, _ in nodes])
        found = [abs(((a + 180.0) % 360.0) - 180.0) for a in angles if a is not None]
        ok = len(found) == 15 and max(found) <= 5.0
        return {"pass": ok, "arrows": len(found), "worst_deg": round(max(found), 3) if found else None}
    raise ValueError(name)


# ------------------------------------------------------------------------------------------------ the engine

def write(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for name, xml in documents().items():
        paths[name] = os.path.join(out_dir, f"srep-0000-{name}.xml")
        with open(paths[name], "w", encoding="utf-8") as f:
            f.write(xml)
    return paths


def _render(engine, doc, png, exec, frame="0", frames=None):
    cmd = [engine, "render", doc] + (["--frames", frames] if frames else ["-f", frame]) + ["-o", png]
    r = exec(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip().splitlines()
        return err[0] if err else f"exit {r.returncode}"
    return None


def run(engine, out_dir, exec=subprocess.run):
    """Write the cases, render each with the engine and measure it; a case the engine refuses reports its
    first diagnostic line under "error"."""
    report = {}
    for name, doc in write(out_dir).items():
        png = os.path.join(out_dir, f"{name}.png")
        err = _render(engine, doc, png, exec)
        if err:
            report[name] = {"pass": False, "error": err}
            continue
        seq = None
        if name == "field-vortex":
            alone = os.path.join(out_dir, f"{name}-f2.png")
            pattern = os.path.join(out_dir, f"{name}-seq-%04d.png")
            err = _render(engine, doc, alone, exec, frame="2") or _render(engine, doc, pattern, exec, frames="0..=2")
            if err:
                report[name] = {"pass": False, "error": err}
                continue
            png, seq = alone, pattern % 2
        report[name] = measure(name, png, seq)
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
    ap.add_argument("--out", default=os.path.join(CONF, "out", "fields-kit"), help="where documents and frames go")
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
