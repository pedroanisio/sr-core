"""tools/release.py: bumps from changelog classes, cutting a release, and the repository's own versions (SREP 4)."""
import importlib.util
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("release", os.path.join(ROOT, "tools", "release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

LOG = """# Changelog

## Unreleased

### Breaking

### Added

### Fixed

- a typo
  spanning two lines

## 1.4.2 — 2026-01-01

### Fixed

- older
"""


def with_entries(**classes):
    text = LOG
    for name, entries in classes.items():
        text = text.replace(f"### {name}\n\n", f"### {name}\n\n" + "".join(f"- {e}\n" for e in entries) + "\n", 1)
    return text


def test_parse():
    classes, released, _ = release.parse(LOG)
    assert classes == {"fixed": ["a typo spanning two lines"]}
    assert released == ["1.4.2"]


@pytest.mark.parametrize("classes,expected", [
    ({}, None),
    ({"fixed": ["x"]}, "1.4.3"),
    ({"docs": ["x"], "changed": ["y"]}, "1.4.3"),
    ({"added": ["x"], "fixed": ["y"]}, "1.5.0"),
    ({"deprecated": ["x"]}, "1.5.0"),
    ({"breaking": ["x"], "added": ["y"]}, "2.0.0"),
    ({"removed": ["x"]}, "2.0.0"),
])
def test_next_version_takes_the_largest_bump(classes, expected):
    assert release.next_version("1.4.2", classes) == expected


def test_many_changes_share_one_bump():
    text = with_entries(Added=["one", "two", "three"])
    classes, _, _ = release.parse(text)
    assert release.next_version("1.4.2", classes) == "1.5.0"


def test_cut_moves_entries_and_leaves_an_empty_unreleased():
    text = with_entries(Added=["feature"])
    out = release.cut(text, "1.5.0", "2026-10-01")
    classes, released, _ = release.parse(out)
    assert classes == {} and released == ["1.5.0", "1.4.2"]
    section = out.split("## 1.5.0 — 2026-10-01\n", 1)[1].split("## 1.4.2", 1)[0]
    assert "- feature" in section and "- a typo spanning two lines" in section and "### Breaking" not in section


def test_entry_outside_a_class_is_an_error():
    with pytest.raises(release.ReleaseError):
        release.parse("## Unreleased\n\n- loose\n")


def test_repository_versions_agree():
    """Every version matches its changelog, the schema hashes and reference are current (release.py check)."""
    assert release.check() == []


def test_one_distribution_version():
    import sr_core
    from sr_core import schemadoc, vpkg
    assert vpkg.__version__ == schemadoc.__version__ == sr_core.__version__ == release.tools_version()


# ------------------------------------------------------------------ scene SDK (SREP 0, D1, D2, D7)
import shutil  # noqa: E402

SDK_FILES = ["schema/scene-render.xsd", "schema/scene-render.sch", "schema/SHA256SUMS",
             "sr_core/scene/_generated.py", "sr_core/scene/schema/scene-render.xsd",
             "sr_core/scene/schema/scene-render.sch", "sr_core/scene/schema/SHA256SUMS"]


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """A scratch copy of the files the SDK controls; release.ROOT points at it."""
    for rel in SDK_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), tmp_path / rel)
    monkeypatch.setattr(release, "ROOT", str(tmp_path))
    return tmp_path


def test_fresh_sdk_has_no_problems(tmp_root):
    assert release.sdk_problems() == []


def test_stale_sdk_is_a_problem(tmp_root):
    gen = tmp_root / release.SDK_GENERATED
    gen.write_bytes(gen.read_bytes() + b"# edited\n")
    assert release.sdk_problems() == ["sr_core/scene is stale; run python3 -m sr_core.scene.generate"]


def test_missing_sdk_is_stale(tmp_root):
    (tmp_root / release.SDK_GENERATED).unlink()
    assert release.SDK_STALE in release.sdk_problems()


def test_schema_change_without_regeneration_is_stale_and_mismatched(tmp_root):
    xsd = tmp_root / "schema/scene-render.xsd"
    xsd.write_bytes(xsd.read_bytes().replace(b"<!--", b"<!-- ", 1))
    problems = release.sdk_problems()
    assert release.SDK_STALE in problems
    assert any("sr_core/scene/schema/scene-render.xsd is not byte-equal to schema/scene-render.xsd" in p for p in problems)
    assert any("XSD_SHA256" in p for p in problems)


@pytest.mark.parametrize("name", ["scene-render.sch", "SHA256SUMS"])
def test_schema_copy_mismatch(tmp_root, name):
    copy = tmp_root / "sr_core/scene/schema" / name
    copy.write_bytes(copy.read_bytes() + b"\n")
    assert release.sdk_problems() == [f"sr_core/scene/schema/{name} is not byte-equal to schema/{name}; "
                                      "run python3 -m sr_core.scene.generate"]


