"""Checks on a scene document, levels 1 to 3 (SREP 0 sections 4.4, 4.5, 6 and 9; CONTRACT C9).

* Level 1 always runs and needs only the standard library: content models (with ``minOccurs``), attributes,
  value spaces, ids and references, the version, and the version gates.
* Level 2 (``schema=True``) validates the written bytes against the bundled XSD and Schematron with lxml.
* Level 3 (``engine=PATH``) hands the written bytes to an engine (``sr_core.scene.engine.level3``).

Notes on level 1:

* Unknown elements are reported once (``xsd:element``) and not descended into.
* Character data in element-only or empty content is reported as ``xsd:occurs``: the children and text do not match
  the content model.
* A reference to an id that a program emits (``P.E``, or a bare ``E``; SREP 87) cannot be resolved without running the
  program, so the SDK leaves it to the engine, as the schema does: when the document holds a build-mode program,
  unresolved ``IDREF`` tokens are not reported. Data programs emit rows and step programs pixels, never ids.
* ``version="auto"`` is valid; it is written as ``min_version()``.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.resources
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sr_core.scene import _generated as _gen
from sr_core.scene import _runtime
from sr_core.scene._runtime import Element, Text, Unknown, _attr_specs, new_id
from sr_core.scene.errors import IntegrityError, SchemaValueError
from sr_core.scene.findings import Finding
from sr_core.scene.gates import refused_versions

__all__ = ["check", "min_version", "new_id", "match_content", "Mismatch", "verify_integrity"]

_LEXICAL_LIMIT = 80
_XSI_ATTRIBUTES = {"xsi:type", "xsi:nil", "xsi:schemaLocation", "xsi:noNamespaceSchemaLocation"}
_SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}


# ------------------------------------------------------------------------------------------ integrity (D8)

_integrity_checked = False


def _bundled_bytes(name: str) -> bytes:
    return importlib.resources.files("sr_core.scene").joinpath("schema").joinpath(name).read_bytes()


def verify_integrity() -> None:
    """Compare the hashes in the generated header with the bundled schema files; raise ``IntegrityError`` on a
    difference. A success is remembered for the process, a failure is raised every time."""
    global _integrity_checked
    if _integrity_checked:
        return
    for label, name, expected in (("xsd", "scene-render.xsd", _gen.XSD_SHA256),
                                  ("sch", "scene-render.sch", _gen.SCH_SHA256)):
        actual = hashlib.sha256(_bundled_bytes(name)).hexdigest()
        if actual != expected:
            raise IntegrityError(f"{label}: the bundled schema/{name} has sha256 {actual}, but the generated module "
                                 f"was built from {expected}; reinstall sr-core or regenerate the SDK")
    _integrity_checked = True


# ------------------------------------------------------------------------------------------ content-model matcher

@dataclass(frozen=True)
class Mismatch:
    """Where a child sequence leaves its content model: ``index`` is the first child that cannot be there, or
    ``len(names)`` when the sequence ends too early; ``expected`` lists the names that could come at that point."""

    index: int
    expected: tuple[str, ...]


def _step(p: tuple[Any, ...], i: int, names: list[str], partial: bool, memo: dict[Any, frozenset[int]]) -> frozenset[int]:
    """Positions reached after exactly one occurrence of particle ``p`` starting at ``i``."""
    kind = p[0]
    if kind == "element":
        return frozenset((i + 1,)) if i < len(names) and names[i] == p[3] else frozenset()
    if kind == "sequence":
        pos: frozenset[int] = frozenset((i,))
        for child in p[3]:
            nxt: set[int] = set()
            for j in pos:
                nxt |= _ends(child, j, names, partial, memo)
            pos = frozenset(nxt)
            if not pos:
                break
        return pos
    if kind == "choice":
        out: set[int] = set()
        for child in p[3]:
            out |= _ends(child, i, names, partial, memo)
        return frozenset(out)
    raise SchemaValueError(f"unknown particle kind {kind!r} in a content model")


def _ends(p: tuple[Any, ...], i: int, names: list[str], partial: bool,
          memo: dict[Any, frozenset[int]]) -> frozenset[int]:
    """Every position at which ``p``, with its own minOccurs and maxOccurs, can end when it starts at ``i``.

    ``partial`` accepts a prefix: once the input is used up, whatever remains of the model counts as satisfiable."""
    key = (id(p), i)
    got = memo.get(key)
    if got is not None:
        return got
    if partial and i == len(names):
        result = frozenset((i,))
        if p[0] not in ("element", "sequence", "choice"):
            raise SchemaValueError(f"unknown particle kind {p[0]!r} in a content model")
    else:
        mn, mx = p[1], p[2]
        cur: frozenset[int] = frozenset((i,))
        res: set[int] = {i} if mn == 0 else set()
        k = 0
        while True:
            k += 1
            nxt_set: set[int] = set()
            for j in cur:
                nxt_set |= _step(p, j, names, partial, memo)
            nxt = frozenset(nxt_set)
            if not nxt:
                break
            fresh = nxt - res if k >= mn else frozenset()
            if k >= mn:
                res |= nxt
            if mx != -1 and k >= mx:
                break
            if k >= mn and not fresh:
                break
            cur = nxt
        result = frozenset(res)
    memo[key] = result
    return result


def _viable(model: tuple[Any, ...], names: list[str]) -> bool:
    return len(names) in _ends(model, 0, names, True, {})


def _model_names(p: tuple[Any, ...], out: dict[str, None]) -> None:
    if p[0] == "element":
        out.setdefault(p[3], None)
    else:
        for child in p[3]:
            _model_names(child, out)


def match_content(content: Optional[tuple[Any, ...]], names: list[str]) -> Optional[Mismatch]:
    """Match child element names against a content particle tree (CONTRACT C5). ``None`` means a match."""
    if content is None:
        return Mismatch(0, ()) if names else None
    if len(names) in _ends(content, 0, names, False, {}):
        return None
    lo, hi = 0, len(names)  # the longest viable prefix; viability only shrinks as a prefix grows
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _viable(content, names[:mid]):
            lo = mid
        else:
            hi = mid - 1
    prefix = names[:lo]
    known: dict[str, None] = {}
    _model_names(content, known)
    expected = tuple(x for x in known if _viable(content, prefix + [x]))
    return Mismatch(lo, expected)


# ------------------------------------------------------------------------------------------ helpers

def _root_of(element: Element) -> Element:
    while element.owner is not None:
        element = element.owner
    return element


def _norm(s: str) -> str:
    return " ".join(s.split())


def _shown(s: str) -> str:
    return repr(s if len(s) <= _LEXICAL_LIMIT else s[:_LEXICAL_LIMIT] + "...")


def _finding(el: Element, code: str, message: str) -> Finding:
    return Finding("error", code, message, el.xml_path, el.source_line, el.source_column)


_ID_KINDS = {"xs:ID": "ID", "xs:IDREF": "IDREF", "xs:IDREFS": "IDREFS"}
_kind_cache: dict[int, Optional[str]] = {}


def _spec_kind(spec: Any, depth: int = 0) -> Optional[str]:
    if depth > 16:
        return None
    if isinstance(spec, str):
        if spec in _ID_KINDS:
            return _ID_KINDS[spec]
        named = _runtime._SIMPLE_TYPES.get(spec)
        return _spec_kind(named, depth + 1) if named is not None else None
    if isinstance(spec, dict) and spec.get("kind") == "restriction" and spec.get("base") is not None:
        return _spec_kind(spec["base"], depth + 1)
    return None


def _id_kind(attr: Any) -> Optional[str]:
    key = id(attr)
    if key not in _kind_cache:
        _kind_cache[key] = _spec_kind(attr.spec)
    return _kind_cache[key]


def _same_value(codec: Any, a: str, b: str) -> bool:
    try:
        return bool(codec.parse(a) == codec.parse(b))
    except SchemaValueError:
        return _norm(a) == _norm(b)


# ------------------------------------------------------------------------------------------ min_version, gates

def _refused(root: Element) -> dict[str, list[tuple[Any, Element]]]:
    return refused_versions(_gen.GATES, root)


def _lowest_clean(refused: dict[str, list[tuple[Any, Element]]]) -> Optional[str]:
    for v in _gen.VERSIONS:
        if not refused.get(v):
            return str(v)
    return None


def min_version(scene: Element) -> str:
    """The lowest ``scene/@version`` value that no version gate refuses for this document."""
    found = _lowest_clean(_refused(_root_of(scene)))
    if found is None:
        raise SchemaValueError("no version in the scene/@version enumeration accepts this document",
                               path=_root_of(scene).xml_path, attribute="version")
    return found


# ------------------------------------------------------------------------------------------ level 1

def _level1(scene: Element) -> list[Finding]:
    root = _root_of(scene)
    out: list[Finding] = []
    if isinstance(root, Unknown):
        return [_finding(root, "xsd:element", f"the root element must be <scene>, not <{root.xml_name}>")]
    is_scene = root.xml_name == "scene"
    ids: dict[str, str] = {}
    refs: list[tuple[Element, str, str]] = []
    build_program = False

    stack: list[Element] = [root]
    while stack:
        el = stack.pop()
        if el._xsd_type == "programNodeType" and el._attrs.get("mode", "build").strip() != "step":
            build_program = True
        _attributes(el, el is root and is_scene, out, ids, refs)
        _children(el, out)
        stack.extend(reversed([c for c in el.elements() if not isinstance(c, Unknown)]))

    if build_program is False:
        for el, attr, token in refs:
            if token not in ids:
                out.append(_finding(el, "xsd:idref", f"{attr}={token!r} names no element: no element has that id"))
    if is_scene:
        _versions(root, out)
    return out


def _attributes(el: Element, is_root_scene: bool, out: list[Finding], ids: dict[str, str],
                refs: list[tuple[Element, str, str]]) -> None:
    specs = _attr_specs(type(el))
    for name, lexical in el._attrs.items():
        attr = specs.get(name)
        if attr is None:
            if name == "xmlns" or name.startswith("xmlns:") or name in _XSI_ATTRIBUTES:
                continue
            out.append(_finding(el, "xsd:attribute", f"<{el.xml_name}> has no attribute {name!r}"))
            continue
        if attr.use == "prohibited":
            out.append(_finding(el, "xsd:attribute", f"attribute {name!r} is prohibited on <{el.xml_name}>"))
            continue
        if is_root_scene and name == "version":
            continue  # judged by _versions
        codec = attr.codec()
        if not codec.is_valid_lexical(lexical):
            out.append(_finding(el, "xsd:value", f"attribute {name}={_shown(lexical)} is not a valid "
                                                 f"{getattr(codec, 'xsd_type', 'value')}"))
            continue
        if attr.fixed is not None and not _same_value(codec, lexical, attr.fixed):
            out.append(_finding(el, "xsd:value", f"attribute {name}={_shown(lexical)} must be the fixed value "
                                                 f"{_shown(attr.fixed)}"))
        kind = _id_kind(attr)
        if kind == "ID":
            ident = _norm(lexical)
            if ident in ids:
                out.append(_finding(el, "xsd:id-unique", f"id {ident!r} is already used by {ids[ident]}"))
            else:
                ids[ident] = el.xml_path
        elif kind == "IDREF":
            refs.append((el, name, _norm(lexical)))
        elif kind == "IDREFS":
            refs.extend((el, name, token) for token in lexical.split())
    for name, attr in specs.items():
        if attr.use == "required" and name not in el._attrs:
            out.append(_finding(el, "xsd:required", f"<{el.xml_name}> needs the attribute {name!r}"))


def _children(el: Element, out: list[Finding]) -> None:
    from sr_core.scene._runtime import _model_of

    simple = el._simple_content
    if simple is not None:
        codec = _runtime._codec_for(simple)
        if not codec.is_valid_lexical(el.content):
            out.append(_finding(el, "xsd:value", f"content {_shown(el.content)} is not a valid "
                                                 f"{getattr(codec, 'xsd_type', 'value')}"))
    elif any(isinstance(n, Text) and not n.is_space for n in el.nodes):
        out.append(_finding(el, "xsd:occurs", f"<{el.xml_name}> does not take character data"))
    allowed = set(_model_of(type(el)).slots) if simple is None else set()
    valid: list[Element] = []
    for child in el.elements():
        if isinstance(child, Unknown) or child.xml_name not in allowed:
            out.append(_finding(child, "xsd:element", f"<{child.xml_name}> is not allowed in <{el.xml_name}>"))
        else:
            valid.append(child)
    if simple is not None:
        return
    miss = match_content(el._content, [c.xml_name for c in valid])
    if miss is None:
        return
    want = ", ".join(f"<{n}>" for n in miss.expected) or "nothing more"
    if miss.index < len(valid):
        child = valid[miss.index]
        out.append(_finding(child, "xsd:occurs", f"<{child.xml_name}> cannot come here in <{el.xml_name}> "
                                                 f"(expected: {want})"))
    else:
        out.append(_finding(el, "xsd:occurs", f"<{el.xml_name}> is incomplete (expected: {want})"))


def _versions(root: Element, out: list[Finding]) -> None:
    raw = root._attrs.get("version")
    if raw is None:
        return  # xsd:required has said it
    ver = _norm(raw)
    if ver == "auto":
        return
    if ver not in _gen.VERSIONS:
        out.append(_finding(root, "xsd:version",
                            f"version {ver!r} is not one of {', '.join(_gen.VERSIONS)}"))
        return
    refused = _refused(root)
    hits = refused.get(ver, [])
    for gate, element in hits:
        out.append(_finding(element, gate.id, gate.message))
    lowest = _lowest_clean(refused)
    if lowest is not None and _gen.VERSIONS.index(ver) < _gen.VERSIONS.index(lowest):
        ids = ", ".join(dict.fromkeys(g.id for g, _ in hits))
        out.append(_finding(root, "xsd:version", f"version {ver} is below the lowest version this document can "
                                                 f"carry, {lowest} (refused by {ids})"))


# ------------------------------------------------------------------------------------------ level 2

_L2: dict[str, Any] = {}


def _lxml() -> Any:
    try:
        from lxml import etree, isoschematron
    except ImportError as err:
        raise ImportError("check(schema=True) needs lxml: install it with `pip install sr-core[validate]`") from err
    return etree, isoschematron


def _locate(root: Element, path: Optional[str]) -> Optional[Element]:
    if not path:
        return None
    segments = re.findall(r"/([^/\[]+)(?:\[(\d+)\])?", path)
    if not segments or segments[0][0] != root.xml_name:
        return None
    el = root
    for name, index in segments[1:]:
        found = el.find_all(name)
        n = int(index) if index else 1
        if n < 1 or n > len(found):
            return None
        el = found[n - 1]
    return el


def _level2(scene: Element) -> list[Finding]:
    etree, isoschematron = _lxml()
    root = _root_of(scene)
    from sr_core.scene import io

    if not _L2:
        _L2["xsd"] = etree.XMLSchema(etree.fromstring(_bundled_bytes("scene-render.xsd")))
        _L2["sch"] = isoschematron.Schematron(etree.fromstring(_bundled_bytes("scene-render.sch")),
                                              store_report=True)
    tree = etree.fromstring(io.to_bytes(root))
    out: list[Finding] = []

    def add(code: str, message: str, raw_path: Optional[str]) -> None:
        el = _locate(root, raw_path)
        if el is not None:
            out.append(Finding("error", code, message, el.xml_path, el.source_line, el.source_column))
        else:
            out.append(Finding("error", code, message, raw_path or None))

    xsd = _L2["xsd"]
    if not xsd.validate(tree):
        for entry in xsd.error_log:
            add("xsd:schema", _norm(entry.message), entry.path)
    sch = _L2["sch"]
    if not sch.validate(tree):
        for failed in sch.validation_report.xpath("//svrl:failed-assert", namespaces=_SVRL):
            text = _norm("".join(failed.xpath("svrl:text//text()", namespaces=_SVRL)))
            add(failed.get("id") or "schematron", text, failed.get("location"))
    return out


def _merge(level1: list[Finding], level2: Iterable[Finding]) -> list[Finding]:
    """Level 1 first; a level 2 finding is dropped when level 1 already said it: the same code at the same path, or
    an XSD error at a path where level 1 has an ``xsd:*`` finding."""
    seen = {(f.code, f.path) for f in level1}
    xsd_paths = {f.path for f in level1 if f.code.startswith("xsd:")}
    out = list(level1)
    for f in level2:
        if (f.code, f.path) in seen:
            continue
        if f.code == "xsd:schema" and f.path in xsd_paths:
            continue
        seen.add((f.code, f.path))
        out.append(f)
    return out


# ------------------------------------------------------------------------------------------ check

def _document_version(root: Element) -> Optional[str]:
    raw = root._attrs.get("version")
    if raw is None:
        return None
    ver = _norm(raw)
    return min_version(root) if ver == "auto" else ver


def check(scene: Element, *, schema: bool = False, engine: Any = None, data: Optional[str] = None) -> list[Finding]:
    """Check the document that ``scene`` belongs to.

    Level 1 always runs. ``schema=True`` adds level 2 (lxml; ``ImportError`` with an install hint when it is
    missing). ``engine=PATH`` adds level 3 (``sr_core.scene.engine.level3``), with ``data`` as its data file.
    Raises ``IntegrityError`` when the bundled schema files do not match the generated module (SREP 0, D8).
    """
    verify_integrity()
    root = _root_of(scene)
    findings = _level1(root)
    if schema:
        findings = _merge(findings, _level2(root))
    if engine is not None:
        from sr_core.scene import io

        runner = importlib.import_module("sr_core.scene.engine").level3
        findings = findings + list(runner(io.to_bytes(root), engine, data=data,
                                          document_version=_document_version(root)))
    return findings
