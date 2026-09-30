"""sr_core.review: the PDF review sheet -- scene reading, sections, PNG decoding, PDF structure, frames, exit codes.

Offline and engine-free: frames are PNGs built here, and the render engine is a stand-in script selected through
VPKG_ENGINE_<ID>. The built-in (standard-library) image path is forced unless a test says otherwise, so the
output does not depend on whether Pillow is installed.
"""
from __future__ import annotations

import os
import re
import struct
import sys
import zlib

import pytest

from sr_core.review import pdf
from sr_core.review.cli import frame_name, main
from sr_core.review.scene import read, read_subtitles

SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<scene version="1.1">
  <project width="64" height="36" fps="24" duration="30"/>
  <output id="main" path="renders/out.mp4" codec="h264" container="mp4"/>
  <metadata title="Coração (test)" author="Desk" description="A scene about (brackets) and \\ slashes.">
    <meta name="thesis" value="Reviews stay in step with the scene."/>
  </metadata>
  <assets>
    <image id="img-a" src="a.png" width="4" height="4" credit="Someone" license="CC BY 4.0"/>
    <text id="t" text="hi" width="10" height="10" size="10"/>
  </assets>
  <markers>
    <marker id="c1" time="0" kind="chapter" label="Chapter one"/>
    <marker id="s1" time="0" kind="section" label="Opening"/>
    <marker id="s2" time="10" kind="section" label="Middle"/>
    <marker id="c2" time="18" kind="chapter" label="Chapter two"/>
    <marker id="s3" time="20" kind="section" duration="5" label="Late"/>
    <marker id="td" time="12" kind="todo" label="Fix the (second) title"/>
    <marker id="cu" time="21" kind="cue" label="VO in"/>
  </markers>
  <captions>
    <captionTrack id="en" language="en-US" src="subs.srt"/>
    <captionTrack id="pt" language="pt-BR">
      <cue start="1" end="2" text="Olá"/>
    </captionTrack>
  </captions>
  <composition><shape id="r" shape="rect" width="10" height="10"/></composition>
