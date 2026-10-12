"""Regression tests for the MODERATE findings 10 to 13 of the drift-risk map.

10  the capability-manifest schema against the code that reads it (sr_core/scene/engine.py) and the subset validator
11  counts quoted in prose against the schema
12  the engine-gap inventory against the SREP diff blocks it was measured for
13  the dependencies CI installs against the extras and the imports of the tests
"""
import ast
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "conformance", "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from sr_core.scene import _generated as gen  # noqa: E402
from sr_core.scene import engine  # noqa: E402

XS = "{http://www.w3.org/2001/XMLSchema}"


def read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


# --------------------------------------------------------------------------------------------------------------- 10
CAPS = json.loads(read("schema", "capabilities-1.schema.json"))
SUBSET = {"$schema", "$id", "title", "description", "type", "const", "enum", "pattern", "minLength", "minItems",
          "required", "properties", "additionalProperties", "items", "$ref", "$defs"}


def _keywords(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            if k in ("properties", "$defs"):
                for sub in v.values():
                    yield from _keywords(sub)
            elif k in ("items", "additionalProperties"):
                yield from _keywords(v)
    elif isinstance(node, list):
        for x in node:
            yield from _keywords(x)


def test_the_engine_reads_the_format_the_schema_names():
    assert engine.CAPABILITIES_FORMAT == CAPS["properties"]["format"]["const"]


def test_the_schema_stays_inside_the_subset_the_test_validator_implements():
    """tests/test_capabilities.py checks manifests with a hand-written validator of a keyword subset. A keyword it
    does not implement would be ignored, and the schema would pass what it should refuse."""
    outside = sorted({k for k in _keywords(CAPS) if isinstance(k, str)} - SUBSET)
    assert outside == []


def test_the_fields_engine_info_reads_are_required_by_the_schema():
    src = read("sr_core", "scene", "engine.py")
    read_keys = set(re.findall(r'manifest\["(\w+)"\]', src))
    assert read_keys == {"format", "engine", "schema"}
    assert read_keys <= set(CAPS["required"])
    assert set(re.findall(r'manifest\["engine"\]\["(\w+)"\]', src)) <= set(CAPS["properties"]["engine"]["required"])


def test_engine_info_accepts_a_manifest_of_the_schema_shape(tmp_path):
    exe = tmp_path / "eng"
    manifest = {"format": CAPS["properties"]["format"]["const"], "engine": {"name": "e", "version": "1.2.3"},
                "schema": "1.7.0", "entries": []}
    exe.write_text(f"#!{sys.executable}\nimport json,sys\nprint(json.dumps({manifest!r}))\n")
    exe.chmod(0o755)
    info = engine.engine_info(exe)
    assert (info.name, info.version, info.schema) == ("e", "1.2.3", "1.7.0")


# --------------------------------------------------------------------------------------------------------------- 11
def _xsd_counts():
    root = ET.parse(os.path.join(ROOT, "schema", "scene-render.xsd")).getroot()
    sch = read("schema", "scene-render.sch")
    return {
        "complex types": len(list(root.iter(XS + "complexType"))),
        "simple types": len([c for c in root.iter(XS + "simpleType") if c.get("name")]),
        "distinct attribute names": len({a.get("name") for a in root.iter(XS + "attribute") if a.get("name")}),
        "Schematron asserts": len(re.findall(r"<(?:sch:)?assert\b", sch)),
    }


def test_the_generated_counts_are_the_schemas():
    c = _xsd_counts()
    assert gen.COUNTS["complex_types"] == c["complex types"]
    assert gen.COUNTS["simple_types"] == c["simple types"]


def test_counts_quoted_in_prose_are_the_schemas():
    c = _xsd_counts()
    srep = read("srep", "srep-0000-python-scene-sdk.md")
    quoted = re.search(r"has (\d+) complex types, (\d+) simple types, (\d+) distinct attribute names and (\d+) "
                       r"Schematron asserts", srep)
    assert quoted, "the sentence of SREP 0000 that quotes the schema's size was reworded: update this test"
    assert tuple(map(int, quoted.groups())) == (c["complex types"], c["simple types"],
                                                c["distinct attribute names"], c["Schematron asserts"])
    gates = re.search(r"At [\d.]+ all (\d+) gate asserts fit the subset", srep)
    assert gates and int(gates.group(1)) == gen.COUNTS["gate_asserts"]
    unreleased = read("CHANGELOG.md").split("\n## 1.", 1)[0]
    for m in re.finditer(r"all (\d+) complex types", unreleased):
        assert int(m.group(1)) == c["complex types"]


# --------------------------------------------------------------------------------------------------------------- 12
def test_the_inventory_names_the_engine_commit_and_the_baseline_it_was_measured_against():
    import engine_gap as g
    inv = json.load(open(g.DEFAULT_OUT))
    assert re.fullmatch(r"[0-9a-f]{40}", inv["engine"]["commit"])
    assert inv["engine"]["commit"].startswith(inv["engine"]["ref"])
    assert re.fullmatch(r"[0-9a-f]{40}", inv["base"]["commit"])


def test_verify_notices_an_edited_diff_block(monkeypatch):
    """The inventory is only as good as the diff blocks of SREPs 76 to 81. Changing one line of any block must make
    `verify` report it, or the blocks could drift from the engine text unseen."""
    import engine_gap as g
    assert g.verify() == []
    real = g.srep_patches

    def edited():
        blocks = list(real())
        n, block = blocks[0]
        added = [i for i, ln in enumerate(block.split("\n")) if ln.startswith("+") and not ln.startswith("+++")]
        assert added, "the first diff block adds nothing"
        lines = block.split("\n")
        lines[added[0]] += " EDITED"
        blocks[0] = (n, "\n".join(lines))
        return blocks

    monkeypatch.setattr(g, "srep_patches", edited)
    assert g.verify() != []


# --------------------------------------------------------------------------------------------------------------- 13
# tests that switch themselves on with an environment variable and say which package that needs
OPT_IN = {"mypy"}


def _ci_installs():
    text = read(".github", "workflows", "ci.yml")
    m = re.search(r"pip install ([^\n]+)\n", text)
    assert m, "ci.yml no longer has the test-dependency pip install line"
    return set(m.group(1).split())


def _pyproject_extras():
    text = read("pyproject.toml")
    out = set()
    for name in ("test", "validate"):
        m = re.search(rf"^{name} = \[(.*?)\]", text, re.M)
        out |= set(re.findall(r'"([A-Za-z0-9_.-]+)', m.group(1)))
    return out


def test_ci_installs_every_extra_of_the_package():
    assert _pyproject_extras() <= _ci_installs()


def test_every_third_party_import_of_the_tests_is_installed_by_ci():
    local = {os.path.splitext(f)[0] for f in os.listdir(os.path.join(ROOT, "tests")) if f.endswith(".py")}
    local |= {"sr_core", "engine_gap", "kit_pending", "run", "make_cases", "release", "check_hygiene", "conftest"}
    local |= {os.path.splitext(f)[0] for d in ("tools", "conformance", os.path.join("conformance", "tools"))
              for f in os.listdir(os.path.join(ROOT, d)) if f.endswith(".py")}
    pip_name = {"PIL": "pillow", "lxml": "lxml", "numpy": "numpy", "pytest": "pytest", "setuptools": "setuptools",
                "wheel": "wheel", "pkg_resources": "setuptools", "_pytest": "pytest"}
    needed = {}
    tests = os.path.join(ROOT, "tests")
    for f in os.listdir(tests):
        if not f.endswith(".py"):
            continue
        source = open(os.path.join(tests, f), encoding="utf-8").read()
        # modules skipped when absent, or imported by a script a test writes out and runs: both pass silently
        for m in re.findall(r'importorskip\("(\w+)|(?:import|from) (numpy|PIL|lxml)\b', source):
            top = m[0] or m[1]
            if top not in local and top not in OPT_IN:
                needed.setdefault(top, f)
        for node in ast.walk(ast.parse(source)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                top = n.split(".")[0]
                if top in sys.stdlib_module_names or top in local or top in OPT_IN or top == "__future__":
                    continue
                needed.setdefault(top, f)
    installed = _ci_installs()
    missing = {m: f for m, f in needed.items() if pip_name.get(m, m) not in installed}
    assert missing == {}, f"imported by tests but not installed by ci.yml: {missing}"
