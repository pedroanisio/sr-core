"""D6 (SREP 91, section 9): the SDK's value-space checks agree with the XSD, as lxml decides them.

For every attribute whose simple type has facets or enumerations (named, inline, or reached through a list or a union),
probes are generated from the type: each enumeration value and a non-member; each numeric bound, inclusive and
exclusive, and a step beyond it; the examples in the documentation and derived positives and negatives of a pattern;
lengths at and beyond a bound. Each probe is put on that attribute of a minimal valid document (built from the content
model, with the required attributes filled in) and judged by lxml's XSD validation. The SDK codec
(`is_valid_lexical`) and, for numbers and strings, the `Attr` setter must accept or refuse exactly as lxml does.

Every disagreement is a bug in `sr_core.scene.values` (or the generated specs). Hosts that cannot be built generically
are logged, and the count of them is asserted against `HAND_TEMPLATES`, so nothing is skipped silently.

Runs by default (needs lxml; `SR_SCENE_CORPUS=0` skips it). `SR_SCENE_CORPUS_STRIDE=N` runs
every N-th probe.
"""
from __future__ import annotations

import collections
import itertools
import logging
import math
import os
import random
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.corpus,
    pytest.mark.skipif(os.environ.get("SR_SCENE_CORPUS") == "0", reason="corpus test switched off with SR_SCENE_CORPUS=0"),
]
etree = pytest.importorskip("lxml.etree")

from sr_core.schemadoc import model  # noqa: E402
from sr_core.scene import _generated as G  # noqa: E402
from sr_core.scene.errors import SchemaError, SchemaValueError  # noqa: E402
from sr_core.scene.values import codec_for, translate_pattern  # noqa: E402

try:
    import re._parser as sre_parse  # Python >= 3.11
except ImportError:  # pragma: no cover
    import sre_parse  # type: ignore[no-redef]

log = logging.getLogger("d6")
ROOT = Path(__file__).resolve().parent.parent
STRIDE = max(1, int(os.environ.get("SR_SCENE_CORPUS_STRIDE", "1")))
TABLE = G.SIMPLE_TYPES

# libxml2 before 2.13 refuses xs:decimal values of more than 24 digits (SREP open issue 4; tests/test_schema_rules.py).
SHORT_DECIMALS = etree.LIBXML_VERSION < (2, 13, 0)
DIGITS = re.compile(r"[0-9]")

# Hosts that cannot be built generically, with a hand-written template: {complex type key: XML text of a minimal valid
# document that holds one element of that type, the host element being the first element named in HOST_ELEMENT}.
# Empty means the generic builder reaches every host; the coverage test fails if one appears that it cannot reach.
HAND_TEMPLATES: dict[str, str] = {}


