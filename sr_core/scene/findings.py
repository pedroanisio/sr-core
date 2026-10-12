"""The result record of every check level (SREP 0, section 6.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class Finding:
    """One finding: ``path`` is in the engine's form (``/scene/composition/layer[2]``); ``line`` and ``column`` are
    1-based and set when the document was read from a file, else None."""

    severity: Severity
    code: str
    message: str
    path: str | None = None
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {"severity": self.severity, "code": self.code, "message": self.message,
                "path": self.path, "line": self.line, "column": self.column}

    def __str__(self) -> str:
        where = self.path or "/"
        if self.line is not None:
            where += f" (line {self.line}" + (f", column {self.column})" if self.column is not None else ")")
        return f"{self.severity}: {self.code}: {where}: {self.message}"
