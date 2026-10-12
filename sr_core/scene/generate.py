"""Generate ``sr_core/scene/_generated.py`` and ``sr_core/scene/schema/`` from the scene-render XSD and Schematron.

Command::

    python3 -m sr_core.scene.generate [--check] [--root DIR]

The generator reads ``DIR/schema/scene-render.xsd`` and ``DIR/schema/scene-render.sch`` (SREP 0, section 2) with
``sr_core.schemadoc.model.read`` and writes the generated model plus byte copies of the two inputs. ``render`` is a
pure function of the two byte strings: no timestamps, members in schema order. Anything the generator does not handle
raises ``SchemaError`` (drift control D3); nothing is dropped silently.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import keyword
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sr_core.schemadoc import model
from sr_core.scene.errors import SchemaError

GENERATOR_VERSION = "1"

XSD_NAME = "scene-render.xsd"
SCH_NAME = "scene-render.sch"
GENERATED_RELPATH = "sr_core/scene/_generated.py"
SCHEMA_DIR_RELPATH = "sr_core/scene/schema"

# XSD builtins the runtime codecs implement (CONTRACT C1); any other builtin is a loud failure.
BUILTINS = {
    "xs:string", "xs:double", "xs:positiveInteger", "xs:boolean", "xs:IDREF", "xs:ID", "xs:anyURI",
    "xs:nonNegativeInteger", "xs:IDREFS", "xs:unsignedLong", "xs:NMTOKEN", "xs:NCName", "xs:integer",
    "xs:decimal", "xs:int", "xs:dateTime", "xs:NMTOKENS",
}
FACETS = {"length", "minLength", "maxLength", "pattern", "minInclusive", "maxInclusive", "minExclusive",
          "maxExclusive"}
USES = {"required", "optional", "prohibited"}

# D3: the XML Schema vocabulary the generator implements, as {element: its attributes}. Any other element or attribute
# in the XML Schema namespace fails the generation: an identity constraint (xs:unique, xs:key, xs:keyref), nillable, a
# target namespace ... would otherwise be dropped, and the SDK would accept documents lxml refuses. The contents of
# xs:annotation, `id`, and attributes in other namespaces carry no validation rule and pass. Facets are judged by
# name later (FACETS), so that an unsupported one is reported as a facet.
_XS_NS = "{http://www.w3.org/2001/XMLSchema}"
_PARTICLE = {"minOccurs", "maxOccurs"}
VOCABULARY: dict[str, set[str]] = {
    "schema": {"version", "elementFormDefault"},
    "annotation": set(),
    "element": {"name", "type"} | _PARTICLE,
    "attribute": {"name", "type", "use", "default", "fixed"},
    "attributeGroup": {"name", "ref"},
    "group": {"name", "ref"} | _PARTICLE,
    "complexType": {"name", "mixed"},
    "complexContent": set(),
    "simpleContent": set(),
    "extension": {"base"},
    "restriction": {"base"},
    "sequence": _PARTICLE,
    "choice": _PARTICLE,
    "simpleType": {"name"},
    "list": {"itemType"},
    "union": {"memberTypes"},
    **{f: {"value"} for f in ("length", "minLength", "maxLength", "pattern", "enumeration", "whiteSpace",
                              "maxInclusive", "maxExclusive", "minInclusive", "minExclusive", "totalDigits",
                              "fractionDigits")},
}

# CONTRACT C3: runtime member names no schema attribute may use, plus the names the generated class body relies on.
RESERVED_ATTRIBUTE_NAMES = {
    "add", "remove", "nodes", "elements", "owner", "xml_name", "xml_path", "content", "find", "find_all", "iter",
    "copy", "attributes", "source_line", "source_column", "new_id", "min_version", "check", "to_bytes",
    "Attr", "Element", "SceneBase",
}
RESERVED_PREFIXES = ("add_", "_")
# Names bound at module level of the generated file; a class may not take one of them.
RESERVED_MODULE_NAMES = {
    "Element", "Attr", "SceneBase", "Gate", "set_simple_types", "SCHEMA_RELEASE", "XSD_SHA256", "SCH_SHA256",
    "GENERATOR_VERSION", "COUNTS", "SIMPLE_TYPES", "ELEMENT_CLASSES", "CLASSES", "VERSIONS", "GATES",
    "SIMPLE_DOCS",
    # sr_core.scene re-exports the generated classes beside these names (sr_core/scene/__init__.py)
    "PI", "Comment", "Text", "Unknown", "Finding", "EngineError", "EngineInfo", "IntegrityError", "SchemaError",
    "SchemaValueError", "UnknownNameError",
}

_BUILTIN_HINTS = {
    "xs:string": "str", "xs:anyURI": "str", "xs:ID": "str", "xs:NCName": "str", "xs:NMTOKEN": "str",
    "xs:IDREF": "_t.Union[str, Element]",
    "xs:IDREFS": "_t.Sequence[_t.Union[str, Element]]",
    "xs:NMTOKENS": "_t.Sequence[str]",
    "xs:positiveInteger": "_t.Union[int, str]", "xs:nonNegativeInteger": "_t.Union[int, str]",
    "xs:unsignedLong": "_t.Union[int, str]", "xs:integer": "_t.Union[int, str]", "xs:int": "_t.Union[int, str]",
    "xs:double": "_t.Union[float, int, str]",
    "xs:decimal": "_t.Union[_Decimal, float, int, str]",
    "xs:boolean": "_t.Union[bool, str]",
    "xs:dateTime": "_t.Union[_dt.datetime, str]",
}
# What reading an attribute gives (the codec's parsed value); the other builtins read as they are set.
_BUILTIN_GET_HINTS = {
    **_BUILTIN_HINTS,
    "xs:positiveInteger": "int", "xs:nonNegativeInteger": "int", "xs:unsignedLong": "int", "xs:integer": "int",
    "xs:int": "int",
    "xs:double": "float",
    "xs:boolean": "bool",
    "xs:IDREF": "str",
    "xs:IDREFS": "_t.List[str]",
    "xs:NMTOKENS": "_t.List[str]",
    "xs:decimal": "_Decimal",
    "xs:dateTime": "_dt.datetime",
}

LINE_WIDTH = 110


# ------------------------------------------------------------------------------- source formatting
@dataclass
class Call:
    """A call expression ``name(arg, ..., key=value)`` in the generated source."""

    name: str
    args: list[Any] = field(default_factory=list)
    kwargs: list[tuple[str, Any]] = field(default_factory=list)


@dataclass
class SetLit:
    """A set display ``{a, b}`` (never empty) in the generated source."""

    items: list[Any]


def quote(s: str) -> str:
    """A Python string literal for ``s``, double-quoted when that needs no extra escape."""
    r = repr(s)
    if r[0] == "'" and '"' not in s and "'" not in s:
        return '"' + r[1:-1] + '"'
    return r


def flat(v: Any) -> str:
    if v is None or isinstance(v, bool):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return quote(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(flat(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{flat(k)}: {flat(x)}" for k, x in v.items()) + "}"
    if isinstance(v, SetLit):
        return "{" + ", ".join(flat(x) for x in v.items) + "}"
    if isinstance(v, Call):
        parts = [flat(a) for a in v.args] + [f"{k}={flat(x)}" for k, x in v.kwargs]
        return f"{v.name}(" + ", ".join(parts) + ")"
    raise SchemaError(f"cannot format {type(v).__name__} into the generated source")


def fmt(v: Any, base: int, lead: int = 0) -> str:
    """``v`` as source: one line when it fits, else one element per line (black-style trailing commas).

    ``base`` is the indentation of the line the text starts on, ``lead`` the characters already on that line.
    """
    one = flat(v)
    if base + lead + len(one) <= LINE_WIDTH:
        return one
    pad = " " * (base + 4)
    end = " " * base
    if (isinstance(v, tuple) and len(v) == 4 and v[0] in ("choice", "sequence") and isinstance(v[3], tuple)
            and v[3]):
        # content-model node: keep ("kind", min, max, ( on one line and the children below it
        head = f"({flat(v[0])}, {v[1]}, {v[2]}, ("
        return head + "\n" + "".join(f"{pad}{fmt(x, base + 4)},\n" for x in v[3]) + end + "))"
    if isinstance(v, tuple) and v:
        return "(\n" + "".join(f"{pad}{fmt(x, base + 4)},\n" for x in v) + end + ")"
    if isinstance(v, dict) and v:
        body = "".join(f"{pad}{flat(k)}: {fmt(x, base + 4, len(flat(k)) + 2)},\n" for k, x in v.items())
        return "{\n" + body + end + "}"
    if isinstance(v, SetLit):
        return "{\n" + "".join(f"{pad}{fmt(x, base + 4)},\n" for x in v.items) + end + "}"
    if isinstance(v, Call):
        body = "".join(f"{pad}{fmt(a, base + 4)},\n" for a in v.args)
        body += "".join(f"{pad}{k}={fmt(x, base + 4, len(k) + 1)},\n" for k, x in v.kwargs)
        return f"{v.name}(\n{body}{end})"
    return one


def docstring(text: str, indent: str) -> str:
    """A docstring literal; falls back to a ``repr`` literal when triple quotes would need escapes."""
    lines = [ln.rstrip() for ln in text.strip().split("\n")]
    body = "\n".join(lines)
    safe = ("\\" not in body and '"""' not in body and not body.endswith('"')
            and all(c == "\n" or c.isprintable() for c in body))
    if not safe:
        return quote(body)
    if len(lines) == 1:
        return f'"""{body}"""'
    rest = "\n".join((indent + ln) if ln else "" for ln in lines[1:])
    return f'"""{lines[0]}\n{rest}\n{indent}"""'


