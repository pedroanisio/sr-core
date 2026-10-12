"""Runtime of the scene SDK: the ``Attr`` descriptor, the ``Element`` base class, the child nodes and ``Unknown``.

The generated module (``_generated.py``) builds one ``Element`` subclass per complex type, in the shape that
CONTRACT C5 describes. This module holds everything those classes share, and it imports nothing from the generated
module: the generated module hands over its simple-type table with :func:`set_simple_types`, and a class finds the
classes of its children in the ``CLASSES`` mapping of its own module.

Standard library only.
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Iterator, Optional, TypeVar, overload

from sr_core.scene.errors import SchemaValueError

__all__ = ["Attr", "Element", "Unknown", "Comment", "PI", "Text", "set_simple_types", "default_of",
           "new_id"]

T = TypeVar("T")

_SIMPLE_TYPES: dict[str, Any] = {}


def set_simple_types(table: dict[str, Any]) -> None:
    """Hand the generated ``SIMPLE_TYPES`` table to the runtime (called once, when the generated module loads)."""
    global _SIMPLE_TYPES
    _SIMPLE_TYPES = table


def _codec_for(spec: Any) -> Any:
    values = importlib.import_module("sr_core.scene.values")
    return values.codec_for(spec, _SIMPLE_TYPES)


# ------------------------------------------------------------------------------------------ child nodes

class Comment:
    """An XML comment, kept where it stood."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return f"Comment({self.text!r})"


class PI:
    """A processing instruction."""

    __slots__ = ("target", "data")

    def __init__(self, target: str, data: str = "") -> None:
        self.target = target
        self.data = data

    def __repr__(self) -> str:
        return f"PI({self.target!r}, {self.data!r})"


class Text:
    """Character data: whitespace between elements, or the simple content of an element."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return f"Text({self.text!r})"

    @property
    def is_space(self) -> bool:
        return not self.text.strip()


# ------------------------------------------------------------------------------------------ attributes

class Attr(Generic[T]):
    """A data descriptor for one XML attribute.

    ``xml_name`` is the name in the document (``from``), ``name`` the Python attribute (``from_``, set by
    ``__set_name__``). The stored form is the lexical string in ``obj._attrs``; reading parses it and returns ``None``
    when the attribute is unset, or the raw string when a document that was read holds an invalid lexical form.
    """

    def __init__(self, xml_name: str, spec: Any, *, use: str = "optional", default: Optional[str] = None,
                 fixed: Optional[str] = None, doc: str = "") -> None:
        self.xml_name = xml_name
        self.spec = spec
        self.use = use
        self.default = default
        self.fixed = fixed
        self.doc = doc
        self.name = xml_name
        self.__doc__ = doc or None
        self._cache: Optional[tuple[Any, Any, Any]] = None

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def codec(self) -> Any:
        """The codec of this attribute's type, resolved on first use (lazily, which avoids an import cycle)."""
        values = importlib.import_module("sr_core.scene.values")
        fn, table = values.codec_for, _SIMPLE_TYPES
        cached = self._cache
        if cached is not None and cached[0] is fn and cached[1] is table:
            return cached[2]
        codec = fn(self.spec, table)
        self._cache = (fn, table, codec)
        return codec

    @overload
    def __get__(self, obj: None, owner: Optional[type] = None) -> "Attr[T]": ...
    @overload
    def __get__(self, obj: "Element", owner: Optional[type] = None) -> Optional[T]: ...

    def __get__(self, obj: Optional["Element"], owner: Optional[type] = None) -> Any:
        if obj is None:
            return self
        lexical = obj._attrs.get(self.xml_name)
        if lexical is None:
            return None
        try:
            return self.codec().parse(lexical)
        except SchemaValueError:
            return lexical

    def __set__(self, obj: "Element", value: Any) -> None:
        if value is None:
            obj._attrs.pop(self.xml_name, None)
            return
        codec = self.codec()
        try:
            lexical = codec.validate(self._lower(value))
        except SchemaValueError as err:
            if err.path is None:
                err.path = obj.xml_path
            if err.attribute is None:
                err.attribute = self.xml_name
            if err.xsd_type is None:
                err.xsd_type = getattr(codec, "xsd_type", None)
            raise
        obj._attrs[self.xml_name] = lexical

    def __delete__(self, obj: "Element") -> None:
        obj._attrs.pop(self.xml_name, None)

    def _lower(self, value: Any) -> Any:
        """An element stands for its id (xs:IDREF); a sequence of elements for their ids (xs:IDREFS)."""
        if isinstance(value, Element):
            return self._id_of(value)
        if isinstance(value, (list, tuple)):
            return [self._id_of(v) if isinstance(v, Element) else v for v in value]
        return value

    def _id_of(self, element: "Element") -> str:
        ident = element._attrs.get("id")
        if ident is None:
            raise SchemaValueError(f"the referenced <{element.xml_name}> has no id", attribute=self.xml_name,
                                   path=element.xml_path)
        return ident


