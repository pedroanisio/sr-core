#!/usr/bin/env python3
"""Score the probe scenes of SREP 12's benchmark catalogue (Appendix A; milestone 0) on an engine.

  python3 catalogue.py [--renderers rs] [--shots 1,2,...]      (also: python3 run.py --catalogue ...)

One probe per shot lives in cases/ as srep-0012-shot-NN-<slug>.xml (tools/srep12_cases.py writes them; its SHOTS
table is the catalogue). For each shot and renderer:

  1. strict render: the shot's check frame (0 unless its content needs time to appear) with --strict and the JSON
     envelope. "pass" when the engine reports success; "fallback"
     when it rendered the frame but reports items not rendered as authored (its `unsupported` list is kept);
     "error" otherwise.
  2. pixel checks: the probe's expected.json entry (the kit's forms: colour classes, regions, absent, coverage) on
     the frame of step 1, through run.py's measure and check.
  3. seek check (SREP 14 rule 5): frame `seek_frame` rendered alone equals, pixel for pixel, the same frame rendered
     after playing from frame 0 (`--frames 0..=N`).

The outcome of a shot, in order of precedence:

  error     a render failed or the document was rejected
  gap       the SHOTS table says no element states the shot's defining content (the probe holds the expressible part)
  degraded  the strict render reported a fallback
  wrong     a pixel check or the seek check failed
  custom    the SHOTS table says the probe reaches the shot only with work done outside the document
  native    strict pass, every check passed, seek check passed, no flag

A shot counts toward the catalogue only when native. The score is a measurement, so the exit status is 0 whenever every
selected probe was scored (1 when an expected entry is malformed or a renderer is unknown); out/catalogue.json and
out/catalogue.md hold the detail. Only the Rust engine is wired (RS_RENDER_BIN; SREP 25).
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run  # noqa: E402  (the kit runner: prepare, measure, check, RENDERERS)

OUTCOMES = ("native", "custom", "gap", "degraded", "wrong", "error")
STRICT = ("pass", "fallback", "error")
TIMEOUT = 900


def _rs_bin():
    return os.environ.get("RS_RENDER_BIN", "scene-render-rs")


# renderer -> (scene, png, frame) -> argv for the strict frame; (scene, png, frame) -> argv for one frame; (scene, pattern,
# last frame) -> argv playing frames 0..last into pattern (with %04d)
CATALOGUE_RENDERERS = {
    "rs": (lambda s, p, f: [_rs_bin(), "render", s, "-f", str(f), "-o", p, "--strict", "--format", "json"],
           lambda s, p, f: [_rs_bin(), "render", s, "-f", str(f), "-o", p],
           lambda s, p, f: [_rs_bin(), "render", s, "--frames", f"0..={f}", "-o", p]),
}


def shots_table():
    spec = importlib.util.spec_from_file_location("srep12_cases", os.path.join(HERE, "tools", "srep12_cases.py"))
    tools = os.path.join(HERE, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SHOTS


def classify(strict, checks_ok, seek_ok, shot):
    """The outcome of a shot from its strict verdict, its pixel checks, its seek check and its SHOTS entry."""
    if strict == "error":
        return "error"
    if shot.get("gap"):
        return "gap"
    if strict == "fallback":
        return "degraded"
    if not checks_ok or not seek_ok:
        return "wrong"
    if shot.get("custom"):
        return "custom"
    return "native"


def strict_verdict(stdout, code):
    """("pass" | "fallback" | "error", notes) from the engine's JSON envelope of a --strict render."""
    try:
        doc = json.loads(stdout)
    except ValueError:
        return "error", [stdout.strip()[:200] if stdout.strip() else f"exit status {code}"]
    if not isinstance(doc, dict) or doc.get("format") != "scene-render-cli/1":
        return "error", [f"unknown output format {(doc or {}).get('format') if isinstance(doc, dict) else None!r}"]
    if doc.get("ok") and code == 0:
        return "pass", list((doc.get("result") or {}).get("unsupported") or [])
    err = doc.get("error") or {}
    result = doc.get("result") or {}
    message = str(err.get("message", ""))
    if err.get("kind") == "failed" and message.startswith("--strict") and result.get("written"):
        return "fallback", list(result.get("unsupported") or [])
    return "error", [message or f"exit status {code}"]


