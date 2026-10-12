"""Exceptions of the scene SDK (SREP 0, sections 3.5 and 9)."""

from __future__ import annotations

import difflib
from typing import Iterable, Optional


class SchemaError(Exception):
    """The generator met a schema construct, pattern, gate form or name it does not handle (D3)."""


class SchemaValueError(ValueError):
    """A value or a child that the schema refuses, raised at construction (level 0).

    ``path`` is the element path in the engine's form, ``attribute`` the XML attribute name (or None for a child or
    content error), ``xsd_type`` the XSD type the value was checked against (or None).
    """

    def __init__(self, message: str, *, path: str | None = None, attribute: str | None = None,
                 xsd_type: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.path = path
        self.attribute = attribute
        self.xsd_type = xsd_type

    def __str__(self) -> str:
        where = []
        if self.path:
            where.append(self.path)
        if self.attribute:
            where.append("@" + self.attribute)
        prefix = "".join(where[:1]) + ("/" + where[1] if len(where) > 1 else "")
        suffix = f" ({self.xsd_type})" if self.xsd_type else ""
        return f"{prefix}: {self.message}{suffix}" if prefix else f"{self.message}{suffix}"


def suggest(name: str, candidates: Iterable[str], limit: int = 3) -> tuple[str, ...]:
    """Up to ``limit`` of ``candidates`` that ``name`` probably meant, best first.

    Order of evidence: the same letters in another case, the XML spelling of a Python name (``from`` for ``from_``,
    and back), one name holding the other (``blendMode`` and ``blend``), then ``difflib`` close matches.
    """
    low: dict[str, str] = {}
    for cand in candidates:
        low.setdefault(cand.lower(), cand)
    key = name.lower()
    found: list[str] = []

    def take(lowered: str) -> None:
        cand = low.get(lowered)
        if cand is not None and cand != name and cand not in found:
            found.append(cand)

    for variant in (key, key + "_", key.rstrip("_")):
        take(variant)
    if len(key) >= 4:
        for lowered in sorted(low, key=len, reverse=True):  # the longest shared name first
            if len(lowered) >= 4 and (lowered in key or key in lowered):
                take(lowered)
    for lowered in difflib.get_close_matches(key, list(low), n=limit, cutoff=0.6):
        take(lowered)
    return tuple(found[:limit])


class UnknownNameError(SchemaValueError, AttributeError):
    """A name the schema does not have: an attribute, an ``add_<name>`` method, a child element or an element name.

    It is an ``AttributeError`` too, so ``hasattr`` and ``getattr(obj, name, default)`` keep working. ``name`` is what was
    asked for, ``element`` the element it was asked of (``layer``), ``suggestions`` the close matches, best first, and
    ``allowed`` every valid name there. ``kind`` is ``attribute``, ``method``, ``child`` or ``element``.
    """

    def __init__(self, name: str, element: str, allowed: Iterable[str], *, kind: str = "attribute",
                 suggestions: Optional[Iterable[str]] = None, path: Optional[str] = None) -> None:
        self.element = element
        self.kind = kind
        self.allowed = tuple(allowed)
        self.suggestions = suggest(name, self.allowed) if suggestions is None else tuple(suggestions)
        if kind == "child":
            head = f"<{name}> is not allowed in <{element}>"
        elif kind == "element":
            head = f"{name!r} is not an element name of {element}"
        else:
            head = f"<{element}> has no {'method' if kind == 'method' else 'attribute'} {name!r}"
        if self.suggestions:
            head += f"; did you mean {self.suggestions[0]!r}?"
        text = ", ".join(self.allowed) or "none"
        SchemaValueError.__init__(self, f"{head} (allowed: {text})", path=path)
        self.name = name  # AttributeError.name

    def __reduce__(self) -> tuple[object, ...]:
        return (_rebuild_unknown, (self.name, self.element, self.allowed, self.kind, self.suggestions, self.path))


def _rebuild_unknown(name: str, element: str, allowed: tuple[str, ...], kind: str, suggestions: tuple[str, ...],
                     path: Optional[str]) -> UnknownNameError:
    return UnknownNameError(name, element, allowed, kind=kind, suggestions=suggestions, path=path)


class IntegrityError(RuntimeError):
    """The bundled schema files do not match the hashes the generated module was built from (D8)."""