_ATTR_SPECS: dict[type, dict[str, Attr[Any]]] = {}


def _attr_specs(cls: type) -> dict[str, Attr[Any]]:
    """xml name -> Attr for a class, in declaration order (base classes first)."""
    found = _ATTR_SPECS.get(cls)
    if found is None:
        found = {}
        for klass in reversed(cls.__mro__):
            for value in vars(klass).values():
                if isinstance(value, Attr):
                    found[value.xml_name] = value
        _ATTR_SPECS[cls] = found
    return found


# ------------------------------------------------------------------------------------------ content model

@dataclass(frozen=True)
class _Slot:
    type_key: str
    max: int  # effective maxOccurs; -1 is unbounded
    rank: int  # position in sequence content; equal for names that share a choice


@dataclass(frozen=True)
class _Model:
    ordered: bool
    slots: dict[str, _Slot]


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return -1 if a == -1 or b == -1 else a * b


def _add_max(a: int, b: int) -> int:
    return -1 if a == -1 or b == -1 else a + b


def _build_model(content: Optional[tuple[Any, ...]]) -> _Model:
    if content is None:
        return _Model(False, {})
    slots: dict[str, _Slot] = {}
    counter = [0]

    def put(name: str, type_key: str, mx: int, rank: int) -> None:
        old = slots.get(name)
        if old is None:
            slots[name] = _Slot(type_key, mx, rank)
        else:
            slots[name] = _Slot(old.type_key, _add_max(old.max, mx), old.rank)

    def walk(p: tuple[Any, ...], mult: int, fixed: Optional[int], ordered: bool) -> None:
        kind = p[0]
        if kind == "element":
            _, _mn, mx, name, type_key = p
            if fixed is not None:
                rank = fixed
            elif ordered:
                rank = counter[0]
                counter[0] += 1
            else:
                rank = 0
            put(name, type_key, _mul(mult, mx), rank)
            return
        if kind not in ("sequence", "choice"):
            raise SchemaValueError(f"unknown particle kind {kind!r} in a content model")
        m = _mul(mult, p[2])
        if kind == "sequence":
            for child in p[3]:
                walk(child, m, fixed, ordered)
        else:
            shared = fixed
            if shared is None and ordered:
                shared = counter[0]
                counter[0] += 1
            for child in p[3]:
                walk(child, m, shared, False)

    walk(content, 1, None, content[0] == "sequence")
    return _Model(content[0] == "sequence", slots)


_MODELS: dict[type, _Model] = {}


def _model_of(cls: type) -> _Model:
    model = _MODELS.get(cls)
    if model is None:
        model = _build_model(getattr(cls, "_content", None))
        _MODELS[cls] = model
    return model


def _class_for(cls: type, type_key: str) -> type["Element"]:
    table = getattr(sys.modules.get(cls.__module__), "CLASSES", None)
    if table is None or type_key not in table:
        raise SchemaValueError(f"no class for type {type_key!r}: module {cls.__module__!r} has no CLASSES entry")
    return table[type_key]  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------------------ Element

