#!/usr/bin/env python3
"""Run every case in cases/ through scene-render implementations and check it against expected.json.

  python3 run.py [--renderers rs] [--cases a1,b2,...]

By default only the Rust engine runs: it is the only active engine (SREP 25). The C, Python and JavaScript
runners stay available with --renderers, for when an engine becomes active again.

For each renderer and case: copy the case into out/<renderer>/<case>/scene.xml (asset paths made absolute),
render frame 0 to PNG (or, for a case whose expected entry names an "output", deliver that output at the given
output time), find each colour's pixels (pure red/green/blue/yellow on black) and compare the
centroid (and size, where expected) with the normative value. Writes out/report.json and out/report.md.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

def _js(scene, png):
    """The JS engine: JS_RENDER_ROOT/bin/scene-render.js under node, else `scene-render-js` on PATH."""
    root = os.environ.get("JS_RENDER_ROOT")
    cmd = ["node", os.path.join(root, "bin", "scene-render.js")] if root else ["scene-render-js"]
    return cmd + ["render", scene, "--output", "still", "--from", "0", "--to", "0.04", "--jobs", "1", "--gpu", "off"]


# name -> (label, command builder: (scene_path, png_path) -> argv, env additions). Each engine is found through
# an environment variable, else by the same command names scenerender-vpkg uses (scene-render-c, scene-render-rs,
# scene-render-js, and python3 with py-render installed); all three native engines install a binary named
# scene-render, so on PATH they need these distinct aliases.
RENDERERS = {
    "c": ("C (c-scene-render)",
          lambda s, p: [os.environ.get("C_RENDER_BIN", "scene-render-c"), "--scene", s, "--frame", "0", "--output", p], {}),
    "rs": ("Rust (rs-scene-render)",
           lambda s, p: [os.environ.get("RS_RENDER_BIN", "scene-render-rs"), "render", s, "-f", "0", "-o", p],
           {"SR_GPU_BACKEND": "vulkan"}),
    "py": ("Python (py-render)",
           lambda s, p: [os.environ.get("PY_RENDER_PYTHON", "python3"), "-m", "scenerender.cli",
                         "still", s, "-t", "0", "-o", p], {}),
    "js": ("JavaScript (js-render-engine)", _js, {}),
}

# name -> (scene, png, output id, output time) -> argv: renderers that can deliver one named output at one output
# time (SREP 13 cases). The output writes a PNG sequence into the case folder; the frame at that time is the file.
OUTPUT_RENDERERS = {
    "rs": lambda s, p, oid, t: [os.environ.get("RS_RENDER_BIN", "scene-render-rs"), "encode", s, "--output", oid,
                                "--start", f"{t}", "--end", f"{t + 0.001}"],
}

# a pixel belongs to a colour when that channel pattern dominates (robust to antialiasing and slight shading)
CLASSES = {
    "red": lambda r, g, b: (r > 0.5) & (g < 0.3) & (b < 0.3),
    "green": lambda r, g, b: (g > 0.5) & (r < 0.3) & (b < 0.3),
    "blue": lambda r, g, b: (b > 0.5) & (r < 0.3) & (g < 0.3),
    "yellow": lambda r, g, b: (r > 0.5) & (g > 0.5) & (b < 0.3),
}


def measure(png):
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.float64) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    res = {}
    for name, f in CLASSES.items():
        m = f(r, g, b)
        n = int(m.sum())
        if n < 12:
            continue
        ys, xs = np.nonzero(m)
        res[name] = {"cx": round(float(xs.mean()) + 0.5, 2), "cy": round(float(ys.mean()) + 0.5, 2),
                     "w": int(xs.max() - xs.min() + 1), "h": int(ys.max() - ys.min() + 1), "px": n}
    return res


def prepare(case, renderer):
    d = os.path.join(OUT, renderer, case)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    xml = open(os.path.join(HERE, "cases", case + ".xml")).read()
    # keep asset paths relative (some renderers refuse absolute ones): copy the assets beside the scene
    shutil.copytree(os.path.join(HERE, "assets"), os.path.join(d, "assets"))
    xml = xml.replace('="../assets/', '="assets/')
    s = os.path.join(d, "scene.xml")
    open(s, "w").write(xml)
    return d, s


def render(renderer, case, output=None):
    label, cmd, env = RENDERERS[renderer]
    d, s = prepare(case, renderer)
    png = os.path.join(d, "frame.png")
    t0 = time.time()
    if output:
        if renderer not in OUTPUT_RENDERERS:
            return None, None, 0.0, [f"{label} cannot deliver an output at an output time from this kit yet"]
        argv = OUTPUT_RENDERERS[renderer](s, png, output["id"], output["time"])
    else:
        argv = cmd(s, png)
    try:
        p = subprocess.run(argv, cwd=d, capture_output=True, text=True, timeout=600, env={**os.environ, **env})
    except FileNotFoundError:
        return None, None, time.time() - t0, [f"{argv[0]} not found: set the engine's environment variable or put "
                                               "its scene-render-* alias on PATH (see the module documentation)"]
    except subprocess.TimeoutExpired:
        return None, None, time.time() - t0, ["timed out after 600 s"]
    dt = time.time() - t0
    if not os.path.exists(png):  # renderers that write the document's own output path
        found = sorted(glob.glob(os.path.join(d, "**", "*.png"), recursive=True))
        if found:
            shutil.copy(found[0], png)
    log = (p.stdout + p.stderr).strip()
    notes = sorted({l.strip() for l in log.splitlines() if re.search(r"not (rendered|supported)|unsupported|error", l, re.I)})
    if p.returncode != 0:                 # an engine that reports failure fails the case, whatever it wrote
        tail = (log.splitlines() or [""])[-1][:160]
        return None, p.returncode, dt, [f"exit status {p.returncode}: {tail}"] + notes[:5]
    return (png if os.path.exists(png) else None), p.returncode, dt, notes[:6]


COLOUR_TOL = 3  # 8-bit code values


def region_rgb(png, box):
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.float64)
    x0, y0, x1, y1 = box
    return [round(float(v), 1) for v in a[y0:y1, x0:x1].reshape(-1, 3).mean(0)]


def check(meas, exp, tol, png=None):
    rows = []
    for k, reg in enumerate(exp.get("regions", [])):
        got = region_rgb(png, reg["box"])
        ok = all(abs(g - w) <= COLOUR_TOL for g, w in zip(got, reg["rgb"]))
        rows.append((f"region{k}", "pass" if ok else "fail", {"rgb": reg["rgb"]}, {"rgb": got}))
    for col in exp.get("absent", []):
        rows.append((col, "fail" if col in meas else "pass", "absent", meas.get(col)))
    for col, e in exp.items():
        if col in ("rule", "regions", "absent", "output"):
            continue
        m = meas.get(col)
        if m is None:
            rows.append((col, "missing", e, None))
            continue
        errs = {k: round(m[k] - e[k], 2) for k in e if k in m}
        ok = all(abs(v) <= tol for v in errs.values())
        rows.append((col, "pass" if ok else "fail", e, {k: m[k] for k in e}, ))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--renderers", default="rs")
    ap.add_argument("--cases", default="")
    a = ap.parse_args()
    spec = json.load(open(os.path.join(HERE, "expected.json")))
    tol = spec["tolerance_px"]
    cases = [c for c in spec["cases"] if not a.cases or any(c.startswith(x) for x in a.cases.split(","))]
    report = {"tolerance_px": tol, "results": {}}
    for r in a.renderers.split(","):
        report["results"][r] = {}
        for c in cases:
            png, code, dt, notes = render(r, c, spec["cases"][c].get("output"))
            entry = {"exit": code, "seconds": round(dt, 2), "notes": notes}
            if png:
                meas = measure(png)
                entry["measured"] = meas
                entry["checks"] = [{"colour": col, "status": st, "expected": e, "measured": m} for col, st, e, m in check(meas, spec["cases"][c], tol, png)]
                entry["status"] = "pass" if all(x["status"] == "pass" for x in entry["checks"]) else "fail"
            else:
                entry["status"] = "error"
            report["results"][r][c] = entry
            print(f"{r:3s} {c:22s} {entry['status']:5s} {dt:6.1f}s " + ("; ".join(notes)[:110] if entry["status"] == "error" else ""), flush=True)
    os.makedirs(OUT, exist_ok=True)
    json.dump(report, open(os.path.join(OUT, "report.json"), "w"), indent=2)
    write_md(report, spec, cases)
    bad = [(r, c) for r, res in report["results"].items() for c, e in res.items() if e["status"] != "pass"]
    if not cases:
        print("no cases selected", flush=True)
        return 2
    if bad:
        print(f"{len(bad)} of {sum(len(v) for v in report['results'].values())} case runs did not pass", flush=True)
        return 1
    return 0


def write_md(report, spec, cases):
    rs = list(report["results"])
    L = ["# Conformance report", "", f"Tolerance: {report['tolerance_px']} px. Rules: CONVENTIONS.md.", "",
         "| case | rule | " + " | ".join(RENDERERS[r][0] for r in rs) + " |", "|---|---|" + "---|" * len(rs)]
    for c in cases:
        cells = []
        for r in rs:
            e = report["results"][r][c]
            if e["status"] == "pass":
                cells.append("✅")
            elif e["status"] == "error":
                cells.append("⛔ " + (e["notes"][0][:60] if e["notes"] else f"exit {e['exit']}"))
            else:
                bad = [x for x in e["checks"] if x["status"] != "pass"]
                cells.append("❌ " + "; ".join(f"{x['colour']} " + ("present (must not appear)" if x["expected"] == "absent" else
                                                                   "missing" if x["measured"] is None else
                                                                   ", ".join(f"{k} {x['measured'][k]} (exp {x['expected'][k]})" for k in x["expected"]))
                                              for x in bad))
        L.append(f"| {c} | {spec['cases'][c]['rule']} | " + " | ".join(cells) + " |")
    open(os.path.join(OUT, "report.md"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
