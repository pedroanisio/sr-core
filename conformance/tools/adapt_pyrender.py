#!/usr/bin/env python3
"""Adapt a scene authored for py-render's shader effects to the Rust scene-render.

  python3 adapt_pyrender.py SCENE.xml [--out SCENE.rust.xml]

The two renderers agree on the scene format and its spatial conventions (CONVENTIONS.md), but their custom
shader effects differ; this rewrites only the shader effects, in a copy:

- sources: `data:` URIs become local files (shaders/<effect id>.glsl), which the Rust renderer requires;
- conventions: py-render accepts Shadertoy code (`mainImage`, `iTime`, `iResolution`) and plain `void main()`
  code (`uv`, `inputTexture`, `fragColor`); both are wrapped in the Rust convention `vec4 effect(vec2 uv)`
  reading `getColor(uv)` (bottom-left origin in both renderers);
- colour: py-render hands the shader straight colour in the effect's @space (default srgb, display-encoded) —
  the same as Rust's getColor for srgb; for a linear @space the wrapper decodes the input and encodes the
  output so the shader still sees and produces linear values;
- animation: py-render animates `<param>` uniforms; Rust reads params as constants, so each animated param
  becomes a GLSL function of `time` (composition time) with the same keys and interpolation.
The original scene is never modified.
"""
import argparse
import base64
import os
import re
import sys

from lxml import etree

LINEAR_SPACES = {"linear-srgb", "linear", "acescg", "aces2065-1"}
SRGB_HELPERS = """
float sr_dec(float x){return x<=0.04045?x/12.92:pow((x+0.055)/1.055,2.4);}
float sr_enc(float x){x=max(x,0.);return x<=0.0031308?12.92*x:1.055*pow(x,1./2.4)-0.055;}
vec3 sr_dec3(vec3 c){return vec3(sr_dec(c.r),sr_dec(c.g),sr_dec(c.b));}
vec3 sr_enc3(vec3 c){return vec3(sr_enc(c.r),sr_enc(c.g),sr_enc(c.b));}
"""


def f(v):
    return f"{float(v):.6f}"


def ease(kind, u):
    """GLSL easing for u in [0, 1] (per scene-render key interpolation names)."""
    if kind in ("linear", None):
        return u
    if kind == "hold":
        return "0.0"
    if kind in ("sine-in-out",):
        return f"(0.5 - 0.5 * cos(3.14159265 * {u}))"
    if kind in ("ease-in-out", "smooth", "smoothstep"):
        return f"({u} * {u} * (3.0 - 2.0 * {u}))"
    if kind == "ease-in":
        return f"({u} * {u})"
    if kind == "ease-out":
        return f"(1.0 - (1.0 - {u}) * (1.0 - {u}))"
    sys.exit(f"unsupported interpolation {kind!r}")


def curve_fn(name, anim):
    if anim.get("timeBase", "composition") != "composition":
        sys.exit(f"animated param {name}: only timeBase=composition is supported")
    default = anim.get("defaultInterpolation")
    keys = sorted((float(k.get("time")), float(k.get("value")), k.get("interpolation") or default) for k in anim.findall("key"))
    lines = [f"float kf_{name}(float t) {{", f"  if (t <= {f(keys[0][0])}) return {f(keys[0][1])};"]
    for (t0, v0, it), (t1, v1, _) in zip(keys, keys[1:]):
        lines.append(f"  if (t < {f(t1)}) {{ float u = (t - {f(t0)}) / {f(t1 - t0)}; return mix({f(v0)}, {f(v1)}, {ease(it, 'u')}); }}")
    lines += [f"  return {f(keys[-1][1])};", "}"]
    return "\n".join(lines)


def source_of(eff, base):
    src = eff.get("src", "")
    if src.startswith("data:"):
        head, _, body = src.partition(",")
        return base64.b64decode(body).decode() if ";base64" in head else body
    return open(os.path.join(base, src)).read()


