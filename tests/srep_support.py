"""Shared helpers for the SREP 15-18 tests: validate a document against the canonical schema as it will be
once `scene/@version` accepts 1.2.

The version enumeration is applied centrally at release time. Until then `verdict12` adds "1.2" to the
enumeration in memory (nothing on disk changes); once the schema lists 1.2 itself the substitution is a
no-op, so these tests keep working unchanged.
"""
import os
import re

import pytest

etree = pytest.importorskip("lxml.etree")
from lxml import isoschematron  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}


def _xsd_text():
    text = open(os.path.join(ROOT, "schema", "scene-render.xsd"), encoding="utf-8").read()
    i = text.index('<xs:element name="scene">')
    m = re.search(r'(<xs:attribute name="version"[^>]*>)(.*?)(</xs:attribute>)', text[i:], re.S)
    block = m.group(2)
    if 'value="1.2"' not in block:
        patched = block.replace('<xs:enumeration value="1.1"/>',
                                '<xs:enumeration value="1.1"/><xs:enumeration value="1.2"/>', 1)
        assert patched != block, "could not locate the scene/@version enumeration"
        text = text[:i + m.start(2)] + patched + text[i + m.end(2):]
    return text


XSD12 = etree.XMLSchema(etree.fromstring(_xsd_text().encode("utf-8")))
SCH12 = isoschematron.Schematron(etree.parse(os.path.join(ROOT, "schema", "scene-render.sch")), store_report=True)


def verdict12(xml):
    """'ok', 'xsd', or 'sch:<ids>' (sorted, comma separated), like test_schema_rules.verdict."""
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    t = etree.fromstring(xml)
    if not XSD12.validate(t):
        return "xsd"
    if not SCH12.validate(t):
        ids = SCH12.validation_report.xpath("//svrl:failed-assert/@id", namespaces=SVRL)
        return "sch:" + ",".join(sorted(set(ids)))
    return "ok"


def xsd_error(xml):
    """The first XSD error message, for assertions that name the offending attribute."""
    XSD12.validate(etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml))
    return str(XSD12.error_log.last_error) if XSD12.error_log else ""


def case_path(name):
    return os.path.join(ROOT, "conformance", "cases", name + ".xml")


def case_verdict(name):
    with open(case_path(name), "rb") as f:
        return verdict12(f.read())
