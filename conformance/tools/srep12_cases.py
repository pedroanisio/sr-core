#!/usr/bin/env python3
"""Writes the probe scenes of SREP 12's benchmark catalogue (Appendix A) to srep_cases/srep-0012.json, one case per
shot, and the two data assets they read (srep_cases/assets/srep12-track.json, srep12-wind.geojson).

SHOTS is the catalogue: one entry per row of Appendix A with the channel, video, shot and track as the SREP states
them, the status the SREP estimated before milestone 0, the technique the probe exercises, and either `custom` (the
probe reaches the shot only with work done outside the document: motion keyed by hand, hand-built geometry or
hand-written expressions standing in for a computation) or `gap` (no element of schema 1.7 states the shot's defining
content; the probe holds the part that is expressible). A shot with neither flag is native when its probe is:
conformance/catalogue.py scores the probes on an engine (strict render, pixel checks, the seek check of SREP 14).

Every probe is a 640 x 360, 24 fps, 2 s document. Its pixel checks are the kit's forms (run.py): colour classes with
exact centroids where the geometry fixes them, regions, absent, and coverage (the fraction of a box in a colour class)
where a simulation or a 3D render fixes only where content must appear. The checks are the shot's own demands at
frame 0; the seek check compares frame `seek_frame` rendered alone with the same frame rendered from the start.
Usage: python3 conformance/tools/srep12_cases.py; then python3 conformance/make_cases.py."""
import json
import math
import os

import kit_pending  # which cases are pending (SREP 0)

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)
W, H = 640, 360
FPS = 24
DURATION = 2
D = (W / 2) / math.tan(math.radians(30))          # implicit camera distance (CONVENTIONS 2.2)
SEEK_FRAME = 12                                    # 0.5 s: motion is under way in every probe

MATERIALS = ('<materials>'
             '<material id="m-red" baseColor="#FF0000FF" unlit="true" doubleSided="true"/>'
             '<material id="m-green" baseColor="#00FF00FF" unlit="true" doubleSided="true"/>'
             '<material id="m-blue" baseColor="#0000FFFF" unlit="true" doubleSided="true"/>'
             '<material id="m-yellow" baseColor="#FFFF00FF" unlit="true" doubleSided="true"/>'
             '<material id="m-white" baseColor="#FFFFFFFF" unlit="true" doubleSided="true"/>'
             '<material id="m-grey" baseColor="#808080FF" unlit="true" doubleSided="true"/>'
             '</materials>\n')
FONT = '<font id="f" src="../assets/srep-test-font.ttf" family="SREPTest"/>'
CLIP = '<video id="clip" src="../assets/srep82-tone-500.mkv" width="64" height="36" fps="25" duration="2.2"/>'
PLATE = '<layer id="plate" asset="clip" fit="fill" boxWidth="640" boxHeight="360" x="0" y="0"/>'
PLATE_BLACK = [{"box": [20, 300, 60, 340], "rgb": [0, 0, 0]}]     # the clip is black; the background is not


def doc(body, assets="", lights="", effects="", background="#000000FF", version="1.7", paints="", tracking="",
        physics=""):
    assets = f"<assets>{assets}</assets>\n" if assets else ""
    effects = f"<effects>{effects}</effects>\n" if effects else ""
    paints = f"<paints>{paints}</paints>\n" if paints else ""
    tracking = f"<tracking>{tracking}</tracking>\n" if tracking else ""
    physics = f"<physics>{physics}</physics>\n" if physics else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scene version="{version}">\n'
            f'<project width="{W}" height="{H}" fps="{FPS}" duration="{DURATION}" background="{background}" seed="1"/>\n'
            '<output id="still" path="out/frame_%04d.png" codec="png-sequence"/>\n'
            f'{assets}{paints}{MATERIALS}{tracking}<composition>\n{body}\n</composition>\n{lights}{effects}{physics}</scene>\n')


def keys(prop, *tv, curve=None):
    c = f' interpolation="{curve}"' if curve else ""
    return (f'<animate property="{prop}">' + "".join(f'<key time="{t}" value="{v}"{c}/>' for t, v in tv) + '</animate>')


def rect(i, x, y, w, h, fill, extra="", inner=""):
    return f'<shape id="{i}" shape="rect" x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"{extra}>{inner}</shape>'


def ellipse(i, cx, cy, w, h, fill, extra="", inner=""):
    return (f'<shape id="{i}" shape="ellipse" x="{cx - w / 2:g}" y="{cy - h / 2:g}" width="{w}" height="{h}" '
            f'fill="{fill}"{extra}>{inner}</shape>')


def path(i, d, fill="#00000000", stroke=None, width=0, extra="", inner=""):
    s = f' stroke="{stroke}" strokeWidth="{width}"' if stroke else ""
    return (f'<shape id="{i}" shape="path" path="{d}" width="{W}" height="{H}" fill="{fill}"{s}{extra}>{inner}'
            '</shape>')


def rects_check(*boxes):
    """Centroid, bounding box and pixel count of the union of axis-aligned rectangles (x, y, w, h) of one colour."""
    a = sum(w * h for _, _, w, h in boxes)
    cx = sum((x + w / 2) * w * h for x, y, w, h in boxes) / a
    cy = sum((y + h / 2) * w * h for x, y, w, h in boxes) / a
    x0, y0 = min(x for x, _, _, _ in boxes), min(y for _, y, _, _ in boxes)
    x1, y1 = max(x + w for x, _, w, _ in boxes), max(y + h for _, y, _, h in boxes)
    return {"cx": round(cx, 2), "cy": round(cy, 2), "w": x1 - x0, "h": y1 - y0, "px": a}


def ellipses_check(*discs):
    """Centroid and bounding box of discs (cx, cy, w, h) of one colour; the pixel count is not stated."""
    a = sum(w * h for _, _, w, h in discs)
    return {"cx": round(sum(cx * w * h for cx, _, w, h in discs) / a, 2),
            "cy": round(sum(cy * w * h for _, cy, w, h in discs) / a, 2),
            "w": max(cx + w / 2 for cx, _, w, _ in discs) - min(cx - w / 2 for cx, _, w, _ in discs),
            "h": max(cy + h / 2 for _, cy, _, h in discs) - min(cy - h / 2 for _, cy, _, h in discs)}


def no_px(check):
    """A colour check without its pixel count: for a shape whose edges are antialiased or partly covered."""
    return {k: v for k, v in check.items() if k != "px"}


def cover(colour, box, lo=None, hi=None):
    c = {"colour": colour, "box": list(box)}
    if lo is not None:
        c["min"] = lo
    if hi is not None:
        c["max"] = hi
    return c


def sphere_w(r, z=0.0):
    """Image diameter of a sphere of radius r centred at depth z under the implicit camera."""
    d = D + z
    return round(2 * d * r / math.sqrt(d * d - r * r), 1)


def disc3d(i, cx, cy, r, material, z=0):
    return f'<object3D id="{i}" primitive="sphere" radius="{r}" x="{cx}" y="{cy}" z="{z}" material="{material}"/>'


TRACK = {"fps": 24, "points": {"pulse": [[0, 8, 18], [24, 56, 18], [48, 8, 18]],
                               "boat": [[0, 32, 18], [48, 48, 24]]}}
WIND = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "North", "capacity": 320},
     "geometry": {"type": "Point", "coordinates": [-2.0, 52.0]}},
    {"type": "Feature", "properties": {"name": "West", "capacity": 180},
     "geometry": {"type": "Point", "coordinates": [-6.0, 47.0]}},
    {"type": "Feature", "properties": {"name": "East", "capacity": 450},
     "geometry": {"type": "Point", "coordinates": [6.0, 49.0]}},
    {"type": "Feature", "properties": {"name": "link", "capacity": 0},
     "geometry": {"type": "LineString", "coordinates": [[-6.0, 47.0], [-2.0, 52.0], [6.0, 49.0]]}}]}


# ---- the catalogue: one entry per row of SREP 12 Appendix A (channel, video, url, shot and track as the SREP states them)

