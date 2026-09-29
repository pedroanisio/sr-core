#!/usr/bin/env python3
"""Compute, apply and check sr-core versions from the changelogs (SREP 4).

    python3 tools/release.py check                 # every version agrees with its changelog; exit 1 if not
    python3 tools/release.py next tools|schema     # the version the Unreleased entries call for
    python3 tools/release.py release tools|schema [--date YYYY-MM-DD]

Nobody picks version numbers. Each change is recorded once under "## Unreleased" in the class that fits, and a
release takes the single largest bump those classes call for: Breaking/Removed -> MAJOR, Added/Deprecated ->
MINOR, anything else -> PATCH. Many changes share one bump, and an empty Unreleased section releases nothing.
`release` moves the entries under a dated heading, writes the new version where it lives, refreshes what depends
on it (schema hashes and the generated reference), and prints the tag to create. It never tags or commits.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MAJOR = {"breaking", "removed"}
MINOR = {"added", "deprecated"}
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
UNRELEASED_SKELETON = "## Unreleased\n\n### Breaking\n\n### Added\n\n### Fixed\n\n"


class ReleaseError(Exception):
    pass


# ------------------------------------------------------------------- changelog
def parse(text: str) -> tuple[dict[str, list[str]], list[str], tuple[int, int]]:
    """({class: [entries]} under Unreleased, [released versions, newest first], (start, end) of Unreleased)."""
    m = re.search(r"^## Unreleased[ \t]*\n", text, re.M)
    if not m:
        raise ReleaseError("no '## Unreleased' section")
    nxt = re.search(r"^## ", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    classes: dict[str, list[str]] = {}
    current = None
    for line in text[m.end():end].splitlines():
        h = re.match(r"### (.+?)\s*$", line)
        if h:
            current = h.group(1).strip().lower()
            classes.setdefault(current, [])
        elif re.match(r"\s*[-*] \S", line):
            if current is None:
                raise ReleaseError(f"entry outside a ### class under Unreleased: {line.strip()}")
            classes[current].append(line.strip()[2:])
        elif line.startswith("  ") and current and classes[current]:
            classes[current][-1] += " " + line.strip()
    released = re.findall(r"^## (\d+\.\d+\.\d+)\b", text, re.M)
    return {k: v for k, v in classes.items() if v}, released, (m.start(), end)


def next_version(current: str, classes: dict[str, list[str]]) -> str | None:
    if not classes:
        return None
    ma, mi, pa = (int(x) for x in SEMVER.fullmatch(current).groups())
    if MAJOR & set(classes):
        return f"{ma + 1}.0.0"
    if MINOR & set(classes):
        return f"{ma}.{mi + 1}.0"
    return f"{ma}.{mi}.{pa + 1}"


def cut(text: str, version: str, date: str) -> str:
    classes, _, (a, b) = parse(text)
    body = "".join(f"### {name.capitalize()}\n\n" + "".join(f"- {e}\n" for e in entries) + "\n"
                   for name, entries in classes.items())
    return text[:a] + UNRELEASED_SKELETON + f"## {version} — {date}\n\n{body}" + text[b:].lstrip("\n")


# ------------------------------------------------------------------ components
def _read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def _write(p, text):
    with open(os.path.join(ROOT, p), "w", encoding="utf-8") as f:
        f.write(text)


INIT = "sr_core/__init__.py"
XSD, SCH, SUMS = "schema/scene-render.xsd", "schema/scene-render.sch", "schema/SHA256SUMS"


def tools_version() -> str:
    return re.search(r'^__version__ = "([^"]+)"', _read(INIT), re.M).group(1)


def set_tools_version(v: str) -> None:
    _write(INIT, re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{v}"', _read(INIT), flags=re.M))


def schema_version() -> str:
    return re.search(r'<xs:schema\b[^>]*\bversion="([^"]+)"', _read(XSD)).group(1)


def document_versions() -> list[str]:
    """The values `scene/@version` accepts."""
    x = _read(XSD)
    i = x.index('<xs:element name="scene">')
    blk = re.search(r'<xs:attribute name="version"[^>]*>(.*?)</xs:attribute>', x[i:], re.S).group(1)
    return re.findall(r'<xs:enumeration value="([^"]+)"', blk)


def set_schema_version(v: str) -> None:
    _write(XSD, re.sub(r'(<xs:schema\b[^>]*\bversion=")[^"]+(")', rf"\g<1>{v}\2", _read(XSD), count=1))
    refresh_schema()


def sums_text() -> str:
    return "".join(f"{hashlib.sha256(open(os.path.join(ROOT, p), 'rb').read()).hexdigest()}  {os.path.basename(p)}\n"
                   for p in (XSD, SCH))


def refresh_schema() -> None:
    _write(SUMS, sums_text())
    from sr_core.schemadoc import cli
    if cli.main([]) != 0:
        raise ReleaseError("sr-schemadoc failed")


COMPONENTS = {
    "tools": {"changelog": "CHANGELOG.md", "get": tools_version, "set": set_tools_version, "tag": "v"},
    "schema": {"changelog": "schema/CHANGELOG.md", "get": schema_version, "set": set_schema_version, "tag": "schema-"},
}


# ----------------------------------------------------------------------- check
def check() -> list[str]:
    problems = []
    for name, c in COMPONENTS.items():
        v = c["get"]()
        if not SEMVER.fullmatch(v):
            problems.append(f"{name}: version {v!r} is not MAJOR.MINOR.PATCH")
            continue
        try:
            _, released, _ = parse(_read(c["changelog"]))
        except ReleaseError as e:
            problems.append(f"{c['changelog']}: {e}")
            continue
        if not released or released[0] != v:
            problems.append(f"{name}: version {v} but the newest release in {c['changelog']} is "
                            f"{released[0] if released else 'none'}")
    if SEMVER.fullmatch(schema_version()):
        mm = ".".join(schema_version().split(".")[:2])
        if mm not in document_versions():
            problems.append(f"schema: {schema_version()} but scene/@version does not accept {mm}")
    if _read(SUMS) != sums_text():
        problems.append(f"{SUMS} does not match the schema files")
    from sr_core.schemadoc import cli
    if cli.canonical_schema()[0] and cli.render(*cli.canonical_schema()) != cli.existing(os.path.join(ROOT, "docs", "schema")):
        problems.append("docs/schema is stale; run python3 -m sr_core.schemadoc")
    from sr_core.vpkg import manifest as mf
    title = mf.load_schema().get("title", "")
    if mf.FORMAT_VERSION not in title or not os.path.basename(mf.SCHEMA_PATH).startswith(f"vpkg-{mf.FORMAT_VERSION.split('.')[0]}."):
        problems.append(f"package format {mf.FORMAT_VERSION} does not match {os.path.basename(mf.SCHEMA_PATH)} ({title!r})")
    if 'dynamic = ["version"]' not in _read("pyproject.toml"):
        problems.append("pyproject.toml must take its version from sr_core.__version__")
    return problems


# ------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="release.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    n = sub.add_parser("next")
    n.add_argument("component", choices=COMPONENTS)
    r = sub.add_parser("release")
    r.add_argument("component", choices=COMPONENTS)
    r.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            problems = check()
            for p in problems:
                print(p, file=sys.stderr)
            if not problems:
                print(f"ok: tools {tools_version()}, schema {schema_version()}")
            return 1 if problems else 0
        c = COMPONENTS[a.component]
        cur = c["get"]()
        classes, _, _ = parse(_read(c["changelog"]))
        new = next_version(cur, classes)
        if a.cmd == "next":
            print(new or f"{cur} (nothing to release)")
            return 0
        if new is None:
            print(f"{a.component}: nothing under Unreleased; {cur} stays", file=sys.stderr)
            return 1
        if a.component == "schema" and new.split(".")[2] == "0":
            mm = ".".join(new.split(".")[:2])
            if mm not in document_versions():
                raise ReleaseError(f"schema {new} adds document version {mm}: add it to scene/@version in the same SREP")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
            raise ReleaseError("--date must be YYYY-MM-DD")
        _write(c["changelog"], cut(_read(c["changelog"]), new, a.date))
        c["set"](new)
        print(f"{a.component}: {cur} -> {new}. Commit, then: git tag {c['tag']}{new}")
        return 0
    except ReleaseError as e:
        print(f"release.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
