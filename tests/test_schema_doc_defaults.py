"""Every numeric default an attribute's documentation states is the default the declaration carries (SREP 92,
Semantics 4: where the documentation and a facet differ the facet governs, so the sentence must not differ)."""
import os
import re

from lxml import etree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XSD = os.path.join(ROOT, "schema", "scene-render.xsd")
XS = "{http://www.w3.org/2001/XMLSchema}"

# "default 64", "default is 0.5", "defaults to 1", "default: 4", "(default 0.1)"; not "default light grey" or "default 1 draws"
# read as "the default, 1, draws" — a number right after the word is the stated default.
STATED = re.compile(r"\bdefaults? (?:is |to |of |:)?(-?\d+(?:\.\d+)?)(?!\.\d|[\d%x×/])")


def _owner(attr):
    for anc in attr.iterancestors():
        if anc.get("name"):
            return anc.get("name")
    return "?"


def stated_defaults():
    """(owner/@name, declared default, number the documentation states) for every declared numeric default."""
    tree = etree.parse(XSD)
    out = []
    for attr in tree.iter(XS + "attribute"):
        declared = attr.get("default")
        if declared is None:
            continue
        try:
            value = float(declared)
        except ValueError:
            continue
        doc = " ".join(d.text or "" for d in attr.iter(XS + "documentation"))
        for m in STATED.finditer(doc):
            out.append((f"{_owner(attr)}/@{attr.get('name')}", value, float(m.group(1))))
    return out


def test_the_documentation_states_the_declared_default():
    rows = stated_defaults()
    assert len(rows) > 100, "the regex found too few stated defaults to be checking anything"
    wrong = [(a, d, s) for a, d, s in rows if d != s]
    assert wrong == [], f"documentation states a default the declaration does not carry: {wrong}"
