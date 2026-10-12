"""Version gates of the scene schema: extraction from the Schematron and native evaluation (SREP 0, section 5).

A *gate* is a Schematron assert that refuses constructs by ``scene/@version``. Two source forms are accepted:

* form A: the rule context is ``/scene[@version='a' or @version='b' ...]`` and the test is ``not(T)`` or
  ``count(P) <= n``;
* form B: the rule context is a construct pattern C (child steps, ``|`` unions, attribute predicates) and the test is
  ``not(/scene/@version='a' or /scene/@version='b' ...)``, optionally followed by ``or not(X)`` over C.

Triggers are compiled from a small XPath 1.0 subset: child (``/``) and descendant (``//``) steps, ``*``, ``.``,
``|`` unions, attribute predicates ``@a`` and ``@a='literal'`` combined with ``and`` / ``or`` / ``not()``, and
``count(path) <= n``. Anything else raises :class:`SchemaError`.

The evaluator needs only four members of an element: ``xml_name``, ``elements()``, ``owner`` and ``attributes()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from .errors import SchemaError

__all__ = ["Gate", "compile_gates", "fires", "refused_versions"]


class _ElementLike(Protocol):
    @property
    def xml_name(self) -> str: ...

    @property
    def owner(self) -> "_ElementLike | None": ...

    def elements(self) -> "list[Any]": ...

    def attributes(self) -> dict[str, str]: ...


# ---------------------------------------------------------------- tokenizer and parser of the XPath subset

_XML_SPACE = " \t\r\n"  # XPath white space is XML's (production S), not NBSP or another Unicode space
_XML_SPACE_RUN = re.compile("[ \t\r\n]+")
_TOK = re.compile(r"[ \t\r\n]*(//|/|\||\(|\)|\[|\]|<=|=|@|\*|'[^']*'|\d+(?:\.\d+)?|\.|[A-Za-z_][\w.\-]*)")
_NAME = re.compile(r"[A-Za-z_][\w\-]*$")

# Parsed forms (nested tuples):
#   step:  (axis, name, predicates)   axis in child | desc | self | attr
#   expr:  ("or"|"and", l, r) | ("not", e) | ("exists", union) | ("eq", union, literal)
#   union: ("union", [steps, ...])
_Step = tuple[str, "str | None", list[Any]]
_Steps = list[_Step]


def _tokens(s: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(s):
        m = _TOK.match(s, i)
        if not m or m.end() == i:
            if s[i:].strip(_XML_SPACE) == "":
                break
            raise SchemaError(f"unsupported syntax near {s[i:i + 20]!r} in {s!r}")
        out.append(m.group(1))
        i = m.end()
    return out


class _Parser:
    """Recursive-descent parser for the subset; every departure from it raises SchemaError."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.t = _tokens(text)
        self.i = 0

    def fail(self, why: str) -> SchemaError:
        return SchemaError(f"{why} in {self.text!r}")

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want: str | None = None) -> str:
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise self.fail(f"expected {want!r}, got {tok!r}")
        self.i += 1
        return tok

    def done(self) -> None:
        if self.peek() is not None:
            raise self.fail(f"unsupported trailing syntax {self.t[self.i:]}")

    def expr(self) -> Any:
        node = self.and_()
        while self.peek() == "or":
            self.take()
            node = ("or", node, self.and_())
        return node

    def and_(self) -> Any:
        node = self.unary()
        while self.peek() == "and":
            self.take()
            node = ("and", node, self.unary())
        return node

    def unary(self) -> Any:
        tok = self.peek()
        nxt = self.t[self.i + 1] if self.i + 1 < len(self.t) else None
        if tok == "not" and nxt == "(":
            self.take()
            self.take("(")
            e = self.expr()
            self.take(")")
            return ("not", e)
        if tok == "(":
            self.take()
            e = self.expr()
            self.take(")")
            return e
        if tok is not None and nxt == "(":
            raise self.fail(f"function {tok!r} is not supported (only not() and count())")
        path = self.union()
        if self.peek() == "=":
            self.take()
            lit = self.take()
            if not lit.startswith("'"):
                raise self.fail("comparison with a non-literal")
            for steps in path[1]:
                if len(steps) != 1 or steps[0][0] != "attr":
                    raise self.fail("only @attribute = 'literal' comparisons are supported")
            return ("eq", path, lit[1:-1])
        return ("exists", path)

    def count_le(self) -> tuple[str, Any, int]:
        """``count(union) <= n``, the whole text."""
        self.take("count")
        self.take("(")
        path = self.union()
        self.take(")")
        self.take("<=")
        num = self.take()
        if not num.isdigit():
            raise self.fail("count() must be compared with an integer literal")
        return ("count<=", path, int(num))

    def union(self) -> tuple[str, list[_Steps]]:
        paths = [self.path()]
        while self.peek() == "|":
            self.take()
            paths.append(self.path())
        return ("union", paths)

    def path(self) -> _Steps:
        steps: _Steps = []
        axis = "child"
        if self.peek() in ("/", "//"):
            raise self.fail("absolute path in a trigger")
        while True:
            tok = self.peek()
            nxt = self.t[self.i + 1] if self.i + 1 < len(self.t) else None
            if tok == ".":
                self.take()
                steps.append(("self", None, []))
            elif tok == "@":
                self.take()
                steps.append(("attr", self.name(), []))
            elif tok == "*" or (tok is not None and re.match(r"[A-Za-z_]", tok) and tok not in ("or", "and")):
                if nxt == "(":
                    raise self.fail(f"function {tok!r} is not supported (only not() and count())")
                name = self.take()
                preds: list[Any] = []
                while self.peek() == "[":
                    self.take("[")
                    p = self.expr()
                    self.take("]")
                    self.check_predicate(p)
                    preds.append(p)
                steps.append((axis, name, preds))
            else:
                raise self.fail(f"unsupported step {tok!r}")
            nxt = self.peek()
            if nxt == "/":
                self.take()
                axis = "child"
            elif nxt == "//":
                self.take()
                axis = "desc"
            else:
                self.check_attr_last(steps)
                return steps

    def name(self) -> str:
        tok = self.take()
        if not _NAME.match(tok):
            raise self.fail(f"unsupported name {tok!r}")
        return tok

    def check_attr_last(self, steps: _Steps) -> None:
        if any(s[0] == "attr" for s in steps[:-1]):
            raise self.fail("an attribute step must be the last step of a path")

    def check_predicate(self, e: Any) -> None:
        """Predicates are @a, @a='literal' and and / or / not() over them."""
        op = e[0]
        if op in ("or", "and"):
            self.check_predicate(e[1])
            self.check_predicate(e[2])
        elif op == "not":
            self.check_predicate(e[1])
        elif op in ("exists", "eq"):
            for steps in e[1][1]:
                if len(steps) != 1 or steps[0][0] != "attr":
                    raise self.fail("predicates may only test attributes (@a, @a='literal')")
        else:  # pragma: no cover - the parser produces only the ops above
            raise self.fail(f"unsupported predicate {op!r}")


