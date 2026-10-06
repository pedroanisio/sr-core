"""SREP 18: output/@report. The SREP adds one attribute and no Schematron rule: it has no default and is accepted in every
version, and the inert findings (INERT-I1..I8) are reports, never validation errors."""
import pytest

from srep_support import case_verdict, verdict12
from test_schema_rules import doc

CASES = ("srep-0018-report", "srep-0018-failed")
OUT = '<output id="o" path="out/o.mp4" codec="h264"{}/>'


def scene(report='report="out/report.json"', version="1.2", body=""):
    return doc(body, version=version, head=OUT.format(" " + report if report else ""))


@pytest.mark.parametrize("name", CASES)
def test_case_validates(name):
    assert case_verdict(name) == "ok"


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_report_is_accepted_in_every_version(version):
    assert verdict12(scene(version=version)) == "ok"


def test_report_is_optional():
    assert verdict12(scene(report="")) == "ok"


def test_report_on_a_sequence_output():
    xml = doc("", head='<output id="o" path="out/f_%04d.png" codec="png-sequence" report="../r/report.json"/>')
    assert verdict12(xml) == "ok"


def test_report_belongs_to_output_only():
    # not on project, nor on the output's stills
    xml = doc("").replace('<project ', '<project report="r.json" ')
    assert verdict12(xml) == "xsd"
    still = doc("", head='<output id="o" path="o.mp4" codec="h264"><poster time="0" report="r.json"/></output>')
    assert verdict12(still) == "xsd"


def test_inert_attributes_are_not_validation_errors():
    # I2 (strokeWidth with no stroke paint), I4 (points on a rect), I5 (path on a rect), I6 (matteMode without matte)
    # and I8 (a node that starts after the composition ends) all validate: they are reported, not rejected.
    inert = ('<shape id="a" shape="rect" width="10" height="10" strokeWidth="2"/>'
             '<shape id="b" shape="rect" width="10" height="10" points="6" path="M0 0 L1 1"/>'
             '<shape id="c" shape="rect" width="10" height="10" matteMode="luma"/>'
             '<shape id="d" shape="rect" width="10" height="10" start="9"/>')
    assert verdict12(scene(body=inert)) == "ok"
    assert verdict12(scene(body=inert, version="1.1")) == "ok"
