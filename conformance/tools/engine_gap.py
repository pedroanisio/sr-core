#!/usr/bin/env python3
"""The schema gap between the reference engine's vendored copy and sr-core, measured and checked (SREPs 76 to 81).

The engine vendors sr-core's XSD and Schematron and keeps extensions of its own in them. This tool lists every
declaration the engine has and sr-core lacks, groups them by feature, finds the engine commit that introduced each
one, splits the textual difference into one patch per SREP, and checks that the patches rebuild the engine's files
byte for byte.

  # measure (needs a clone of the engine): write the inventory and the per-SREP patches
  python3 conformance/tools/engine_gap.py measure --engine-repo ../rs-scene-render --engine-ref origin/main \\
      --base-ref schema-1.5.0 --exclude-ref origin/srep/drafts-2026-10 \\
      --out conformance/tools/engine-gap-1.5.0.json --patches <dir>

  # the same measurement, compared with the committed inventory; exit 1 on any difference
  python3 conformance/tools/engine_gap.py check --engine-repo ../rs-scene-render ... --out conformance/tools/engine-gap-1.5.0.json

  # offline: apply the diff blocks of SREPs 76 to 81 in order to the 1.5.0 files and compare the hashes
  python3 conformance/tools/engine_gap.py verify

A ```diff block of an SREP is the measured patch: the engine's text at the measured commit, which `verify` rebuilds byte
for byte. A ```diff amendment block is a later change the SREP makes to its own text (for example the engine's text on
a later branch). Amendments are not part of the measurement: `verify` ignores them, and `proposed_schema` applies them
after every measured block, each hunk where its removed and context lines occur exactly once.

An item is one declaration: in the XSD a named type, group or attribute group, an element or attribute declaration,
an enumeration value, or a documentation block; in the Schematron a pattern, rule, assert, report or let. Its key is
the path of named items that contain it, e.g. complexType[fractureType]/attribute[source]. An item is "added" when
its key is only in the engine, "changed" when both have it and its own content differs (attributes, facets, text;
not the items inside it), "removed" when only sr-core has it.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.parsers.expat

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_OUT = os.path.join(HERE, "engine-gap-1.5.0.json")

XS = "http://www.w3.org/2001/XMLSchema"
SCH = "http://purl.oclc.org/dsdl/schematron"
FILES = {  # sr-core path: engine path
    "schema/scene-render.xsd": "schema/scene-render-1.1.xsd",
    "schema/scene-render.sch": "schema/scene-render-1.1.sch",
}
ITEM_TAGS = {f"{{{XS}}}{t}" for t in ("complexType", "simpleType", "group", "attributeGroup", "element", "attribute",
                                      "enumeration", "documentation")} | \
            {f"{{{SCH}}}{t}" for t in ("pattern", "rule", "assert", "report", "let")}

# The features, in the order their SREPs apply. A key belongs to the first feature whose pattern matches it.
FEATURES = [
    ("black-hole", 76, "Schwarzschild black hole, accretion disk and geodesic camera",
     r"blackHoleType|accretionDiskType|element\[(blackHole|accretionDisk)\]|cameraType\]/attribute\[geodesics\]"
     r"|pattern\[cinematic-black-hole"),
    ("impact", 77, "Impacts: ejecta that become ground, fractures from a body, the density of water",
     r"craterType\]/attribute\[(mantle|bulking|repose)\]|craterType\]/documentation$|assert\[CRT(4|10|11|12)\]"
     r"|fractureType\]/attribute\[(source|minImpulse|energyFraction)\]|fractureType\]/documentation$|assert\[FRX[567]\]"
     r"|oceanType\]/attribute\[density\]"),
    ("pyro", 78, "Pyro: a window that follows the plume, and blasts",
     r"pyroType\]/attribute\[follow|pyroBlast|assert\[PYRO(9|10|11)\]|assert\[PYC[56]\]"),
    ("light", 79, "Multiple scattering in media, and foam in the water's albedo",
     r"mediumType\]/attribute\[scatterBounces\]|whitewaterType\]/attribute\[foam(Mode|Radius|Albedo|Roughness)\]"
     r"|assert\[OCN14\]"),
    ("voxels", 80, "Voxel assets, objects of cells and their physics",
     r"voxel|enumeration\[voxels\]"
     r"|rigidBody3DType\]/attribute\[(density|maxFragments|fragmentMinCells|fragmentOverflow|anchor)\]"
     r"|object3DType\]/attribute\[(cellSize|palette|surface|surfaceMemoryMiB)\]|assert\[CRT(5|1[3-7])\]"
     r"|assert\[FRX(3|4|8|9|1\d)\]|fractureType\]/attribute\[(interiorMaterial|partition|planes|labels|mode|strength)\]"
     r"|burst3DType\]/attribute\[count\]|burst3DType\]/documentation$"),
    ("annotations", 81, "Documentation of SREP 40 attributes (no change of meaning)",
     r"attributeGroup\[pyroCrater\]/documentation$|particles3DType\]/attribute\[gas\]/documentation$"
     r"|burst3DType\]/attribute\[angle(Spread)?\]|assert\[P3D10\]|oceanType\]/attribute\[bodyDrag\]/documentation$"),
]
ORDER = [f[0] for f in FEATURES]
SREP_OF = {f[0]: f[1] for f in FEATURES}
BLANK_FEATURE = "annotations"     # whitespace-only lines carry no meaning; they ride with the documentation SREP

# A line two features change: the earlier feature's SREP carries the form the engine had when that feature was
# added (taken verbatim from the engine commit named here), the later one the final form.
INTERMEDIATE = {
    ("schema/scene-render.sch", 'id="FRX4"'): ("impact", "2820484"),
}


# ----------------------------------------------------------------------------------------------------- git and files
def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def git_bytes(repo: str, ref: str, path: str) -> bytes:
    return subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], check=True, capture_output=True).stdout


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------------------------------------------------ items
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def segment(el) -> str | None:
    t, a = _local(el.tag), el.attrib
    if t in ("complexType", "simpleType") and "name" not in a:
        return None
    if t == "enumeration":
        return f"enumeration[{a['value']}]"
    if t == "documentation":
        return "documentation"
    if t == "pattern":
        return f"pattern[{a.get('id')}]"
    if t == "rule":
        return f"rule[{a['context']}]"
    if t in ("assert", "report"):
        return f"{t}[{a['id']}]"
    if "name" in a:
        return f"{t}[{a['name']}]"
    if "ref" in a:
        return f"{t}[ref={a['ref']}]"
    return None


def is_item(el) -> bool:
    return isinstance(el.tag, str) and el.tag in ITEM_TAGS and segment(el) is not None


def key_of(el) -> str:
    parts, e = [], el
    while e is not None:
        if is_item(e):
            parts.append(segment(e))
        e = e.getparent()
    return "/".join(reversed(parts))


def own_content(el, root=True):
    """What an item says itself: its attributes, facets and text, without the items inside it."""
    if not isinstance(el.tag, str) or (not root and is_item(el)):
        return None
    t = _local(el.tag)
    if t == "documentation":
        return ["doc", el.text]
    kids = [c for c in (own_content(k, False) for k in el) if c is not None]
    text = el.text if t in ("assert", "report") else (el.text or "").strip()
    return [t, sorted(el.attrib.items()), kids, text]


def element_lines(data: bytes) -> list[tuple[int, int]]:
    """(first line, last line) of every element, in document order (1-based)."""
    spans, stack = [], []
    p = xml.parsers.expat.ParserCreate()

    def start(name, attrs):
        stack.append(len(spans))
        spans.append([p.CurrentLineNumber, None])

    def end(name):
        spans[stack.pop()][1] = p.CurrentLineNumber

    p.StartElementHandler, p.EndElementHandler = start, end
    p.Parse(data, True)
    return [tuple(s) for s in spans]


def items_of(data: bytes) -> dict:
    """key -> {"content", "lines": (first, last), "depth"}."""
    from lxml import etree
    root = etree.fromstring(data)
    elements = [e for e in root.iter() if isinstance(e.tag, str)]
    spans = element_lines(data)
    assert len(elements) == len(spans)
    out = {}
    for el, span in zip(elements, spans):
        if is_item(el):
            k = key_of(el)
            if k in out:
                raise SystemExit(f"duplicate item key {k}")
            out[k] = {"content": json.dumps(own_content(el)), "lines": span, "depth": k.count("/")}
    return out


def compare(base: dict, eng: dict) -> dict:
    status = {}
    for k, v in eng.items():
        if k not in base:
            status[k] = "added"
        elif base[k]["content"] != v["content"]:
            status[k] = "changed"
    for k in base:
        if k not in eng:
            status[k] = "removed"
    return status


def feature_of(key: str) -> str | None:
    for name, _, _, pattern in FEATURES:
        if re.search(pattern, key):
            return name
    return None


# --------------------------------------------------------------------------------------------- line atoms and stages
def line_features(lines: list[str], items: dict, status: dict) -> list[str | None]:
    """The feature of each line: the outermost added or changed item that spans it; blank lines are editorial."""
    feat: list[str | None] = [None] * len(lines)
    best: list[int] = [10 ** 9] * len(lines)
    for k, it in items.items():
        if status.get(k) not in ("added", "changed"):
            continue
        a, b = it["lines"]
        for n in range(a - 1, b):
            if it["depth"] < best[n]:
                best[n], feat[n] = it["depth"], feature_of(k)
    for n, line in enumerate(lines):
        if not line.strip():
            feat[n] = BLANK_FEATURE
    return feat


def fill(feats: list[str | None]) -> list[str]:
    """Lines no changed item spans (closing tags of unchanged containers) take the feature of the line before them,
    or of the line after at the start of a run."""
    out = list(feats)
    for n in range(len(out)):
        if out[n] is None and n > 0:
            out[n] = out[n - 1]
    for n in range(len(out) - 1, -1, -1):
        if out[n] is None and n + 1 < len(out):
            out[n] = out[n + 1]
    if any(f is None for f in out):
        raise SystemExit(f"cannot place lines {feats}")
    return out


LINE_KEY = re.compile(r'\b(?:id|name|value|context)="([^"]+)"')


def depth_ok(lines: list[str]) -> bool:
    """Whether a run of lines opens and closes its own tags (comments ignored)."""
    d = 0
    for line in lines:
        line = re.sub(r"<!--.*?-->", "", line)
        for m in re.finditer(r"<(/?)([A-Za-z][\w:.-]*)[^<>]*?(/?)>", line):
            if m.group(1):
                d -= 1
            elif not m.group(3):
                d += 1
            if d < 0:
                return False
    return d == 0


def atoms_for(base: list[str], eng: list[str], fb: list, fe: list) -> list[dict]:
    """Split the line difference into atoms of one feature each. An atom replaces base[i1:i2] (empty for an
    insertion) by engine lines; atoms at one base position keep the engine's order."""
    sm = difflib.SequenceMatcher(None, base, eng, autojunk=False)
    ops = [list(o) for o in sm.get_opcodes()]
    atoms: list[dict] = []
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            continue
        e_feats = fill(fe[j1:j2]) if j2 > j1 else []
        b_feats = [f for f in fb[i1:i2] if f is not None]
        feats = set(e_feats) | set(b_feats)
        if not feats and i2 > i1:     # pure deletion of lines no item owns
            feats = {BLANK_FEATURE} if all(not l.strip() for l in base[i1:i2]) else set()
        if len(feats) == 1:
            atoms.append({"i1": i1, "i2": i2, "lines": eng[j1:j2], "feature": feats.pop()})
            continue
        # mixed: pair replaced lines by their id/name, then cut the insertions between them by feature
        pairs, jj = [], j1
        for i in range(i1, i2):
            m = LINE_KEY.search(base[i])
            hit = next((j for j in range(jj, j2) if m and LINE_KEY.search(eng[j]) and
                        LINE_KEY.search(eng[j]).group(1) == m.group(1)), None)
            if hit is None:
                raise SystemExit(f"cannot pair base line {i + 1} in a mixed change: {base[i][:80]}")
            pairs.append((i, hit))
            jj = hit + 1
        runs, cursor = [], j1
        for i, j in pairs + [(i2, j2)]:
            if j > cursor:
                runs.append((i, cursor, j))           # insertion before base line i
            if i < i2:
                runs.append(("pair", i, j))
            cursor = j + 1
        local = fill(fe[j1:j2])
        for r in runs:
            if r[0] == "pair":
                _, i, j = r
                atoms.append({"i1": i, "i2": i + 1, "lines": [eng[j]], "feature": local[j - j1]})
                continue
            at, a, b = r
            segs: list[list] = []
            for j in range(a, b):
                f = local[j - j1]
                if segs and segs[-1][0] == f:
                    segs[-1][2] = j + 1
                else:
                    segs.append([f, j, j + 1])
            # a closing run of a container that the diff matched to a later copy: rotate it so that each feature's
            # run is a whole element (the engine's text is unchanged; only which equal lines are matched moves)
            nxt = ops[n + 1] if n + 1 < len(ops) and at == i2 else None
            if len(segs) > 1 and not all(depth_ok(eng[s:e]) for _, s, e in segs):
                done = False
                for idx, (f, s, e) in enumerate(segs[:-1]):
                    k = next((k for k in range(1, min(8, e - s)) if depth_ok(eng[s:e - k])), None)
                    if not (k and nxt and nxt[0] == "equal" and nxt[2] - nxt[1] >= k and eng[e - k:e] == eng[b:b + k]):
                        continue
                    # eng[e-k:e] now match base[at:at+k]; what followed them is inserted after those base lines,
                    # and the lines after the change (equal to the rotated ones) close the last run
                    for f2, s2, e2 in segs[:idx]:
                        atoms.append({"i1": at, "i2": at, "lines": eng[s2:e2], "feature": f2})
                    atoms.append({"i1": at, "i2": at, "lines": eng[s:e - k], "feature": f})
                    rest = segs[idx + 1:]
                    for n2, (f2, s2, e2) in enumerate(rest):
                        tail = eng[b:b + k] if n2 == len(rest) - 1 else []
                        atoms.append({"i1": at + k, "i2": at + k, "lines": eng[s2:e2] + tail, "feature": f2})
                    done = True
                    break
                if not done:
                    raise SystemExit(f"cannot split the change at base line {at + 1} into whole elements")
                continue
            for f, s, e in segs:
                atoms.append({"i1": at, "i2": at, "lines": eng[s:e], "feature": f})
    return atoms


