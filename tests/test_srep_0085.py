"""SREP 85: decimal and double attributes are tested by value. The SREP's diff block, applied to the 1.5.0
Schematron with SREP 84 (exactly) and, by content, to the files with the drafts of SREPs 76 to 81, 83 and 84, its drafts
block (SREP 78's PYRO11 and PYC6, SREP 80's FRX11), applied by content to the latter, and its amendment of SREP 67
(ITR1, SRT1) give its kit cases their verdicts; each changed line is the line before with every numeric read of an
attribute in the '+'-stripping form; no numeric read of an attribute is left outside that form; no other kit case
changes verdict. SREP 85 is accepted: the canonical Schematron carries the three blocks, and with them taken back out
each kit case of this SREP has its verdict before SREP 85 and no other kit case changes verdict.
"""
import glob
import json
import os
import re
import sys

import pytest

etree = pytest.importorskip("lxml.etree")
from lxml import isoschematron  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
import engine_gap as gap  # noqa: E402
import srep85_cases  # noqa: E402

SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
SREP83 = os.path.join(ROOT, "srep", "srep-0083.md")
SREP84 = os.path.join(ROOT, "srep", "srep-0084.md")
SREP85 = os.path.join(ROOT, "srep", "srep-0085.md")
# the assertions the diffs change, and the lets (by rule context) whose rules read them
ACCEPTED = {"C13", "C14", "C15", "C37", "C38", "C44", "C52", "C53", "C54", "C56", "PYRO2", "PYRO4", "VOL4", "P3D3",
            "OCN3", "OCN5", "let nx (pyro)", "let ny (pyro)", "let nz (pyro)", "let start (particles3D)",
            "let life (particles3D)", "let dy (particles3D)", "let angle (particles3D/burst)",
            "let spread (particles3D/burst)", "let cell (ocean)", "let nx (ocean)", "let nz (ocean)"}
DRAFTED = {"PYRO11", "PYC6", "FRX11"}
AMENDED = {"ITR1", "SRT1"}
# the rules whose verdicts change: the assertions above, and PYRO1 and P3D10 through the lets they read
RULES = {"C13", "C14", "C15", "C37", "C38", "C44", "C52", "C53", "C54", "C56", "PYRO1", "PYRO2", "PYRO4", "VOL4", "P3D3",
         "P3D10", "OCN3", "OCN5", "PYRO11", "PYC6", "FRX11", "ITR1", "SRT1"}

assert gap.baseline() is not None, (
    "the schema 1.5.0 files are neither the git tag nor conformance/tools/baseline-1.5.0/ "
    "with the inventory's hashes")


def blocks(path, fence):
    return re.findall(rf"^```{fence}\n(.*?)^```", open(path, encoding="utf-8").read(), re.S | re.M)


def apply(files, block, exact):
    files = {p: b.decode().split("\n") for p, b in files.items()}
    (gap.apply_patch if exact else gap.apply_amendment)(files, block)
    return {p: "\n".join(v).encode() for p, v in files.items()}


def validators(files):
    xsd = etree.XMLSchema(etree.fromstring(files["schema/scene-render.xsd"]))
    sch = isoschematron.Schematron(etree.fromstring(files["schema/scene-render.sch"]), store_report=True)
    return xsd, sch


def verdict(validator, xml):
    xsd, sch = validator
    t = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode())
    if xsd is not None and not xsd.validate(t):
        return "xsd"
    if not sch.validate(t):
        return "sch:" + ",".join(sorted(set(sch.validation_report.xpath("//svrl:failed-assert/@id", namespaces=SVRL))))
    return "ok"


def want(case):
    f = case["expected"]["findings"]
    return "ok" if f["valid"] else "sch:" + ",".join(sorted(f["codes"]))


