"""SREP 44: findings for key parameters the curve ignores. The SREP changes no schema fragment and no Schematron
rule; C40 keeps its context. Findings (E19, E21) are engine reports, so the schema tests check what must stay true."""
import os

from test_schema_rules import ROOT, doc, verdict

CASES = [os.path.join(ROOT, "conformance", "cases", f"srep-0044-{n}.xml")
         for n in ("key-default-handles", "key-parameters-ignored")]


def keys(default, k1, k2, interp=""):
    return (f'<shape id="s" shape="rect" width="5" height="5"><animate property="x" defaultInterpolation="{default}">'
            f'<key time="0" value="0" {k1}/><key time="1" value="9" {k2}/></animate></shape>')


def test_cases_validate():
    for c in CASES:
        # version 1.2 joins the scene/@version list centrally; the SREP adds no gated syntax, so check as 1.1
        assert verdict(open(c, "rb").read().replace(b'version="1.2"', b'version="1.1"')) == "ok", c


def test_default_cubic_bezier_without_handles_stays_valid():
    # SREP 44 Semantics 1: only a warning, never a validation error (MINOR rule of SREP 0)
    assert verdict(doc(keys("cubic-bezier", "", ""))) == "ok"


def test_c40_still_rejects_an_explicit_cubic_bezier_key_without_handles():
    bad = doc(keys("linear", 'interpolation="cubic-bezier"', ""))
    assert verdict(bad) == "sch:C40"


def test_c40_accepts_handles_in_each_of_its_three_forms():
    assert verdict(doc(keys("linear", 'interpolation="cubic-bezier" bezier="0.2,0.1,0.3,1"', ""))) == "ok"
    assert verdict(doc(keys("linear", 'interpolation="cubic-bezier" easeOut="0.2,0.1"', ""))) == "ok"
    assert verdict(doc(keys("linear", 'interpolation="cubic-bezier"', 'easeIn="0.3,1"'))) == "ok"


def test_c40_does_not_apply_to_an_inherited_curve_even_with_handles_absent():
    # the extension to inherited curves is deferred to a MAJOR (SREP 44, Open issues)
    assert verdict(doc(keys("cubic-bezier", "", ""))) == "ok"


def test_parameters_a_curve_does_not_read_are_schema_valid():
    # the table of Semantics 2 is reported as information by an engine, never rejected
    xml = doc(keys("linear", 'bezier="0.2,0.1,0.3,1" easeOut="0.1,0.1" steps="3" stepPosition="start" '
                             'stiffness="150" damping="12" mass="2" tension="0.5" continuity="0.2" bias="0.1"',
                   'easeIn="0.3,1"'))
    assert verdict(xml) == "ok"
