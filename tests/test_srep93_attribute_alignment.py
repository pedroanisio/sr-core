"""Acceptance boundaries and authored presence for the SREP 93 draft, without running an engine."""
from pathlib import Path
from itertools import combinations

import pytest

etree = pytest.importorskip("lxml.etree")
from lxml import isoschematron  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
XS = "http://www.w3.org/2001/XMLSchema"
XSD = etree.XMLSchema(etree.parse(str(ROOT / "schema/scene-render.xsd")))
SCH = isoschematron.Schematron(etree.parse(str(ROOT / "schema/scene-render.sch")), store_report=True)


def scene(body="", assets="", head="", project="", version="1.7"):
    return etree.fromstring(
        f'<scene version="{version}"><project width="100" height="100" fps="30" duration="1" {project}/>'
        f'{head}<assets>{assets}</assets><composition>{body}</composition></scene>'
    )


def codes(tree):
    SCH.validate(tree)
    return set(SCH.validation_report.xpath("//s:failed-assert/@id", namespaces={"s": "http://purl.oclc.org/dsdl/svrl"}))


@pytest.mark.parametrize("value,valid", [("1", True), ("1024", True), ("0", False), ("1025", False), ("1.5", False)])
def test_ridges(value, valid):
    tree = scene(f'<shape id="s" shape="rect" width="20" height="20"><shapeModifier type="zig-zag" ridges="{value}"/></shape>')
    assert XSD.validate(tree) == valid, XSD.error_log


@pytest.mark.parametrize("value,valid", [("x", True), ("y", True), ("z", False), ("X", False), ("horizontal", False)])
def test_axis(value, valid):
    tree = scene(f'<shape id="s" shape="rect" width="20" height="20"><deform><modifier type="bend" axis="{value}"/></deform></shape>')
    assert XSD.validate(tree) == valid, XSD.error_log


@pytest.mark.parametrize("value,valid", [("#FF0000 var(--brand)", True), ("", False), ("   ", False), ("#FF0000 notacolour", False), ("#FFF", False)])
def test_palette(value, valid):
    tree = scene(assets=f'<fractal id="f" kind="mandelbrot" width="10" height="10" palette="{value}"/>')
    assert XSD.validate(tree) == valid, XSD.error_log


@pytest.mark.parametrize("value,valid", [("0", True), ("0.99", True), ("0.9901", False), ("1", False), ("-0.1", False)])
def test_smoothing(value, valid):
    tree = scene(assets=f'<audio id="a" src="a.wav"/><audiogram id="g" source="a" width="10" height="10" smoothing="{value}"/>')
    assert XSD.validate(tree) == valid, XSD.error_log


@pytest.mark.parametrize("value,valid", [("1", True), ("0.001", True), ("0", False), ("-1", False)])
def test_mass(value, valid):
    tree = scene(f'<shape id="s" shape="rect" width="10" height="10"><rigidBody mass="{value}"/></shape>')
    assert XSD.validate(tree) == valid, XSD.error_log


@pytest.mark.parametrize("kwargs", [
    {"project": 'mode="standard"'},
    {"head": '<colorManagement bitDepth="16f"/>'},
    {"head": '<markers><marker id="m" time="0" color="#FF0000"/></markers>'},
])
def test_removed_attributes(kwargs):
    assert not XSD.validate(scene(**kwargs))


@pytest.mark.parametrize("version", ["1.1", "1.7"])
@pytest.mark.parametrize("legend", ["", 'legend="false"', 'legend="true"'])
def test_legend_has_no_new_version_gate(version, legend):
    tree = scene(assets=f'<chart id="c" kind="line" width="50" height="50" {legend}><series name="S" values="1 2"/></chart>', version=version)
    assert XSD.validate(tree), XSD.error_log
    assert not codes(tree)