def build_stage(base: list[str], atoms: list[dict], upto: int, path: str, intermediates: dict) -> list[str]:
    """The file after the SREPs of the first `upto` features: base with every atom of those features applied."""
    allowed = set(ORDER[:upto])
    by_pos: dict[int, list[dict]] = {}
    for n, a in enumerate(atoms):
        by_pos.setdefault(a["i1"], []).append(a)
    out, i = [], 0
    while i <= len(base):
        skip_to = None
        for a in by_pos.get(i, []):
            lines = None
            if a["feature"] in allowed:
                lines = a["lines"]
            elif a["i2"] > a["i1"]:
                inter = intermediates.get((path, a["i1"]))
                if inter and inter[0] in allowed:
                    lines = inter[1]
            if lines is None:
                continue
            out.extend(lines)
            if a["i2"] > a["i1"]:
                skip_to = a["i2"]
        if i == len(base):
            break
        if skip_to is not None:
            i = skip_to
            continue
        out.append(base[i])
        i += 1
    return out


def check_stage(path: str, text: str, xsd_text: str | None) -> list[str]:
    """Problems of a stage file: it must parse, and the XSD and Schematron must compile."""
    from lxml import etree, isoschematron
    try:
        doc = etree.fromstring(text.encode())
    except etree.XMLSyntaxError as e:
        return [f"{path}: not well-formed: {e}"]
    try:
        if path.endswith(".xsd"):
            etree.XMLSchema(doc)
        else:
            isoschematron.Schematron(doc)
    except Exception as e:  # noqa: BLE001 - any compile error is a finding
        return [f"{path}: does not compile: {e}"]
    return []


