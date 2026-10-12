"""Tests of sr_core.scene._runtime: Attr, Element, the child nodes, Unknown and the content model.

The classes below are hand-written in the shape of the generated module (CONTRACT C5), so that the runtime is tested
without the generator. ``values.codec_for`` is the real one when ``sr_core.scene.values`` exists; otherwise a small
stand-in covers the few XSD types used here.
"""
from __future__ import annotations

import importlib
import math
import sys
import types
from typing import Any

import pytest

from sr_core.scene import _runtime
from sr_core.scene._runtime import PI, Attr, Comment, Element, Text, Unknown
from sr_core.scene.errors import SchemaValueError


# ------------------------------------------------------------------------------------------ codec stand-in

class _StubCodec:
    def __init__(self, spec: Any) -> None:
        self.spec = spec
        self.xsd_type = spec if isinstance(spec, str) else "inline"
        self.literals = None

    def validate(self, value: Any) -> str:
        if self.spec == "xs:double":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SchemaValueError(f"{value!r} is not a number", xsd_type=self.xsd_type)
            if not math.isfinite(value):
                raise SchemaValueError("NaN and infinities are refused", xsd_type=self.xsd_type)
            text = repr(float(value))
            return text[:-2] if text.endswith(".0") else text
        if self.spec == "xs:IDREFS":
            return " ".join(str(v) for v in value)
        if not isinstance(value, str):
            raise SchemaValueError(f"{value!r} is not a string", xsd_type=self.xsd_type)
        if self.spec in ("xs:ID", "xs:IDREF") and not value.replace("-", "a").replace("_", "a").isalnum():
            raise SchemaValueError(f"{value!r} is not an NCName", xsd_type=self.xsd_type)
        return value

    def parse(self, lexical: str) -> Any:
        if self.spec == "xs:double":
            try:
                return float(lexical)
            except ValueError:
                raise SchemaValueError(f"{lexical!r} is not a double", xsd_type=self.xsd_type) from None
        if self.spec == "xs:IDREFS":
            return lexical.split()
        return lexical

    def is_valid_lexical(self, text: str) -> bool:
        try:
            self.parse(text)
        except SchemaValueError:
            return False
        return True


def _stub_codec_for(spec: Any, simple_table: Any) -> _StubCodec:
    return _StubCodec(spec)


