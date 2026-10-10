"""Which kit cases of SREPs 66 to 84 are pending, and why (SREP 0: an active implementer that cannot pass a case yet
is marked pending, and the SREP stays Accepted until none is).

The case generators (srep66_cases.py to srep75_reference.py, engine_gap_cases.py, srep82_cases.py, srep83_cases.py,
srep84_cases.py) call settle() before they write their srep_cases/*.json: a case named in PENDING keeps "pending" with its reason, and
every other case runs. When the Rust reference passes a case, delete its entry here and rerun the generator.

Recorded 2026-10-10 from conformance/run.py with "pending" removed, on rs-scene-render main 82ad2091 (SREPs 66 to 75)
and b7eb4edc (all), on llvmpipe (sr-prod-01): every case of SREPs 66 to 75 and 82 not listed here passes on both
(SREP 82's on b7eb4edc, which merged its reference implementation), as do the cases of SREPs 76 to 80 and 83 not
listed here. SREP 73's two sprite cases were rewritten on 2026-10-10 with a sprite drawn one texel per pixel (the
earlier 8 x 8 sprite, magnified five times, measured the engine's filtering, which SREP 73 does not specify); they pass
on v0.3.1 (1ae5ce10), which draws the earlier case exactly as main 82ad2091 and b7eb4edc did (the same centroids,
extents and pixel counts), so they are not pending.

SREP 84, recorded 2026-10-10 the same way on rs-scene-render main a8310ca7 and on its branch prep/srep-84-boolean-forms
(ea8750bd, the reference implementation), on llvmpipe (sr-prod-01): all 32 cases pass on the branch; on main the 13
not listed here pass (those whose verdict SREP 84 does not change, and srep-0084-geo2-tile-size-plus-64, since main's
native GEO2 already reads "+64" as 64), and the 19 listed fail with the literal reading.
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
_SREP84 = ("the Rust reference implements SREP 84 on its branch prep/srep-84-boolean-forms (ea8750bd), not yet on main; "
           "main (a8310ca7) {got}")

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
    "srep-0083-srep77-crater-mantle-version-1.5": _SREP83.format(got="CRT1"),
    "srep-0083-srep77-fracture-contact-version-1.5": _SREP83.format(got="FRX1"),
    "srep-0083-srep77-ocean-density-version-1.5": _SREP83.format(got="OCN1"),
    "srep-0083-srep78-pyro-follow-version-1.5": _SREP83.format(got="V8"),
    "srep-0083-srep79-volume-scatter-bounces-version-1.5": _SREP83.format(got="V8"),
    "srep-0083-srep80-voxel-crater-version-1.5": _SREP83.format(got="CRT1 and VOX1"),
    "srep-0083-srep80-voxel-fracture-version-1.5": _SREP83.format(got="FRX1 and VOX1"),
    # SREP 84: main reads these attributes by their spelling
    **{f"srep-0084-{c}": _SREP84.format(got=got) for c, got in [
        ("c15-reverse-0", "refuses the document with C15"),
        ("c15-reverse-padded-false", "refuses the document with C15"),
        ("c15-loop-00", "refuses the document with C15"),
        ("c15-loop-plus-0", "refuses the document with C15"),
        ("c15-loop-padded-0", "refuses the document with C15"),
        ("c43-alpha-1", "does not report C43"),
        ("c43-alpha-padded-true", "does not report C43"),
        ("r15-has-audio-padded-true", "reports R15"),
        ("r15-has-audio-padded-1", "reports R15"),
        ("r48-from-threed-1", "does not report R48-from"),
        ("r48-from-threed-padded-true", "does not report R48-from"),
        ("r48-to-threed-1", "does not report R48-to"),
        ("vol5-blackbody-padded-true", "does not report VOL5"),
        ("vol5-blackbody-padded-1", "does not report VOL5"),
        ("c80-from-plus-0", "refuses the document with C80"),
        ("c80-step-plus-1", "refuses the document with C80"),
        ("pyro9-follow-padded-true-closed", "reports PYRO10, not PYRO9"),
        ("pyro10-follow-padded-1", "refuses the document with PYRO10"),
        ("pyro11-margin-plus-2", "refuses the document with PYRO11")]},
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
