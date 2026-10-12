"""Public introspection of the scene model: what an element, its children and its attributes are (SREP 91, section 3.6).

:func:`describe` takes an element class, an element instance, an XML element name or a class name, and returns a frozen
:class:`Description`; :func:`describe_all` returns the whole schema as one JSON-ready dict; :func:`element_names` lists
every XML element name. Both dict forms carry ``"format": "sr-scene-describe/1"``. Everything is derived from the
generated tables (classes, ``SIMPLE_TYPES``, ``SIMPLE_DOCS``, ``GATES``); standard library only.

The JSON shape of ``sr-scene-describe/1``::

    {"format": "sr-scene-describe/1", "schema_release": "1.7.0",
     "xml_names": ["layer"], "class_name": "Layer", "xsd_type": "layerType", "doc": "...", "min_version": "1.0",
     "content_model": "choice",            # sequence | choice | all | simple | empty | mixed
     "simple_content": null,               # a type object for an element whose content is text
     "children": [{"name": "animate", "class_name": "Animate", "min_occurs": 0, "max_occurs": null,
                   "position": 0, "min_version": "1.0"}],
     "attributes": [{"xml_name": "opacity", "python_name": "opacity", "required": false, "use": "optional",
                     "default": "1", "fixed": null, "min_version": null, "value_min_versions": {},
                     "doc": "...", "type": {"name": "unitDecimal", "kind": "atomic", "base": "xs:double",
                                            "enum": [], "facets": {"minInclusive": "0"}, "patterns": [],
                                            "item": null, "members": [], "doc": ""}}]}

``max_occurs`` null is unbounded. ``position`` is the rank in a sequence: children with the same position are
alternatives of one choice. A type object's ``kind`` is ``atomic``, ``list`` or ``union``; ``base`` is the XSD builtin an
atomic type derives from; ``facets`` and ``enum`` are the effective ones after restriction. ``min_version`` is the lowest
``scene/@version`` that no version gate refuses for the construct; null on an attribute means no gate names it, and
``value_min_versions`` maps an enumeration value to its own minimum when a gate names the value.
"""
from __future__ import annotations

import functools
import inspect
import json
from dataclasses import dataclass
from typing import Any, Optional

from sr_core.scene import _generated as _gen
from sr_core.scene._runtime import Attr, Element, _attr_specs, _model_of
from sr_core.scene.errors import SchemaValueError, UnknownNameError

__all__ = ["FORMAT", "AmbiguousNameError", "AttributeDescription", "ChildDescription", "Description",
           "TypeDescription", "describe", "describe_all", "element_names"]

FORMAT = "sr-scene-describe/1"
_CLASSES: dict[str, Any] = _gen.CLASSES


class AmbiguousNameError(SchemaValueError):
    """An XML element name that several classes share (``point``): pass one of ``candidates`` (class names)."""

    def __init__(self, name: str, candidates: tuple[str, ...]) -> None:
        super().__init__(f"element name {name!r} is used by more than one class ({', '.join(candidates)}); "
                         f"describe the class instead")
        self.name = name
        self.candidates = candidates


# ------------------------------------------------------------------------------------------ records

@dataclass(frozen=True)
class TypeDescription:
    name: Optional[str]
    kind: str                                  # atomic | list | union
    base: Optional[str]
    enum: tuple[str, ...] = ()
    facets: tuple[tuple[str, str], ...] = ()
    patterns: tuple[str, ...] = ()
    item: Optional["TypeDescription"] = None
    members: tuple["TypeDescription", ...] = ()
    doc: str = ""

    def to_dict(self, shared: bool = False) -> dict[str, Any]:
        if shared and self.name is not None and self.name in _gen.SIMPLE_TYPES:
            return {"name": self.name}
        return {"name": self.name, "kind": self.kind, "base": self.base, "enum": list(self.enum),
                "facets": dict(self.facets), "patterns": list(self.patterns),
                "item": self.item.to_dict(shared) if self.item is not None else None,
                "members": [m.to_dict(shared) for m in self.members], "doc": self.doc}


@dataclass(frozen=True)
class AttributeDescription:
    xml_name: str
    python_name: str
    required: bool
    use: str
    default: Optional[str]
    fixed: Optional[str]
    type: TypeDescription
    min_version: Optional[str]
    value_min_versions: tuple[tuple[str, str], ...]
    doc: str

    def to_dict(self, shared: bool = False) -> dict[str, Any]:
        return {"xml_name": self.xml_name, "python_name": self.python_name, "required": self.required,
                "use": self.use, "default": self.default, "fixed": self.fixed, "min_version": self.min_version,
                "value_min_versions": dict(self.value_min_versions), "doc": self.doc,
                "type": self.type.to_dict(shared)}


