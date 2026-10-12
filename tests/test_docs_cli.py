"""The commands and options the docs show are the ones the CLIs have (doc-hygiene audit, 2026-10-12).

docs/vpkg-howto.md had lagged the CLI by five options since 1.0.0. Every long option of `scenerender-vpkg` must
appear in the how-to, and every `python3 -m sr_core...` line of the README must run with `--help`.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBCOMMANDS = ["init", "pack", "verify", "info", "unpack", "fetch", "run"]
# option -> why the how-to leaves it out: the how-to writes the short form
NOT_IN_HOWTO = {"--dry-run": "written -n", "--verbose": "written -v", "--output": "written -o"}


def _help(*argv):
    done = subprocess.run([sys.executable, "-m", *argv, "--help"], cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout


def test_every_long_option_of_scenerender_vpkg_is_in_the_howto():
    howto = open(os.path.join(ROOT, "docs", "vpkg-howto.md"), encoding="utf-8").read()
    options = {o for sub in SUBCOMMANDS for o in re.findall(r"(?<![\w-])--[a-z][a-z-]+", _help("sr_core.vpkg", sub))}
    options -= {"--help"}
    assert len(options) >= 20, options          # the scrape found the options
    missing = sorted(o for o in options if o not in howto and o not in NOT_IN_HOWTO)
    assert missing == [], f"options of scenerender-vpkg that docs/vpkg-howto.md never names: {missing}"


def test_the_howto_names_only_subcommands_that_exist():
    howto = open(os.path.join(ROOT, "docs", "vpkg-howto.md"), encoding="utf-8").read()
    used = set(re.findall(r"scenerender-vpkg (\w+)", howto)) - {"is", "ships", "works"}
    assert used <= set(SUBCOMMANDS), used - set(SUBCOMMANDS)


def test_every_module_command_of_the_readme_runs():
    text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    modules = sorted(set(re.findall(r"^python3 -m (sr_core(?:\.\w+)+)", text, re.M)))
    assert {"sr_core.vpkg", "sr_core.schemadoc", "sr_core.review", "sr_core.scene", "sr_core.scene.generate"} <= set(modules)
    for module in modules:
        done = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT, capture_output=True, text=True)
        assert done.returncode == 0, f"python3 -m {module} --help: {done.stderr.strip()[-200:]}"


def test_the_readme_option_flags_exist():
    text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    checks = {"sr_core.schemadoc": "--check", "sr_core.scene.generate": "--check", "sr_core.review": "--engine",
              "sr_core.scene": "--schema"}
    for module, flag in checks.items():
        assert flag in text
        sub = ["check"] if module == "sr_core.scene" else []
        assert flag in _help(module, *sub), (module, flag)