# --------------------------------------------------------------------------------------------------------- measure
def first_parent_merge(repo: str, ref: str, commit: str, fp: list[str]) -> str | None:
    """The first-parent commit of `ref` that brought `commit` in, when `commit` is not itself on that line."""
    if commit in fp:
        return None
    lo, hi = 0, len(fp) - 1          # fp is oldest first; find the oldest that contains commit
    while lo < hi:
        mid = (lo + hi) // 2
        if subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", commit, fp[mid]]).returncode == 0:
            hi = mid
        else:
            lo = mid + 1
    return fp[lo]


def _anchor(key: str) -> str | None:
    """The text that declares an item, for git log -S: its start tag up to its name, id or context."""
    m = re.search(r"(\w+)\[([^\]]+)\]$", key)
    if not m:
        return None
    tag, val = m.groups()
    if tag in ("assert", "report", "pattern"):
        return f'<sch:{tag} id="{val}"'
    if tag == "rule":
        return f'<sch:rule context="{val}"'
    if tag == "let":
        return None
    if tag in ("complexType", "simpleType", "group", "attributeGroup", "element", "attribute") and "=" not in val:
        return f'<xs:{tag} name="{val}"'
    return None


def _unique(lines: list[str], n: int) -> str:
    """Line n (0-based), widened with the lines before it until the text is unique in the file."""
    text = "\n".join(lines)
    snippet, top = lines[n].strip(), n
    while text.count(snippet) > 1 and top > 0:
        top -= 1
        snippet = "\n".join(lines[top:n + 1]).strip()
    return snippet


