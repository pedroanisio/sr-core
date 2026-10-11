"""Which kit cases of SREPs 66 to 85 and 89 are pending, and why (SREP 0: an active implementer that cannot pass a case yet
is marked pending, and the SREP stays Accepted until none is).

The case generators (srep66_cases.py to srep75_reference.py, engine_gap_cases.py, srep82_cases.py, srep83_cases.py,
srep84_cases.py, srep85_cases.py, srep89_cases.py) call settle() before they write their srep_cases/*.json: a case named in PENDING
keeps "pending" with its reason, and every other case runs. When the Rust reference passes a case, delete its entry
here and rerun the generator.

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

SREP 85, recorded 2026-10-10 the same way on rs-scene-render release/0.4.0 (a86e3c72, which merges the branches of
SREPs 76 to 81, 83 and 84 but not prep/srep-85-decimal-forms, ceffcb57, the reference implementation) and on v0.3.2
(a6f158e2), on llvmpipe (sr-prod-01), with the same results on both: the 38 cases not listed here pass (23 whose
verdict SREP 85 does not change, and 15 of PYRO1, PYRO2, PYRO4, VOL4, PYRO11, ITR1, SRT1, OCN3's wavelength and OCN5,
to which the native rules already give their SREP 85 verdict), and the 27 listed fail: 26 whose verdict SREP 85
changes, and srep-0085-ocn5-whitewater-plus-0.5-to-plus-1, valid before and after SREP 85 in the Schematron, which the
native OCN5 refuses. They stay pending until release/0.4.0 carries that branch.

SREP 89, recorded 2026-10-10 at its acceptance: its three cases have not been run on any engine. The reference
implementation is rs-scene-render d7f12a2f, on the branch fix/atlas-findings, not yet on main; there the engine's own
tests of the change (crates/sr-gpu/tests/bloom_hdr.rs) pass on lavapipe, as SREP 89 states. Run the cases on the
reference before deleting their entries.
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
_SREP85 = ("the Rust reference implements SREP 85 on its branch prep/srep-85-decimal-forms (ceffcb57), not yet on "
           "release/0.4.0; release/0.4.0 (a86e3c72) {got}")
_SREP89 = ("the reference implementation is rs-scene-render d7f12a2f, on the branch fix/atlas-findings, not yet on "
           "main; the case has not been run on any engine")
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
        ("c43-alpha-1", "does not report C43; its encoder then refuses the output (H264 cannot carry alpha)"),
        ("c43-alpha-padded-true", "does not report C43; its encoder then refuses the output (H264 cannot carry "
                                   "alpha)"),
        ("r15-has-audio-padded-true", "reports R15"),
        ("r15-has-audio-padded-1", "reports R15"),
        ("r48-from-threed-1", "does not report R48-from"),
        ("r48-from-threed-padded-true", "does not report R48-from"),
        ("r48-to-threed-1", "does not report R48-to"),
        ("vol5-blackbody-padded-true", "does not report VOL5; the render then fails (blackbody requires "
                                        "temperatureGrid)"),
        ("vol5-blackbody-padded-1", "does not report VOL5; the render then fails (blackbody requires "
                                     "temperatureGrid)"),
        ("c80-from-plus-0", "refuses the document with C80"),
        ("c80-step-plus-1", "refuses the document with C80"),
        ("pyro9-follow-padded-true-closed", "reports PYRO10, not PYRO9"),
        ("pyro10-follow-padded-1", "refuses the document with PYRO10"),
        ("pyro11-margin-plus-2", "refuses the document with PYRO11")]},
    # SREP 85: release/0.4.0 reads these decimal and double attributes through XPath 1.0's number(), without the sign
    **{f"srep-0085-{c}": _SREP85.format(got=got) for c, got in [
        ("c13-min-size-plus-0.5", "refuses the document with C13"),
        ("c13-max-size-plus-1", "refuses the document with C13"),
        ("c14-size-plus-1", "refuses the document with C14"),
        ("c14-letter-spacing-plus-0.5", "refuses the document with C14"),
        ("c15-speed-plus-1", "refuses the document with C15"),
        ("c37-offsets-plus-1-then-plus-0.5", "does not report C37"),
        ("c38-times-plus-1-then-plus-0.5", "refuses the document with E04, not C38"),
        ("c44-end-plus-1", "refuses the document with C44"),
        ("c44-start-plus-0.5", "refuses the document with C44"),
        ("c52-end-plus-1", "refuses the document with C52"),
        ("c52-start-plus-0.5", "refuses the document with C52"),
        ("c53-domain-plus-1-then-plus-0.5", "does not report C53"),
        ("c54-start-plus-0", "refuses the document with C54"),
        ("c56-to-plus-1", "refuses the document with C56"),
        ("c56-from-plus-0.5", "refuses the document with C56"),
        ("c56-duration-plus-1", "refuses the document with C56"),
        ("p3d3-lifetime-plus-1", "refuses the document with P3D3"),
        ("p3d3-speed-variance-plus-0.5", "refuses the document with P3D3"),
        ("p3d3-burst-time-plus-0.5", "refuses the document with P3D3"),
        ("p3d10-angle-plus-1-spread-plus-0.5", "refuses the document with P3D10"),
        ("ocn3-cell-size-plus-0.5", "refuses the document with OCN3"),
        ("ocn3-impulse-x-plus-1", "refuses the document with OCN3"),
        ("ocn5-whitewater-plus-0.5-to-plus-1", "refuses the document with OCN5"),
        ("pyc6-x-plus-1", "refuses the document with PYC6"),
        ("pyc6-y-plus-0.5", "refuses the document with PYC6"),
        ("frx11-planes-plus-1", "refuses the document with FRX11"),
        ("frx11-planes-plus-0.5", "refuses the document with FRX11")]},
    # SREP 89: the supersample clamp keeps values above 1
    **{f"srep-0089-supersample-hdr-{slug}": _SREP89 for slug in ("n1", "box-n2", "lanczos3-n3")},
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