@pytest.mark.parametrize("attrs,valid", [
    ('', True), ('spongeCells="4"', True), ('spongeCells="31"', True),
    ('spongeCells="3"', False), ('spongeCells="32"', False),
    ('width="32"', False), ('depth="32"', False),
    ('cellSize="2"', False), ('width="33" depth="33"', True),
    ('spongeCells="+4" width="+9" depth="+9"', True),
])
def test_absorbing_boundary(attrs, valid):
    tree = scene(f'<ocean id="o" boundary="absorbing" {attrs}/>')
    assert XSD.validate(tree), XSD.error_log
    assert ("OCN15" not in codes(tree)) == valid


def test_sponge_is_ignored_for_other_boundaries():
    tree = scene('<ocean id="o" width="4" depth="4" spongeCells="1"/>')
    assert XSD.validate(tree), XSD.error_log
    assert "OCN15" not in codes(tree)
    assert not XSD.validate(scene('<ocean id="o" spongeCells="0"/>'))


@pytest.mark.parametrize("mode,has_hash,valid", [("step", True, False), ("step", False, True), ("build", True, True)])
def test_step_output_hash(mode, has_hash, valid):
    pin = 'outputSha256="' + 'a' * 64 + '"' if has_hash else ''
    tree = scene(f'<program id="p" src="p.wasm" sha256="{"b" * 64}" mode="{mode}" width="1" height="1" {pin}/>')
    assert XSD.validate(tree), XSD.error_log
    assert ("PRG18" not in codes(tree)) == valid


BOXES = [" ".join(f'{a}="1"' for a in subset) for n in range(5) for subset in combinations(("x", "y", "width", "height"), n)]


@pytest.mark.parametrize("box", BOXES)
@pytest.mark.parametrize("text", ["", 'text="phrase"'])
def test_region_presence(box, text):
    tree = scene(assets=f'<pdf id="p" src="p.pdf" sha256="{"a" * 64}" cache="p.png" cacheSha256="{"b" * 64}" width="100" height="100"><region id="r" {box} {text}/></pdf>')
    assert XSD.validate(tree), XSD.error_log
    assert ("C81" not in codes(tree)) == bool(text or len(box.split()) == 4)


@pytest.mark.parametrize("aspect,valid", [("9:16", True), ("18:32", True), ("1:1", False), ("0:0", False), ("0:16", False)])
def test_layout_aspect(aspect, valid):
    tree = scene(head=f'<layouts><layout id="l" width="1080" height="1920" aspect="{aspect}"/></layouts>')
    if aspect.startswith("0:"):
        assert not XSD.validate(tree)
    else:
        assert XSD.validate(tree), XSD.error_log
        assert ("C82" not in codes(tree)) == valid


def test_defaults_preserve_authored_presence():
    schema = etree.XMLSchema(etree.parse(str(ROOT / "schema/scene-render.xsd")), attribute_defaults=True)
    tree = scene('<layer id="s" asset="t"><textAnimator preset="word-by-word"/></layer>'
                 '<particleEmitter id="p" preset="smoke"/>',
                 assets='<text id="t" text="Words" width="100" height="40" size="20"/>')
    schema.assertValid(tree)
    animator = tree.find('.//textAnimator')
    emitter = tree.find('.//particleEmitter')
    assert "unit" not in animator.attrib and "overlap" not in animator.attrib
    covered = ('lifetime lifetimeVariance speed speedVariance direction spread gravityY drag turbulence size '
               'sizeEnd sizeVariance color colorEnd opacityEnd rotationVariance angularVelocity angularVelocityVariance shape trail').split()
    assert not (set(covered) & set(emitter.attrib))
    assert emitter.get('rate') == '10'  # rate is not preset-controlled in the baseline.
    animator.set('unit', 'character')
    animator.set('overlap', '0')
    emitter.set('lifetime', '1')
    schema.assertValid(tree)
    assert animator.get('unit') == 'character' and animator.get('overlap') == '0'
    assert emitter.get('lifetime') == '1'


def test_new_rule_identifiers_are_unique():
    rules = etree.parse(str(ROOT / 'schema/scene-render.sch'))
    ids = rules.xpath('//@id')
    assert len(ids) == len(set(ids))