def _run(argv, cwd, env):
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    except FileNotFoundError:
        return None, [f"{argv[0]} not found: set RS_RENDER_BIN or put scene-render-rs on PATH"]
    except subprocess.TimeoutExpired:
        return None, [f"timed out after {TIMEOUT} s"]
    return p, []


def _same_pixels(a, b):
    import numpy as np
    from PIL import Image
    x = np.asarray(Image.open(a).convert("RGB"))
    y = np.asarray(Image.open(b).convert("RGB"))
    if x.shape != y.shape:
        return False, f"sizes differ: {x.shape[1]}x{x.shape[0]} and {y.shape[1]}x{y.shape[0]}"
    diff = np.abs(x.astype(int) - y.astype(int)).max(axis=2)
    n = int((diff > 0).sum())
    return n == 0, (f"{n} pixels differ (largest difference {int(diff.max())} code values)" if n else "identical")


def score_shot(renderer, shot, case, entry, tol):
    """Score one shot; returns its report row."""
    _, _, env_add = run.RENDERERS[renderer]
    strict_cmd, frame_cmd, play_cmd = CATALOGUE_RENDERERS[renderer]
    env = {**os.environ, **env_add}
    d, scene = run.prepare(case, renderer)
    t0 = time.time()
    check_frame = int(shot.get("check_frame", 0))
    row = {"case": case, "slug": shot["slug"], "estimate": shot["estimate"], "check_frame": check_frame,
           "seek_frame": shot["seek_frame"], "strict": "error", "unsupported": [], "checks": [], "seek": None, "notes": []}
    for flag in ("custom", "gap"):
        if shot.get(flag):
            row[flag] = shot[flag]
    # 1. strict render of the check frame
    png = os.path.join(d, "strict.png")
    p, notes = _run(strict_cmd(scene, png, check_frame), d, env)
    if p is None:
        row["notes"] += notes
    else:
        verdict, info = strict_verdict(p.stdout, p.returncode)
        if verdict == "error" and not p.stdout.strip() and p.stderr.strip():
            info = [p.stderr.strip().splitlines()[-1][:200]]
        row["strict"] = verdict
        row["unsupported" if verdict != "error" else "notes"] += info
        if verdict != "error" and not os.path.exists(png):
            row["strict"] = "error"
            row["notes"].append("the engine reported success but wrote no frame")
    # 2. pixel checks on that frame
    checks_ok = False
    if row["strict"] != "error":
        meas = run.measure(png)
        rows = run.check(meas, entry, tol, png)
        row["checks"] = [{"check": c, "status": st, "expected": e, "measured": m} for c, st, e, m in rows]
        checks_ok = bool(rows) and all(r[1] == "pass" for r in rows)
        if not rows:
            row["notes"].append("no check ran")
    # 3. seek check
    seek_ok = False
    if row["strict"] != "error":
        n = shot["seek_frame"]
        alone = os.path.join(d, "alone.png")
        played = os.path.join(d, "played_%04d.png")
        p1, n1 = _run(frame_cmd(scene, alone, n), d, env)
        p2, n2 = _run(play_cmd(scene, played, n), d, env)
        target = played % n
        if p1 is None or p2 is None:
            row["notes"] += n1 + n2
            row["strict"] = "error"
        elif p1.returncode != 0 or p2.returncode != 0 or not os.path.exists(alone) or not os.path.exists(target):
            row["strict"] = "error"
            tail = ((p1.stderr if p1.returncode else p2.stderr).strip().splitlines() or [""])[-1][:200]
            row["notes"].append(f"seek check render failed (exit {p1.returncode}/{p2.returncode}): {tail}")
        else:
            seek_ok, why = _same_pixels(alone, target)
            row["seek"] = seek_ok
            if not seek_ok:
                row["notes"].append(f"seek check: frame {n} alone and after playing from 0 differ: {why}")
    row["outcome"] = classify(row["strict"], checks_ok, seek_ok, shot)
    row["seconds"] = round(time.time() - t0, 2)
    return row


