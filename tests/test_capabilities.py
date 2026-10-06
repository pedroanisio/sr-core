"""SREP 22 and 63: the capability manifest format, schema/capabilities-1.schema.json.

The JSON Schema uses a small subset of draft 2020-12 (type, const, enum, pattern, minLength, minItems, required,
properties, additionalProperties, items, $ref to $defs); this file checks manifests against it with a validator of
that subset, so sr-core stays free of dependencies.
"""
import json
import os
import re

import pytest

from test_schema_rules import ROOT

SCHEMA = json.load(open(os.path.join(ROOT, "schema", "capabilities-1.schema.json")))
TYPES = {"object": dict, "array": list, "string": str}


def errors(value, schema, path="$"):
    if "$ref" in schema:
        schema = SCHEMA["$defs"][schema["$ref"].split("/")[-1]]
    out = []
    if "type" in schema and not isinstance(value, TYPES[schema["type"]]):
        return [f"{path}: not {schema['type']}"]
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append(f"{path}: too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, dict):
        out += [f"{path}: lacks {k}" for k in schema.get("required", []) if k not in value]
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                out += errors(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}: unknown {k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            out.append(f"{path}: fewer than {schema['minItems']} items")
        for i, v in enumerate(value):
            out += errors(v, schema.get("items", {}), f"{path}[{i}]")
    return out


def manifest(*entries):
    return {"format": "scene-render-capabilities/1", "engine": {"name": "e", "version": "1.0.0"}, "schema": "1.5.0",
            "entries": list(entries)}


def test_the_examples_of_sreps_22_and_63_validate():
    srep22 = manifest({"construct": "particleEmitter", "status": "unsupported"},
                      {"construct": "layer/@frameBlend=optical-flow", "status": "reported", "definition": "D20"},
                      {"construct": "effect/@type=glow", "status": "approximate", "note": "bloom radius capped at 64 px"})
    assert errors(srep22, SCHEMA) == []
    srep63 = manifest({"construct": "object3D/@shadowCatcher=true", "status": "reported",
                       "when": ["camera/@renderer=pathtrace"], "note": "the path tracer draws no shadow catcher"})
    assert errors(srep63, SCHEMA) == []


@pytest.mark.parametrize("entry", [
    {"construct": "shape", "status": "partial"},
    {"construct": "shape/@fill=", "status": "exact"},
    {"construct": "shape/fill", "status": "exact"},
    {"construct": "shape", "status": "exact", "when": []},
    {"construct": "shape", "status": "exact", "when": ["camera renderer"]},
    {"construct": "shape", "status": "exact", "since": "1.0"},
    {"status": "exact"},
])
def test_bad_entries_are_rejected(entry):
    assert errors(manifest(entry), SCHEMA) != []


def test_the_manifest_names_its_format_and_schema():
    m = manifest()
    assert errors(m, SCHEMA) == []
    assert errors({**m, "format": "scene-render-capabilities/2"}, SCHEMA) != []
    assert errors({**m, "schema": "1.5"}, SCHEMA) != []