def provenance(repo: str, ref: str, path: str, key: str, st: str, eng_lines: list[str], base_lines: list[str],
               ei: dict, bi: dict, fp: list[str], done: dict) -> dict:
    """The engine commit that introduced an item (git log -S, oldest hit) and the commits that last touched its lines
    (git blame). method: "anchor" -S on the item's declaring tag (unique in the file); "parent" inherited from the
    added item that contains it; "line" -S on its first line made unique by the lines before it; "changed-line" -S
    on the first line that differs from sr-core's, for a changed item."""
    a, b = ei[key]["lines"]
    text = "\n".join(eng_lines)
    parent = key.rsplit("/", 1)[0] if "/" in key else None
    anchor = _anchor(key)
    if st == "changed":
        old = base_lines[bi[key]["lines"][0] - 1:bi[key]["lines"][1]]
        new = eng_lines[a - 1:b]
        sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
        j = next(j1 for tag, _, _, j1, j2 in sm.get_opcodes() if tag != "equal" and j2 > j1)
        method, snippet = "changed-line", _unique(eng_lines, a - 1 + j)
    elif anchor and text.count(anchor) == 1:
        method, snippet = "anchor", anchor
    elif parent in done:
        method, snippet = "parent", None
    else:
        method, snippet = "line", _unique(eng_lines, a - 1)
    if snippet is None:
        res = {k: v for k, v in done[parent].items() if k != "last_touched"}
        res["method"] = "parent"
    else:
        log = git(repo, "log", "--reverse", "--format=%H %ad %s", "--date=short", f"-S{snippet}", ref, "--", path)
        first = log.splitlines()[0] if log.strip() else None
        intro = first.split()[0] if first else None
        res = {"introduced": intro[:7] if intro else None,
               "introduced_subject": first.split(" ", 2)[2] if first else None,
               "date": first.split()[1] if first else None,
               "merged_by": ((first_parent_merge(repo, ref, intro, fp) or "")[:7] or None) if intro else None,
               "method": method}
    blame = git(repo, "blame", "--porcelain", "-L", f"{a},{b}", ref, "--", path)
    res["last_touched"] = sorted({ln.split()[0][:7] for ln in blame.splitlines() if re.match(r"^[0-9a-f]{40} ", ln)})
    if st == "added":
        done[key] = res
    return res


