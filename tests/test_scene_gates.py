"""Tests for sr_core.scene.gates: version-gate compiler and native evaluator (CONTRACT C6, SREP section 5)."""

from __future__ import annotations

import dataclasses
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

import pytest

from sr_core.scene.errors import SchemaError
from sr_core.scene.gates import Gate, compile_gates, fires, refused_versions
from sr_core.schemadoc import model

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7")

EXPECTED_IDS = {
    "A": ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11", "V12", "V13", "V14", "V15", "V16", "VOX1"],
    "B": ["MSQ1", "P3D1", "OCN1", "CRT1", "BH1", "FRX1", "GEO1"],
}


class FakeEl:
    """The four-member element API of CONTRACT C6, over xml.etree."""

    def __init__(self, el: ET.Element, owner: "FakeEl | None" = None) -> None:
        self._el = el
        self._owner = owner
        self._kids = [FakeEl(c, self) for c in el if isinstance(c.tag, str)]

    @property
    def xml_name(self) -> str:
        return str(self._el.tag)

    @property
    def owner(self) -> "FakeEl | None":
        return self._owner

    def elements(self) -> list["FakeEl"]:
        return list(self._kids)

    def attributes(self) -> dict[str, str]:
        return dict(self._el.attrib)

    def walk(self) -> Iterator["FakeEl"]:
        yield self
        for k in self._kids:
            yield from k.walk()


def doc(xml: str) -> FakeEl:
    return FakeEl(ET.fromstring(xml))


def gate_a(trigger: str, versions: tuple[str, ...] = ("1.0",)) -> Gate:
    ctx = "/scene[" + " or ".join(f"@version='{v}'" for v in versions) + "]"
    return Gate(id="T", versions=frozenset(versions), context=ctx, trigger=trigger, message="m", form="A")


def gate_b(context: str, extra: str | None = None, versions: tuple[str, ...] = ("1.0", "1.1")) -> Gate:
    trig = "not(" + " or ".join(f"/scene/@version='{v}'" for v in versions) + ")"
    if extra:
        trig += " or " + extra
    return Gate(id="T", versions=frozenset(versions), context=context, trigger=trig, message="m", form="B")


def names(els: list[FakeEl]) -> list[str]:
    return [e.xml_name for e in els]


@pytest.fixture(scope="module")
def schema() -> model.Schema:
    return model.read((ROOT / "schema/scene-render.xsd").read_bytes(), (ROOT / "schema/scene-render.sch").read_bytes())


@pytest.fixture(scope="module")
def gates(schema: model.Schema) -> tuple[Gate, ...]:
    return compile_gates(schema)


# ---------------------------------------------------------------- the real schema

def test_real_schema_has_24_gates(gates: tuple[Gate, ...]) -> None:
    assert len(gates) == 24
    assert len({g.id for g in gates}) == 24


def test_real_schema_ids_and_forms(gates: tuple[Gate, ...]) -> None:
    assert sorted(g.id for g in gates if g.form == "A") == sorted(EXPECTED_IDS["A"])
    assert sorted(g.id for g in gates if g.form == "B") == sorted(EXPECTED_IDS["B"])


def test_real_schema_gates_are_in_schema_order(schema: model.Schema, gates: tuple[Gate, ...]) -> None:
    order = [a.id for r in schema.rules for a in r.asserts]
    pos = [order.index(g.id) for g in gates]
    assert pos == sorted(pos)