class Element:
    """Base of every element class. Subclasses MUST declare ``__slots__`` (``()`` when they add none)."""

    __slots__ = ("_attrs", "_owner", "_nodes", "_name", "_pre", "_post", "source_line", "source_column")

    _xsd_type: ClassVar[str] = ""
    _element_names: ClassVar[tuple[str, ...]] = ()
    _content: ClassVar[Optional[tuple[Any, ...]]] = None
    _simple_content: ClassVar[Any] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "__slots__" not in cls.__dict__:
            raise TypeError(f"{cls.__name__} must declare __slots__ (use __slots__ = ()) so that undeclared "
                            f"attributes raise AttributeError")

    def __init__(self, **attrs: Any) -> None:
        if not self._element_names:
            raise TypeError(f"{type(self).__name__} has no element name")
        self._reset(self._element_names[0])
        self._set_all(attrs)

    # -- construction helpers

    def _reset(self, name: str) -> None:
        self._attrs: dict[str, str] = {}
        self._owner: Optional[Element] = None
        self._nodes: list[Any] = []
        self._name = name
        self._pre: list[Any] = []
        self._post: list[Any] = []
        self.source_line: Optional[int] = None
        self.source_column: Optional[int] = None

    @classmethod
    def _blank(cls, name: str) -> "Element":
        obj = cls.__new__(cls)
        obj._reset(name)
        return obj

    def _set_all(self, attrs: dict[str, Any]) -> None:
        for key, value in attrs.items():
            desc = getattr(type(self), key, None)
            if not isinstance(desc, Attr):
                raise AttributeError(f"<{self.xml_name}> has no attribute {key!r}")
            setattr(self, key, value)

    # -- read-only structure

    @property
    def xml_name(self) -> str:
        return self._name

    @property
    def owner(self) -> Optional["Element"]:
        return self._owner

    @property
    def nodes(self) -> list[Any]:
        return self._nodes

    def elements(self) -> list["Element"]:
        return [n for n in self._nodes if isinstance(n, Element)]

    def attributes(self) -> dict[str, str]:
        return dict(self._attrs)

    @property
    def xml_path(self) -> str:
        parts: list[str] = []
        el: Optional[Element] = self
        while el is not None:
            seg = el._name
            owner = el._owner
            if owner is not None:
                same = [s for s in owner._nodes if isinstance(s, Element) and s._name == seg]
                pos = next((i for i, s in enumerate(same) if s is el), len(same))
                total = len(same) + (0 if pos < len(same) else 1)
                if total > 1:
                    seg = f"{seg}[{pos + 1}]"
            parts.append(seg)
            el = owner
        return "/" + "/".join(reversed(parts))

    # -- simple content

    @property
    def content(self) -> str:
        return "".join(n.text for n in self._nodes if isinstance(n, Text))

    @content.setter
    def content(self, value: Optional[str]) -> None:
        text = "" if value is None else self._validate_content(value)
        at = next((i for i, n in enumerate(self._nodes) if isinstance(n, Text)), len(self._nodes))
        self._nodes[:] = [n for n in self._nodes if not isinstance(n, Text)]
        if text:
            self._nodes.insert(min(at, len(self._nodes)), Text(text))

    def _validate_content(self, value: str) -> str:
        spec = self._simple_content
        if spec is None:
            raise SchemaValueError("this element has no simple content", path=self.xml_path)
        codec = _codec_for(spec)
        try:
            return str(codec.validate(value))
        except SchemaValueError as err:
            if err.path is None:
                err.path = self.xml_path
            if err.xsd_type is None:
                err.xsd_type = getattr(codec, "xsd_type", None)
            raise

    # -- children

    def _slot_for(self, name: str, child: Optional["Element"]) -> Optional[_Slot]:
        """The content-model slot for a child of this name; refuses what the model does not allow."""
        slot = _model_of(type(self)).slots.get(name)
        if slot is None:
            allowed = ", ".join(sorted(_model_of(type(self)).slots)) or "none"
            raise SchemaValueError(f"<{name}> is not allowed in <{self.xml_name}> (allowed: {allowed})",
                                   path=self.xml_path)
        if child is not None and child._xsd_type != slot.type_key:
            raise SchemaValueError(f"<{name}> here must be of type {slot.type_key}, not {child._xsd_type or '?'}",
                                   path=self.xml_path)
        if slot.max != -1:
            count = sum(1 for n in self._nodes if isinstance(n, Element) and n._name == name)
            if count >= slot.max:
                raise SchemaValueError(f"<{name}> may occur at most {slot.max} time(s) in <{self.xml_name}>",
                                       path=self.xml_path)
        return slot

    def add(self, child: "Element") -> "Element":
        """Append an existing element, in content-model position for sequence content."""
        if not isinstance(child, Element):
            raise SchemaValueError(f"only an Element can be added, not {type(child).__name__}", path=self.xml_path)
        if child._owner is not None:
            raise SchemaValueError(f"<{child.xml_name}> already belongs to <{child._owner.xml_name}>",
                                   path=self.xml_path)
        slot = self._slot_for(child._name, child)
        self._insert(child, slot)
        return child

    def _add(self, name: str, attrs: dict[str, Any]) -> "Element":
        """The common body of the generated ``add_<name>`` factories."""
        slot = self._slot_for(name, None)
        assert slot is not None
        child = _class_for(type(self), slot.type_key)._blank(name)
        child._owner = self  # the path in an error message names the future parent
        try:
            child._set_all(attrs)
        finally:
            child._owner = None
        self._insert(child, slot)
        return child

    def _insert(self, child: "Element", slot: Optional[_Slot]) -> None:
        nodes = self._nodes
        index: int
        copy_after = False
        if slot is None:
            index = len(nodes)
        else:
            slots = _model_of(type(self)).slots
            current = -1
            last_le: Optional[int] = None
            first_gt: Optional[int] = None
            for i, node in enumerate(nodes):
                if not isinstance(node, Element):
                    continue
                known = slots.get(node._name)
                if known is not None:
                    current = known.rank
                if current <= slot.rank:
                    last_le = i
                elif first_gt is None:
                    first_gt = i
            if last_le is not None:
                index, copy_after = last_le + 1, True
            elif first_gt is not None:
                index = first_gt
            else:
                index = len(nodes)
            space = self._space_before(index - 1 if copy_after else index)
            if space is not None and (copy_after or first_gt is not None):
                if copy_after:
                    nodes[index:index] = [Text(space), child]
                else:
                    nodes[index:index] = [child, Text(space)]
                child._owner = self
                return
        nodes.insert(index, child)
        child._owner = self

    def _space_before(self, element_index: int) -> Optional[str]:
        """The whitespace text that stands right before the node at this index, if any."""
        if 0 < element_index < len(self._nodes):
            prev = self._nodes[element_index - 1]
            if isinstance(prev, Text) and prev.is_space:
                return prev.text
        return None

    def remove(self, child: "Element") -> None:
        """Detach a child; the whitespace that led up to it goes with it."""
        nodes = self._nodes
        index = next((i for i, n in enumerate(nodes) if n is child), None)
        if index is None:
            raise SchemaValueError(f"<{getattr(child, 'xml_name', child)}> is not a child of <{self.xml_name}>",
                                   path=self.xml_path)
        del nodes[index]
        child._owner = None
        prev = nodes[index - 1] if index > 0 else None
        nxt = nodes[index] if index < len(nodes) else None
        if isinstance(prev, Text) and prev.is_space and (nxt is None or (isinstance(nxt, Text) and nxt.is_space)):
            del nodes[index - 1]

    def find(self, name: str) -> Optional["Element"]:
        return next((n for n in self._nodes if isinstance(n, Element) and n._name == name), None)

    def find_all(self, name: str) -> list["Element"]:
        return [n for n in self._nodes if isinstance(n, Element) and n._name == name]

    def iter(self, name: Optional[str] = None) -> Iterator["Element"]:
        """Depth-first, document order, self included."""
        stack: list[Element] = [self]
        while stack:
            el = stack.pop()
            if name is None or el._name == name:
                yield el
            stack.extend(reversed(el.elements()))

    def copy(self) -> "Element":
        """A deep copy, detached: lexical forms, comments, text and unknown content are kept."""
        new = type(self)._blank(self._name)
        new._attrs = dict(self._attrs)
        for node in self._nodes:
            if isinstance(node, Element):
                child = node.copy()
                child._owner = new
                new._nodes.append(child)
            else:
                new._nodes.append(_copy_node(node))
        new._pre = [_copy_node(n) for n in self._pre]
        new._post = [_copy_node(n) for n in self._post]
        return new

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={v!r}" for k, v in self._attrs.items())
        return f"{type(self).__name__}({attrs})"