def _parse_expr(text: str) -> Any:
    p = _Parser(text)
    e = p.expr()
    p.done()
    return e


# ---------------------------------------------------------------- evaluation

def _descendants(n: _ElementLike) -> list[_ElementLike]:
    out: list[_ElementLike] = []
    stack = list(reversed(n.elements()))
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(reversed(c.elements()))
    return out


def _ev_path(steps: _Steps, ctx: _ElementLike) -> list[Any]:
    nodes: list[Any] = [ctx]
    for axis, name, preds in steps:
        nxt: list[Any] = []
        for n in nodes:
            if isinstance(n, str):
                continue
            if axis == "self":
                nxt.append(n)
            elif axis == "attr":
                attrs = n.attributes()
                if name in attrs:
                    nxt.append(attrs[name])
            else:
                cands = n.elements() if axis == "child" else _descendants(n)
                for c in cands:
                    if (name == "*" or c.xml_name == name) and all(_truth(p, c) for p in preds):
                        nxt.append(c)
        nodes = nxt
    return nodes


def _ev_union(u: tuple[str, list[_Steps]], ctx: _ElementLike) -> list[Any]:
    out: list[Any] = []
    for steps in u[1]:
        out += _ev_path(steps, ctx)
    return out


def _truth(e: Any, ctx: _ElementLike) -> bool:
    op = e[0]
    if op == "or":
        return _truth(e[1], ctx) or _truth(e[2], ctx)
    if op == "and":
        return _truth(e[1], ctx) and _truth(e[2], ctx)
    if op == "not":
        return not _truth(e[1], ctx)
    if op == "exists":
        return bool(_ev_union(e[1], ctx))
    if op == "eq":
        return any(n == e[2] for n in _ev_union(e[1], ctx))
    if op == "count<=":
        return len(_ev_union(e[1], ctx)) <= e[2]
    raise AssertionError(f"unknown compiled op {op!r}")  # pragma: no cover


def _matches_pattern(steps: _Steps, el: _ElementLike) -> bool:
    """XSLT pattern of child steps: ``el`` matches the last step, its owner the one before, and so on."""
    node: _ElementLike | None = el
    for axis, name, preds in reversed(steps):
        if node is None or axis != "child" or (name != "*" and node.xml_name != name):
            return False
        if not all(_truth(p, node) for p in preds):
            return False
        node = node.owner
    return True


# ---------------------------------------------------------------- the gate

_VERS_CTX = re.compile(r"^/scene\[(@version='[\d.]+'(?: or @version='[\d.]+')*)\]$")
_VERS_TEST = re.compile(r"^not\((/scene/@version='[\d.]+'(?: or /scene/@version='[\d.]+')*)\)(?: or (.+))?$", re.S)


def _norm(s: str) -> str:
    return _XML_SPACE_RUN.sub(" ", s).strip(" ")


