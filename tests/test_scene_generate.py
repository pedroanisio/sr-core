"""Tests for ``sr_core.scene.generate`` (CONTRACT C8; SREP 0 sections 2, 3 and 9: D1, D3, D4, D7).

The failure-mode tests use tiny synthetic schemas and stand-ins for ``values`` and ``gates``, so they do not depend
on the other modules. The real-schema tests use the real ones and are skipped when they are not importable.
"""

from __future__ import annotations

import ast
import importlib
import keyword
import shutil
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from sr_core.schemadoc import model
from sr_core.scene import generate
from sr_core.scene.errors import SchemaError

REPO = Path(__file__).resolve().parents[1]
GEN = "sr_core/scene/_generated.py"
SHIPPED = "sr_core/scene/schema"

XS = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'
SCH_EMPTY = b'<schema xmlns="http://purl.oclc.org/dsdl/schematron"><pattern id="p"/></schema>'


# ------------------------------------------------------------------------------- synthetic schemas
def xsd(types: str = "", root_children: str = "", root_attrs: str = "", simple: str = "") -> bytes:
    """A tiny schema: a root ``scene`` with a version enumeration, plus the given parts."""
    return f"""<?xml version="1.0"?>
<xs:schema {XS} version="9.9.9">
  <xs:element name="scene">
    <xs:complexType>
      <xs:sequence>{root_children}</xs:sequence>
      <xs:attribute name="version" use="required">
        <xs:simpleType><xs:restriction base="xs:string">
          <xs:enumeration value="1.0"/><xs:enumeration value="1.1"/>
        </xs:restriction></xs:simpleType>
      </xs:attribute>{root_attrs}
    </xs:complexType>
  </xs:element>
  {types}
  {simple}
</xs:schema>""".encode()


def el(name: str, typ: str, extra: str = ' minOccurs="0"') -> str:
    return f'<xs:element name="{name}" type="{typ}"{extra}/>'


def render_syn(xsd_bytes: bytes) -> dict[str, bytes]:
    return generate.render(xsd_bytes, SCH_EMPTY)


@pytest.fixture
def fake_deps(monkeypatch):
    """Stand-ins for values.translate_pattern and gates.compile_gates with the C4/C6 signatures."""
    def translate_pattern(rx: str) -> str:
        if "\\p{" in rx or "\\i" in rx:
            raise SchemaError(f"untranslatable pattern {rx!r}")
        return rx

    state = SimpleNamespace(gates=())

    def compile_gates(schema):
        if isinstance(state.gates, Exception):
            raise state.gates
        return state.gates

    monkeypatch.setitem(sys.modules, "sr_core.scene.values", types.SimpleNamespace(translate_pattern=translate_pattern))
    monkeypatch.setitem(sys.modules, "sr_core.scene.gates", types.SimpleNamespace(compile_gates=compile_gates))
    return state