def srep_fragments(repo: str, ref: str, numbers: range) -> dict:
    """Names the SREPs' Syntax fragments declare: (owner type, name) pairs, top-level names and rule ids."""
    owned, names, ids = set(), {}, {}
    for n in numbers:
        try:
            text = git(repo, "show", f"{ref}:srep/srep-{n:04d}.md")
        except subprocess.CalledProcessError:
            continue
        for block in re.findall(r"```xml\n(.*?)```", text, re.S):
            owner = None
            for line in block.splitlines():
                c = re.search(r"<!--\s*(\w+)", line)
                if c and "gains" in line:
                    owner = c.group(1)
                for m in re.finditer(r'<xs:(\w+) name="([^"]+)"', line):
                    names.setdefault(m.group(2), set()).add(n)
                    if owner and m.group(1) in ("attribute", "element"):
                        owned.add((owner, m.group(2), n))
                for m in re.finditer(r'<sch:(?:assert|report) id="([^"]+)"', line):
                    ids.setdefault(m.group(1), set()).add(n)
    return {"owned": owned, "names": names, "ids": ids}


def measure(args) -> dict:
    repo, ref = args.engine_repo, args.engine_ref
    head = git(repo, "rev-parse", ref).strip()
    upstream = git_bytes(repo, ref, "schema/UPSTREAM").decode()
    fp = git(repo, "rev-list", "--first-parent", "--reverse", ref).split()
    excl = srep_fragments(ROOT, args.exclude_ref, range(66, 76))
    result = {"engine": {"ref": ref, "commit": head, "upstream_note": upstream.splitlines()[0]},
              "base": {"ref": args.base_ref, "commit": git(ROOT, "rev-parse", args.base_ref + "^{commit}").strip()},
              "excluded_sreps": {"ref": args.exclude_ref, "numbers": list(range(66, 76))},
              "features": [{"feature": f, "srep": s, "title": t} for f, s, t, _ in FEATURES],
              "files": {}, "items": [], "excluded": [], "unclassified": [], "removed": []}
    stages_text = {}
    for core_path, eng_path in FILES.items():
        bb, eb = git_bytes(ROOT, args.base_ref, core_path), git_bytes(repo, ref, eng_path)
        result["files"][core_path] = {"engine_path": eng_path, "base_sha256": sha256(bb), "engine_sha256": sha256(eb)}
        bi, ei = items_of(bb), items_of(eb)
        status = compare(bi, ei)
        base_lines, eng_lines = bb.decode().split("\n"), eb.decode().split("\n")
        done: dict = {}
        for k in sorted(status, key=lambda k: (ei.get(k) or bi[k])["lines"][0]):
            st = status[k]
            if st == "removed":
                result["removed"].append({"file": core_path, "key": k})
                continue
            leaf = re.findall(r"\[([^\]]+)\]$", k)
            owner = re.findall(r"(?:complexType|group|attributeGroup)\[([^\]]+)\]", k)
            hit = None
            if leaf:
                for o, nm, n in excl["owned"]:
                    if nm == leaf[0] and owner and o == owner[-1]:
                        hit = n
                if k.startswith("pattern") and leaf[0] in excl["ids"]:
                    hit = sorted(excl["ids"][leaf[0]])[0]
                if re.match(r"^(complexType|simpleType)\[[^\]]+\]$", k) and leaf[0] in excl["names"]:
                    hit = sorted(excl["names"][leaf[0]])[0]
            entry = {"file": core_path, "key": k, "status": st, "lines": ei[k]["lines"]}
            if hit:
                entry["srep"] = hit
                result["excluded"].append(entry)
                continue
            f = feature_of(k)
            if f is None:
                result["unclassified"].append(entry)
                continue
            entry["feature"], entry["srep"] = f, SREP_OF[f]
            entry.update(provenance(repo, ref, eng_path, k, st, eng_lines, base_lines, ei, bi, fp, done))
            result["items"].append(entry)
        # new rule ids must not collide with sr-core's or with SREPs 66-75
        if core_path.endswith(".sch"):
            base_ids = set(re.findall(r'<sch:(?:assert|report) id="([^"]+)"', bb.decode()))
            new_ids = [re.findall(r"\[([^\]]+)\]$", e["key"])[0] for e in result["items"]
                       if e["file"] == core_path and e["status"] == "added" and re.search(r"/(assert|report)\[", e["key"])]
            result["rule_id_collisions"] = sorted({i for i in new_ids if i in base_ids or i in excl["ids"]})
        # line atoms and the files after each SREP
        fb = line_features(base_lines, bi, status)
        fe = line_features(eng_lines, ei, status)
        atoms = atoms_for(base_lines, eng_lines, fb, fe)
        intermediates = {}
        for (p, needle), (feat, commit) in INTERMEDIATE.items():
            if p != core_path:
                continue
            old = git_bytes(repo, commit, eng_path).decode().split("\n")
            line = next(l for l in old if needle in l)
            pos = next(a["i1"] for a in atoms if a["i2"] > a["i1"] and needle in base_lines[a["i1"]])
            intermediates[(core_path, pos)] = (feat, [line])
            result.setdefault("intermediates", []).append({"file": core_path, "line": needle, "feature": feat,
                                                           "from_engine_commit": commit})
        stages = [base_lines] + [build_stage(base_lines, atoms, k, core_path, intermediates)
                                 for k in range(1, len(ORDER) + 1)]
        if "\n".join(stages[-1]).encode() != eb:
            raise SystemExit(f"{core_path}: the atoms do not rebuild the engine's file")
        stages_text[core_path] = stages
    # each stage must parse and compile; the per-SREP patches are the differences between stages
    patches = {f: [] for f in ORDER}
    problems = []
    for core_path, stages in stages_text.items():
        for k, f in enumerate(ORDER, 1):
            problems += [f"after SREP {SREP_OF[f]}: {p}" for p in check_stage(core_path, "\n".join(stages[k]), None)]
            d = list(difflib.unified_diff(stages[k - 1], stages[k], f"a/{core_path}", f"b/{core_path}", n=3,
                                          lineterm=""))
            if d:
                patches[f].append("\n".join(d))
    result["stage_problems"] = problems
    result["patches"] = {f: {"srep": SREP_OF[f], "sha256": sha256("\n".join(p).encode()), "files": len(p)}
                         for f, p in patches.items()}
    counts = {}
    for e in result["items"]:
        c = counts.setdefault(e["feature"], {"srep": e["srep"], "xsd": {"added": 0, "changed": 0},
                                             "sch": {"added": 0, "changed": 0}})
        c["xsd" if e["file"].endswith(".xsd") else "sch"][e["status"]] += 1
    result["counts"] = counts
    if args.patches:
        os.makedirs(args.patches, exist_ok=True)
        for f, p in patches.items():
            with open(os.path.join(args.patches, f"srep-{SREP_OF[f]:04d}-{f}.diff"), "w") as fh:
                fh.write("\n".join(p) + "\n")
    return result