# ------------------------------------------------------------------------------- schema checks
def class_name(key: str) -> str:
    """SREP 3.1: the type name without the suffix ``Type``, first letter upper case; the root is ``Scene``."""
    if key == model.ROOT_TYPE:
        return "Scene"
    if "/" in key or "#" in key:
        raise SchemaError(f"anonymous complex type {key!r} is not supported")
    name = key[:-4] if key.endswith("Type") and len(key) > 4 else key
    name = name[:1].upper() + name[1:]
    if not name.isidentifier() or keyword.iskeyword(name):
        raise SchemaError(f"complex type {key!r} gives the invalid class name {name!r}")
    return name


def python_name(xml_name: str, owner: str) -> str:
    if not xml_name.isidentifier():
        raise SchemaError(f"{owner}: attribute name {xml_name!r} is not a Python identifier")
    for pre in RESERVED_PREFIXES:
        if xml_name.startswith(pre):
            raise SchemaError(f"{owner}: attribute {xml_name!r} starts with reserved prefix {pre!r}")
    if xml_name in RESERVED_ATTRIBUTE_NAMES:
        raise SchemaError(f"{owner}: attribute {xml_name!r} collides with a reserved runtime name")
    return xml_name + "_" if keyword.iskeyword(xml_name) else xml_name


