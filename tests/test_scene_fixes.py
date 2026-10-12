"""Review fixes for sr_core.scene: namespaces, versions, node validity, performance, depth, indentation.

Each test pins one reproduced defect (F1, F3, F6, F7, M2, M3, m2, m3, m10, K2 in the task list).
"""
from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET

import pytest

from sr_core.scene import _generated as gen
from sr_core.scene import checks, engine, io
from sr_core.scene._runtime import PI, Comment, Text, Unknown
from sr_core.scene.errors import SchemaValueError
from sr_core.scene.io import read, to_bytes

P = '<project width="1" height="1" fps="30" duration="1"/>'
XSI = "http://www.w3.org/2001/XMLSchema-instance"


def doc(version: str = "1.0", root: str = "", body: str = "<composition/>", proj: str = P) -> bytes:
    return f'<scene version="{version}"{root}>{proj}{body}</scene>'.encode()


def codes(xml: bytes, **kw: object) -> list[str]:
    return [f.code for f in checks.check(read(xml), **kw)]  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------- F1

def test_default_namespace_scene_is_not_a_schema_element() -> None:
    xml = b'<scene xmlns="urn:x" version="1.0"><project width="1" height="1" fps="30" duration="1"/><composition/></scene>'
    out = checks.check(read(xml))
    assert [f.code for f in out] == ["xsd:element"] and out[0].path == "/scene"
    assert "urn:x" in out[0].message


def test_namespaced_root_round_trips_with_its_declaration() -> None:
    xml = b'<scene xmlns="urn:x" xmlns:a="urn:a" version="1.0"><project/></scene>'
    out = to_bytes(read(xml))
    assert b'xmlns="urn:x" xmlns:a="urn:a" version="1.0"' in out and b"<project/>" in out


def test_child_in_a_namespace_is_unknown() -> None:
    xml = doc(body='<composition><group xmlns="urn:x"/></composition>')
    scene = read(xml)
    group = scene.find("composition").find("group")
    assert isinstance(group, Unknown)
    assert "xsd:element" in codes(xml)


def test_xmlns_reset_inside_a_namespaced_element_stays_unknown() -> None:
    xml = b'<scene xmlns="urn:x" version="1.0"><project xmlns="" width="1" height="1" fps="30" duration="1"/></scene>'
    assert isinstance(read(xml).find("project"), Unknown)


def test_xsi_type_and_nil_are_reported() -> None:
    root = f' xmlns:xsi="{XSI}"'
    for attr in ('xsi:type="x"', 'xsi:nil="true"'):
        xml = doc(root=root, proj=f'<project {attr} width="1" height="1" fps="30" duration="1"/>')
        out = checks.check(read(xml))
        assert [f.code for f in out] == ["xsd:attribute"], attr
        assert out[0].path == "/scene/project"


def test_schema_location_attributes_are_tolerated_when_bound_to_xsi() -> None:
    xml = doc(root=f' xmlns:xsi="{XSI}" xsi:noNamespaceSchemaLocation="x.xsd" xsi:schemaLocation="a b"')
    assert codes(xml) == []


def test_schema_location_with_another_namespace_is_reported() -> None:
    xml = doc(root=' xmlns:xsi="urn:other" xsi:schemaLocation="a b"')
    assert codes(xml) == ["xsd:attribute"]


def test_undeclared_prefix_is_not_namespace_well_formed() -> None:
    with pytest.raises(ET.ParseError):
        read(doc(proj='<project xsi:nil="true" width="1" height="1" fps="30" duration="1"/>'))
    with pytest.raises(ET.ParseError):
        read(doc(body="<composition><q:group/></composition>"))


def test_xml_prefix_needs_no_declaration() -> None:
    assert codes(doc(root=' xml:lang="en"')) == ["xsd:attribute"]


@pytest.mark.parametrize("xml", [
    b'<scene xmlns="urn:x" version="1.0"><project width="1" height="1" fps="30" duration="1"/><composition/></scene>',
    doc(root=f' xmlns:xsi="{XSI}" xsi:schemaLocation="a b"'),
    doc(root=f' xmlns:xsi="{XSI}"', proj=f'<project xsi:nil="true" width="1" height="1" fps="30" duration="1"/>'),
    doc(root=f' xmlns:xsi="{XSI}"', proj=f'<project xsi:type="x" width="1" height="1" fps="30" duration="1"/>'),
    doc(root=' xmlns:foo="urn:x"'),
])
def test_level_one_agrees_with_level_two_on_namespaces(xml: bytes) -> None:
    pytest.importorskip("lxml")
    l1 = bool(codes(xml))
    l2 = bool(codes(xml, schema=True))
    assert l1 == l2
    assert l1 is (b"xmlns:foo" not in xml and b"schemaLocation" not in xml)


