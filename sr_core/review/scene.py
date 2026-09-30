"""What a review shows, read from a scene document: facts, sections, captions, markers and credits.

Sections come from the first of these that the scene has:
  1. `section` markers, each inside the latest `chapter` marker at or before it;
  2. `chapter` markers;
  3. the top-level groups and sequences of the composition, with their windows (`start`/`end`, or
     `startMarker`/`endMarker`);
  4. the whole duration.
A section ends at its marker's `duration` when that is set, else where the next one starts, else at the end.
"""
from __future__ import annotations

import hashlib
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

TIMED = ("cue", "beat", "comment", "todo", "cta")


class SceneError(ValueError):
    pass


@dataclass
class Marker:
    id: str
    time: float
    kind: str
    label: str
    duration: float = 0.0


@dataclass
class Cue:
    start: float
    end: float
    text: str
    speaker: str = ""


@dataclass
class Section:
    index: int
    start: float
    end: float
    label: str
    chapter: str = ""
    markers: list[Marker] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)

    def frame_time(self, at: str, duration: float) -> float:
        t = self.start if at == "start" else (self.start + self.end) / 2
        return max(0.0, min(t, duration - 1e-3))


@dataclass
class Review:
    path: str
    sha256: str
    title: str
    facts: list[tuple[str, str]]
    outputs: list[str]
    sections: list[Section]
    markers: list[Marker]
    credits: list[tuple[str, str]]
    meta: list[tuple[str, str]]
    notes: list[str]
    duration: float


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(e, name: str):
    return [c for c in e if _local(c.tag) == name] if e is not None else []


def _all(e) -> list:
    return list(e) if e is not None else []


def _kid(e, name: str):
    k = _kids(e, name)
    return k[0] if k else None


def _float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def clock(t: float) -> str:
    s = max(0.0, t)
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


_TIME = re.compile(r"(?:(\d+):)?(\d+):(\d+)[.,](\d+)")


def _stamp(s: str) -> float:
    m = _TIME.search(s)
    if not m:
        raise ValueError(s)
    h, mi, se, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(frac) / 10 ** len(frac)