def attribute_doc(schema: model.Schema, a: model.Attribute) -> str:
    """The documentation of an attribute: its own, else the one of its simple type (named or inline), dedented."""
    text = a.doc
    if not text:
        st = schema.simple.get(a.type) if a.type is not None else a.inline
        text = st.doc if st is not None else ""
    return inspect.cleandoc(text) if text else ""


def first_paragraph(text: str) -> str:
    """The first paragraph of ``text`` on one line."""
    return " ".join(text.strip().split("\n\n", 1)[0].split())


def natural_key(version: str) -> tuple:
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in version.replace("-", ".").split("."))


class Generator:
    def __init__(self, schema: model.Schema, gates: tuple[Any, ...]) -> None:
        self.s = schema
        self.gates = gates
        self.names = {key: class_name(key) for key in schema.complex}
        self._check_class_names()
        self.alias_order: list[str] = []
        self.params: dict[str, list[tuple[str, str]]] = {}
        self.param_docs: dict[str, dict[str, str]] = {}
        self._alias_open: set[str] = set()
        self._check_simple_types()

    # ------------------------------------------------------------ validation
    def _check_class_names(self) -> None:
        seen: dict[str, str] = {}
        for key, name in self.names.items():
            if name in seen:
                raise SchemaError(f"class name collision: {seen[name]!r} and {key!r} both give {name!r}")
            if name in RESERVED_MODULE_NAMES or name.startswith("T_") or name.startswith("_"):
                raise SchemaError(f"complex type {key!r} gives the reserved class name {name!r}")
            seen[name] = key

    def _check_simple_types(self) -> None:
        for name, st in self.s.simple.items():
            if not name.isidentifier():
                raise SchemaError(f"simple type name {name!r} is not a Python identifier")
            self._validate_simple(st, f"simpleType {name}")

    def check_ref(self, ref: str, where: str) -> None:
        if ref.startswith("xs:"):
            if ref not in BUILTINS:
                raise SchemaError(f"{where}: unsupported XSD builtin {ref!r}")
        elif ref not in self.s.simple:
            raise SchemaError(f"{where}: unknown simple type {ref!r}")

    def _validate_simple(self, st: model.SimpleType, where: str) -> None:
        if st.kind not in ("restriction", "list", "union"):
            raise SchemaError(f"{where}: unsupported simple type kind {st.kind!r}")
        if st.kind == "restriction":
            if st.base is None and len(st.inline) != 1:
                raise SchemaError(f"{where}: restriction without a base")
            if st.base is not None:
                self.check_ref(st.base, where)
            for facet, value in st.facets:
                if facet not in FACETS:
                    raise SchemaError(f"{where}: unsupported facet {facet!r}")
                if facet == "pattern":
                    importlib.import_module("sr_core.scene.values").translate_pattern(value)
        elif st.kind == "list":
            if (st.base is None) == (len(st.inline) != 1):
                raise SchemaError(f"{where}: list needs exactly one item type")
            if st.base is not None:
                self.check_ref(st.base, where)
        else:
            if not st.members and not st.inline:
                raise SchemaError(f"{where}: union without members")
            for m in st.members:
                self.check_ref(m, where)
        for i, inner in enumerate(st.inline):
            self._validate_simple(inner, f"{where}/inline[{i}]")

    # ------------------------------------------------------------ simple type specs and hints
    def spec(self, st: model.SimpleType) -> dict[str, Any]:
        """The C5 spec dict of a simple type (named or inline)."""
        inner = [self.spec(x) for x in st.inline]
        if st.kind == "restriction":
            base: Any = st.base if st.base is not None else inner[0]
            return {"kind": "restriction", "base": base, "enums": tuple(v for v, _ in st.enums),
                    "facets": tuple((f, v) for f, v in st.facets), "members": (), "item": None}
        if st.kind == "list":
            return {"kind": "list", "base": None, "enums": (), "facets": tuple((f, v) for f, v in st.facets),
                    "members": (), "item": st.base if st.base is not None else inner[0]}
        return {"kind": "union", "base": None, "enums": (), "facets": tuple((f, v) for f, v in st.facets),
                "members": tuple(st.members) + tuple(inner), "item": None}

    def ref_hint(self, ref: str, get: bool = False) -> str:
        if ref.startswith("xs:"):
            return (_BUILTIN_GET_HINTS if get else _BUILTIN_HINTS)[ref]
        self.alias(ref)
        return f"{'G' if get else 'T'}_{ref}"

    def type_hint(self, st: model.SimpleType, get: bool = False) -> str:
        """The Python type of a simple type: what it accepts when set (``T_``), or what it reads as (``get``, ``G_``)."""
        inner = [self.type_hint(x, get) for x in st.inline]
        if st.kind == "restriction":
            if st.enums:
                return "_t.Literal[" + ", ".join(quote(v) for v, _ in st.enums) + "]"
            return self.ref_hint(st.base, get) if st.base is not None else inner[0]
        if st.kind == "list":
            item = self.ref_hint(st.base, get) if st.base is not None else inner[0]
            return ("_t.List[" if get else "_t.Sequence[") + item + "]"
        members: list[str] = []
        for h in [self.ref_hint(m, get) for m in st.members] + inner:
            if h not in members:
                members.append(h)
        return members[0] if len(members) == 1 else "_t.Union[" + ", ".join(members) + "]"

    def alias(self, name: str) -> None:
        if name in self.alias_order:
            return
        if name in self._alias_open:
            raise SchemaError(f"simple type {name!r} refers to itself")
        self._alias_open.add(name)
        self.type_hint(self.s.simple[name])          # registers dependencies first
        self.type_hint(self.s.simple[name], True)
        self._alias_open.discard(name)
        self.alias_order.append(name)

    # ------------------------------------------------------------ content models
    def particle(self, p: model.Particle, owner: str, stack: tuple[str, ...] = ()) -> tuple:
        lo, hi = occurs(p.min, p.max, owner)
        if p.kind == "element":
            if p.type is None or p.type not in self.s.complex:
                raise SchemaError(f"{owner}: element {p.name!r} has no complex type ({p.type!r})")
            return ("element", lo, hi, p.name, p.type)
        if p.kind in ("sequence", "choice"):
            return (p.kind, lo, hi, tuple(self.particle(c, owner, stack) for c in p.children))
        if p.kind == "group":
            if p.name is None:
                raise SchemaError(f"{owner}: a group reference without a name")
            if p.name in stack:
                raise SchemaError(f"{owner}: group cycle through {p.name!r}")
            inner = self.particle(self.s.groups[p.name].content, owner, stack + (p.name,))
            if (inner[1], inner[2]) == (1, 1):
                return (inner[0], lo, hi) + inner[3:]
            return ("sequence", lo, hi, (inner,))
        raise SchemaError(f"{owner}: unknown particle kind {p.kind!r}")

    def content(self, key: str, stack: tuple[str, ...] = ()) -> tuple | None:
        t = self.s.complex[key]
        parts = []
        if t.base:
            if t.base not in self.s.complex:
                raise SchemaError(f"{key}: unknown base type {t.base!r}")
            if t.base in stack:
                raise SchemaError(f"{key}: extension cycle through {t.base!r}")
            base = self.content(t.base, stack + (key,))
            if base is not None:
                parts.append(base)
        if t.content is not None:
            parts.append(self.particle(t.content, key))
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else ("sequence", 1, 1, tuple(parts))

    def element_types(self, key: str) -> dict[str, str]:
        """element name -> type key for the children of ``key``; fails when one name has two types."""
        out: dict[str, str] = {}
        for p in self.s.children(key):
            if p.type is None or p.type not in self.s.complex:
                raise SchemaError(f"{key}: element {p.name!r} has no complex type ({p.type!r})")
            if p.name is None:
                raise SchemaError(f"{key}: an element particle without a name")
            if out.setdefault(p.name, p.type) != p.type:
                raise SchemaError(f"{key}: element {p.name!r} has two types ({out[p.name]!r} and {p.type!r})")
        return out

    # ------------------------------------------------------------ attributes
    def attr_lines(self, key: str) -> list[str]:
        out = []
        params: list[tuple[str, str]] = []
        docs: dict[str, str] = self.param_docs.setdefault(key, {})
        seen: dict[str, str] = {}
        for a in self.s.all_attributes(key):
            py = python_name(a.name, key)
            if py in seen:
                raise SchemaError(f"{key}: attribute {a.name!r} declared twice")
            seen[py] = a.name
            if py == "self":
                raise SchemaError(f"{key}: attribute {a.name!r} cannot be a keyword parameter named 'self'")
            if a.use not in USES:
                raise SchemaError(f"{key}: attribute {a.name!r} has unsupported use {a.use!r}")
            if (a.type is None) == (a.inline is None):
                raise SchemaError(f"{key}: attribute {a.name!r} needs exactly one of type and inline type")
            if a.type is not None:
                self.check_ref(a.type, f"{key}/@{a.name}")
                spec: Any = a.type
                hint, got = self.ref_hint(a.type), self.ref_hint(a.type, True)
            else:
                assert a.inline is not None  # the check above: exactly one of type and inline type
                self._validate_simple(a.inline, f"{key}/@{a.name}")
                spec = self.spec(a.inline)
                hint, got = self.type_hint(a.inline), self.type_hint(a.inline, True)
            self._check_lexical(key, a, spec)
            if key == model.ROOT_TYPE and a.name == "version":
                # SceneBase accepts "auto" through the API, and a document that was read may carry it (SREP 4.5)
                hint, got = (f'_t.Union[{h}, _t.Literal["auto"]]' for h in (hint, got))
            head = f"{py}: Attr[{got}, {hint}] = "
            doc = attribute_doc(self.s, a)
            source = self.attr_source(head, a, spec, doc)
            if doc:  # an attribute docstring, which editors show on hover
                source += "\n    " + docstring(doc, "    ")
            out.append(source)
            params.append((py, hint))
            docs[py] = doc
        self.params[key] = params
        return out

    def signature(self, name: str, key: str, returns: str, indent: str,
                  element_names: tuple[str, ...] = (), doc: str = "") -> list[str]:
        """A keyword-only signature over the attributes of type ``key`` (all optional), for type checkers.

        ``element_names`` (the constructor of a class that covers several element names) adds ``xml_name``, the
        choice among them; a runtime-reserved name, so that no attribute can collide with it."""
        lines = [f"{indent}def {name}(", f"{indent}    self,"]
        if self.params[key] or len(element_names) > 1:
            lines.append(f"{indent}    *,")
        if len(element_names) > 1:
            lines.append(f"{indent}    xml_name: _t.Literal[{', '.join(quote(n) for n in element_names)}] | None = None,")
        lines += [f"{indent}    {py}: {hint} | None = None," for py, hint in self.params[key]]
        if doc:
            lines += [f"{indent}) -> {returns}:", f"{indent}    " + docstring(doc, indent + "    "),
                      f"{indent}    ..."]
        else:
            lines.append(f"{indent}) -> {returns}: ...")
        return lines

    def init_doc(self, key: str) -> str:
        """The docstring of a stub constructor: the type summary, then one line per documented attribute."""
        summary = first_paragraph(self.s.complex[key].doc)
        rows = [f"{py}: {first_paragraph(text)}" for py, text in self.param_docs.get(key, {}).items() if text]
        return "\n\n".join(p for p in (summary, "Args:\n" + "\n".join("    " + r for r in rows) if rows else "") if p)

    def add_doc(self, name: str, tkey: str) -> str:
        summary = first_paragraph(self.s.complex[tkey].doc)
        head = f"Add a <{name}> child; the keywords are the attributes of {self.names[tkey]}."
        return head + (f"\n\n{summary}" if summary else "")

    def _check_lexical(self, key: str, a: model.Attribute, spec: Any) -> None:
        """Every default and fixed value must be valid for the attribute's own type (SchemaError otherwise)."""
        if a.default is None and a.fixed is None:
            return
        if not hasattr(self, "_table"):
            self._table = {n: self.spec(st) for n, st in self.s.simple.items()}
        codec = importlib.import_module("sr_core.scene.values").codec_for(spec, self._table)
        for what, lex in (("default", a.default), ("fixed", a.fixed)):
            if lex is not None and not codec.is_valid_lexical(lex):
                raise SchemaError(f"{key}/@{a.name}: {what} value {lex!r} is not valid for its type")

    @staticmethod
    def attr_source(head: str, a: model.Attribute, spec: Any, doc_text: str) -> str:
        """One attribute declaration: a single line when it fits, else name/type, flags and doc on their own lines."""
        flags = f"use={quote(a.use)}, default={flat(a.default)}, fixed={flat(a.fixed)}"
        doc = f"doc={quote(doc_text)}"
        one = f"    {head}Attr({quote(a.name)}, {flat(spec)}, {flags}, {doc})"
        if len(one) <= LINE_WIDTH:
            return one
        lines = [f"    {head}Attr("]
        first = f"{quote(a.name)}, {flat(spec)}, {flags},"
        if 8 + len(first) + 1 + len(doc) + 1 <= LINE_WIDTH:
            lines.append(f"        {first} {doc},")
            lines.append("    )")
            return "\n".join(lines)
        if 8 + len(first) <= LINE_WIDTH:
            lines.append("        " + first)
        else:
            lines.append(f"        {quote(a.name)},")
            lines.append("        " + fmt(spec, 8) + ",")
            lines.append(f"        {flags},")
        lines.append(f"        {doc},")
        lines.append("    )")
        return "\n".join(lines)

    # ------------------------------------------------------------ counts and versions
    def versions(self) -> tuple[str, ...]:
        for a in self.s.complex[model.ROOT_TYPE].attributes:
            if a.name == "version":
                st = a.inline if a.inline is not None else self.s.simple.get(a.type or "")
                while st is not None and not st.enums and st.base in self.s.simple:
                    st = self.s.simple[st.base]
                if st is not None and st.enums:
                    return tuple(v for v, _ in st.enums)
        raise SchemaError("scene/@version has no enumeration; cannot build VERSIONS")

    def count_enums(self, st: model.SimpleType) -> int:
        return len(st.enums) + sum(self.count_enums(x) for x in st.inline)

    def counts(self) -> dict[str, int]:
        attrs = 0
        enums = sum(self.count_enums(st) for st in self.s.simple.values())
        for key in self.s.complex:
            for a in self.s.all_attributes(key):
                attrs += 1
                if a.inline is not None:
                    enums += self.count_enums(a.inline)
        return {"complex_types": len(self.s.complex), "simple_types": len(self.s.simple), "attributes": attrs,
                "enum_values": enums, "gate_asserts": len(self.gates)}

    # ------------------------------------------------------------ classes
    def class_source(self, key: str) -> str:
        t = self.s.complex[key]
        if t.mixed:
            raise SchemaError(f"{key}: mixed content is not supported")
        cname = self.names[key]
        types = self.element_types(key)
        element_names = tuple(self.parent_names.get(key, ()))
        simple: Any = None
        if t.simple_base is not None:
            self.check_ref(t.simple_base, key)
            simple = t.simple_base
        base = "SceneBase" if key == "#root" else "Element"
        lines = [f"class {cname}({base}):", "    " + docstring(t.doc or f"Complex type {key}.", "    "), "",
                 "    __slots__ = ()", f"    _xsd_type = {quote(key)}"]
        lines.append("    _element_names = " + fmt(element_names, 4, len("_element_names = ")))
        head = "_content = "
        lines.append("    " + head + fmt(self.content(key), 4, len(head)))
        lines.append("    _simple_content = " + fmt(simple, 4, len("_simple_content = ")))
        attrs = self.attr_lines(key)
        if attrs:
            lines += [""] + attrs
        for name in types:
            if not name.isidentifier():
                raise SchemaError(f"{key}: element name {name!r} is not a Python identifier")
        for tkey in types.values():
            if tkey not in self.params:
                self.attr_lines(tkey)
        # Type checkers see keyword-only signatures; at run time the same methods take **attrs, so that an attribute
        # the element does not declare raises AttributeError (SREP 3.3), not TypeError.
        lines += ["", "    if _t.TYPE_CHECKING:", ""]
        lines += self.signature("__init__", key, "None", "        ", element_names=element_names,
                                doc=self.init_doc(key))
        for name, tkey in types.items():
            lines += [""] + self.signature(f"add_{name}", tkey, self.names[tkey], "        ",
                                           doc=self.add_doc(name, tkey))
        if types:
            lines += ["", "    else:"]
            for name, tkey in types.items():
                lines += ["", f"        def add_{name}(self, **attrs: _t.Any) -> {self.names[tkey]}:",
                          f"            return self._add({quote(name)}, attrs)"]
        return "\n".join(lines)

    def compute_parent_names(self) -> None:
        self.parent_names: dict[str, list[str]] = {model.ROOT_TYPE: [self.s.root]}
        for key in self.s.complex:
            for name, tkey in self.element_types(key).items():
                names = self.parent_names.setdefault(tkey, [])
                if name not in names:
                    names.append(name)

    def gate_source(self, g: Any) -> str:
        ordered = sorted(g.versions, key=natural_key)
        versions = Call("frozenset", [SetLit(ordered)] if ordered else [])
        call = Call("Gate", [], [
            ("id", g.id), ("versions", versions),
            ("context", g.context), ("trigger", g.trigger), ("message", g.message), ("form", g.form)])
        return "    " + fmt(call, 4)

    def module(self) -> str:
        s = self.s
        self.compute_parent_names()
        counts = self.counts()
        versions = self.versions()
        simple_specs = {name: self.spec(st) for name, st in s.simple.items()}
        simple_docs = {name: inspect.cleandoc(st.doc) for name, st in s.simple.items() if st.doc}
        for name in s.simple:
            self.alias(name)
        class_blocks = [self.class_source(k) for k in s.complex]       # also fills alias_order for attributes

        header = "\n".join([
            "GENERATED by sr_core.scene.generate. Do not edit; run `python3 -m sr_core.scene.generate`.",
            "",
            f"schema release: {s.version}",
            f"xsd sha256: {s.xsd_sha256}",
            f"sch sha256: {s.sch_sha256}",
            f"generator version: {GENERATOR_VERSION}",
            " ".join(f"{k}={v}" for k, v in counts.items()),
        ])
        out = [f'"""{header}\n"""', "", "from __future__ import annotations", "",
               "import datetime as _dt", "import typing as _t", "from decimal import Decimal as _Decimal", "",
               "from sr_core.scene._runtime import Attr, Element, SceneBase, set_simple_types",
               "from sr_core.scene.gates import Gate", "",
               f"SCHEMA_RELEASE = {quote(s.version or '')}", f"XSD_SHA256 = {quote(s.xsd_sha256 or "")}",
               f"SCH_SHA256 = {quote(s.sch_sha256 or "")}", f"GENERATOR_VERSION = {quote(GENERATOR_VERSION)}",
               "COUNTS = " + fmt(counts, 0, len("COUNTS = ")), "",
               "# Simple types by name, in schema order (CONTRACT C5).",
               "SIMPLE_TYPES = " + fmt(simple_specs, 0, len("SIMPLE_TYPES = ")), "",
               "# Documentation of the simple types that have some (read by sr_core.scene.introspect).",
               "SIMPLE_DOCS = " + fmt(simple_docs, 0, len("SIMPLE_DOCS = ")), "",
               "# Python types of the simple types, for the attribute hints:",
               "# T_ is what an attribute accepts when set, G_ what it reads as."]
        for name in self.alias_order:
            out.append(f"T_{name} = " + self.type_hint(s.simple[name]))
            out.append(f"G_{name} = " + self.type_hint(s.simple[name], True))
        out.append("")
        for block in class_blocks:
            out += ["", block, ""]
        out += ["", "ELEMENT_CLASSES = {", f"    (None, {quote(s.root)}): {self.names[model.ROOT_TYPE]},"]
        for key in s.complex:
            for name, tkey in self.element_types(key).items():
                out.append(f"    ({quote(key)}, {quote(name)}): {self.names[tkey]},")
        out += ["}", "", "CLASSES = {"]
        out += [f"    {quote(k)}: {self.names[k]}," for k in s.complex]
        out += ["}", "", "VERSIONS = " + fmt(versions, 0, len("VERSIONS = ")), "", "GATES = ("]
        out += [self.gate_source(g) + "," for g in self.gates]
        out += [")", "", "set_simple_types(SIMPLE_TYPES)", ""]
        return "\n".join(out)


