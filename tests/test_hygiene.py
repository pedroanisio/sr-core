"""tools/check_hygiene.py: the representative cases for each rule, run on throwaway git repositories."""
import importlib.util
import os
import subprocess
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("check_hygiene", os.path.join(ROOT, "tools", "check_hygiene.py"))
hy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hy)

SREP_OK = """```
SREP:            {n}
Title:           T
Author:          a
Status:          {status}
Type:            Process
Created:         2026-01-01
Schema-Version:  n/a
{resolution}```

# SREP {n}
"""


def repo(tmp_path, files: dict[str, str]):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return str(tmp_path)


def rules(tmp_path, files):
    return sorted({f.rule for f in hy.check(repo(tmp_path, files))})


HOME = "/ho" + "me/"    # assembled so this file does not itself match R2


@pytest.mark.parametrize("files,expected", [
    ({"README.md": "pip install -e ~/src/sr-core\n"}, ["R2"]),  # hygiene: allow R2 rule fixture
    ({"docs/x.md": f"use {HOME}me/.venvs/py/bin/python\n"}, []),                        # placeholder user
    ({"docs/x.md": "`/home/...` and `/Users/...` are refused\n"}, []),                 # describes patterns
    ({"tests/t.py": f'P = "{HOME}someone/v.onnx"  # hygiene: allow R2 lint fixture\n'}, []),
    ({"docs/x.md": f'P = "{HOME}someone/v.onnx"  <!-- hygiene: allow R2 fixture -->\n'}, ["R2"]),
    ({"notes/plan.md": "next steps\n"}, ["R1"]),
    ({"CLAUDE.md": "instructions\n"}, ["R1"]),
    ({"docs/x.md": "see the v007-ww2 project\n"}, ["R2"]),  # hygiene: allow R2 rule fixture
    ({"docs/x.md": "mail someone@example.org\n"}, ["R2"]),  # hygiene: allow R2 rule fixture
    ({"LICENSE": "Copyright someone@example.org\n"}, []),  # hygiene: allow R2 rule fixture
    ({"schema/s.xsd": "<!-- rs-scene-render extension -->\n"}, ["R2"]),  # hygiene: allow R2 rule fixture
    ({"docs/s.md": "rs-scene-render renders it\n"}, []),                                # engine names are fine in docs  # hygiene: allow R2 rule fixture
    ({"docs/x.md": "[gone](missing.md) and [ok](y.md) and [web](https://x.org) and [a](#b)\n", "docs/y.md": ""},
     ["R3"]),
])
def test_rules(tmp_path, files, expected):
    assert rules(tmp_path, files) == expected


def test_srep_records(tmp_path):
    quoted = SREP_OK.format(n=2, status="Final", resolution='Resolution:      2026-01-01: accepted ("do it")\n')
    assert rules(tmp_path / "a", {"srep/srep-0002.md": quoted}) == ["R4"]
    undecided = SREP_OK.format(n=2, status="Final", resolution="")
    assert rules(tmp_path / "b", {"srep/srep-0002.md": undecided}) == ["R4"]
    draft_process = {"srep/srep-0000.md": SREP_OK.format(n=0, status="Draft", resolution=""),
                     "srep/srep-0002.md": SREP_OK.format(n=2, status="Final",
                                                         resolution="Resolution:      2026-01-01: accepted.\n")}
    assert rules(tmp_path / "c", draft_process) == ["R4"]
    ok = SREP_OK.format(n=2, status="Final", resolution="Resolution:      2026-01-01: accepted by the editor.\n")
    assert rules(tmp_path / "d", {"srep/srep-0002.md": ok}) == []


def test_allowlist_exceptions_are_narrow_and_expire(tmp_path):
    files = {"docs/x.md": "pip install -e ~/src/x\n",  # hygiene: allow R2 rule fixture
             "tools/hygiene-allow.txt": "docs/x.md:R2:example kept on purpose\n"}
    assert rules(tmp_path / "a", files) == []
    files["docs/x.md"] = "clean now\n"
    assert rules(tmp_path / "b", files) == ["allow"]                     # stale exception
    files["tools/hygiene-allow.txt"] = "docs/x.md:R2:\n"
    files["docs/x.md"] = "pip install -e ~/src/x\n"  # hygiene: allow R2 rule fixture
    assert rules(tmp_path / "c", files) == ["allow"]                     # exception without a reason


