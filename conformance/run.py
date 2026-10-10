#!/usr/bin/env python3
"""Run every case in cases/ through scene-render implementations and check it against expected.json.

  python3 run.py [--renderers rs] [--cases a1,b2,...]

By default only the Rust engine runs: it is the only active engine (SREP 25). The C, Python and JavaScript
runners stay available with --renderers, for when an engine becomes active again.

For each renderer and case: copy the case into out/<renderer>/<case>/scene.xml (asset paths made absolute),
render frame 0 to PNG (or, for a case whose expected entry names an "output", deliver that output at the given
output time), find each colour's pixels (pure red/green/blue/yellow on black) and compare the
centroid (and size, where expected) with the normative value. Writes out/report.json and out/report.md.

Three forms check something other than a picture: "findings" (the engine's diagnostics, `validate --format json`),
"captions" (the caption pages after paging and the current word per time, `captions --at`; SREP 52) and "audio"
(the gain of each test tone at given times in an audio-only WAV output; SREP 82).
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import time

try:                          # pixel cases need them; findings cases do not
    import numpy as np
    from PIL import Image
except ImportError:
    np = Image = None

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
# An expected "output" entry is {"id", "time"} and may add "start" and "end" (the CLI range, default time to time + 1 ms:
# for a segmented output that is output time) and "frame" (which written file to take, default the first). An output
# without segments takes its origin from the CLI start, so a case that needs output time t reads the frame t from start 0.
OUTPUT_RENDERERS = {
    "rs": lambda s, p, out: [os.environ.get("RS_RENDER_BIN", "scene-render-rs"), "encode", s, "--output", out["id"],
                             "--start", f"{out.get('start', out['time'])}",
                             "--end", f"{out.get('end', out.get('start', out['time']) + 0.001)}"],
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
        argv = OUTPUT_RENDERERS[renderer](s, png, output)
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
        # the assets copied beside the scene are inputs, not output
        found = sorted(f for f in glob.glob(os.path.join(d, "**", "*.png"), recursive=True)
                       if not f.startswith(os.path.join(d, "assets") + os.sep))
        if found:
            shutil.copy(found[min((output or {}).get("frame", 0), len(found) - 1)], png)
    log = (p.stdout + p.stderr).strip()
    notes = sorted({l.strip() for l in log.splitlines() if re.search(r"not (rendered|supported)|unsupported|error", l, re.I)})
    if p.returncode != 0:                 # an engine that reports failure fails the case, whatever it wrote
        tail = (log.splitlines() or [""])[-1][:160]
        return None, p.returncode, dt, [f"exit status {p.returncode}: {tail}"] + notes[:5]
    return (png if os.path.exists(png) else None), p.returncode, dt, notes[:6]


def findings(renderer, case, want):
    """A case whose expected entry has "findings": the engine validates the document and reports these diagnostics.

    {"codes": [...]} must all be present, {"absent": [...]} must not be, {"counts": {code: n}} gives exact numbers,
    {"messages": [...]} are substrings some message holds, {"valid": bool} is the verdict. With {"via": "render"} the engine
    renders frame 0 and only {"messages": [...]} is checked, against everything it printed. Only the Rust
    engine is asked (`validate --format json`, which includes the evaluation warnings); another renderer is an error."""
    label, _, env = RENDERERS[renderer]
    if renderer != "rs":
        return "error", 0.0, [f"{label} cannot report findings from this kit yet"], {}
    d, s_ = prepare(case, renderer)
    t0 = time.time()
    exe = os.environ.get("RS_RENDER_BIN", "scene-render-rs")
    if want.get("via") == "render":
        # reports that exist only at frame evaluation (an unknown joint or morph name, an unknown clip): the engine
        # renders frame 0, the exit status is ignored (an unknown clip fails the frame), and every message must be a
        # substring of some line of what it printed
        try:
            p = subprocess.run([exe, "render", s_, "-f", "0", "-o", os.path.join(d, "frame.png")], cwd=d,
                               capture_output=True, text=True, timeout=600, env={**os.environ, **env})
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return "error", time.time() - t0, [f"render failed: {type(e).__name__}: {e}"], {}
        said = p.stdout + p.stderr
        checks = {"messages": [(m, m in said) for m in want.get("messages", [])]}
        ok = all(v for rows in checks.values() for _, v in rows)
        return ("pass" if ok else "fail"), time.time() - t0, [], {"reported": [l.strip()[:120] for l in said.splitlines() if l.strip()][:6], "valid": None, "checks": checks}
    try:
        p = subprocess.run([exe, "validate", s_, "--format", "json"], cwd=d, capture_output=True, text=True,
                           timeout=600, env={**os.environ, **env})
        out = json.loads(p.stdout)["files"][0]
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError) as e:
        return "error", time.time() - t0, [f"validate failed: {type(e).__name__}: {e}"], {}
    diags = out.get("diagnostics", [])
    # the safe-area audit prints SA01 and SA02 lines in the text form of `validate`
    text = ""
    if any(c.startswith("SA") for c in list(want.get("codes", [])) + list(want.get("absent", []))):
        text = subprocess.run([exe, "validate", s_], cwd=d, capture_output=True, text=True, timeout=600,
                              env={**os.environ, **env}).stdout
    got = sorted({x["code"] for x in diags} | set(re.findall(r"\b(SA0[12])\b", text)))
    counts = {c: max(sum(1 for x in diags if x["code"] == c), len(re.findall(rf"\b{c}\b", text)))
              for c in want.get("counts", {})}
    checks = {"codes": [(c, c in got) for c in want.get("codes", [])],
              "absent": [(c, c not in got) for c in want.get("absent", [])],
              "counts": [(f"{c} x{n}", counts[c] == n) for c, n in want.get("counts", {}).items()],
              "messages": [(m, any(m in x.get("message", "") for x in diags)) for m in want.get("messages", [])]}
    if "valid" in want:
        checks["valid"] = [(str(want["valid"]), out.get("valid") == want["valid"])]
    ok = all(v for rows in checks.values() for _, v in rows)
    return ("pass" if ok else "fail"), time.time() - t0, [], {"reported": got, "valid": out.get("valid"), "checks": checks}


def captions(renderer, case, want):
    """A case whose expected entry has "captions": the engine's caption tracks after paging (SREP 52), read from
    `scene-render captions <scene> --at <times>` (one JSON document; no picture, so no font metrics are involved).

    The entry is one check or a list of them, each naming a "track" by id and checking, all exactly:
    {"pages": [...]}, the text of each page in order, its lines joined by "\n"; {"preset": name}, the preset the
    layout applies; {"wordCount": n}, the words over all cues; {"activeWord": [[time, index], ...]}, the current word
    at that time as an index in its cue (null: none on screen); {"wordsAndTimesEqualTo": "<case>"}, the words of
    every cue, their texts, starts and ends, equal those of the same track in that other case. Only the Rust engine
    is asked; another renderer is an error."""
    label, _, env = RENDERERS[renderer]
    if renderer != "rs":
        return "error", 0.0, [f"{label} cannot dump caption pages from this kit yet"], {}
    specs = want if isinstance(want, list) else [want]
    exe = os.environ.get("RS_RENDER_BIN", "scene-render-rs")
    t0 = time.time()

    def dump(name, times):
        d, s_ = prepare(name, renderer)
        argv = [exe, "captions", s_] + (["--at", ",".join(repr(float(t)) for t in times)] if times else [])
        p = subprocess.run(argv, cwd=d, capture_output=True, text=True, timeout=600, env={**os.environ, **env})
        if p.returncode != 0:
            tail = ((p.stderr or p.stdout).strip().splitlines() or [""])[-1][:160]
            raise RuntimeError(f"exit status {p.returncode}: {tail}")
        return {t["id"]: t for t in json.loads(p.stdout)["tracks"]}

    def words(track):
        return [[(w["text"], w["start"], w["end"]) for w in c["words"]] for c in track["cues"]]

    times = sorted({float(t) for spec in specs for t, _ in spec.get("activeWord", [])})
    try:
        tracks = dump(case, times)
        others = {o: dump(o, []) for o in sorted({s["wordsAndTimesEqualTo"] for s in specs if "wordsAndTimesEqualTo" in s})}
    except (FileNotFoundError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError) as e:
        return "error", time.time() - t0, [f"captions failed: {type(e).__name__}: {e}"], {}
    checks = {"tracks": [], "pages": [], "preset": [], "wordCount": [], "activeWord": [], "wordsAndTimes": []}
    reported = {}
    for spec in specs:
        tid = spec["track"]
        t = tracks.get(tid)
        checks["tracks"].append((tid, t is not None))
        if t is None:
            continue
        pages = [p["text"] for p in t["pages"]]
        reported[tid] = pages
        if "pages" in spec:
            checks["pages"].append((f"{tid} {spec['pages']!r} (got {pages!r})", pages == spec["pages"]))
        if "preset" in spec:
            checks["preset"].append((f"{tid} {spec['preset']} (got {t['preset']})", t["preset"] == spec["preset"]))
        if "wordCount" in spec:
            checks["wordCount"].append((f"{tid} {spec['wordCount']} (got {t['wordCount']})", t["wordCount"] == spec["wordCount"]))
        at = {float(a["time"]): a["word"] for a in t["at"]}
        for tm, idx in spec.get("activeWord", []):
            got = at.get(float(tm), "missing")
            checks["activeWord"].append((f"{tid} at {tm}: {idx} (got {got})", got == idx))
        if "wordsAndTimesEqualTo" in spec:
            other = spec["wordsAndTimesEqualTo"]
            o = others[other].get(tid)
            checks["wordsAndTimes"].append((f"{tid} equal to {other}", o is not None and words(o) == words(t)))
    ok = all(v for rows in checks.values() for _, v in rows)
    return ("pass" if ok else "fail"), time.time() - t0, [], {"form": "captions", "reported": reported, "checks": checks}


def read_wav(path):
    """(rate, first channel as float in [-1, 1]) of a RIFF/WAVE file: integer PCM of 16, 24 or 32 bits, or 32/64-bit
    float, plain or WAVE_FORMAT_EXTENSIBLE."""
    data = open(path, "rb").read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{os.path.basename(path)} is not a RIFF/WAVE file")
    i, fmt, body = 12, None, None
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], int.from_bytes(data[i + 4:i + 8], "little")
        if cid == b"fmt ":
            fmt = data[i + 8:i + 8 + size]
        elif cid == b"data":
            body = data[i + 8:i + 8 + size]
        i += 8 + size + (size & 1)
    if fmt is None or body is None:
        raise ValueError(f"{os.path.basename(path)} lacks a fmt or data chunk")
    tag, channels, rate = (int.from_bytes(fmt[a:b], "little") for a, b in ((0, 2), (2, 4), (4, 8)))
    bits = int.from_bytes(fmt[14:16], "little")
    if tag == 0xFFFE:                       # WAVE_FORMAT_EXTENSIBLE: the sub-format's first two bytes are the tag
        tag = int.from_bytes(fmt[24:26], "little")
    width = bits // 8
    n = len(body) // (width * channels)
    if tag == 3:
        x = np.frombuffer(body[:n * width * channels], dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif tag == 1 and bits in (16, 32):
        x = np.frombuffer(body[:n * width * channels], dtype=f"<i{width}").astype(np.float64) / 2.0 ** (bits - 1)
    elif tag == 1 and bits == 24:
        b = np.frombuffer(body[:n * 3 * channels], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float64) / 2.0 ** 23
    else:
        raise ValueError(f"{os.path.basename(path)}: unsupported WAVE format {tag} with {bits} bits")
    return rate, x.reshape(-1, channels)[:, 0]


def tone_amplitude(x, rate, freq, t, window):
    """The amplitude of the sine of `freq` Hz in `x` over the window of `window` seconds centred on `t` (a single DFT
    bin: 2/N |sum x[n] e^(-2 pi i f n / rate)|). A tone completing a whole number of cycles in the window does not
    leak into another such tone's bin."""
    n = int(round(window * rate))
    i0 = int(round((t - window / 2) * rate))
    seg = x[max(i0, 0):max(i0, 0) + n]
    if len(seg) < n:
        return 0.0
    k = np.arange(n) + i0
    return float(2.0 / n * abs(np.sum(seg * np.exp(-2j * np.pi * freq * k / rate))))