def occurs(lo: str, hi: str, owner: str) -> tuple[int, int]:
    try:
        return int(lo), (-1 if hi == "unbounded" else int(hi))
    except ValueError:
        raise SchemaError(f"{owner}: bad occurrence bounds {lo!r}..{hi!r}") from None


def sha256sums(xsd: bytes, sch: bytes) -> bytes:
    return (f"{hashlib.sha256(xsd).hexdigest()}  {XSD_NAME}\n"
            f"{hashlib.sha256(sch).hexdigest()}  {SCH_NAME}\n").encode()


def check_vocabulary(xsd_bytes: bytes) -> None:
    """D3: raise ``SchemaError`` for the first element or attribute of XML Schema outside ``VOCABULARY``."""
    try:
        root = ET.fromstring(xsd_bytes)
    except ET.ParseError as exc:
        raise SchemaError(f"the XSD is not well-formed: {exc}") from None
    stack: list[tuple[ET.Element, str]] = [(root, "")]
    while stack:
        el, where = stack.pop()
        if not el.tag.startswith(_XS_NS):
            raise SchemaError(f"{where}: element {el.tag!r} outside xs:annotation is not supported by the SDK "
                              f"generator (D3)")
        tag = el.tag[len(_XS_NS):]
        here = f"{where}/xs:{tag}" + (f"[@name={el.get('name')!r}]" if el.get("name") else "")
        allowed = VOCABULARY.get(tag)
        if allowed is None:
            raise SchemaError(f"{here}: <xs:{tag}> is not supported by the SDK generator (D3)")
        for name in el.attrib:
            if name not in allowed and name != "id" and not name.startswith("{"):
                raise SchemaError(f"{here}: attribute {name!r} of <xs:{tag}> is not supported by the SDK generator "
                                  f"(D3)")
        if tag != "annotation":
            stack.extend((c, here) for c in reversed(el))