# ------------------------------------------------------------------------------------------------------ the SREP side
def srep_patches(numbers=None, fence: str = "diff") -> list[tuple[int, str]]:
    """The ```diff blocks of the SREPs (or, with fence="diff amendment", their amendment blocks), in SREP order."""
    out = []
    for n in (numbers if numbers is not None else [f[1] for f in FEATURES]):
        path = os.path.join(ROOT, "srep", f"srep-{n:04d}.md")
        if not os.path.exists(path):
            continue
        for block in re.findall(rf"^```{re.escape(fence)}\n(.*?)^```", open(path, encoding="utf-8").read(),
                                re.S | re.M):
            out.append((n, block))
    return out


def srep_amendments(numbers=None) -> list[tuple[int, str]]:
    """The ```diff amendment blocks of the SREPs, in SREP order."""
    return srep_patches(numbers, fence="diff amendment")


def apply_amendment(files: dict[str, list[str]], patch: str) -> None:
    """Apply a unified diff by content: each hunk's removed and context lines must occur exactly once in the file,
    wherever the earlier blocks have put them (the line numbers of its hunk headers are not used)."""
    lines = patch.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    i, path = 0, None
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            i += 1
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            i += 1
            continue
        if not line.startswith("@@"):
            raise ValueError(f"unexpected patch line: {line[:80]}")
        i += 1
        old, new = [], []
        while i < len(lines) and not lines[i].startswith(("@@", "--- ")):
            t = lines[i]
            if t.startswith(" ") or t == "":
                old.append(t[1:])
                new.append(t[1:])
            elif t.startswith("-"):
                old.append(t[1:])
            elif t.startswith("+"):
                new.append(t[1:])
            elif not t.startswith("\\"):
                raise ValueError(f"unexpected hunk line: {t[:80]}")
            i += 1
        text = files[path]
        at = [k for k in range(len(text) - len(old) + 1) if text[k:k + len(old)] == old]
        if len(at) != 1:
            raise ValueError(f"{path}: an amendment hunk matches {len(at)} places, not one")
        text[at[0]:at[0] + len(old)] = new


