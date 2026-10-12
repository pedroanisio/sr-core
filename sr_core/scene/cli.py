"""The ``sr-scene`` command (SREP 0 section 8): ``check``, ``min-version``, ``format``, ``describe``, ``list`` and ``new``.

Exit codes: 0 valid (or nothing to change), 1 findings (errors; warnings count only with ``--deny-warnings``;
``format --check``: a file would change), 2 a file cannot be read or is not well-formed XML, or a usage error.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional, Sequence

import sr_core
from sr_core.scene import _generated, io
from sr_core.scene._runtime import Unknown
from sr_core.scene.errors import SchemaValueError, UnknownNameError
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
    # level 1 runs only the Schematron's version gates; "ok" says how far the document was checked
    levels = [1] + ([2] if args.schema else []) + ([3] if args.engine else [])
    ok = "ok (level 1)" if len(levels) == 1 else f"ok (levels {', '.join(map(str, levels))})"
    records: list[dict[str, Any]] = []
    for path in args.files:
        scene, error = _read(path)
        if scene is None:
            print(f"{path}: cannot read: {error}", file=sys.stderr)
            records.append({"file": path, "valid": False, "error": error, "findings": []})
            status = 2
            continue
        try:
            findings = checks.check(scene, schema=args.schema, engine=args.engine, data=args.data)
        except ImportError:
            if not args.schema:
                raise
            print("check --schema needs lxml: pip install sr-core[validate]", file=sys.stderr)
            return 2
        failed = _fails(findings, args.deny_warnings)
        records.append({"file": path, "valid": not failed, "findings": [f.to_dict() for f in findings]})
        if args.format == "human":
            for finding in findings:
                print(_human(path, finding))
            if not findings:
                print(f"{path}: {ok}")
        if failed and status == 0:
            status = 1
    if args.format == "json":
        print(json.dumps({"format": "sr-scene-findings/1", "valid": all(r["valid"] for r in records),
                          "levels": levels, "files": records}, indent=2))
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
        if isinstance(scene, Unknown) or scene.xml_name != "scene":
            print(f"{path}: error: the root element must be <scene>, not <{scene.xml_name}>", file=sys.stderr)
            status = max(status, 1)
            continue
        try:
            print(f"{path}: {checks.min_version(scene)}")
        except SchemaValueError as exc:
            print(f"{path}: error: {exc}", file=sys.stderr)
            status = max(status, 1)
    return status


def _write_atomically(path: str, data: bytes) -> None:
    """Write ``data`` to a temporary file next to ``path`` and rename it over ``path``."""
    directory = os.path.dirname(os.path.abspath(path))
    handle = tempfile.NamedTemporaryFile(dir=directory, prefix=".sr-scene-", suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(handle.name, os.stat(path).st_mode & 0o7777)
        except OSError:
            pass
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _cmd_format(args: argparse.Namespace) -> int:
    status = 0
    for path in args.files:
        scene, error = _read(path)
        if scene is None:
            print(f"{path}: cannot read: {error}", file=sys.stderr)
            status = 2
            continue
        if io.has_doctype(path):
            print(f"{path}: refused: the file declares a DOCTYPE, and rewriting it would drop the declaration and "
                  f"inline its entities", file=sys.stderr)
            status = max(status, 1) if status != 2 else status
            continue
        current = Path(path).read_bytes()
        moved = io.reorder_count(scene)
        pretty = io.to_bytes(scene, layout="pretty")
        if pretty == current:
            continue
        if moved:
            print(f"{path}: reordered {moved} elements into content-model order", file=sys.stderr)
        if args.check:
            print(f"{path}: would be reformatted")
            if status == 0:
                status = 1
        else:
            _write_atomically(path, pretty)
            print(f"{path}: formatted")
    return status


def _summary(doc: str) -> str:
    """The first sentence of a documentation text, on one line."""
    flat = " ".join(doc.split())
    match = re.search(r"[.!?](?:\s|$)", flat)
    text = flat[:match.end()].strip() if match else flat
    return text if len(text) <= 160 else text[:157].rstrip() + "..."


def _type_text(t: Any) -> str:
    """A short human form of a type description."""
    if t.kind == "list":
        text = "list of " + (_type_text(t.item) if t.item is not None else "?")
    elif t.kind == "union":
        text = " | ".join(_type_text(m) for m in t.members)
    else:
        text = t.name or t.base or "?"
    if t.enum:
        text += " {" + ", ".join(t.enum) + "}"
    parts = [f"{k}={v}" for k, v in t.facets] + [f"pattern {p}" for p in t.patterns]
    if parts:
        text += " (" + "; ".join(parts) + ")"
    return text


def _describe_human(d: Any) -> str:
    since = f", since {d.min_version}" if d.min_version != _generated.VERSIONS[0] else ""
    lines = [f"{'|'.join(d.xml_names) or '(abstract)'}  (class {d.class_name}, type {d.xsd_type}{since})"]
    if d.doc:
        lines += ["  " + ln for ln in d.doc.splitlines()]
    lines.append(f"  content: {d.content_model}")
    if d.simple_content is not None:
        lines.append(f"    text of type {_type_text(d.simple_content)}")
    if d.children:
        lines.append("  children:")
        for c in d.children:
            hi = "*" if c.max_occurs is None else str(c.max_occurs)
            gate = f"  since {c.min_version}" if c.min_version != _generated.VERSIONS[0] else ""
            lines.append(f"    {c.name}  {c.min_occurs}..{hi}  {c.class_name}{gate}")
    if d.attributes:
        lines.append("  attributes:")
        for a in d.attributes:
            name = a.xml_name if a.python_name == a.xml_name else f"{a.xml_name} (python: {a.python_name})"
            flags = ["required" if a.required else "optional"]
            if a.default is not None:
                flags.append(f"default {a.default}")
            if a.fixed is not None:
                flags.append(f"fixed {a.fixed}")
            if a.min_version:
                flags.append(f"since {a.min_version}")
            lines.append(f"    {name}  {_type_text(a.type)}  [{', '.join(flags)}]")
            if a.value_min_versions:
                lines.append("        values since: " + ", ".join(f"{k} {v}" for k, v in a.value_min_versions))
            if a.doc:
                lines += ["        " + ln for ln in a.doc.splitlines()]
    return "\n".join(lines)


def _cmd_describe(args: argparse.Namespace) -> int:
    from sr_core.scene import introspect

    if args.all:
        if args.format == "json":
            print(json.dumps(introspect.describe_all(), separators=(",", ":"), ensure_ascii=False))
        else:
            from sr_core.scene import CLASSES
            print("\n\n".join(_describe_human(introspect.describe(c)) for c in CLASSES.values()))
        return 0
    found: list[Any] = []
    status = 0
    for name in args.names:
        try:
            found.append(introspect.describe(name))
        except introspect.AmbiguousNameError as exc:
            found += [introspect.describe(c) for c in exc.candidates]
        except UnknownNameError as exc:
            hint = f"; did you mean {exc.suggestions[0]!r}?" if exc.suggestions else "; run 'sr-scene list' for the names"
            print(f"sr-scene: {name!r} is not an element or class name{hint}", file=sys.stderr)
            status = 2
    if args.format == "json":
        if found:
            print(json.dumps({"format": introspect.FORMAT, "schema_release": _generated.SCHEMA_RELEASE,
                              "elements": [d.to_dict() for d in found]}, ensure_ascii=False))
    else:
        if found:
            print("\n\n".join(_describe_human(d) for d in found))
    return status


def _cmd_list(args: argparse.Namespace) -> int:
    from sr_core.scene import CLASSES, introspect

    rows = []
    for cls in CLASSES.values():
        d = introspect.describe(cls)
        for name in d.xml_names:
            rows.append({"name": name, "class_name": d.class_name, "summary": _summary(d.doc),
                         "min_version": d.min_version})
    rows.sort(key=lambda r: (r["name"], r["class_name"]))
    shared = {r["name"] for r in rows if sum(1 for x in rows if x["name"] == r["name"]) > 1}
    if args.format == "json":
        print(json.dumps({"format": "sr-scene-list/1", "schema_release": _generated.SCHEMA_RELEASE,
                          "elements": rows}, indent=2, ensure_ascii=False))
        return 0
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        tag = f" [{r['class_name']}]" if r["name"] in shared else ""
        print(f"{r['name']:<{width}}  {r['summary']}{tag}".rstrip())
    return 0


def _cmd_new(args: argparse.Namespace) -> int:
    from sr_core.scene import Scene

    scene = Scene(version=args.version)
    scene.add_project(width=1280, height=720, fps="30", duration=4)
    scene.add_composition()
    data = io.to_bytes(scene, layout=args.layout)
    if args.output:
        _write_atomically(args.output, data)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sr-scene", description="Check, inspect and format scene documents.")
    parser.add_argument("--version", action="version",
                        version=f"sr-scene {sr_core.__version__} (schema {_generated.SCHEMA_RELEASE})")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{check,min-version,format,describe,list,new}")

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

    desc = sub.add_parser("describe", help="show what the schema says about elements: children, attributes, types, docs")
    desc.add_argument("names", nargs="*", metavar="NAME", help="an XML element name (layer) or a class name (Layer)")
    desc.add_argument("--all", action="store_true", help="describe every element (use with --format json for a "
                                                         "compact dump of the whole schema)")
    desc.add_argument("--format", choices=("human", "json"), default="human")
    desc.set_defaults(run=_cmd_describe)

    lst = sub.add_parser("list", help="list the element names with the first sentence of their documentation")
    lst.add_argument("--format", choices=("human", "json"), default="human")
    lst.set_defaults(run=_cmd_list)

    new = sub.add_parser("new", help="print a minimal scene that is clean at check levels 1 and 2")
    new.add_argument("--version", choices=("auto",) + tuple(_generated.VERSIONS), default="auto",
                     help="scene version (default: auto, the lowest the content allows)")
    new.add_argument("--layout", choices=("pretty", "indent", "preserve"), default="pretty")
    new.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of standard output")
    new.set_defaults(run=_cmd_new)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run ``sr-scene`` and return its exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "check" and args.data and not args.engine:
        parser.error("--data needs --engine")
    if args.command == "describe" and bool(args.names) == bool(args.all):
        parser.error("describe needs one or more NAMEs, or --all (not both)")
    return int(args.run(args))
