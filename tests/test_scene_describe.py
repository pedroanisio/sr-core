"""Public introspection: ``describe``, ``describe_all`` and ``element_names`` (SREP 91, section 3.6)."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from sr_core.schemadoc import model
from sr_core.scene import (CLASSES, ELEMENT_CLASSES, VERSIONS, Layer, Scene, Still, UnknownNameError, describe,
                           describe_all, element_names)
from sr_core.scene import _generated as gen
from sr_core.scene._runtime import _attr_specs, _model_of
from sr_core.scene.introspect import AmbiguousNameError, Description

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = model.read((ROOT / "schema/scene-render.xsd").read_bytes(), (ROOT / "schema/scene-render.sch").read_bytes(),
                    "scene-render.xsd", "scene-render.sch")


def attr(desc: Description, name: str):
    return next(a for a in desc.attributes if a.xml_name == name)


def test_element_names_are_all_xml_names_sorted() -> None:
    names = element_names()
    assert names == tuple(sorted(set(names)))
    assert {"scene", "layer", "poster", "thumbnail", "program"} <= set(names)
    assert set(names) == {n for c in CLASSES.values() for n in c._element_names}
    assert len(names) == 162


def test_target_forms_agree() -> None:
    by_name = describe("layer")
    assert describe(Layer) == by_name
    assert describe(Layer(id="x")) == by_name
    assert describe("Layer") == by_name  # the class name works too
    assert by_name.class_name == "Layer" and by_name.xml_names == ("layer",) and by_name.xsd_type == "layerType"


def test_a_multi_name_class() -> None:
    d = describe("poster")
    assert d.class_name == "Still" and d.xml_names == ("poster", "thumbnail")
    assert describe(Still) == d == describe("thumbnail")


def test_an_ambiguous_name_asks_for_the_class() -> None:
    with pytest.raises(AmbiguousNameError) as info:
        describe("point")
    assert set(info.value.candidates) == {"WarpPoint", "MeshPoint"}
    assert isinstance(info.value, UnknownNameError) is False
    assert describe(CLASSES["warpPointType"]).class_name == "WarpPoint"


def test_an_unknown_name_gives_suggestions() -> None:
    with pytest.raises(UnknownNameError) as info:
        describe("layr")
    assert info.value.suggestions[0] == "layer"
    with pytest.raises(UnknownNameError):
        describe(42)  # type: ignore[arg-type]


def test_element_level_fields() -> None:
    d = describe("layer")
    assert d.format == "sr-scene-describe/1"
    assert d.schema_release == gen.SCHEMA_RELEASE
    assert d.doc.startswith("Places an asset.")
    assert d.min_version == "1.0"
    assert d.content_model == "choice"
    assert describe("scene").content_model == "sequence"
    assert describe("expression").content_model == "simple"
    assert describe("expression").simple_content is not None
    assert describe("layer").simple_content is None
    empty = next(c for c in CLASSES.values() if c._content is None and c._simple_content is None)
    assert describe(empty).content_model == "empty" and describe(empty).children == ()


def test_children_in_order_with_occurrences() -> None:
    kids = describe("scene").children
    assert [c.name for c in kids][:4] == ["project", "metadata", "parameters", "styles"]
    project = kids[0]
    assert (project.min_occurs, project.max_occurs, project.class_name) == (1, 1, "Project")
    output = next(c for c in kids if c.name == "output")
    assert (output.min_occurs, output.max_occurs) == (0, None)  # None is unbounded
    composition = next(c for c in kids if c.name == "composition")
    assert composition.min_occurs == 1
    layer_children = {c.name: c for c in describe("layer").children}
    assert layer_children["animate"].min_occurs == 0  # one of several alternatives


def test_children_agree_with_the_runtime_content_model() -> None:
    for cls in CLASSES.values():
        slots = _model_of(cls).slots
        kids = describe(cls).children
        assert [c.name for c in kids] == list(slots), cls.__name__
        for c in kids:
            slot = slots[c.name]
            assert (-1 if c.max_occurs is None else c.max_occurs) == slot.max, (cls.__name__, c.name)
            assert c.position == slot.rank
            assert CLASSES[slot.type_key].__name__ == c.class_name


def test_attributes_in_schema_order_with_names() -> None:
    d = describe("layer")
    specs = list(_attr_specs(Layer).values())
    assert [a.python_name for a in d.attributes] == [s.name for s in specs]
    assert [a.xml_name for a in d.attributes] == [s.xml_name for s in specs]
    ident = attr(d, "id")
    assert ident.required is True and ident.use == "required" and ident.type.name == "xs:ID"
    assert ident.type.kind == "atomic" and ident.type.base == "xs:ID"
    flag = attr(d, "safeAreaForce")
    assert flag.required is False and flag.default == "false" and flag.type.base == "xs:boolean"
    assert flag.doc.startswith("true exempts this node")


def test_python_name_differs_for_keywords() -> None:
    from sr_core.scene._runtime import Attr

    host = next(c for c in CLASSES.values() if any(isinstance(v, Attr) and v.name == "from_" for v in vars(c).values()))
    a = next(x for x in describe(host).attributes if x.python_name == "from_")
    assert a.xml_name == "from"


def test_facets_enums_lists_and_unions() -> None:
    d = describe("layer")
    opacity = attr(d, "opacity")
    assert opacity.type.name == "unitDecimal" and opacity.type.base == "xs:double"
    assert dict(opacity.type.facets) == {"minInclusive": "0", "maxInclusive": "1"}
    blend = attr(d, "blend")
    assert "multiply" in blend.type.enum
    tags = attr(d, "tags")
    assert tags.type.kind == "list" and tags.type.item is not None and tags.type.item.base == "xs:NMTOKEN"
    unions = [a for c in CLASSES.values() for a in describe(c).attributes if a.type.kind == "union"]
    assert unions and all(len(u.type.members) >= 2 for u in unions)
    triple = next(t for t in gen.SIMPLE_TYPES if t == "unitTripleType")
    holder = next(a for c in CLASSES.values() for a in describe(c).attributes if a.type.name == triple)
    assert holder.type.kind == "list" and dict(holder.type.facets)["length"] == "3"
    assert holder.type.item is not None and holder.type.item.name == "unitDecimal"


def test_patterns_are_listed() -> None:
    withpat = [a for c in CLASSES.values() for a in describe(c).attributes if a.type.patterns]
    assert withpat


def test_version_gates_give_minimum_versions() -> None:
    assert describe(CLASSES["programNodeType"]).min_version == "1.6"
    assert describe("scene").min_version == VERSIONS[0]
    assert describe("meshSequence").min_version == "1.3"
    meta = next(c for c in describe("scene").children if c.name == "metadata")
    assert meta.min_version == "1.1"
    volume = attr(describe("object3D"), "volume")
    assert volume.min_version == "1.3"
    assert attr(describe("object3D"), "primitive").min_version is None
    assert dict(attr(describe("object3D"), "primitive").value_min_versions)["capsule"] == "1.1"
    assert attr(describe("layer"), "id").min_version is None


def test_the_description_is_frozen_and_json_serialisable() -> None:
    d = describe("layer")
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.doc = "x"  # type: ignore[misc]
    data = d.to_dict()
    assert data["format"] == "sr-scene-describe/1"
    assert json.loads(json.dumps(data)) == data
    assert json.loads(d.to_json()) == data
    assert data["attributes"][0]["python_name"] == "id"
    assert set(data) >= {"format", "schema_release", "xml_names", "class_name", "xsd_type", "doc", "min_version",
                         "content_model", "children", "attributes", "simple_content"}


def test_describe_all() -> None:
    allofit = describe_all()
    assert allofit["format"] == "sr-scene-describe/1"
    assert allofit["schema_release"] == gen.SCHEMA_RELEASE
    assert allofit["versions"] == list(VERSIONS)
    assert len(allofit["elements"]) == len(CLASSES)
    assert {e["class_name"] for e in allofit["elements"]} == {c.__name__ for c in CLASSES.values()}
    assert set(allofit["types"]) == set(gen.SIMPLE_TYPES)
    assert allofit["types"]["unitDecimal"]["facets"] == {"minInclusive": "0", "maxInclusive": "1"}
    assert "enum" not in allofit["types"]["unitDecimal"]  # empty members are left out
    layer = next(e for e in allofit["elements"] if e["class_name"] == "Layer")
    opacity = next(a for a in layer["attributes"] if a["xml_name"] == "opacity")
    assert opacity["type"] == "unitDecimal"  # named types are looked up in "types"
    assert "python_name" not in opacity and "required" not in opacity and "use" not in opacity
    ident = next(a for a in layer["attributes"] if a["xml_name"] == "id")
    assert ident == {"xml_name": "id", "type": "xs:ID", "required": True}
    assert "min_version" not in layer and layer["children"][0]["name"]
    text = json.dumps(allofit, separators=(",", ":"))
    assert json.loads(text) == allofit
    # about 280 kB without the attribute docs (srep-0092.md) and about 720 kB with them
    assert len(text) < 800_000


def test_every_attribute_of_the_schema_is_described() -> None:
    total = 0
    for key, cls in CLASSES.items():
        d = describe(cls)
        expected = SCHEMA.all_attributes(key)
        assert [a.xml_name for a in d.attributes] == [a.name for a in expected], key
        total += len(expected)
        for got, want in zip(d.attributes, expected):
            assert got.required == (want.use == "required")
            assert got.default == want.default and got.fixed == want.fixed
    assert total == gen.COUNTS["attributes"]


def test_simple_type_documentation_is_carried() -> None:
    assert set(gen.SIMPLE_DOCS) == {n for n, st in SCHEMA.simple.items() if st.doc}
    named = describe_all()["types"]
    for name, doc in gen.SIMPLE_DOCS.items():
        assert named[name]["doc"] == doc


def test_element_classes_cover_every_named_class() -> None:
    names = {c.__name__ for c in CLASSES.values()}
    seen = {c.__name__ for c in ELEMENT_CLASSES.values()}
    assert seen <= names
    assert describe(Scene).xml_names == ("scene",)


def test_a_type_without_documentation_has_an_empty_doc() -> None:
    assert describe("animate").doc == ""
    assert not any(describe(c).doc.startswith("Complex type ") for c in CLASSES.values())