def render(xsd_bytes: bytes, sch_bytes: bytes) -> dict[str, bytes]:
    """The generated files as ``{relative path: bytes}``; a pure function of the two inputs."""
    check_vocabulary(xsd_bytes)
    try:
        schema = model.read(xsd_bytes, sch_bytes, XSD_NAME, SCH_NAME)
    except model.SchemaError as exc:
        raise SchemaError(str(exc)) from exc
    gates = tuple(importlib.import_module("sr_core.scene.gates").compile_gates(schema))
    source = Generator(schema, gates).module()
    return {
        GENERATED_RELPATH: source.encode("utf-8"),
        f"{SCHEMA_DIR_RELPATH}/{XSD_NAME}": xsd_bytes,
        f"{SCHEMA_DIR_RELPATH}/{SCH_NAME}": sch_bytes,
        f"{SCHEMA_DIR_RELPATH}/SHA256SUMS": sha256sums(xsd_bytes, sch_bytes),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m sr_core.scene.generate",
                                 description="Generate the scene SDK model from schema/scene-render.{xsd,sch}.")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the output differs")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                    help="repository root holding schema/ and sr_core/ (default: this checkout)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        files = render((root / "schema" / XSD_NAME).read_bytes(), (root / "schema" / SCH_NAME).read_bytes())
    except (SchemaError, OSError) as exc:
        print(f"generate: {exc}", file=sys.stderr)
        return 2
    stale = [rel for rel, data in files.items()
             if not (root / rel).is_file() or (root / rel).read_bytes() != data]
    if args.check:
        for rel in stale:
            print(f"generate: {rel} differs from a fresh run", file=sys.stderr)
        return 1 if stale else 0
    for rel in stale:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[rel])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