@pytest.fixture(autouse=True)
def _codec_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the real values module when it is there, a stand-in when it is not."""
    try:
        importlib.import_module("sr_core.scene.values")
    except ImportError:
        module = types.ModuleType("sr_core.scene.values")
        module.codec_for = _stub_codec_for  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sr_core.scene.values", module)
    monkeypatch.setattr(_runtime, "_SIMPLE_TYPES", {})


# ------------------------------------------------------------------------------------------ a tiny scene

class Item(Element):
    __slots__ = ()
    _xsd_type = "itemType"
    _element_names = ("a", "b", "d", "e", "x")
    _content = None
    _simple_content = None
    id: Attr[str] = Attr("id", "xs:ID", doc="the id")
    weight: Attr[float] = Attr("weight", "xs:double")
    from_: Attr[str] = Attr("from", "xs:string")


class Expr(Element):
    __slots__ = ()
    _xsd_type = "exprType"
    _element_names = ("expr",)
    _content = None
    _simple_content = "xs:string"
    lang: Attr[str] = Attr("lang", "xs:string")


class Bag(Element):
    __slots__ = ()
    _xsd_type = "bagType"
    _element_names = ("c",)
    _content = ("choice", 0, -1, (
        ("element", 0, -1, "x", "itemType"),
        ("element", 0, -1, "expr", "exprType"),
    ))
    _simple_content = None
    ref: Attr[str] = Attr("ref", "xs:IDREF")

    def add_x(self, **attrs: Any) -> Item:
        return self._add("x", attrs)  # type: ignore[return-value]

    def add_expr(self, **attrs: Any) -> Expr:
        return self._add("expr", attrs)  # type: ignore[return-value]


class Scene(Element):
    __slots__ = ()
    _xsd_type = "#root"
    _element_names = ("scene",)
    _content = ("sequence", 1, 1, (
        ("element", 1, 1, "a", "itemType"),
        ("element", 0, -1, "b", "itemType"),
        ("element", 0, 1, "c", "bagType"),
        ("choice", 0, 1, (
            ("element", 1, 1, "d", "itemType"),
            ("element", 1, 1, "e", "itemType"),
        )),
    ))
    _simple_content = None
    version: Attr[str] = Attr("version", "xs:string", use="required")
    opacity: Attr[float] = Attr("opacity", "xs:double", default="1")
    start: Attr[float] = Attr("start", "xs:double")

    def add_a(self, **attrs: Any) -> Item:
        return self._add("a", attrs)  # type: ignore[return-value]

    def add_b(self, **attrs: Any) -> Item:
        return self._add("b", attrs)  # type: ignore[return-value]

    def add_c(self, **attrs: Any) -> Bag:
        return self._add("c", attrs)  # type: ignore[return-value]

    def add_d(self, **attrs: Any) -> Item:
        return self._add("d", attrs)  # type: ignore[return-value]

    def add_e(self, **attrs: Any) -> Item:
        return self._add("e", attrs)  # type: ignore[return-value]


CLASSES = {"#root": Scene, "itemType": Item, "exprType": Expr, "bagType": Bag}
ELEMENT_CLASSES = {
    (None, "scene"): Scene,
    ("#root", "a"): Item, ("#root", "b"): Item, ("#root", "c"): Bag, ("#root", "d"): Item, ("#root", "e"): Item,
    ("bagType", "x"): Item, ("bagType", "expr"): Expr,
}

names = lambda el: [e.xml_name for e in el.elements()]  # noqa: E731


# ------------------------------------------------------------------------------------------ Attr

def test_attr_get_set_roundtrip_and_lexical_form() -> None:
    item = Item(id="i1", weight=1.5)
    assert item.id == "i1"
    assert item.weight == 1.5
    assert item.attributes() == {"id": "i1", "weight": "1.5"}


def test_attr_unset_is_none_and_none_deletes() -> None:
    item = Item(weight=2)
    assert item.id is None
    assert item.attributes() == {"weight": "2"}
    item.weight = None
    assert item.weight is None
    assert item.attributes() == {}
    item.weight = None  # deleting an unset attribute is not an error


def test_attr_keeps_lexical_form_of_stored_value() -> None:
    item = Item()
    item._attrs["weight"] = "1.50"
    assert item.weight == 1.5
    assert item.attributes()["weight"] == "1.50"


def test_attr_invalid_stored_lexical_returns_raw_string() -> None:
    item = Item()
    item._attrs["weight"] = "heavy"
    assert item.weight == "heavy"


def test_attr_set_replaces_in_place_and_keeps_order() -> None:
    item = Item(id="i1", weight=1, from_="p")
    item.weight = 3
    assert list(item.attributes()) == ["id", "weight", "from"]
    assert item.attributes()["weight"] == "3"


def test_attr_python_keyword_maps_to_xml_name() -> None:
    item = Item(from_="somewhere")
    assert item.attributes() == {"from": "somewhere"}
    assert item.from_ == "somewhere"


def test_attr_bad_value_raises_schema_value_error_with_context() -> None:
    scene = Scene(version="1.0")
    item = scene.add_a(id="i1")
    with pytest.raises(SchemaValueError) as exc:
        item.weight = "heavy"
    assert exc.value.attribute == "weight"
    assert exc.value.path == "/scene/a"
    assert exc.value.xsd_type == "xs:double"
    assert item.weight is None  # the failed assignment stored nothing


def test_attr_bad_value_in_constructor() -> None:
    with pytest.raises(SchemaValueError):
        Item(weight=math.nan)


def test_attr_accepts_element_with_id_for_references() -> None:
    scene = Scene(version="1.0")
    target = scene.add_a(id="t1")
    bag = scene.add_c()
    bag.ref = target
    assert bag.attributes() == {"ref": "t1"}


def test_attr_refuses_element_without_id() -> None:
    scene = Scene(version="1.0")
    target = scene.add_a()
    bag = scene.add_c()
    with pytest.raises(SchemaValueError) as exc:
        bag.ref = target
    assert exc.value.attribute == "ref"


def test_attr_metadata_and_class_access() -> None:
    desc = Item.__dict__["id"]
    assert isinstance(desc, Attr)
    assert Item.id is desc
    assert desc.xml_name == "id" and desc.name == "id"
    assert Item.from_.xml_name == "from" and Item.from_.name == "from_"
    assert Item.id.doc == "the id"
    assert Scene.version.use == "required"
    assert Scene.opacity.default == "1"
    assert Item.id.__doc__ == "the id"


def test_attr_passes_the_simple_table_to_codec_for(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def spy(spec: Any, table: Any) -> _StubCodec:
        seen.append((spec, table))
        return _StubCodec(spec)

    import sr_core.scene.values as values
    monkeypatch.setattr(values, "codec_for", spy)
    table = {"unitDecimal": {"kind": "restriction"}}
    _runtime.set_simple_types(table)
    Item(weight=1)
    assert seen and seen[0][0] == "xs:double" and seen[0][1] is table


def test_undeclared_attribute_raises_attribute_error() -> None:
    item = Item()
    with pytest.raises(AttributeError):
        item.bogus = 1  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        Scene(version="1.0", nonsense=3)
    assert not hasattr(item, "__dict__")


def test_subclass_without_slots_is_refused() -> None:
    with pytest.raises(TypeError):
        class Loose(Element):  # noqa: F841
            _xsd_type = "looseType"
            _element_names = ("loose",)


# ------------------------------------------------------------------------------------------ nodes

def test_node_classes() -> None:
    assert Comment("hi").text == "hi"
    pi = PI("target", "data")
    assert (pi.target, pi.data) == ("target", "data")
    assert Text("  ").text == "  "
    assert "hi" in repr(Comment("hi"))
    assert "target" in repr(pi)
    assert "  " in repr(Text("  "))
    for node in (Comment("c"), pi, Text("t")):
        with pytest.raises(AttributeError):
            node.extra = 1  # type: ignore[attr-defined]


def test_nodes_hold_document_order() -> None:
    scene = Scene(version="1.0")
    scene.nodes.append(Comment("first"))
    a = scene.add_a(id="a1")
    scene.nodes.append(Text("\n"))
    assert [type(n).__name__ for n in scene.nodes] == ["Comment", "Item", "Text"]
    assert scene.elements() == [a]


# ------------------------------------------------------------------------------------------ adding children

def test_factory_builds_adds_and_returns_child() -> None:
    scene = Scene(version="1.0")
    a = scene.add_a(id="a1", weight=2)
    assert isinstance(a, Item)
    assert a.owner is scene
    assert a.xml_name == "a"
    assert scene.elements() == [a]
    assert a.weight == 2


def test_add_existing_element() -> None:
    scene = Scene(version="1.0")
    b = Item(id="b1")
    b._name = "b"
    scene.add(b)
    assert b.owner is scene and scene.find("b") is b


def test_element_default_name_is_first_element_name() -> None:
    assert Item().xml_name == "a"
    assert Scene(version="1.0").xml_name == "scene"


def test_add_refuses_element_that_has_an_owner() -> None:
    scene = Scene(version="1.0")
    a = scene.add_a(id="a1")
    other = Scene(version="1.0")
    with pytest.raises(SchemaValueError):
        other.add(a)
    with pytest.raises(SchemaValueError):
        scene.add(a)


def test_add_refuses_disallowed_name_with_parent_path() -> None:
    scene = Scene(version="1.0")
    stray = Item()
    stray._name = "zzz"
    with pytest.raises(SchemaValueError) as exc:
        scene.add(stray)
    assert exc.value.path == "/scene"
    assert "zzz" in str(exc.value)
    with pytest.raises(SchemaValueError):
        scene._add("nope", {})
    leaf = Item()
    with pytest.raises(SchemaValueError):
        leaf._add("a", {})  # an element with no content model takes no children


def test_add_refuses_non_element() -> None:
    with pytest.raises(SchemaValueError):
        Scene(version="1.0").add("text")  # type: ignore[arg-type]


def test_add_refuses_wrong_type_for_name() -> None:
    scene = Scene(version="1.0")
    wrong = Expr()
    wrong._name = "a"
    with pytest.raises(SchemaValueError):
        scene.add(wrong)


def test_max_occurs_refusal_on_single_slot() -> None:
    scene = Scene(version="1.0")
    scene.add_a(id="a1")
    with pytest.raises(SchemaValueError) as exc:
        scene.add_a(id="a2")
    assert exc.value.path == "/scene"
    assert len(scene.elements()) == 1


def test_max_occurs_unbounded_and_nested_choice() -> None:
    scene = Scene(version="1.0")
    scene.add_a(id="a1")
    for i in range(5):
        scene.add_b(id=f"b{i}")
    assert len(scene.find_all("b")) == 5
    scene.add_d(id="d1")
    with pytest.raises(SchemaValueError):
        scene.add_d(id="d2")  # the nested choice is 0..1, so d is bounded to 1 overall
    bag = scene.add_c()
    for _ in range(3):  # choice 0..unbounded, element 0..unbounded
        bag.add_x()
    assert len(bag.find_all("x")) == 3


def test_failed_factory_leaves_parent_unchanged() -> None:
    scene = Scene(version="1.0")
    with pytest.raises(SchemaValueError) as exc:
        scene.add_a(weight="heavy")
    assert exc.value.path == "/scene/a"
    assert scene.nodes == []


def test_sequence_ordering_when_added_out_of_order() -> None:
    scene = Scene(version="1.0")
    scene.add_e(id="e1")
    scene.add_c()
    scene.add_b(id="b1")
    scene.add_a(id="a1")
    scene.add_b(id="b2")
    assert names(scene) == ["a", "b", "b", "c", "e"]
    assert [e.id for e in scene.find_all("b")] == ["b1", "b2"]  # same rank keeps insertion order


def test_choice_inside_sequence_shares_one_rank() -> None:
    scene = Scene(version="1.0")
    scene.add_e(id="e1")
    scene.add_d(id="d1")  # which of d / e is present is a check concern; both rank after c
    scene.add_c()
    assert names(scene) == ["c", "e", "d"]


def test_choice_content_keeps_insertion_order() -> None:
    bag = Scene(version="1.0").add_c()
    bag.add_expr()
    bag.add_x(id="x1")
    bag.add_expr()
    bag.add_x(id="x2")
    assert names(bag) == ["expr", "x", "expr", "x"]


def test_insert_copies_neighbouring_whitespace() -> None:
    scene = Scene(version="1.0")
    scene.nodes.extend([Text("\n  ")])
    a = scene.add_a(id="a1")
    scene.nodes.append(Text("\n"))
    scene.add_b(id="b1")
    kinds = [n.text if isinstance(n, Text) else n.xml_name for n in scene.nodes]
    assert kinds == ["\n  ", "a", "\n  ", "b", "\n"]
    c_first = Scene(version="1.0")
    c_first.nodes.extend([Text("\n  "), Item()])
    c_first.nodes[1]._name = "b"
    c_first.nodes[1]._owner = c_first
    c_first.add_a(id="a1")
    kinds = [n.text if isinstance(n, Text) else n.xml_name for n in c_first.nodes]
    assert kinds == ["\n  ", "a", "\n  ", "b"]
    assert a.owner is scene


# ------------------------------------------------------------------------------------------ remove, find, iter

def test_remove_detaches_and_tidies_whitespace() -> None:
    scene = Scene(version="1.0")
    a = scene.add_a(id="a1")
    b = scene.add_b(id="b1")
    scene.nodes[:] = [Text("\n  "), a, Text("\n  "), b, Text("\n")]
    scene.remove(b)
    assert b.owner is None
    assert [n.text if isinstance(n, Text) else n.xml_name for n in scene.nodes] == ["\n  ", "a", "\n"]
    scene.remove(a)
    assert [n.text for n in scene.nodes] == ["\n"]
    scene.add(b)  # a detached element can be added again
    assert b.owner is scene


def test_remove_requires_a_child_and_uses_identity() -> None:
    scene = Scene(version="1.0")
    scene.add_a(id="a1")
    twin = Item(id="a1")
    with pytest.raises(SchemaValueError):
        scene.remove(twin)


def test_find_and_find_all() -> None:
    scene = Scene(version="1.0")
    a = scene.add_a(id="a1")
    b1 = scene.add_b(id="b1")
    b2 = scene.add_b(id="b2")
    bag = scene.add_c()
    bag.add_x(id="deep")
    assert scene.find("a") is a
    assert scene.find("b") is b1
    assert scene.find_all("b") == [b1, b2]
    assert scene.find("nope") is None
    assert scene.find_all("x") == []  # direct children only


def test_iter_is_depth_first_document_order_with_self() -> None:
    scene = Scene(version="1.0")
    scene.add_a(id="a1")
    bag = scene.add_c()
    bag.add_x(id="x1")
    bag.add_expr()
    scene.add_b(id="b1")
    assert [e.xml_name for e in scene.iter()] == ["scene", "a", "b", "c", "x", "expr"]
    assert [e.xml_name for e in scene.iter("x")] == ["x"]
    assert [e.xml_name for e in bag.iter("c")] == ["c"]
    assert list(scene.iter("nothing")) == []


# ------------------------------------------------------------------------------------------ copy, path, repr

def test_copy_is_deep_and_detached() -> None:
    scene = Scene(version="1.0", opacity=1.0)
    scene.nodes.append(Comment("keep"))
    scene.add_a(id="a1")
    bag = scene.add_c()
    bag.add_expr(lang="en").content = " 1 + 2 "
    scene.find("a")._attrs["weight"] = "1.50"
    twin = scene.copy()
    assert twin is not scene and twin.owner is None
    assert twin.attributes() == scene.attributes()
    assert twin.find("a")._attrs["weight"] == "1.50"  # lexical form kept
    assert twin.find("a") is not scene.find("a")
    assert twin.find("a").owner is twin
    assert any(isinstance(n, Comment) and n.text == "keep" for n in twin.nodes)
    assert twin.find("c").find("expr").content == " 1 + 2 "
    twin.find("a").id = "changed"
    assert scene.find("a").id == "a1"
    inner = bag.copy()
    assert inner.owner is None and inner.xml_name == "c"
    scene.add_b().weight = 1
    assert twin.find("b") is None


def test_copy_keeps_unknown_and_resets_source_position() -> None:
    odd = Unknown("odd", {"k": "v"})
    odd.source_line = 4
    twin = odd.copy()
    assert isinstance(twin, Unknown)
    assert twin.xml_name == "odd" and twin.attributes() == {"k": "v"}
    assert twin.source_line is None and twin.source_column is None


def test_xml_path_indexes() -> None:
    scene = Scene(version="1.0")
    scene.add_a(id="a1")
    b1 = scene.add_b(id="b1")
    b2 = scene.add_b(id="b2")
    bag = scene.add_c()
    x = bag.add_x(id="x1")
    assert scene.xml_path == "/scene"
    assert scene.find("a").xml_path == "/scene/a"  # only one: no index
    assert b1.xml_path == "/scene/b[1]"
    assert b2.xml_path == "/scene/b[2]"
    assert x.xml_path == "/scene/c/x"
    bag.add_x(id="x2")
    assert x.xml_path == "/scene/c/x[1]"
    assert Item().xml_path == "/a"  # detached: its own root


def test_xml_path_counts_same_name_siblings_only() -> None:
    scene = Scene(version="1.0")
    scene.add_a(id="a1")
    scene.add_b(id="b1")
    bag = scene.add_c()
    bag.add_expr()
    bag.add_x()
    bag.add_expr()
    assert [e.xml_path for e in bag.elements()] == ["/scene/c/expr[1]", "/scene/c/x", "/scene/c/expr[2]"]


def test_repr_shows_class_name_and_attributes() -> None:
    item = Item(id="i1", weight=1.5)
    text = repr(item)
    assert text.startswith("Item(") and "id='i1'" in text and "weight='1.5'" in text
    assert repr(Unknown("odd", {"k": "v"})).startswith("Unknown(")
    assert "odd" in repr(Unknown("odd"))


# ------------------------------------------------------------------------------------------ content and Unknown

def test_simple_content_property() -> None:
    expr = Expr()
    assert expr.content == ""
    expr.content = "1 + 2"
    assert expr.content == "1 + 2"
    assert [type(n) for n in expr.nodes] == [Text]
    expr.content = " x "
    assert expr.content == " x " and len(expr.nodes) == 1
    expr.content = ""
    assert expr.nodes == []


def test_content_setter_refused_on_element_only_content() -> None:
    with pytest.raises(SchemaValueError):
        Item().content = "no"


def test_content_getter_joins_text_nodes() -> None:
    expr = Expr()
    expr.nodes.extend([Text("a"), Comment("x"), Text("b")])
    assert expr.content == "ab"


def test_unknown_takes_any_child_and_attribute_data() -> None:
    odd = Unknown("odd", {"k": "v"})
    assert odd.xml_name == "odd"
    assert odd.attributes() == {"k": "v"}
    child = odd.add(Unknown("kid"))
    again = odd.add(Unknown("kid"))
    odd.add(Item())  # even a known class: Unknown accepts every child
    assert odd.find_all("kid") == [child, again]
    assert child.xml_path == "/odd/kid[1]"
    odd.content = "text"
    assert odd.content == "text"
    with pytest.raises(AttributeError):
        odd.extra = 1  # type: ignore[attr-defined]


def test_unknown_refused_by_known_parent() -> None:
    scene = Scene(version="1.0")
    with pytest.raises(SchemaValueError):
        scene.add(Unknown("a"))


def test_source_position_defaults() -> None:
    item = Item()
    assert item.source_line is None and item.source_column is None


# ------------------------------------------------------------------------------------------ helpers

def test_default_of_and_new_id() -> None:
    scene = Scene(version="1.0")
    assert _runtime.default_of(scene, "opacity") == 1.0
    assert _runtime.default_of(scene, "start") is None
    assert _runtime.default_of(Item(), "from_") is None
    assert _runtime.default_of(Item(), "from") is None
    with pytest.raises(AttributeError):
        _runtime.default_of(scene, "nope")
    assert _runtime.new_id(scene, "item") == "item"
    scene.add_a(id="item")
    assert _runtime.new_id(scene, "item") == "item-2"
    scene.add_b(id="item-2")
    assert _runtime.new_id(scene, "item") == "item-3"
    assert _runtime.new_id(scene, "item") == "item-3"  # deterministic


def test_set_simple_types_stores_table() -> None:
    table = {"t": {"kind": "restriction"}}
    _runtime.set_simple_types(table)
    assert _runtime._SIMPLE_TYPES is table