</scene>
"""
SRT = "1\n00:00:01,000 --> 00:00:02,500\nFirst <i>line</i>\nwrapped\n\n2\n00:00:11,000 --> 00:00:12,000\nSecond\n"


def png(width: int, height: int, ctype: int, rows: list[bytes], depth: int = 8, filters=None, plte: bytes = b"") -> bytes:
    """A PNG with the given raw rows, each filtered with filters[y] (0-4) as the PNG spec defines."""
    bpp = max(1, {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype] * depth // 8)
    raw, prev = bytearray(), bytes(len(rows[0]))
    for y, row in enumerate(rows):
        f = (filters or [0] * height)[y]
        out = bytearray()
        for i, v in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = [0, a, b, (a + b) >> 1, pdf._paeth(a, b, c)][f]
            out.append((v - pred) & 255)
        raw += bytes([f]) + out
        prev = row

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    body = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0))
    if plte:
        body += chunk(b"PLTE", plte)
    return b"\x89PNG\r\n\x1a\n" + body + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")


def pixels(img: pdf.Image) -> bytes:
    assert img.filter == "FlateDecode"
    data = zlib.decompress(img.data)
    if not img.params:
        return data
    # PDF PNG-predictor data: undo the per-row filters
    stride = img.width * img.colors
    return bytes(pdf._unfilter(data, img.height, stride, img.colors))


def objects(data: bytes) -> dict[int, bytes]:
    """Every object of a PDF, checking that the xref table points at each one."""
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF\n$", data).group(1))
    table = data[start:].split(b"trailer")[0].split(b"\n")
    count = int(table[1].split()[1])
    out = {}
    for i in range(1, count):
        off = int(table[2 + i][:10])
        assert data[off:].startswith(b"%d 0 obj\n" % i), f"xref entry {i} is off"
        out[i] = data[off:data.index(b"\nendobj\n", off)]
    return out


def page_texts(data: bytes) -> list[str]:
    objs = objects(data)
    texts = []
    for body in objs.values():
        if body.split(b"\n", 1)[1].startswith(b"<< /Filter /FlateDecode /Length"):
            raw = body.split(b"stream\n", 1)[1].rsplit(b"\nendstream", 1)[0]
            ops = zlib.decompress(raw)
            if b" Tj ET" in ops:
                strings = re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", ops)
                texts.append(" ".join(re.sub(rb"\\(.)", rb"\1", s).decode("cp1252") for s in strings))
    return texts


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "_with_pillow", lambda data, max_width: None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "scene.xml").write_text(SCENE, encoding="utf-8")
    (tmp_path / "subs.srt").write_text(SRT, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------------------------------------- scene

def test_sections_follow_section_markers_inside_chapters(project):
    rv = read(str(project / "scene.xml"))
    assert [(s.index, s.start, s.end, s.label, s.chapter) for s in rv.sections] == [
        (1, 0, 10, "Opening", "Chapter one"), (2, 10, 20, "Middle", "Chapter one"),
        (3, 20, 25, "Late", "Chapter two")]
    assert [m.id for m in rv.sections[1].markers] == ["td"]
    assert [m.id for m in rv.sections[2].markers] == ["cu"]
    assert rv.title == "Coração (test)"


def test_captions_come_from_the_first_track_or_the_named_language(project):
    rv = read(str(project / "scene.xml"))
    assert [(c.start, c.text) for c in rv.sections[0].cues] == [(1.0, "First line wrapped")]
    assert [c.text for c in rv.sections[1].cues] == ["Second"]
    pt = read(str(project / "scene.xml"), language="pt")
    assert [c.text for c in pt.sections[0].cues] == ["Olá"]


def test_sections_fall_back_to_chapters_groups_and_the_whole(project):
    only_chapters = SCENE.replace('kind="section"', 'kind="beat"')
    (project / "a.xml").write_text(only_chapters, encoding="utf-8")
    assert [(s.start, s.end, s.label) for s in read(str(project / "a.xml")).sections] == [
        (0, 18, "Chapter one"), (18, 30, "Chapter two")]
    groups = re.sub(r"<markers>.*</markers>", '<markers><marker id="m" time="4"/></markers>', SCENE, flags=re.S)
    groups = groups.replace('<composition>', '<composition><group id="g2" name="Two" startMarker="m" end="9"/>'
                                              '<group id="g1" start="1" end="4"/>')
    (project / "b.xml").write_text(groups, encoding="utf-8")
    assert [(s.start, s.end, s.label) for s in read(str(project / "b.xml")).sections] == [
        (1, 4, "g1"), (4, 9, "Two")]
    bare = re.sub(r"<markers>.*</markers>", "", SCENE, flags=re.S)
    (project / "c.xml").write_text(bare, encoding="utf-8")
    assert [(s.start, s.end) for s in read(str(project / "c.xml")).sections] == [(0, 30)]


def test_vtt_cues_are_read(tmp_path):
    p = tmp_path / "s.vtt"
    p.write_text("WEBVTT\n\nintro\n00:01.000 --> 00:02.000 align:start\n<v Ana>Hello</v>\n")
    assert [(c.start, c.end, c.text) for c in read_subtitles(str(p))] == [(1.0, 2.0, "Hello")]


# -------------------------------------------------------------------------------------------------- images

ROWS = [bytes((x * 37 + y * 11 + c * 5) & 255 for x in range(5) for c in range(3)) for y in range(5)]


@pytest.mark.parametrize("filters", [[0] * 5, [1] * 5, [2] * 5, [3] * 5, [4] * 5, [0, 1, 2, 3, 4]])
def test_png_filters_decode_exactly(filters):
    rgba = [bytes(v for x in range(5) for v in (*r[3 * x:3 * x + 3], 255)) for r in ROWS]
    img = pdf.read_png(png(5, 5, 6, rgba, filters=filters))       # decoded path (opaque alpha is dropped)
    assert (img.width, img.height, img.colors) == (5, 5, 3)
    assert pixels(img) == b"".join(ROWS)
    img = pdf.read_png(png(5, 5, 2, ROWS, filters=filters))       # PNG-predictor pass-through path
    assert img.params and pixels(img) == b"".join(ROWS)


def test_png_alpha_is_composited_over_white():
    img = pdf.read_png(png(2, 1, 6, [bytes([255, 0, 0, 0, 0, 0, 255, 128])]))
    assert pixels(img) == bytes([255, 255, 255, 127, 127, 255])   # transparent red -> white; half blue


def test_png_grey_palette_and_16_bit():
    assert pixels(pdf.read_png(png(2, 1, 0, [b"\x10\xf0"]))) == b"\x10\xf0"
    pal = pdf.read_png(png(2, 1, 3, [b"\x01\x00"], plte=b"\x00\x00\x00\xff\x80\x00"))
    assert pixels(pal) == b"\xff\x80\x00\x00\x00\x00"
    deep = pdf.read_png(png(1, 1, 2, [b"\x12\x34\x56\x78\x9a\xbc"], depth=16))
    assert pixels(deep) == b"\x12\x56\x9a"


def test_wide_images_are_reduced():
    rows = [bytes(range(30)) for _ in range(4)]
    img = pdf.read_png(png(10, 4, 2, rows), max_width=4)          # every 3rd pixel of every 3rd row
    assert (img.width, img.height) == (4, 2)
    assert pixels(img) == bytes([0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 28, 29]) * 2


def test_unsupported_images_say_why():
    with pytest.raises(pdf.ImageError, match="interlaced"):
        pdf.read_png(png(1, 1, 2, [b"\0\0\0"]).replace(b"\x08\x02\x00\x00\x00", b"\x08\x02\x00\x00\x01"))
    with pytest.raises(pdf.ImageError, match="not a PNG"):
        pdf.read_png(b"GIF89a")


def test_jpeg_is_embedded_as_is():
    sof = b"\xff\xc0\x00\x11\x08\x00\x02\x00\x03\x03" + b"\x01\x11\x00" * 3
    data = b"\xff\xd8\xff\xe0\x00\x04ab" + sof + b"\xff\xd9"
    img = pdf.read_jpeg(data)
    assert (img.width, img.height, img.colors, img.filter, img.data) == (3, 2, 3, "DCTDecode", data)


# ----------------------------------------------------------------------------------------------------- text

def test_text_is_winansi_with_escapes():
    assert pdf._literal("a(b)c\\") == b"(a\\(b\\)c\\\\)"
    assert pdf.encode("ção€β") == "ção€".encode("cp1252") + b"?"
    assert pdf.text_width("ab", 10) == (556 + 556) / 100
    assert all(pdf.text_width(line, 9) <= 60 for line in pdf.wrap("a long line of words to wrap here", 60, 9))
    assert pdf.wrap("Supercalifragilistic", 30, 9)[0] != "Supercalifragilistic"


# ---------------------------------------------------------------------------------------------------- output

def test_review_without_frames(project, capsys):
    out = project / "r.pdf"
    assert main([str(project / "scene.xml"), "-o", str(out)]) == 0
    data = out.read_bytes()
    assert data.startswith(b"%PDF-1.4") and b"/Count 5 " in data           # cover, 3 sections, closing
    texts = page_texts(data)
    assert "Coração (test)" in texts[0] and "A scene about (brackets) and \\ slashes." in texts[0]
    assert "Middle" in texts[2] and "Fix the (second) title" in texts[2] and "TO-DO" in texts[2]
    assert "no frame" in texts[1]
    assert "Someone" in texts[4] and "CC BY 4.0" in texts[4] and "Reviews stay in step" in texts[4]
    assert "3 sections, 0 frames" in capsys.readouterr().out


def test_review_is_reproducible_and_defaults_beside_the_scene(project):
    assert main([str(project / "scene.xml")]) == 0
    first = (project / "scene.review.pdf").read_bytes()
    assert main([str(project / "scene.xml")]) == 0
    assert (project / "scene.review.pdf").read_bytes() == first
    assert b"CreationDate" not in first


def test_frames_are_read_from_a_folder(project, capsys):
    frames = project / "frames"
    frames.mkdir()
    for t in (5.0, 15.0):                                         # middles of sections 1 and 2; 3 is missing
        (frames / f"{frame_name(t)}.png").write_bytes(png(2, 2, 2, [b"\xff\0\0\0\xff\0"] * 2))
    code = main([str(project / "scene.xml"), "-o", str(project / "r.pdf"), "--frames", str(frames)])
    assert code == 1
    data = (project / "r.pdf").read_bytes()
    assert data.count(b"/Subtype /Image") == 2
    err = capsys.readouterr().err
    assert "section 03 at 22.5 s: not found" in err


def test_frames_are_rendered_with_the_engine_and_reused(project, monkeypatch, capsys):
    calls = project / "calls.txt"
    engine = project / "engine.py"
    frame = png(2, 2, 2, [b"\0\0\xff\0\0\xff"] * 2)
    engine.write_text(
        "import sys\n"
        f"open({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"open(sys.argv[sys.argv.index('-o') + 1], 'wb').write({frame!r})\n")
    monkeypatch.setenv("VPKG_ENGINE_RS", f"{sys.executable} {engine}")
    args = [str(project / "scene.xml"), "-o", str(project / "r.pdf"), "--engine", "rs", "--at", "start"]
    assert main(args) == 0
    lines = calls.read_text().splitlines()
    assert [ln.split()[:1] + ln.split()[2:4] for ln in lines] == [
        ["render", "--time", "0"], ["render", "--time", "10"], ["render", "--time", "20"]]
    assert sorted(os.listdir(project / "r.frames")) == [f"{frame_name(t)}.png" for t in (0, 10, 20)]
    assert main(args) == 0 and len(calls.read_text().splitlines()) == 3      # frames reused
    assert (project / "r.pdf").read_bytes().count(b"/Subtype /Image") == 3


def test_a_failing_engine_leaves_placeholders(project, monkeypatch, capsys):
    engine = project / "bad.py"
    engine.write_text("import sys\nprint('GPU on fire', file=sys.stderr)\nsys.exit(3)\n")
    monkeypatch.setenv("VPKG_ENGINE_RS", f"{sys.executable} {engine}")
    assert main([str(project / "scene.xml"), "-o", str(project / "r.pdf"), "--engine", "rs"]) == 1
    assert "exit 3: GPU on fire" in capsys.readouterr().err
    assert "GPU on fire" in page_texts((project / "r.pdf").read_bytes())[1]


def test_nothing_is_written_when_it_cannot_be(project, monkeypatch, capsys):
    monkeypatch.setenv("VPKG_ENGINE_RS", str(project / "no-such-engine"))
    assert main([str(project / "scene.xml"), "-o", str(project / "r.pdf"), "--engine", "rs"]) == 2
    assert main([str(project / "scene.xml"), "-o", str(project / "r.pdf"), "--engine", "js"]) == 2
    assert "has no still command" in capsys.readouterr().err
    (project / "x.xml").write_text("<notascene/>")
    assert main([str(project / "x.xml")]) == 2
    assert main([str(project / "missing.xml")]) == 2
    assert not (project / "r.pdf").exists()


def test_pillow_frames_are_jpeg_when_available(project, monkeypatch):
    pytest.importorskip("PIL")
    monkeypatch.undo()
    rows = [bytes(range(90)) for _ in range(10)]
    p = project / "wide.png"
    p.write_bytes(png(30, 10, 2, rows))
    img = pdf.read_image(str(p), max_width=12)
    assert (img.filter, img.width, img.height) == ("DCTDecode", 12, 4)
    assert pdf.read_image(str(p), max_width=12, pillow=False).filter == "FlateDecode"