@pytest.mark.parametrize("const", ["XSD_SHA256", "SCH_SHA256"])
def test_header_hash_mismatch(tmp_root, const):
    gen = tmp_root / release.SDK_GENERATED
    text = gen.read_text(encoding="utf-8")
    old = next(l for l in text.splitlines() if l.startswith(f"{const} = "))
    gen.write_text(text.replace(old, f'{const} = "{"0" * 64}"'), encoding="utf-8")
    problems = release.sdk_problems()
    assert any(const in p and "differs from the hash" in p for p in problems)


def test_check_reports_the_sdk_problems(monkeypatch):
    monkeypatch.setattr(release, "sdk_problems", lambda: ["sdk problem"])
    assert "sdk problem" in release.check()


def test_refresh_schema_regenerates_the_sdk(tmp_root, monkeypatch):
    from sr_core.schemadoc import cli
    monkeypatch.setattr(cli, "main", lambda argv: 0)
    xsd = tmp_root / "schema/scene-render.xsd"
    xsd.write_bytes(xsd.read_bytes().replace(b"<!--", b"<!-- ", 1))
    release.refresh_schema()
    assert release.sdk_problems() == []
    assert (tmp_root / "sr_core/scene/schema/scene-render.xsd").read_bytes() == xsd.read_bytes()
    assert (tmp_root / "schema/SHA256SUMS").read_text() == release.sums_text()


TOOLS_LOG = "# Changelog\n\n## Unreleased\n\n### Breaking\n\n### Added\n\n### Fixed\n\n## 1.7.0 — 2026-10-12\n\n### Added\n\n- x\n"


@pytest.mark.parametrize("schema_classes,section,expected_ok", [
    ({"fixed": ["f"]}, "Added", True),
    ({"added": ["a"]}, "Added", True),
    ({"changed": ["c"], "added": ["a"]}, "Added", True),
    ({"breaking": ["b"]}, "Breaking", True),
    ({"removed": ["r"], "added": ["a"]}, "Breaking", True),
    ({"fixed": ["f"]}, "Fixed", False),
    ({"fixed": ["f"]}, "Breaking", False),
    ({"breaking": ["b"]}, "Added", False),
    ({"removed": ["r"]}, "Added", False),
])
def test_sdk_entry_class_follows_the_schema_change(schema_classes, section, expected_ok):
    text = TOOLS_LOG.replace(f"### {section}\n\n", f"### {section}\n\n- Regenerates `sr_core.scene` for 1.7.1.\n\n", 1)
    problem = release.sdk_entry_problem(schema_classes, text, "1.7.1")
    assert (problem is None) is expected_ok
    if not expected_ok:
        assert "sr_core.scene" in problem


def test_sdk_entry_must_mention_the_sdk():
    text = TOOLS_LOG.replace("### Added\n\n", "### Added\n\n- something else\n\n", 1)
    assert "no Unreleased entry that mentions sr_core.scene and 1.7.1 under Added" in release.sdk_entry_problem({"fixed": ["f"]}, text, "1.7.1")


@pytest.mark.parametrize("entry,ok", [
    ("Regenerates `sr_core.scene` for schema 1.7.1.", True),
    ("Introduces `sr_core.scene`, generated from schema 1.7.0.", False),   # an older entry: the introduction
    ("Regenerates `sr_core.scene`.", False),                              # no version at all
    ("Regenerates `sr_core.scene` for 1.7.10.", False),                   # a longer version is not this one
    ("Regenerates `sr_core.scene` for 21.7.1.", False),
    ("Schema 1.7.1 changes.", False),                                     # does not mention the SDK
])
def test_sdk_entry_must_name_the_version_being_released(entry, ok):
    text = TOOLS_LOG.replace("### Added\n\n", f"### Added\n\n- {entry}\n\n", 1)
    problem = release.sdk_entry_problem({"fixed": ["f"]}, text, "1.7.1")
    assert (problem is None) is ok
    if not ok:
        assert "sr_core.scene and 1.7.1" in problem


def test_sdk_entry_for_an_older_release_does_not_satisfy_a_newer_one():
    text = TOOLS_LOG.replace("### Added\n\n", "### Added\n\n- Regenerates `sr_core.scene` for 1.7.1.\n\n", 1)
    assert release.sdk_entry_problem({"fixed": ["f"]}, text, "1.7.1") is None
    assert release.sdk_entry_problem({"added": ["a"]}, text, "1.8.0") is not None