# ----------------------------------------------------------------------------------------------- the type tree
BUILTIN_FAMILY = {
    "xs:double": "double", "xs:decimal": "decimal", "xs:integer": "integer", "xs:int": "integer",
    "xs:positiveInteger": "integer", "xs:nonNegativeInteger": "integer", "xs:unsignedLong": "integer",
    "xs:boolean": "boolean", "xs:dateTime": "datetime", "xs:string": "string", "xs:anyURI": "string",
    "xs:ID": "token", "xs:IDREF": "token", "xs:NCName": "token", "xs:NMTOKEN": "token",
    "xs:IDREFS": "tokens", "xs:NMTOKENS": "tokens",
}
BUILTIN_SAMPLES = {
    "double": ["1", "0", "-1", "0.5", "1e2", "1E2", "+1", ".5", "5.", "-0", "INF", "-INF", "NaN", "", " ", "abc", " 1 ",
               "1 2", "1_0", "0x10", "1e", "--1", "1e400", "1.5e-3", "\n1\n"],
    "decimal": ["1", "0", "-1", "0.5", "+1", ".5", "5.", "1.0", "01", "-0", "1e1", "", " ", "abc", " 1 ", "1,5", "1 2",
                "1_0", "--1", "\t2\t"],
    "integer": ["1", "0", "-1", "2", "+1", "01", "1.0", "1.", "1e1", "-0", "", " ", "abc", " 1 ", "1 2", "0x1", "1_0"],
    "boolean": ["true", "false", "1", "0", "TRUE", ""],
    "datetime": ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00", "2026-13-01T00:00:00Z", "2026-01-01", ""],
    "string": ["a", "", " ", "abc", " a ", "a b", "ä", "x" * 3],
    "token": ["a", "A1", "a-b", "a.b", "1a", "a b", " a ", "", "a:b"],
    "tokens": ["a", "a b", "", " a  b "],
}
URI_SAMPLES = [
    "", "#", "?", "a%41", "%", "a%", "%zz", "%4", "%%", "#a#b", "a#b#", "a?b#c#d", "[", "]", "a[b]", "x]", "http://x/[1]",
    "http://[::1]/p", "http://[::1/", "http://[:::1]/", "http://[1:2]/", "http://[v1.x]/", "http://[v.x]/",
    "http://[2001:db8::7]/", "http://[::ffff:1.2.3.4]/", "http://u:p@h:80/p?q=1/2?#f", "http://h:p/", "http://127.0.0.1:8080",
    ":::", "1:2", ":a", "a:b:c", "mailto:x@y", "//h/p", "/a//b", "~u/x", "a b", "a\tb", "é.png", "日本/x", "\U0001F600",
    "a<b>{c}|d\\e^f`g\"h", "\x7f", "file:///a%20b.png", "a%d", "http://exa mple.com", "\u00a0", "\ufffd",
]
NUMERIC = {"double", "decimal", "integer"}
LENGTH_FACETS = ("length", "minLength", "maxLength")
BOUND_FACETS = ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive")
DOC = {name: st.doc for name, st in model.read(
    (ROOT / "schema/scene-render.xsd").read_bytes(), (ROOT / "schema/scene-render.sch").read_bytes(),
    "scene-render.xsd", "scene-render.sch").simple.items()}


@dataclass(eq=False)
class Node:
    """A simple type resolved from an SDK spec: builtin, restriction (also with facets on a list or union), list or union."""

    ref: Any
    kind: str
    name: str | None = None
    builtin: str | None = None
    enums: tuple[str, ...] = ()
    facets: tuple[tuple[str, str], ...] = ()
    base: Node | None = None
    item: Node | None = None
    members: tuple[Node, ...] = ()
    _probes: list[str] | None = field(default=None, repr=False)
    _sample: str | None = field(default=None, repr=False)
    _sampled: bool = field(default=False, repr=False)

    @property
    def family(self) -> str:
        if self.kind == "builtin":
            return BUILTIN_FAMILY[self.builtin]
        if self.kind == "restriction":
            return self.base.family
        return self.kind

    def interesting(self) -> bool:
        """True if this type, or anything it is built from, has an enumeration or a facet."""
        if self.enums or self.facets:
            return True
        return any(n.interesting() for n in ([self.base, self.item] if self.base or self.item else []) + list(self.members)
                   if n is not None)

    def codec(self) -> Any:
        return codec_for(self.ref, TABLE)


def resolve(ref: Any) -> Node:
    if isinstance(ref, str):
        if ref.startswith("xs:"):
            return Node(ref, "builtin", builtin=ref)
        node = resolve(TABLE[ref])
        node.ref, node.name = ref, ref
        return node
    kind = ref["kind"]
    enums = tuple(e[0] if isinstance(e, (tuple, list)) else e for e in ref.get("enums") or ())
    facets = tuple((f, v) for f, v in ref.get("facets") or ())
    if kind == "restriction":
        return Node(ref, "restriction", enums=enums, facets=facets, base=resolve(ref["base"]))
    if kind == "list":
        node = Node(ref, "list", enums=enums, facets=facets, item=resolve(ref["item"]))
    else:
        node = Node(ref, "union", enums=enums, facets=facets, members=tuple(resolve(m) for m in ref["members"]))
    return node


# ---------------------------------------------------------------------------------------------------- probes
def xml_legal(s: str) -> bool:
    return all(c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or ord(c) >= 0x10000 for c in s)


