"""Reading and writing scene documents (CONTRACT C7, SREP 0 section 4).

``read`` parses with expat, so that comments and processing instructions outside the root element are kept (the
standard ``ElementTree`` parser drops them), and builds the tree of ``_runtime`` elements. Attribute values stay in
the lexical form they had. ``to_bytes`` and ``write`` serialise it again, with ``layout="preserve"`` (the stored
whitespace, attribute order and child order) or ``layout="pretty"`` (2-space indentation, attributes in the schema's
declaration order, sequence children in content-model order).

Reading never judges the content against the schema: ``check`` does that. It raises only on XML that is not
well-formed, as ``xml.etree.ElementTree.ParseError``. That includes a namespace prefix that no ``xmlns:prefix``
declares (the document is not namespace-well-formed).

The schema's elements are in no namespace, so an element in a namespace (through ``xmlns="..."`` or a prefix) is read
as ``Unknown``, and namespace declarations stay among the attributes, so that the round trip keeps them. A root that
is not ``<scene>`` is read as ``Unknown`` too; ``check`` reports it (``xsd:element``).

Standard library only.
"""
from __future__ import annotations

import importlib
import os
import xml.etree.ElementTree as ET
import xml.parsers.expat
from pathlib import Path
from typing import Any, BinaryIO, Literal, Mapping, Optional, Union

from sr_core.scene._runtime import (PI, Comment, Element, Text, Unknown, _attr_specs, _check_chars, _check_comment,
                                    _check_name, _check_pi, _model_of)
from sr_core.scene.errors import SchemaValueError

__all__ = ["read", "to_bytes", "write", "reorder_count", "has_doctype"]

Layout = Literal["preserve", "pretty"]
ClassTable = Mapping[tuple[Optional[str], str], type]
Source = Union[str, "os.PathLike[str]", bytes]

_DECL = '<?xml version="1.0" encoding="UTF-8"?>'
_INDENT = "  "
XML_NS = "http://www.w3.org/XML/1998/namespace"


# ------------------------------------------------------------------------------------------ read

def _default_classes() -> ClassTable:
    module = importlib.import_module("sr_core.scene._generated")
    return module.ELEMENT_CLASSES  # type: ignore[no-any-return]


def read(source: Source, *, classes: Optional[ClassTable] = None) -> Element:
    """Read a scene document from a path (``str`` or path-like) or from ``bytes``.

    ``classes`` maps ``(parent type key or None for the root, element name)`` to an element class; it defaults to
    the generated ``ELEMENT_CLASSES``. A name the table does not list at its place becomes an ``Unknown`` element.
    Raises ``xml.etree.ElementTree.ParseError`` when the XML is not well-formed.
    """
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        with open(source, "rb") as handle:
            raw = handle.read()
    table = classes if classes is not None else _default_classes()

    stack: list[Element] = []
    pre: list[Any] = []
    post: list[Any] = []
    buf: list[str] = []
    state: dict[str, Any] = {"root": None}
    parser = xml.parsers.expat.ParserCreate()
    parser.ordered_attributes = True

    def flush() -> None:
        if buf:
            if stack:
                stack[-1]._nodes.append(Text("".join(buf)))
            buf.clear()

    def outside(node: Any) -> None:
        (post if state["root"] is not None else pre).append(node)

    scopes: list[dict[str, str]] = [{"xml": XML_NS, "": ""}]

    def unbound(prefix: str, name: str) -> ET.ParseError:
        error = ET.ParseError(f"unbound prefix {prefix!r} in {name!r}: line {parser.CurrentLineNumber}, "
                              f"column {parser.CurrentColumnNumber}")
        error.position = (parser.CurrentLineNumber, parser.CurrentColumnNumber)
        return error

    def start(name: str, attrs: list[str]) -> None:
        flush()
        scope = scopes[-1]
        declared = {(k[6:] if k != "xmlns" else ""): v for k, v in zip(attrs[0::2], attrs[1::2])
                    if k == "xmlns" or k.startswith("xmlns:")}
        if declared:
            scope = {**scope, **declared}
        scopes.append(scope)
        prefix = name.partition(":")[0] if ":" in name else ""
        if prefix not in scope:
            raise unbound(prefix, name)
        for key in attrs[0::2]:
            if ":" in key and not key.startswith("xmlns:") and key.partition(":")[0] not in scope:
                raise unbound(key.partition(":")[0], key)
        parent = stack[-1] if stack else None
        cls: Optional[type] = None
        if scope[prefix]:
            cls = None  # the schema's elements are in no namespace
        elif parent is None:
            cls = table.get((None, name))
        elif not isinstance(parent, Unknown):
            cls = table.get((parent._xsd_type, name))
        element = cls._blank(name) if cls is not None else Unknown._blank(name)  # type: ignore[attr-defined]
        element._attrs = dict(zip(attrs[0::2], attrs[1::2]))
        element.source_line = parser.CurrentLineNumber
        element.source_column = parser.CurrentColumnNumber + 1
        if parent is None:
            state["root"] = element
        else:
            element._owner = parent
            parent._nodes.append(element)
        stack.append(element)

    def end(name: str) -> None:
        flush()
        stack.pop()
        scopes.pop()

    def comment(text: str) -> None:
        flush()
        (stack[-1]._nodes.append(Comment(text)) if stack else outside(Comment(text)))

    def pi(target: str, data: str) -> None:
        flush()
        (stack[-1]._nodes.append(PI(target, data)) if stack else outside(PI(target, data)))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = buf.append
    parser.CommentHandler = comment
    parser.ProcessingInstructionHandler = pi
    try:
        parser.Parse(raw, True)
    except xml.parsers.expat.ExpatError as err:
        error = ET.ParseError(str(err))
        error.code = err.code
        error.position = (err.lineno, err.offset)
        raise error from None
    root: Optional[Element] = state["root"]
    if root is None:
        raise ET.ParseError("no element found")
    root._pre, root._post = pre, post
    return root