@pytest.fixture
def release_root(tmp_root, monkeypatch):
    (tmp_root / "sr_core").mkdir(exist_ok=True)
    (tmp_root / "sr_core/__init__.py").write_text('__version__ = "1.7.0"\n')
    xsd = tmp_root / "schema/scene-render.xsd"       # releases from 1.7.0, whatever the checkout's schema version is
    xsd.write_text(re.sub(r'(<xs:schema\b[^>]*\bversion=")[^"]+(")', r"\g<1>1.7.0\2", xsd.read_text(), count=1))
    schema_log = LOG.replace("1.4.2", "1.7.0")
    (tmp_root / "schema/CHANGELOG.md").write_text(schema_log)
    (tmp_root / "CHANGELOG.md").write_text(TOOLS_LOG)
    calls = []
    monkeypatch.setattr(release, "refresh_schema", lambda: calls.append("refresh"))
    return tmp_root, calls


def run_release(capsys):
    rc = release.main(["release", "schema", "--date", "2026-10-13"])
    return rc, capsys.readouterr().err


def test_release_schema_refused_without_an_sdk_entry(release_root, capsys):
    root, calls = release_root
    rc, err = run_release(capsys)
    assert rc == 2 and "mentions sr_core.scene" in err
    assert calls == [] and "## Unreleased" in (root / "schema/CHANGELOG.md").read_text()
    assert "1.7.1" not in (root / "schema/CHANGELOG.md").read_text()


def test_release_schema_refused_with_the_wrong_class(release_root, capsys):
    root, calls = release_root
    (root / "CHANGELOG.md").write_text(TOOLS_LOG.replace("### Fixed\n\n", "### Fixed\n\n- `sr_core.scene` regenerated for 1.7.1\n\n", 1))
    rc, err = run_release(capsys)
    assert rc == 2 and "under Added" in err and "found under fixed" in err
    assert "1.7.1" not in (root / "schema/CHANGELOG.md").read_text()


def test_release_schema_allowed_with_the_right_class(release_root, capsys):
    root, calls = release_root
    (root / "CHANGELOG.md").write_text(TOOLS_LOG.replace("### Added\n\n", "### Added\n\n- `sr_core.scene` regenerated for 1.7.1\n\n", 1))
    rc, err = run_release(capsys)
    assert rc == 0 and err == ""
    assert "## 1.7.1 — 2026-10-13" in (root / "schema/CHANGELOG.md").read_text()
    assert calls == ["refresh"]


def test_release_tools_needs_no_sdk_entry(release_root, capsys):
    root, _ = release_root
    (root / "CHANGELOG.md").write_text(TOOLS_LOG.replace("### Fixed\n\n", "### Fixed\n\n- a fix\n\n", 1))
    assert release.main(["release", "tools", "--date", "2026-10-13"]) == 0


# ---------------------------------------------------------------------------------------------- publish
RELEASED_LOG = """# Changelog

## Unreleased

### Breaking

### Added

### Fixed

## 1.8.0 — 2026-10-20

### Added

- `publish`
- second entry

### Fixed

- a fix

## 1.7.0 — 2026-10-12

### Added

- older
"""


def test_notes_are_the_versions_changelog_section():
    assert release.notes(RELEASED_LOG, "1.8.0") == "### Added\n\n- `publish`\n- second entry\n\n### Fixed\n\n- a fix\n"
    assert release.notes(RELEASED_LOG, "1.7.0") == "### Added\n\n- older\n"


def test_notes_of_an_unreleased_version_are_an_error():
    with pytest.raises(release.ReleaseError, match="no '## 1.9.0' section"):
        release.notes(RELEASED_LOG, "1.9.0")
    with pytest.raises(release.ReleaseError, match="no '## 1.8' section"):
        release.notes(RELEASED_LOG, "1.8")      # a prefix is not a version


class FakeGit:
    """`git` answers for a tag that exists locally and on origin, with RELEASED_LOG at it."""
    def __init__(self, local=("v1.8.0", "schema-1.7.1"), remote=("v1.8.0", "schema-1.7.1")):
        self.local, self.remote, self.calls = set(local), set(remote), []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "rev-parse":
            tag = args[-1].removeprefix("refs/tags/")
            if tag not in self.local:
                raise subprocess.CalledProcessError(128, args)
            return b"0123456789abcdef\n"
        if args[0] == "ls-remote":
            return (f"0123456789abcdef\trefs/tags/{args[-1]}\n" if args[-1] in self.remote else "").encode()
        if args[0] == "show":
            return RELEASED_LOG.replace("1.8.0", args[1].split(":")[0].lstrip("v").removeprefix("schema-")).encode()
        raise AssertionError(args)


