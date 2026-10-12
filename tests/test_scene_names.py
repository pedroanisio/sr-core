"""XML name character classes (F4).

XML Schema 1.0 Second Edition (https://www.w3.org/TR/xmlschema-2/), sections 3.3.4 to 3.3.9, defines NMTOKEN and Name
by the productions of "[XML 1.0 (Second Edition)]" and NCName, ID and IDREF by the NCName production of "[Namespaces
in XML]" (1999), which is built from the Letter, Digit, CombiningChar and Extender classes of XML 1.0 (Second
Edition) Appendix B (https://www.w3.org/TR/2000/REC-xml-20001006#CharClasses). libxml2 implements those classes, so
the SDK must too. The tables in ``values.py`` were generated from the productions [84] to [89] of that text.
"""
from __future__ import annotations

import hashlib
import os

import pytest

from sr_core.scene import values
from sr_core.scene.values import codec_for

SKIP_WS = {0x9, 0xA, 0xD, 0x20}


def test_range_tables_are_pinned() -> None:
    blob = repr((values.NAME_START_RANGES, values.NAME_CHAR_RANGES)).encode()
    assert len(values.NAME_START_RANGES) == 204
    assert len(values.NAME_CHAR_RANGES) == 287
    assert hashlib.sha256(blob).hexdigest() == "3e76feb42692ef05be5e3e41ae534197a79d78f2fd3264752fd9ba60d1f10fbb"


@pytest.mark.parametrize("ch,start,rest", [
    ("a", True, True), ("_", True, True), ("-", False, True), (".", False, True), ("0", False, True),
    ("١", False, True),   # ARABIC-INDIC DIGIT ONE: a Digit, not a Letter
    ("\u0133", False, False),  # LATIN SMALL LIGATURE IJ: not in BaseChar (U+0132-0133 are unlisted)
    ("⺀", False, False),  # CJK RADICAL: a start character only in the fifth edition
    ("·", False, True),   # Extender
    ("̀", False, True),   # CombiningChar
    ("〇", True, True),    # Ideographic
    ("\U00010000", False, False),
    (":", False, False),       # not an NCName character
])
def test_ncname_spot_code_points(ch: str, start: bool, rest: bool) -> None:
    ncname = codec_for("xs:NCName", {})
    assert ncname.is_valid_lexical(ch) is start
    assert ncname.is_valid_lexical("a" + ch) is rest


def test_name_nmtoken_and_ids_use_the_same_classes() -> None:
    for kind in ("xs:ID", "xs:IDREF", "xs:NCName"):
        assert not codec_for(kind, {}).is_valid_lexical("١٢")
    assert not codec_for("xs:IDREFS", {}).is_valid_lexical("ok ١")
    assert codec_for("xs:NMTOKEN", {}).is_valid_lexical("١:x")
    assert not codec_for("xs:NMTOKENS", {}).is_valid_lexical("ok ⺀")
    assert values._NAME.fullmatch(":a١")
    assert not values._NAME.fullmatch("١a")


# ---------------------------------------------------------------------------------------------- lxml sweep

def _lxml_verdicts(strings: list[str]) -> list[tuple[bool, bool, bool]]:
    from lxml import etree

    xsd = etree.fromstring(
        b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="r"><xs:complexType>'
        b'<xs:choice maxOccurs="unbounded"><xs:element name="n" type="xs:NCName"/>'
        b'<xs:element name="t" type="xs:NMTOKEN"/><xs:element name="m" type="xs:Name"/>'
        b"</xs:choice></xs:complexType></xs:element></xs:schema>")
    schema = etree.XMLSchema(xsd)
    out: list[tuple[bool, bool, bool]] = []
    for lo in range(0, len(strings), 4000):
        chunk = strings[lo:lo + 4000]
        rows = []
        for s in chunk:
            esc = s.replace("&", "&amp;").replace("<", "&lt;")
            rows.append(f"<n>{esc}</n><t>{esc}</t><m>{esc}</m>")
        body = "".join(r.replace("</m>", "</m>\n") if False else r + "\n" for r in rows)
        tree = etree.fromstring(("<r>\n" + body + "</r>").encode("utf-8"))
        schema.validate(tree)
        bad: set[tuple[int, str]] = set()
        for entry in schema.error_log:
            bad.add((entry.line, "n" if "NCName" in entry.message else "t" if "NMTOKEN" in entry.message else "m"))
        for i in range(len(chunk)):
            line = i + 2
            bad_n = (line, "n") in bad
            bad_t = (line, "t") in bad
            bad_m = (line, "m") in bad
            out.append((not bad_n, not bad_t, not bad_m))
    return out


@pytest.mark.corpus
@pytest.mark.skipif(os.environ.get("SR_SCENE_CORPUS") == "0", reason="corpus test switched off with SR_SCENE_CORPUS=0")
def test_sweep_agrees_with_lxml_on_every_code_point() -> None:
    pytest.importorskip("lxml")
    points = [c for c in range(0x2FFFF + 1)
              if c not in SKIP_WS and not 0xD800 <= c <= 0xDFFF and c not in (0xFFFE, 0xFFFF)
              and (c >= 0x20 or c in SKIP_WS)]
    for label, build in (("first", lambda ch: ch), ("rest", lambda ch: "a" + ch)):
        strings = [build(chr(c)) for c in points]
        verdicts = _lxml_verdicts(strings)
        diffs = []
        for c, s, (ncn, nmt, nm) in zip(points, strings, verdicts):
            mine = (values._NCNAME.fullmatch(s) is not None, values._NMTOKEN.fullmatch(s) is not None,
                    values._NAME.fullmatch(s) is not None)
            if mine != (ncn, nmt, nm):
                diffs.append((hex(c), mine, (ncn, nmt, nm)))
        assert not diffs, f"{label}: {len(diffs)} differences, first {diffs[:5]}"
