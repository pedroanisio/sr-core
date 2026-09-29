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
