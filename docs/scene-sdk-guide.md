# Scene SDK guide

How to build, check and fix scene documents with `sr_core.scene` (Python) and `sr-scene` (command line). It is written
for people and for AI agents that write scenes: every rule below comes with the exact output the SDK gives, and every
Python block is executed by the test suite (`tests/test_scene_guide.py`).

The reference is [the SDK SREP](../srep/srep-0091.md); the schema is in [schema/](../schema/).

## 1. Install

```bash
pip install sr-core              # building, reading, writing and check level 1: standard library only
pip install "sr-core[validate]"  # adds lxml for level 2 (the XSD and the Schematron)
```

Three check levels exist: 1 is the SDK's own (required attributes, occurrences, ids, references, version gates), 2 runs
the bundled XSD and Schematron through lxml (`schema=True`), 3 runs an engine's `validate` (`engine=PATH`).

## 2. The loop: build, check, fix

```python
from sr_core.scene import Scene

scene = Scene(version="auto")                  # written as the lowest version the content allows
scene.add_project(width=1280, height=720, fps="30", duration=4)
composition = scene.add_composition()
layer = composition.add_layer()                # forgot the required attributes on purpose

for finding in scene.check():
    print(finding)
```

```text
error: xsd:required: /scene/composition/layer: <layer> needs the attribute 'id'
error: xsd:required: /scene/composition/layer: <layer> needs the attribute 'asset'
```

Read a finding as `severity: code: path: message`. The path is the element, in the form the engine uses
(`/scene/composition/layer[2]` is the second layer). Fix what the message says, then check again until the list is empty:

```python
from sr_core.scene import Scene

scene = Scene(version="auto")
scene.add_project(width=1280, height=720, fps="30", duration=4)
scene.add_assets().add_image(id="logo", src="logo.png", width=256, height=64)
layer = scene.add_composition().add_layer(id="title", asset="logo")
assert [f.code for f in scene.check()] == []   # nothing left to fix
data = scene.to_bytes(layout="pretty")         # UTF-8 bytes with the XML declaration
```

From the shell the same loop is `sr-scene check FILE` (exit 0 clean, 1 findings, 2 unreadable file), and
`sr-scene new -o scene.xml` starts from a document that is clean at levels 1 and 2.

## 3. Ask the schema, do not guess

Names are the schema's names: `layer.safeAreaForce`, `layer.rotationX`, `add_imageSequence`. The one change is the
attribute `from`, which is a Python keyword and is written `from_`. When you are not sure what an element takes, ask.

```python
from sr_core.scene import describe, element_names

d = describe("layer")                          # an XML name, a class, an instance or a class name ("Layer")
print(d.xml_names, d.class_name, d.min_version)
print([c.name for c in d.children][:3])
print([(a.python_name, a.type.name, a.required) for a in d.attributes][:3])
assert "layer" in element_names()
assert d.to_dict()["format"] == "sr-scene-describe/1"
```

```text
('layer',) Layer 1.0
['animate', 'expression', 'motionPath']
[('id', 'xs:ID', True), ('name', 'xs:string', False), ('tags', 'xs:NMTOKENS', False)]
```

`describe` returns a frozen record with, for the element, its documentation, minimum version, content model and children
(in order, with minimum and maximum occurrences, `None` meaning unbounded), and for each attribute its XML and Python
name, type, enumeration values, facets (bounds, patterns, lengths), default, whether it is required, the version it
needs when a gate names it, and its documentation. `describe(...).to_dict()` is plain JSON. A name that several classes
share (`point`) raises `AmbiguousNameError`; pass the class instead.

The same from the shell:

```bash
$ sr-scene list
$ sr-scene describe layer poster
$ sr-scene describe layer --format json
$ sr-scene describe --all --format json
$ sr-scene describe layr  # exit 2
```

`describe --all --format json` prints the whole schema on one line, without empty members, for a prompt or a tool;
section 8 gives its shape. An unknown name exits 2 and names the closest element:

```text
sr-scene: 'layr' is not an element or class name; did you mean 'layer'?
```

## 4. The errors the SDK gives

