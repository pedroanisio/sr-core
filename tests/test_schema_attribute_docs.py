"""Every attribute declared in the schema is documented, or listed with a reason in an allow-list that can only shrink.

The documentation is annotation-only: the same documents are accepted and rejected as before (SREP draft
`srep-0000-schema-attribute-docs.md`).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

pytest.importorskip("lxml")
from lxml import etree  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XSD = os.path.join(ROOT, "schema", "scene-render.xsd")
ALLOW = os.path.join(ROOT, "tests", "undocumented-attributes.txt")
CASES = os.path.join(ROOT, "conformance", "cases")
BASE_COMMIT = "a960b65"
XS = "http://www.w3.org/2001/XMLSchema"
OWNERS = ("complexType", "attributeGroup", "element")


def _q(tag: str) -> str:
    return f"{{{XS}}}{tag}"


def attribute_docs(tree) -> dict[str, str]:
    """`owner/@name` -> documentation text ('' when absent) for every xs:attribute (a ref counts under its name)."""
    out: dict[str, str] = {}
    for att in tree.iter(_q("attribute")):
        owner = next(a for a in att.iterancestors() if a.tag in {_q(o) for o in OWNERS} and a.get("name"))
        name = att.get("name") or att.get("ref")
        key = f"{etree.QName(owner).localname}:{owner.get('name')}/@{name}"
        doc = "".join(att.xpath("xs:annotation/xs:documentation//text()", namespaces={"xs": XS})).strip()
        assert key not in out, f"{key} is declared twice under one owner"
        out[key] = doc
    return out


def allow_list() -> dict[str, str]:
    entries: dict[str, str] = {}
    with open(ALLOW, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, reason = line.partition(" # ")
            assert sep and reason.strip(), f"{ALLOW}:{n}: an entry is `owner/@name # reason`"
            assert key not in entries, f"{ALLOW}:{n}: {key} listed twice"
            entries[key.strip()] = reason.strip()
    return entries


def test_every_attribute_is_documented_or_allow_listed():
    docs = attribute_docs(etree.parse(XSD))
    allowed = allow_list()
    missing = sorted(k for k, d in docs.items() if not d and k not in allowed)
    assert not missing, f"{len(missing)} attributes have no documentation and are not in the allow-list: {missing[:10]}"


def test_allow_list_only_names_undocumented_attributes():
    """An entry whose attribute is documented, or no longer exists, must be removed: the list only shrinks."""
    docs = attribute_docs(etree.parse(XSD))
    stale = sorted(k for k in allow_list() if k not in docs or docs[k])
    assert not stale, f"remove from the allow-list (documented or gone): {stale[:10]}"


def test_schema_compiles():
    etree.XMLSchema(etree.parse(XSD))


def _base_xsd() -> bytes:
    if not shutil.which("git"):
        pytest.skip("git is not available")
    r = subprocess.run(["git", "-C", ROOT, "show", f"{BASE_COMMIT}:schema/scene-render.xsd"], capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"{BASE_COMMIT} is not in this checkout's history")
    return r.stdout


def _strip_annotations(root) -> bytes:
    for ann in list(root.iter(_q("annotation"))):
        ann.getparent().remove(ann)
    for el in root.iter():
        el.text = el.text if el.text and el.text.strip() else None
        el.tail = el.tail if el.tail and el.tail.strip() else None
    return etree.tostring(root, method="c14n")


def test_diff_against_base_is_annotation_only():
    base = etree.fromstring(_base_xsd())
    now = etree.parse(XSD).getroot()
    assert _strip_annotations(now) == _strip_annotations(base)


def test_corpus_verdicts_equal_the_base_schema():
    base = etree.XMLSchema(etree.fromstring(_base_xsd()))
    now = etree.XMLSchema(etree.parse(XSD))
    names = sorted(n for n in os.listdir(CASES) if n.endswith(".xml"))
    assert names
    for n in names:
        doc = etree.parse(os.path.join(CASES, n))
        assert base.validate(doc) == now.validate(doc), n
