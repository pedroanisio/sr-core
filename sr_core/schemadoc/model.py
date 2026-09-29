"""Read a scene-render XSD and its Schematron into a model the HTML writer walks.

Only the XSD features the scene-render schema uses are modelled: one global element, named and anonymous
complex types (sequence, choice, group references, simple and complex content extension), named and inline
simple types (restriction with facets, list, union), attribute groups, and ISO Schematron patterns, rules and
asserts. Anything else raises SchemaError rather than being silently dropped.
"""
from __future__ import annotations

import hashlib
import re
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

XS = "{http://www.w3.org/2001/XMLSchema}"
SCH = "{http://purl.oclc.org/dsdl/schematron}"
ROOT_TYPE = "#root"          # key of the global element's anonymous type


class SchemaError(ValueError):
    pass


def local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def doc_of(e: ET.Element | None) -> str:
    """The xs:annotation/xs:documentation text of `e`, dedented, or ''."""
    if e is None:
        return ""
    parts = []
    for a in e.findall(XS + "annotation"):
        for d in a.findall(XS + "documentation"):
            parts.append(textwrap.dedent("".join(d.itertext())).strip("\n"))
    return "\n\n".join(p.strip() for p in parts if p.strip())


@dataclass
class SimpleType:
    """A named or inline simple type."""
    name: str | None
    kind: str                      # restriction | list | union
    base: str | None = None        # restriction base, or list itemType
    members: list[str] = field(default_factory=list)          # union memberTypes
    enums: list[tuple[str, str]] = field(default_factory=list)  # (value, documentation)
    facets: list[tuple[str, str]] = field(default_factory=list)  # (facet, value), enumeration excluded
    inline: list["SimpleType"] = field(default_factory=list)   # anonymous member or item types
    doc: str = ""


@dataclass
class Attribute:
    name: str
    type: str | None               # named type, or None when inline
    inline: SimpleType | None
    use: str                       # required | optional | prohibited
    default: str | None
    fixed: str | None
    doc: str
    origin: str | None = None      # attributeGroup it came from; None when declared on the type
    inherited: str | None = None   # base type it came from through extension


@dataclass
class Particle:
    """One node of a content model: an element, a sequence/choice, or a group reference."""
    kind: str                      # element | sequence | choice | group | all
    min: str = "1"
    max: str = "1"
    name: str | None = None        # element name, or group name for kind == group
    type: str | None = None        # element's type (named complex/simple type, or ROOT_TYPE-style key)
    doc: str = ""
    children: list["Particle"] = field(default_factory=list)


@dataclass
class ComplexType:
    key: str                       # type name, or ROOT_TYPE
    label: str                     # what pages call it
    doc: str
    content: Particle | None       # None: empty or simple content
    simple_base: str | None        # simpleContent extension base
    base: str | None               # complexContent extension base
    attributes: list[Attribute]
    mixed: bool = False


@dataclass
class Group:
    name: str
    doc: str
    content: Particle


@dataclass
class AttributeGroup:
    name: str
    doc: str
    attributes: list[Attribute]


@dataclass
class Assert:
    id: str
    test: str
    message: str                   # <sch:value-of select="x"/> rendered as {x}
    kind: str = "assert"           # assert | report


@dataclass
class Rule:
    pattern: str
    context: str
    asserts: list[Assert]


@dataclass
class Usage:
    """Element `element` of type `type` appears in the content of `parent` (a type key)."""
    element: str
    type: str | None
    parent: str
    min: str
    max: str


@dataclass
class Schema:
    version: str
    doc: str
    root: str                                  # the global element's name
    complex: dict[str, ComplexType]
    simple: dict[str, SimpleType]
    groups: dict[str, Group]
    attr_groups: dict[str, AttributeGroup]
    rules: list[Rule]
    sch_title: str
    xsd_sha256: str
    sch_sha256: str | None
    xsd_name: str
    sch_name: str | None
    usages: list[Usage] = field(default_factory=list)

    # ------------------------------------------------------------ derived views
    def children(self, key: str) -> list[Particle]:
        """Every element particle reachable from type `key`'s content, through groups and its base."""
        out: list[Particle] = []
        seen: set[str] = set()

        def walk(p: Particle | None):
            if p is None:
                return
            if p.kind == "element":
                out.append(p)
            elif p.kind == "group":
                if p.name not in seen:
                    seen.add(p.name)
                    walk(self.groups[p.name].content)
            else:
                for c in p.children:
                    walk(c)

        t = self.complex[key]
        chain = []
        while t is not None:
            chain.append(t)
            t = self.complex.get(t.base) if t.base else None
        for t in reversed(chain):
            walk(t.content)
        return out

    def all_attributes(self, key: str) -> list[Attribute]:
        """Attributes of type `key`, its extension bases' first (marked inherited)."""
        t = self.complex[key]
        if t.base and t.base in self.complex:
            inherited = [Attribute(**{**a.__dict__, "inherited": a.inherited or t.base})
                         for a in self.all_attributes(t.base)]
        else:
            inherited = []
        return inherited + t.attributes

    def types_of_element(self, name: str, parent: str | None = None) -> list[str]:
        keys = []
        for u in self.usages:
            if u.element == name and u.type in self.complex and (parent is None or u.parent in parent_keys(self, parent)):
                if u.type not in keys:
                    keys.append(u.type)
        return keys