def _copy_node(node: Any) -> Any:
    if isinstance(node, Comment):
        return Comment(node.text)
    if isinstance(node, PI):
        return PI(node.target, node.data)
    return Text(node.text)


class Unknown(Element):
    """An element the schema does not declare at its place: name, attributes and children are kept and written back."""

    __slots__ = ()
    _xsd_type = "#unknown"

    def __init__(self, name: str, attrs: Optional[dict[str, str]] = None) -> None:
        self._reset(name)
        if attrs:
            self._attrs.update(attrs)

    def _slot_for(self, name: str, child: Optional[Element]) -> Optional[_Slot]:
        return None

    def _add(self, name: str, attrs: dict[str, Any]) -> Element:
        child = Unknown(name, {k: str(v) for k, v in attrs.items()})
        self._insert(child, None)
        return child

    def _validate_content(self, value: str) -> str:
        return str(value)

    def __repr__(self) -> str:
        attrs = "".join(f", {k}={v!r}" for k, v in self._attrs.items())
        return f"Unknown({self._name!r}{attrs})"


# ------------------------------------------------------------------------------------------ helpers

def default_of(element: Element, name: str) -> Any:
    """The schema default of an attribute (by Python or XML name), parsed; ``None`` when it has none."""
    desc = getattr(type(element), name, None)
    if not isinstance(desc, Attr):
        desc = _attr_specs(type(element)).get(name)
    if desc is None:
        raise AttributeError(f"<{element.xml_name}> has no attribute {name!r}")
    if desc.default is None:
        return None
    try:
        return desc.codec().parse(desc.default)
    except SchemaValueError:
        return desc.default


def new_id(scene: Element, prefix: str) -> str:
    """``prefix``, then ``prefix-2``, ``prefix-3`` ...: the first one no element of the document holds."""
    taken = {el._attrs["id"] for el in scene.iter() if "id" in el._attrs}
    if prefix not in taken:
        return prefix
    n = 2
    while f"{prefix}-{n}" in taken:
        n += 1
    return f"{prefix}-{n}"
