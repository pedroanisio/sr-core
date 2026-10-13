"""Every attribute declared in the schema is documented, or listed with a reason in an allow-list that can only shrink.

Documentation edits (SREP 92, `srep-0092.md`) remain annotation-only except for the explicit declarations proposed by SREP 93.
The existing corpus keeps its XSD verdicts; focused SREP 93 tests cover the newly changed input boundaries.
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


def test_diff_against_base_is_annotation_only_except_srep91():
    base = etree.fromstring(_base_xsd())
    now = etree.parse(XSD).getroot()
    # Restore only the declared SREP 91 and SREP 93 attribute changes to their baseline declarations.
    # Any other structural edit still fails the canonical comparison below.
    changes = {
        "markerType": {"color"},
        "colorManagementType": {"bitDepth"},
        # SREP 93: antialias3d defaults to 4, the count the reference engine drew with.
        "projectType": {"mode", "antialias3d"},
        "shapeModifierType": {"ridges"},
        "modifierType": {"axis"},
        "fractalAssetType": {"palette"},
        "audiogramAssetType": {"smoothing"},
        "rigidBodyType": {"mass"},
        "chartAssetType": {"legend"},
        "oceanType": {"boundary", "spongeCells"},
        "pdfRegionType": {"x", "y", "width", "height"},
        "textAnimatorType": {"unit", "overlap"},
        "particleEmitterType": set(
            "lifetime lifetimeVariance speed direction spread gravityY drag turbulence size sizeVariance "
            "color rotationVariance angularVelocity angularVelocityVariance shape trail".split()
        ),
    }
    for owner, names in changes.items():
        old = base.find(f"{_q('complexType')}[@name='{owner}']")
        current = now.find(f"{_q('complexType')}[@name='{owner}']")
        for name in names:
            att = current.find(f"{_q('attribute')}[@name='{name}']")
            if att is not None:
                current.remove(att)
        # Insert from the end so each next sibling has already been restored.
        for att in reversed(list(old)):
            if att.tag == _q("attribute") and att.get("name") in names:
                following = att.getnext()
                if following is None:
                    current.append(etree.fromstring(etree.tostring(att)))
                else:
                    anchor = current.find(f"{following.tag}[@name='{following.get('name')}']")
                    current.insert(current.index(anchor), etree.fromstring(etree.tostring(att)))
    assert _strip_annotations(now) == _strip_annotations(base)


def test_corpus_verdicts_equal_the_base_schema():
    base = etree.XMLSchema(etree.fromstring(_base_xsd()))
    now = etree.XMLSchema(etree.parse(XSD))
    names = sorted(n for n in os.listdir(CASES) if n.endswith(".xml"))
    assert names
    for n in names:
        doc = etree.parse(os.path.join(CASES, n))
        assert base.validate(doc) == now.validate(doc), n


# ---- reviewed corrections (adversarial review against the engine code) ----

# The facets reject out-of-range values at validation time, so a doc must not say they are clamped. These three
# are not facet-bounded input: the clamp applies to a value computed from the attribute (a blend weight, the
# filtered pixel).
COMPUTED_VALUE_CLAMPS = {
    "complexType:textAnimatorType/@easeHigh",
    "complexType:textAnimatorType/@easeLow",
    "complexType:projectType/@supersample",
}
RANGE_LIMIT_WORDS = re.compile(r"clamp|capped|limited to", re.I)


def _facet_bounded(att, simple_types) -> bool:
    node = att.find(_q("simpleType"))
    if node is None:
        node = simple_types.get((att.get("type") or "").split(":")[-1])
    seen: set[str] = set()
    while node is not None:
        restriction = node.find(_q("restriction"))
        if restriction is None:
            return False
        if any(c.tag in {_q(f) for f in ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive")}
               for c in restriction):
            return True
        base = (restriction.get("base") or "").split(":")[-1]
        if base in seen or base not in simple_types:
            return False
        seen.add(base)
        node = simple_types[base]
    return False


def test_no_doc_claims_clamping_for_a_facet_bounded_attribute():
    tree = etree.parse(XSD)
    simple_types = {s.get("name"): s for s in tree.iter(_q("simpleType")) if s.get("name")}
    offenders = []
    for att in tree.iter(_q("attribute")):
        owner = next(a for a in att.iterancestors() if a.tag in {_q(o) for o in OWNERS} and a.get("name"))
        key = f"{etree.QName(owner).localname}:{owner.get('name')}/@{att.get('name') or att.get('ref')}"
        doc = "".join(att.xpath("xs:annotation/xs:documentation//text()", namespaces={"xs": XS}))
        if key in COMPUTED_VALUE_CLAMPS or not re.search("clamp", doc, re.I):
            continue
        if _facet_bounded(att, simple_types):
            offenders.append(key)
    assert not offenders, f"facet-bounded attributes whose doc says clamped (out-of-range is invalid): {offenders}"


@pytest.mark.parametrize("key", [
    "complexType:parametricPathType/@samples",
    "complexType:parametricSurfaceType/@uSamples",
    "complexType:parametricSurfaceType/@vSamples",
    "complexType:heightfieldType/@xSamples",
    "complexType:heightfieldType/@zSamples",
    "complexType:fractalAssetType/@maxIterations",
    "complexType:lightType/@shadowMapSize",
])
def test_range_limited_attribute_doc_does_not_claim_clamp_or_cap(key):
    doc = attribute_docs(etree.parse(XSD))[key]
    assert not RANGE_LIMIT_WORDS.search(doc), f"{key}: {doc}"


@pytest.mark.parametrize("key, phrase", [
    ("attributeGroup:transformAttributes/@scaleX", "before skew"),
    ("attributeGroup:transformAttributes/@scaleY", "before skew"),
    ("complexType:particleEmitterType/@preset", "all but rate"),
    ("complexType:particles3DType/@color", "colorEnd"),
    ("complexType:outputType/@codec", "png-sequence"),
    ("complexType:lightType/@range", "lighting effect"),
    ("complexType:chartSeriesType/@name", "legend"),
    ("complexType:chartSeriesType/@values", "Whitespace-separated numbers"),
    ("complexType:representationType/@width", "Declared width"),
    ("complexType:representationType/@height", "Declared height"),
    ("complexType:videoAssetType/@timecodeStart", "source in and out timecodes"),
    ("complexType:audioAssetType/@sampleRate", "Hz"),
    ("complexType:layoutType/@aspect", "W * height equals H * width"),
    ("complexType:lightType/@shadowBias", "normalized shadow-map"),
    ("complexType:lightType/@skyExponent", "dimensionless"),
    ("complexType:constraintType/@maxForce", "newton-metres"),
    ("complexType:constraintType/@breakForce", "newtons"),
])
def test_reviewed_correction_is_present(key, phrase):
    doc = attribute_docs(etree.parse(XSD))[key]
    assert phrase in doc, f"{key}: {doc}"


def test_particles3d_color_is_not_described_as_a_birth_only_tint():
    doc = attribute_docs(etree.parse(XSD))["complexType:particles3DType/@color"]
    assert "Tint of the particles at birth" not in doc, doc