def apply_patch(files: dict[str, list[str]], patch: str) -> None:
    """Apply a unified diff exactly (no fuzz): every context and removed line must match where the hunk says."""
    lines = patch.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    i, path = 0, None
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            i += 1
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            offset = 0
            i += 1
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if not m:
            raise ValueError(f"unexpected patch line: {line[:80]}")
        start = int(m.group(1)) - (0 if m.group(2) == "0" else 1)
        i += 1
        old, new = [], []
        while i < len(lines) and not lines[i].startswith(("@@", "--- ")):
            t = lines[i]
            if t.startswith(" ") or t == "":
                old.append(t[1:])
                new.append(t[1:])
            elif t.startswith("-"):
                old.append(t[1:])
            elif t.startswith("+"):
                new.append(t[1:])
            elif t.startswith("\\"):
                pass
            else:
                raise ValueError(f"unexpected hunk line: {t[:80]}")
            i += 1
        text = files[path]
        at = start + offset
        if text[at:at + len(old)] != old:
            raise ValueError(f"{path}: hunk at line {start + 1} does not match")
        text[at:at + len(old)] = new
        offset += len(new) - len(old)


def baseline(ref: str = "schema-1.5.0") -> dict[str, bytes] | None:
    """The 1.5.0 schema files: from the tag when git has it, else from schema/ while it is still 1.5.0."""
    want = {}
    if os.path.exists(DEFAULT_OUT):
        want = {p: v["base_sha256"] for p, v in json.load(open(DEFAULT_OUT))["files"].items()}
    out = {}
    for path in FILES:
        try:
            out[path] = git_bytes(ROOT, ref, path)
        except (subprocess.CalledProcessError, FileNotFoundError):
            data = open(os.path.join(ROOT, path), "rb").read()
            if want and sha256(data) != want.get(path):
                return None
            out[path] = data
    return out