CATEGORY_CHAR = {"CATEGORY_DIGIT": "7", "CATEGORY_NOT_DIGIT": "x", "CATEGORY_SPACE": " ", "CATEGORY_NOT_SPACE": "x",
                 "CATEGORY_WORD": "w", "CATEGORY_NOT_WORD": "-"}


def gen_regex(sub: Any, rnd: random.Random) -> str:
    out = []
    for op, av in sub:
        name = str(op)
        if name == "LITERAL":
            out.append(chr(av))
        elif name == "NOT_LITERAL":
            out.append("a" if chr(av) != "a" else "b")
        elif name == "ANY":
            out.append(rnd.choice("aZ5-"))
        elif name == "IN":
            items = list(av)
            if any(str(o) == "NEGATE" for o, _ in items):
                banned = {chr(v) for o, v in items if str(o) == "LITERAL"}
                out.append(next(c for c in "aZ5_~" if c not in banned))
                continue
            o, v = rnd.choice(items)
            if str(o) == "LITERAL":
                out.append(chr(v))
            elif str(o) == "RANGE":
                out.append(chr(rnd.choice([v[0], v[1], rnd.randint(v[0], min(v[1], v[0] + 80))])))
            else:
                out.append(CATEGORY_CHAR[str(v)])
        elif name == "BRANCH":
            out.append(gen_regex(rnd.choice(av[1]), rnd))
        elif name == "SUBPATTERN":
            out.append(gen_regex(av[-1], rnd))
        elif name in ("MAX_REPEAT", "MIN_REPEAT"):
            lo, hi, body = av
            hi = lo + 2 if hi >= 65535 or hi > lo + 3 and rnd.random() < 0.5 else hi
            n = rnd.choice([lo, lo + 1 if lo + 1 <= hi else lo, hi])
            out.extend(gen_regex(body, rnd) for _ in range(n))
        elif name == "AT":
            continue
        else:
            raise ValueError(f"regex op {name} not handled by the probe generator")
    return "".join(out)


def pattern_positives(pattern: str, seed: str) -> list[str]:
    rnd = random.Random(seed)
    parsed = sre_parse.parse(translate_pattern(pattern))
    found: dict[str, None] = {}
    for _ in range(24):
        try:
            s = gen_regex(parsed, rnd)
        except ValueError:
            break
        if xml_legal(s):
            found[s] = None
    return list(found)[:10]


def mutate(s: str) -> list[str]:
    out = [s + "x", s + " ", " " + s, s + "\n", "x" + s]
    if s:
        out += [s[1:], s[:-1], s[:-1] + "~", s.upper(), s.lower(), s[0] + s]
    return out


def doc_examples(text: str) -> list[str]:
    found = re.findall(r'"([^"\n]{1,60})"', text or "")
    found += re.findall(r"\b(?:var|url)\([^)\s]+\)", text or "") + re.findall(r"#[0-9A-Fa-f]{3,8}\b", text or "")
    return [f for f in found if xml_legal(f)]


def decimals_around(bound: str, family: str) -> list[str]:
    b = Decimal(bound)
    if family == "integer":
        steps = [Decimal(1), Decimal(2)]
    else:
        steps = [Decimal("0.000001"), Decimal("0.000000000001")]
    out = [bound, format(b, "f")]
    for d in steps:
        out += [format(b + d, "f"), format(b - d, "f")]
    if family == "double":
        x = float(b)
        for y in (math.nextafter(x, math.inf), math.nextafter(x, -math.inf)):
            out.append(format(Decimal(repr(y)), "f"))
    return out


def numeric_variants(lit: str, family: str) -> list[str]:
    out = [f"+{lit}" if not lit.startswith("-") else lit, f" {lit} ", f"{lit}.0", f"0{lit}" if lit[0].isdigit() else lit]
    if family == "integer":
        out += [f"{lit}e0"]
    return out


def sample_items(node: Node, n: int) -> str | None:
    s = sample(node)
    return None if s is None else " ".join([s] * n)