# ------------------------------------------------------------------------------------------ write

def _esc_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")


def _esc_attr(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
            .replace("\t", "&#9;").replace("\n", "&#10;").replace("\r", "&#13;"))


class _Writer:
    def __init__(self, root: Element, pretty: bool) -> None:
        self.root = root
        self.pretty = pretty
        self.out: list[str] = []
        self.version: Optional[str] = None
        if root._attrs.get("version") == "auto" and root._api_auto:
            self.version = _auto_version(root)

    def document(self) -> bytes:
        self.out.append(_DECL + "\n")
        for node in self.root._pre:
            self.out.append(self.leaf(node) + "\n")
        self.element(self.root, 0)
        self.out.append("\n")
        for node in self.root._post:
            self.out.append(self.leaf(node) + "\n")
        return "".join(self.out).encode("utf-8")

    # -- pieces

    @staticmethod
    def leaf(node: Any) -> str:
        if isinstance(node, Comment):
            _check_comment(node.text)
            return f"<!--{node.text}-->"
        if isinstance(node, PI):
            _check_pi(node.target, node.data)
            return f"<?{node.target} {node.data}?>" if node.data else f"<?{node.target}?>"
        _check_chars(node.text, "text")
        return _esc_text(node.text)

    def tag(self, el: Element) -> str:
        items = list(el._attrs.items())
        if self.pretty and items:
            order = {name: i for i, name in enumerate(_attr_specs(type(el)))}
            items.sort(key=lambda kv: order.get(kv[0], len(order)))  # stable: undeclared ones keep their order
        if isinstance(el, Unknown):
            _check_name(el._name, "element name", el.xml_path)
            for key, value in items:
                _check_name(key, "attribute name", el.xml_path)
                _check_chars(value, f"attribute {key}", el.xml_path)
        parts = [el._name]
        for key, value in items:
            if el is self.root and key == "version" and self.version is not None:
                value = self.version
            parts.append(f'{key}="{_esc_attr(value)}"')
        return " ".join(parts)

    # -- elements (iterative: the document may be nested deeper than the interpreter's recursion limit)

    def element(self, root: Element, depth: int) -> None:
        stack: list[Any] = [(root, depth, False)]
        out = self.out
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                out.append(item)
                continue
            el, level, forced = item
            if self.pretty and not forced and not self.inline(el):
                self.block(el, level, stack)
            else:
                self.verbatim(el, stack)

    @staticmethod
    def inline(el: Element) -> bool:
        if el._simple_content is not None:
            return True
        return any(isinstance(n, Text) and not n.is_space for n in el._nodes)

    def verbatim(self, el: Element, stack: list[Any]) -> None:
        if not el._nodes:
            self.out.append(f"<{self.tag(el)}/>")
            return
        self.out.append(f"<{self.tag(el)}>")
        items: list[Any] = []
        for node in el._nodes:
            items.append((node, 0, True) if isinstance(node, Element) else self.leaf(node))
        items.append(f"</{el._name}>")
        stack.extend(reversed(items))

    def block(self, el: Element, depth: int, stack: list[Any]) -> None:
        groups = _groups(el)
        if not groups:
            self.out.append(f"<{self.tag(el)}/>")
            return
        pad = _INDENT * (depth + 1)
        self.out.append(f"<{self.tag(el)}>\n")
        items: list[Any] = []
        for group in groups:
            for node in group:
                items.append(pad)
                items.append((node, depth + 1, False) if isinstance(node, Element) else self.leaf(node))
                items.append("\n")
        items.append(f"{_INDENT * depth}</{el._name}>")
        stack.extend(reversed(items))