(MAIN84,) = blocks(SREP84, "diff")
(DRAFT84,) = blocks(SREP84, "diff drafts")
(V83,) = blocks(SREP83, "diff")
(MAIN,) = blocks(SREP85, "diff")
(DRAFT,) = blocks(SREP85, "diff drafts")
(AMEND67,) = blocks(SREP85, "diff amendment 67")
BASE84_FILES = apply(gap.baseline(), MAIN84, exact=True)
DRAFT84_FILES = apply(apply(apply(gap.proposed_schema(), V83, exact=False), MAIN84, exact=False), DRAFT84, exact=False)
BASE85_FILES = apply(BASE84_FILES, MAIN, exact=True)
DRAFT85_FILES = apply(apply(DRAFT84_FILES, MAIN, exact=False), DRAFT, exact=False)
BASE84, BASE85 = validators(BASE84_FILES), validators(BASE85_FILES)
DRAFTS84, DRAFTS85 = validators(DRAFT84_FILES), validators(DRAFT85_FILES)
CASES = json.load(open(os.path.join(ROOT, "conformance", "srep_cases", "srep-0085.json")))
OTHER = sorted(p for p in glob.glob(os.path.join(ROOT, "conformance", "cases", "*.xml"))
               if not os.path.basename(p).startswith("srep-0085-"))

# the '+'-stripping forms: R(P) for number(P), S(P) for sum(P) (0 for an absent attribute)
PATH = r"(?:/scene/project/@\w+|(?:\.\./|preceding-sibling::\w+\[1\]/|whitewater/)?@\w+|\.|(?:preceding|following)-sibling::\*\[\d\])"
R = re.compile(r"number\(substring\(normalize-space\((" + PATH + r")\),1\+number\(starts-with\(normalize-space\(\1\),'\+'\)\)\)\)")
S = re.compile(r"number\(concat\(substring\(normalize-space\((" + PATH + r")\),1\+number\(starts-with\(normalize-space\(\1\),"
               r"'\+'\)\)\),substring\('0',1,number\(not\(\1\)\)\)\)\)")
NUMBER = re.compile(r"number\((" + PATH + r")\)")


def back(line):
    """A changed line with its '+'-stripping reads written as number() and sum() again."""
    return R.sub(lambda m: f"number({m.group(1)})", S.sub(lambda m: f"sum({m.group(1)})", line))


def bare(line):
    """number(P) written P: an attribute that a comparison reads converts to a number in XPath 1.0 all the same."""
    return NUMBER.sub(lambda m: m.group(1), line)


def changed(old, new):
    """The changed lines of a one-for-one diff, keyed by assertion id or 'let <name> (<rule context>)'."""
    old, new = old.decode().split("\n"), new.decode().split("\n")
    assert len(old) == len(new), "the diff replaces lines one for one"
    out, context = {}, None
    for a, b in zip(old, new):
        m = re.search(r'<sch:rule context="([^"]+)"', a)
        context = m.group(1) if m else context
        if a == b:
            continue
        i = re.findall(r'<sch:assert id="([^"]+)"', b)
        n = re.findall(r'<sch:let name="([^"]+)"', b)
        assert len(i) + len(n) == 1, "each changed line is one assertion or one let"
        out[i[0] if i else f"let {n[0]} ({context})"] = (a, b)
    return out


def amendment_lines():
    """The removed and added lines of the amendment of SREP 67."""
    lines = AMEND67.split("\n")
    return [x[1:] for x in lines if x.startswith("-") and not x.startswith("---")], \
           [x[1:] for x in lines if x.startswith("+") and not x.startswith("+++")]


def srep67_rules(lines):
    """A Schematron of SREP 67's two rule contexts with these assertion lines, without XSD."""
    by = {re.search(r'id="([^"]+)"', x).group(1): x for x in lines}
    sch = ('<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt"><sch:pattern>'
           f'<sch:rule context="iterate">{by["ITR1"]}</sch:rule>'
           f'<sch:rule context="effects/effect[@type=\'segmented-sort\']">{by["SRT1"]}</sch:rule>'
           '</sch:pattern></sch:schema>')
    return None, isoschematron.Schematron(etree.fromstring(sch), store_report=True)


