"""Exceptions of the scene SDK (SREP 0, sections 3.5 and 9)."""

from __future__ import annotations


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


class IntegrityError(RuntimeError):
    """The bundled schema files do not match the hashes the generated module was built from (D8)."""
