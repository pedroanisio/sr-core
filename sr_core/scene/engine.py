"""Level 3: ask an engine (SREP 0 sections 6 and 7).

The engine is any executable that implements two commands:

- ``<engine> capabilities`` prints the manifest of SREP 22 (``format``, ``engine``, ``schema``, ``entries``);
- ``<engine> validate --format json [--no-assets] FILE`` prints
  ``{"valid", "files": [{"file", "valid", "errors", "warnings", "diagnostics": [...]}]}`` and exits 0 when valid,
  1 on findings, 2 on usage or read errors.

``level3`` returns the engine's diagnostics unchanged, as ``Finding`` records, plus three findings of its own, all
with a ``sdk:`` code: ``sdk:schema-skew``, ``sdk:engine-version`` and ``sdk:engine-failed``.

Standard library only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from sr_core.scene import _generated
from sr_core.scene.findings import Finding

__all__ = ["EngineError", "EngineInfo", "engine_info", "level3"]

PathLike = Union[str, "os.PathLike[str]"]
CAPABILITIES_FORMAT = "scene-render-capabilities/1"
_STDERR_LIMIT = 500
_INFO_CACHE: dict[tuple[str, int], "EngineInfo"] = {}


class EngineError(RuntimeError):
    """The engine could not be run, timed out, or answered with something that is not its documented output."""


@dataclass(frozen=True)
class EngineInfo:
    """What ``<engine> capabilities`` says about the engine: its name, its version, and the schema release it
    implements (``MAJOR.MINOR.PATCH``). ``path`` is the resolved executable."""

    name: str
    version: str
    schema: str
    path: Path


def _excerpt(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _STDERR_LIMIT else text[:_STDERR_LIMIT] + "..."


def _run(argv: list[str], timeout: float) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"engine {argv[0]!r} timed out after {timeout:g} s running {argv[1]!r}") from exc
    except FileNotFoundError as exc:
        raise EngineError(f"engine not found: {argv[0]!r}") from exc
    except OSError as exc:
        raise EngineError(f"cannot run engine {argv[0]!r}: {exc}") from exc


def _executable(path: PathLike) -> Path:
    """The engine path as given, or, when it has no path separator, the executable of that name on ``PATH``."""
    text = os.fspath(path)
    if os.sep not in text and (os.altsep is None or os.altsep not in text):
        found = shutil.which(text)
        if found is None:
            raise EngineError(f"engine not found: {text!r} (not on PATH)")
        return Path(found)
    return Path(text)


def engine_info(path: PathLike, *, timeout: float = 30.0) -> EngineInfo:
    """Run ``<engine> capabilities`` (``path`` with no path separator is looked up on ``PATH``) and read ``engine.name``, ``engine.version`` and ``schema`` (SREP 22).

    The result is cached per resolved path and modification time, so replacing the executable invalidates it.
    Raises ``EngineError`` when the engine cannot be run, exits non-zero, or prints a manifest of another format.
    """
    resolved = _executable(path).resolve()
    try:
        key = (str(resolved), resolved.stat().st_mtime_ns)
    except OSError as exc:
        raise EngineError(f"engine not found: {str(path)!r} ({exc.strerror})") from exc
    cached = _INFO_CACHE.get(key)
    if cached is not None:
        return cached
    done = _run([str(resolved), "capabilities"], timeout)
    if done.returncode != 0:
        raise EngineError(f"'{resolved} capabilities' exited {done.returncode}: {_excerpt(done.stderr)}")
    try:
        manifest = json.loads(done.stdout)
        if manifest["format"] != CAPABILITIES_FORMAT:
            raise EngineError(f"unsupported capabilities format {manifest['format']!r} (want {CAPABILITIES_FORMAT!r})")
        info = EngineInfo(str(manifest["engine"]["name"]), str(manifest["engine"]["version"]),
                          str(manifest["schema"]), resolved)
    except (ValueError, KeyError, TypeError) as exc:
        raise EngineError(f"'{resolved} capabilities' printed an unusable manifest: {exc!r}") from exc
    _INFO_CACHE[key] = info
    return info


def _major_minor(release: Optional[str]) -> Optional[tuple[int, int]]:
    if not release:
        return None
    parts = release.split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None


_SEVERITIES = ("error", "warning", "info")


def _to_finding(diag: Any) -> Finding:
    if not isinstance(diag, dict) or "code" not in diag or "message" not in diag:
        raise EngineError(f"diagnostic without code and message: {diag!r}")
    loc = diag.get("loc") if isinstance(diag.get("loc"), dict) else {}
    severity = diag.get("severity")
    return Finding(severity if severity in _SEVERITIES else "info", str(diag["code"]), str(diag["message"]),
                   diag.get("path"), loc.get("line"), loc.get("column"))


def _validate(xml_bytes: bytes, exe: Path, data: Optional[PathLike], timeout: float) -> list[Finding]:
    directory = None if data is None else str(data)
    try:
        handle = tempfile.NamedTemporaryFile(dir=directory, prefix=".sr-scene-", suffix=".xml", delete=False)
    except OSError as exc:
        raise EngineError(f"cannot write the temporary scene file: {exc}") from exc
    name = handle.name
    try:
        with handle:
            handle.write(xml_bytes)
        argv = [str(exe), "validate", "--format", "json"]
        if data is None:
            argv.append("--no-assets")
        argv.append(name)
        done = _run(argv, timeout)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass
    if done.returncode not in (0, 1):
        raise EngineError(f"'validate' exited {done.returncode}: {_excerpt(done.stderr) or _excerpt(done.stdout)}")
    try:
        report = json.loads(done.stdout)
        files = report["files"]
        if not isinstance(files, list):
            raise TypeError("'files' is not a list")
        return [_to_finding(d) for f in files for d in f["diagnostics"]]
    except EngineError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise EngineError(f"'validate' printed unusable output ({exc!r}): {_excerpt(done.stderr)}") from exc


def level3(xml_bytes: bytes, engine_path: PathLike, *, data: Optional[PathLike] = None,
           document_version: Optional[str] = None, timeout: float = 300.0) -> list[Finding]:
    """Validate ``xml_bytes`` with the engine and return its diagnostics unchanged (code, message, severity, path,
    and line and column from ``loc``), followed by the SDK's own findings.

    Asset paths: the bytes are written to a temporary file *inside* ``data``, so the engine resolves relative asset
    paths against that directory. Without ``data`` the file goes to the system temporary directory and the engine
    is run with ``--no-assets``, because relative paths could not resolve there. The file is removed afterwards.

    SDK findings: ``sdk:schema-skew`` (warning) when the engine's schema release differs from the SDK's;
    ``sdk:engine-version`` (error) when the engine's schema MAJOR.MINOR is below ``document_version``;
    ``sdk:engine-failed`` (error) when the engine cannot be run, times out, exits 2, or prints unusable JSON.
    """
    try:
        info = engine_info(engine_path)
        findings = _validate(xml_bytes, info.path, data, timeout)
    except EngineError as exc:
        return [Finding("error", "sdk:engine-failed", str(exc))]
    if info.schema != _generated.SCHEMA_RELEASE:
        findings.append(Finding(
            "warning", "sdk:schema-skew",
            f"engine {info.name} {info.version} implements schema {info.schema}; "
            f"this SDK was generated from schema {_generated.SCHEMA_RELEASE}"))
    # SREP 0 section 7.3 says "the engine's MAJOR.MINOR". Document versions track the schema's MAJOR.MINOR
    # (scene/@version), so the comparable quantity is the engine's schema release, not its own product version.
    engine_mm, doc_mm = _major_minor(info.schema), _major_minor(document_version)
    if engine_mm is not None and doc_mm is not None and engine_mm < doc_mm:
        findings.append(Finding(
            "error", "sdk:engine-version",
            f"engine {info.name} {info.version} implements schema {info.schema}, below the document's "
            f"version {document_version}"))
    return findings