def test_real_schema_versions_are_known(gates: tuple[Gate, ...]) -> None:
    for g in gates:
        assert g.versions and g.versions <= set(VERSIONS)
    by_id = {g.id: g for g in gates}
    assert by_id["V2"].versions == {"1.0"}
    assert by_id["V9"].versions == {"1.0", "1.1"}
    assert by_id["VOX1"].versions == {"1.0", "1.1", "1.2"}
    assert by_id["GEO1"].versions == {"1.0", "1.1", "1.2"}
    assert by_id["V16"].versions == {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5"}


def test_real_schema_gate_strings_are_source_text(gates: tuple[Gate, ...]) -> None:
    by_id = {g.id: g for g in gates}
    assert by_id["V2"].context == "/scene[@version='1.0']"
    assert by_id["V2"].trigger == "count(output) <= 1"
    assert by_id["CRT1"].context == "object3D/crater"
    assert by_id["BH1"].context == "blackHole|accretionDisk|camera[@geodesics]"
    assert by_id["GEO1"].trigger.startswith("not(/scene/@version='1.0'")
    assert by_id["V16"].message


def test_real_schema_compilation_is_deterministic(schema: model.Schema, gates: tuple[Gate, ...]) -> None:
    assert compile_gates(schema) == gates


# ---------------------------------------------------------------- Gate as plain data

def test_gate_is_frozen_and_plain() -> None:
    g = gate_a("not(assets/pdf)")
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.id = "X"  # type: ignore[misc]
    assert g == gate_a("not(assets/pdf)")
    assert hash(g) == hash(gate_a("not(assets/pdf)"))
    assert "_ctx" not in repr(g) and "_test" not in repr(g)
    assert {f.name for f in dataclasses.fields(g) if f.compare} == {"id", "versions", "context", "trigger", "message", "form"}


def test_gate_post_init_builds_compiled_parts() -> None:
    a, b = gate_a("not(assets/pdf)"), gate_b("ocean")
    assert a._test is not None and a._ctx is None
    assert b._ctx is not None


def test_gate_versions_must_match_the_strings() -> None:
    with pytest.raises(SchemaError):
        Gate(id="T", versions=frozenset({"1.1"}), context="/scene[@version='1.0']", trigger="not(a)", message="m", form="A")
    with pytest.raises(SchemaError):
        Gate(id="T", versions=frozenset({"1.0"}), context="ocean", trigger="not(/scene/@version='1.1')", message="m", form="B")


def test_gate_form_must_match_the_strings() -> None:
    with pytest.raises(SchemaError):
        Gate(id="T", versions=frozenset({"1.0"}), context="/scene[@version='1.0']", trigger="not(a)", message="m", form="B")
    with pytest.raises(SchemaError):
        Gate(id="T", versions=frozenset({"1.0"}), context="ocean", trigger="not(/scene/@version='1.0')", message="m", form="A")
    with pytest.raises(SchemaError):
        Gate(id="T", versions=frozenset({"1.0"}), context="ocean", trigger="not(/scene/@version='1.0')", message="m", form="C")  # type: ignore[arg-type]


# ---------------------------------------------------------------- trigger constructs (form A)

SCENE = "<scene version='9.9'>{}</scene>"


@pytest.mark.parametrize(
    ("trigger", "body", "expect"),
    [
        ("not(assets/pdf)", "<assets><pdf/></assets>", True),
        ("not(assets/pdf)", "<assets><font/></assets>", False),
        ("not(assets/pdf)", "<composition><assets><pdf/></assets></composition>", False),  # child steps only
        ("not(.//repeat/points)", "<a><b><repeat><points/></repeat></b></a>", True),
        ("not(.//repeat/points)", "<a><repeat><x><points/></x></repeat></a>", False),
        ("not(.//repeat/points)", "", False),
        ("not(metadata|parameters)", "<parameters/>", True),
        ("not(metadata|parameters)", "<metadata/>", True),
        ("not(metadata|parameters)", "<other/>", False),
        ("not(.//object3D[@volume])", "<x><object3D volume='v'/></x>", True),
        ("not(.//object3D[@volume])", "<x><object3D/></x>", False),
        ("not(.//object3D[@primitive='voxels'])", "<object3D primitive='voxels'/>", True),
        ("not(.//object3D[@primitive='voxels'])", "<object3D primitive='cone'/>", False),
        ("not(.//object3D[@primitive='a' or @primitive='b'])", "<object3D primitive='b'/>", True),
        ("not(.//object3D[@primitive='a' or @primitive='b'])", "<object3D primitive='c'/>", False),
        ("not(.//o[@p='a' and @q])", "<o p='a' q='1'/>", True),
        ("not(.//o[@p='a' and @q])", "<o p='a'/>", False),
        ("not(.//o[not(@p)])", "<o/>", True),
        ("not(.//o[not(@p)])", "<o p='1'/>", False),
        ("not(.//o[(@p or @q) and not(@r='x')])", "<o q='1' r='y'/>", True),
        ("not(.//o[(@p or @q) and not(@r='x')])", "<o q='1' r='x'/>", False),
        ("not(.//a or .//b)", "<z><b/></z>", True),
        ("not(.//a and .//b)", "<z><b/></z>", False),
        ("not(.//a and .//b)", "<a/><b/>", True),
        ("not(effects/effect[@type='k'])", "<effects><effect type='k'/></effects>", True),
        ("not(effects/effect[@type='k'])", "<effects><effect type='j'/></effects>", False),
        ("not(a/*)", "<a><q/></a>", True),
        ("not(a/*)", "<a/>", False),
        ("not(a/b | .//c)", "<x><c/></x>", True),
        ("not(@mode)", "", False),
        ("not(.//x)", "<p><x/></p>", True),
    ],
)
def test_form_a_not_triggers(trigger: str, body: str, expect: bool) -> None:
    root = doc(SCENE.format(body))
    assert bool(fires(gate_a(trigger), root)) is expect


def test_form_a_root_attribute_paths() -> None:
    assert fires(gate_a("not(@mode)"), doc("<scene version='9' mode='x'/>")) != []
    assert fires(gate_a("not(@mode='x')"), doc("<scene version='9' mode='y'/>")) == []


def test_form_a_returns_the_root_as_context() -> None:
    root = doc(SCENE.format("<assets><pdf/></assets>"))
    assert fires(gate_a("not(assets/pdf)"), root) == [root]


def test_form_a_requires_scene_root() -> None:
    assert fires(gate_a("not(assets/pdf)"), doc("<other><assets><pdf/></assets></other>")) == []


@pytest.mark.parametrize(("body", "expect"), [("", False), ("<output/>", False), ("<output/><output/>", True),
                                              ("<output/><output/><output/>", True)])
def test_form_a_count_trigger(body: str, expect: bool) -> None:
    assert bool(fires(gate_a("count(output) <= 1"), doc(SCENE.format(body)))) is expect


def test_count_with_zero_bound_and_union() -> None:
    g = gate_a("count(a|b) <= 0")
    assert fires(g, doc(SCENE.format("<a/>"))) != []
    assert fires(g, doc(SCENE.format(""))) == []


def test_fires_ignores_document_version() -> None:
    g = gate_a("not(assets/pdf)", ("1.0",))
    for v in ("1.0", "1.5", "banana"):
        assert fires(g, doc(f"<scene version='{v}'><assets><pdf/></assets></scene>")) != []


# ---------------------------------------------------------------- form B

def test_form_b_plain_context() -> None:
    root = doc(SCENE.format("<a><ocean/></a><ocean/><nope/>"))
    hits = fires(gate_b("ocean"), root)
    assert names(hits) == ["ocean", "ocean"]
    assert fires(gate_b("ocean"), doc(SCENE.format("<nope/>"))) == []


def test_form_b_parent_chain_pattern() -> None:
    root = doc(SCENE.format("<object3D><crater/></object3D><other><crater/></other><crater/>"))
    hits = fires(gate_b("object3D/crater"), root)
    assert len(hits) == 1 and hits[0].owner is not None and hits[0].owner.xml_name == "object3D"


def test_form_b_union_with_predicate() -> None:
    root = doc(SCENE.format("<blackHole/><accretionDisk/><camera/><camera geodesics='1'/>"))
    ctx = "blackHole|accretionDisk|camera[@geodesics]"
    assert names(fires(gate_b(ctx), root)) == ["blackHole", "accretionDisk", "camera"]
    assert fires(gate_b(ctx), doc(SCENE.format("<camera/>"))) == []


def test_form_b_extra_not_condition() -> None:
    extra = "not((@terrain and @primitive='globe') or @planetRadius)"
    g = gate_b("object3D", extra)
    root = doc(SCENE.format(
        "<object3D terrain='t' primitive='globe'/>"   # fires
        "<object3D terrain='t' primitive='cone'/>"    # no
        "<object3D planetRadius='6'/>"                # fires
        "<object3D/>"))                               # no
    hits = fires(g, root)
    assert [h.attributes() for h in hits] == [{"terrain": "t", "primitive": "globe"}, {"planetRadius": "6"}]


def test_form_b_extra_over_child_and_descendant_paths() -> None:
    g = gate_b("object3D", "not(a/b or .//c)")
    root = doc(SCENE.format("<object3D><a><b/></a></object3D><object3D><x><c/></x></object3D><object3D><a/></object3D>"))
    assert len(fires(g, root)) == 2


def test_form_b_without_extra_fires_on_every_match() -> None:
    assert len(fires(gate_b("fracture"), doc(SCENE.format("<fracture/><fracture/>")))) == 2


def test_form_b_wildcard_context_step() -> None:
    assert len(fires(gate_b("a/*"), doc(SCENE.format("<a><x/><y/></a>")))) == 2


# ---------------------------------------------------------------- refused_versions

def test_refused_versions_groups_by_version() -> None:
    gs = (
        Gate(id="G1", versions=frozenset({"1.0"}), context="/scene[@version='1.0']", trigger="not(assets/pdf)", message="m", form="A"),
        Gate(id="G2", versions=frozenset({"1.0", "1.1"}), context="ocean", trigger="not(/scene/@version='1.0' or /scene/@version='1.1')",
             message="m", form="B"),
    )
    root = doc(SCENE.format("<assets><pdf/></assets><ocean/>"))
    r = refused_versions(gs, root)
    assert list(r) == ["1.0", "1.1"]
    assert [(g.id, e.xml_name) for g, e in r["1.0"]] == [("G1", "scene"), ("G2", "ocean")]
    assert [(g.id, e.xml_name) for g, e in r["1.1"]] == [("G2", "ocean")]


def test_refused_versions_lists_clean_versions_as_empty() -> None:
    gs = (Gate(id="G1", versions=frozenset({"1.0", "1.2"}), context="ocean",
               trigger="not(/scene/@version='1.0' or /scene/@version='1.2')", message="m", form="B"),)
    r = refused_versions(gs, doc(SCENE.format("<x/>")))
    assert r == {"1.0": [], "1.2": []}


def test_refused_versions_orders_versions_numerically() -> None:
    gs = (Gate(id="G", versions=frozenset({"1.10", "1.9", "1.2"}), context="ocean",
               trigger="not(/scene/@version='1.10' or /scene/@version='1.9' or /scene/@version='1.2')", message="m", form="B"),)
    assert list(refused_versions(gs, doc(SCENE.format("<ocean/>")))) == ["1.2", "1.9", "1.10"]


def test_refused_versions_empty_gates() -> None:
    assert refused_versions((), doc(SCENE.format(""))) == {}


# ---------------------------------------------------------------- hand-built documents, real gates

def _hits(gates: tuple[Gate, ...], gid: str, root: FakeEl) -> list[FakeEl]:
    return fires(next(g for g in gates if g.id == gid), root)


def test_real_gate_form_a_fires_and_does_not(gates: tuple[Gate, ...]) -> None:
    yes = doc(SCENE.format("<assets><pdf/></assets>"))
    no = doc(SCENE.format("<assets><image/></assets>"))
    assert _hits(gates, "V9", yes) == [yes]
    assert _hits(gates, "V9", no) == []
    two = doc(SCENE.format("<output/><output/>"))
    assert _hits(gates, "V2", two) == [two]
    assert _hits(gates, "V2", doc(SCENE.format("<output/>"))) == []
    assert _hits(gates, "V7", doc(SCENE.format("<o><object3D primitive='torus'/></o>"))) != []
    assert _hits(gates, "V7", doc(SCENE.format("<o><object3D primitive='box'/></o>"))) == []


def test_real_gate_form_b_fires_and_does_not(gates: tuple[Gate, ...]) -> None:
    root = doc(SCENE.format("<assets><meshSequence/></assets><particles3D/><ocean/>"))
    assert names(_hits(gates, "MSQ1", root)) == ["meshSequence"]
    assert names(_hits(gates, "P3D1", root)) == ["particles3D"]
    assert names(_hits(gates, "OCN1", root)) == ["ocean"]
    assert _hits(gates, "FRX1", root) == []
    assert _hits(gates, "BH1", doc(SCENE.format("<camera geodesics='1'/>"))) != []


def test_real_gate_geo1_extra_condition(gates: tuple[Gate, ...]) -> None:
    assert _hits(gates, "GEO1", doc(SCENE.format("<object3D terrain='t' primitive='globe'/>"))) != []
    assert _hits(gates, "GEO1", doc(SCENE.format("<object3D terrainZoom='3'/>"))) != []
    assert _hits(gates, "GEO1", doc(SCENE.format("<object3D terrain='t' primitive='cone'/>"))) == []
    assert _hits(gates, "GEO1", doc(SCENE.format("<object3D/>"))) == []


def test_real_refused_versions_for_a_document(gates: tuple[Gate, ...]) -> None:
    root = doc(SCENE.format("<assets><fractal/></assets><ocean/>"))
    r = refused_versions(gates, root)
    assert sorted(r) == ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"]
    assert "OCN1" in {g.id for g, _ in r["1.2"]} and "OCN1" not in {g.id for g, _ in r["1.3"]}
    assert {g.id for g, _ in r["1.5"]} == {"V16"}


# ---------------------------------------------------------------- compile_gates on synthetic schemas

class _Assert:
    def __init__(self, id: str, test: str, message: str = "msg") -> None:
        self.id, self.test, self.message, self.kind = id, test, message, "assert"


class _Rule:
    def __init__(self, context: str, *asserts: _Assert) -> None:
        self.pattern, self.context, self.asserts = "p", context, list(asserts)


class _Schema:
    def __init__(self, *rules: _Rule) -> None:
        self.rules = list(rules)


def test_compile_gates_ignores_non_version_asserts() -> None:
    s = _Schema(_Rule("layer", _Assert("X1", "@id and @name")), _Rule("/scene[@version='1.0']", _Assert("G", "not(assets/pdf)")))
    out = compile_gates(s)  # type: ignore[arg-type]
    assert [g.id for g in out] == ["G"]
    assert out[0].message == "msg"


def test_compile_gates_normalises_whitespace_in_tests() -> None:
    s = _Schema(_Rule("/scene[@version='1.0']", _Assert("G", "not(assets/pdf\n      | assets/font)")))
    g = compile_gates(s)[0]  # type: ignore[arg-type]
    assert g.trigger == "not(assets/pdf | assets/font)"


def test_compile_gates_form_b_and_versions() -> None:
    s = _Schema(_Rule("ocean", _Assert("O", "not(/scene/@version='1.0' or /scene/@version='1.2')")))
    g = compile_gates(s)[0]  # type: ignore[arg-type]
    assert (g.form, g.versions) == ("B", frozenset({"1.0", "1.2"}))


@pytest.mark.parametrize(
    ("context", "test"),
    [
        ("layer", "@version='1.0'"),                                            # version only in the test, no gate form
        ("/scene[@version='1.0']", "@version='1.0'"),                           # form A body not not()/count
        ("/scene[@version='1.0']", "not(a) or not(b)"),
        ("/scene[@version='1.0']", "not(a) and not(b)"),
        ("/scene[@version!='1.0']", "not(a)"),
        ("/scene[@version='1.0' and @x]", "not(a)"),
        ("ocean", "not(/scene/@version='1.0') or @a"),                          # form B remainder not not()
        ("ocean", "not(/scene/@version='1.0') and not(@a)"),
        ("ocean", "not(/scene/@version>'1.0')"),
        ("ocean", "/scene/@version='1.0'"),
        ("ocean", "not(@version='1.0')"),
        ("a//b", "not(/scene/@version='1.0')"),                                 # descendant in a pattern
        ("ocean", "not(/scene/@version='1.0') or not(@a/b)"),                   # attr step not last
        ("ancestor::a", "not(/scene/@version='1.0')"),
    ],
)
def test_compile_gates_rejects_unfit_version_asserts(context: str, test: str) -> None:
    with pytest.raises(SchemaError):
        compile_gates(_Schema(_Rule(context, _Assert("BAD", test))))  # type: ignore[arg-type]


# ---------------------------------------------------------------- rejection of unsupported trigger syntax

@pytest.mark.parametrize(
    "trigger",
    [
        "not(contains(@a, 'x'))",
        "not(starts-with(@a, 'x'))",
        "not(string-length(@a))",
        "not(sum(a))",
        "not(position())",
        "not(ancestor::a)",
        "not(child::a)",
        "not(a/following-sibling::b)",
        "not(attribute::a)",
        "not(a/..)",
        "not(.//x[1])",
        "not(.//x[last()])",
        "not(.//x[y])",
        "not(.//x[y/z='1'])",
        "not(.//x[count(y) <= 1])",
        "not(.//x[@a != 'v'])",
        "not(.//x[@a = 'v' or @b < 2])",
        "not(.//x[@a >= 2])",
        "not(.//x[@a > 2])",
        "not(.//x[@a < 2])",
        "not(.//x[@a = @b])",
        "not(.//x[@a = 3])",
        "not(.//x[@a = \"v\"])",
        "not(.//x = 'v')",
        "not(a/b = 'v')",
        "not(@a != 'v')",
        "not(@a = $v)",
        "not(//x)",
        "not(/scene/x)",
        "not(a + b)",
        "not(a, b)",
        "not(a div b)",
        "not(a)) or (not(b)",
        "not(",
        "",
        "count(a) = 1",
        "count(a) < 1",
        "count(a) >= 1",
        "count(a) <= b",
        "count(a) <= 1 or count(b) <= 1",
        "not(count(a) <= 1)",
        "count(contains(a,'b')) <= 1",
        "not(a) extra",
        "a",
    ],
)
def test_unsupported_trigger_syntax_raises_schema_error(trigger: str) -> None:
    with pytest.raises(SchemaError):
        gate_a(trigger)


@pytest.mark.parametrize(
    "extra",
    ["contains(@a, 'x')", "not(ancestor::a)", "not(@a != 'b')", "not(count(@a) <= 1)", "not(@a < 1)", "not(@a = @b)"],
)
def test_unsupported_form_b_extra_raises_schema_error(extra: str) -> None:
    with pytest.raises(SchemaError):
        gate_b("object3D", extra)


@pytest.mark.parametrize("context", ["", "a[1]", "a[b]", "a//b", "//a", "/scene/a", "@a", ".", "a/..", "a|", "child::a", "a[@x!='1']"])
def test_unsupported_form_b_context_raises_schema_error(context: str) -> None:
    with pytest.raises(SchemaError):
        gate_b(context)


# ---------------------------------------------------------------- corpus differential (needs lxml; run on a VM)

CORPUS_FILES = sorted((ROOT / "conformance/cases").glob("*.xml")) + sorted((ROOT / "tests/fixtures").rglob("*.xml"))


@pytest.mark.corpus
@pytest.mark.skipif(os.environ.get("SR_SCENE_CORPUS") == "0", reason="corpus differential switched off with SR_SCENE_CORPUS=0")
def test_corpus_gates_agree_with_lxml_schematron(gates: tuple[Gate, ...]) -> None:
    etree = pytest.importorskip("lxml.etree")
    isoschematron = pytest.importorskip("lxml.isoschematron")
    svrl = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
    sch = isoschematron.Schematron(etree.parse(str(ROOT / "schema/scene-render.sch")), store_report=True)
    ids = {g.id for g in gates}
    assert CORPUS_FILES, "no corpus documents found"
    runs = 0
    diffs: list[dict[str, object]] = []
    for path in CORPUS_FILES:
        try:
            base = etree.fromstring(path.read_bytes())
        except etree.XMLSyntaxError:
            continue
        for v in VERSIONS:
            base.set("version", v)
            data = etree.tostring(base)
            sch.validate(etree.fromstring(data))
            theirs = set(sch.validation_report.xpath("//svrl:failed-assert/@id", namespaces=svrl)) & ids
            tree = FakeEl(ET.fromstring(data))
            ours = {g.id for g in gates if v in g.versions and fires(g, tree)}
            runs += 1
            if theirs != ours:
                diffs.append({"file": str(path.relative_to(ROOT)), "version": v, "lxml": sorted(theirs), "sdk": sorted(ours)})
    assert runs > 0
    assert not diffs, f"{len(diffs)} of {runs} runs differ: {diffs[:10]}"