def adapt_shader(eff, code):
    linear = (eff.get("space") or "srgb") in LINEAR_SPACES
    anims = {a.get("property"): a for a in eff.findall("animate")}
    fns = []
    for name, a in anims.items():
        code = re.sub(rf"^\s*uniform\s+\w+\s+{name}\s*;[^\n]*$", "", code, flags=re.M)
        fns.append(curve_fn(name, a))
        eff.remove(a)
        for p in eff.findall("param"):
            if p.get("name") == name:
                eff.remove(p)
    head = "// Adapted from py-render's shader convention for the Rust scene-render (tools/adapt_pyrender.py).\n"
    head += SRGB_HELPERS + "\n".join(fns) + "\n" + "".join(f"#define {n} (kf_{n}(time))\n" for n in anims)
    if "mainImage" in code:
        body = "#define iTime time\n#define iResolution vec3(resolution, 1.0)\n" + code
        out = "vec4(sr_enc3(c.rgb), clamp(c.a, 0.0, 1.0))" if linear else "vec4(c.rgb, clamp(c.a, 0.0, 1.0))"
        tail = f"\nvec4 effect(vec2 sr_p) {{\n  vec4 c = vec4(0.0);\n  mainImage(c, sr_p * resolution);\n  return {out};\n}}\n"
        return head + body + tail
    if re.search(r"void\s+main\s*\(\s*\)", code):
        body = re.sub(r"^\s*(in\s+vec2\s+uv|out\s+vec4\s+fragColor|uniform\s+sampler2D\s+[\w\s,]+)\s*;[^\n]*$", "", code, flags=re.M)
        if "sourceTexture" in body:
            sys.exit(f"effect {eff.get('id')}: sourceTexture has no Rust equivalent")
        body = re.sub(r"texture\s*\(\s*inputTexture\s*,", "sr_in(", body)
        body = re.sub(r"void\s+main\s*\(\s*\)", "void sr_user_main()", body)
        sample = "vec4 s = getColor(p); return vec4(sr_dec3(s.rgb), s.a);" if linear else "return getColor(p);"
        glue = f"vec2 uv;\nvec4 fragColor;\nvec4 sr_in(vec2 p) {{ {sample} }}\n"
        out = "vec4(sr_enc3(fragColor.rgb), clamp(fragColor.a, 0.0, 1.0))" if linear else "vec4(fragColor.rgb, clamp(fragColor.a, 0.0, 1.0))"
        tail = f"\nvec4 effect(vec2 sr_p) {{\n  uv = sr_p;\n  fragColor = vec4(0.0);\n  sr_user_main();\n  return {out};\n}}\n"
        return head + glue + body + tail
    if "effect(" in code:
        return None  # already in the Rust convention
    sys.exit(f"effect {eff.get('id')}: unrecognised shader convention")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--out")
    a = ap.parse_args()
    src = os.path.abspath(a.scene)
    base = os.path.dirname(src)
    dst = os.path.abspath(a.out) if a.out else src.replace(".scene.xml", ".rust.scene.xml").replace("scene.xml", "scene.rust.xml") if not src.endswith(".rust.scene.xml") else src
    if dst == src:
        sys.exit("refusing to overwrite the source scene; pass --out")
    tree = etree.parse(src)
    os.makedirs(os.path.join(base, "shaders"), exist_ok=True)
    n = 0
    for eff in tree.getroot().iter("effect"):
        if eff.get("type") != "shader":
            continue
        code = adapt_shader(eff, source_of(eff, base))
        if code is None:
            continue
        path = os.path.join("shaders", eff.get("id") + ".glsl")
        open(os.path.join(base, path), "w").write(code)
        eff.set("src", path)
        n += 1
    tree.write(dst, xml_declaration=True, encoding="UTF-8")
    print(f"adapted {n} shader effect(s) -> {os.path.relpath(dst, base)}")


if __name__ == "__main__":
    main()
