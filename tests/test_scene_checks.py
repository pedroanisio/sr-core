"""Tests of sr_core.scene.checks: levels 1-3, min_version, new_id, the integrity check and the Scene API.

SREP 0 sections 4.4, 4.5, 6 and 9 (D8); CONTRACT C0, C3, C9.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from sr_core.scene import _generated as gen
from sr_core.scene import checks, gates, io
from sr_core.scene._runtime import Attr, Element, SceneBase
from sr_core.scene.errors import IntegrityError, SchemaValueError
from sr_core.scene.findings import Finding
from sr_core.scene.io import read

PROJECT = '<project width="100" height="100" fps="1" duration="1"/>'


def doc(body: str = "", version: str = "1.1", head: str = "", tail: str = "", root_extra: str = "") -> bytes:
    return (f'<scene version="{version}"{root_extra}>{PROJECT}{head}<composition>{body}</composition>{tail}'
            f"</scene>").encode()


def codes(findings: list[Finding]) -> list[str]:
    return [f.code for f in findings]


def only(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]


def by_code(xml: bytes, code: str) -> list[Finding]:
    return only(checks.check(read(xml)), code)


# ------------------------------------------------------------------------------------------ level 1: clean

def test_clean_document_has_no_findings() -> None:
    assert checks.check(read(doc('<group id="g"/>'))) == []


def test_built_scene_is_clean() -> None:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=100, height=100, fps="1", duration=1)
    scene.add_composition().add_group(id="g")
    assert checks.check(scene) == []


def test_findings_are_finding_instances_with_error_severity() -> None:
    out = checks.check(read(doc("<bogus/>")))
    assert out and all(isinstance(f, Finding) and f.severity == "error" for f in out)


def test_namespace_declarations_and_xsi_attributes_are_not_undeclared_attributes() -> None:
    xml = doc(root_extra=' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="x.xsd"')
    assert checks.check(read(xml)) == []


# ------------------------------------------------------------------------------------------ xsd:element / xsd:occurs

def test_unknown_element_is_xsd_element_with_path_and_position() -> None:
    xml = b'<scene version="1.1">\n  <project width="100" height="100" fps="1" duration="1"/>\n' \
          b"  <composition>\n    <group id=\"g\"/>\n    <bogus/>\n  </composition>\n</scene>\n"
    found = only(checks.check(read(xml)), "xsd:element")
    assert len(found) == 1
    assert found[0].path == "/scene/composition/bogus"
    assert (found[0].line, found[0].column) == (5, 5)
    assert "bogus" in found[0].message


def test_unknown_element_children_are_not_judged() -> None:
    out = checks.check(read(doc('<bogus><group/><zzz q="1"/></bogus>')))
    assert codes(out) == ["xsd:element"]


def test_child_name_not_allowed_by_parent_is_xsd_element() -> None:
    # <project> is a known element of <scene>, but <composition> does not take it: read makes it Unknown
    out = by_code(doc("<project/>"), "xsd:element")
    assert [f.path for f in out] == ["/scene/composition/project"]


def test_missing_required_child_is_xsd_occurs() -> None:
    xml = f'<scene version="1.1">{PROJECT}</scene>'.encode()
    out = only(checks.check(read(xml)), "xsd:occurs")
    assert len(out) == 1 and out[0].path == "/scene" and "composition" in out[0].message


def test_children_in_the_wrong_order_are_xsd_occurs() -> None:
    xml = f'<scene version="1.1"><composition/>{PROJECT}</scene>'.encode()
    out = only(checks.check(read(xml)), "xsd:occurs")
    assert len(out) >= 1
    assert out[0].path in ("/scene/project", "/scene/composition", "/scene")


def test_too_many_of_a_single_child_is_xsd_occurs() -> None:
    xml = f'<scene version="1.1">{PROJECT}{PROJECT}<composition/></scene>'.encode()
    out = only(checks.check(read(xml)), "xsd:occurs")
    assert len(out) == 1 and out[0].path == "/scene/project[2]"


def test_unbounded_choice_accepts_any_mix_and_count() -> None:
    body = "".join(f'<group id="g{i}"/>' for i in range(30))
    assert checks.check(read(doc(body))) == []


def test_text_in_element_only_content_is_xsd_occurs() -> None:
    out = by_code(doc("hello"), "xsd:occurs")
    assert [f.path for f in out] == ["/scene/composition"]


def test_whitespace_and_comments_between_children_are_fine() -> None:
    assert checks.check(read(doc("  <!-- c -->\n  <?pi x?>  <group id=\"g\"/>\n"))) == []


def test_root_that_is_not_scene_is_xsd_element() -> None:
    out = checks.check(read(b"<other/>"))
    assert codes(out) == ["xsd:element"] and out[0].path == "/other"


def test_built_scene_missing_required_children() -> None:
    scene = gen.Scene(version="1.1")
    out = only(checks.check(scene), "xsd:occurs")
    assert len(out) == 1 and "project" in out[0].message and out[0].path == "/scene"
    assert out[0].line is None and out[0].column is None


# ------------------------------------------------------------------------------------------ attributes

def test_undeclared_attribute_is_xsd_attribute() -> None:
    out = by_code(doc('<group id="g" bogus="1"/>'), "xsd:attribute")
    assert len(out) == 1 and out[0].path == "/scene/composition/group" and "bogus" in out[0].message


def test_missing_required_attribute_is_xsd_required() -> None:
    out = by_code(doc("<group/>"), "xsd:required")
    assert len(out) == 1 and out[0].path == "/scene/composition/group" and "id" in out[0].message


def test_missing_version_is_xsd_required() -> None:
    xml = f"<scene>{PROJECT}<composition/></scene>".encode()
    out = only(checks.check(read(xml)), "xsd:required")
    assert [f.path for f in out] == ["/scene"]


def test_built_element_missing_required_attribute() -> None:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=100, height=100, fps="1", duration=1)
    scene.add_composition().add_group()
    out = only(checks.check(scene), "xsd:required")
    assert [f.path for f in out] == ["/scene/composition/group"]


def test_invalid_lexical_form_is_xsd_value() -> None:
    xml = f'<scene version="1.1"><project width="abc" height="100" fps="1" duration="1"/><composition/></scene>'
    out = only(checks.check(read(xml.encode())), "xsd:value")
    assert len(out) == 1 and out[0].path == "/scene/project" and "width" in out[0].message


def test_value_outside_a_facet_is_xsd_value() -> None:
    out = by_code(doc('<group id="g" opacity="1.5"/>'), "xsd:value")
    assert len(out) == 1 and "opacity" in out[0].message


def test_value_check_uses_the_stored_lexical_string() -> None:
    assert by_code(doc('<group id="g" opacity="0.50"/>'), "xsd:value") == []
    assert by_code(doc('<group id="g" opacity=" 0.5 "/>'), "xsd:value") == []  # whitespace is collapsed


def test_invalid_id_lexical_is_xsd_value() -> None:
    assert len(by_code(doc('<group id="1bad"/>'), "xsd:value")) == 1


def test_empty_idrefs_is_xsd_value() -> None:
    out = by_code(doc('<adjustment id="a" effects=" "/>'), "xsd:value")
    assert len(out) == 1 and "effects" in out[0].message


# ------------------------------------------------------------------------------------------ fixed, simple content

class Leaf(Element):
    __slots__ = ()
    _xsd_type = "leafType"
    _element_names = ("leaf",)
    _content = None
    _simple_content = "xs:positiveInteger"
    k = Attr("k", "xs:string", fixed="a")
    n = Attr("n", "xs:positiveInteger", use="required")


class Empty(Element):
    __slots__ = ()
    _xsd_type = "emptyType"
    _element_names = ("empty",)
    _content = None
    _simple_content = None


class Root(Element):
    __slots__ = ()
    _xsd_type = "rootType"
    _element_names = ("root",)
    _content = ("sequence", 1, 1, (("element", 1, -1, "leaf", "leafType"), ("element", 0, 1, "empty", "emptyType")))


TABLE = {(None, "root"): Root, ("rootType", "leaf"): Leaf, ("rootType", "empty"): Empty}


def synthetic(xml: str) -> Element:
    return io.read(xml.encode(), classes=TABLE)


def test_fixed_mismatch_is_xsd_value() -> None:
    out = checks.check(synthetic('<root><leaf n="1" k="b">4</leaf></root>'))
    assert codes(out) == ["xsd:value"] and "fixed" in out[0].message and out[0].path == "/root/leaf"


def test_fixed_match_is_clean() -> None:
    assert checks.check(synthetic('<root><leaf n="1" k="a">4</leaf></root>')) == []


def test_invalid_simple_content_is_xsd_value() -> None:
    out = checks.check(synthetic('<root><leaf n="1">-4</leaf></root>'))
    assert codes(out) == ["xsd:value"] and out[0].path == "/root/leaf"


def test_child_element_in_simple_content_is_xsd_element() -> None:
    out = checks.check(synthetic('<root><leaf n="1">4<x/></leaf></root>'))
    assert "xsd:element" in codes(out)


def test_children_and_text_in_empty_content() -> None:
    out = checks.check(synthetic('<root><leaf n="1">4</leaf><empty><x/></empty></root>'))
    assert codes(out) == ["xsd:element"]
    out = checks.check(synthetic('<root><leaf n="1">4</leaf><empty>text</empty></root>'))
    assert codes(out) == ["xsd:occurs"]


def test_generic_root_name_skips_version_logic() -> None:
    assert checks.check(synthetic('<root><leaf n="1">4</leaf></root>')) == []


# ------------------------------------------------------------------------------------------ ids and references

def test_duplicate_id_is_xsd_id_unique_at_the_second_use() -> None:
    out = by_code(doc('<group id="g"/><group id="g"/>'), "xsd:id-unique")
    assert len(out) == 1 and out[0].path == "/scene/composition/group[2]" and "g" in out[0].message


def test_duplicate_id_across_different_element_kinds() -> None:
    out = by_code(doc('<group id="x"/>', tail='<effects><effect id="x" type="blur"/></effects>'), "xsd:id-unique")
    assert len(out) == 1


def test_unique_ids_are_clean() -> None:
    assert by_code(doc('<group id="a"/><group id="b"/>'), "xsd:id-unique") == []


def test_dangling_idref_is_xsd_idref() -> None:
    out = by_code(doc('<group id="a" parent="nope"/>'), "xsd:idref")
    assert len(out) == 1 and out[0].path == "/scene/composition/group" and "nope" in out[0].message


def test_resolving_idref_is_clean() -> None:
    assert by_code(doc('<group id="a"/><group id="b" parent="a"/>'), "xsd:idref") == []


def test_forward_reference_resolves() -> None:
    assert by_code(doc('<group id="b" parent="a"/><group id="a"/>'), "xsd:idref") == []


def test_idrefs_each_token_is_resolved() -> None:
    head = '<effects><effect id="e1" type="blur"/></effects>'
    ok = doc('<adjustment id="a" effects="e1"/>', tail=head)
    assert by_code(ok, "xsd:idref") == []
    bad = doc('<adjustment id="a" effects="e1   nope\n e1"/>', tail=head)
    out = by_code(bad, "xsd:idref")
    assert len(out) == 1 and "nope" in out[0].message


def test_idref_to_an_id_on_an_unknown_element_does_not_resolve() -> None:
    out = by_code(doc('<bogus id="x"/><group id="a" parent="x"/>'), "xsd:idref")
    assert len(out) == 1


def test_built_scene_reference_by_element() -> None:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=100, height=100, fps="1", duration=1)
    comp = scene.add_composition()
    a = comp.add_group(id="a")
    comp.add_group(id="b", parent=a)
    assert checks.check(scene) == []
    a.id = "renamed"  # the stored reference is the old id: now dangling
    assert codes(checks.check(scene)) == ["xsd:idref"]


PROGRAM = '<program id="p" src="m.wasm" sha256="%s"%s/>' % ("0" * 64, "%s")


def test_references_are_not_judged_when_a_build_program_may_have_emitted_the_target() -> None:
    # SREP 59 / SREP 87: a reference to an id a program emits (bare, or namespaced P.E) is left to the engine
    prog = PROGRAM % ""
    assert by_code(doc(prog + '<group id="a" parent="p.g1"/>', version="1.6"), "xsd:idref") == []
    assert by_code(doc(prog + '<group id="a" parent="g1"/>', version="1.6"), "xsd:idref") == []


def test_step_programs_emit_no_ids_so_references_are_still_judged() -> None:
    prog = PROGRAM % ' mode="step" width="4" height="4"'
    out = by_code(doc(prog + '<group id="a" parent="g1"/>', version="1.6"), "xsd:idref")
    assert len(out) == 1


def test_data_programs_emit_no_ids() -> None:
    head = '<parameters><program id="d" src="m.wasm" sha256="%s"/></parameters>' % ("0" * 64)
    out = by_code(doc('<group id="a" parent="g1"/>', version="1.6", head=head), "xsd:idref")
    assert len(out) == 1


# ------------------------------------------------------------------------------------------ versions and gates

def test_gate_firing_is_reported_under_the_gate_id() -> None:
    out = checks.check(read(doc(version="1.0", head="<metadata/>")))
    v1 = only(out, "V1")
    assert len(v1) == 1 and v1[0].path == "/scene" and v1[0].severity == "error"
    gate = next(g for g in gen.GATES if g.id == "V1")
    assert v1[0].message == gate.message


def test_no_gate_findings_at_a_version_the_gates_accept() -> None:
    assert checks.check(read(doc(version="1.1", head="<metadata/>"))) == []


def test_version_below_min_version_is_xsd_version_naming_the_gate() -> None:
    out = only(checks.check(read(doc(version="1.0", head="<metadata/>"))), "xsd:version")
    assert len(out) == 1 and "V1" in out[0].message and "1.1" in out[0].message and out[0].path == "/scene"


def test_unknown_version_is_xsd_version_only() -> None:
    out = checks.check(read(doc(version="9.9")))
    assert codes(out) == ["xsd:version"] and "9.9" in out[0].message


def test_version_auto_is_clean_and_fires_no_gate_when_set_through_the_api() -> None:
    scene = read(doc(version="1.7", head="<metadata/>"))
    scene.version = "auto"
    assert checks.check(scene) == []


def test_version_auto_in_a_read_document_is_xsd_version() -> None:
    assert codes(checks.check(read(doc(version="auto", head="<metadata/>")))) == ["xsd:version"]


def test_gate_findings_one_per_firing_element() -> None:
    # every gate in GATES that fires at the document's version yields exactly one finding per context element
    scene = read(doc(version="1.0", head="<metadata/>"))
    expect = sum(len(gates.fires(g, scene)) for g in gen.GATES if "1.0" in g.versions)
    got = sum(1 for f in checks.check(scene) if f.code in {g.id for g in gen.GATES})
    assert got == expect >= 1


# ------------------------------------------------------------------------------------------ min_version

def test_min_version_of_a_plain_document_is_the_lowest() -> None:
    assert checks.min_version(read(doc(version="1.7"))) == gen.VERSIONS[0]


def test_min_version_follows_the_gates() -> None:
    assert checks.min_version(read(doc(head="<metadata/>"))) == "1.1"


def test_min_version_of_a_program_document() -> None:
    scene = read(doc(PROGRAM % "", version="1.7"))
    got = checks.min_version(scene)
    assert gen.VERSIONS.index(got) >= gen.VERSIONS.index("1.6")


def test_min_version_is_the_lowest_unrefused_version() -> None:
    for xml in (doc(head="<metadata/>"), doc(PROGRAM % ""), doc('<group id="a"/>')):
        scene = read(xml)
        refused = gates.refused_versions(gen.GATES, scene)
        got = checks.min_version(scene)
        assert not refused.get(got)
        for lower in gen.VERSIONS[: gen.VERSIONS.index(got)]:
            assert refused.get(lower)


def test_min_version_ignores_the_documents_own_version_label() -> None:
    a = checks.min_version(read(doc(version="1.0", head="<metadata/>")))
    b = checks.min_version(read(doc(version="1.7", head="<metadata/>")))
    assert a == b == "1.1"


def test_min_version_method_on_scene() -> None:
    scene = read(doc(head="<metadata/>"))
    assert scene.min_version() == "1.1"  # type: ignore[attr-defined]


def test_min_version_raises_when_no_version_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    refuse_all = tuple(
        gates.Gate(id=f"X{v}", versions=frozenset({v}), context="/scene[@version='%s']" % v,
                   trigger="not(project)", message="m", form="A") for v in gen.VERSIONS)
    monkeypatch.setattr(gen, "GATES", refuse_all)
    with pytest.raises(SchemaValueError):
        checks.min_version(read(doc()))


def test_version_auto_is_written_as_min_version() -> None:
    scene = gen.Scene(version="auto")
    scene.add_project(width=100, height=100, fps="1", duration=1)
    scene.add_metadata()
    scene.add_composition()
    out = io.to_bytes(scene)
    assert b'<scene version="1.1">' in out
    assert scene.version == "auto"
    assert b'version="1.1"' in io.to_bytes(scene, layout="pretty")
    assert read(out).find("metadata") is not None
    assert checks.check(read(out)) == []


def test_version_auto_reassigned_after_construction() -> None:
    scene = gen.Scene(version="1.3")
    scene.version = "auto"
    assert scene.attributes()["version"] == "auto"
    with pytest.raises(SchemaValueError):
        scene.version = "nonsense"


# ------------------------------------------------------------------------------------------ new_id

def test_new_id_returns_prefix_when_free() -> None:
    assert checks.new_id(read(doc()), "hero") == "hero"


def test_new_id_counts_up_from_two() -> None:
    scene = read(doc('<group id="hero"/><group id="hero-2"/>'))
    assert checks.new_id(scene, "hero") == "hero-3"
    scene = read(doc('<group id="hero"/>'))
    assert checks.new_id(scene, "hero") == "hero-2"


def test_new_id_skips_a_taken_numbered_id_even_when_the_bare_prefix_is_free() -> None:
    scene = read(doc('<group id="hero-2"/>'))
    assert checks.new_id(scene, "hero") == "hero"


def test_new_id_sees_every_element_of_the_document_including_unknown_ones() -> None:
    scene = read(doc('<bogus id="hero"/>', tail='<effects><effect id="hero-2" type="blur"/></effects>'))
    assert checks.new_id(scene, "hero") == "hero-3"


def test_new_id_from_a_descendant_considers_the_whole_document() -> None:
    scene = read(doc('<group id="deep"/><group id="hero"/>'))
    inner = scene.find("composition").find("group")  # type: ignore[union-attr]
    assert checks.new_id(inner, "hero") == "hero-2"


def test_new_id_is_deterministic_and_does_not_reserve() -> None:
    scene = read(doc())
    assert checks.new_id(scene, "a") == checks.new_id(scene, "a") == "a"


def test_new_id_result_is_a_valid_ncname_that_the_document_accepts() -> None:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=100, height=100, fps="1", duration=1)
    comp = scene.add_composition()
    for _ in range(4):
        comp.add_group(id=scene.new_id("g"))  # type: ignore[attr-defined]
    assert [g.id for g in comp.find_all("group")] == ["g", "g-2", "g-3", "g-4"]
    assert checks.check(scene) == []


@pytest.mark.parametrize("prefix", ["", "1a", "a b", "a:b", "-x"])
def test_new_id_refuses_a_prefix_that_is_not_an_ncname(prefix: str) -> None:
    with pytest.raises(SchemaValueError):
        checks.new_id(read(doc()), prefix)


# ------------------------------------------------------------------------------------------ Scene API

def test_scene_class_derives_from_scene_base() -> None:
    assert issubclass(gen.Scene, SceneBase) and SceneBase.__slots__ == ()
    assert gen.Scene.__slots__ == ()
    assert not hasattr(gen.Scene(version="1.1"), "__dict__")


def test_scene_methods_delegate_to_the_module_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = gen.Scene(version="1.1")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(checks, "check", lambda s, **kw: seen.update(check=(s, kw)) or ["F"])
    monkeypatch.setattr(checks, "min_version", lambda s: seen.update(min=s) or "1.4")
    assert scene.check(schema=True, data="d") == ["F"]  # type: ignore[attr-defined]
    assert seen["check"] == (scene, {"schema": True, "data": "d"})
    assert scene.min_version() == "1.4"  # type: ignore[attr-defined]
    assert seen["min"] is scene


def test_scene_to_bytes_and_new_id_delegate() -> None:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=1, height=1, fps="1", duration=1)
    assert scene.to_bytes() == io.to_bytes(scene)  # type: ignore[attr-defined]
    assert scene.to_bytes(layout="pretty") == io.to_bytes(scene, layout="pretty")  # type: ignore[attr-defined]
    assert scene.new_id("x") == "x"  # type: ignore[attr-defined]


def test_other_elements_do_not_carry_the_scene_api() -> None:
    assert not hasattr(gen.Group, "min_version") and not hasattr(gen.Group, "check")


# ------------------------------------------------------------------------------------------ content-model matcher

def el(name: str, mn: int = 1, mx: int = 1) -> tuple[Any, ...]:
    return ("element", mn, mx, name, name + "Type")


def seq(children: tuple[Any, ...], mn: int = 1, mx: int = 1) -> tuple[Any, ...]:
    return ("sequence", mn, mx, children)


def cho(children: tuple[Any, ...], mn: int = 1, mx: int = 1) -> tuple[Any, ...]:
    return ("choice", mn, mx, children)


def test_matcher_sequence_with_optional() -> None:
    model = seq((el("a"), el("b", 0, 1), el("c")))
    assert checks.match_content(model, ["a", "c"]) is None
    assert checks.match_content(model, ["a", "b", "c"]) is None
    bad = checks.match_content(model, ["a", "b", "b", "c"])
    assert bad is not None and bad.index == 2 and bad.expected == ("c",)
    short = checks.match_content(model, ["a", "b"])
    assert short is not None and short.index == 2 and short.expected == ("c",)
    empty = checks.match_content(model, [])
    assert empty is not None and empty.index == 0 and empty.expected == ("a",)


def test_matcher_order_matters_in_a_sequence() -> None:
    model = seq((el("a"), el("b")))
    bad = checks.match_content(model, ["b", "a"])
    assert bad is not None and bad.index == 0 and bad.expected == ("a",)


def test_matcher_choice_is_exclusive_at_max_one() -> None:
    model = cho((el("a"), el("b")))
    assert checks.match_content(model, ["a"]) is None
    assert checks.match_content(model, ["b"]) is None
    both = checks.match_content(model, ["a", "b"])
    assert both is not None and both.index == 1 and both.expected == ()
    none = checks.match_content(model, [])
    assert none is not None and none.index == 0 and set(none.expected) == {"a", "b"}


def test_matcher_unbounded_choice_takes_any_mix() -> None:
    model = cho((el("a"), el("b")), 0, -1)
    assert checks.match_content(model, []) is None
    assert checks.match_content(model, list("abbaab")) is None
    bad = checks.match_content(model, ["a", "z"])
    assert bad is not None and bad.index == 1 and set(bad.expected) == {"a", "b"}


def test_matcher_choice_inside_sequence() -> None:
    model = seq((el("x"), cho((el("a"), el("b")))))
    assert checks.match_content(model, ["x", "a"]) is None
    bad = checks.match_content(model, ["x", "a", "b"])
    assert bad is not None and bad.index == 2


def test_matcher_repeated_sequence_counts_whole_repetitions() -> None:
    model = seq((el("a"), el("b")), 2, 3)
    assert checks.match_content(model, list("abab")) is None
    assert checks.match_content(model, list("ababab")) is None
    few = checks.match_content(model, list("ab"))
    assert few is not None and few.index == 2 and few.expected == ("a",)
    many = checks.match_content(model, list("abababab"))
    assert many is not None and many.index == 6
    half = checks.match_content(model, list("aba"))
    assert half is not None and half.index == 3 and half.expected == ("b",)


def test_matcher_min_occurs_of_an_element() -> None:
    model = seq((el("a", 2, 4),))
    assert checks.match_content(model, ["a"]) is not None
    assert checks.match_content(model, ["a"] * 2) is None
    assert checks.match_content(model, ["a"] * 4) is None
    over = checks.match_content(model, ["a"] * 5)
    assert over is not None and over.index == 4


def test_matcher_nullable_loop_terminates() -> None:
    model = seq((el("a", 0, 1),), 0, -1)
    assert checks.match_content(model, []) is None
    assert checks.match_content(model, ["a", "a", "a"]) is None
    bad = checks.match_content(model, ["b"])
    assert bad is not None and bad.index == 0


def test_matcher_empty_content_model() -> None:
    assert checks.match_content(None, []) is None
    bad = checks.match_content(None, ["a"])
    assert bad is not None and bad.index == 0 and bad.expected == ()


def test_matcher_same_name_in_two_places_backtracks() -> None:
    # (a?, a, b): "a b" needs the optional a to match nothing
    model = seq((el("a", 0, 1), el("a"), el("b")))
    assert checks.match_content(model, ["a", "b"]) is None
    assert checks.match_content(model, ["a", "a", "b"]) is None
    assert checks.match_content(model, ["a", "a", "a", "b"]) is not None


def test_matcher_on_a_real_content_model() -> None:
    scene_model = gen.Scene._content
    names = ["project", "composition"]
    assert checks.match_content(scene_model, names) is None
    assert checks.match_content(scene_model, ["project", "metadata", "composition", "effects"]) is None
    bad = checks.match_content(scene_model, ["composition", "project"])
    assert bad is not None and bad.index == 0 and bad.expected == ("project",)


def test_matcher_rejects_an_unknown_particle_kind() -> None:
    with pytest.raises(SchemaValueError):
        checks.match_content(("all", 1, 1, (el("a"),)), ["a"])


# ------------------------------------------------------------------------------------------ integrity (D8)

@pytest.fixture
def fresh_integrity(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(checks, "_integrity_checked", False)
    return monkeypatch


def test_integrity_passes_for_the_bundled_schema(fresh_integrity: pytest.MonkeyPatch) -> None:
    checks.verify_integrity()
    assert checks._integrity_checked is True


@pytest.mark.parametrize("name", ["XSD_SHA256", "SCH_SHA256"])
def test_integrity_difference_raises(fresh_integrity: pytest.MonkeyPatch, name: str) -> None:
    fresh_integrity.setattr(gen, name, "0" * 64)
    with pytest.raises(IntegrityError) as err:
        checks.check(read(doc()))
    assert name.split("_")[0].lower() in str(err.value).lower()
    with pytest.raises(IntegrityError):  # a failure is not cached as success
        checks.check(read(doc()))


def test_integrity_is_checked_once(fresh_integrity: pytest.MonkeyPatch) -> None:
    checks.check(read(doc()))
    assert checks._integrity_checked is True
    fresh_integrity.setattr(gen, "XSD_SHA256", "0" * 64)  # no longer compared: the result is cached
    assert checks.check(read(doc())) == []


def test_integrity_detects_a_changed_bundled_file(fresh_integrity: pytest.MonkeyPatch) -> None:
    real = checks._bundled_bytes
    fresh_integrity.setattr(checks, "_bundled_bytes", lambda name: real(name) + b" " if name.endswith(".sch") else real(name))
    with pytest.raises(IntegrityError):
        checks.verify_integrity()


# ------------------------------------------------------------------------------------------ level 2

def test_level2_without_lxml_hints_at_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)
    monkeypatch.setitem(sys.modules, "lxml.isoschematron", None)
    with pytest.raises(ImportError, match=r"sr-core\[validate\]"):
        checks.check(read(doc()), schema=True)
    assert checks.check(read(doc())) == []  # level 1 never needs lxml


class TestLevel2:
    @pytest.fixture(autouse=True)
    def _lxml(self) -> None:
        pytest.importorskip("lxml.etree")

    def test_clean_document(self) -> None:
        assert checks.check(read(doc('<group id="g"/>')), schema=True) == []

    def test_schematron_assert_ids_are_the_codes(self) -> None:
        xml = doc('<shape id="s" shape="rect"/>')  # C69: a shape needs width and height
        assert checks.check(read(xml)) == []
        out = checks.check(read(xml), schema=True)
        assert "C69" in codes(out)
        hit = only(out, "C69")[0]
        assert hit.path == "/scene/composition/shape" and hit.severity == "error" and hit.message

    def test_level1_findings_are_kept(self) -> None:
        out = checks.check(read(doc("<bogus/>")), schema=True)
        assert "xsd:element" in codes(out)

    def test_duplicates_with_level1_are_dropped(self) -> None:
        out = checks.check(read(doc(version="1.0", head="<metadata/>")), schema=True)
        assert len(only(out, "V1")) == 1
        out = checks.check(read(doc('<group id="g" bogus="1"/>')), schema=True)
        assert codes(out).count("xsd:attribute") == 1 and "xsd:schema" not in codes(out)

    def test_xsd_errors_are_xsd_schema_when_level1_is_silent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(checks, "_level1", lambda scene: [])
        out = checks.check(read(doc('<group id="g" bogus="1"/>')), schema=True)
        xs = only(out, "xsd:schema")
        assert xs and xs[0].path == "/scene/composition/group" and "bogus" in xs[0].message

    def test_lines_come_from_the_read_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        xml = b'<scene version="1.1">\n  <project width="100" height="100" fps="1" duration="1"/>\n' \
              b'  <composition>\n    <shape id="s" shape="rect"/>\n  </composition>\n</scene>\n'
        out = only(checks.check(read(xml), schema=True), "C69")
        assert out and (out[0].line, out[0].column) == (4, 5)

    def test_level2_on_a_built_scene_has_no_lines(self) -> None:
        scene = gen.Scene(version="1.1")
        scene.add_project(width=1, height=1, fps="1", duration=1)
        scene.add_composition().add_shape(id="s", shape="rect")
        out = only(checks.check(scene, schema=True), "C69")
        assert out and out[0].line is None

    def test_version_auto_is_validated_at_its_written_version(self) -> None:
        scene = gen.Scene(version="auto")
        scene.add_project(width=1, height=1, fps="1", duration=1)
        scene.add_metadata()
        scene.add_composition()
        assert checks.check(scene, schema=True) == []

    def test_malformed_scene_content_does_not_crash(self) -> None:
        out = checks.check(read(doc("<bogus><deeper/></bogus>")), schema=True)
        assert "xsd:element" in codes(out)


# ------------------------------------------------------------------------------------------ level 3

def install_engine(monkeypatch: pytest.MonkeyPatch, result: list[Finding]) -> list[Any]:
    calls: list[Any] = []
    fake = types.ModuleType("sr_core.scene.engine")

    def level3(xml_bytes: bytes, engine_path: Any, *, data: Any = None, document_version: Any = None) -> list[Finding]:
        calls.append((xml_bytes, engine_path, data, document_version))
        return result

    fake.level3 = level3  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sr_core.scene.engine", fake)
    return calls


def test_level3_calls_the_engine_runner_with_the_written_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = Finding("warning", "E99", "engine says", "/scene")
    calls = install_engine(monkeypatch, [extra])
    scene = read(doc())
    out = checks.check(scene, engine="/opt/engine", data="rows.json")
    assert out == [extra]
    assert calls == [(io.to_bytes(scene), "/opt/engine", "rows.json", "1.1")]


def test_level3_findings_follow_level1(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = Finding("error", "E01", "x")
    install_engine(monkeypatch, [extra])
    out = checks.check(read(doc("<bogus/>")), engine="/e")
    assert codes(out) == ["xsd:element", "E01"]


def test_level3_is_not_called_without_an_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_engine(monkeypatch, [])
    checks.check(read(doc()))
    assert calls == []


def test_level3_document_version_for_auto_is_the_min_version(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_engine(monkeypatch, [])
    scene = read(doc(version="1.7", head="<metadata/>"))
    scene.version = "auto"
    checks.check(scene, engine="/e")
    assert calls[0][3] == "1.1" and b'version="1.1"' in calls[0][0]


def test_level3_document_version_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_engine(monkeypatch, [])
    checks.check(read(f"<scene>{PROJECT}<composition/></scene>".encode()), engine="/e")
    assert calls[0][3] is None


def test_all_three_levels_together(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("lxml.etree")
    install_engine(monkeypatch, [Finding("info", "E00", "ok")])
    out = checks.check(read(doc('<shape id="s" shape="rect"/>')), schema=True, engine="/e")
    assert codes(out)[-1] == "E00" and "C69" in codes(out)