def test_sdist_without_release_tooling_fails(tmp_path):
    root = repo(tmp_path, {"pyproject.toml": '[project]\nname = "x"\nversion = "0.1"\n'
                                             '[tool.setuptools]\npackages = ["sr_core"]\n',
                           "sr_core/__init__.py": ""})
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
    messages = [f.message for f in hy.r5(root, run_tests=False)]
    assert any("lacks tools/release.py" in m for m in messages)
    assert any("lacks schema/scene-render.xsd" in m for m in messages)


def in_checkout():
    r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "HEAD"], capture_output=True)
    return r.returncode == 0 and bool(hy.tracked(ROOT))


@pytest.mark.skipif(not in_checkout(), reason="needs the sr-core git checkout")
def test_repository_is_clean():
    assert [str(f) for f in hy.check(ROOT)] == []


@pytest.mark.skipif(not in_checkout(), reason="needs the sr-core git checkout")
def test_release_artifacts_are_complete():
    assert [str(f) for f in hy.r5(ROOT, run_tests=False)] == []


# ---- srep/index.md against the SREP headers (drift-risk map finding 5)
def _srep(n, title="T", typ="Process", status="Draft", version="n/a"):
    return SREP_OK.format(n=n, status=status, resolution="").replace("Title:           T", f"Title:           {title}") \
        .replace("Type:            Process", f"Type:            {typ}") \
        .replace("Schema-Version:  n/a", f"Schema-Version:  {version}")


def _row(n, title="T", typ="Process", status="Draft", version="n/a"):
    return f"| [{n}](srep-{n:04d}.md) | {title} | {typ} | {status} | {version} |\n"


INDEX_HEAD = "# SREP index\n\n| SREP | Title | Type | Status | Version |\n|---|---|---|---|---|\n"


def _index_repo(tmp_path, index_rows, sreps=((1, {}),), allow=""):
    files = {f"srep/srep-{n:04d}.md": _srep(n, **kw) for n, kw in sreps}
    files["srep/index.md"] = INDEX_HEAD + "".join(index_rows)
    if allow:
        files["tools/hygiene-allow.txt"] = allow
    return repo(tmp_path, files)


def _index_findings(tmp_path, *a, **k):
    return [str(f) for f in hy.check(_index_repo(tmp_path, *a, **k)) if f.rule == "R4"]


def test_an_index_that_matches_its_headers_is_clean(tmp_path):
    assert _index_findings(tmp_path, [_row(1)]) == []


def test_index_tolerates_code_marks_and_a_trailing_note(tmp_path):
    rows = [_row(1, title="Add `<program>` (amends SREP 2)", version="n/a")]
    assert _index_findings(tmp_path, rows, sreps=((1, {"title": "Add <program>"}),)) == []


@pytest.mark.parametrize("col,row_kw,srep_kw", [
    ("Title", {"title": "Other"}, {}),
    ("Type", {"typ": "Standards"}, {}),
    ("Status", {"status": "Review"}, {}),
    ("Version", {"version": "1.5"}, {"version": "1.3"}),
])
def test_a_column_that_differs_from_the_header_is_a_finding(tmp_path, col, row_kw, srep_kw):
    found = _index_findings(tmp_path, [_row(1, **row_kw)], sreps=((1, srep_kw),))
    assert len(found) == 1 and f"index.md {col} is" in found[0] and found[0].split()[1] == "srep/srep-0001.md:", found


def test_a_srep_without_a_row_is_a_finding(tmp_path):
    found = _index_findings(tmp_path, [_row(1)], sreps=((1, {}), (2, {})))
    assert any("srep/srep-0002.md" in f and "no row" in f for f in found), found


def test_a_row_for_a_missing_file_or_out_of_order_is_a_finding(tmp_path):
    assert any("not a tracked file" in f for f in _index_findings(tmp_path, [_row(1), _row(9)]))
    found = _index_findings(tmp_path, [_row(2), _row(1)], sreps=((1, {}), (2, {})))
    assert any("ascending" in f for f in found), found


def test_an_intended_difference_is_allowed_by_path_and_needs_a_reason(tmp_path):
    rows, kw = [_row(1, version="1.5")], ((1, {"version": "1.3"}),)
    allow = "srep/srep-0001.md:R4:drafted for 1.3, shipped in 1.5\n"
    assert _index_findings(tmp_path, rows, sreps=kw, allow=allow) == []
    other = tmp_path / "x"
    other.mkdir()
    found = hy.check(_index_repo(other, rows, sreps=kw, allow="srep/srep-0001.md:R4:\n"))
    assert [f.rule for f in found] == ["allow"] and "needs a reason" in found[0].message