def read_subtitles(path: str) -> list[Cue]:
    """SRT or WebVTT cues (text lines joined with a space; tags removed)."""
    with open(path, encoding="utf-8-sig") as f:
        blocks = re.split(r"\n\s*\n", f.read().replace("\r\n", "\n"))
    cues = []
    for b in blocks:
        lines = [x for x in b.strip().split("\n") if x.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, _, z = line.partition("-->")
                text = " ".join(re.sub(r"<[^>]+>", "", x).strip() for x in lines[i + 1:])
                cues.append(Cue(_stamp(a), _stamp(z), text))
                break
    return cues


def _cues(root, base: str, language: str | None, notes: list[str]) -> list[Cue]:
    tracks = _kids(_kid(root, "captions"), "captionTrack")
    if language:
        tracks = [t for t in tracks if (t.get("language") or "").lower().startswith(language.lower())]
    if not tracks:
        return []
    t = tracks[0]
    cues = []
    for c in _kids(t, "cue"):
        text = c.get("text") or " ".join(w.get("text", "") for w in _kids(c, "word"))
        cues.append(Cue(_float(c.get("start")), _float(c.get("end")), text.strip(), c.get("speaker") or ""))
    src = t.get("src")
    if src:
        fmt = (t.get("format") or os.path.splitext(src)[1][1:]).lower()
        if fmt in ("srt", "vtt"):
            try:
                cues += read_subtitles(os.path.join(base, src))
            except (OSError, ValueError, UnicodeDecodeError) as e:
                notes.append(f"captions {t.get('id')}: cannot read {src} ({e})")
        else:
            notes.append(f"captions {t.get('id')}: {fmt} files are not read")
    elif t.get("transcribe") and not cues:
        notes.append(f"captions {t.get('id')}: transcribed captions are not read")
    return sorted(cues, key=lambda c: c.start)


def _group_sections(root, markers: dict[str, float], duration: float) -> list[Section]:
    out = []
    for e in _all(_kid(root, "composition")):
        if _local(e.tag) not in ("group", "sequence"):
            continue
        start = markers.get(e.get("startMarker"), _float(e.get("start")))
        end = markers.get(e.get("endMarker"), _float(e.get("end"), duration))
        out.append(Section(0, start, end, e.get("name") or e.get("id") or _local(e.tag)))
    out.sort(key=lambda s: s.start)
    return out


def read(path: str, language: str | None = None) -> Review:
    try:
        with open(path, "rb") as f:
            raw = f.read()
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError) as e:
        raise SceneError(f"{path}: {e}") from None
    if _local(root.tag) != "scene":
        raise SceneError(f"{path}: not a scene document (root is <{_local(root.tag)}>)")
    base = os.path.dirname(os.path.abspath(path))
    notes: list[str] = []
    project = _kid(root, "project")
    if project is None:
        raise SceneError(f"{path}: no <project>")
    duration = _float(project.get("duration"))
    md = _kid(root, "metadata")
    meta = [(m.get("name", ""), m.get("value", "")) for m in _kids(md, "meta")]
    title = (md.get("title") if md is not None else None) or dict(meta).get("title") or \
        os.path.splitext(os.path.basename(path))[0]

    markers = sorted((Marker(m.get("id") or "", _float(m.get("time")), m.get("kind") or "cue", m.get("label") or "",
                             _float(m.get("duration")))
                      for m in _kids(_kid(root, "markers"), "marker")), key=lambda m: m.time)
    by_id = {m.id: m.time for m in markers if m.id}

    def from_markers(kind: str) -> list[Section]:
        return [Section(0, m.time, m.time + m.duration if m.duration > 0 else -1, m.label or m.id)
                for m in markers if m.kind == kind]

    sections = from_markers("section") or from_markers("chapter")
    if sections:
        chapters = [m for m in markers if m.kind == "chapter"] if any(m.kind == "section" for m in markers) else []
        for i, s in enumerate(sections):
            nxt = sections[i + 1].start if i + 1 < len(sections) else duration
            if s.end < 0:
                s.end = nxt
            s.chapter = next((c.label or c.id for c in reversed(chapters) if c.time <= s.start + 1e-9), "")
    else:
        sections = _group_sections(root, by_id, duration) or [Section(0, 0.0, duration, "Whole video")]
    for i, s in enumerate(sections, 1):
        s.index = i

    cues = _cues(root, base, language, notes)
    for s in sections:
        last = s is sections[-1]
        s.markers = [m for m in markers if m.kind in TIMED and s.start <= m.time and (m.time < s.end or last)]
        s.cues = [c for c in cues if s.start <= c.start and (c.start < s.end or last)]

    facts = [("Document", os.path.basename(path)),
             ("SHA-256", hashlib.sha256(raw).hexdigest()),
             ("Format", f"scene {root.get('version', '?')}"),
             ("Picture", f"{project.get('width')} x {project.get('height')}, {project.get('fps')} fps"),
             ("Duration", f"{clock(duration)} ({duration:g} s)")]
    if md is not None:
        facts += [(k.capitalize(), md.get(k)) for k in ("author", "description", "language", "created", "modified",
                                                         "revision") if md.get(k)]
    facts += [("Sections", str(len(sections))), ("Caption cues", str(len(cues))),
              ("Open to-dos", str(sum(m.kind == "todo" for m in markers)))]
    outputs = [" ".join(x for x in (o.get("id"), o.get("path"), o.get("codec"), o.get("container")) if x)
               for o in _kids(root, "output")]

    credits = []
    for a in _all(_kid(root, "assets")):
        kind = _local(a.tag)
        bits = [f"{kind} {a.get('src') or a.get('cache') or ''}".strip()]
        if kind == "generated":
            bits.append(f"made by {a.get('provider')} {a.get('model')}")
        bits += [f"{k}: {a.get(k)}" for k in ("credit", "license") if a.get(k)]
        if len(bits) > 1 or kind in ("image", "video", "audio", "font", "imageSequence", "mesh", "lottie"):
            credits.append((a.get("id") or "", "; ".join(bits)))
    return Review(path, hashlib.sha256(raw).hexdigest(), title, facts, outputs, sections, markers, credits, meta,
                  notes, duration)