def parent_keys(s: Schema, element: str) -> set[str]:
    return {u.type for u in s.usages if u.element == element and u.type}


# ---------------------------------------------------------------- XSD parsing
def _occurs(e: ET.Element) -> tuple[str, str]:
    return e.get("minOccurs", "1"), e.get("maxOccurs", "1")


def _simple(e: ET.Element, name: str | None) -> SimpleType:
    kids = [c for c in e if c.tag != XS + "annotation"]
    if len(kids) != 1:
        raise SchemaError(f"simpleType {name or '(inline)'}: expected one of restriction/list/union")
    k = kids[0]
    kind = local(k.tag)
    st = SimpleType(name=name, kind=kind, doc=doc_of(e))
    if kind == "restriction":
        st.base = k.get("base")
        for f in k:
            if f.tag == XS + "annotation":
                continue
            if f.tag == XS + "simpleType":
                st.inline.append(_simple(f, None))
            elif f.tag == XS + "enumeration":
                st.enums.append((f.get("value"), doc_of(f)))
            else:
                st.facets.append((local(f.tag), f.get("value")))
    elif kind == "list":
        st.base = k.get("itemType")
        st.inline += [_simple(c, None) for c in k.findall(XS + "simpleType")]
    elif kind == "union":
        st.members = (k.get("memberTypes") or "").split()
        st.inline += [_simple(c, None) for c in k.findall(XS + "simpleType")]
    else:
        raise SchemaError(f"simpleType {name}: unsupported <{kind}>")
    return st


def _attribute(e: ET.Element, origin: str | None) -> Attribute:
    if e.get("ref"):
        raise SchemaError(f"attribute ref={e.get('ref')!r} is not supported")
    st = e.find(XS + "simpleType")
    return Attribute(name=e.get("name"), type=e.get("type"), inline=_simple(st, None) if st is not None else None,
                     use=e.get("use", "optional"), default=e.get("default"), fixed=e.get("fixed"),
                     doc=doc_of(e), origin=origin)


def _attributes(parent: ET.Element, attr_groups: dict[str, ET.Element], origin: str | None = None,
                _stack: tuple[str, ...] = ()) -> list[Attribute]:
    out = []
    for c in parent:
        if c.tag == XS + "attribute":
            out.append(_attribute(c, origin))
        elif c.tag == XS + "attributeGroup":
            ref = c.get("ref")
            if ref in _stack:
                raise SchemaError(f"attributeGroup cycle through {ref}")
            if ref not in attr_groups:
                raise SchemaError(f"unknown attributeGroup {ref}")
            out += _attributes(attr_groups[ref], attr_groups, origin or ref, _stack + (ref,))
        elif c.tag == XS + "anyAttribute":
            out.append(Attribute(name="*", type=None, inline=None, use="optional", default=None, fixed=None,
                                 doc=f"any attribute (namespace {c.get('namespace', '##any')})", origin=origin))
    return out


def _particle(e: ET.Element, anon: dict[str, ET.Element], owner: str) -> Particle:
    kind = local(e.tag)
    lo, hi = _occurs(e)
    if kind == "element":
        if e.get("ref"):
            raise SchemaError(f"element ref={e.get('ref')!r} is not supported")
        typ = e.get("type")
        inline = e.find(XS + "complexType")
        if typ is None and inline is not None:
            typ = f"{owner}/{e.get('name')}"
            anon[typ] = inline
        elif typ is None and e.find(XS + "simpleType") is not None:
            typ = None
        return Particle("element", lo, hi, name=e.get("name"), type=typ, doc=doc_of(e))
    if kind == "group":
        return Particle("group", lo, hi, name=e.get("ref"))
    if kind in ("sequence", "choice", "all"):
        return Particle(kind, lo, hi, children=[_particle(c, anon, owner) for c in e
                                                 if c.tag in (XS + "element", XS + "group", XS + "sequence",
                                                              XS + "choice", XS + "any")])
    if kind == "any":
        return Particle("element", lo, hi, name="*", doc=f"any element (namespace {e.get('namespace', '##any')})")
    raise SchemaError(f"unsupported particle <{kind}>")


