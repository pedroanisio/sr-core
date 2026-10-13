"""Attribute documentation reaches the descriptors, ``help()`` and the type-checker stubs (SREP 91, section 3)."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from sr_core.schemadoc import model
from sr_core.scene import CLASSES, Layer, generate
from sr_core.scene import _generated as gen
from sr_core.scene._runtime import Attr, _attr_specs
from test_scene_generate import SCH_EMPTY, xsd

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = model.read((ROOT / "schema/scene-render.xsd").read_bytes(), (ROOT / "schema/scene-render.sch").read_bytes(),
                    "scene-render.xsd", "scene-render.sch")
TREE = ast.parse(Path(gen.__file__).read_text(encoding="utf-8"))
CLASS_NODES = {n.name: n for n in TREE.body if isinstance(n, ast.ClassDef)}


def expected_doc(a: model.Attribute) -> str:
    """The attribute's own documentation, else the one of its simple type (named, or inline)."""
    if a.doc:
        return inspect.cleandoc(a.doc)
    st = SCHEMA.simple.get(a.type) if a.type else a.inline
    return inspect.cleandoc(st.doc) if st is not None and st.doc else ""


def test_every_descriptor_carries_the_documentation_of_the_schema() -> None:
    checked = documented = 0
    for key, cls in CLASSES.items():
        specs = {a.xml_name: a for a in _attr_specs(cls).values()}
        for a in SCHEMA.all_attributes(key):
            attr = specs[a.name]
            assert attr.doc == expected_doc(a), (key, a.name)
            assert attr.__doc__ == (attr.doc or None), (key, a.name)
            checked += 1
            documented += bool(attr.doc)
    assert checked == gen.COUNTS["attributes"]
    assert documented >= 380  # The SREP 91 documentation baseline; SREP 92 adds declaration-level coverage.


@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize("own_doc", ["", "Attribute documentation."])
def test_type_documentation_is_the_fallback(named: bool, own_doc: str) -> None:
    # SREP 92 leaves no named-type documentation fallback in the real schema; SREP 91 still requires it for inputs
    # the generator may receive. Exercise both named and inline types, including attribute precedence.
    simple = ('<xs:simpleType' + (' name="documentedType"' if named else '') + '>'
              '<xs:annotation><xs:documentation>Type documentation.\n  Second line.</xs:documentation></xs:annotation>'
              '<xs:restriction base="xs:string"/></xs:simpleType>')
    annotation = f'<xs:annotation><xs:documentation>{own_doc}</xs:documentation></xs:annotation>' if own_doc else ''
    attr = ('<xs:attribute name="value"' + (' type="documentedType"' if named else '') + '>'
            + annotation + ('' if named else simple) + '</xs:attribute>')
    source = generate.render(xsd(root_attrs=attr, simple=simple if named else ''), SCH_EMPTY)
    tree = ast.parse(source["sr_core/scene/_generated.py"])
    scene = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Scene")
    declaration = next(n for n in scene.body if isinstance(n, ast.AnnAssign) and n.target.id == "value")
    call = declaration.value
    descriptor = Attr(*(ast.literal_eval(a) for a in call.args),
                      **{k.arg: ast.literal_eval(k.value) for k in call.keywords})
    want = own_doc or "Type documentation.\nSecond line."
    assert descriptor.doc == want
    assert descriptor.__doc__ == want
    following = scene.body[scene.body.index(declaration) + 1]
    assert inspect.cleandoc(ast.literal_eval(following.value)) == want


def test_a_documented_attribute_shows_in_help() -> None:
    attr = Layer.safeAreaForce
    assert isinstance(attr, Attr)
    assert attr.doc.startswith("true exempts this node")
    assert "\n      " not in attr.doc  # the schema's source indentation is gone
    assert attr.__doc__ == attr.doc
    assert inspect.getdoc(Layer.safeAreaForce) == attr.doc
    assert "true exempts this node" in inspect.getdoc(Layer.safeAreaForce)  # what help() prints


def test_generated_class_bodies_carry_attribute_docstrings() -> None:
    body = CLASS_NODES["Layer"].body
    seen = 0
    for i, node in enumerate(body):
        if isinstance(node, ast.AnnAssign) and node.target.id == "safeAreaForce":  # type: ignore[union-attr]
            nxt = body[i + 1]
            assert isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant)
            assert inspect.cleandoc(nxt.value.value) == Layer.safeAreaForce.doc
            seen += 1
    assert seen == 1


def test_every_documented_attribute_has_a_docstring_after_its_declaration() -> None:
    total = 0
    for name, cls in CLASS_NODES.items():
        body = cls.body
        for i, node in enumerate(body):
            if not (isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", None) == "Attr"):
                continue
            kw = {k.arg: ast.literal_eval(k.value) for k in node.value.keywords}
            nxt = body[i + 1] if i + 1 < len(body) else None
            has = isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant) and isinstance(nxt.value.value, str)
            assert has == bool(kw["doc"]), (name, node.target.id)  # type: ignore[union-attr]
            total += has
    assert total >= 380


def test_the_checker_stubs_document_the_attributes() -> None:
    cls = CLASS_NODES["Layer"]
    block = next(n for n in cls.body if isinstance(n, ast.If) and ast.unparse(n.test) == "_t.TYPE_CHECKING")
    init = next(n for n in block.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    text = ast.get_docstring(init)
    assert text is not None
    assert "safeAreaForce" in text and "true exempts this node" in text
    adders = [n for n in block.body if isinstance(n, ast.FunctionDef) and n.name.startswith("add_")]
    comp = CLASS_NODES["Composition"]
    cblock = next(n for n in comp.body if isinstance(n, ast.If))
    add_layer = next(n for n in cblock.body if isinstance(n, ast.FunctionDef) and n.name == "add_layer")
    assert ast.get_docstring(add_layer) and "Layer" in ast.get_docstring(add_layer)  # type: ignore[operator]
    assert adders == [] or all(ast.get_docstring(a) for a in adders)


def test_generator_helper_matches() -> None:
    a = next(a for a in SCHEMA.all_attributes("layerType") if a.name == "safeAreaForce")
    assert generate.attribute_doc(SCHEMA, a) == expected_doc(a)
