"""Tests of sr_core.scene.io: read, to_bytes, write (CONTRACT C7, SREP 0 section 4).

The small scene classes come from test_scene_runtime and are injected through ``classes=``.
"""
from __future__ import annotations

import os
import sys
import types
import xml.etree.ElementTree as ET
import xml.parsers.expat
from pathlib import Path
from typing import Any

import pytest

from sr_core.scene import io
from sr_core.scene._runtime import PI, Comment, Element, Text, Unknown
from sr_core.scene.errors import SchemaValueError
from test_scene_runtime import (ELEMENT_CLASSES, Bag, Expr, Item, Scene,  # noqa: F401
                                _codec_stand_in)

DECL = b'<?xml version="1.0" encoding="UTF-8"?>\n'

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<!-- before -->
<?proc data?>
<scene version="1.0" opacity="1.50">
  <!-- inside -->
  <a weight="1.50" id="a1"/>
  <b id="b1"/>
  <?inner x?>
  <c>
    <x id="x1" from="p"/>
    <expr lang="en">  1 + 2 </expr>
    <weird k="v">t<sub/>tail</weird>
  </c>
  <z attr="1"/>
</scene>
<!-- after -->
<?epi data?>
"""


def read(source: Any) -> Scene:
    return io.read(source, classes=ELEMENT_CLASSES)  # type: ignore[return-value]


def c14n(data: bytes | str) -> str:
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    return ET.canonicalize(xml_data=text, with_comments=True)


def prolog_epilog(raw: bytes) -> tuple[list[str], list[str]]:
    pre: list[str] = []
    post: list[str] = []
    state = {"depth": 0, "seen": False}
    parser = xml.parsers.expat.ParserCreate()

    def start(*_: Any) -> None:
        state["depth"] += 1
        state["seen"] = True

    def end(*_: Any) -> None:
        state["depth"] -= 1

    def comment(text: str) -> None:
        if state["depth"] == 0:
            (post if state["seen"] else pre).append(f"<!--{text}-->")

    def pi(target: str, data: str) -> None:
        if state["depth"] == 0:
            (post if state["seen"] else pre).append(f"<?{target} {data}?>")

    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CommentHandler, parser.ProcessingInstructionHandler = comment, pi
    parser.Parse(raw, True)
    return pre, post


def assert_same_document(out: bytes, original: bytes) -> None:
    assert c14n(out) == c14n(original)
    assert prolog_epilog(out) == prolog_epilog(original)


# ------------------------------------------------------------------------------------------ read

def test_read_bytes_picks_classes_by_parent_and_name() -> None:
    scene = read(SAMPLE)
    assert type(scene) is Scene
    assert [type(e) for e in scene.elements()] == [Item, Item, Bag, Unknown]
    bag = scene.find("c")
    assert [type(e) for e in bag.elements()] == [Item, Expr, Unknown]
    assert scene.find("a").xml_name == "a"


def test_read_from_str_path_and_pathlike(tmp_path: Path) -> None:
    target = tmp_path / "s.xml"
    target.write_bytes(SAMPLE)
    for source in (str(target), target):
        assert read(source).version == "1.0"


def test_read_keeps_lexical_form_and_attribute_order() -> None:
    scene = read(SAMPLE)
    assert scene.attributes() == {"version": "1.0", "opacity": "1.50"}
    assert scene.opacity == 1.5
    a = scene.find("a")
    assert list(a.attributes()) == ["weight", "id"]
    assert a.attributes()["weight"] == "1.50"


def test_read_unknown_elements_keep_name_attributes_children() -> None:
    scene = read(SAMPLE)
    weird = scene.find("c").find("weird")
    assert isinstance(weird, Unknown)
    assert weird.attributes() == {"k": "v"}
    assert isinstance(weird.find("sub"), Unknown)
    assert weird.content == "ttail"
    assert weird.xml_path == "/scene/c/weird"
    z = scene.find("z")
    assert isinstance(z, Unknown) and z.attributes() == {"attr": "1"}


def test_read_undeclared_attribute_on_known_element_is_kept() -> None:
    scene = read(b'<scene version="1.0" mystery="m"><a/></scene>')
    assert scene.attributes() == {"version": "1.0", "mystery": "m"}


def test_read_does_not_validate() -> None:
    scene = read(b'<scene version="1.0"><a weight="heavy"/><a/><a/></scene>')
    assert len(scene.find_all("a")) == 3
    assert scene.find("a").weight == "heavy"


def test_read_records_comments_and_pis_inside_the_root() -> None:
    scene = read(SAMPLE)
    kinds = [type(n).__name__ for n in scene.nodes]
    assert "Comment" in kinds and "PI" in kinds and "Text" in kinds
    comment = next(n for n in scene.nodes if isinstance(n, Comment))
    assert comment.text == " inside "
    pi = next(n for n in scene.nodes if isinstance(n, PI))
    assert (pi.target, pi.data) == ("inner", "x")


def test_read_keeps_whitespace_text_nodes() -> None:
    scene = read(SAMPLE)
    assert isinstance(scene.nodes[0], Text) and scene.nodes[0].text == "\n  "
    expr = scene.find("c").find("expr")
    assert expr.content == "  1 + 2 "


def test_read_captures_prolog_and_epilog() -> None:
    scene = read(SAMPLE)
    assert [type(n).__name__ for n in scene._pre] == ["Comment", "PI"]
    assert [type(n).__name__ for n in scene._post] == ["Comment", "PI"]
    assert scene._pre[0].text == " before "
    assert scene._post[1].target == "epi"


def test_read_source_line_and_column() -> None:
    scene = read(SAMPLE)
    assert (scene.source_line, scene.source_column) == (4, 1)
    a = scene.find("a")
    assert (a.source_line, a.source_column) == (6, 3)
    x = scene.find("c").find("x")
    assert (x.source_line, x.source_column) == (10, 5)


def test_read_malformed_xml_raises_parse_error() -> None:
    with pytest.raises(ET.ParseError):
        read(b"<scene><a></scene>")
    with pytest.raises(ET.ParseError):
        read(b"")


def test_read_unknown_root() -> None:
    root = read(b"<other/>")
    assert isinstance(root, Unknown) and root.xml_name == "other"


def test_read_with_default_classes_uses_generated(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("sr_core.scene._generated")
    fake.ELEMENT_CLASSES = ELEMENT_CLASSES  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sr_core.scene._generated", fake)
    assert type(io.read(b'<scene version="1.0"/>')) is Scene


def test_read_returned_elements_have_owners() -> None:
    scene = read(SAMPLE)
    for el in scene.iter():
        if el is not scene:
            assert el.owner is not None
    assert scene.owner is None
    assert scene.find("c").find("x").owner is scene.find("c")


# ------------------------------------------------------------------------------------------ preserve

def test_preserve_roundtrip_is_c14n_equal_with_prolog_and_epilog() -> None:
    out = io.to_bytes(read(SAMPLE))
    assert_same_document(out, SAMPLE)
    assert out.startswith(DECL)


def test_preserve_roundtrip_is_stable() -> None:
    once = io.to_bytes(read(SAMPLE))
    assert io.to_bytes(read(once)) == once


def test_preserve_keeps_lexical_form_and_attribute_order() -> None:
    out = io.to_bytes(read(SAMPLE))
    assert b'opacity="1.50"' in out
    assert b'<a weight="1.50" id="a1"/>' in out


def test_preserve_keeps_whitespace_exactly() -> None:
    raw = b'<scene version="1.0">\n\t<a/>\n\n   <b/>  </scene>'
    out = io.to_bytes(read(raw))
    assert out == DECL + raw + b"\n"


def test_preserve_keeps_stored_order_of_children() -> None:
    raw = b'<scene version="1.0"><b/><a/></scene>'
    assert io.to_bytes(read(raw)) == DECL + raw + b"\n"


def test_preserve_escapes_text_and_attributes() -> None:
    scene = read(b'<scene version="a &amp; &lt;&quot;"><c><expr>1 &lt; 2 &amp; 3 &gt; 2</expr></c></scene>')
    out = io.to_bytes(scene)
    assert_same_document(out, b'<scene version="a &amp; &lt;&quot;"><c><expr>1 &lt; 2 &amp; 3 &gt; 2</expr></c></scene>')
    assert scene.version == 'a & <"'
    scene.version = "tab\tnew\nline"
    again = read(io.to_bytes(scene))
    assert again.version == "tab\tnew\nline"


def test_preserve_non_ascii_is_utf8() -> None:
    raw = '<scene version="1.0"><c><expr>café — \U0001f600</expr></c></scene>'.encode("utf-8")
    out = io.to_bytes(read(raw))
    assert "café — \U0001f600".encode("utf-8") in out
    assert_same_document(out, raw)


def test_preserve_added_after_reading_goes_to_content_model_position() -> None:
    scene = read(b'<scene version="1.0">\n  <a id="a1"/>\n  <c/>\n</scene>')
    scene.add_b(id="b1")
    assert [e.xml_name for e in scene.elements()] == ["a", "b", "c"]
    assert io.to_bytes(scene) == (
        DECL + b'<scene version="1.0">\n  <a id="a1"/>\n  <b id="b1"/>\n  <c/>\n</scene>\n')


def test_unchanged_unknown_content_roundtrips() -> None:
    raw = b'<scene version="1.0"><a/><z q="1"><y>text<!--c--><w/></y></z></scene>'
    assert_same_document(io.to_bytes(read(raw)), raw)


def test_empty_elements_are_self_closed() -> None:
    assert b"<a/>" in io.to_bytes(read(b'<scene version="1.0"><a></a></scene>'))


def test_to_bytes_rejects_unknown_layout() -> None:
    with pytest.raises(ValueError):
        io.to_bytes(Scene(version="1.0"), layout="fancy")  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------ pretty

def test_pretty_exact_bytes_for_a_built_scene() -> None:
    scene = Scene(version="1.0")
    scene.add_b(weight=1.5, id="b1")
    scene.add_a(weight=0.25, id="a1", from_="p")
    bag = scene.add_c()
    bag.add_expr(lang="en").content = "1 + 2"
    bag.add_x(id="x1")
    scene.add_b(id="b2")
    assert io.to_bytes(scene, layout="pretty") == (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<scene version="1.0">\n'
        b'  <a id="a1" weight="0.25" from="p"/>\n'
        b'  <b id="b1" weight="1.5"/>\n'
        b'  <b id="b2"/>\n'
        b'  <c>\n'
        b'    <expr lang="en">1 + 2</expr>\n'
        b'    <x id="x1"/>\n'
        b'  </c>\n'
        b'</scene>\n')


def test_pretty_vs_preserve_attribute_order() -> None:
    scene = Scene(version="1.0")
    scene.add_a(weight=1, id="a1")
    assert b'<a weight="1" id="a1"/>' in io.to_bytes(scene)
    assert b'<a id="a1" weight="1"/>' in io.to_bytes(scene, layout="pretty")


def test_pretty_keeps_comments_with_their_following_sibling_and_sorts_sequence() -> None:
    raw = (b'<?xml version="1.0"?>\n<!--top-->\n<scene version="1.0">\n<b id="b1"/><!--about a--><?pi q?>'
           b'<a id="a1"/><!--tail--></scene>\n<!--end-->')
    out = io.to_bytes(read(raw), layout="pretty")
    assert out == (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<!--top-->\n'
        b'<scene version="1.0">\n'
        b'  <!--about a-->\n'
        b'  <?pi q?>\n'
        b'  <a id="a1"/>\n'
        b'  <b id="b1"/>\n'
        b'  <!--tail-->\n'
        b'</scene>\n'
        b'<!--end-->\n')


def test_pretty_unknown_elements_keep_their_place_after_predecessor() -> None:
    raw = b'<scene version="1.0"><b id="b1"/><z/><a id="a1"/></scene>'
    out = io.to_bytes(read(raw), layout="pretty")
    lines = [line.strip() for line in out.decode().splitlines()[2:-1]]
    assert lines == ['<a id="a1"/>', '<b id="b1"/>', "<z/>"]


def test_pretty_output_reads_back_to_the_same_tree_and_is_idempotent() -> None:
    scene = read(SAMPLE)
    out = io.to_bytes(scene, layout="pretty")
    again = read(out)
    assert sorted(e.xml_path for e in again.iter()) == sorted(e.xml_path for e in scene.iter())
    assert io.to_bytes(again, layout="pretty") == out


def test_pretty_keeps_mixed_text_inline() -> None:
    raw = b'<scene version="1.0"><a/><z>one<y/>two</z></scene>'
    out = io.to_bytes(read(raw), layout="pretty")
    assert b"<z>one<y/>two</z>" in out


def test_pretty_keeps_whitespace_only_simple_content() -> None:
    scene = Scene(version="1.0")
    scene.add_a()
    scene.add_c().add_expr().content = "   "
    assert b"<expr>   </expr>" in io.to_bytes(scene, layout="pretty")


# ------------------------------------------------------------------------------------------ write / auto

def test_write_to_path_and_file_object(tmp_path: Path) -> None:
    scene = read(SAMPLE)
    target = tmp_path / "out.xml"
    io.write(scene, target)
    assert target.read_bytes() == io.to_bytes(scene)
    other = tmp_path / "pretty.xml"
    io.write(scene, str(other), layout="pretty")
    assert other.read_bytes() == io.to_bytes(scene, layout="pretty")
    with open(tmp_path / "fh.xml", "wb") as handle:
        io.write(scene, handle)
    assert (tmp_path / "fh.xml").read_bytes() == io.to_bytes(scene)


def test_version_auto_writes_min_version(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("sr_core.scene.checks")
    fake.min_version = lambda scene: "1.4"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sr_core.scene.checks", fake)
    scene = Scene(version="auto")
    scene._api_auto = True  # what SceneBase does when "auto" is set through the API
    scene.add_a(id="a1")
    out = io.to_bytes(scene)
    assert b'<scene version="1.4">' in out
    assert scene.version == "auto"  # the scene itself is not changed
    assert b'version="1.4"' in io.to_bytes(scene, layout="pretty")


def test_version_explicit_is_not_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("sr_core.scene.checks")
    fake.min_version = lambda scene: pytest.fail("must not be called")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sr_core.scene.checks", fake)
    assert b'version="1.2"' in io.to_bytes(Scene(version="1.2"))


def test_version_auto_without_checks_module_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sr_core.scene.checks", None)  # makes the import fail
    scene = Scene(version="auto")
    scene._api_auto = True
    with pytest.raises(SchemaValueError):
        io.to_bytes(scene)


# ------------------------------------------------------------------------------------------ corpus

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.corpus
def test_corpus_roundtrip_is_c14n_equal() -> None:
    if os.environ.get("SR_SCENE_CORPUS") != "1":
        pytest.skip("set SR_SCENE_CORPUS=1 to run the corpus tests")
    try:
        __import__("sr_core.scene._generated")
    except ImportError:
        pytest.skip("sr_core.scene._generated is not importable yet")
    files = sorted(p for base in (ROOT / "conformance" / "cases", ROOT / "tests" / "fixtures")
                   for p in base.rglob("*.xml"))
    assert files, "no corpus files found"
    bad: list[str] = []
    skipped = 0
    for path in files:
        raw = path.read_bytes()
        try:
            want = c14n(raw)
            want_pro = prolog_epilog(raw)
        except (ET.ParseError, xml.parsers.expat.ExpatError, UnicodeDecodeError):
            skipped += 1  # not well-formed on purpose: nothing to round-trip
            continue
        out = io.to_bytes(io.read(raw))
        if c14n(out) != want or prolog_epilog(out) != want_pro:
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, f"{len(bad)} of {len(files)} documents differ ({skipped} skipped): {bad[:10]}"
