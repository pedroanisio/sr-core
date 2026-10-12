"""Public docstring coverage of sr_core does not fall (doc-hygiene audit, 2026-10-12: 99 of 299, 33 %).

Raise FLOOR when it rises. The generated SDK (sr_core/scene/_generated.py) is excluded.
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 0.33
WORST_MODULES = ["vpkg/pack.py", "review/scene.py", "review/pdf.py", "review/cli.py", "schemadoc/html.py"]


def _public(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_")]


def _files():
    for base, _, names in os.walk(os.path.join(ROOT, "sr_core")):
        for n in names:
            if n.endswith(".py") and n != "_generated.py":
                yield os.path.join(base, n)


def test_public_docstring_coverage_does_not_fall():
    total = documented = 0
    for f in _files():
        nodes = _public(f)
        total += len(nodes)
        documented += sum(1 for n in nodes if ast.get_docstring(n))
    assert documented / total >= FLOOR, f"{documented}/{total} = {documented / total:.2f} < {FLOOR}"


def test_the_five_modules_audited_as_worst_have_every_public_docstring():
    bare = [f"{m}:{n.lineno} {n.name}" for m in WORST_MODULES for n in _public(os.path.join(ROOT, "sr_core", m))
            if not ast.get_docstring(n)]
    assert bare == []