def verify(gap_path: str = DEFAULT_OUT) -> list[str]:
    """Apply the SREPs' diff blocks in order to 1.5.0 and compare with the engine's hashes. Returns problems."""
    gap = json.load(open(gap_path))
    base = baseline(gap["base"]["ref"])
    if base is None:
        return ["the 1.5.0 schema files are not available (no tag and schema/ has moved on)"]
    files = {p: b.decode().split("\n") for p, b in base.items()}
    problems = []
    blocks = srep_patches()
    if not blocks:
        return ["no diff blocks in SREPs 76 to 81"]
    for n, block in blocks:
        try:
            apply_patch(files, block)
        except (ValueError, KeyError) as e:
            problems.append(f"SREP {n}: {e}")
    for p, info in gap["files"].items():
        got = sha256("\n".join(files[p]).encode())
        if got != info["engine_sha256"]:
            problems.append(f"{p}: after SREPs 76 to 81 the hash is {got}, the engine's is {info['engine_sha256']}")
    for f in gap["features"]:
        text = "".join(b + "\n" for n, b in blocks if n == f["srep"])
        want = gap["patches"][f["feature"]]
        if want["files"] and not text:
            problems.append(f"SREP {f['srep']} has no diff block")
    return problems


def proposed_schema(upto: int | None = None, amendments: bool = True) -> dict[str, bytes]:
    """The 1.5.0 files with the diff blocks of SREPs 76.. applied (all of them, or those up to SREP `upto`), then their
    amendment blocks (unless amendments=False, which gives the measured engine text)."""
    base = baseline()
    if base is None:
        raise RuntimeError("the 1.5.0 schema files are not available")
    files = {p: b.decode().split("\n") for p, b in base.items()}
    for n, block in srep_patches():
        if upto is None or n <= upto:
            apply_patch(files, block)
    if amendments:
        for n, block in srep_amendments():
            if upto is None or n <= upto:
                apply_amendment(files, block)
    return {p: "\n".join(v).encode() for p, v in files.items()}


# ------------------------------------------------------------------------------------------------------------- main
def table(result: dict) -> str:
    rows = ["| SREP | Feature | XSD added | XSD changed | Schematron added | Schematron changed | Total |",
            "|---|---|---|---|---|---|---|"]
    tot = [0, 0, 0, 0]
    for f, s, t, _ in FEATURES:
        c = result["counts"].get(f)
        if not c:
            continue
        v = [c["xsd"]["added"], c["xsd"]["changed"], c["sch"]["added"], c["sch"]["changed"]]
        tot = [a + b for a, b in zip(tot, v)]
        rows.append(f"| {s} | {t} | " + " | ".join(map(str, v)) + f" | {sum(v)} |")
    rows.append("| | **all** | " + " | ".join(map(str, tot)) + f" | {sum(tot)} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("measure", "check"):
        p = sub.add_parser(name)
        p.add_argument("--engine-repo", required=True)
        p.add_argument("--engine-ref", default="origin/main")
        p.add_argument("--base-ref", default="schema-1.5.0")
        p.add_argument("--exclude-ref", default="origin/srep/drafts-2026-10")
        p.add_argument("--out", default=DEFAULT_OUT)
        p.add_argument("--patches", help="directory to write one .diff per SREP into")
        p.add_argument("--table", action="store_true", help="print the counts as a Markdown table")
    v = sub.add_parser("verify")
    v.add_argument("--gap", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if args.cmd == "verify":
        problems = verify(args.gap)
        print("\n".join(problems) or "ok: SREPs 76 to 81 rebuild the engine's XSD and Schematron byte for byte")
        return 1 if problems else 0
    result = measure(args)
    bad = []
    if result["unclassified"]:
        bad.append(f"{len(result['unclassified'])} unclassified items: " +
                   ", ".join(e["key"] for e in result["unclassified"][:10]))
    if result["removed"]:
        bad.append(f"{len(result['removed'])} items sr-core has and the engine lacks")
    if result.get("rule_id_collisions"):
        bad.append(f"rule ids that collide: {result['rule_id_collisions']}")
    bad += result["stage_problems"]
    if args.table:
        print(table(result))
    if args.cmd == "measure":
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print(f"wrote {args.out}: {len(result['items'])} items, {len(result['excluded'])} excluded")
    else:
        committed = json.load(open(args.out))
        if committed != json.loads(json.dumps(result)):
            a = json.dumps(committed, indent=1, sort_keys=True).splitlines()
            b = json.dumps(result, indent=1, sort_keys=True).splitlines()
            bad.append("the committed inventory differs from the measurement:\n" +
                       "\n".join(list(difflib.unified_diff(a, b, "committed", "measured", lineterm=""))[:60]))
        else:
            print(f"ok: {args.out} matches {result['engine']['ref']} at {result['engine']['commit'][:7]}")
    for b in bad:
        print("problem:", b, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