def own_probes(node: Node) -> list[str]:
    out: list[str] = []
    fam = node.family
    if node.enums:
        for lit in node.enums:
            out.append(lit)
            if fam in NUMERIC:
                out += numeric_variants(lit, fam)
            elif fam in ("string", "token"):
                out += [lit.upper(), lit.capitalize(), lit + " ", " " + lit, lit[:-1], lit + "x"]
        out += ["zz-not-a-member", "", " "]
        if fam in NUMERIC:
            out += [str(Decimal(node.enums[0]) + 1 if fam != "integer" else int(node.enums[0]) + 1), "-1", "0", "7"]
    for facet, value in node.facets:
        if facet in BOUND_FACETS and fam in NUMERIC:
            out += decimals_around(value, fam)
        elif facet in LENGTH_FACETS:
            n = int(value)
            for m in sorted({max(n - 1, 0), n, n + 1}):
                if fam in ("string", "token"):
                    out.append("a" * m)
                    if m <= 70:
                        out += ["\U0001F600" * m, "é" * m]
                else:
                    s = sample_items(node.item if node.kind == "list" else node.base.item if node.base and node.base.kind == "list" else node, m) if m else ""
                    if s is not None:
                        out.append(s)
        elif facet == "pattern":
            positives = pattern_positives(value, f"{node.name}:{value}")
            out += positives + doc_examples(DOC.get(node.name or "", ""))
            for p in positives[:4]:
                out += mutate(p)
    return out


def probes(node: Node) -> list[str]:
    if node._probes is not None:
        return node._probes
    node._probes = []  # recursion guard
    out: list[str] = []
    if node.kind == "builtin":
        out += BUILTIN_SAMPLES[BUILTIN_FAMILY[node.builtin]]
        if node.builtin == "xs:anyURI":
            out += URI_SAMPLES
    elif node.kind == "restriction":
        out += probes(node.base)
    elif node.kind == "list":
        item = probes(node.item)
        out += item + ["", " ", " ".join(item[:2]), " ".join(item[:3])]
    else:
        for m in node.members:
            out += probes(m)
    out += own_probes(node)
    node._probes = [s for s in dict.fromkeys(out) if xml_legal(s)]
    return node._probes


def sample(node: Node) -> str | None:
    """A lexical form the SDK codec accepts for this type (non-empty if possible)."""
    if not node._sampled:
        codec = node.codec()
        good = [s for s in probes(node) if codec.is_valid_lexical(s)]
        pick = node.enums[0] if node.enums else None
        node._sample = pick if pick else next((s for s in good if s.strip() == s and s), good[0] if good else None)
        node._sampled = True
    return node._sample


# ------------------------------------------------------------------------------- minimal documents (content model)
S = model.read((ROOT / "schema/scene-render.xsd").read_bytes(), (ROOT / "schema/scene-render.sch").read_bytes(),
               "scene-render.xsd", "scene-render.sch")
XSD_DOC = etree.parse(str(ROOT / "schema/scene-render.xsd"))
XSD = etree.XMLSchema(XSD_DOC)
INF_COST = 10 ** 9


def contents(key: str) -> list[Any]:
    """The top particles of `key`: its extension bases' first (the base's content precedes the extension's)."""
    chain, t = [], S.complex[key]
    while t is not None:
        chain.append(t)
        t = S.complex.get(t.base) if t.base else None
    return [t.content for t in reversed(chain) if t.content is not None]


def lo_hi(p: Any) -> tuple[int, int]:
    return int(p.min), (10 ** 6 if p.max == "unbounded" else int(p.max))


def can_hold(p: Any, name: str) -> bool:
    if p.kind == "element":
        return p.name == name
    if p.kind == "group":
        return can_hold(S.groups[p.name].content, name)
    return any(can_hold(c, name) for c in p.children)


_COST: dict[str, int] = {}


def type_cost(key: str) -> int:
    if key in _COST:
        return _COST[key]
    _COST[key] = INF_COST  # a cycle through required content has no finite cost
    total = sum(particle_cost(c, True) for c in contents(key))
    _COST[key] = min(total, INF_COST)
    return _COST[key]


