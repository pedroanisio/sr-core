"""The sources must parse on the oldest Python that pyproject.toml supports (3.10).

Python 3.12 (PEP 701) lets an f-string's replacement fields reuse the enclosing quote, hold backslashes and hold
comments. Before 3.12 each of those is a SyntaxError, and ``ast.parse(..., feature_version=(3, 10))`` on 3.12+ does
not report them. A newer interpreter therefore passes the whole suite while 3.10 cannot import the module, so this
test tokenizes every source file and applies the pre-3.12 f-string rules itself.
"""
from __future__ import annotations

import io
import os
import sys
import tokenize

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ("sr_core", "tools", "tests")

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12),
                                reason="f-strings are tokenized as one STRING before 3.12; the parser checks them")


def _sources() -> list[str]:
    out = []
    for d in DIRS:
        for base, _, files in os.walk(os.path.join(ROOT, d)):
            out += [os.path.join(base, f) for f in files if f.endswith(".py")]
    return sorted(out)


def _quote(start: str) -> str:
    """The closing delimiter of an FSTRING_START token such as ``f"`` or ``rf'''``."""
    body = start.lstrip("fFrRbBuU")
    return body[:3] if body[:3] in ('"""', "'''") else body[:1]


def pre_312_fstring_problems(src: str) -> list[tuple[int, str]]:
    """(line, problem) for every f-string construct that only Python 3.12+ accepts."""
    problems: list[tuple[int, str]] = []
    quotes: list[str] = []  # enclosing f-string delimiters, innermost last
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        name = tokenize.tok_name[tok.type]
        if quotes and name not in ("FSTRING_MIDDLE", "FSTRING_END"):
            # inside a replacement field (the format spec arrives as FSTRING_MIDDLE)
            if any(q in tok.string for q in quotes):
                problems.append((tok.start[0], f"reuses an enclosing f-string quote: {tok.string!r}"))
            if "\\" in tok.string:
                problems.append((tok.start[0], f"backslash in an f-string expression: {tok.string!r}"))
            if name == "COMMENT":
                problems.append((tok.start[0], "comment in an f-string expression"))
        elif len(quotes) > 1:  # the text of an f-string nested in another one's replacement field
            if any(q in tok.string for q in quotes[:-1]):
                problems.append((tok.start[0], f"reuses an enclosing f-string quote: {tok.string!r}"))
            if "\\" in tok.string:
                problems.append((tok.start[0], f"backslash in an f-string expression: {tok.string!r}"))
        if name == "FSTRING_START":
            quotes.append(_quote(tok.string))
        elif name == "FSTRING_END":
            quotes.pop()
    return problems


@pytest.mark.parametrize("src, bad", [
    ('x = f"{d.get("k")}"\n', True),
    ("x = f'{d.get('k')}'\n", True),
    ('x = f"{d.get(\'k\')}"\n', False),
    ('x = f"""{d.get("k")}"""\n', False),
    ('x = f"{a!r:>{w}}"\n', False),
    ('x = f"{f\'{a}\'}"\n', False),
    ('x = f"{f"{a}"}"\n', True),
    ("x = f\"{f'say \"hi\"'}\"\n", True),
    ('x = f"{chr(10)}" + "\\n"\n', False),
])
def test_the_checker_matches_the_pre_312_grammar(src: str, bad: bool) -> None:
    assert bool(pre_312_fstring_problems(src)) is bad


def test_no_source_needs_python_312_fstrings() -> None:
    found = []
    for path in _sources():
        with open(path, encoding="utf-8") as f:
            for line, problem in pre_312_fstring_problems(f.read()):
                found.append(f"{os.path.relpath(path, ROOT)}:{line}: {problem}")
    assert not found, "\n".join(found)
