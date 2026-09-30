"""Command line: sr-review SCENE [-o OUT.pdf] [--engine ID] [--frames DIR] [--at middle|start] [--captions LANG]
(also python -m sr_core.review).

Writes a review sheet of a scene as a PDF: a cover with the scene's facts and outputs, one page per section with
a frame, its captions and its markers, then the open to-dos, sources and credits, and metadata. Standard library
only.

Frames: with --engine, each section's frame is rendered with that engine's still command (the same engine
commands as `scenerender-vpkg run`: ~/.config/scene-vpkg/engines.json or VPKG_ENGINE_<ID>) into --frames (default:
OUT.frames/ beside the PDF). A frame already there is reused. With --frames alone, frames are only read. Frame
files are named t<milliseconds, 8 digits>.png (or .jpg).

Exit status: 0 written; 1 written, but some frames are missing or failed to render; 2 nothing written (unreadable
scene, unknown engine command, bad options).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from fractions import Fraction

from .. import __version__
from ..vpkg.run import engine_config, missing_command
from . import pdf
from .scene import Review, SceneError, Section, clock, read

W, H = 842.0, 595.0          # A4 landscape, points
M = 36.0                     # margin
FRAME_W = 520.0
FRAME_PX = 1280             # widest frame embedded, pixels
COL_X = M + FRAME_W + 20
COL_W = W - M - COL_X
BOTTOM = H - M - 14          # above the footer


def frame_name(t: float) -> str:
    return f"t{round(t * 1000):08d}"


def find_frame(folder: str, t: float) -> str | None:
    for ext in (".png", ".jpg", ".jpeg"):
        p = os.path.join(folder, frame_name(t) + ext)
        if os.path.isfile(p):
            return p
    return None


def render_frame(engine: str, scene: str, t: float, fps: Fraction, to: str) -> str | None:
    """Render one still; returns an error message, or None when `to` was written."""
    cfg = engine_config(engine)
    if not cfg.get("still"):
        return f"engine {engine!r} has no still command"
    argv = cfg["command"] + [x.format(scene=scene, to=to, time=f"{t:g}", frame=round(t * fps), output="")
                             for x in cfg["still"]] + cfg.get("args", [])
    env = dict(os.environ, **cfg.get("env", {}))
    try:
        r = subprocess.run(argv, cwd=os.path.dirname(scene), env=env, capture_output=True, text=True)
    except OSError as e:
        return f"{argv[0]}: {e}"
    if r.returncode != 0 or not os.path.isfile(to):
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["no output"]
        return f"exit {r.returncode}: {tail[0]}"
    return None


class Flow:
    """Lines of text poured into column regions, adding continuation pages as needed."""

    def __init__(self, doc: pdf.Document, heading: str):
        self.doc, self.heading = doc, heading
        self.regions: list[tuple[float, float, float, float]] = []    # x, y, bottom, width
        self.page: pdf.Page | None = None
        self.y = 0.0

    def start(self, page: pdf.Page, regions: list[tuple[float, float, float, float]]) -> None:
        self.page, self.regions = page, list(regions)
        self.y = self.regions[0][1]

    def _room(self, h: float) -> None:
        while self.y + h > self.regions[0][2]:
            self.regions.pop(0)
            if not self.regions:
                page = self.doc.page(W, H)
                page.text(M, M + 12, f"{self.heading} (continued)", 12, "F2")
                half = (W - 2 * M - 20) / 2
                self.start(page, [(M, M + 36, BOTTOM, half), (M + half + 20, M + 36, BOTTOM, half)])
            else:
                self.y = self.regions[0][1]

    def para(self, text: str, size: float = 9, font: str = "F1", indent: float = 0, grey: float = 0,
             lead: str = "", gap: float = 2) -> None:
        x, _, _, w = self.regions[0]
        lw = pdf.text_width(lead, size, "F2") + 4 if lead else 0
        lines = pdf.wrap(text, w - indent - lw, size, font) if text else [""]
        for i, line in enumerate(lines):
            self._room(size * 1.3)
            x, _, _, w = self.regions[0]
            self.y += size * 1.3
            if lead and i == 0:
                self.page.text(x + indent, self.y, lead, size, "F2", grey)
            self.page.text(x + indent + lw, self.y, line, size, font, grey)
        self.y += gap

    def title(self, text: str) -> None:
        self._room(28)
        self.y += 8
        self.para(text, 11, "F2", gap=3)


def cover(doc: pdf.Document, rv: Review) -> None:
    page = doc.page(W, H)
    page.text(M, M + 22, rv.title, 22, "F2")
    page.text(M, M + 40, "Review sheet", 11, "F1", 0.4)
    page.line(M, M + 50, W - M, M + 50)
    flow = Flow(doc, rv.title)
    half = (W - 2 * M - 30) / 2
    flow.start(page, [(M, M + 58, BOTTOM, half), (M + half + 30, M + 58, BOTTOM, half)])
    for k, v in rv.facts:
        flow.para(v, lead=f"{k}:")
    if rv.outputs:
        flow.title("Outputs")
        for o in rv.outputs:
            flow.para(o)
    if rv.notes:
        flow.title("Not read")
        for n in rv.notes:
            flow.para(n, grey=0.3)
    flow.title("Sections")
    for s in rv.sections:
        where = f"{s.chapter} / {s.label}" if s.chapter else s.label
        flow.para(where, lead=f"{s.index:02d}  {clock(s.start)}-{clock(s.end)}")


def section_page(doc: pdf.Document, rv: Review, s: Section, frame: str | None, t: float, why: str | None,
                 aspect: float) -> None:
    page = doc.page(W, H)
    head = f"{s.index:02d}  {clock(s.start)}-{clock(s.end)}"
    page.text(M, M + 14, head, 13, "F2")
    page.text(M + pdf.text_width(head, 13, "F2") + 12, M + 14, s.label[:120], 13, "F2")
    if s.chapter:
        page.text(M, M + 30, s.chapter, 9, "F1", 0.4)
    top = M + 42
    fh = min(FRAME_W * aspect, BOTTOM - top - 30)
    fw = fh / aspect
    shown = False
    if frame:
        try:
            page.image(pdf.read_image(frame, FRAME_PX), M, top, fw, fh)
            shown = True
        except (OSError, pdf.ImageError) as e:
            why = f"{os.path.basename(frame)}: {e}"
    if not shown:
        page.rect(M, top, fw, fh, 0.9)
        page.text(M + 12, top + 20, "no frame", 10, "F2", 0.45)
        if why:
            for i, line in enumerate(pdf.wrap(why, fw - 24, 8)[:6]):
                page.text(M + 12, top + 34 + 11 * i, line, 8, "F1", 0.45)
    page.text(M, top + fh + 14, f"frame at {clock(t)} ({t:g} s)", 8, "F1", 0.4)

    flow = Flow(doc, f"{s.index:02d} {s.label}")
    flow.start(page, [(COL_X, top - 12, BOTTOM, COL_W), (M, top + fh + 24, BOTTOM, FRAME_W)])
    flow.title("Captions")
    if not s.cues:
        flow.para("none", grey=0.45)
    for c in s.cues:
        flow.para(f"{c.speaker + ': ' if c.speaker else ''}{c.text}", lead=clock(c.start))
    flow.title("Markers")
    if not s.markers:
        flow.para("none", grey=0.45)
    for m in s.markers:
        flow.para(m.label or m.id, lead=f"{clock(m.time)} {'TO-DO' if m.kind == 'todo' else m.kind}")


def closing(doc: pdf.Document, rv: Review) -> None:
    page = doc.page(W, H)
    flow = Flow(doc, "Open to-dos, sources and credits")
    half = (W - 2 * M - 30) / 2
    flow.start(page, [(M, M, BOTTOM, half), (M + half + 30, M, BOTTOM, half)])
    todos = [m for m in rv.markers if m.kind == "todo"]
    flow.title(f"Open to-dos ({len(todos)})")
    if not todos:
        flow.para("none", grey=0.45)
    for m in todos:
        flow.para(m.label or m.id, lead=clock(m.time))
    flow.title("Sources and credits")
    if not rv.credits:
        flow.para("none", grey=0.45)
    for aid, text in rv.credits:
        flow.para(text, lead=aid)
    if rv.meta:
        flow.title("Metadata")
        for k, v in rv.meta:
            flow.para(v, lead=f"{k}:")


def build(rv: Review, frames: dict[int, tuple[str | None, float, str | None]], aspect: float) -> bytes:
    doc = pdf.Document(title=f"{rv.title}: review sheet", producer=f"sr-review {__version__}")
    cover(doc, rv)
    for s in rv.sections:
        path, t, why = frames[s.index]
        section_page(doc, rv, s, path, t, why, aspect)
    closing(doc, rv)
    n = len(doc.pages)
    for i, p in enumerate(doc.pages, 1):
        foot = f"{rv.title}  -  {i} / {n}"
        p.text(W - M - pdf.text_width(foot, 8), H - M + 8, foot, 8, "F1", 0.45)
    return doc.tobytes()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sr-review", description="Review sheet (PDF) of a scene-render scene.")
    ap.add_argument("--version", action="version", version=f"sr-review {__version__}")
    ap.add_argument("scene", help="scene document")
    ap.add_argument("-o", "--out", help="PDF to write (default: SCENE with .review.pdf)")
    ap.add_argument("--engine", help="render each section's frame with this engine's still command (py, rs, c, ...)")
    ap.add_argument("--frames", help="folder of frames to read, and to render into with --engine "
                                     "(default with --engine: OUT.frames)")
    ap.add_argument("--at", choices=("middle", "start"), default="middle",
                    help="which moment of each section the frame shows (default: middle)")
    ap.add_argument("--captions", metavar="LANG", help="caption track by language tag prefix (default: the first)")
    a = ap.parse_args(argv)

    scene = os.path.abspath(a.scene)
    try:
        rv = read(scene, a.captions)
    except SceneError as e:
        print(f"sr-review: {e}", file=sys.stderr)
        return 2
    out = a.out or (os.path.splitext(scene)[0].removesuffix(".scene") + ".review.pdf")
    folder = a.frames or (os.path.splitext(out)[0] + ".frames" if a.engine else None)
    if a.engine:
        cfg = engine_config(a.engine)
        problem = (None if cfg.get("still") else f"engine {a.engine!r} has no still command") or \
            missing_command(cfg["command"], a.engine)
        if problem:
            print(f"sr-review: {problem}", file=sys.stderr)
            return 2
        os.makedirs(folder, exist_ok=True)

    import xml.etree.ElementTree as ET
    proj = next(e for e in ET.parse(scene).getroot() if e.tag.rsplit("}", 1)[-1] == "project")
    try:
        fps = Fraction(proj.get("fps") or "30")
        aspect = float(proj.get("height")) / float(proj.get("width"))
    except (TypeError, ValueError, ZeroDivisionError):
        fps, aspect = Fraction(30), 9 / 16

    frames, missing = {}, 0
    for s in rv.sections:
        t = s.frame_time(a.at, rv.duration)
        path, why = (find_frame(folder, t) if folder else None), None
        if folder and not path:
            if a.engine:
                to = os.path.join(os.path.abspath(folder), frame_name(t) + ".png")
                why = render_frame(a.engine, scene, t, fps, to)
                path = None if why else to
            else:
                why = f"not found: {os.path.join(folder, frame_name(t))}.png"
            if why:
                missing += 1
                print(f"sr-review: section {s.index:02d} at {t:g} s: {why}", file=sys.stderr)
        frames[s.index] = (path, t, why)

    data = build(rv, frames, aspect)
    try:
        with open(out, "wb") as f:
            f.write(data)
    except OSError as e:
        print(f"sr-review: {e}", file=sys.stderr)
        return 2
    shown = sum(1 for p, _, _ in frames.values() if p)
    print(f"wrote {out}: {len(rv.sections)} sections, {shown} frames"
          + (f", {missing} missing" if missing else ""))
    return 1 if missing else 0