def particle_cost(p: Any, force: bool) -> int:
    """Elements the cheapest instance of `p` needs; zero when it is optional and not forced."""
    if not force and lo_hi(p)[0] == 0:
        return 0
    if p.kind == "element":
        return 1 + type_cost(p.type)
    if p.kind == "group":
        return particle_cost(S.groups[p.name].content, True)
    if p.kind == "sequence":
        return min(sum(particle_cost(c, False) for c in p.children), INF_COST)
    return min((particle_cost(c, True) for c in p.children), default=INF_COST)


def expand(p: Any, must: str | None, force: bool = False) -> list[tuple[str, str, bool]] | None:
    """Child elements (name, type, is_the_must_one) in content-model order, or None if `p` cannot hold `must`."""
    holds = must is not None and can_hold(p, must)
    if must is not None and not holds:
        return None
    if not holds and not force and lo_hi(p)[0] == 0:
        return []
    if p.kind == "element":
        return [(p.name, p.type, holds)] * max(lo_hi(p)[0], 1 if holds else 0)
    if p.kind == "group":
        return expand(S.groups[p.name].content, must, True)
    if p.kind == "sequence":
        out: list[tuple[str, str, bool]] = []
        placed = False
        for c in p.children:
            got = expand(c, must if holds and not placed and can_hold(c, must) else None)
            if holds and not placed and can_hold(c, must):
                placed = True
            out += got
        return out
    # choice
    if holds:
        return next(r for c in p.children if can_hold(c, must) for r in [expand(c, must, True)] if r is not None)
    best = min(p.children, key=lambda c: particle_cost(c, True))
    return expand(best, None, True)


def children_of(key: str, must: str | None) -> list[tuple[str, str, bool]] | None:
    out: list[tuple[str, str, bool]] = []
    placed = False
    for c in contents(key):
        want = must if must is not None and not placed and can_hold(c, must) else None
        got = expand(c, want, force=True) if want else expand(c, None)
        if got is None:
            return None
        placed = placed or want is not None
        out += got
    return out if must is None or placed else None


def class_attr(key: str, xml_name: str) -> Any:
    for klass in G.CLASSES[key].__mro__:
        for v in vars(klass).values():
            if getattr(v, "xml_name", None) == xml_name and hasattr(v, "spec"):
                return v
    raise KeyError((key, xml_name))


def has_id(key: str) -> str | None:
    return next((a.name for a in S.all_attributes(key) if a.type == "xs:ID"), None)


class Unreachable(Exception):
    pass


class Builder:
    """Builds the minimal valid document around one host type: root -> ... -> host element, by shortest path."""

    def __init__(self) -> None:
        self.paths: dict[str, list[tuple[str, str]]] = {"#root": []}
        queue = ["#root"]
        for key in queue:  # breadth first: the shortest path to every type
            for p in S.children(key):
                if p.type not in self.paths:
                    self.paths[p.type] = self.paths[key] + [(p.name, p.type)]
                    queue.append(p.type)
        self.counter = itertools.count(1)

    def element(self, name: str, key: str, rest: list[tuple[str, str]], ids: list[str],
                refs: list[tuple[Any, str]]) -> Any:
        el = etree.Element(name)
        for a in S.all_attributes(key):
            if a.use != "required":
                continue
            node = resolve(class_attr(key, a.name).spec)
            if a.type == "xs:ID":
                el.set(a.name, f"i{next(self.counter)}")
            elif a.type in ("xs:IDREF", "xs:IDREFS"):
                el.set(a.name, "")
                refs.append((el, a.name))
            elif a.fixed is not None:
                el.set(a.name, a.fixed)
            else:
                value = a.default if a.default is not None and node.codec().is_valid_lexical(a.default) else sample(node)
                if value is None:
                    raise Unreachable(f"no valid sample for required {key}/@{a.name}")
                el.set(a.name, value)
        idname = has_id(key)
        if idname:
            if el.get(idname) is None:
                el.set(idname, f"i{next(self.counter)}")
            ids.append(el.get(idname))
        step = rest[0] if rest else None
        kids = children_of(key, step[0] if step else None)
        if kids is None:
            raise Unreachable(f"{key} cannot hold <{step[0]}>")
        led = False
        for cname, ckey, is_must in kids:
            lead = is_must and not led and (cname, ckey) == step
            led = led or lead
            el.append(self.element(cname, ckey, rest[1:] if lead else [], ids, refs))
        return el

    def document(self, key: str) -> Any:
        """The root of a minimal valid document that holds one element of type `key`."""
        if key not in self.paths:
            raise Unreachable(f"{key} is not reachable from the root")
        ids: list[str] = []
        refs: list[tuple[Any, str]] = []
        root = self.element("scene", "#root", self.paths[key], ids, refs)
        for el, name in refs:
            if not ids:
                raise Unreachable("an IDREF is required and no element in the document has an id")
            el.set(name, ids[0])
        return root