def shot(n, slug, channel, video, url, shot, track, estimate, technique, xml, expected, custom=None, gap=None,
         seek_frame=SEEK_FRAME, check_frame=0):
    """One catalogue row. `check_frame` is the frame the strict render and the pixel checks look at (0 unless the
    probe's content needs time to appear, as particles do); `seek_frame` is the frame of the seek check."""
    s = {"n": n, "slug": slug, "channel": channel, "video": video, "url": url, "shot": shot, "track": track,
         "estimate": estimate, "technique": technique, "seek_frame": seek_frame, "check_frame": check_frame,
         "xml": xml, "expected": expected}
    if custom:
        s["custom"] = custom
    if gap:
        s["gap"] = gap
    return s


def build():
    S = []
    yt = "https://www.youtube.com/watch?v="

    # 1 Veritasium: footage with a tracked plate, a glowing pulse on the track, clock overlay
    track = '<trackData id="trk" src="../assets/srep12-track.json" kind="point" footage="clip"/>'
    clock = '<text id="clock" text="0" width="200" height="60" size="40" fontAsset="f" color="#FFFFFFFF"/>'
    body = (PLATE +
            ellipse("pulse", 12, 12, 24, 24, "#FF0000FF", ' anchorX="12" anchorY="12" effects="glow"',
                    '<transformConstraint type="track" target="trk" point="pulse"/>') +
            rect("mirror", 560, 150, 10, 60, "#0000FFFF") +
            '<layer id="hud" asset="clock" x="20" y="20"><textAnimator preset="counter" presetStart="0" presetDuration="2"/></layer>')
    S.append(shot(1, "light-pulse-on-footage", "Veritasium", "Why No One Has Measured The Speed Of Light",
                  yt + "pTn6Ewhb27k",
                  "presenter on location with a glowing light pulse drawn into the tracked plate, travelling to a "
                  "mirror and back, with clock overlays",
                  "Footage (LA1 computes the track)", "native",
                  "video layer, point track from a JSON file mapped through the footage layer, track constraint, "
                  "glow effect, counter text animator",
                  doc(body, assets=CLIP + FONT + clock, tracking=track, background="#303030FF",
                      effects='<effect id="glow" type="glow" radius="12" intensity="1"/>'),
                  {"regions": PLATE_BLACK, "red": {"cx": 80, "cy": 180}, "blue": rects_check((560, 150, 10, 60))}))

    # 2 Veritasium: wire loop, bulb, switch; field arrows spreading (gap: no field element)
    arrows = "".join(f'<shape id="a{k}" shape="polygon" points="3" x="{x}" y="{y}" width="14" height="14" fill="#00FF00FF" '
                     f'start="{0.5 + 0.1 * k}"/>' for k, (x, y) in enumerate([(300, 110), (340, 110), (300, 230), (340, 230),
                                                                               (260, 140), (380, 140), (260, 200), (380, 200)]))
    body = (path("wire", "M80 120 H560 V240 H80 Z", stroke="#FFFFFFFF", width="4") +
            ellipse("bulb", 112, 182, 24, 24, "#FFFF00FF") +
            rect("switch", 520, 180, 40, 6, "#FF0000FF", ' anchorX="0" anchorY="3"', keys("rotation", (0, 0), (0.5, -30))) +
            arrows)
    S.append(shot(2, "wire-loop-fields", "Veritasium", "The Big Misconception About Electricity", yt + "bHIhgxav9LY",
                  "a long wire loop with bulb and switch; when the switch closes, E, B and Poynting-vector arrows "
                  "spread through the space around the wires", "Math and fields (MF5)", "gap",
                  "path, ellipse, keyed rotation; the field arrows are hand-placed polygons with staggered starts",
                  doc(body),
                  {"yellow": ellipses_check((112, 182, 24, 24)), "red": rects_check((520, 177, 40, 6)), "absent": ["green"]},
                  gap="no field element draws E, B and Poynting vectors from a source current (MF5); the arrows are "
                      "hand-placed polygons"))

    # 3 Veritasium: T-handle flipping in zero g (custom: the flip is keyed)
    bar = (f'<object3D id="bar" primitive="box" width="160" height="30" depth="4" x="320" y="180" z="0" material="m-red">'
           + keys("rotationY", (0, 0), (0.5, 180), (1, 360)) + keys("rotationX", (0, 0), (1, 180), (2, 0)) + '</object3D>')
    stem = (f'<object3D id="stem" primitive="box" width="20" height="60" depth="4" x="320" y="225" z="0" material="m-green">'
            + keys("rotationY", (0, 0), (0.5, 180), (1, 360)) + '</object3D>')
    axes = ('<object3D id="ax" primitive="box" width="240" height="2" depth="2" x="320" y="180" z="-3" material="m-blue"/>'
            '<object3D id="ay" primitive="box" width="2" height="150" depth="2" x="320" y="180" z="-3" material="m-yellow"/>')
    k = D / (D - 2)
    S.append(shot(3, "t-handle-flip", "Veritasium", "The Bizarre Behavior of Rotating Bodies, Explained", yt + "1VPfZ_XzisU",
                  "a 3D T-handle spinning in zero g flips periodically, principal axes drawn on it",
                  "3D simulation (SREP 11 rigid bodies; S-track)", "custom",
                  "3D boxes under the implicit camera with keyed rotationX and rotationY",
                  doc(bar + stem + axes),
                  {"red": {"cx": 320, "cy": 180, "w": round(160 * k, 1), "h": round(30 * k, 1)},
                   "green": {"cx": 320, "cy": 225, "w": round(20 * k, 1), "h": round(60 * k, 1)}},
                  custom="the flip is keyed by hand: rigidBody has an initial angularVelocity in 2D only and no 3D "
                         "inertia tensor (SREP 11 S-track would simulate it)"))

    # 4 Veritasium: worldlines on a curved sheet, camera orbiting (custom: hand-written surfaces)
    sheet = ('<object3D id="sheet" primitive="parametric" x="320" y="200" z="0" material="m-green">'
             '<parametricSurface x="u" y="30 * Math.exp(-(u * u + v * v) / 20000)" z="v" u0="-200" u1="200" v0="-150" v1="150" '
             'uSamples="40" vSamples="30"/></object3D>')
    ribbon = ('<object3D id="apple" primitive="parametric" x="320" y="196" z="0" material="m-red">'
              '<parametricSurface x="u" y="30 * Math.exp(-(u * u) / 20000) + v" z="60" u0="-200" u1="200" v0="-3" v1="3" '
              'uSamples="40" vSamples="2"/></object3D>')
    cam = (f'<camera id="orbit" x="320" y="60" z="{-D:.3f}" target="sheet">' + keys("x", (0, 320), (1, 320 + 300), (2, 320)) +
           keys("z", (0, round(-D, 3)), (1, round(-D + 120, 3)), (2, round(-D, 3))) + '</camera>')
    S.append(shot(4, "curved-spacetime-sheet", "Veritasium", "Why Gravity is NOT a Force", yt + "XRr1kaXKBsU",
                  "worldlines of a falling apple and the ground as straight paths on a curved spacetime sheet, camera "
                  "orbiting", "Space (SP6)", "gap",
                  "parametric surfaces (a sheet and a thin ribbon for the worldline), a camera with a target and keyed "
                  "position",
                  doc(sheet + ribbon + cam),
                  {"coverage": [cover("green", (120, 100, 520, 300), lo=0.3), cover("red", (120, 100, 520, 300), lo=0.002)]},
                  custom="the sheet and the worldline are hand-written parametric surfaces; SP6 would derive them "
                         "from the metric and integrate the geodesics"))

    # 5 Veritasium: Einstein-solid lattice with hopping packets (custom: hops keyed by hand)
    lattice = ('<repeat id="lattice" x="320" y="180"><points type="grid" columns="5" rows="3" spacingX="60" spacingY="60"/>'
               '<shape id="atom" shape="ellipse" x="-10" y="-10" width="20" height="20" fill="#0000FFFF"/></repeat>')
    hops = [(260, 180), (320, 180), (320, 120), (380, 120), (380, 180)]
    packet = ellipse("packet", 0, 0, 16, 16, "#FF0000FF", "",
                     keys("x", *[(0.4 * i, x - 8) for i, (x, _) in enumerate(hops)], curve="hold") +
                     keys("y", *[(0.4 * i, y - 8) for i, (_, y) in enumerate(hops)], curve="hold"))
    S.append(shot(5, "einstein-solid-packets", "Veritasium", "The Most Misunderstood Concept in Physics", yt + "DxL2HoqLbyA",
                  "an Einstein-solid lattice of atoms with energy packets hopping between them and slowly spreading out",
                  "Math and fields (MF4 with F1 random streams)", "custom",
                  "a repeat over a grid of points, a packet with hold-keyed position",
                  doc(lattice + packet),
                  {"blue": {"w": 260, "h": 140}, "red": ellipses_check((260, 180, 16, 16))},
                  custom="the hops are keyed by hand; MF4 with F1 (seeded random streams) would draw them in the "
                         "document"))

    # 6 Veritasium: boat through shade balls with callouts following the track
    body = (PLATE +
            ellipse("boat", 10, 10, 20, 20, "#FF0000FF", ' anchorX="10" anchorY="10"', '<transformConstraint type="track" target="trk" point="boat"/>') +
            rect("callout", 400, 60, 120, 30, "#FFFF00FF") +
            '<connector id="lead" from="callout" to="boat" stroke="#FFFFFFFF" strokeWidth="2"/>')
    S.append(shot(6, "shade-balls-callouts", "Veritasium", "Why Are 96,000,000 Black Balls on This Reservoir?", yt + "uxPdPpi5W4o",
                  "a boat moving through the shade-ball carpet, with callouts following the tracked footage",
                  "Footage (LA1 computes the track)", "native",
                  "video layer, point track mapped through the footage layer, a connector from a callout to the tracked "
                  "node",
                  doc(body, assets=CLIP, tracking=track, background="#303030FF"),
                  {"regions": PLATE_BLACK, "red": {"cx": 320, "cy": 180}, "yellow": rects_check((400, 60, 120, 30))}))

    # 7 Veritasium: Penrose diagram turning into a wormhole render (gap: no wormhole)
    diagram = (path("diamond", "M320 40 L460 180 L320 320 L180 180 Z", stroke="#FFFFFFFF", width="3") +
               rect("singularity", 240, 60, 160, 8, "#0000FFFF") +
               path("horizon", "M180 180 L320 40", stroke="#FFFFFFFF", width="2", extra=' dash="8 6"') +
               rect("label", 470, 172, 16, 16, "#FF0000FF"))
    hole = ('<group id="bridge" x="0" y="0" start="1">'
            f'<camera id="eye" x="320" y="180" z="-300" geodesics="true"/>'
            '<blackHole id="hole" mass="8" x="320" y="180" z="0"/>'
            '<accretionDisk id="disk" blackHole="hole" outerRadius="90" temperatureScale="5000" rotationX="70"/></group>')
    S.append(shot(7, "penrose-to-wormhole", "Veritasium", "Something Strange Happens When You Follow Einstein's Math", yt + "6akmv1bsz1M",
                  "a Penrose diagram of the extended black hole that turns into a 3D wormhole render",
                  "Space (SP6) and light (SP7)", "gap",
                  "paths and rects for the diagram; a geodesic camera with one black hole from 1 s",
                  doc(diagram + hole),
                  {"blue": no_px(rects_check((240, 60, 160, 8))), "red": rects_check((470, 172, 16, 16))},
                  gap="no wormhole: the geodesic camera renders one Schwarzschild hole (blackHole), not an "
                      "Einstein-Rosen bridge (SP6, SP7)"))

    # 8 3Blue1Brown: pixels flatten into neurons, layers light up through weighted connections
    pixels = ('<repeat id="pixels" x="100" y="180"><points type="grid" columns="8" rows="8" spacingX="12" spacingY="12"/>'
              '<shape id="px" shape="rect" x="-5" y="-5" width="10" height="10" fill="#FFFFFFFF"/></repeat>')

    def column(i, x, n, spacing, fill):
        return (f'<repeat id="{i}" x="{x}" y="180"><points type="grid" columns="1" rows="{n}" spacingY="{spacing}"/>'
                f'<shape id="{i}-n" shape="ellipse" x="-8" y="-8" width="16" height="16" fill="{fill}">'
                + keys("opacity", (0, 0.4), (1, 1)) + '</shape></repeat>')
    links = "".join(f'<connector id="l{k}" fromX="258" fromY="{75 + 30 * k}" toX="372" toY="{90 + 36 * k}" stroke="#FFFFFFFF" strokeWidth="1"/>'
                    for k in range(5))
    body = pixels + column("in", 250, 8, 30, "#0000FFFF") + column("hid", 380, 6, 36, "#00FF00FF") + column("out", 510, 4, 50, "#FF0000FF") + links
    S.append(shot(8, "neural-network-layers", "3Blue1Brown", "But what is a neural network?", yt + "aircAruvnKk",
                  "28×28 digit pixels flatten into a column of neurons; layers light up with weighted connections", "—", "native",
                  "repeats over point grids, connectors between nodes, keyed opacity",
                  doc(body),
                  {"blue": {"cx": 250, "cy": 180, "w": 16, "h": 7 * 30 + 16}, "green": {"cx": 380, "cy": 180, "w": 16, "h": 5 * 36 + 16},
                   "red": {"cx": 510, "cy": 180, "w": 16, "h": 3 * 50 + 16}}))

    # 9 3Blue1Brown: a signal wound around a circle as the frequency sweeps (custom: the centre of mass is hand-written)
    winding = ('<shape id="wind" shape="parametric" x="0" y="0" fill="#00000000" stroke="#FFFF00FF" strokeWidth="2">'
               '<parametricPath x="160 + 40 * (1 + Math.cos(3 * t)) * Math.cos((1 + time) * t)" '
               'y="180 + 40 * (1 + Math.cos(3 * t)) * Math.sin((1 + time) * t)" t0="0" t1="12.566370614359172" samples="600"/></shape>')
    plot = ('<shape id="plot" shape="parametric" x="0" y="0" fill="#00000000" stroke="#FFFFFFFF" strokeWidth="2">'
            '<parametricPath x="360 + 60 * t" y="300 - 100 * Math.exp(-((t - 3) * (t - 3)) / 0.5)" t0="0" t1="4" samples="200"/></shape>')
    com = ellipse("com", 0, 0, 12, 12, "#FF0000FF", "", keys("x", (0, 160 - 6), (2, 200 - 6)) + keys("y", (0, 180 - 6), (2, 180 - 6)))
    S.append(shot(9, "fourier-winding", "3Blue1Brown", "But what is the Fourier Transform? A visual introduction.", yt + "spUNpyF58BY",
                  "a signal wound around a circle as the winding frequency sweeps, its centre of mass tracing the "
                  "transform plot", "Math and fields (MF1, MF4)", "gap",
                  "parametric paths whose expressions read time (the winding frequency sweeps), a keyed marker",
                  doc(winding + plot + com),
                  {"coverage": [cover("yellow", (60, 80, 260, 280), lo=0.02)], "red": ellipses_check((160, 180, 12, 12))},
                  custom="the centre of mass and the transform plot are hand-written expressions; MF4 would "
                         "integrate them from the winding in the document"))

    # 10 3Blue1Brown: the grid under a matrix, basis vectors following, entries shown
    grid = "".join(f'<shape id="g{k}" shape="rect" x="{-200 + 40 * k}" y="-200" width="1" height="400" fill="#FFFFFF66"/>'
                   f'<shape id="h{k}" shape="rect" x="-200" y="{-200 + 40 * k}" width="400" height="1" fill="#FFFFFF66"/>' for k in range(11))
    space = ('<group id="space" x="320" y="180">' + keys("skewX", (0, 0), (1, 30)) + keys("rotation", (0, 0), (1, 20)) + grid +
             rect("ihat", 0, -2, 60, 4, "#FF0000FF") + rect("jhat", -2, -60, 4, 60, "#00FF00FF") + '</group>')
    matrix = r'<formula id="mat" tex="\begin{pmatrix} 1 &amp; 0 \\ 0 &amp; 1 \end{pmatrix}" width="160" height="80" size="36"/>'
    S.append(shot(10, "matrix-transformation", "3Blue1Brown", "Linear transformations and matrices", yt + "kYB8IZa5AuE",
                  "the 2D grid shears and rotates under a matrix while the basis vectors follow, matrix entries shown",
                  "Math and fields (MF2, MF3 improve it)", "native",
                  "a group with keyed skew and rotation over a grid of rects, a TeX matrix formula asset",
                  doc(space + '<layer id="entries" asset="mat" x="470" y="20"/>', assets=matrix),
                  {"red": no_px(rects_check((320, 178, 60, 4))), "green": no_px(rects_check((318, 120, 4, 60))),
                   "coverage": [cover("lit", (470, 20, 630, 100), lo=0.01)]}))

    # 11 3Blue1Brown: stereographic projection of the hypersphere (gap: no projection of curves)
    body = (disc3d("ball", 320, 150, 70, "m-blue") +
            '<object3D id="ring" primitive="torus" radius="60" x="320" y="150" z="-40" rotationX="60" material="m-red"/>'
            '<object3D id="plane" primitive="plane" width="400" height="60" x="320" y="300" z="0" material="m-green"/>')
    S.append(shot(11, "stereographic-projection", "3Blue1Brown", "Visualizing quaternions (4d numbers) with stereographic projection", yt + "d4EgbgTm0Bg",
                  "stereographic projection of the hypersphere: circles and spheres pass through the pole and blow up to "
                  "infinity", "Math and fields (MF2)", "gap",
                  "an unlit sphere, a torus and a plane under the implicit camera",
                  doc(body),
                  {"blue": {"cx": 320}, "green": {"cx": 320, "cy": 300, "w": 400, "h": 60},
                   "coverage": [cover("red", (200, 60, 440, 240), lo=0.005)]},
                  gap="no projection of curves on the hypersphere onto 3-space or the plane (MF2); the sphere, a ring "
                      "and the plane draw, the projected circle cannot"))

    # 12 3Blue1Brown: a vector field with tracer particles from a source and around a curl point (custom: preset fields)
    emitter = ('<particleEmitter id="src" x="200" y="180" rate="150" lifetime="3" speed="60" direction="0" spread="360" '
               'size="5" color="#FF0000FF" seed="3"><burst time="0" count="300"/></particleEmitter>')
    swirl = '<forceField id="curl" type="vortex" x="440" y="180" strength="40" radius="3" affects="particles"/>'
    arrows = "".join(f'<shape id="v{k}" shape="polygon" points="3" x="{x}" y="{y}" width="12" height="12" fill="#00FF00FF" rotation="{r}"/>'
                     for k, (x, y, r) in enumerate([(140, 100, -45), (260, 100, 45), (140, 260, -135), (260, 260, 135)]))
    S.append(shot(12, "divergence-curl-particles", "3Blue1Brown", "Divergence and curl", yt + "rB83DpBJQsE",
                  "a 2D vector field with tracer particles pouring out of sources and swirling around curl points",
                  "Math and fields (MF5)", "custom",
                  "a particle emitter with a burst at 0, a vortex force field, hand-placed arrows",
                  doc(emitter + arrows, physics=swirl),
                  {"coverage": [cover("red", (150, 130, 250, 230), lo=0.02)], "green": {"cx": 200, "cy": 180}},
                  check_frame=SEEK_FRAME,
                  custom="the field is a vortex preset and the arrows are hand-placed; MF5 would draw the field of a "
                         "formula and advect tracers through it"))

    # 13 PBS Space Time: light cones on a spacetime diagram
    body = (rect("taxis", 318, 40, 4, 280, "#FFFFFFFF") + rect("xaxis", 100, 178, 440, 4, "#FFFFFFFF") +
            path("future", "M320 180 L200 60 L440 60 Z", fill="#FFFF00FF") +
            path("past", "M320 180 L200 300 L440 300 Z", fill="#0000FFFF") +
            ellipse("event", 320, 180, 12, 12, "#FF0000FF") + ellipse("other", 450, 110, 12, 12, "#00FF00FF"))
    S.append(shot(13, "light-cones", "PBS Space Time", "The Speed of Light is NOT About Light", yt + "msVuCEs8Ydo",
                  "light cones on a spacetime diagram with events and causal regions", "—", "native",
                  "filled paths, rects and ellipses",
                  doc(body),
                  {"yellow": {"cx": 320, "cy": 100, "w": 240}, "blue": {"cx": 320, "cy": 260, "w": 240},
                   "red": ellipses_check((320, 180, 12, 12)), "green": ellipses_check((450, 110, 12, 12))}))

    # 14 PBS Space Time: falling toward a black hole (gap: no redshift of the infalling object)
    fall = (f'<camera id="eye" x="320" y="180" z="-600" geodesics="true">' + keys("z", (0, -600), (2, -250)) + '</camera>'
            '<blackHole id="hole" mass="10" x="320" y="180" z="0"/>'
            '<accretionDisk id="disk" blackHole="hole" outerRadius="120" temperatureScale="5000" rotationX="75" seed="2"/>')
    S.append(shot(14, "event-horizon-fall", "PBS Space Time", "What Happens at the Event Horizon?", yt + "mht-1c4wc0Q",
                  "an observer falls toward a black hole: starfield distortion and redshift of the infalling object",
                  "Light and volumes (SP7)", "gap",
                  "a geodesic camera with keyed position, a black hole with an accretion disk and its starfield",
                  doc(fall),
                  {"coverage": [cover("lit", (0, 0, 640, 360), lo=0.02), cover("dark", (310, 170, 330, 190), lo=0.9)]},
                  gap="no redshift or blueshift of an infalling source (SP7); the lensed starfield and the disk render"))

    # 15 PBS Space Time: double slit (gap: no wave propagation, no sampled hits)
    barrier = (rect("b1", 300, 60, 8, 80, "#0000FFFF") + rect("b2", 300, 160, 8, 40, "#0000FFFF") + rect("b3", 300, 220, 8, 80, "#0000FFFF"))
    hits = "".join(f'<shape id="hit{k}" shape="ellipse" x="{500}" y="{y}" width="4" height="4" fill="#FF0000FF" start="{0.2 + 0.1 * k}"/>'
                   for k, y in enumerate([178, 120, 236, 182, 60, 300, 176, 124]))
    body = (ellipse("source", 120, 180, 20, 20, "#FFFF00FF") + barrier + rect("screen", 500, 40, 6, 280, "#808080FF") + hits)
    S.append(shot(15, "double-slit-hits", "PBS Space Time", "The Quantum Experiment that Broke Reality", yt + "p-MNSLsjjdo",
                  "a wave passes a double slit while single-particle hits build an interference pattern dot by dot",
                  "Optics and waves (OW3, OW4)", "gap",
                  "rects and ellipses; the hits are hand-placed with staggered starts",
                  doc(body),
                  {"yellow": ellipses_check((120, 180, 20, 20)), "blue": rects_check((300, 60, 8, 80), (300, 160, 8, 40), (300, 220, 8, 80)),
                   "absent": ["red"]},
                  gap="no wave propagation through the slits (OW3) and no sampled hits from an intensity (OW4); the hits "
                      "are hand-placed"))

    # 16 PBS Space Time: Minkowski space squeezed into a Penrose diamond (custom: hand-written compactification)
    squeeze = "".join(
        f'<shape id="u{k}" shape="parametric" x="0" y="0" fill="#00000000" stroke="#FFFFFFAA" strokeWidth="1">'
        f'<parametricPath x="320 + 120 * ((1 - time / 2) * ({c} / 3) + (time / 2) * (Math.atan(t + {c}) + Math.atan(t - {c})) / 3.1415926)" '
        f'y="180 - 120 * ((1 - time / 2) * (t / 3) + (time / 2) * (Math.atan(t + {c}) - Math.atan(t - {c})) / 3.1415926)" '
        f't0="-3" t1="3" samples="60"/></shape>' for k, c in enumerate([-2, -1, 0, 1, 2]))
    body = (path("diamond", "M320 60 L440 180 L320 300 L200 180 Z", fill="#FFFF00FF") + squeeze +
            path("ray1", "M230 90 L410 270", stroke="#FF0000FF", width="3") + path("ray2", "M410 90 L230 270", stroke="#FF0000FF", width="3"))
    S.append(shot(16, "penrose-diamond", "PBS Space Time", "The Geometry of Causality", yt + "1YFrISfN7jo",
                  "Minkowski space squeezed into a Penrose diamond, light rays at 45°", "Math and fields (MF2)", "gap",
                  "a filled diamond path, parametric grid lines whose expressions read time, 45-degree stroked paths",
                  doc(body),
                  {"yellow": {"cx": 320, "cy": 180, "w": 240, "h": 240}, "red": {"cx": 320, "cy": 180}},
                  custom="the compactification of each grid line is a hand-written expression; MF2 would map the grid"))

    # 17 Kurzgesagt: two figures in a starry void, rim light, parallax star layers
    stars = "".join(f'<repeat id="stars{k}" x="320" y="180" threeD="true" zDepth="{z}">'
                    f'<points type="scatter" count="{n}" width="900" height="500" seed="{k + 1}"/>'
                    f'<shape id="star{k}" shape="ellipse" x="-1.5" y="-1.5" width="3" height="3" fill="#FFFFFFFF"/></repeat>'
                    for k, (z, n) in enumerate([(400, 60), (200, 40), (80, 25)]))
    figures = ellipse("a", 230, 180, 60, 100, "#FF0000FF") + ellipse("b", 410, 180, 60, 100, "#00FF00FF")
    cam = f'<camera id="cam" x="320" y="180" z="{-D:.3f}">' + keys("x", (0, 320), (2, 360)) + '</camera>'
    S.append(shot(17, "figures-in-void", "Kurzgesagt", "The Egg – A Short Story", yt + "h6fcK_fRYaI",
                  "two figures floating in a starry void, flat-shaded with rim light and parallax star layers", "—", "native",
                  "2.5D repeats of scattered points at three depths, a camera with keyed position, flat ellipses",
                  doc(stars + figures + cam),
                  {"red": ellipses_check((230, 180, 60, 100)), "green": ellipses_check((410, 180, 60, 100))}))

    # 18 Kurzgesagt: continuous zoom out, labels changing with scale
    space = ('<group id="scale" x="320" y="180">' + keys("scaleX", (0, 1), (1, 0.1), (2, 0.01)) + keys("scaleY", (0, 1), (1, 0.1), (2, 0.01)) +
             ellipse("betelgeuse", 600, 0, 1000, 1000, "#0000FFFF") + ellipse("sun", 0, 0, 40, 40, "#FFFF00FF") + '</group>')
    labels = ('<text id="l1" text="Sun" width="200" height="40" size="28" fontAsset="f"/>'
              '<text id="l2" text="Betelgeuse" width="300" height="40" size="28" fontAsset="f"/>')
    body = space + '<layer id="n1" asset="l1" x="40" y="300" end="1"/><layer id="n2" asset="l2" x="40" y="300" start="1"/>'
    S.append(shot(18, "star-size-zoom", "Kurzgesagt", "The Largest Star in the Universe – Size Comparison", yt + "3mnSDifDSxQ",
                  "continuous zoom out from the Sun past Betelgeuse to Stephenson 2-18, labels changing with scale", "—", "native",
                  "a group with keyed scale, text layers with start and end",
                  doc(body, assets=FONT + labels),
                  {"yellow": ellipses_check((320, 180, 40, 40)), "coverage": [cover("blue", (400, 0, 640, 360), lo=0.5)]}))

    # 19 Kurzgesagt: macrophages engulfing bacteria
    tissue = rect("tissue", 0, 0, 640, 360, "#402030FF")
    macro = ellipse("macro", 340, 180, 80, 60, "#00FF00FF", "", keys("scaleX", (0, 1), (1, 1.3), (2, 1)) + keys("scaleY", (0, 1), (1, 1.3), (2, 1)))
    bugs = (ellipse("bug1", 200, 120, 16, 16, "#FF0000FF", "", keys("x", (0, 192), (1, 300)) + keys("y", (0, 112), (1, 170)) + keys("scaleX", (1, 1), (1.5, 0)) + keys("scaleY", (1, 1), (1.5, 0))) +
            ellipse("bug2", 440, 240, 16, 16, "#FF0000FF", "", keys("x", (0, 432), (2, 380))))
    S.append(shot(19, "macrophage-engulfs", "Kurzgesagt", "The Immune System Explained I – Bacteria Infection", yt + "zQGOcOUBi6s",
                  "macrophages engulfing bacteria in a crowded tissue scene", "—", "native",
                  "ellipses with keyed position and scale over a tissue-coloured background",
                  doc(tissue + macro + bugs),
                  {"green": ellipses_check((340, 180, 80, 60)), "red": ellipses_check((200, 120, 16, 16), (440, 240, 16, 16))}))

    # 20 Kurzgesagt: land-use infographic with growing bars
    chart = ('<chart id="land" kind="column" width="300" height="240" labels="pasture,crops">'
             '<series name="share" values="77 23" color="#FF0000FF"/>' + keys("progress", (0, 0.3), (1.5, 1)) + '</chart>')
    icons = rect("icon-pasture", 60, 80, 80, 50, "#00FF00FF") + rect("icon-crops", 60, 160, 80, 50, "#FFFF00FF")
    body = icons + '<layer id="bars" asset="land" x="300" y="60"/>'
    S.append(shot(20, "land-use-bars", "Kurzgesagt", "Why Meat is the Best Worst Thing in the World", yt + "NxvQPzrg2Wg",
                  "land-use infographic: farmland icons split into pasture and crops, bars growing", "—", "native",
                  "a column chart with keyed progress, icon rects",
                  doc(body, assets=chart),
                  {"green": rects_check((60, 80, 80, 50)), "yellow": rects_check((60, 160, 80, 50)),
                   "coverage": [cover("red", (300, 60, 600, 300), lo=0.02), cover("lit", (300, 60, 600, 300), lo=0.03)]}))

    # 21 Kurzgesagt: flash, fireball, shockwave and mushroom cloud over a flat skyline
    sky = [(40, 220, 60, 100), (120, 180, 50, 140), (190, 240, 70, 80), (280, 150, 40, 170), (340, 200, 80, 120), (440, 170, 60, 150), (520, 230, 80, 90)]
    skyline = "".join(rect(f"b{k}", x, y, w, h, "#0000FFFF") for k, (x, y, w, h) in enumerate(sky))
    blast = (rect("flash", 0, 0, 640, 360, "#FFFFFFFF", ' start="0.5" end="0.6"') +
             ellipse("fireball", 320, 200, 20, 20, "#FFFF00FF", ' start="0.5"', keys("scaleX", (0.5, 1), (1.5, 8)) + keys("scaleY", (0.5, 1), (1.5, 8))) +
             ellipse("ring", 320, 200, 40, 40, "#00000000", ' stroke="#FF0000FF" strokeWidth="6" start="0.7"', keys("scaleX", (0.7, 1), (2, 12)) + keys("scaleY", (0.7, 1), (2, 12))) +
             ellipse("cloud", 320, 90, 120, 80, "#FF8000FF", ' start="1.0"') + rect("stem", 300, 120, 40, 100, "#FF8000FF", ' start="1.0"'))
    S.append(shot(21, "nuke-skyline", "Kurzgesagt", "What if We Nuke a City?", yt + "5iPH-br_eJQ",
                  "flat city skyline, flash, fireball, shockwave ring and rising mushroom cloud, in vector form", "—", "native",
                  "rects with start and end, ellipses with keyed scale, a stroked ring",
                  doc(skyline + blast),
                  {"blue": rects_check(*sky), "absent": ["yellow", "red"]}))

    # 22 Kurzgesagt: timeline with key words and the title animating in
    title = ('<text id="title" text="Optimistic Nihilism" width="500" height="60" size="40" fontAsset="f"/>'
             '<text id="w1" text="Big Bang" width="200" height="40" size="24" fontAsset="f"/>'
             '<text id="w2" text="Now" width="200" height="40" size="24" fontAsset="f"/>')
    marks = [(140, 236, 8, 40), (320, 236, 8, 40), (500, 236, 8, 40)]
    body = (rect("line", 100, 254, 440, 4, "#FFFFFFFF") + "".join(rect(f"m{k}", x, y, w, h, "#FFFF00FF") for k, (x, y, w, h) in enumerate(marks)) +
            rect("now", 100, 230, 4, 52, "#FF0000FF", "", keys("x", (0, 100), (2, 500))) +
            '<layer id="t" asset="title" x="70" y="60"><textAnimator preset="word-by-word" presetStart="0.2" presetDuration="1"/></layer>'
            '<layer id="k1" asset="w1" x="100" y="290"><textAnimator preset="slide-up" presetStart="0.5" presetDuration="0.5"/></layer>'
            '<layer id="k2" asset="w2" x="440" y="290"><textAnimator preset="slide-up" presetStart="1.0" presetDuration="0.5"/></layer>')
    S.append(shot(22, "timeline-typography", "Kurzgesagt", "Optimistic Nihilism", yt + "MBRqu0YOH14",
                  "flat-vector universe timeline with key words and the title animating in", "—", "native",
                  "text animator presets (word-by-word, slide-up), rects, a keyed marker",
                  doc(body, assets=FONT + title),
                  {"yellow": rects_check(*marks), "red": rects_check((100, 230, 4, 52))}))

    # 23 Kurzgesagt: stylised black hole with a glowing disk and a lensed ring
    hole = ('<camera id="eye" x="320" y="180" z="-500" geodesics="true"/>'
            '<blackHole id="hole" mass="10" x="320" y="180" z="0"/>'
            '<accretionDisk id="disk" blackHole="hole" outerRadius="150" temperatureScale="6000" rotationX="80" angularPattern="spiral" seed="5"/>')
    S.append(shot(23, "black-hole-disk", "Kurzgesagt", "This Black Hole Could be Bigger Than The Universe", yt + "71eUes30gwc",
                  "stylised black hole with a glowing accretion disk and a lensed ring", "—", "native",
                  "a geodesic camera, a black hole and an accretion disk",
                  doc(hole),
                  {"coverage": [cover("lit", (0, 0, 640, 360), lo=0.05), cover("dark", (310, 170, 330, 190), lo=0.9)]}))

    # 24 minutephysics: hand-drawn worldlines, the frame changing by a shear (custom: the look is a stroke font and wobble)
    board = ('<group id="frame" x="320" y="180">' + keys("skewX", (0, 0), (1, -25)) +
             path("tline", "M0 120 L0 -120", stroke="#FF0000FF", width="4") + path("xline", "M-60 120 L60 -120", stroke="#00FF00FF", width="4") +
             path("wobble", "M-150 120 Q-100 116 -50 121 T50 119 T150 121", stroke="#FFFFFFFF", width="3") + '</group>'
             '<shape id="lt" shape="stroke-text" text="H" strokeFont="hand" x="330" y="50" width="30" height="30" stroke="#FFFFFFFF" strokeWidth="2"/>'
             '<shape id="lx" shape="stroke-text" text="I" strokeFont="hand" x="480" y="290" width="30" height="30" stroke="#FFFFFFFF" strokeWidth="2"/>')
    S.append(shot(24, "whiteboard-worldlines", "minutephysics", "Spacetime Diagrams, Special Relativity Ch. 2", yt + "hTxWAQGgeQw",
                  "hand-drawn worldlines on a whiteboard, the frame changing by a shear", "Characters, agents and looks (CL1)", "custom",
                  "stroke-text with a single-line stroke font, stroked paths in a group with keyed skew",
                  doc(board, assets='<strokeFont id="hand" src="../assets/stroke-hi.jhf"/>', background="#F4F1E8FF"),
                  {"red": {"cx": 320, "cy": 180, "w": 4, "h": 240}, "green": {"cx": 320, "cy": 180, "w": 124, "h": 240}},
                  custom="the hand-drawn look is a stroke font and hand-wobbled paths; CL1 would give it as a look"))

    # 25 minutephysics: charges with field lines sprouting (gap: no field-line tracer)
    lines = "".join(f'<shape id="fl{k}" shape="path" path="M240 180 C {240 + 60 * k - 60} {180 - 100 * k + 100}, {400 - 60 * k + 60} {180 - 100 * k + 100}, 400 180" '
                    f'width="{W}" height="{H}" fill="#00000000" stroke="#FFFF00FF" strokeWidth="2">' + keys("trimEnd", (0, 0), (1, 1)) + '</shape>'
                    for k in range(3))
    body = lines + ellipse("plus", 240, 180, 30, 30, "#FF0000FF") + ellipse("minus", 400, 180, 30, 30, "#0000FFFF")
    S.append(shot(25, "charges-field-lines", "minutephysics", "Real World Telekinesis (feat. Neil Turok)", yt + "NMgcX8UNIGY",
                  "hand-drawn charges with electric field lines sprouting from them and rearranging",
                  "Math and fields (MF5) and looks (CL1)", "gap",
                  "ellipses, hand-placed paths with keyed trimEnd",
                  doc(body),
                  {"red": ellipses_check((240, 180, 30, 30)), "blue": ellipses_check((400, 180, 30, 30)), "absent": ["yellow"]},
                  gap="no field-line tracer from charges (MF5); the lines are hand-placed paths"))

    # 26 minutephysics: sunlight scattering off air molecules, blue sideways
    mols = ('<repeat id="air" x="320" y="180"><points type="grid" columns="4" rows="3" spacingX="60" spacingY="70"/>'
            '<shape id="mol" shape="ellipse" x="-6" y="-6" width="12" height="12" fill="#FFFFFFFF" stroke="#C0C0C0FF" strokeWidth="2"/></repeat>')
    beam = rect("beam", 0, 170, 300, 20, "#FFFF00FF")
    dots = (ellipse("sc1", 300, 100, 12, 12, "#0000FFFF", "", keys("y", (0, 94), (2, 10))) +
            ellipse("sc2", 300, 260, 12, 12, "#0000FFFF", "", keys("y", (0, 254), (2, 340))))
    S.append(shot(26, "rayleigh-doodle", "minutephysics", "Why is the Sun Yellow and the Sky Blue?", yt + "NafbGOQBlQs",
                  "sunlight's spectrum scattering off air molecules, blue scattered sideways, in doodle style", "—", "native",
                  "a repeat over a grid, a rect, ellipses with keyed position",
                  doc(mols + beam + dots),
                  {"yellow": rects_check((0, 170, 300, 20)), "blue": ellipses_check((300, 100, 12, 12), (300, 260, 12, 12))}))

    # 27 Steve Mould: live footage with overlays
    body = (PLATE + rect("shaft", 400, 100, 4, 100, "#FF0000FF") + path("head", "M392 100 L402 86 L412 100 Z", fill="#FF0000FF") +
            rect("label", 430, 60, 100, 30, "#FFFF00FF"))
    S.append(shot(27, "chain-fountain-overlays", "Steve Mould", "The Chain Fountain AKA The Mould Effect", yt + "_dQJBBklpQQ",
                  "a bead chain rising out of a beaker in an arc and falling to the floor, live, with overlays", "—", "native",
                  "a video layer with shape overlays",
                  doc(body, assets=CLIP, background="#303030FF"),
                  {"regions": PLATE_BLACK, "red": {"cx": 402}, "yellow": rects_check((430, 60, 100, 30))}))

    # 28 Steve Mould: colour bands in a sugar column with a rotating E-vector helix (custom: hand-written)
    column = ('<shape id="column" shape="rect" x="280" y="40" width="80" height="280" fill="url(#bands)"/>')
    helix = ('<shape id="helix" shape="parametric" x="0" y="0" fill="#00000000" stroke="#FF0000FF" strokeWidth="3">'
             '<parametricPath x="320 + 30 * Math.cos(8 * t + 6 * time)" y="40 + 280 * t" t0="0" t1="1" samples="400"/></shape>')
    pol = rect("polariser", 100, 150, 60, 60, "#00FF00FF", "", keys("rotation", (0, 0), (2, 90)))
    paints = ('<linearGradient id="bands" x1="0" y1="0" x2="0" y2="1"><stop offset="0" color="#FF0040FF"/><stop offset="0.5" color="#8000FFFF"/>'
              '<stop offset="1" color="#0040FFFF"/></linearGradient>')
    S.append(shot(28, "optical-rotation-helix", "Steve Mould", "Why Sugar Always Twists Light To The Right – Optical Rotation", yt + "975r9a7FMqc",
                  "polarised light through a sugar column showing colour bands, with a rotating E-vector helix",
                  "Optics and waves (OW2, OW3)", "custom",
                  "a gradient-filled rect, a parametric helix whose expression reads time, a rect with keyed rotation",
                  doc(column + helix + pol, paints=paints),
                  {"coverage": [cover("lit", (280, 40, 360, 320), lo=0.9), cover("red", (280, 40, 360, 320), lo=0.01)],
                   "green": rects_check((100, 150, 60, 60))},
                  custom="the helix pitch and the colour bands are hand-written; OW2 and OW3 would derive them from the "
                         "rotation per length and the spectrum"))

    # 29 Real Engineering: booster separation (custom: keyed motion, particle plumes)
    stack = (f'<object3D id="tank" primitive="cylinder" radius="22" height="200" x="320" y="180" z="0" material="m-white"/>'
             f'<object3D id="orbiter" primitive="box" width="30" height="120" depth="20" x="320" y="200" z="-40" material="m-grey"/>')
    boosters = "".join(f'<object3D id="srb{k2}" primitive="cylinder" radius="12" height="160" x="{320 + s * 40}" y="180" z="0" material="m-red">'
                       + keys("x", (0.3, 320 + s * 40), (2, 320 + s * 140)) + keys("y", (0.3, 180), (2, 300)) + keys("rotation", (0.3, 0), (2, s * 60)) +
                       '</object3D>' for k2, s in enumerate([-1, 1]))
    plumes = "".join(f'<particles3D id="plume{k2}" x="{320 + s * 40}" y="262" z="0" rate="200" speed="120" lifetime="1" size="6" spread="20" '
                     f'directionY="1" material="m-yellow" seed="{k2 + 1}"><burst time="0" count="100"/></particles3D>' for k2, s in enumerate([-1, 1]))
    S.append(shot(29, "booster-separation", "Real Engineering", "The Insane Engineering of the Space Shuttle", yt + "UcBc0l7IrZU",
                  "the orbiter stack at booster separation, boosters tumbling away with exhaust plumes",
                  "3D simulation (SREP 11, S2 through A2)", "custom",
                  "3D primitives with keyed position and rotation, 3D particle emitters with a burst",
                  doc(stack + boosters + plumes),
                  {"red": {"cx": 320, "cy": 180}, "coverage": [cover("yellow", (200, 250, 440, 360), lo=0.01)]},
                  check_frame=6,
                  custom="the separation and tumble are keyed by hand (SREP 11 rigid bodies with joints and thrust, S2, "
                         "would compute them); the plumes are particle emitters (A2 would make them media)"))

    # 30 Real Engineering: J58 nacelle cutaway with flow and shock lines (gap: no flow field)
    walls = [(120, 100, 400, 12), (120, 248, 400, 12)]
    body = ("".join(rect(f"wall{k2}", x, y, w, h, "#0000FFFF") for k2, (x, y, w, h) in enumerate(walls)) +
            path("spike", "M0 0 L120 -30 L120 30 Z", fill="#FF0000FF", extra=' x="140" y="180"', inner=keys("x", (0, 140), (2, 200))) +
            "".join(path(f"flow{k2}", f"M100 {y} H540", stroke="#FFFFFFFF", width="2", extra=f' dash="12 8"', inner=keys("dashOffset", (0, 0), (2, -200)))
                    for k2, y in enumerate([130, 160, 200, 230])) +
            path("shock", "M260 112 L330 180 L260 248", stroke="#FFFF00FF", width="2"))
    S.append(shot(30, "nacelle-cutaway", "Real Engineering", "The Insane Engineering of the SR-71 Blackbird", yt + "3hYSnyVLmGE",
                  "cutaway of the J58 nacelle: the inlet spike moves while flow and shock lines pass through",
                  "3D simulation (S5 with MF5)", "gap",
                  "rects, a keyed path, dashed paths with keyed dash offset",
                  doc(body),
                  {"blue": no_px(rects_check(*walls)), "red": {"cx": 220, "cy": 180, "w": 120, "h": 60}},
                  gap="no flow field or shock lines from a solver (S5 with MF5); the lines are hand-placed dashed paths"))

    # 31 Real Engineering: re-entry capsule (gap: no plasma sheath or bow shock medium)
    body = ('<object3D id="shield" primitive="cylinder" radius="50" height="6" x="320" y="180" z="0" rotationX="90" material="m-red"/>'
            '<object3D id="capsule" primitive="cone" radius="50" height="80" x="320" y="180" z="43" rotationX="-90" material="m-grey"/>'
            '<particles3D id="sheath" x="320" y="180" z="-5" rate="300" speed="150" lifetime="1.2" size="5" spread="40" directionX="-1" '
            'directionY="0" material="m-yellow" seed="4"><burst time="0" count="150"/></particles3D>')
    S.append(shot(31, "reentry-plasma", "Real Engineering", "The Insane Engineering of Re-Entry", yt + "ivLX9o6Ayl8",
                  "a capsule's heat shield glowing, with a plasma sheath and bow shock trailing behind",
                  "Light and volumes (A2)", "gap",
                  "3D primitives, an unlit shield, a 3D particle emitter with a burst",
                  doc(body),
                  {"red": {"cy": 180}, "coverage": [cover("red", (270, 130, 370, 230), lo=0.5),
                                                    cover("yellow", (0, 60, 320, 300), lo=0.002)]},
                  check_frame=SEEK_FRAME,
                  gap="no plasma sheath or bow shock medium (A2); the shield is an unlit disc and the trail a particle "
                      "emitter"))

    # 32 Real Engineering: a map of wind farms and grid links, then a chart
    geo = ('<geo id="farms" src="../assets/srep12-wind.geojson"/>'
           '<map id="atlas" width="320" height="300" projection="mercator" fit="farms" fitPadding="30" background="#0000FFFF">'
           '<geoLayer geo="farms" fill="#FF0000FF" stroke="#FFFFFFFF" strokeWidth="2" pointRadius="12" label="capacity"/></map>'
           '<chart id="cap" kind="bar" width="260" height="200" labels="North,West,East"><series name="MW" values="320 180 450" color="#FFFF00FF"/></chart>')
    body = '<layer id="m" asset="atlas" x="20" y="30"/><layer id="c" asset="cap" x="360" y="80" start="0"/>'
    S.append(shot(32, "wind-farm-map-chart", "Real Engineering", "The Problem with Wind Energy", yt + "LklUVkMPl8g",
                  "a map of wind farms and grid links with capacity figures, then a chart", "—", "native",
                  "a map asset fitted to a GeoJSON geo asset with a labelled geo layer, a bar chart",
                  doc(body, assets=geo),
                  {"coverage": [cover("blue", (20, 30, 340, 330), lo=0.6), cover("red", (20, 30, 340, 330), lo=0.001),
                                cover("yellow", (360, 80, 620, 280), lo=0.05)]}))

    # 33 Primer: blobs running for food, dying off, a population graph (gap: no agents)
    blobs = (ellipse("blob1", 200, 200, 40, 40, "#00FF00FF", "", keys("x", (0, 180), (1, 240)) + keys("y", (0, 180), (1, 200))) +
             ellipse("blob2", 440, 200, 40, 40, "#00FF00FF", "", keys("x", (0, 420), (1, 360)) + keys("opacity", (1.2, 1), (1.8, 0))))
    food = ellipse("food1", 300, 220, 10, 10, "#FF0000FF", ' end="1.2"') + ellipse("food2", 340, 220, 10, 10, "#FF0000FF", ' end="1.6"')
    chart = ('<chart id="pop" kind="line" width="200" height="120" labels="0,1,2,3,4"><series name="n" values="10 14 12 9 11" color="#FFFF00FF"/>'
             + keys("progress", (0, 0.2), (2, 1)) + '</chart>')
    body = blobs + food + '<layer id="graph" asset="pop" x="420" y="20"/>'
    S.append(shot(33, "natural-selection-blobs", "Primer", "Simulating Natural Selection", yt + "0ZGbIKd0XrM",
                  "blob creatures running for food on a plateau, some dying off, a population graph ticking beside them",
                  "Characters, agents and looks (CL2, CL3)", "gap",
                  "ellipses with keyed motion and opacity, a line chart with keyed progress",
                  doc(body, assets=chart),
                  {"green": ellipses_check((200, 200, 40, 40), (440, 200, 40, 40)), "red": ellipses_check((300, 220, 10, 10), (340, 220, 10, 10)),
                   "coverage": [cover("lit", (420, 20, 620, 140), lo=0.02)]},
                  gap="no agent behaviour (seek food, eat, die: CL2) and no chart bound to a simulation (CL3); the blobs "
                      "are keyed by hand"))

    # 34 Primer: hawks and doves at pellets, a stacked-area chart (gap: no agent model)
    pellets = [(200, 240), (320, 240), (440, 240)]
    body = ("".join(ellipse(f"p{k2}", x, y, 10, 10, "#FFFF00FF") for k2, (x, y) in enumerate(pellets)) +
            ellipse("hawk", 180, 150, 36, 36, "#FF0000FF", "", keys("x", (0, 162), (1, 190))) +
            ellipse("dove", 460, 150, 36, 36, "#0000FFFF", "", keys("x", (0, 442), (1, 410))) +
            '<layer id="mixgraph" asset="mix" x="40" y="20"/>')
    chart = ('<chart id="mix" kind="area" width="220" height="110" labels="0,1,2,3"><series name="hawk" values="2 3 5 4" color="#FF0000FF"/>'
             '<series name="dove" values="6 5 3 4" color="#0000FFFF"/></chart>')
    S.append(shot(34, "hawk-dove-chart", "Primer", "Simulating the Evolution of Aggression", yt + "YNMkADpvO4w",
                  "hawk and dove blobs pairing up at food pellets, then a stacked-area chart of the population mix",
                  "Characters, agents and looks (CL3)", "gap",
                  "ellipses with keyed motion, a two-series area chart",
                  doc(body, assets=chart),
                  {"yellow": ellipses_check(*[(x, y, 10, 10) for x, y in pellets]), "coverage": [cover("lit", (40, 20, 260, 130), lo=0.02)]},
                  gap="no agent model (CL2) and no stacked-area chart bound to it (CL3): an area chart draws its series "
                      "unstacked and from fixed values"))

    # 35 Sebastian Lague: particles pouring into a box and sloshing (gap: no particle liquid)
    box = ('<object3D id="floor" primitive="plane" width="300" height="8" x="320" y="300" z="0" material="m-green"/>'
           '<object3D id="lwall" primitive="plane" width="8" height="160" x="174" y="224" z="0" material="m-green"/>'
           '<object3D id="rwall" primitive="plane" width="8" height="160" x="466" y="224" z="0" material="m-green"/>')
    pour = ('<particles3D id="pour" x="320" y="60" z="0" rate="400" speed="40" lifetime="4" size="5" spread="30" directionY="1" '
            'gravityY="400" colliders="floor lwall rwall" material="m-blue" seed="7"><burst time="0" count="200"/></particles3D>')
    S.append(shot(35, "fluid-particles", "Sebastian Lague", "Coding Adventure: Simulating Fluids", yt + "rSKMYc1CQHE",
                  "particles pouring into a box and sloshing, coloured by speed", "3D simulation (S3)", "gap",
                  "a 3D particle emitter with gravity and plane colliders, unlit planes",
                  doc(box + pour),
                  {"green": {"cx": 320, "cy": round((300 * 2400 + 224 * 1280 * 2) / (2400 + 2560), 2)}, "blue": {"cx": 320, "cy": 60}},
                  gap="no particle liquid (S3): particles3D fall and bounce off the planes but carry no pressure, and "
                      "nothing colours them by speed"))

    # 36 Sebastian Lague: sweeping over a planet's limb at sunset (gap: no atmosphere from orbit)
    sky = ('<lights><light id="sky" type="dome" sky="gradient" skyZenith="#102060" skyHorizon="#FF8040" skyGround="#000000" skyExponent="1" '
           'sunAzimuth="0" sunElevation="2" sunSize="4" sunColor="#FFE0A0" sunIntensity="3" environmentVisible="true"/></lights>\n')
    limb = (f'<object3D id="planet" primitive="sphere" radius="900" x="320" y="1200" z="200" material="m-blue"/>'
            '<object3D id="terrain" primitive="heightfield" x="320" y="300" z="-100" material="m-green">'
            '<heightfield height="12 * Math.sin(x / 15) * Math.cos(z / 15)" width="500" depth="120" xSamples="50" zSamples="12"/></object3D>'
            f'<camera id="cam" x="320" y="180" z="{-D:.3f}">' + keys("x", (0, 320), (2, 400)) + keys("pitch", (0, 0), (2, 6)) + '</camera>')
    S.append(shot(36, "planet-limb-sunset", "Sebastian Lague", "Coding Adventure: Atmosphere", yt + "DxfEbulyFcY",
                  "the camera sweeps over a planet's limb at sunset, a scattered sky above terrain", "Space (A1)", "gap",
                  "a dome light with the procedural sky and a sun, an unlit sphere as the planet, a heightfield, a camera with "
                  "keyed position and pitch",
                  doc(limb, lights=sky),
                  {"coverage": [cover("lit", (0, 0, 640, 60), lo=0.9), cover("blue", (160, 250, 480, 330), lo=0.3),
                                cover("green", (120, 200, 520, 320), lo=0.05)]},
                  gap="no atmosphere seen from orbit (A1): the dome sky is a ground-level gradient and the planet has "
                      "no scattering shell"))
    return S


SHOTS = build()


def main():
    cases = {}
    for s in SHOTS:
        name = f"srep-0012-shot-{s['n']:02d}-{s['slug']}"
        cases[name] = {"xml": s["xml"], "expected": {"rule": f"SREP 12 Appendix A, shot {s['n']} ({s['technique']})",
                                                     **s["expected"]}}
    kit_pending.settle(cases, 12)
    assets = os.path.join(CONF, "srep_cases", "assets")
    os.makedirs(assets, exist_ok=True)
    with open(os.path.join(assets, "srep12-track.json"), "w") as f:
        json.dump(TRACK, f, indent=1, sort_keys=True)
        f.write("\n")
    with open(os.path.join(assets, "srep12-wind.geojson"), "w") as f:
        json.dump(WIND, f, indent=1, sort_keys=True)
        f.write("\n")
    json.dump(cases, open(os.path.join(CONF, "srep_cases", "srep-0012.json"), "w"), indent=1, ensure_ascii=False)
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