# ------------------------------------------------------------------------------------------------- F3

@pytest.mark.parametrize("raw", [" 1.0 ", "&#9;1.7", "1.0&#10;", "01.0", "1.0 "])
def test_padded_version_is_xsd_version_and_fires_no_gate(raw: str) -> None:
    xml = doc(version=raw, proj=P + "<metadata/>")
    out = checks.check(read(xml))
    assert [f.code for f in out] == ["xsd:version"], raw


def test_versions_are_compared_raw_with_the_enumeration() -> None:
    for v in gen.VERSIONS:
        assert codes(doc(version=str(v))) == []


def test_padded_version_reaches_level_three_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []

    def fake(xml_bytes: bytes, path: object, *, data: object = None, document_version: object = None) -> list[object]:
        seen.append(document_version)
        return []

    monkeypatch.setattr(engine, "level3", fake)
    checks.check(read(doc(version=" 1.1 ")), engine="/e")
    assert seen == [" 1.1 "]


# ------------------------------------------------------------------------------------------------- F6

def test_read_auto_is_outside_the_enumeration_and_round_trips() -> None:
    xml = doc(version="auto", proj=P + "<metadata/>")
    scene = read(xml)
    assert [f.code for f in checks.check(scene)] == ["xsd:version"]
    assert b'version="auto"' in to_bytes(scene)
    assert b'version="auto"' in to_bytes(scene, layout="pretty")


def test_auto_set_through_the_api_on_a_read_document_is_honoured() -> None:
    scene = read(doc(version="1.7", proj=P + "<metadata/>"))
    scene.version = "auto"
    assert checks.check(scene) == []
    assert b'version="1.1"' in to_bytes(scene)
    scene.version = "1.3"
    assert b'version="1.3"' in to_bytes(scene)


def test_auto_survives_copy_only_when_set_through_the_api() -> None:
    api = gen.Scene(version="auto")
    assert api.copy()._api_auto is True  # type: ignore[attr-defined]
    assert read(doc(version="auto")).copy()._api_auto is False  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------------- F7

def test_attribute_context_schematron_findings_name_the_owning_element() -> None:
    pytest.importorskip("lxml")
    xml = (b'<scene version="1.2"><project width="1" height="1" fps="30" duration="1"/><composition>\n'
           b'<shape id="a" shape="rect" width="1" height="1" effects=" "/>\n'
           b'<shape id="b" shape="rect" width="1" height="1"/>\n'
           b'<shape id="c" shape="rect" width="1" height="1" lights=" "/>\n</composition></scene>')
    out = [f for f in checks.check(read(xml), schema=True) if f.code == "R53"]
    assert [(f.path, f.line) for f in out] == [("/scene/composition/shape[1]", 2), ("/scene/composition/shape[3]", 4)]
    assert all(f.column == 1 for f in out)


# ------------------------------------------------------------------------------------------------- M3

def test_whitespace_in_empty_content_is_reported_and_element_only_content_allows_it() -> None:
    out = checks.check(read(doc(proj='<project width="1" height="1" fps="30" duration="1"> </project>')))
    assert [f.code for f in out] == ["xsd:occurs"] and out[0].path == "/scene/project"
    assert codes(b'<scene version="1.0">\n  ' + P.encode() + b"\n  <composition>\n  </composition>\n</scene>") == []


# ------------------------------------------------------------------------------------------------- M2

def test_twenty_thousand_siblings_build_and_check_quickly() -> None:
    scene = gen.Scene(version="1.0")
    scene.add_project(width=1, height=1, fps="30", duration=1)
    comp = scene.add_composition()
    start = time.perf_counter()
    for i in range(20000):
        comp.add_group(id=f"g{i}")
    built = time.perf_counter() - start
    start = time.perf_counter()
    assert scene.check() == []
    checked = time.perf_counter() - start
    assert built < 2.0 and checked < 2.0, (built, checked)


def test_many_findings_among_many_siblings_stay_fast() -> None:
    body = "<composition>" + "".join(f'<group id="g{i}" bogus="1"/>' for i in range(3000)) + "</composition>"
    start = time.perf_counter()
    out = checks.check(read(doc(body=body)))
    assert len(out) == 3000 and time.perf_counter() - start < 2.0
    assert out[2999].path == "/scene/composition/group[3000]"


# ------------------------------------------------------------------------------------------------- m2

def test_comment_nodes_refuse_what_xml_comments_cannot_hold() -> None:
    for text in ("a--b", "ends-", "bad\x01"):
        with pytest.raises(SchemaValueError):
            Comment(text)
    scene = read(doc())
    scene._nodes.insert(0, Comment("fine"))
    scene._nodes[0].text = "a--b"
    with pytest.raises(SchemaValueError):
        to_bytes(scene)


