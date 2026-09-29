#!/usr/bin/env python3
"""Release hygiene: tracked files and release artifacts carry only releasable material.

    python3 tools/check_hygiene.py                # R1-R4 and R6 on the tracked files; exit 1 on findings
    python3 tools/check_hygiene.py --artifacts    # also R5: build the sdist and wheel and inspect them

Rules:
  R1  no working material tracked (agent instructions, notes, plans, scratch, logs, audits)
  R2  no private references: machine paths, private working directories, local project ids, sibling folders
      that are not published, e-mail addresses outside LICENSE and pyproject; in the schema, no engine
      repository or command names
  R3  every relative Markdown link resolves to a tracked file
  R4  SREP headers are complete, statuses valid, decisions recorded as a date and a plain statement
  R5  release artifacts: the wheel holds only the package, the sdist holds what its tests need and they pass
      from it, and the package metadata passes R2
  R6  versions, schema hashes and the generated reference agree (tools/release.py check)

Exceptions: `hygiene: allow R<n> <reason>` on the line itself, accepted only in tests/ and
sr_core/vpkg/lint.py (where such paths are the product's test data and patterns); otherwise an entry
`path:R<n>:reason` in tools/hygiene-allow.txt. An allowlist entry that no longer matches anything fails.
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKING_MATERIAL = ["CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/*", "*.prompt.md", "notes/*", "plans/*",
                    "scratch/*", "*.log", "*audit*.md"]
PRIVATE = [
    (re.compile(r"~/(?:src|videos|work)\b"), "home-relative development path"),
    (re.compile(r"/home/(?!me/)[A-Za-z][\w.-]*/"), "machine path under /home"),
    (re.compile(r"/Users/(?!me/)[A-Za-z][\w.-]*/"), "machine path under /Users"),
    (re.compile(r"/tmp/claude-|\bscratchpad\b|\.claude/projects|\.local/share/scene-render"), "private working directory"),
    (re.compile(r"\bv\d{3}-[a-z]"), "local project id"),
    (re.compile(r"\bscene-render-conformance/"), "unpublished sibling folder"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "e-mail address"),
]
SCHEMA_ONLY = [(re.compile(r"\b(?:rs|c|py)-scene-render\b|\bpy-render\b|\bjs-render-engine\b|"
                           r"`scene-render (?:resolve|encode|render|validate|simulate)`"), "engine name in the schema")]
EMAIL_OK = {"LICENSE", "pyproject.toml"}
MARKER = re.compile(r"hygiene: allow (R\d)")
MARKER_OK = ("tests/", "sr_core/vpkg/lint.py")
TEXT = (".md", ".py", ".toml", ".txt", ".json", ".xsd", ".sch", ".in", ".cfg", ".yml", ".yaml", "")
SREP_STATUS = {"Draft", "Review", "Accepted", "Final", "Active", "Deferred", "Rejected", "Withdrawn", "Superseded"}
SREP_REQUIRED = ("SREP", "Title", "Author", "Status", "Type", "Created", "Schema-Version")
DECIDED = {"Accepted", "Final", "Active", "Deferred", "Rejected", "Superseded"}
RESOLUTION = re.compile(r"\d{4}-\d{2}-\d{2}: [^\"“”']+")


class Finding:
    def __init__(self, rule: str, where: str, message: str):
        self.rule, self.where, self.message = rule, where, message

    def __str__(self):
        return f"{self.rule} {self.where}: {self.message}"


def tracked(root: str) -> list[str]:
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True, capture_output=True).stdout
    return sorted(p for p in out.decode().split("\0") if p)


def read(root: str, path: str) -> str | None:
    try:
        with open(os.path.join(root, path), encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return None


def load_allow(root: str) -> list[tuple[str, str, str]]:
    text = read(root, "tools/hygiene-allow.txt") or ""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            path, rule, reason = (line.split(":", 2) + ["", ""])[:3]
            out.append((path, rule, reason.strip()))
    return out


# ------------------------------------------------------------------ rules
def r1(files):
    return [Finding("R1", p, "working material is not tracked; keep it in a local directory outside the repository")
            for p in files if any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(os.path.basename(p), g)
                                  for g in WORKING_MATERIAL)]


def r2_text(path: str, text: str, schema: bool = False) -> list[Finding]:
    found = []
    rules = PRIVATE + (SCHEMA_ONLY if schema else [])
    for n, line in enumerate(text.splitlines(), 1):
        m = MARKER.search(line)
        if m and path.startswith(MARKER_OK) and m.group(1) == "R2":
            continue
        for rx, what in rules:
            hit = rx.search(line)
            if not hit:
                continue
            if what == "e-mail address" and os.path.basename(path) in EMAIL_OK:
                continue
            found.append(Finding("R2", f"{path}:{n}", f"{what} {hit.group(0)!r}; use a neutral example or remove it"))
        if m and not path.startswith(MARKER_OK):
            found.append(Finding(m.group(1), f"{path}:{n}", "inline exceptions are only accepted in tests/ and "
                                                            "sr_core/vpkg/lint.py; use tools/hygiene-allow.txt"))
    return found


def r2(root, files):
    out = []
    for p in files:
        if p.startswith("docs/schema/") or not p.endswith(TEXT):
            continue
        text = read(root, p)
        if text is not None:
            out += r2_text(p, text, schema=p.startswith("schema/") and p.endswith((".xsd", ".sch")))
    return out


LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def r3(root, files):
    have = set(files)
    out = []
    for p in files:
        if not p.endswith(".md"):
            continue
        for n, line in enumerate((read(root, p) or "").splitlines(), 1):
            for target in LINK.findall(line):
                if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                t = os.path.normpath(os.path.join(os.path.dirname(p), target.split("#")[0])).replace(os.sep, "/")
                if t not in have and not any(f.startswith(t.rstrip("/") + "/") for f in have):
                    out.append(Finding("R3", f"{p}:{n}", f"link to {target} does not resolve to a tracked file"))
    return out


def srep_header(text: str) -> dict[str, tuple[int, str]]:
    m = re.match(r"```\n(.*?)\n```", text, re.S)
    if not m:
        return {}
    out = {}
    for n, line in enumerate(m.group(1).splitlines(), 2):
        k, _, v = line.partition(":")
        out[k.strip()] = (n, v.strip())
    return out


def r4(root, files):
    out, statuses = [], {}
    for p in files:
        if not re.fullmatch(r"srep/srep-\d{4}\.md", p):
            continue
        h = srep_header(read(root, p) or "")
        for k in SREP_REQUIRED:
            if k not in h:
                out.append(Finding("R4", p, f"header lacks {k}"))
        status = h.get("Status", (0, ""))[1]
        statuses[p] = status
        if status and status not in SREP_STATUS:
            out.append(Finding("R4", f"{p}:{h['Status'][0]}", f"unknown status {status!r}"))
        if "Resolution" in h and not RESOLUTION.fullmatch(h["Resolution"][1]):
            out.append(Finding("R4", f"{p}:{h['Resolution'][0]}", "Resolution must be 'YYYY-MM-DD: decision', "
                                                                  "a plain statement without quotations"))
        if status in DECIDED and "Resolution" not in h:
            out.append(Finding("R4", p, f"status {status} needs a Resolution"))
    if statuses.get("srep/srep-0000.md") == "Draft" and any(s in DECIDED for s in statuses.values()):
        out.append(Finding("R4", "srep/srep-0000.md", "the process is Draft while SREPs are decided under it"))
    return out


def r6(root):
    if root != ROOT:
        return []
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import release
    return [Finding("R6", "tools/release.py check", p) for p in release.check()]


def r5(root, run_tests: bool = True) -> list[Finding]:
    """Build the sdist and wheel from HEAD in a scratch directory and inspect them."""
    out = []
    with tempfile.TemporaryDirectory(prefix="hygiene-") as tmp:
        tree = os.path.join(tmp, "tree")
        os.makedirs(tree)
        tar = subprocess.run(["git", "-C", root, "archive", "--format=tar", "HEAD"], check=True, capture_output=True).stdout
        _extract(tarfile.open(fileobj=io.BytesIO(tar)), tree)
        dist = os.path.join(tmp, "dist")
        build = ("import sys, setuptools.build_meta as b; d = sys.argv[1]; "
                 "s = b.build_sdist(d); w = b.build_wheel(d); print('ARTIFACTS', s, w)")
        r = subprocess.run([sys.executable, "-c", build, dist], cwd=tree, capture_output=True, text=True)
        if r.returncode:
            return [Finding("R5", "build", r.stderr.strip().splitlines()[-1] if r.stderr else "build failed")]
        line = [ln for ln in r.stdout.splitlines() if ln.startswith("ARTIFACTS ")][-1]
        sdist_name, wheel_name = line.split()[1:3]
        with zipfile.ZipFile(os.path.join(dist, wheel_name)) as w:
            for n in w.namelist():
                if not (n.startswith("sr_core/") or ".dist-info/" in n):
                    out.append(Finding("R5", wheel_name, f"unexpected entry {n}"))
            meta = next(n for n in w.namelist() if n.endswith(".dist-info/METADATA"))
            out += [Finding("R5", f"{wheel_name}:METADATA", f.message)
                    for f in r2_text("METADATA", w.read(meta).decode("utf-8"))]
        with tarfile.open(os.path.join(dist, sdist_name)) as s:
            names = {n.split("/", 1)[1] for n in s.getnames() if "/" in n}
            for need in ("schema/scene-render.xsd", "schema/scene-render.sch", "tools/release.py", "tests"):
                if need not in names and not any(n.startswith(need + "/") for n in names):
                    out.append(Finding("R5", sdist_name, f"lacks {need}"))
            if run_tests and not out:
                _extract(s, os.path.join(tmp, "sd"))
                sd = os.path.join(tmp, "sd", sdist_name[:-len(".tar.gz")])
                subprocess.run(["git", "init", "-q"], cwd=sd, check=True)
                t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                                   cwd=sd, capture_output=True, text=True)
                if t.returncode:
                    out.append(Finding("R5", sdist_name, "tests fail from the unpacked sdist: "
                                                         + (t.stdout.strip().splitlines() or ["?"])[-1]))
    return out


def _extract(t: tarfile.TarFile, dest: str) -> None:
    try:
        t.extractall(dest, filter="data")
    except TypeError:                     # Python without extraction filters
        t.extractall(dest)


# ---------------------------------------------------------------- driver
def check(root: str = ROOT, artifacts: bool = False, run_tests: bool = True) -> list[Finding]:
    files = tracked(root)
    findings = r1(files) + r2(root, files) + r3(root, files) + r4(root, files) + r6(root)
    if artifacts:
        findings += r5(root, run_tests)
    allow = load_allow(root)
    used = set()
    kept = []
    for f in findings:
        path = f.where.split(":")[0]
        hit = next((i for i, (p, rule, _) in enumerate(allow) if p == path and rule == f.rule), None)
        if hit is None:
            kept.append(f)
        else:
            used.add(hit)
    for i, (p, rule, reason) in enumerate(allow):
        if not reason:
            kept.append(Finding("allow", f"tools/hygiene-allow.txt:{p}", "every exception needs a reason"))
        elif i not in used:
            kept.append(Finding("allow", f"tools/hygiene-allow.txt:{p}", f"{rule} exception matches nothing; remove it"))
    return kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="check_hygiene.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--artifacts", action="store_true", help="also build and inspect the sdist and wheel (R5)")
    a = ap.parse_args(argv)
    findings = check(artifacts=a.artifacts)
    for f in findings:
        print(f, file=sys.stderr)
    print(f"hygiene: {len(findings)} finding(s)" if findings else "hygiene: clean")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