Everything the schema refuses raises a subclass of `SchemaValueError` the moment it is set, with the path of the element
and the attribute in the message. A name the schema does not have raises `UnknownNameError`, which is also an
`AttributeError`, so `hasattr(layer, "nope")` stays `False`. Its fields are `name`, `element`, `suggestions` and
`allowed`.

### A wrong attribute name

```python
# raises: UnknownNameError
from sr_core.scene import Layer

layer = Layer(id="title")
layer.blendMode = "multiply"
```

```text
<layer> has no attribute 'blendMode'; did you mean 'blend'? (allowed: id, name, tags, safeAreaForce, z, visible, opacity, start, end, shutterAngle, startMarker, endMarker, condition, motionBlur, matte, matteMode, matteVisible, edgeBlend, parent, threeD, zDepth, rotationX, rotationY, alignX, alignY, alignTo, margin, x, y, rotation, scaleX, scaleY, anchorX, anchorY, skewX, skewY, asset, blend, effects, clipIn, clipOut, loop, reverse, speed, timeStretch, freezeAt, frameBlend, resample, fit, boxWidth, boxHeight, focusX, focusY, cropLeft, cropTop, cropRight, cropBottom, flipX, flipY, stabilize, stabilizeSmoothness, volume, mute, audioBus)
```

The same error comes from a constructor keyword (`Layer(colour="#fff")`), from reading a missing attribute, and from
`default_of`. Suggestions cover another letter case (`Opacity`), a Python keyword (`from` for `from_`) and a name that
contains the right one (`blendMode` for `blend`). Catch it for its fields:

```python
from sr_core.scene import Layer, UnknownNameError

try:
    Layer(id="title", opacty=0.5)
except UnknownNameError as err:
    assert err.name == "opacty" and err.element == "layer"
    assert err.suggestions[0] == "opacity" and "opacity" in err.allowed
```

### A wrong factory name

```python
# raises: UnknownNameError
from sr_core.scene import Composition

Composition().add_layr(id="title")
```

```text
<composition> has no method 'add_layr'; did you mean 'add_layer'? (allowed: add_accretionDisk, add_adjustment, add_blackHole, add_camera, add_compute, add_connector, add_erosion, add_flock, add_fluid, add_group, add_include, add_instance, add_iterate, add_layer, add_object3D, add_ocean, add_particleEmitter, add_particles3D, add_program, add_repeat, add_sequence, add_shape, add_skeleton, add_slime, add_transition, add_viewport3D)
```

`add_<name>` exists only for the children the element allows; the allowed list is the answer to "what can go here".
Adding an existing element that does not belong (`Composition().add(Scene())`) gives
`/composition: <scene> is not allowed in <composition> (allowed: ...)`, with a `did you mean` when a name is close.

### A wrong value

```python
# raises: SchemaValueError
from sr_core.scene import Layer

Layer(id="title").opacity = 2
```

```text
/layer/@opacity: 2 violates maxInclusive 1.0 (unitDecimal)
```

