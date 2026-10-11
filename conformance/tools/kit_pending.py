"""Which kit cases of SREPs 66 to 85 and 89 are pending, and why (SREP 0: an active implementer that cannot pass a case yet
is marked pending, and the SREP stays Accepted until none is).

The case generators (srep66_cases.py to srep75_reference.py, engine_gap_cases.py, srep82_cases.py, srep83_cases.py,
srep84_cases.py, srep85_cases.py, srep89_cases.py) call settle() before they write their srep_cases/*.json: a case named in PENDING
keeps "pending" with its reason, and every other case runs. When the Rust reference passes a case, delete its entry
here and rerun the generator.

Recorded 2026-10-11 from conformance/run.py with every "pending" removed, against sr-core cba5808 (SREPs 66 to 85 and
89), on a release build of rs-scene-render release/0.4.0 at 6e0e4f71 (its later commits up to 57ee6293, the reference
build for schema 1.6.0, change tests only), on llvmpipe (sr-prod-01): every case of those SREPs not listed here passes.
Only two kinds of case stay pending: those whose check run.py cannot express yet (a failed render with an error code,
SREPs 66 and 69; a comparison with another render, SREP 71), each checked by hand on the reference with the result
given in its reason, and the one case the reference fails, SREP 72's PREC1.

Earlier records: SREPs 66 to 75 and 82 on rs-scene-render main 82ad2091 and b7eb4edc (2026-10-10); SREP 84 on main
a8310ca7 and its branch prep/srep-84-boolean-forms (ea8750bd); SREP 85 on release/0.4.0 a86e3c72 and v0.3.2 (a6f158e2),
before release/0.4.0 carried prep/srep-85-decimal-forms (ceffcb57); SREP 89 on main 1c989c9f (2026-10-11). The pending
entries for SREPs 76, 77, 80 and 83 to 85 that those runs needed were removed on 2026-10-11, when release/0.4.0 passed
them.
"""

_FAILURE = ("the expected result is a failed render with the error code in 'failure', which expected.json and run.py "
            "cannot check yet; the Rust reference fails the render with {code} (main 82ad2091 and b7eb4edc, and "
            "release/0.4.0 at 6e0e4f71, checked by hand on 2026-10-10 and 2026-10-11)")
_RENDER_COMPARISON = ("the check is a comparison with another render, which run.py cannot express yet; checked by hand "
                      "on the Rust reference (release/0.4.0 at 6e0e4f71, 2026-10-11): {what}")

PENDING = {
    # SREP 66 and 69: failed renders
    **{f"srep-0066-program-{slug}": _FAILURE.format(code=code) for slug, code in [
        ("fuel", "PRG12"), ("import-forbidden", "PRG11"), ("threads-forbidden", "PRG11"),
        ("relaxed-simd-forbidden", "PRG11"), ("output-invalid", "PRG14"), ("id-collision", "PRG14"),
        ("sha256-mismatch", "PRG10"), ("output-sha256-mismatch", "PRG15")]},
    "srep-0069-step-missing-export": _FAILURE.format(code="PRG11"),
    # SREP 71: render comparisons
    "srep-0071-subsurface-zero-neutral": _RENDER_COMPARISON.format(
        what='with subsurface="0" the render is pixel-identical to the scene without the subsurface attributes'),
    "srep-0071-subsurface-wraps-terminator": _RENDER_COMPARISON.format(
        what='with subsurface="1", 20574 pixels are brighter than with "0" and none darker, and the lit span on row 180 '
             'reaches column 400 instead of 364'),
    # SREP 72: the one case the reference fails
    "srep-0072-precision-3d-note": ("the Rust reference (main 82ad2091 and b7eb4edc, and release/0.4.0 at 6e0e4f71) "
                                    "reports E23 for this document, not the information finding PREC1 that SREP 72 "
                                    "requires; it has no PREC1 code"),
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
