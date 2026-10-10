"""Which kit cases of SREPs 66 to 83 are pending, and why (SREP 0: an active implementer that cannot pass a case yet
is marked pending, and the SREP stays Accepted until none is).

The case generators (srep66_cases.py to srep75_reference.py, engine_gap_cases.py, srep82_cases.py, srep83_cases.py)
call settle() before they write their srep_cases/*.json: a case named in PENDING keeps "pending" with its reason, and
every other case runs. When the Rust reference passes a case, delete its entry here and rerun the generator.

Recorded 2026-10-10 from conformance/run.py with "pending" removed, on rs-scene-render main 82ad2091 (SREPs 66 to 75)
and b7eb4edc (all), on llvmpipe (sr-prod-01): every case of SREPs 66 to 75 and 82 not listed here passes on both
(SREP 82's on b7eb4edc, which merged its reference implementation), as do the cases of SREPs 76 to 80 and 83 not
listed here.
"""

_FAILURE = ("the expected result is a failed render with the error code in 'failure', which expected.json and run.py "
            "cannot check yet; the Rust reference (main 82ad2091 and b7eb4edc) fails the render with {code}, checked by "
            "hand on 2026-10-10")
_RENDER_COMPARISON = ("the check is a comparison with another render, which run.py cannot express yet; not checked on "
                      "the Rust reference")
_FOLLOWUPS = ("the Rust reference implements {what} on its branch prep/srep-76-81-followups, not yet on main; main "
              "(b7eb4edc) {got}")
_SREP83 = ("the Rust reference implements SREP 83 on its branch prep/srep-83-version-gates (6f9d13c0), not yet on main; "
           "main (b7eb4edc) refuses the document with {got}")

PENDING = {
    # SREP 66 and 69: failed renders
    **{f"srep-0066-program-{slug}": _FAILURE.format(code=code) for slug, code in [
        ("fuel", "PRG12"), ("import-forbidden", "PRG11"), ("threads-forbidden", "PRG11"),
        ("relaxed-simd-forbidden", "PRG11"), ("output-invalid", "PRG14"), ("id-collision", "PRG14"),
        ("sha256-mismatch", "PRG10"), ("output-sha256-mismatch", "PRG15")]},
    "srep-0069-step-missing-export": _FAILURE.format(code="PRG11"),
    # SREP 71: render comparisons
    "srep-0071-subsurface-zero-neutral": _RENDER_COMPARISON,
    "srep-0071-subsurface-wraps-terminator": _RENDER_COMPARISON,
    # SREP 72
    "srep-0072-precision-3d-note": ("the Rust reference (main 82ad2091 and b7eb4edc) reports E23 for this document, not "
                                    "the information finding PREC1 that SREP 72 requires"),
    # SREP 73
    **{f"srep-0073-{slug}": ("the Rust reference (main 82ad2091 and b7eb4edc) keeps the sprite upright as SREP 73 "
                             f"requires ({order}), but its red half measures 17 px across where the case expects 20 "
                             "(tolerance 2; blue 18 px): the case's assumption that the sprite is drawn as an unfiltered "
                             "size x size square is not checked")
       for slug, order in [("upright-sprite", "red left of blue"), ("upright-sprite-node-rotation", "red above blue")]},
    # SREPs 76, 77 and 80: the amendments
    "srep-0076-valid-w11-no-lens": _FOLLOWUPS.format(what="the warning numbers W11 and W12 (c2a66950)", got="reports W03"),
    "srep-0076-valid-w12-denoise": _FOLLOWUPS.format(what="the warning numbers W11 and W12 (c2a66950)", got="reports W04"),
    **{f"srep-0076-valid-black-hole-version-{v}": _FOLLOWUPS.format(what="BH1 for version 1.3 or later (c2a66950)",
                                                                    got="refuses the document with BH1")
       for v in ("1.4", "1.5")},
    **{f"srep-0076-{c}": _FOLLOWUPS.format(what="the boolean forms of geodesics (298bddd6)",
                                           got=f"does not report {c[:3].upper()}")
       for c in ("bh5-geodesics-1-without-hole", "bh6-geodesics-1-other-object",
                 "bh7-geodesics-1-inside-photon-sphere", "bh8-geodesics-1-and-true")},
    "srep-0077-crt12-repose-with-mantle-1": _FOLLOWUPS.format(what="the boolean forms of mantle (f91dbfcc)",
                                                              got="does not report CRT12"),
    "srep-0077-valid-crater-mantle-1-bulking": _FOLLOWUPS.format(what="the boolean forms of mantle (f91dbfcc)",
                                                                 got="refuses the document with CRT11"),
    **{f"srep-0080-valid-voxels-version-{v}": _FOLLOWUPS.format(what="VOX1 for version 1.3 or later (c2a66950)",
                                                                got="refuses the document with VOX1")
       for v in ("1.4", "1.5")},
    # SREP 83
    **{f"srep-0083-{gate.lower()}-version-{v}": _SREP83.format(got=gate)
       for gate in ("V8", "MSQ1", "P3D1", "OCN1", "CRT1", "FRX1", "GEO1") for v in ("1.4", "1.5")},
    **{f"srep-0083-msq1-version-{v}": _SREP83.format(got="MSQ1") + (
        "; it also reports A04, because the case (from srep-0040-msq1-rejected) names ../media/mesh-frame-%d.obj, "
        "which the kit does not carry, so the case needs that asset before it can pass on any engine")
       for v in ("1.4", "1.5")},
    "srep-0083-srep77-crater-mantle-version-1.5": _SREP83.format(got="CRT1"),
    "srep-0083-srep77-fracture-contact-version-1.5": _SREP83.format(got="FRX1"),
    "srep-0083-srep77-ocean-density-version-1.5": _SREP83.format(got="OCN1"),
    "srep-0083-srep78-pyro-follow-version-1.5": _SREP83.format(got="V8"),
    "srep-0083-srep79-volume-scatter-bounces-version-1.5": _SREP83.format(got="V8"),
    "srep-0083-srep80-voxel-crater-version-1.5": _SREP83.format(got="CRT1 and VOX1"),
    "srep-0083-srep80-voxel-fracture-version-1.5": _SREP83.format(got="FRX1 and VOX1"),
}


def settle(cases: dict, srep: int) -> dict:
    """Set or drop "pending" on the cases of one SREP from PENDING; every name PENDING lists for it must exist."""
    prefix = f"srep-{srep:04d}-"
    unknown = {n for n in PENDING if n.startswith(prefix)} - set(cases)
    assert not unknown, f"PENDING names cases that do not exist: {sorted(unknown)}"
    for name, case in cases.items():
        if name in PENDING:
            case["expected"]["pending"] = PENDING[name]
        else:
            case["expected"].pop("pending", None)
    return cases