def _complex(e: ET.Element, key: str, label: str, attr_groups: dict[str, ET.Element],
             anon: dict[str, ET.Element]) -> ComplexType:
    content = None
    simple_base = base = None
    attrs_from = e
    for c in e:
        t = c.tag
        if t in (XS + "sequence", XS + "choice", XS + "all", XS + "group"):
            content = _particle(c, anon, key)
        elif t == XS + "simpleContent":
            ext = c.find(XS + "extension")
            if ext is None:
                raise SchemaError(f"{label}: simpleContent without extension")
            simple_base, attrs_from = ext.get("base"), ext
        elif t == XS + "complexContent":
            ext = c.find(XS + "extension")
            if ext is None:
                raise SchemaError(f"{label}: complexContent without extension")
            base, attrs_from = ext.get("base"), ext
            for cc in ext:
                if cc.tag in (XS + "sequence", XS + "choice", XS + "all", XS + "group"):
                    content = _particle(cc, anon, key)
    return ComplexType(key=key, label=label, doc=doc_of(e), content=content, simple_base=simple_base, base=base,
                       attributes=_attributes(attrs_from, attr_groups), mixed=e.get("mixed") == "true")


def _usages(s: Schema) -> list[Usage]:
    out = []
    for key in s.complex:
        for p in s.children(key):
            if p.name != "*":
                out.append(Usage(p.name, p.type, key, p.min, p.max))
    return out


# ------------------------------------------------------------- Schematron
def _message(a: ET.Element) -> str:
    out = [a.text or ""]
    for c in a:
        if c.tag == SCH + "value-of":
            out.append("{" + c.get("select", "") + "}")
        elif c.tag == SCH + "name":
            out.append("{name()}")
        else:
            out.append("".join(c.itertext()))
        out.append(c.tail or "")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def read_schematron(data: bytes) -> tuple[str, list[Rule]]:
    root = ET.fromstring(data)
    if root.tag != SCH + "schema":
        raise SchemaError("not an ISO Schematron schema")
    title = "".join(root.findtext(SCH + "title") or "").strip()
    rules = []
    for c in root:
        if c.tag != SCH + "pattern":
            continue
        for r in c.findall(SCH + "rule"):
            asserts = [Assert(id=a.get("id", ""), test=a.get("test", ""), message=_message(a), kind=local(a.tag))
                       for a in r if a.tag in (SCH + "assert", SCH + "report")]
            rules.append(Rule(pattern=c.get("id", ""), context=r.get("context", ""), asserts=asserts))
    return title, rules


# ------------------------------------------------------------------ entry
def read(xsd: bytes, sch: bytes | None = None, xsd_name: str = "schema.xsd", sch_name: str | None = None) -> Schema:
    root = ET.fromstring(xsd)
    if root.tag != XS + "schema":
        raise SchemaError("not an XML Schema")
    attr_groups_el = {c.get("name"): c for c in root.findall(XS + "attributeGroup")}
    globals_ = root.findall(XS + "element")
    if len(globals_) != 1:
        raise SchemaError(f"expected one global element, found {len(globals_)}")
    g = globals_[0]
    anon: dict[str, ET.Element] = {}
    complex_: dict[str, ComplexType] = {}
    ct = g.find(XS + "complexType")
    if ct is None:
        raise SchemaError("the global element must have an inline complexType")
    complex_[ROOT_TYPE] = _complex(ct, ROOT_TYPE, f"<{g.get('name')}>", attr_groups_el, anon)
    complex_[ROOT_TYPE].doc = doc_of(g) or complex_[ROOT_TYPE].doc
    for c in root.findall(XS + "complexType"):
        complex_[c.get("name")] = _complex(c, c.get("name"), c.get("name"), attr_groups_el, anon)
    groups = {}
    for c in root.findall(XS + "group"):
        body = [x for x in c if x.tag != XS + "annotation"]
        groups[c.get("name")] = Group(c.get("name"), doc_of(c), _particle(body[0], anon, "group:" + c.get("name")))
    while anon:                      # anonymous complex types nested in elements
        key, el = sorted(anon.items())[0]
        del anon[key]
        complex_[key] = _complex(el, key, key.split("/")[-1] + " (anonymous)", attr_groups_el, anon)
    simple = {c.get("name"): _simple(c, c.get("name")) for c in root.findall(XS + "simpleType")}
    attr_groups = {n: AttributeGroup(n, doc_of(e), _attributes(e, attr_groups_el)) for n, e in attr_groups_el.items()}
    title, rules = read_schematron(sch) if sch else ("", [])
    s = Schema(version=root.get("version", ""), doc=doc_of(root), root=g.get("name"), complex=complex_,
               simple=simple, groups=groups, attr_groups=attr_groups, rules=rules, sch_title=title,
               xsd_sha256=hashlib.sha256(xsd).hexdigest(),
               sch_sha256=hashlib.sha256(sch).hexdigest() if sch else None,
               xsd_name=xsd_name, sch_name=sch_name)
    for p in s.groups.values():
        _check_refs(s, p.content)
    for t in s.complex.values():
        _check_refs(s, t.content)
    s.usages = _usages(s)
    return s