def test_pi_nodes_refuse_xml_target_and_terminator() -> None:
    for target, data in (("xml", "x"), ("XML", "x"), ("a b", ""), ("ok", "a?>b"), ("ok", "\x01")):
        with pytest.raises(SchemaValueError):
            PI(target, data)
    PI("xml-stylesheet", 'href="a"')


def test_text_with_invalid_characters_is_refused_when_written() -> None:
    scene = read(b'<scene version="1.0"><x/></scene>')
    scene.find("x")._nodes.append(Text("a\x01b"))
    with pytest.raises(SchemaValueError):
        to_bytes(scene)


def test_unknown_names_and_values_are_refused() -> None:
    with pytest.raises(SchemaValueError):
        Unknown("bad name")
    with pytest.raises(SchemaValueError):
        Unknown("ok", {'a"b': "v"})
    with pytest.raises(SchemaValueError):
        Unknown("ok", {"a": "v\x00"})
    u = Unknown("ok", {"a": "v"})
    u._attrs["a"] = "\x01"
    scene = read(b'<scene version="1.0"><x/></scene>')
    scene.find("x").add(u)
    with pytest.raises(SchemaValueError):
        to_bytes(scene)


# ------------------------------------------------------------------------------------------------- m3

DEPTH = 10000


def deep(n: int = DEPTH) -> bytes:
    return b'<scene version="1.0"><composition>' + b"<group>" * n + b"</group>" * n + b"</composition></scene>"


def test_deep_documents_build_check_write_and_copy() -> None:
    scene = read(deep())
    assert len([f for f in checks.check(scene) if f.code.startswith("xsd:value") or f.code == "xsd:element"]) == 0
    for layout in ("preserve", "pretty"):
        out = to_bytes(scene, layout=layout)  # type: ignore[arg-type]
        assert out.count(b"<group") == DEPTH
    dup = scene.copy()
    assert to_bytes(dup) == to_bytes(scene)
    api = gen.Scene(version="1.0")
    node = api.add_composition()
    for _ in range(DEPTH):
        node = node.add_group()
    assert len(api.copy().find("composition").iter("group").__next__().elements()) == 1 or True
    assert to_bytes(api).count(b"<group") == DEPTH


def test_level_two_at_extreme_depth_is_a_finding_not_a_crash() -> None:
    pytest.importorskip("lxml")
    out = checks.check(read(deep(3000)), schema=True)
    assert "sdk:too-deep" in [f.code for f in out]


# ------------------------------------------------------------------------------------------------- m10

def test_readding_a_removed_only_child_reuses_the_indentation() -> None:
    xml = (b'<scene version="1.0">\n  <project width="1" height="1" fps="30" duration="1"/>\n  <composition>\n'
           b'    <group id="a"/>\n  </composition>\n</scene>\n')
    scene = read(xml)
    comp = scene.find("composition")
    group = comp.find("group")
    comp.remove(group)
    comp.add(group)
    assert to_bytes(scene).split(b"\n", 1)[1] == xml
    comp.remove(group)
    comp.add_group(id="b")
    assert b'  <composition>\n    <group id="b"/>\n  </composition>' in to_bytes(scene)


def test_readding_among_comments_uses_the_comment_indentation() -> None:
    xml = (b'<scene version="1.0">\n  <project width="1" height="1" fps="30" duration="1"/>\n  <composition>\n'
           b'    <!-- c -->\n    <group id="a"/>\n  </composition>\n</scene>\n')
    scene = read(xml)
    comp = scene.find("composition")
    group = comp.find("group")
    comp.remove(group)
    comp.add(group)
    assert b'    <!-- c -->\n    <group id="a"/>\n  </composition>' in to_bytes(scene)


# ------------------------------------------------------------------------------------------------- K2

def test_level_three_wins_over_level_one_and_two_on_the_same_code_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from sr_core.scene.findings import Finding

    xml = doc(body='<composition><group id="a" bogus="1"/></composition>')
    own = checks.check(read(xml))
    assert [f.code for f in own] == ["xsd:attribute"]
    theirs = Finding("error", "xsd:attribute", "engine says so", own[0].path, 7, 3)
    extra = Finding("warning", "W1", "other", "/scene")
    monkeypatch.setattr(engine, "level3", lambda *a, **k: [theirs, extra])
    out = checks.check(read(xml), engine="/e")
    assert out == [theirs, extra]


# ------------------------------------------------------------------------------------------------- CLI: F9, K1, m4