BUILDER = Builder()


def type_of(el: Any) -> str:
    parent = el.getparent()
    if parent is None:
        return "#root"
    pk = type_of(parent)
    for p in S.children(pk):
        if p.name == el.tag:
            return p.type
    raise Unreachable(f"<{el.tag}> not allowed in {pk}")


def locate(root: Any, key: str) -> Any:
    """The host element: follow the shortest path, taking at each level the child whose type leads on."""
    host = root
    for name, typ in BUILDER.paths[key]:
        host = next((c for c in host if c.tag == name and type_of(c) == typ), None)
        if host is None:
            raise Unreachable(f"cannot find <{name}> of type {typ}")
    return host


# --------------------------------------------------------------------------------------------------- the hosts
@dataclass
class Host:
    key: str
    attr: str
    node: Node
    ref: Any
    root: Any = None
    el: Any = None
    why: str | None = None


def interesting_hosts() -> list[Host]:
    hosts = []
    for key in S.complex:
        if key not in G.CLASSES:
            continue
        for a in S.all_attributes(key):
            if a.use == "prohibited":
                continue
            attr = class_attr(key, a.name)
            node = resolve(attr.spec)
            if node.interesting():
                hosts.append(Host(key, a.name, node, attr))
    return hosts


def prepare(host: Host, cache: dict[str, tuple[Any, Any] | str]) -> None:
    """Build the document for the host's type once, and check that a valid value on the host attribute validates."""
    if host.key not in cache:
        try:
            root = BUILDER.document(host.key)
            cache[host.key] = (root, locate(root, host.key))
        except Unreachable as e:
            cache[host.key] = str(e)
    got = cache[host.key]
    if isinstance(got, str):
        host.why = got
        return
    host.root, host.el = got
    value = sample(host.node)
    if value is None:
        host.why = "no SDK-valid sample for the host attribute"
        return
    previous = host.el.get(host.attr)
    host.el.set(host.attr, value)
    ok = XSD.validate(host.root)
    if previous is None:
        del host.el.attrib[host.attr]
    else:
        host.el.set(host.attr, previous)
    if not ok:
        host.why = f"base document is invalid with {value!r}: {XSD.error_log.last_error}"
        host.root = host.el = None


# ----------------------------------------------------------------------------------------------- judging probes
STRICT_NUMBER = re.compile(r"[+-]?(?:[0-9]{1,15}(?:\.[0-9]{0,15})?|\.[0-9]{1,15})")
STRICT_INT = re.compile(r"[+-]?[0-9]{1,18}")


def lxml_valid(host: Host, lexical: str) -> bool:
    previous = host.el.get(host.attr)
    host.el.set(host.attr, lexical)
    try:
        return bool(XSD.validate(host.root))
    finally:
        if previous is None:
            del host.el.attrib[host.attr]
        else:
            host.el.set(host.attr, previous)


def setter_python_value(node: Node, s: str) -> tuple[bool, Any]:
    """(usable, the Python value a caller would pass for the lexical `s`) for the families the setter can be checked on."""
    fam = node.family
    if fam == "double" and STRICT_NUMBER.fullmatch(s):
        return True, float(s)
    if fam == "decimal" and STRICT_NUMBER.fullmatch(s):
        return True, Decimal(s)
    if fam == "integer" and STRICT_INT.fullmatch(s):
        return True, int(s)
    if fam == "string" and node.builtin is None:
        return True, s
    return False, None