class FakeGh:
    """`gh` answers: `release view` fails for a tag without a release; `release create` prints the URL."""
    def __init__(self, existing=()):
        self.existing, self.calls = set(existing), []

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if args[:3] == ["gh", "release", "view"]:
            rc = 0 if args[3] in self.existing else 1
            return subprocess.CompletedProcess(args, rc, b"", b"release not found\n")
        if args[:3] == ["gh", "release", "create"]:
            return subprocess.CompletedProcess(args, 0, f"https://github.com/x/y/releases/tag/{args[3]}\n".encode(), b"")
        raise AssertionError(args)


@pytest.fixture
def publish_env(monkeypatch, tmp_path):
    git, gh = FakeGit(), FakeGh()
    monkeypatch.setattr(release, "_git", git)
    monkeypatch.setattr(release.subprocess, "run", gh)      # no test may reach the real gh
    monkeypatch.setattr(release, "archive", lambda ref, out: (str(tmp_path / f"scene-render-schema-{ref.removeprefix('schema-')}.tar.gz"), "ab" * 32))
    # COMPONENTS captured the version readers at import: patch the table entries, not the module names, so the
    # tests do not depend on the checkout's versions
    monkeypatch.setitem(release.COMPONENTS["tools"], "get", lambda: "1.8.0")
    monkeypatch.setitem(release.COMPONENTS["schema"], "get", lambda: "1.7.1")
    return git, gh


def test_publish_tools_creates_the_release_from_the_changelog(publish_env, tmp_path):
    git, gh = publish_env
    url = release.publish("tools", None, run=gh, out_dir=str(tmp_path))
    assert url == "https://github.com/x/y/releases/tag/v1.8.0"
    create = [c for c in gh.calls if c[:3] == ["gh", "release", "create"]]
    assert len(create) == 1
    cmd = create[0]
    assert cmd[3] == "v1.8.0" and "--verify-tag" in cmd
    assert cmd[cmd.index("--title") + 1] == "sr-core 1.8.0"
    notes_file = cmd[cmd.index("--notes-file") + 1]
    assert open(notes_file, encoding="utf-8").read() == release.notes(RELEASED_LOG, "1.8.0")
    assert not any(a.endswith(".tar.gz") for a in cmd)
    assert ("ls-remote", "--tags", "origin", "v1.8.0") in git.calls


def test_publish_schema_attaches_the_archive_and_its_sha256(publish_env, tmp_path):
    git, gh = publish_env
    url = release.publish("schema", "1.7.1", run=gh, out_dir=str(tmp_path))
    assert url.endswith("/schema-1.7.1")
    cmd = [c for c in gh.calls if c[:3] == ["gh", "release", "create"]][0]
    assert cmd[cmd.index("--title") + 1] == "scene-render schema 1.7.1"
    tarball = str(tmp_path / "scene-render-schema-1.7.1.tar.gz")
    assert cmd[-2:] == [tarball, tarball + ".sha256"]


def test_publish_refuses_a_tag_that_is_not_on_origin(publish_env, tmp_path, monkeypatch):
    git, gh = publish_env
    git.remote.discard("v1.8.0")
    with pytest.raises(release.ReleaseError, match="v1.8.0 is not on origin"):
        release.publish("tools", None, run=gh, out_dir=str(tmp_path))
    assert not any(c[:3] == ["gh", "release", "create"] for c in gh.calls)


def test_publish_refuses_a_missing_tag(publish_env, tmp_path):
    git, gh = publish_env
    with pytest.raises(release.ReleaseError, match="no tag v1.9.0"):
        release.publish("tools", "1.9.0", run=gh, out_dir=str(tmp_path))
    assert gh.calls == []


def test_publish_refuses_an_existing_release(publish_env, tmp_path, monkeypatch):
    git, gh = publish_env
    gh.existing.add("v1.8.0")
    with pytest.raises(release.ReleaseError, match="release v1.8.0 exists"):
        release.publish("tools", None, run=gh, out_dir=str(tmp_path))
    assert not any(c[:3] == ["gh", "release", "create"] for c in gh.calls)


def test_publish_reports_gh_failures(publish_env, tmp_path):
    git, gh = publish_env

    def failing(args, **kw):
        if args[:3] == ["gh", "release", "create"]:
            return subprocess.CompletedProcess(args, 1, b"", b"HTTP 403: forbidden\n")
        return gh(args, **kw)
    with pytest.raises(release.ReleaseError, match="gh release create failed: HTTP 403"):
        release.publish("tools", None, run=failing, out_dir=str(tmp_path))


def test_publish_command_prints_the_url(publish_env, tmp_path, monkeypatch, capsys):
    git, gh = publish_env
    assert release.main(["publish", "tools", "-o", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "https://github.com/x/y/releases/tag/v1.8.0"
    git.remote.discard("v1.8.0")
    assert release.main(["publish", "tools", "-o", str(tmp_path)]) == 2
    assert "not on origin" in capsys.readouterr().err