@pytest.mark.usefixtures("fake_deps")
class TestSyntheticPositive:
    def test_minimal_schema_renders_compilable_module(self):
        files = render_syn(xsd(types='<xs:complexType name="aType"/>', root_children=el("a", "aType")))
        src = files[GEN].decode()
        compile(src, "_generated.py", "exec")
        assert "class Scene(SceneBase):" in src and "class A(Element):" in src
        assert "def add_a(self, **attrs: _t.Any) -> A:" in src
        assert "VERSIONS = (\"1.0\", \"1.1\")" in src
        assert "SCHEMA_RELEASE = \"9.9.9\"" in src
        assert src.rstrip().endswith("set_simple_types(SIMPLE_TYPES)")

    def test_keyword_attribute_becomes_trailing_underscore_with_xml_name_kept(self):
        t = '<xs:complexType name="aType"><xs:attribute name="from" type="xs:double"/></xs:complexType>'
        src = render_syn(xsd(types=t, root_children=el("a", "aType")))[GEN].decode()
        assert 'from_: Attr[float, _t.Union[float, int, str]] = Attr(' in src

    def test_name_with_two_types_under_different_parents_picks_the_parents_type(self):
        t = ('<xs:complexType name="pType"><xs:sequence>' + el("point", "aType") + "</xs:sequence></xs:complexType>"
             '<xs:complexType name="aType"/><xs:complexType name="bType"/>')
        src = render_syn(xsd(types=t, root_children=el("point", "bType") + el("p", "pType")))[GEN].decode()
        assert "def add_point(self, **attrs: _t.Any) -> B:" in src      # on Scene
        assert "def add_point(self, **attrs: _t.Any) -> A:" in src      # on P
        assert '("#root", "point"): B,' in src and '("pType", "point"): A,' in src

    def test_groups_are_inlined_and_extension_content_is_composed(self):
        t = ('<xs:group name="g"><xs:choice>' + el("a", "aType", "") + el("b", "aType", "")
             + '</xs:choice></xs:group>'
             '<xs:complexType name="aType"/>'
             '<xs:complexType name="baseType"><xs:choice maxOccurs="unbounded">' + el("a", "aType", "")
             + '</xs:choice></xs:complexType>'
             '<xs:complexType name="extType"><xs:complexContent><xs:extension base="baseType"><xs:sequence>'
             '<xs:group ref="g" minOccurs="0" maxOccurs="unbounded"/></xs:sequence>'
             '<xs:attribute name="k" type="xs:int"/></xs:extension></xs:complexContent></xs:complexType>')
        src = render_syn(xsd(types=t, root_children=el("e", "extType")))[GEN].decode()
        compile(src, "_g.py", "exec")
        a_el = ("element", 1, 1, "a", "aType")
        base = ("choice", 1, -1, (a_el,))
        own = ("sequence", 1, 1, (("choice", 0, -1, (a_el, ("element", 1, 1, "b", "aType"))),))
        assert ast.literal_eval(_class_assign(src, "Ext", "_content")) == ("sequence", 1, 1, (base, own))
        assert "group" not in _class_assign(src, "Ext", "_content")
        assert ast.literal_eval(_class_assign(src, "Base", "_content")) == base

    def test_inline_enum_attribute_becomes_a_spec_dict_and_a_literal_hint(self):
        a = ('<xs:attribute name="mode"><xs:simpleType><xs:restriction base="xs:string">'
             '<xs:enumeration value="x"/><xs:enumeration value="y"/></xs:restriction></xs:simpleType></xs:attribute>')
        src = render_syn(xsd(types=f'<xs:complexType name="aType">{a}</xs:complexType>',
                             root_children=el("a", "aType")))[GEN].decode()
        assert 'Attr[_t.Literal["x", "y"], _t.Literal["x", "y"]]' in src
        assert '"enums": ("x", "y")' in src

    def test_signatures_are_keyword_only_typed_and_checked_by_type_checkers_only(self):
        t = ('<xs:complexType name="aType"><xs:attribute name="from" type="xs:double"/>'
             '<xs:attribute name="r" type="xs:IDREF"/><xs:attribute name="d" type="xs:decimal"/></xs:complexType>')
        src = render_syn(xsd(types=t, root_children=el("a", "aType")))[GEN].decode()
        assert "    if _t.TYPE_CHECKING:\n" in src and "\n    else:\n" in src
        assert "            from_: _t.Union[float, int, str] | None = None,\n" in src
        assert "            r: _t.Union[str, Element] | None = None,\n" in src
        assert "Attr[str, _t.Union[str, Element]]" in src and "Attr[_Decimal, _t.Union[_Decimal, float, int, str]]" in src
        assert "        def add_a(self, **attrs: _t.Any) -> A:" in src
        assert render_syn(xsd(types=t, root_children=el("a", "aType"))) == render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_an_attribute_called_self_is_refused(self):
        t = '<xs:complexType name="aType"><xs:attribute name="self" type="xs:int"/></xs:complexType>'
        with pytest.raises(SchemaError, match="self"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_gates_are_emitted_as_literal_calls(self, fake_deps):
        fake_deps.gates = (SimpleNamespace(id="V9-x", versions=frozenset({"1.10", "1.2"}), context="a",
                                           trigger="@k", message="m 'q' \"d\"", form="A"),)
        src = render_syn(xsd(types='<xs:complexType name="aType"/>', root_children=el("a", "aType")))[GEN].decode()
        tree = ast.parse(src)
        gates = [n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "GATES"][0].value
        call = gates.elts[0]
        kw = {k.arg: k.value for k in call.keywords}
        assert call.func.id == "Gate" and ast.literal_eval(kw["id"]) == "V9-x"
        assert [e.value for e in kw["versions"].args[0].elts] == ["1.2", "1.10"]      # natural order
        assert ast.literal_eval(kw["message"]) == "m 'q' \"d\"" and ast.literal_eval(kw["form"]) == "A"
        assert "gate_asserts=1" in src

    def test_docs_are_escaped_safely(self):
        doc = 'quote """ and \\ backslash and \'s\' "d"'
        t = (f'<xs:complexType name="aType"><xs:annotation><xs:documentation>{doc}</xs:documentation></xs:annotation>'
             f'<xs:attribute name="k" type="xs:string"><xs:annotation><xs:documentation>{doc}</xs:documentation>'
             '</xs:annotation></xs:attribute></xs:complexType>')
        src = render_syn(xsd(types=t, root_children=el("a", "aType")))[GEN].decode()
        tree = ast.parse(src)
        cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "A"][0]
        assert ast.get_docstring(cls, clean=False).strip() == doc

    def test_output_is_deterministic_and_has_no_timestamp(self):
        data = xsd(types='<xs:complexType name="aType"/>', root_children=el("a", "aType"))
        assert render_syn(data) == render_syn(data)