# libxml2 (the oracle) departs from XSD 1.0 / RFC 3986 in three places. Each is recognised narrowly, counted, logged, and pinned by
# test_known_libxml2_deviations_still_hold, so that a fixed libxml2 makes that test fail and the entry is removed.
EMPTY_EXPONENT = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)[eE][+-]?")


def has_builtin(node: Node, name: str) -> bool:
    return node.builtin == name or any(has_builtin(n, name) for n in [node.base, node.item, *node.members] if n)


def has_range_facet(node: Node) -> bool:
    return any(f in BOUND_FACETS for f, _ in node.facets) or any(
        has_range_facet(n) for n in [node.base, node.item, *node.members] if n)


# Exact strings only. RFC 3986 3.2.2: IP-literal = "[" ( IPv6address / IPvFuture ) "]". "[:::1]" and "[1:2]" are not
# IPv6addresses and "[v.x]" is not an IPvFuture (needs 1*HEXDIG after "v"); libxml2 checks only the brackets.
LAX_IP_LITERALS = {"http://[:::1]/", "http://[1:2]/", "http://[v.x]/"}


def known_deviation(host: Host, lexical: str, want: bool, got: bool) -> str | None:
    """Why a disagreement is lxml departing from XSD 1.0 (Part 2), or None when it is not a known departure."""
    node = host.node
    if want and not got and node.family in ("double", "union") and EMPTY_EXPONENT.fullmatch(lexical.strip()):
        return "libxml2 accepts an xs:double with an empty exponent ('1e'); XSD 1.0 3.2.5.1 needs digits"
    if want and not got and lexical.strip() == "NaN" and has_range_facet(node):
        return "libxml2 lets NaN pass range facets; XSD 1.0 3.2.5.1/4.3.7: NaN is incomparable, so it violates them"
    if got is False and want and lexical in LAX_IP_LITERALS:
        return "libxml2 accepts a malformed IP-literal in xs:anyURI; RFC 3986 3.2.2 refuses it"
    return None


def judge(host: Host, lexical: str, counts: dict[str, int]) -> list[str]:
    """The disagreements about one probe, as messages (empty when the SDK and lxml agree)."""
    where = f"{host.key}/@{host.attr} ({host.node.name or host.node.family}) {lexical[:70]!r}"
    if SHORT_DECIMALS and len(DIGITS.findall(lexical)) > 24 and host.node.family == "decimal":
        counts["skipped_long_decimal"] += 1
        log.info("skip (libxml2 %s refuses long decimals): %s", etree.LIBXML_VERSION, where)
        return []
    want = lxml_valid(host, lexical)
    codec = host.node.codec()
    got = codec.is_valid_lexical(lexical)
    counts["probes"] += 1
    problems = []
    if got != want:
        why = known_deviation(host, lexical, want, got)
        if why:
            counts["known_deviation: " + why.split(";")[0]] += 1
            log.info("known oracle deviation (%s): %s", why, where)
            return []
        problems.append(f"codec says {got}, lxml says {want}: {where}")
    usable, value = setter_python_value(host.node, lexical)
    if usable:
        counts["setter_probes"] += 1
        cls = G.CLASSES[host.key]
        inst = cls()
        try:
            host.ref.__set__(inst, value)
            accepted = True
        except SchemaValueError:
            accepted = False
        if accepted != want:
            problems.append(f"setter {'accepted' if accepted else 'refused'} {value!r}, lxml says {want}: {where}")
        if accepted and not codec.is_valid_lexical(inst._attrs[host.attr]):
            problems.append(f"setter stored {inst._attrs[host.attr]!r}, which the codec refuses: {where}")
        if accepted and not lxml_valid(host, inst._attrs[host.attr]):
            problems.append(f"setter stored {inst._attrs[host.attr]!r}, which lxml refuses: {where}")
    return problems


HOSTS = interesting_hosts()
_CACHE: dict[str, tuple[Any, Any] | str] = {}
_PREPARED = False


def prepared() -> list[Host]:
    global _PREPARED
    if not _PREPARED:
        for h in HOSTS:
            prepare(h, _CACHE)
        _PREPARED = True
    return HOSTS