@dataclass(frozen=True)
class ChildDescription:
    name: str
    class_name: str
    min_occurs: int
    max_occurs: Optional[int]
    position: int
    min_version: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "class_name": self.class_name, "min_occurs": self.min_occurs,
                "max_occurs": self.max_occurs, "position": self.position, "min_version": self.min_version}


@dataclass(frozen=True)
class Description:
    """What the schema says about one element class; see the module docstring for the JSON form."""

    format: str
    schema_release: str
    xml_names: tuple[str, ...]
    class_name: str
    xsd_type: str
    doc: str
    min_version: str
    content_model: str
    simple_content: Optional[TypeDescription]
    children: tuple[ChildDescription, ...]
    attributes: tuple[AttributeDescription, ...]

    def to_dict(self, shared: bool = False) -> dict[str, Any]:
        return {"format": self.format, "schema_release": self.schema_release, "xml_names": list(self.xml_names),
                "class_name": self.class_name, "xsd_type": self.xsd_type, "doc": self.doc,
                "min_version": self.min_version, "content_model": self.content_model,
                "simple_content": self.simple_content.to_dict(shared) if self.simple_content else None,
                "children": [c.to_dict() for c in self.children],
                "attributes": [a.to_dict(shared) for a in self.attributes]}

    def to_json(self, *, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, separators=(",", ":") if indent is None else None,
                          ensure_ascii=False)


# ------------------------------------------------------------------------------------------ types

_BUILTIN_LISTS = {"xs:NMTOKENS": "xs:NMTOKEN", "xs:IDREFS": "xs:IDREF"}


def _resolve(spec: Any, name: Optional[str] = None) -> TypeDescription:
    table = _gen.SIMPLE_TYPES
    if isinstance(spec, str):
        if spec.startswith("xs:"):
            if spec in _BUILTIN_LISTS:
                return TypeDescription(spec, "list", None, item=TypeDescription(_BUILTIN_LISTS[spec], "atomic",
                                                                                _BUILTIN_LISTS[spec]))
            return TypeDescription(spec, "atomic", spec)
        inner = _resolve(table[spec], spec)
        return TypeDescription(spec, inner.kind, inner.base, inner.enum, inner.facets, inner.patterns, inner.item,
                               inner.members, _gen.SIMPLE_DOCS.get(spec, ""))
    kind = spec["kind"]
    own = tuple(spec["facets"])
    if kind == "list":
        return TypeDescription(name, "list", None, (), _facets((), own), _patterns((), own),
                               item=_resolve(spec["item"]))
    if kind == "union":
        return TypeDescription(name, "union", None, (), _facets((), own), _patterns((), own),
                               members=tuple(_resolve(m) for m in spec["members"]))
    base = _resolve(spec["base"])
    return TypeDescription(name, base.kind, base.base, tuple(spec["enums"]) or base.enum,
                           _facets(base.facets, own), _patterns(base.patterns, own), base.item, base.members)