def test_the_diffs_change_the_listed_lines_and_nothing_else():
    assert set(changed(BASE84_FILES["schema/scene-render.sch"], BASE85_FILES["schema/scene-render.sch"])) == ACCEPTED
    assert set(changed(DRAFT84_FILES["schema/scene-render.sch"], DRAFT85_FILES["schema/scene-render.sch"])) == \
        ACCEPTED | DRAFTED
    old, new = amendment_lines()
    assert {re.search(r'id="([^"]+)"', x).group(1) for x in old + new} == AMENDED
    assert "scene-render.xsd" not in MAIN + DRAFT + AMEND67, "the XSD does not change"


def test_each_changed_line_reads_the_same_attributes_by_value():
    """Written back, every changed line is the line before: only the numeric reads of attributes change, and each of
    them is the '+'-stripping form of the number() or sum() it replaces."""
    pairs = list(changed(DRAFT84_FILES["schema/scene-render.sch"], DRAFT85_FILES["schema/scene-render.sch"]).values())
    pairs += list(zip(*amendment_lines()))
    for a, b in pairs:
        # (a line that SREP 84 already changed has that SREP's form for its integers: both are written back)
        assert len(R.findall(b)) + len(S.findall(b)) > len(R.findall(a)) + len(S.findall(a)), b
        assert bare(back(b)) == bare(back(a)), (a, b)


# a numeric read of an attribute or list item: number(P) or sum(P), or a bare attribute in a comparison or a test for 0
LEFT = [re.compile(r"(?<![\w-])(?:number|sum)\(" + PATH + r"\)"),
        re.compile(r"(?<![\w/.:])@\w+\s*(?:&lt;|&gt;|!?=\s*-?[\d.])"),
        re.compile(r"(?:&lt;|&gt;)=?\s*(?:\.\./|\w+/)*@\w+")]


def numeric_reads(sch):
    out = set()
    for line in sch.decode().split("\n"):
        if any(p.search(line) for p in LEFT):
            m = re.search(r'<sch:(?:assert id|let name)="([^"]+)"', line)
            out.add(m.group(1) if m else line.strip()[:60])
    return out


def test_no_numeric_read_of_an_attribute_is_left_outside_the_form():
    """What the SREP lists is all there is: before it, these lines read an attribute through number(), sum() or a
    bare comparison; after it, none does (PYRO8, P3D6, OCN7 and OCN14 read theirs through translate(.,'+',''), and
    C80, GEO2, PYRO11's followMargin, VOL6 and the drafts' lets through the form of SREP 84)."""
    before = numeric_reads(DRAFT84_FILES["schema/scene-render.sch"])
    assert before == {"C13", "C14", "C15", "C37", "C38", "C44", "C52", "C53", "C54", "C56", "PYRO2", "PYRO4", "VOL4",
                      "P3D3", "OCN3", "OCN5", "nx", "ny", "nz", "start", "life", "dy", "angle", "spread", "cell",
                      "PYRO11", "PYC6", "FRX11"}, before
    assert numeric_reads(DRAFT85_FILES["schema/scene-render.sch"]) == set()
    old, new = amendment_lines()
    assert numeric_reads("\n".join(old).encode()) == AMENDED
    assert numeric_reads("\n".join(new).encode()) == set()


@pytest.mark.parametrize("name", sorted(CASES))
def test_kit_case_verdict(name):
    case = CASES[name]
    requires = case["expected"].get("requires")
    if requires == [67]:
        # SREP 67's two rules, before and after the amendment, without XSD (the canonical schema, with SREP 67, is
        # checked below)
        old, new = amendment_lines()
        assert verdict(srep67_rules(new), case["xml"]) == want(case), name
        assert verdict(srep67_rules(old), case["xml"]) == srep85_cases.BEFORE[name], name
        return
    before, after = (DRAFTS84, (DRAFTS85,)) if requires else (BASE84, (BASE85, DRAFTS85))
    for v in after:
        assert verdict(v, case["xml"]) == want(case), name
    assert verdict(before, case["xml"]) == srep85_cases.BEFORE[name], name