def score(renderers, shots_arg=""):
    spec = json.load(open(os.path.join(HERE, "expected.json")))
    tol = spec["tolerance_px"]
    table = shots_table()
    wanted = {int(x) for x in shots_arg.split(",") if x.strip()} if shots_arg else {s["n"] for s in table}
    selected = [s for s in table if s["n"] in wanted]
    report = {"engine": {}, "results": {}, "problems": []}
    for r in renderers:
        if r not in CATALOGUE_RENDERERS:
            report["problems"].append(f"renderer {r!r} is not wired for the catalogue (only {sorted(CATALOGUE_RENDERERS)})")
            continue
        report["results"][r] = {}
        for s in selected:
            case = f"srep-0012-shot-{s['n']:02d}-{s['slug']}"
            entry = spec["cases"].get(case)
            if entry is None:
                report["problems"].append(f"{case}: not in expected.json (run tools/srep12_cases.py and make_cases.py)")
                continue
            problems = run.entry_problems(entry)
            if problems:
                report["problems"] += [f"{case}: expected.json: {p}" for p in problems]
                continue
            row = score_shot(r, s, case, entry, tol)
            report["results"][r][str(s["n"])] = row
            note = "; ".join(row["notes"] + [u[:60] for u in row["unsupported"][:2]])[:110]
            print(f"{r:3s} shot {s['n']:2d} {s['slug']:28s} {row['outcome']:8s} strict={row['strict']:8s} "
                  f"checks={'ok' if all(c['status'] == 'pass' for c in row['checks']) and row['checks'] else 'fail':4s} "
                  f"seek={str(row['seek']):5s} {row['seconds']:6.1f}s {note}".rstrip(), flush=True)
    return report, selected


def counts(rows):
    c = {o: 0 for o in OUTCOMES}
    for row in rows.values():
        c[row["outcome"]] += 1
    return c


def write_reports(report, selected):
    os.makedirs(run.OUT, exist_ok=True)
    md = ["# SREP 12 benchmark catalogue: measured statuses", "",
          "Outcome order: error, gap, degraded, wrong, custom, native (catalogue.py). A shot counts when native.", ""]
    for r, rows in report["results"].items():
        c = counts(rows)
        report.setdefault("counts", {})[r] = c
        md += [f"## {run.RENDERERS[r][0]}", "",
               f"{c['native']} of {len(rows)} shots native (custom {c['custom']}, gap {c['gap']}, degraded {c['degraded']}, "
               f"wrong {c['wrong']}, error {c['error']}).", "",
               "| # | shot | estimate | outcome | strict | checks | seek | notes |", "|---|---|---|---|---|---|---|---|"]
        for s in selected:
            row = rows.get(str(s["n"]))
            if row is None:
                continue
            checks = "pass" if row["checks"] and all(x["status"] == "pass" for x in row["checks"]) else \
                ("; ".join(f"{x['check']} {x['status']}" for x in row["checks"] if x["status"] != "pass") or "none")
            notes = "; ".join(row["notes"] + [row.get("custom", ""), row.get("gap", "")] + row["unsupported"][:2]).strip("; ")
            md.append(f"| {s['n']} | {s['slug']} | {s['estimate']} | {row['outcome']} | {row['strict']} | {checks} | "
                      f"{row['seek']} | {notes.replace('|', '/')} |")
        md.append("")
    json.dump(report, open(os.path.join(run.OUT, "catalogue.json"), "w"), indent=2)
    # a flat view for scripts: shots of the first renderer
    first = next(iter(report["results"].values()), {})
    json.dump({**report, "shots": first}, open(os.path.join(run.OUT, "catalogue.json"), "w"), indent=2)
    open(os.path.join(run.OUT, "catalogue.md"), "w").write("\n".join(md))


def score_and_report(renderers, shots_arg=""):
    report, selected = score(renderers, shots_arg)
    write_reports(report, selected)
    for r, rows in report["results"].items():
        c = counts(rows)
        print(f"catalogue: {c['native']} of {len(rows)} shots native (custom {c['custom']}, gap {c['gap']}, "
              f"degraded {c['degraded']}, wrong {c['wrong']}, error {c['error']}) on {run.RENDERERS[r][0]}", flush=True)
    for p in report["problems"]:
        print("problem: " + p, flush=True)
    return 1 if report["problems"] or not report["results"] else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--renderers", default="rs")
    ap.add_argument("--shots", default="", help="shot numbers to score, comma-separated; all when absent")
    a = ap.parse_args()
    return score_and_report(a.renderers.split(","), a.shots)


if __name__ == "__main__":
    sys.exit(main())