def audio(renderer, case, want):
    """A case whose expected entry has "audio": the engine delivers the document's audio-only WAV output and the gain
    of each sound source is measured at given times (SREP 82). The entry is {"output": id, "tones": {name: Hz},
    "level": amplitude, "window": seconds, "tolerance": gain, "gains": [[time, {name: gain}], ...]}: each source plays
    a sine of its frequency at `level`, and its gain at a time is the amplitude of that sine over the window centred on
    the time, divided by `level` (tone_amplitude). Every listed gain must be within `tolerance`. Only the Rust engine
    is asked (`encode <scene> --output <id>`); another renderer is an error."""
    label, _, env = RENDERERS[renderer]
    if renderer != "rs":
        return "error", 0.0, [f"{label} cannot deliver an audio output from this kit yet"], {}
    d, s_ = prepare(case, renderer)
    exe = os.environ.get("RS_RENDER_BIN", "scene-render-rs")
    t0 = time.time()
    try:
        p = subprocess.run([exe, "encode", s_, "--output", want["output"]], cwd=d, capture_output=True, text=True,
                           timeout=600, env={**os.environ, **env})
        if p.returncode != 0:
            tail = ((p.stderr or p.stdout).strip().splitlines() or [""])[-1][:160]
            raise RuntimeError(f"exit status {p.returncode}: {tail}")
        xml = open(s_).read()
        m = re.search(r'<output\b[^>]*\bid="%s"[^>]*>' % re.escape(want["output"]), xml)
        path = re.search(r'\bpath="([^"]+)"', m.group(0)).group(1) if m else ""
        rate, x = read_wav(os.path.join(d, path))
    except (FileNotFoundError, subprocess.TimeoutExpired, RuntimeError, ValueError, AttributeError) as e:
        return "error", time.time() - t0, [f"audio failed: {type(e).__name__}: {e}"], {}
    tol, level, window = want["tolerance"], want["level"], want["window"]
    rows, measured = [], []
    for t, gains in want["gains"]:
        got = {k: round(tone_amplitude(x, rate, want["tones"][k], t, window) / level, 4) for k in gains}
        measured.append([t, got])
        for k, g in gains.items():
            rows.append((f"{k} at {t}: {g} (got {got[k]})", abs(got[k] - g) <= tol))
    ok = all(v for _, v in rows)
    return ("pass" if ok else "fail"), time.time() - t0, [], {"form": "audio", "measured": measured,
                                                              "checks": {"gains": rows}}


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
            pending = spec["cases"][c].get("pending")
            if pending:
                report["results"][r][c] = {"status": "pending", "reason": pending, "notes": []}
                print(f"{r:3s} {c:22s} pending ({pending[:90]})", flush=True)
                continue
            if "captions" in spec["cases"][c]:
                st, dt, notes, detail = captions(r, c, spec["cases"][c]["captions"])
                report["results"][r][c] = {"status": st, "seconds": round(dt, 2), "notes": notes, **detail}
                print(f"{r:3s} {c:22s} {st:5s} {dt:6.1f}s captions " + ("; ".join(notes)[:110] if st == "error" else ""), flush=True)
                continue
            if "audio" in spec["cases"][c]:
                st, dt, notes, detail = audio(r, c, spec["cases"][c]["audio"])
                report["results"][r][c] = {"status": st, "seconds": round(dt, 2), "notes": notes, **detail}
                print(f"{r:3s} {c:22s} {st:5s} {dt:6.1f}s audio " + ("; ".join(notes)[:110] if st == "error" else ""), flush=True)
                continue
            if "findings" in spec["cases"][c]:
                st, dt, notes, detail = findings(r, c, spec["cases"][c]["findings"])
                report["results"][r][c] = {"status": st, "seconds": round(dt, 2), "notes": notes, **detail}
                print(f"{r:3s} {c:22s} {st:5s} {dt:6.1f}s findings " + ("; ".join(notes)[:110] if st == "error" else ""), flush=True)
                continue
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
    bad = [(r, c) for r, res in report["results"].items() for c, e in res.items() if e["status"] not in ("pass", "pending")]
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
            if e["status"] == "pending":
                cells.append("⏳ pending: " + e["reason"][:80])
            elif e["status"] == "pass":
                cells.append("✅")
            elif e["status"] == "error":
                cells.append("⛔ " + (e["notes"][0][:60] if e["notes"] else f"exit {e.get('exit')}"))
            elif e.get("form") in ("captions", "audio"):
                bad = [f"{k} {c}" for k, rows in e["checks"].items() for c, ok in rows if not ok]
                cells.append(f"❌ {e['form']}: " + "; ".join(bad))
            elif "checks" in e and "measured" not in e:
                bad = [f"{k} {c}" for k, rows in e["checks"].items() for c, ok in rows if not ok]
                cells.append("❌ findings: " + ", ".join(bad) + f" (reported {', '.join(e['reported']) or 'none'})")
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