(The path starts at the root of the tree the element is in: `/layer/@opacity` for a layer that is not in a document yet,
`/scene/composition/layer/@opacity` once it is.) Enumerations list every allowed value and, when a value is close, name it: `layer.blend = "mutliply"` ends with
`; did you mean 'multiply'?` (the error's `suggestions` holds it); compare with `describe("layer")`.

## 5. Values are lexical strings; layouts

The document stores text. An attribute takes the Python value you would expect, or a string in its lexical form; the
string is kept as written, so a document that was read is written back unchanged.

```python
from sr_core.scene import Layer

layer = Layer(id="title")
layer.opacity = 0.5                            # a float: written as 0.5
layer.opacity = "0.5000"                       # a lexical string: written as given
assert layer.opacity == 0.5                    # reading parses it
assert layer.attributes()["opacity"] == "0.5000"
layer.visible = False                          # booleans are written true / false
layer.tags = ["intro", "title"]                # a list type takes a sequence
layer.x = None                                 # None removes the attribute
```

Two traps. A type the schema declares as a string stays a string: `project(fps="30")`, not `fps=30` (the second is
refused with `expected str, got int 30`, `xs:string`). An element reference takes the id, or the element itself:
`layer.asset = image` writes `image`'s id, and fails if the element has none.

`to_bytes(layout=...)` takes `"preserve"` (the default: what was read is written back as it was), `"pretty"`
(re-indents and puts children in content-model order) and `"indent"` (keeps the order, indents where libxml2 would). Use
`sr-scene format FILE` to bring files to the pretty layout.

## 6. Version gates

A document declares `version="1.x"`; newer elements and attributes are refused at older versions. Three tools:

```python
from sr_core.scene import Scene, describe

scene = Scene(version="auto")                  # "auto" is accepted only through the API
scene.add_project(width=1280, height=720, fps="30", duration=4)
scene.add_assets().add_pdf(id="doc", src="a.pdf", cache="a.png", cacheSha256="0" * 64, width=100, height=100)
scene.add_composition()
assert scene.min_version() == "1.2"            # the lowest version that no gate refuses for this content
assert describe("pdf").min_version == "1.2"    # the element knows its own minimum
assert dict(next(a for a in describe("object3D").attributes if a.xml_name == "primitive").value_min_versions)[
    "capsule"] == "1.1"                        # so does a single enumeration value
scene.version = "1.0"
codes = [f.code for f in scene.check()]
assert "V9" in codes and "xsd:version" in codes
```

The finding for a gate carries the gate's own id (`V9`) and says what it needs: `pdf assets need version="1.2".`
`sr-scene min-version FILE` prints the lowest version of each file. `Scene(version="auto")` and `scene.version = "auto"`
are written as `min_version()`.

## 7. Findings and their codes

`Finding` has `severity` (`error`, `warning`, `info`), `code`, `message`, `path`, and `line` and `column` (set when the
document was read from a file). `sr-scene check FILE --format json` prints
`{"format": "sr-scene-findings/1", "valid": ..., "levels": [1], "files": [{"file": ..., "valid": ..., "findings": [...]}]}`
(`levels`: the check levels that ran; a clean file is reported as `ok (level 1)`, `ok (levels 1, 2)` ...); a finding
is the dict `{"severity", "code", "message", "path", "line", "column"}`.

| Code | Level | Meaning |
|---|---|---|
| `xsd:element` | 1 | The root is not `<scene>`, or an element is not allowed where it stands |
| `xsd:attribute` | 1 | The element has no such attribute, or the attribute is prohibited |
| `xsd:value` | 1 | An attribute or text is not valid for its type, or differs from the fixed value |
| `xsd:required` | 1 | A required attribute is missing |
| `xsd:occurs` | 1 | A child is out of order or too frequent, a required child is missing, or text where none is allowed |
| `xsd:id-unique` | 1 | Two elements carry the same id |
| `xsd:idref` | 1 | A reference names no id |
| `xsd:version` | 1 | `scene/@version` is not an allowed value, or is below the lowest version the content needs |
| `V1`, `V2`, ... `P3D1` | 1 | A version gate: the id of the Schematron assert that refuses the construct at this version |
| `xsd:schema` | 2 | The bundled XSD refused something level 1 did not name |
| `sdk:too-deep` | 2 | The document nests too deeply for lxml; level 1 still checked it |
| other Schematron ids | 2 | The id of the failed Schematron assert |
| `sdk:engine-failed` | 3 | The engine could not be run, timed out, or printed unusable output |
| `sdk:engine-version` | 3 | The engine implements an older schema than the document's version |
| `sdk:schema-skew` | 3 | Warning: the engine and this SDK come from different schema releases |
| other codes | 3 | The engine's own diagnostic codes, passed through |

Level 1 findings come first; a level 2 finding that level 1 already reported at the same path is dropped. Exit codes of
`sr-scene check`: 0 clean (warnings do not fail unless `--deny-warnings`), 1 errors, 2 a file cannot be read.

## 8. Formats

| Format | Where | Content |
|---|---|---|
| `sr-scene-describe/1` | `describe(...).to_dict()`, `describe_all()`, `sr-scene describe --format json` | the shape in `sr_core/scene/introspect.py` |
| `sr-scene-list/1` | `sr-scene list --format json` | `{"format", "schema_release", "elements": [{"name", "class_name", "summary", "min_version"}]}` |
| `sr-scene-findings/1` | `sr-scene check --format json` | section 7 |

`describe` returns one element in full: every type is spelled out. `describe_all()` and `sr-scene describe --all
--format json` return the compact form: `{"format", "schema_release", "versions", "types", "elements"}`, where an
attribute's `type` is a type name to look up in `types` (or a builtin such as `xs:double`), and members that are empty
are left out. The format string changes only when a reader of the old shape would break.

```python
import json

from sr_core.scene import describe_all

everything = describe_all()
text = json.dumps(everything, separators=(",", ":"))
layer = next(e for e in everything["elements"] if e["class_name"] == "Layer")
opacity = next(a for a in layer["attributes"] if a["xml_name"] == "opacity")
assert opacity["type"] == "unitDecimal" and everything["types"]["unitDecimal"]["facets"]["maxInclusive"] == "1"
assert json.loads(text) == everything
```

## 9. Common mistakes

| Mistake | What you see | Fix |
|---|---|---|
| `layer.blendMode`, `Layer(colour=...)` | `UnknownNameError`: `did you mean 'blend'?` | take the name from `describe("layer")` or `sr-scene describe layer` |
| `add_layr`, `add_clip` | `has no method 'add_layr'`; the allowed list | pick from the list, or `describe(parent).children` |
| a number where a string is declared (`fps=30`) | `expected str, got int 30 (xs:string)` | pass `"30"` |
| an enumeration value spelled differently | `'mutliply' is not one of 'normal', ...; did you mean 'multiply'?` | use the suggestion, or copy one of the listed values |
| a class name spelled differently (`sr_core.scene.Layr`, `S.textanimator`) | `UnknownNameError`: `has no class 'Layr'; did you mean 'Layer'?` (an `ImportError` in a `from` import) | take the name from `sr_core.scene.__all__`, or `describe("layer")` |
| a value out of its bounds | `2 violates maxInclusive 1.0 (unitDecimal)` | read the facets in `describe` |
| `from=` in a call | a syntax error | write `from_` |
| a newer element in an older document | `V9`, `xsd:version` | `Scene(version="auto")`, or raise the version |
| forgetting a required attribute | `xsd:required` at `check()`, not at construction | construct with the attributes `describe` marks `required` |
| `find("compositon")` | `None`, silently | take the name from `element_names()` |
| editing `_generated.py` | overwritten by the next generation | change `schema/`, then `python3 -m sr_core.scene.generate` |

## 10. The cost of a path-traced camera

A camera with `renderer="pathtrace"` traces `pathSamples` paths per pixel, and each path meets at most `maxBounces`
surfaces. The work of one frame is therefore bounded by width × height × `pathSamples` × `maxBounces`, and a video
multiplies that by its frame count. Raising both values at once multiplies the cost: 320 samples at 20 bounces is 25
times the work of the defaults, 64 samples at 4 bounces.

```python
from sr_core.scene import describe

camera = {a.xml_name: a for a in describe("camera").attributes}
assert (camera["pathSamples"].default, camera["maxBounces"].default) == ("64", "4")
assert dict(camera["pathSamples"].type.facets)["maxInclusive"] == "65536"
assert dict(camera["maxBounces"].type.facets)["maxInclusive"] == "64"
```

- **Start from the defaults.** The path-traced image is denoised unless `denoise="false"`. Raise `pathSamples` only
  when noise is still visible in a test frame.
- **Raise `maxBounces` to what a path has to cross.** Each surface a path meets uses one bounce. Seen from the side,
  a glass of water puts four surfaces in the way: into the glass, into the water, into the glass again and out of
  it, and one more bounce reaches what is behind. Count the surfaces in the view and set `maxBounces` a little above
  that count, not at the maximum.
- **Try a small frame first.** A test at a quarter of the width and height takes about a sixteenth of the work.
- **Read the engine's warnings.** At check level 3 the engine's own codes are passed through. scene-render warns
  with `W15` when one frame of a path-traced camera is more than 1920 × 1080 × 256 × 4 path segments, measured at
  the size of its `viewport3D` or else of the project.