def _facets(inherited: tuple[tuple[str, str], ...], own: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    merged = dict(inherited)
    for key, value in own:
        if key != "pattern":
            merged[key] = value
    return tuple(merged.items())


def _patterns(inherited: tuple[str, ...], own: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    return tuple(inherited) + tuple(v for k, v in own if k == "pattern")


# ------------------------------------------------------------------------------------------ version gates

def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _lowest_clean(refused: set[str]) -> str:
    return next((v for v in _gen.VERSIONS if v not in refused), _gen.VERSIONS[-1])


def _pred_leaves(pred: Any) -> list[tuple[str, str, Optional[str]]]:
    """(``attr``, name, None) and (``value``, name, literal) leaves of a predicate joined only by ``or``."""
    op = pred[0]
    if op == "or":
        return _pred_leaves(pred[1]) + _pred_leaves(pred[2])
    if op in ("exists", "eq"):
        out = []
        for steps in pred[1][1]:
            if len(steps) == 1 and steps[0][0] == "attr":
                out.append(("attr" if op == "exists" else "value", steps[0][1], pred[2] if op == "eq" else None))
        return out
    return []


def _walk_gate_expr(expr: Any) -> list[list[tuple[str, str, list[Any]]]]:
    """The paths of a gate trigger that are joined by ``or`` at the top."""
    if expr[0] == "or":
        return _walk_gate_expr(expr[1]) + _walk_gate_expr(expr[2])
    if expr[0] == "exists":
        return [list(steps) for steps in expr[1][1]]
    return []


@functools.lru_cache(maxsize=None)
def _gate_index() -> tuple[dict[tuple[Optional[str], str], set[str]], dict[tuple[str, str], set[str]],
                           dict[tuple[str, str, str], set[str]]]:
    """Refused versions of elements (by parent element name, None for any parent), attributes and attribute values."""
    elements: dict[tuple[Optional[str], str], set[str]] = {}
    attributes: dict[tuple[str, str], set[str]] = {}
    values: dict[tuple[str, str, str], set[str]] = {}
    for gate in _gen.GATES:
        paths: list[tuple[list[Any], bool]] = []   # (steps, form A)
        if gate.form == "A":
            kind, body = gate._test
            if kind != "A-not":
                continue
            paths = [(p, True) for p in _walk_gate_expr(body)]
        elif gate._test is None:
            paths = [(list(p), False) for p in gate._ctx]
        for steps, form_a in paths:
            axis, name, preds = steps[-1]
            if name in (None, "*") or axis == "attr":
                continue
            if len(steps) >= 2:
                parent: Optional[str] = steps[-2][1]
            else:
                parent = "scene" if (form_a and axis == "child") else None
            if not preds:
                elements.setdefault((parent, name), set()).update(gate.versions)
            elif len(preds) == 1:
                for kind_, attr_name, literal in _pred_leaves(preds[0]):
                    if kind_ == "attr":
                        attributes.setdefault((name, attr_name), set()).update(gate.versions)
                    else:
                        values.setdefault((name, attr_name, str(literal)), set()).update(gate.versions)
    return elements, attributes, values


def _element_min(name: str, parent: Optional[str]) -> str:
    elements = _gate_index()[0]
    refused = elements.get((None, name), set()) | (elements.get((parent, name), set()) if parent else set())
    return _lowest_clean(refused)


def _parents_of(cls: Any) -> list[Optional[str]]:
    out: list[Optional[str]] = []
    for (pkey, _name), klass in _gen.ELEMENT_CLASSES.items():
        if klass is cls:
            if pkey is None:
                if None not in out:
                    out.append(None)
            else:
                for pname in _CLASSES[pkey]._element_names:
                    if pname not in out:
                        out.append(pname)
    return out


def _class_min(cls: Any) -> str:
    parents = _parents_of(cls) or [None]
    best = _gen.VERSIONS[-1]
    for name in cls._element_names or ("",):
        for parent in parents:
            v = _element_min(name, parent)
            if _vkey(v) < _vkey(best):
                best = v
    return best


# ------------------------------------------------------------------------------------------ content model

def _children(cls: Any) -> tuple[ChildDescription, ...]:
    content = cls._content
    if content is None:
        return ()
    slots = _model_of(cls).slots
    mins: dict[str, int] = {}

    def walk(p: Any, mult: int, loose: bool) -> None:
        if p[0] == "element":
            _, lo, _hi, name, _tk = p
            mins[name] = mins.get(name, 0) + (0 if loose else mult * lo)
            return
        m = mult * p[1]
        alternatives = p[0] == "choice" and len(p[3]) > 1
        for child in p[3]:
            walk(child, m, loose or alternatives)

    walk(content, 1, False)
    own = cls._element_names[0] if cls._element_names else ""
    out = []
    for name, slot in slots.items():
        klass = _CLASSES[slot.type_key]
        out.append(ChildDescription(name, klass.__name__, mins.get(name, 0), None if slot.max == -1 else slot.max,
                                    slot.rank, _element_min(name, own)))
    return tuple(out)


def _content_model(cls: Any) -> str:
    if cls._simple_content is not None:
        return "simple"
    return "empty" if cls._content is None else str(cls._content[0])


# ------------------------------------------------------------------------------------------ describe

def _attribute(cls: Any, attr: Attr[Any, Any]) -> AttributeDescription:
    names = cls._element_names
    _elements, attributes, values = _gate_index()
    gated = [_lowest_clean(attributes[(n, attr.xml_name)]) for n in names if (n, attr.xml_name) in attributes]
    # gated only when every element name this class covers is gated
    min_version = min(gated, key=_vkey) if names and len(gated) == len(names) else None
    by_value: dict[str, str] = {}
    for (n, a, literal), refused in values.items():
        if a == attr.xml_name and n in names:
            by_value[literal] = _lowest_clean(refused)
    return AttributeDescription(attr.xml_name, attr.name, attr.use == "required", attr.use, attr.default, attr.fixed,
                                _resolve(attr.spec), min_version, tuple(by_value.items()), attr.doc)


_CLASS_CACHE: dict[Any, Description] = {}


def _describe_class(cls: Any) -> Description:
    found = _CLASS_CACHE.get(cls)
    if found is None:
        found = _CLASS_CACHE[cls] = _build(cls)
    return found


def _class_doc(cls: Any) -> str:
    """The schema's documentation of the type; the generator's placeholder ``Complex type X.`` counts as none."""
    doc = inspect.cleandoc(cls.__doc__ or "")
    return "" if doc == f"Complex type {cls._xsd_type}." else doc


def _build(cls: Any) -> Description:
    simple = _resolve(cls._simple_content) if cls._simple_content is not None else None
    return Description(
        format=FORMAT, schema_release=_gen.SCHEMA_RELEASE, xml_names=tuple(cls._element_names),
        class_name=cls.__name__, xsd_type=cls._xsd_type, doc=_class_doc(cls),
        min_version=_class_min(cls), content_model=_content_model(cls), simple_content=simple,
        children=_children(cls), attributes=tuple(_attribute(cls, a) for a in _attr_specs(cls).values()))


def _by_name() -> dict[str, list[Any]]:
    found: dict[str, list[Any]] = {}
    for cls in _CLASSES.values():
        for name in cls._element_names:
            found.setdefault(name, []).append(cls)
    return found


def element_names() -> tuple[str, ...]:
    """Every XML element name of the schema, sorted."""
    return tuple(sorted(_by_name()))


def describe(target: Any) -> Description:
    """Describe an element class, an element instance, an XML element name (``"layer"``) or a class name (``"Layer"``).

    An unknown name raises :class:`UnknownNameError` with suggestions; a name that several classes share raises
    :class:`AmbiguousNameError` (describe the class instead).
    """
    if isinstance(target, type) and issubclass(target, Element):
        return _describe_class(target)
    if isinstance(target, Element):
        return _describe_class(type(target))
    if isinstance(target, str):
        classes = {cls.__name__: cls for cls in _CLASSES.values()}
        found = _by_name().get(target)
        if found is None:
            if target in classes:
                return _describe_class(classes[target])
            raise UnknownNameError(target, "the scene schema", list(_by_name()) + list(classes), kind="element")
        if len(found) > 1:
            raise AmbiguousNameError(target, tuple(c.__name__ for c in found))
        return _describe_class(found[0])
    raise UnknownNameError(repr(target), "the scene schema", element_names(), kind="element")


def _compact_type(t: dict[str, Any]) -> Any:
    """A named type or a builtin becomes its name; an inline type loses its empty members."""
    if t.get("name") is not None and (set(t) == {"name"} or t["name"].startswith("xs:")):
        return t["name"]
    return _strip(t)


def _strip(obj: Any) -> Any:
    if isinstance(obj, dict):
        kept = {k: _strip(v) for k, v in obj.items()}
        return {k: v for k, v in kept.items() if v is not None and v != "" and v != [] and v != {}}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _compact_element(d: dict[str, Any]) -> dict[str, Any]:
    first = _gen.VERSIONS[0]
    out = _strip({k: v for k, v in d.items() if k not in ("format", "schema_release", "attributes", "simple_content",
                                                          "children")})
    if out.get("min_version") == first:
        del out["min_version"]
    if d["simple_content"] is not None:
        out["simple_content"] = _compact_type(d["simple_content"])
    out["children"] = [{k: v for k, v in c.items() if not (k == "min_version" and v == first)}
                       for c in d["children"]]
    attributes = []
    for a in d["attributes"]:
        item = {"xml_name": a["xml_name"], "type": _compact_type(a["type"])}
        if a["python_name"] != a["xml_name"]:
            item["python_name"] = a["python_name"]
        if a["required"]:
            item["required"] = True
        for key in ("default", "fixed", "min_version", "value_min_versions", "doc"):
            if a[key] not in (None, "", {}):
                item[key] = a[key]
        attributes.append(item)
    out["attributes"] = attributes
    return {k: v for k, v in out.items() if v != [] or k in ("children", "attributes")}


def describe_all() -> dict[str, Any]:
    """The whole schema as one compact, JSON-ready dict, for a prompt or a tool.

    ``format``, ``schema_release``, ``versions``, ``types`` (every named simple type, in full) and ``elements`` (one
    entry per class, in schema order). In ``elements`` an attribute's ``type`` is a type name (``"unitDecimal"``, to be
    looked up in ``types``; or an XSD builtin such as ``"xs:double"``) or, for an inline type, a type object. Members
    that are empty are left out, and so are ``python_name`` when it equals ``xml_name``, ``required`` when false, ``use``
    (it is ``required`` or ``optional``) and ``min_version`` when it is the first version."""
    types = {name: _strip(_resolve(name).to_dict()) for name in _gen.SIMPLE_TYPES}
    return {"format": FORMAT, "schema_release": _gen.SCHEMA_RELEASE, "versions": list(_gen.VERSIONS), "types": types,
            "elements": [_compact_element(_describe_class(cls).to_dict(shared=True)) for cls in _CLASSES.values()]}
