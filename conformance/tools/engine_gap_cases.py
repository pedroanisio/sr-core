#!/usr/bin/env python3
"""Writes the kit cases of SREPs 76 to 80 (srep_cases/srep-00NN.json and their assets) from the reference engine's
validation corpus, so that the cases are the documents the engine's own corpus test already holds.

  python3 conformance/tools/engine_gap_cases.py --engine-repo ../rs-scene-render --engine-ref 4bf7a9e
  python3 conformance/make_cases.py

Every invalid corpus document whose expected codes include a rule of an SREP becomes a findings case of that SREP:
{"valid": false, "codes": [its Schematron rule ids]} (the engine's warnings in the corpus entry, such as W09, are
left out: they are not what the case checks). The valid corpus documents that use an SREP's syntax become
{"valid": true} cases, with the warnings the corpus expects of them (W03 to W10) as codes. Asset paths "../media/<f>" become "../assets/<prefix>-<f>", and the files are copied.
The "<!-- expect: ... -->" line of a corpus document is dropped; nothing else changes.
"""
import argparse
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.dirname(HERE)

RULES = {
    76: r"BH\d+",
    77: r"CRT(4|10|11|12)|FRX[567]",
    78: r"PYRO(9|10|11)|PYC[56]",
    79: r"OCN14",
    80: r"VOX\d+|CRT(5|1[3-7])|FRX(3|4|8|9|1\d)",
}
VALID = {
    76: ["black-hole", "black-hole-disk-at-isco", "black-hole-without-disk", "w03-no-lens", "w04-denoise", "w05-lights"],
    77: ["crater-mantle", "crater-mantle-bulking", "crater-repose", "fracture-contact", "fracture-contact-tuned",
         "ocean-density"],
    78: ["pyro-follow", "pyro-blast", "pyro-blast-gas"],
    79: ["volume-scatter-bounces", "volume-scatter-bounces-zero", "whitewater-foam-albedo", "w06-foam-material",
         "w07-foam-raster", "w08-foam-unlit", "w10-scatter-black-albedo"],
    80: ["voxels", "voxels-from-mesh", "voxels-srvol", "voxels-srvol-format", "voxels-surface-memory", "voxel-body",
         "voxel-crater", "voxel-crater-signed-scale", "voxel-ejecta", "voxel-fracture", "voxel-fracture-labels",
         "voxel-fracture-planes", "voxel-fracture-stress", "w09-voxel-cells-small"],
}
SCHEMATRON_CODE = re.compile(r"^(BH|VOX|CRT|FRX|PYRO|PYC|OCN|P3D)\d+$")
# The amendments of SREPs 76 and 80: BH1 and VOX1 refuse only the versions before 1.3. These cases are a valid corpus
# document with nothing but scene/@version changed: to 1.4 and 1.5, which the amended gate accepts, and to 1.0 and
# 1.1, which it still refuses (the corpus's own bh1-version and vox1-version are 1.2). sr-core's schema up to 1.5.0
# has no version 1.6, so no case uses it; the engine's corpus has black-hole-version-1.6 and voxels-version-1.6.
LATER = {76: ("black-hole", "BH1"), 80: ("voxels", "VOX1")}
LATER_VERSIONS = {"1.4": True, "1.5": True, "1.0": False, "1.1": False}


def show(repo, ref, path, binary=False):
    out = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], check=True, capture_output=True).stdout
    return out if binary else out.decode()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine-repo", required=True)
    ap.add_argument("--engine-ref", default="4bf7a9e")
    args = ap.parse_args()
    repo, ref = args.engine_repo, args.engine_ref
    commit = subprocess.run(["git", "-C", repo, "rev-parse", "--short=7", ref], check=True, capture_output=True,
                            text=True).stdout.strip()
    manifest = json.loads(show(repo, ref, "tests/corpus/manifest.json"))
    assets = {}

    def convert(text, srep):
        text = re.sub(r"^<!-- expect:[^>]*-->\n", "", text, flags=re.M)
        for f in re.findall(r'"\.\./media/([^"]+)"', text):
            name = assets.setdefault(f, f"srep{srep}-{f}")
            text = text.replace(f'"../media/{f}"', f'"../assets/{name}"')
        return text

    for srep, pattern in RULES.items():
        rule = re.compile(rf"^({pattern})$")
        cases = {}
        for f, codes in sorted(manifest["invalid"].items()):
            mine = [c for c in codes if rule.match(c)]
            if not mine:
                continue
            stem = f[:-len(".scene.xml")]
            text = convert(show(repo, ref, f"tests/corpus/invalid/{f}"), srep)
            cases[f"srep-{srep:04d}-{stem}"] = {"xml": text, "expected": {
                "rule": f"SREP {srep} " + " ".join(mine),
                "source": f"engine corpus tests/corpus/invalid/{f} at {commit}",
                "findings": {"valid": False, "codes": [c for c in codes if SCHEMATRON_CODE.match(c)]}}}
        for stem in VALID[srep]:
            f = f"{stem}.scene.xml"
            kind = next((k for k in ("valid", "warnings") if f in manifest[k]), None)
            if kind is None:
                raise SystemExit(f"{f} is not a valid corpus document at {ref}")
            text = convert(show(repo, ref, f"tests/corpus/valid/{f}"), srep)   # warnings documents are in valid/ too
            findings = {"valid": True}
            if manifest[kind][f]:
                findings["codes"] = manifest[kind][f]
            cases[f"srep-{srep:04d}-valid-{stem}"] = {"xml": text, "expected": {
                "rule": f"SREP {srep}", "source": f"engine corpus tests/corpus/valid/{f} ({kind}) at {commit}",
                "findings": findings}}
        if srep in LATER:
            stem, gate = LATER[srep]
            f = f"{stem}.scene.xml"
            base = convert(show(repo, ref, f"tests/corpus/valid/{f}"), srep)
            assert base.count('<scene version="1.3">') == 1, f
            for version, valid in LATER_VERSIONS.items():
                text = base.replace('<scene version="1.3">', f'<scene version="{version}">')
                source = f"engine corpus tests/corpus/valid/{f} at {commit}, scene/@version {version}"
                if valid:
                    cases[f"srep-{srep:04d}-valid-{stem}-version-{version}"] = {"xml": text, "expected": {
                        "rule": f"SREP {srep} {gate} (amendment)", "source": source,
                        "findings": {"valid": True}}}
                else:
                    cases[f"srep-{srep:04d}-{gate.lower()}-version-{version}"] = {"xml": text, "expected": {
                        "rule": f"SREP {srep} {gate}", "source": source,
                        "findings": {"valid": False, "codes": [gate]}}}
        with open(os.path.join(CONF, "srep_cases", f"srep-{srep:04d}.json"), "w") as fh:
            json.dump(cases, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print(f"SREP {srep}: {len(cases)} cases")
    for f, name in sorted(assets.items()):
        with open(os.path.join(CONF, "srep_cases", "assets", name), "wb") as fh:
            fh.write(show(repo, ref, f"tests/corpus/media/{f}", binary=True))
    print(f"{len(assets)} assets: {', '.join(sorted(assets.values()))}")


if __name__ == "__main__":
    main()
