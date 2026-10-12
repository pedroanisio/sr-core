"""Second review of sr_core.scene (2026-10-12): each test pins one reproduced defect.

R1 cycles through add(), R2 XML white space, R3 new_id cost, R4 identity constraints in the generator, R5 the DOCTYPE
internal subset, R6 the CLI's "ok", R8 the gate oracle.
"""
from __future__ import annotations

import time

import pytest

from sr_core.scene import _generated as gen
from sr_core.scene import checks, gates
from sr_core.scene._runtime import Text
from sr_core.scene.errors import SchemaError, SchemaValueError
from sr_core.scene.io import read, to_bytes

PROJECT = '<project width="100" height="100" fps="1" duration="1"/>'
NBSP = " "
EM_SPACE = " "


def doc(body: str = "", version: str = "1.1", tail: str = "") -> bytes:
    return f'<scene version="{version}">{PROJECT}<composition>{body}</composition>{tail}</scene>'.encode()


def codes(xml: bytes) -> list[str]:
    return [f.code for f in checks.check(read(xml))]


# ------------------------------------------------------------------------------------------------- R1

def test_add_refuses_the_element_itself() -> None:
    g = gen.Group(id="g")
    with pytest.raises(SchemaValueError, match="itself or an ancestor"):
        g.add(g)
    assert g.nodes == [] and g.owner is None


def test_add_refuses_an_ancestor() -> None:
    outer = gen.Group(id="o")
    inner = outer.add_group(id="i")
    with pytest.raises(SchemaValueError, match="itself or an ancestor"):
        inner.add(outer)
    assert inner.nodes == [] and outer.owner is None
    assert [el.id for el in outer.iter()] == ["o", "i"]


def test_the_node_list_refuses_an_ancestor_too() -> None:
    outer = gen.Group(id="o")
    inner = outer.add_group(id="i")
    for change in (lambda: inner.nodes.append(outer), lambda: inner.nodes.extend([outer]),
                   lambda: inner.nodes.insert(0, outer), lambda: inner.nodes.__setitem__(slice(0, 0), [outer])):
        with pytest.raises(SchemaValueError, match="itself or an ancestor"):
            change()
    assert inner.nodes == [] and outer.owner is None


def test_the_node_list_refuses_an_element_of_another_parent() -> None:
    a, b = gen.Composition(), gen.Composition()
    g = a.add_group(id="g")
    with pytest.raises(SchemaValueError, match="already belongs"):
        b.nodes.append(g)
    a.nodes[:] = [g]  # its own parent may put it back
    assert b.nodes == [] and g.owner is a


def test_the_node_list_adopts_an_element_without_owner() -> None:
    comp = gen.Composition()
    g = gen.Group(id="g")
    comp.nodes.append(g)
    assert g.owner is comp


# ------------------------------------------------------------------------------------------------- R2

@pytest.mark.parametrize("text, space", [(" \t\r\n", True), ("", True), (NBSP, False), (EM_SPACE, False),
                                         ("\u0085", False), ("\u000b", False), ("\u000c", False)])
def test_only_xml_white_space_is_white_space(text: str, space: bool) -> None:
    assert Text(text).is_space is space


@pytest.mark.parametrize("ch", [NBSP, EM_SPACE])
def test_a_non_xml_space_in_element_only_content_is_character_data(ch: str) -> None:
    out = [f for f in checks.check(read(doc(f'{ch}<group id="g"/>'))) if f.code == "xsd:occurs"]
    assert [f.path for f in out] == ["/scene/composition"]


@pytest.mark.parametrize("layout", ["pretty", "indent"])
def test_layouts_keep_a_non_xml_space(layout: str) -> None:
    out = to_bytes(read(doc(f'{NBSP}<group id="g"/>')), layout=layout)  # type: ignore[arg-type]
    assert NBSP.encode() in out


@pytest.mark.parametrize("body", [f'<group id="a"/><group id="a{NBSP}"/>',
                                  f'<group id="a"/><group id="b" parent="a{NBSP}"/>',
                                  f'<group id="a"/><group id="b" parent="a"/><adjustment id="c" effects="a{NBSP}b"/>'])
def test_a_non_xml_space_in_an_id_or_reference_is_a_bad_value_not_a_separator(body: str) -> None:
    # no character Python takes for a space (and XML does not) is an NCName character, so the value check catches it
    assert codes(doc(body)) == ["xsd:value"]


def test_a_program_mode_padded_with_a_non_xml_space_is_not_a_step_program() -> None:
    prog = '<program id="p" src="m.wasm" sha256="%s" mode="step%s" width="4" height="4"/>' % ("0" * 64, NBSP)
    out = codes(doc(prog + '<group id="a" parent="g1"/>', version="1.6"))
    assert "xsd:value" in out and "xsd:idref" not in out  # not "step": it may be a build program