@dataclass(frozen=True)
class Gate:
    """One version gate: the constructs a Schematron assert refuses at the versions in ``versions``.

    ``context`` and ``trigger`` are the source strings of the rule context and the assert test. The compiled forms
    ``_ctx`` and ``_test`` are built from them on construction, so a generated module can hold plain ``Gate(...)``
    calls. ``form`` is ``"A"`` or ``"B"`` (module docstring).
    """

    id: str
    versions: frozenset[str]
    context: str
    trigger: str
    message: str
    form: str
    _ctx: Any = field(init=False, repr=False, compare=False, default=None)
    _test: Any = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        trigger = _norm(self.trigger)
        context = _norm(self.context)
        if self.form == "A":
            m = _VERS_CTX.match(context)
            if not m:
                raise SchemaError(f"{self.id}: form A needs context /scene[@version='..' or ...], got {self.context!r}")
            declared = frozenset(re.findall(r"'([\d.]+)'", m.group(1)))
            p = _Parser(trigger)
            if p.peek() == "count":
                body: Any = p.count_le()
                p.done()
                test: Any = ("A-count", body)
            else:
                body = p.expr()
                p.done()
                if body[0] != "not":
                    raise SchemaError(f"{self.id}: form A test must be not(T) or count(P) <= n, got {self.trigger!r}")
                test = ("A-not", body[1])
            ctx: Any = None
        elif self.form == "B":
            m = _VERS_TEST.match(trigger)
            if not m:
                raise SchemaError(f"{self.id}: form B needs test not(/scene/@version='..' or ...) [or not(X)], "
                                  f"got {self.trigger!r}")
            declared = frozenset(re.findall(r"'([\d.]+)'", m.group(1)))
            cond = None
            if m.group(2):
                rest = _parse_expr(m.group(2))
                if rest[0] != "not":
                    raise SchemaError(f"{self.id}: form B remainder must be not(X), got {m.group(2)!r}")
                cond = rest[1]
            pp = _Parser(context)
            union = pp.union()
            pp.done()
            for steps in union[1]:
                if any(axis != "child" for axis, _, _ in steps):
                    raise SchemaError(f"{self.id}: form B context must use child steps only, got {self.context!r}")
            ctx = tuple(tuple(steps) for steps in union[1])
            test = cond
        else:
            raise SchemaError(f"{self.id}: gate form must be 'A' or 'B', got {self.form!r}")
        if frozenset(self.versions) != declared:
            raise SchemaError(f"{self.id}: versions {sorted(self.versions)} do not match the source text {sorted(declared)}")
        object.__setattr__(self, "versions", frozenset(self.versions))
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_test", test)


def compile_gates(schema: Any) -> tuple[Gate, ...]:
    """Extract every version-gate assert of ``schema.rules``, in schema order.

    Any assert that mentions ``@version`` (in its rule context or its test) but does not fit form A or B raises
    :class:`SchemaError`.
    """
    out: list[Gate] = []
    for rule in schema.rules:
        context = _norm(rule.context)
        for a in rule.asserts:
            test = _norm(a.test)
            if "@version" not in context and "@version" not in test:
                continue
            if _VERS_CTX.match(context):
                form, versions = "A", re.findall(r"'([\d.]+)'", context)
            else:
                m = _VERS_TEST.match(test)
                if not m:
                    raise SchemaError(f"{a.id}: version gate not recognised: context {context!r}, test {test!r}")
                form, versions = "B", re.findall(r"'([\d.]+)'", m.group(1))
            try:
                out.append(Gate(id=a.id, versions=frozenset(versions), context=context, trigger=test,
                                message=a.message, form=form))
            except SchemaError as e:
                raise SchemaError(f"{a.id}: {e}") from e
    return tuple(out)


def fires(gate: Gate, root: Any) -> list[Any]:
    """The context elements where ``gate`` would fail if the document were labelled at one of ``gate.versions``.

    The document's own ``version`` attribute is ignored. Form A gates fire on the root (``scene``) element.
    """
    if gate.form == "A":
        if root.xml_name != "scene":
            return []
        kind, body = gate._test
        hit = _truth(body, root) if kind == "A-not" else not _truth(body, root)
        return [root] if hit else []
    hits: list[Any] = []
    stack = [root]
    while stack:
        el = stack.pop()
        if any(_matches_pattern(steps, el) for steps in gate._ctx) and (gate._test is None or _truth(gate._test, el)):
            hits.append(el)
        stack.extend(reversed(el.elements()))
    return hits


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def refused_versions(gates: Iterable[Gate], root: Any) -> dict[str, list[tuple[Gate, Any]]]:
    """Map each version some gate refuses to the ``(gate, element)`` pairs that fire there.

    Keys are every version named by any gate, in numeric order, and a clean version maps to an empty list. A version
    that no gate names is absent and therefore refused by nothing.
    """
    gates = tuple(gates)
    found = {g.id + "\0" + str(i): fires(g, root) for i, g in enumerate(gates)}
    out: dict[str, list[tuple[Gate, Any]]] = {}
    for v in sorted({v for g in gates for v in g.versions}, key=_version_key):
        out[v] = [(g, el) for i, g in enumerate(gates) if v in g.versions for el in found[g.id + "\0" + str(i)]]
    return out