def _class_assign(src: str, cls: str, name: str) -> str:
    tree = ast.parse(src)
    c = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls][0]
    for n in c.body:
        if isinstance(n, ast.Assign) and n.targets[0].id == name:
            return ast.get_source_segment(src, n.value)
    raise AssertionError(name)


# ------------------------------------------------------------------------------- C8 failure modes
@pytest.mark.usefixtures("fake_deps")
class TestLoudFailures:
    def test_class_name_collision(self):
        t = '<xs:complexType name="aType"/><xs:complexType name="AType"/>'
        with pytest.raises(SchemaError, match="collision"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_class_name_collision_with_the_root(self):
        with pytest.raises(SchemaError, match="collision"):
            render_syn(xsd(types='<xs:complexType name="sceneType"/>'))

    def test_class_name_that_is_a_keyword(self):
        with pytest.raises(SchemaError, match="invalid class name"):
            render_syn(xsd(types='<xs:complexType name="noneType"/>'))

    def test_class_name_taking_a_module_name(self):
        with pytest.raises(SchemaError, match="reserved class name"):
            render_syn(xsd(types='<xs:complexType name="elementType"/>'))

    @pytest.mark.parametrize("type_name", ["textType", "commentType", "pIType", "unknownType", "findingType",
                                           "schemaErrorType", "engineInfoType"])
    def test_class_name_taking_a_package_export(self, type_name):
        # sr_core.scene re-exports every generated class next to its own names; a clash would shadow one of them.
        with pytest.raises(SchemaError, match="reserved class name"):
            render_syn(xsd(types=f'<xs:complexType name="{type_name}"/>'))

    def test_one_parent_giving_one_name_two_types(self):
        t = '<xs:complexType name="aType"/><xs:complexType name="bType"/>'
        with pytest.raises(SchemaError, match="two types"):
            render_syn(xsd(types=t, root_children=el("x", "aType") + el("x", "bType")))

    @pytest.mark.parametrize("name", ["add", "add_thing", "_hidden", "xml_name", "owner", "content", "find_all",
                                      "min_version", "to_bytes", "source_line", "Attr"])
    def test_reserved_attribute_names(self, name):
        t = f'<xs:complexType name="aType"><xs:attribute name="{name}" type="xs:string"/></xs:complexType>'
        with pytest.raises(SchemaError, match="reserved"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_reserved_name_on_the_root(self):
        with pytest.raises(SchemaError, match="reserved"):
            render_syn(xsd(root_attrs='<xs:attribute name="check" type="xs:string"/>'))

    def test_attribute_that_is_not_an_identifier(self):
        t = '<xs:complexType name="aType"><xs:attribute name="a-b" type="xs:string"/></xs:complexType>'
        with pytest.raises(SchemaError, match="identifier"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_unknown_builtin(self):
        t = '<xs:complexType name="aType"><xs:attribute name="k" type="xs:float"/></xs:complexType>'
        with pytest.raises(SchemaError, match="builtin"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_unknown_builtin_as_restriction_base(self):
        s = '<xs:simpleType name="sT"><xs:restriction base="xs:date"/></xs:simpleType>'
        with pytest.raises(SchemaError, match="builtin"):
            render_syn(xsd(simple=s))

    def test_unknown_simple_type_reference(self):
        t = '<xs:complexType name="aType"><xs:attribute name="k" type="nope"/></xs:complexType>'
        with pytest.raises(SchemaError, match="unknown simple type"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_unknown_facet(self):
        s = ('<xs:simpleType name="sT"><xs:restriction base="xs:decimal"><xs:totalDigits value="3"/>'
             '</xs:restriction></xs:simpleType>')
        with pytest.raises(SchemaError, match="facet"):
            render_syn(xsd(simple=s))

    def test_untranslatable_pattern(self):
        s = ('<xs:simpleType name="sT"><xs:restriction base="xs:string"><xs:pattern value="\\p{L}+"/>'
             '</xs:restriction></xs:simpleType>')
        with pytest.raises(SchemaError, match="pattern"):
            render_syn(xsd(simple=s))

    def test_pattern_in_an_inline_attribute_type_is_checked_too(self):
        a = ('<xs:attribute name="k"><xs:simpleType><xs:restriction base="xs:string"><xs:pattern value="\\i"/>'
             '</xs:restriction></xs:simpleType></xs:attribute>')
        with pytest.raises(SchemaError, match="pattern"):
            render_syn(xsd(types=f'<xs:complexType name="aType">{a}</xs:complexType>', root_children=el("a", "aType")))

    def test_gate_form_not_compiled(self, fake_deps):
        fake_deps.gates = SchemaError("gate V1: form not compiled")
        with pytest.raises(SchemaError, match="not compiled"):
            render_syn(xsd())

    def test_unknown_particle_kind(self):
        t = ('<xs:complexType name="aType"><xs:all>' + el("b", "bType") + "</xs:all></xs:complexType>"
             '<xs:complexType name="bType"/>')
        with pytest.raises(SchemaError, match="xs:all.*not supported"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_unsupported_xsd_construct_surfaces_as_schema_error(self):
        t = '<xs:complexType name="aType"><xs:sequence><xs:element ref="b"/></xs:sequence></xs:complexType>'
        with pytest.raises(SchemaError, match="ref"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_any_attribute_is_refused(self):
        t = '<xs:complexType name="aType"><xs:anyAttribute/></xs:complexType>'
        with pytest.raises(SchemaError):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_mixed_content_is_refused(self):
        t = '<xs:complexType name="aType" mixed="true"><xs:sequence/></xs:complexType>'
        with pytest.raises(SchemaError, match="mixed"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_anonymous_complex_type_is_refused(self):
        child = '<xs:element name="a"><xs:complexType/></xs:element>'
        with pytest.raises(SchemaError, match="anonymous"):
            render_syn(xsd(root_children=child))

    def test_element_without_a_complex_type_is_refused(self):
        with pytest.raises(SchemaError, match="no complex type"):
            render_syn(xsd(root_children=el("a", "xs:string")))

    def test_missing_version_enumeration(self):
        data = (b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="scene"><xs:complexType>'
                b'<xs:attribute name="version" type="xs:string"/></xs:complexType></xs:element></xs:schema>')
        with pytest.raises(SchemaError, match="version"):
            render_syn(data)

    def test_not_a_schema(self):
        with pytest.raises(SchemaError):
            render_syn(b'<root xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')

    def test_main_reports_a_schema_error_with_exit_2(self, tmp_path, capsys):
        (tmp_path / "schema").mkdir()
        (tmp_path / "schema" / "scene-render.xsd").write_bytes(xsd(types='<xs:complexType name="noneType"/>'))
        (tmp_path / "schema" / "scene-render.sch").write_bytes(SCH_EMPTY)
        assert generate.main(["--root", str(tmp_path)]) == 2
        assert "invalid class name" in capsys.readouterr().err
        assert not (tmp_path / "sr_core").exists()


_A = ('<xs:complexType name="aType"><xs:sequence>{}</xs:sequence>{}</xs:complexType>'
      '<xs:complexType name="bType"><xs:attribute name="x" type="xs:string"/></xs:complexType>')
_B = '<xs:element name="b" type="bType" minOccurs="0" maxOccurs="unbounded"/>'


def _idc(kind: str, extra: str = "") -> bytes:
    """An identity constraint on a nested element: lxml enforces it, the SDK's checks do not."""
    inner = f'<xs:{kind} name="u"{extra}><xs:selector xpath="b"/><xs:field xpath="@x"/></xs:{kind}>'
    return xsd(types=_A.format(_B, ""), root_children=f'<xs:element name="a" type="aType" minOccurs="0">{inner}'
                                                      f'</xs:element>')


def _root_idc(kind: str) -> bytes:
    data = xsd(types=_A.format(_B, ""), root_children=el("a", "aType"))
    inner = f'<xs:{kind} name="u"><xs:selector xpath="a/b"/><xs:field xpath="@x"/></xs:{kind}>'
    return data.replace(b"    </xs:complexType>\n  </xs:element>", f"    </xs:complexType>{inner}\n  </xs:element>".encode())


class TestVocabulary:
    """D3: a construct of XML Schema the generator does not implement fails, instead of being dropped (review R4)."""

    @pytest.mark.parametrize("data, construct", [
        (_root_idc("unique"), "xs:unique"),
        (_root_idc("key"), "xs:key"),
        (_idc("unique"), "xs:unique"),
        (_idc("key"), "xs:key"),
        (_idc("keyref", ' refer="k"'), "xs:keyref"),
        (xsd(types=_A.format("", ""), root_children=el("a", "aType", ' minOccurs="0" nillable="true"')), "nillable"),
        (xsd(types=_A.format("", ""), root_children=el("a", "aType", ' minOccurs="0" fixed="z"')), "fixed"),
        (xsd(types=_A.format("", ""), root_children=el("a", "aType", ' minOccurs="0" block="#all"')), "block"),
        (xsd(types=_A.format("", '<xs:attribute name="k" type="xs:string" form="qualified"/>'),
             root_children=el("a", "aType")), "form"),
        (xsd(types=_A.format("", "").replace('name="aType"', 'name="aType" abstract="true"'),
             root_children=el("a", "aType")), "abstract"),
        (xsd(types=_A.format("", "").replace("<xs:sequence>", "<xs:openContent/><xs:sequence>"),
             root_children=el("a", "aType")), "xs:openContent"),
        (xsd(simple='<xs:notation name="n" public="x"/>'), "xs:notation"),
        (xsd(simple='<xs:import namespace="urn:x"/>'), "xs:import"),
        (xsd().replace(b'version="9.9.9"', b'version="9.9.9" targetNamespace="urn:x"'), "targetNamespace"),
        (xsd().replace(b'version="9.9.9"', b'version="9.9.9" attributeFormDefault="qualified"'),
         "attributeFormDefault"),
        (xsd().replace(b'version="9.9.9"', b'version="9.9.9" blockDefault="#all"'), "blockDefault"),
        (xsd(types=_A.format('<xs:any minOccurs="0"/>', ""), root_children=el("a", "aType")), "xs:any"),
        (xsd(types=_A.format("", '<o:rule xmlns:o="urn:o"/>'), root_children=el("a", "aType")), "urn:o"),
    ], ids=lambda v: v if isinstance(v, str) else "")
    def test_an_unimplemented_construct_fails(self, data: bytes, construct: str) -> None:
        with pytest.raises(SchemaError, match=f"{construct}.*not supported"):
            render_syn(data)

    def test_annotations_and_foreign_attributes_pass(self) -> None:
        data = xsd(types=_A.format("", '<xs:attribute name="k" type="xs:string" xmlns:o="urn:o" o:since="1.1"/>'),
                   root_children=el("a", "aType"))
        data = data.replace(b"<xs:complexType name=\"bType\">",
                            b'<xs:complexType name="bType"><xs:annotation><xs:appinfo><o:x xmlns:o="urn:o"/>'
                            b'</xs:appinfo><xs:documentation source="s" xml:lang="en">d</xs:documentation>'
                            b"</xs:annotation>")
        render_syn(data)


class TestDefaultsAreValidated:
    """Uses the real values and gates modules."""

    @pytest.fixture(autouse=True)
    def _real(self):
        pytest.importorskip("sr_core.scene.values")
        pytest.importorskip("sr_core.scene.gates")

    @pytest.mark.parametrize("attr", [
        '<xs:attribute name="k" type="xs:int" default="abc"/>',
        '<xs:attribute name="k" type="xs:boolean" fixed="maybe"/>',
    ])
    def test_invalid_default_or_fixed_is_refused(self, attr):
        t = f'<xs:complexType name="aType">{attr}</xs:complexType>'
        with pytest.raises(SchemaError, match="not valid for its type"):
            render_syn(xsd(types=t, root_children=el("a", "aType")))

    def test_valid_default_passes(self):
        t = '<xs:complexType name="aType"><xs:attribute name="k" type="xs:int" default="3"/></xs:complexType>'
        render_syn(xsd(types=t, root_children=el("a", "aType")))


@pytest.mark.usefixtures("fake_deps")
class TestHelpers:
    def test_class_name_rule(self):
        assert generate.class_name("layerType") == "Layer"
        assert generate.class_name("rigidBody3DType") == "RigidBody3D"
        assert generate.class_name("#root") == "Scene"
        assert generate.class_name("plain") == "Plain"

    def test_quote_prefers_double_quotes_and_round_trips(self):
        for s in ["a", "it's", 'say "hi"', "both ' and \"", "back\\slash", "nl\nx", "é", ""]:
            assert ast.literal_eval(generate.quote(s)) == s
        assert generate.quote("a") == '"a"'

    def test_fmt_breaks_long_containers_one_element_per_line(self):
        v = tuple(f"value-number-{i}" for i in range(12))
        out = generate.fmt(v, 0, 0)
        assert out.startswith("(\n") and out.count("\n") == 13 and ast.literal_eval(out) == v
        assert generate.fmt(("a",), 0, 0) == '("a",)'

    def test_sha256sums_format(self):
        out = generate.sha256sums(b"x", b"y").decode().splitlines()
        assert [ln.split("  ")[1] for ln in out] == ["scene-render.xsd", "scene-render.sch"]

    def test_natural_version_order(self):
        assert sorted(["1.10", "1.2", "1.0"], key=generate.natural_key) == ["1.0", "1.2", "1.10"]


# ------------------------------------------------------------------------------- real schema
@pytest.fixture(scope="module")
def inputs():
    return (REPO / "schema" / "scene-render.xsd").read_bytes(), (REPO / "schema" / "scene-render.sch").read_bytes()


@pytest.fixture(scope="module")
def real(inputs):
    for mod in ("values", "gates"):
        try:
            importlib.import_module(f"sr_core.scene.{mod}")
        except ImportError as exc:
            pytest.skip(f"sr_core.scene.{mod} is not importable yet: {exc}")
    files = generate.render(*inputs)
    return SimpleNamespace(files=files, src=files[GEN].decode(), tree=ast.parse(files[GEN].decode()),
                           schema=model.read(*inputs))


def _module_assign(tree: ast.Module, name: str) -> ast.expr:
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name:
            return n.value
    raise AssertionError(f"no module-level {name}")


def _classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def _attr_decls(cls: ast.ClassDef) -> list[ast.Call]:
    return [n.value for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", None) == "Attr"]


def _enum_literals(spec) -> list[str]:
    """Every enumeration literal in a spec dict, nested specs included."""
    out: list[str] = []
    if isinstance(spec, dict):
        out += list(spec["enums"])
        for part in [spec["base"], spec["item"], *spec["members"]]:
            out += _enum_literals(part)
    return out


def _schema_enums(st: model.SimpleType) -> list[str]:
    return [v for v, _ in st.enums] + [x for i in st.inline for x in _schema_enums(i)]


class TestRealSchema:
    def test_counts(self, real):
        counts = ast.literal_eval(_module_assign(real.tree, "COUNTS"))
        assert counts["complex_types"] == 169 and counts["simple_types"] == 67 and counts["gate_asserts"] == 24
        assert counts["attributes"] == sum(len(real.schema.all_attributes(k)) for k in real.schema.complex)
        header = ast.get_docstring(real.tree, clean=False)
        assert "complex_types=169 simple_types=67" in header and "gate_asserts=24" in header
        assert f"attributes={counts['attributes']} enum_values={counts['enum_values']}" in header
        assert f"schema release: {real.schema.version}" in header
        assert f"xsd sha256: {real.schema.xsd_sha256}" in header
        assert f"sch sha256: {real.schema.sch_sha256}" in header
        assert f"generator version: {generate.GENERATOR_VERSION}" in header
        assert generate.GENERATOR_VERSION == "1"

    def test_header_constants(self, real):
        assert ast.literal_eval(_module_assign(real.tree, "XSD_SHA256")) == real.schema.xsd_sha256
        assert ast.literal_eval(_module_assign(real.tree, "SCH_SHA256")) == real.schema.sch_sha256
        assert ast.literal_eval(_module_assign(real.tree, "SCHEMA_RELEASE")) == real.schema.version
        assert ast.literal_eval(_module_assign(real.tree, "GENERATOR_VERSION")) == generate.GENERATOR_VERSION

    def test_render_is_deterministic(self, real, inputs):
        assert generate.render(*inputs) == real.files

    def test_generated_source_compiles(self, real):
        compile(real.src, "_generated.py", "exec")

    def test_generated_source_has_no_private_paths(self, real):
        assert "/home/" not in real.src

    def test_d4_complex_types_and_classes(self, real):
        classes = _classes(real.tree)
        schema = real.schema
        assert len(classes) == len(schema.complex) == 169
        by_type = {}
        for name, cls in classes.items():
            [xt] = [n.value.value for n in cls.body if isinstance(n, ast.Assign) and n.targets[0].id == "_xsd_type"]
            assert xt not in by_type, f"two classes for {xt}"
            by_type[xt] = name
        assert set(by_type) == set(schema.complex)                       # both ways
        assert by_type["#root"] == "Scene"
        assert by_type["layerType"] == "Layer" and by_type["rigidBody3DType"] == "RigidBody3D"
        keys = [k.value for k in _module_assign(real.tree, "CLASSES").keys]
        assert keys == list(schema.complex)                              # schema order

    def test_d4_attribute_declarations(self, real):
        classes = _classes(real.tree)
        total = 0
        for key, t in real.schema.complex.items():
            cls = classes[generate.class_name(key)]
            expected = [a.name for a in real.schema.all_attributes(key)]
            decls = _attr_decls(cls)
            assert [d.args[0].value for d in decls] == expected, key
            targets = [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)]
            assert targets == [x + "_" if keyword.iskeyword(x) else x for x in expected], key
            for d, a in zip(decls, real.schema.all_attributes(key)):
                kw = {k.arg: ast.literal_eval(k.value) for k in d.keywords}
                assert (kw["use"], kw["default"], kw["fixed"], kw["doc"]) == (a.use, a.default, a.fixed, a.doc)
                spec = ast.literal_eval(d.args[1])
                assert (spec == a.type) if a.type else isinstance(spec, dict)
            total += len(decls)
        assert total == ast.literal_eval(_module_assign(real.tree, "COUNTS"))["attributes"]
        assert [x for x in real.src.split("\n") if x.startswith("    from_: Attr[")]
        assert "from_" in {n.target.id for c in classes.values() for n in c.body if isinstance(n, ast.AnnAssign)}

    def test_d4_enumeration_literals(self, real):
        simple = ast.literal_eval(_module_assign(real.tree, "SIMPLE_TYPES"))
        assert list(simple) == list(real.schema.simple) and len(simple) == 67
        total = 0
        for name, st in real.schema.simple.items():
            assert _enum_literals(simple[name]) == _schema_enums(st), name
            total += len(_schema_enums(st))
        for key in real.schema.complex:
            cls = _classes(real.tree)[generate.class_name(key)]
            for d, a in zip(_attr_decls(cls), real.schema.all_attributes(key)):
                got = _enum_literals(ast.literal_eval(d.args[1]))
                want = _schema_enums(a.inline) if a.inline else []
                assert got == want, (key, a.name)
                total += len(want)
        assert total == ast.literal_eval(_module_assign(real.tree, "COUNTS"))["enum_values"] > 100

    def test_d4_gate_asserts(self, real):
        from sr_core.scene import gates
        want = gates.compile_gates(real.schema)
        got = _module_assign(real.tree, "GATES").elts
        assert len(got) == len(want) == 24
        for call, g in zip(got, want):
            kw = {k.arg: k.value for k in call.keywords}
            assert call.func.id == "Gate"
            assert ast.literal_eval(kw["id"]) == g.id and ast.literal_eval(kw["context"]) == g.context
            assert ast.literal_eval(kw["trigger"]) == g.trigger and ast.literal_eval(kw["message"]) == g.message
            assert ast.literal_eval(kw["form"]) == g.form
            assert {e.value for e in kw["versions"].args[0].elts} == set(g.versions)
        asserts = {a.id for r in real.schema.rules for a in r.asserts}
        assert {ast.literal_eval(dict((k.arg, k.value) for k in c.keywords)["id"]) for c in got} <= asserts

    def test_versions_follow_the_scene_version_enumeration(self, real):
        versions = ast.literal_eval(_module_assign(real.tree, "VERSIONS"))
        root_version = [a for a in real.schema.complex["#root"].attributes if a.name == "version"][0]
        assert versions == tuple(v for v, _ in root_version.inline.enums) and versions[0] == "1.0"

    def test_element_classes_cover_every_usage(self, real):
        table = _module_assign(real.tree, "ELEMENT_CLASSES")
        got = {(ast.literal_eval(k) if not isinstance(k, ast.Constant) else k.value): v.id
               for k, v in zip(table.keys, table.values)}
        assert got[(None, "scene")] == "Scene"
        for u in real.schema.usages:
            assert got[(u.parent, u.element)] == generate.class_name(u.type)
        assert len(got) == 1 + len({(u.parent, u.element) for u in real.schema.usages})

    def test_every_allowed_child_has_a_factory_with_the_parents_type(self, real):
        classes = _classes(real.tree)
        for key in real.schema.complex:
            cls = classes[generate.class_name(key)]
            runtime = [m for n in cls.body for m in (n.orelse if isinstance(n, ast.If) else [n])]
            factories = {n.name: ast.unparse(n.returns) for n in runtime
                         if isinstance(n, ast.FunctionDef) and n.name.startswith("add_")}
            want = {f"add_{p.name}": generate.class_name(p.type) for p in real.schema.children(key)}
            assert factories == want, key
        point_types = {generate.class_name(t) for t in real.schema.types_of_element("point")}
        assert len(point_types) == 2

    def test_simple_content_types(self, real):
        classes = _classes(real.tree)
        for key in ("expressionType", "spanType", "dataSourceType"):
            seg = _class_assign(real.src, generate.class_name(key), "_simple_content")
            assert ast.literal_eval(seg) == real.schema.complex[key].simple_base
        assert _class_assign(real.src, "Layer", "_simple_content") == "None"
        assert "Layer" in classes

    def test_generated_module_imports_when_the_runtime_exists(self, real):
        try:
            gm = importlib.import_module("sr_core.scene._generated")
        except ImportError as exc:
            pytest.skip(f"runtime not importable yet: {exc}")
        assert len(gm.CLASSES) == 169 and len(gm.GATES) == 24 and gm.VERSIONS[-1] == "1.7"

    def test_d7_shipped_copies_in_render_output(self, real, inputs):
        xsd_b, sch_b = inputs
        assert real.files[f"{SHIPPED}/scene-render.xsd"] == xsd_b
        assert real.files[f"{SHIPPED}/scene-render.sch"] == sch_b
        repo_lines = (REPO / "schema" / "SHA256SUMS").read_text().splitlines()
        shipped = real.files[f"{SHIPPED}/SHA256SUMS"].decode().splitlines()
        for name in ("scene-render.xsd", "scene-render.sch"):
            [want] = [ln for ln in repo_lines if ln.endswith("  " + name)]
            assert want in shipped
        assert len(shipped) == 2


# ------------------------------------------------------------------------------- --check and the committed output
@pytest.fixture
def tmp_root(tmp_path, real):
    (tmp_path / "schema").mkdir()
    for name in ("scene-render.xsd", "scene-render.sch"):
        shutil.copyfile(REPO / "schema" / name, tmp_path / "schema" / name)
    return tmp_path


class TestCheckMode:
    def test_check_writes_nothing_and_fails_on_a_missing_output(self, tmp_root):
        assert generate.main(["--check", "--root", str(tmp_root)]) == 1
        assert not (tmp_root / "sr_core").exists()

    def test_write_then_check_passes_and_a_planted_change_fails(self, tmp_root, capsys):
        assert generate.main(["--root", str(tmp_root)]) == 0
        for rel in (GEN, f"{SHIPPED}/scene-render.xsd", f"{SHIPPED}/scene-render.sch", f"{SHIPPED}/SHA256SUMS"):
            assert (tmp_root / rel).is_file()
        assert generate.main(["--check", "--root", str(tmp_root)]) == 0
        gen = tmp_root / GEN
        original = gen.read_bytes()
        gen.write_bytes(original + b"# planted\n")
        assert generate.main(["--check", "--root", str(tmp_root)]) == 1
        assert GEN in capsys.readouterr().err
        assert gen.read_bytes().endswith(b"# planted\n")                # --check did not repair it
        assert generate.main(["--root", str(tmp_root)]) == 0
        assert gen.read_bytes() == original

    def test_a_changed_schema_copy_is_detected(self, tmp_root):
        assert generate.main(["--root", str(tmp_root)]) == 0
        copy = tmp_root / SHIPPED / "scene-render.xsd"
        copy.write_bytes(copy.read_bytes() + b"\n")
        assert generate.main(["--check", "--root", str(tmp_root)]) == 1

    def test_a_changed_input_schema_makes_the_committed_output_stale(self, tmp_root):
        assert generate.main(["--root", str(tmp_root)]) == 0
        xsd_path = tmp_root / "schema" / "scene-render.xsd"
        xsd_path.write_bytes(xsd_path.read_bytes().replace(b'version="1.7.0"', b'version="1.7.1"', 1))
        assert generate.main(["--check", "--root", str(tmp_root)]) == 1

    def test_d1_committed_output_is_current(self, real):
        assert generate.main(["--check"]) == 0

    def test_d7_committed_schema_copies(self, real):
        for name in ("scene-render.xsd", "scene-render.sch"):
            assert (REPO / SHIPPED / name).read_bytes() == (REPO / "schema" / name).read_bytes()
        repo_lines = (REPO / "schema" / "SHA256SUMS").read_text().splitlines()
        shipped = (REPO / SHIPPED / "SHA256SUMS").read_text().splitlines()
        for name in ("scene-render.xsd", "scene-render.sch"):
            [want] = [ln for ln in repo_lines if ln.endswith("  " + name)]
            assert want in shipped
        header = ast.get_docstring(ast.parse((REPO / GEN).read_text()), clean=False)
        for ln in shipped:
            assert ln.split("  ")[0] in header


def test_default_root_is_the_checkout():
    parser_default = Path(generate.__file__).resolve().parents[2]
    assert (parser_default / "schema" / "scene-render.xsd").is_file()