def test_new_id_does_not_trim_a_non_xml_space() -> None:
    assert checks.new_id(read(doc(f'<group id="hero{NBSP}"/>')), "hero") == "hero"


def test_xpath_white_space_is_xml_white_space() -> None:
    assert gates._tokens("@x \t\r\n") == gates._tokens("@x")
    with pytest.raises(SchemaError):
        gates._tokens(f"@x{NBSP}")
    assert gates._norm(f"a{NBSP}b") == f"a{NBSP}b" and gates._norm(" a \n b ") == "a b"


# ------------------------------------------------------------------------------------------------- R3

def _build(n: int) -> float:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=1, height=1, fps="1", duration=1)
    comp = scene.add_composition()
    start = time.perf_counter()
    for _ in range(n):
        comp.add_group(id=scene.new_id("g"))
    return time.perf_counter() - start


def test_new_id_in_a_building_loop_is_not_quadratic() -> None:
    _build(200)  # warm the codecs
    small, large = min(_build(1000) for _ in range(3)), min(_build(8000) for _ in range(3))
    assert large / small < 8 * 3, (small, large)  # 8x the work: linear is ~8, quadratic ~64


def _brute(scene: gen.Scene, prefix: str) -> str:
    taken = {el._attrs["id"].strip(" \t\r\n") for el in scene.iter() if "id" in el._attrs}
    n = 2
    if prefix not in taken:
        return prefix
    while f"{prefix}-{n}" in taken:
        n += 1
    return f"{prefix}-{n}"


def test_new_id_follows_every_kind_of_change() -> None:
    scene = gen.Scene(version="1.1")
    scene.add_project(width=1, height=1, fps="1", duration=1)
    comp = scene.add_composition()

    def same() -> None:
        assert scene.new_id("g") == _brute(scene, "g")

    a = comp.add_group(id=scene.new_id("g"))
    b = comp.add_group(id=scene.new_id("g"))
    c = comp.add_group(id=scene.new_id("g"))
    same()
    comp.remove(b)  # g-2 is free again
    same()
    assert scene.new_id("g") == "g-2"
    b.add_group(id="g-4")
    comp.add(b)  # a subtree comes in with its ids
    same()
    a.id = "g-9"  # renamed: "g" is free
    same()
    assert scene.new_id("g") == "g"
    a.id = "g"
    del c.id
    same()
    c.id = None
    same()
    loose = gen.Group(id="g-3")
    comp.nodes.append(loose)  # the node list itself
    same()
    loose.id = "zz"  # an adopted element still reports to its document
    same()
    comp.nodes.remove(loose)
    same()
    comp.nodes[:] = []
    same()
    assert scene.new_id("g") == "g"
    detached = gen.Group(id="d")
    detached.add_group(id="d-2")
    assert checks.new_id(detached, "d") == "d-3"
    comp.add(detached)
    assert scene.new_id("d") == "d-3"
    comp.remove(detached)
    assert checks.new_id(detached, "d") == "d-3" and scene.new_id("d") == "d"


def test_new_id_follows_a_change_in_a_copy_and_in_a_read_document() -> None:
    scene = read(doc('<group id="g"/><group id="g-2"/>'))
    assert scene.new_id("g") == "g-3"  # type: ignore[attr-defined]
    twin = scene.copy()
    twin.find("composition").find_all("group")[1].id = "x"  # type: ignore[union-attr]
    assert checks.new_id(twin, "g") == "g-2" and scene.new_id("g") == "g-3"  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------------- R5

def _c14n(data: bytes) -> bytes:
    etree = pytest.importorskip("lxml.etree")
    parser = etree.XMLParser(resolve_entities=True)
    return etree.tostring(etree.fromstring(data, parser).getroottree(), method="c14n2", with_comments=True)


@pytest.mark.parametrize("subset", ["<!--inside dtd-->", "<?pi inside?>",
                                    '<!ELEMENT scene ANY><!--a--><!ATTLIST scene version CDATA #IMPLIED><?b c?>'])
def test_comments_and_pis_of_the_doctype_internal_subset_are_not_moved_into_the_prolog(subset: str) -> None:
    body = doc('<group id="g"/>').decode()
    original = f'<!--before--><!DOCTYPE scene [{subset}]><?after x?>{body}<!--end-->'.encode()
    written = to_bytes(read(original))
    assert _c14n(written) == _c14n(original)
    assert b"inside" not in written and b"<!--a-->" not in written
