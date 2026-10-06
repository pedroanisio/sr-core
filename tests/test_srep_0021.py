"""SREP 21: pinned-font policy. project/@fontPolicy and Schematron rules C70-C73 (pattern p74).

Pattern id p67 in the SREP text became p74 (coordinator's renumbering table); the assert ids are unchanged.
The case declares version="1.2"; the 1.2 value of scene/@version is applied centrally, so it is validated here
with the version attribute set to 1.1. The V5 gate is applied centrally and is not tested here.
"""
import os

import pytest
from test_schema_rules import ROOT, verdict

H64 = "a" * 64
CASE = os.path.join(ROOT, "conformance", "cases", "srep-0021-pinned-font.xml")


def scene(policy="pinned", fonts=f'<font id="f" src="x.ttf" family="Fam" sha256="{H64}"/>', body="", styles=""):
    pol = f' fontPolicy="{policy}"' if policy else ""
    return (f'<scene version="1.1"><project width="100" height="100" fps="1" duration="1"{pol}/>'
            f'<assets>{fonts}<text id="t" text="x" width="50" height="50" size="10"{body}/></assets>'
            f'<composition></composition></scene>')


def test_case_validates():
    assert verdict(open(CASE).read().replace('version="1.2"', 'version="1.1"').encode()) == "ok"


def test_valid_pinned_document_with_font_and_fallback_passes():
    fonts = (f'<font id="f1" src="a.ttf" family="Fam" sha256="{H64}"/>'
             f'<font id="f2" src="b.ttf" family="Other Fam" sha256="{H64}"/>')
    assert verdict(scene(fonts=fonts, body=' font="Fam" fallback="Fam, Other Fam"')) == "ok"
    assert verdict(scene(fonts=fonts, body=' font="Fam" fallback="Other Fam"')) == "ok"


def test_system_policy_and_absent_policy_apply_no_rule():
    loose = ' font="Nowhere" fontFile="x.ttf" fallback="Nope"'
    assert verdict(scene("system", fonts="", body=loose)) == "ok"
    assert verdict(scene(None, fonts="", body=loose)) == "ok"


@pytest.mark.parametrize("rule,kw", [
    ("C70", dict(body=' fontFile="x.ttf"')),
    ("C71", dict(fonts='<font id="f" src="x.ttf" family="Fam"/>')),
    ("C72", dict(body=' font="Missing"')),
    ("C73", dict(body=' fallback="Fam, Missing"')),
])
def test_pinned_rejects(rule, kw):
    assert verdict(scene(**kw)) == f"sch:{rule}"


def test_c73_checks_every_listed_family_and_ignores_blanks_around_commas():
    assert verdict(scene(body=' fallback="Missing"')) == "sch:C73"
    assert verdict(scene(body=' fallback="Fam,Fam"')) == "ok"
    assert verdict(scene(body=' fallback=" Fam , Fam "')) == "ok"


def test_unknown_policy_value_is_rejected_by_xsd():
    assert verdict(scene("embedded")) == "xsd"