def test_the_cases_cover_every_changed_rule_with_a_changed_verdict():
    """Each rule has at least one case whose verdict SREP 85 changes (it was bypassed or misfired before)."""
    changed_rules = {c["expected"]["rule"].split()[2] for n, c in CASES.items() if want(c) != srep85_cases.BEFORE[n]}
    assert changed_rules == RULES
    assert {c["expected"]["rule"].split()[2] for c in CASES.values()} == RULES


def test_the_cases_write_the_plus_one_and_plus_one_half_forms():
    """Every rule has a case with a value written "+1" and one with "+0.5" (for ITR1's integers, "+1" and "+20")."""
    for rule in RULES:
        xml = " ".join(c["xml"] for c in CASES.values() if c["expected"]["rule"].split()[2] == rule)
        assert re.search(r'="(?:[^"]* )?\+1[ "]', xml), rule
        assert re.search(r'="(?:[^"]* )?\+(?:0\.5|20)[ "]', xml), rule


def test_the_exponent_case_is_marked_native_only():
    """The one case that writes an exponent is marked native_only; libxml2's number() reads exponents (an extension
    of XPath 1.0), so this validator gives it the native verdict."""
    marked = {n for n, c in CASES.items() if "native_only" in c["expected"]}
    exponents = {n for n, c in CASES.items() if re.search(r'="[^"]*\d[eE][+-]?\d', c["xml"])}
    assert marked == exponents == {"srep-0085-c15-speed-exponent"}
    assert etree.fromstring('<a v="1e0"/>').xpath("number(@v)") == 1.0


@pytest.mark.parametrize("case", OTHER, ids=os.path.basename)
def test_no_other_kit_case_changes_verdict(case):
    xml = open(case, "rb").read()
    assert verdict(BASE85, xml) == verdict(BASE84, xml)
    assert verdict(DRAFTS85, xml) == verdict(DRAFTS84, xml)


CANONICAL = {p: open(os.path.join(ROOT, p), "rb").read() for p in ("schema/scene-render.xsd", "schema/scene-render.sch")}


def reverse(block):
    """A diff block with its sides swapped: applied by content, it takes the block back out."""
    swap = {"-": "+", "+": "-"}
    return "\n".join(x if x.startswith(("---", "+++")) or x[:1] not in swap else swap[x[0]] + x[1:]
                     for x in block.split("\n"))


def unapplied(files):
    """The files with SREP 85's three blocks taken back out, by content."""
    for block in (AMEND67, DRAFT, MAIN):
        files = apply(files, reverse(block), exact=False)
    return files


CANON, CANON_BEFORE = validators(CANONICAL), validators(unapplied(CANONICAL))


def test_the_canonical_schematron_carries_the_three_blocks():
    """Every line the three blocks add is in schema/scene-render.sch once and no line they remove is; taken back out,
    they change exactly the listed lines; the XSD is the one the blocks leave alone."""
    have = CANONICAL["schema/scene-render.sch"].decode().split("\n")
    for block in (MAIN, DRAFT, AMEND67):
        b = block.split("\n")
        assert all(have.count(x[1:]) == 1 for x in b if x.startswith("+") and not x.startswith("+++"))
        assert not {x[1:] for x in b if x.startswith("-") and not x.startswith("---")} & set(have)
    before = unapplied(CANONICAL)
    assert set(changed(before["schema/scene-render.sch"], CANONICAL["schema/scene-render.sch"])) == \
        ACCEPTED | DRAFTED | AMENDED
    assert before["schema/scene-render.xsd"] == CANONICAL["schema/scene-render.xsd"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_kit_case_verdict_on_the_canonical_schema(name):
    """With the canonical files (SREP 67, 78 and 80 included, XSD and all) each case has its verdict, and with SREP 85
    taken back out its verdict before SREP 85."""
    case = CASES[name]
    assert verdict(CANON, case["xml"]) == want(case), name
    assert verdict(CANON_BEFORE, case["xml"]) == srep85_cases.BEFORE[name], name


@pytest.mark.parametrize("case", OTHER, ids=os.path.basename)
def test_no_other_kit_case_changes_verdict_on_the_canonical_schema(case):
    xml = open(case, "rb").read()
    assert verdict(CANON, xml) == verdict(CANON_BEFORE, xml)
