"""The ``sr-scene`` command (SREP 0 section 8): ``check``, ``min-version`` and ``format``.

Exit codes: 0 valid (or nothing to change), 1 findings (errors; warnings count only with ``--deny-warnings``;
``format --check``: a file would change), 2 a file cannot be read or is not well-formed XML, or a usage error.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional, Sequence

import sr_core
from sr_core.scene import _generated, io
from sr_core.scene.findings import Finding

__all__ = ["main"]

_READ_ERRORS = (OSError, ET.ParseError, UnicodeError)


def _checks() -> Any:
    return importlib.import_module("sr_core.scene.checks")


def _read(path: str) -> tuple[Optional[Any], Optional[str]]:
    try:
        return io.read(path), None
    except _READ_ERRORS as exc:
        return None, str(exc)


def _human(path: str, finding: Finding) -> str:
    where = path
    if finding.line is not None:
        where += f":{finding.line}" + (f":{finding.column}" if finding.column is not None else "")
    place = f"{finding.path}: " if finding.path else ""
    return f"{where}: {finding.severity}: {finding.code}: {place}{finding.message}"


def _fails(findings: Sequence[Finding], deny_warnings: bool) -> bool:
    return any(f.severity == "error" or (deny_warnings and f.severity == "warning") for f in findings)


def _cmd_check(args: argparse.Namespace) -> int:
    checks = _checks()
    status = 0
    records: list[dict[str, Any]] = []
    for path in args.files:
        scene, error = _read(path)
        if scene is None:
            print(f"{path}: cannot read: {error}", file=sys.stderr)
            records.append({"file": path, "valid": False, "error": error, "findings": []})
            status = 2
            continue
        findings = checks.check(scene, schema=args.schema, engine=args.engine, data=args.data)
        failed = _fails(findings, args.deny_warnings)
        records.append({"file": path, "valid": not failed, "findings": [f.to_dict() for f in findings]})
        if args.format == "human":
            for finding in findings:
                print(_human(path, finding))
            if not findings:
                print(f"{path}: ok")
        if failed and status == 0:
            status = 1
    if args.format == "json":
        print(json.dumps({"valid": all(r["valid"] for r in records), "files": records}, indent=2))
    return status


def _cmd_min_version(args: argparse.Namespace) -> int:
    checks = _checks()
    status = 0
    for path in args.files:
        scene, error = _read(path)
        if scene is None:
            print(f"{path}: cannot read: {error}", file=sys.stderr)
            status = 2
            continue
        print(f"{path}: {checks.min_version(scene)}")
    return status


def _cmd_format(args: argparse.Namespace) -> int:
    status = 0
    for path in args.files:
        scene, error = _read(path)
        if scene is None:
            print(f"{path}: cannot read: {error}", file=sys.stderr)
            status = 2
            continue
        current = Path(path).read_bytes()
        pretty = io.to_bytes(scene, layout="pretty")
        if pretty == current:
            continue
        if args.check:
            print(f"{path}: would be reformatted")
            if status == 0:
                status = 1
        else:
            Path(path).write_bytes(pretty)
            print(f"{path}: formatted")
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sr-scene", description="Check, inspect and format scene documents.")
    parser.add_argument("--version", action="version",
                        version=f"sr-scene {sr_core.__version__} (schema {_generated.SCHEMA_RELEASE})")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{check,min-version,format}")

    check = sub.add_parser("check", help="check documents (level 1; --schema adds level 2; --engine adds level 3)")
    check.add_argument("files", nargs="+", metavar="FILE")
    check.add_argument("--schema", action="store_true", help="also validate against the bundled XSD and Schematron (lxml)")
    check.add_argument("--engine", metavar="PATH", help="also run '<engine> validate' on the document")
    check.add_argument("--data", metavar="DIR", help="directory that relative asset paths resolve against (with --engine)")
    check.add_argument("--format", choices=("human", "json"), default="human")
    check.add_argument("--deny-warnings", action="store_true", help="exit 1 on warnings too")
    check.set_defaults(run=_cmd_check)

    minv = sub.add_parser("min-version", help="print each document's lowest valid scene version")
    minv.add_argument("files", nargs="+", metavar="FILE")
    minv.set_defaults(run=_cmd_min_version)

    fmt = sub.add_parser("format", help="rewrite documents in the pretty layout")
    fmt.add_argument("files", nargs="+", metavar="FILE")
    fmt.add_argument("--check", action="store_true", help="write nothing; exit 1 if a file would change")
    fmt.set_defaults(run=_cmd_format)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run ``sr-scene`` and return its exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "check" and args.data and not args.engine:
        parser.error("--data needs --engine")
    return int(args.run(args))