def _check_refs(s: Schema, p: Particle | None):
    if p is None:
        return
    if p.kind == "group" and p.name not in s.groups:
        raise SchemaError(f"unknown group {p.name}")
    for c in p.children:
        _check_refs(s, c)


# ------------------------------------------------------- rule → element map
_STEP = re.compile(r"[A-Za-z_][\w.-]*")
_AXIS = re.compile(r"^[a-z-]+::")


def rule_targets(context: str) -> list[tuple[str | None, str]]:
    """(parent, element) pairs a Schematron rule context selects, from the last step of each alternative.

    `/scene[@version='1.0']` -> [(None, 'scene')]; `assets/text` -> [('assets', 'text')];
    `constraint[@type!='pin']` -> [(None, 'constraint')]. Wildcards and functions yield nothing.
    """
    out = []
    for alt in _split_top(context, "|"):
        steps = [re.sub(r"\[.*\]$", "", _AXIS.sub("", st.strip())) for st in _split_top(alt.strip(), "/") if st.strip()]
        if not steps or not _STEP.fullmatch(steps[-1]):
            continue
        parent = steps[-2] if len(steps) > 1 and _STEP.fullmatch(steps[-2]) else None
        out.append((parent, steps[-1]))
    return out


def _split_top(s: str, sep: str) -> list[str]:
    """Split on `sep` outside brackets, parentheses and quotes."""
    parts, depth, quote, cur = [], 0, None, []
    for ch in s:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    return parts


def rule_types(s: Schema, context: str) -> list[str]:
    """Complex-type keys a rule context applies to, in schema order.

    Named steps resolve through the element usages (qualified by the parent step when there is one). A
    wildcard step `*[...]` resolves to the elements named by `self::x` tests in its predicate, or else to every
    type that declares one of the attributes its predicate tests (`*[@fill or @stroke]`).
    """
    keys: list[str] = []

    def add(ks):
        for k in ks:
            if k not in keys:
                keys.append(k)

    for alt in _split_top(context, "|"):
        steps = [st.strip() for st in _split_top(alt.strip(), "/") if st.strip()]
        if not steps:
            continue
        last = _AXIS.sub("", steps[-1])
        name = re.sub(r"\[.*\]$", "", last)
        pred = last[len(name):]
        if name == "*":
            positive = re.sub(r"not\([^()]*\)", "", pred)
            selfs = re.findall(r"self::([A-Za-z_][\w.-]*)", positive)
            if selfs:
                for n in selfs:
                    add(s.types_of_element(n))
            else:
                attrs = set(re.findall(r"@([A-Za-z_][\w.-]*)", pred))
                add(k for k in s.complex if attrs & {a.name for a in s.all_attributes(k)})
            continue
        if not _STEP.fullmatch(name):
            continue
        if name == s.root and len(steps) == 1:
            add([ROOT_TYPE])
            continue
        parent = re.sub(r"\[.*\]$", "", _AXIS.sub("", steps[-2])) if len(steps) > 1 else None
        found = s.types_of_element(name, parent) if parent and parent != s.root else []
        if parent == s.root:
            found = [u.type for u in s.usages if u.element == name and u.parent == ROOT_TYPE and u.type in s.complex]
        add(found or s.types_of_element(name))
    return keys