# ---------------------------------------------------------------------------------------------------- tests
def test_every_interesting_attribute_has_a_host_document():
    """Coverage: the generic builder reaches the host of every attribute with facets or enumerations (counted)."""
    hosts = prepared()
    abstract = {t.base for t in S.complex.values() if t.base}
    ok = {(h.key, h.attr) for h in hosts if not h.why}
    # an extension base that is no element's type (gradientBaseType) is probed through each extension that inherits it
    via_extension = [h for h in hosts if h.why and h.key in abstract and h.key not in BUILDER.paths and any(
        (k, h.attr) in ok for k, t in S.complex.items() if t.base == h.key)]
    failed = [h for h in hosts if h.why and h not in via_extension]
    for h in via_extension:
        log.info("D6 %s/@%s is covered through the types that extend %s", h.key, h.attr, h.key)
    for h in failed:
        log.warning("D6 host not reachable generically: %s/@%s: %s", h.key, h.attr, h.why)
    uncovered = [h for h in failed if h.key not in HAND_TEMPLATES]
    log.info("D6 hosts: %d attributes, %d built generically, %d through an extension, %d unreachable, "
             "%d of those with hand templates", len(hosts), len(hosts) - len(failed) - len(via_extension),
             len(via_extension), len(failed), len(failed) - len(uncovered))
    assert not uncovered, "hosts neither built nor covered by HAND_TEMPLATES:\n" + "\n".join(
        f"  {h.key}/@{h.attr}: {h.why}" for h in uncovered[:40])
    assert len(hosts) >= 300, f"only {len(hosts)} attributes with facets or enumerations were found"


def test_every_type_with_facets_is_probed():
    """Every simple type with facets or enumerations (named or inline) is reached by at least one reachable host."""
    reached: set[str] = set()

    def visit(n: Node) -> None:
        if n.name:
            reached.add(n.name)
        for sub in [n.base, n.item, *n.members]:
            if sub is not None:
                visit(sub)

    for h in prepared():
        if not h.why:
            visit(h.node)
    named = {n for n, spec in TABLE.items() if resolve(n).interesting()}
    assert not (named - reached), f"named types never probed: {sorted(named - reached)}"


def test_sdk_agrees_with_lxml_on_every_probe():
    counts: dict[str, int] = collections.defaultdict(int)
    problems: list[str] = []
    index = 0
    for h in prepared():
        if h.why:
            continue
        for lexical in probes(h.node):
            index += 1
            if index % STRIDE:
                continue
            problems += judge(h, lexical, counts)
    log.info("D6 probes: %s (stride %d)", counts, STRIDE)
    assert counts["probes"] > 0
    assert not problems, f"{len(problems)} disagreements (first 40):\n" + "\n".join(problems[:40])


def test_known_libxml2_deviations_still_hold():
    """Pins the three libxml2 departures that `known_deviation` tolerates; if one stops holding, remove its entry."""
    xsd = etree.XMLSchema(etree.fromstring(b'''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="a"><xs:complexType>
        <xs:attribute name="d" type="xs:double"/><xs:attribute name="u" type="xs:anyURI"/>
        <xs:attribute name="p"><xs:simpleType><xs:restriction base="xs:double">
          <xs:minExclusive value="0"/></xs:restriction></xs:simpleType></xs:attribute>
      </xs:complexType></xs:element></xs:schema>'''))

    def ok(**attrs: str) -> bool:
        return bool(xsd.validate(etree.Element("a", **attrs)))

    assert ok(d="1e") and not ok(d="1e+x")        # empty exponent accepted
    assert ok(p="NaN") and not ok(p="-1")          # NaN passes a range facet
    assert all(ok(u=u) for u in LAX_IP_LITERALS) and not ok(u="http://[::1/")   # malformed IP-literal accepted
    # and the SDK is on the XSD side of each
    from sr_core.scene.values import codec_for
    assert not codec_for("xs:double", {}).is_valid_lexical("1e")
    assert not codec_for("positiveDecimal", TABLE).is_valid_lexical("NaN")
    assert not any(codec_for("xs:anyURI", {}).is_valid_lexical(u) for u in LAX_IP_LITERALS)