def _groups(el: Element) -> list[list[Any]]:
    """Children for the pretty layout: whitespace dropped, each comment or PI bound to the element that follows it,
    the groups put in content-model order (an element the model does not know keeps its predecessor's place), and
    the comments and PIs after the last element kept at the end."""
    groups: list[list[Any]] = []
    pending: list[Any] = []
    for node in el._nodes:
        if isinstance(node, Text):
            if not node.is_space:
                raise SchemaValueError("text among the children cannot be indented", path=el.xml_path)
            continue
        pending.append(node)
        if isinstance(node, Element):
            groups.append(pending)
            pending = []
    model = _model_of(type(el))
    if model.ordered:
        keyed: list[tuple[int, list[Any]]] = []
        current = -1
        for group in groups:
            slot = model.slots.get(group[-1]._name)
            if slot is not None:
                current = slot.rank
            keyed.append((current, group))
        keyed.sort(key=lambda kv: kv[0])
        groups = [g for _, g in keyed]
    if pending:
        groups.append(pending)
    return groups


def reorder_count(scene: Element) -> int:
    """How many elements ``layout="pretty"`` would move to put sequence content into content-model order."""
    moved = 0
    for el in scene.iter():
        if not _model_of(type(el)).ordered or _Writer.inline(el):
            continue
        after = [n for group in _groups(el) for n in group if isinstance(n, Element)]
        moved += sum(1 for a, b in zip(el.elements(), after) if a is not b)
    return moved


def has_doctype(source: Source) -> bool:
    """Whether the document declares a DOCTYPE, which ``read`` does not keep (its entities are expanded)."""
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    found: list[bool] = []
    parser = xml.parsers.expat.ParserCreate()
    parser.StartDoctypeDeclHandler = lambda *args: found.append(True)
    try:
        parser.Parse(raw, True)
    except xml.parsers.expat.ExpatError:
        pass
    return bool(found)


def _auto_version(root: Element) -> str:
    try:
        checks = importlib.import_module("sr_core.scene.checks")
    except ImportError as err:
        raise SchemaValueError('version="auto" needs sr_core.scene.checks.min_version, which cannot be imported',
                               path=root.xml_path, attribute="version") from err
    return str(checks.min_version(root))


def to_bytes(scene: Element, *, layout: Layout = "preserve") -> bytes:
    """Serialise a document as UTF-8 with an XML declaration. ``version="auto"`` is written as ``min_version()``."""
    if layout not in ("preserve", "pretty"):
        raise ValueError(f"layout must be 'preserve' or 'pretty', not {layout!r}")
    return _Writer(scene, layout == "pretty").document()


def write(scene: Element, target: Union[str, "os.PathLike[str]", BinaryIO], *, layout: Layout = "preserve") -> None:
    """Write a document to a path or to a binary file object."""
    data = to_bytes(scene, layout=layout)
    if hasattr(target, "write"):
        target.write(data)  # type: ignore[union-attr]
    else:
        with open(target, "wb") as handle:  # type: ignore[arg-type]
            handle.write(data)