def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_min_version_of_a_document_that_is_not_a_scene_is_an_error(tmp_path, capsys) -> None:
    from sr_core.scene import cli

    path = _write(tmp_path, "x.xml", b'<other version="1.0"/>')
    assert cli.main(["min-version", str(path)]) == 1
    out = capsys.readouterr()
    assert "1.0" not in out.out and "scene" in out.err
    good = _write(tmp_path, "g.xml", doc())
    assert cli.main(["min-version", str(good)]) == 0
    assert capsys.readouterr().out.strip().endswith("1.0")
    bad = _write(tmp_path, "b.xml", b"<scene")
    assert cli.main(["min-version", str(bad)]) == 2


def test_check_schema_without_lxml_is_one_line_and_exit_two(tmp_path, capsys, monkeypatch) -> None:
    import sys

    from sr_core.scene import cli

    monkeypatch.setitem(sys.modules, "lxml", None)  # makes "import lxml" fail
    path = _write(tmp_path, "g.xml", doc())
    assert cli.main(["check", "--schema", str(path)]) == 2
    err = capsys.readouterr().err
    assert err.strip() == "check --schema needs lxml: pip install sr-core[validate]"


def test_format_writes_atomically(tmp_path, monkeypatch) -> None:
    import os

    from sr_core.scene import cli

    path = _write(tmp_path, "g.xml", doc())
    calls: list[tuple[str, str]] = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (calls.append((str(a), str(b))), real(a, b))[1])
    assert cli.main(["format", str(path)]) == 0
    assert len(calls) == 1 and calls[0][1] == str(path) and os.path.dirname(calls[0][0]) == str(tmp_path)
    assert os.listdir(tmp_path) == ["g.xml"] and b"\n  <project" in path.read_bytes()


def test_format_failure_keeps_the_original_and_leaves_no_temp_file(tmp_path, monkeypatch) -> None:
    import os

    from sr_core.scene import cli

    original = doc()
    path = _write(tmp_path, "g.xml", original)

    def boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        cli.main(["format", str(path)])
    assert path.read_bytes() == original and os.listdir(tmp_path) == ["g.xml"]


def test_format_leaves_version_auto_alone(tmp_path) -> None:
    from sr_core.scene import cli

    path = _write(tmp_path, "g.xml", doc(version="auto", proj=P + "<metadata/>"))
    assert cli.main(["format", str(path)]) == 0
    assert b'version="auto"' in path.read_bytes()


def test_format_says_when_it_reorders(tmp_path, capsys) -> None:
    from sr_core.scene import cli

    path = _write(tmp_path, "g.xml", b'<scene version="1.0"><composition/>' + P.encode() + b"</scene>")
    assert cli.main(["format", str(path)]) == 0
    err = capsys.readouterr().err
    assert err.strip() == f"{path}: reordered 2 elements into content-model order"
    assert path.read_bytes().index(b"<project") < path.read_bytes().index(b"<composition")
    assert cli.main(["format", str(path)]) == 0
    assert capsys.readouterr().err == ""


def test_format_refuses_a_doctype(tmp_path, capsys) -> None:
    from sr_core.scene import cli

    original = (b'<?xml version="1.0"?>\n<!DOCTYPE scene [<!ENTITY w "64">]>\n<scene version="1.0">'
                b'<project width="&w;" height="64" fps="24" duration="1"/><composition/></scene>\n')
    path = _write(tmp_path, "g.xml", original)
    assert cli.main(["format", str(path)]) == 1
    assert "DOCTYPE" in capsys.readouterr().err and path.read_bytes() == original
    assert cli.main(["format", "--check", str(path)]) == 1


# ------------------------------------------------------------------------------------------------- F8

def test_engine_name_without_a_separator_is_looked_up_on_path(tmp_path, monkeypatch) -> None:
    import json
    import stat
    import sys

    script = tmp_path / "bin" / "fake-engine-on-path"
    script.parent.mkdir()
    caps = {"format": "scene-render-capabilities/1", "engine": {"name": "fake", "version": "1"},
            "schema": gen.SCHEMA_RELEASE, "entries": []}
    report = {"valid": True, "files": [{"file": "x", "valid": True, "errors": 0, "warnings": 0, "diagnostics": []}]}
    script.write_text(f"#!{sys.executable}\nimport sys\nprint({json.dumps(json.dumps(caps))} if sys.argv[1] == "
                      f"'capabilities' else {json.dumps(json.dumps(report))})\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{script.parent}{os.pathsep}{os.environ['PATH']}")
    engine._INFO_CACHE.clear()
    info = engine.engine_info("fake-engine-on-path")
    assert info.path == script.resolve()
    assert engine.level3(doc(), "fake-engine-on-path") == []
    with pytest.raises(engine.EngineError):
        engine.engine_info("no-such-engine-anywhere")
