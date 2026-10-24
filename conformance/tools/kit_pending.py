"""Which kit cases of SREPs 66 to 85, 87 and 89 are pending, and why (SREP 0: an active implementer that cannot pass a case yet
is marked pending, and the SREP stays Accepted until none is).

The case generators (srep66_cases.py to srep75_reference.py, engine_gap_cases.py, srep82_cases.py, srep83_cases.py,
srep84_cases.py, srep85_cases.py, srep87_cases.py, srep89_cases.py) call settle() before they write their srep_cases/*.json: a case named in PENDING
keeps "pending" with its reason, and every other case runs. When the Rust reference passes a case, delete its entry
here and rerun the generator.

Recorded 2026-10-11 from conformance/run.py with every "pending" removed, against sr-core cba5808 (SREPs 66 to 85 and
89), on a release build of rs-scene-render release/0.4.0 at 6e0e4f71 (its later commits up to 57ee6293, the reference
build for schema 1.6.0, change tests only), on llvmpipe (sr-prod-01): every case of those SREPs not listed here passes.
Only two kinds of case stayed pending then: those whose check run.py could not express (a failed render with an error
code, SREPs 66 and 69; a comparison with another render, SREP 71), each checked by hand on the reference with the
result given in its reason, and the one case the reference failed then, SREP 72's PREC1 (see below).

Earlier records: SREPs 66 to 75 and 82 on rs-scene-render main 82ad2091 and b7eb4edc (2026-10-10); SREP 84 on main
a8310ca7 and its branch prep/srep-84-boolean-forms (ea8750bd); SREP 85 on release/0.4.0 a86e3c72 and v0.3.2 (a6f158e2),
before release/0.4.0 carried prep/srep-85-decimal-forms (ceffcb57); SREP 89 on main 1c989c9f (2026-10-11). The pending
entries for SREPs 76, 77, 80 and 83 to 85 that those runs needed were removed on 2026-10-11, when release/0.4.0 passed
them.

SREP 87 (accepted 2026-10-11, schema 1.7.0) amends SREP 66. Its reference implementation reached rs-scene-render main
on 2026-10-11 (6602b81d). Recorded from conformance/run.py with every "pending" removed, against sr-core records/85-87,
on a release build of main 6602b81d on llvmpipe (sr-prod-01): every case of SREP 87 passes, and so does the SREP 66
case it amends (srep-0066-program-id-collision, whose scene writes the namespaced id p.g1). As for SREPs 66 and 71,
the cases whose check run.py cannot express (three failed renders and one render comparison) stay pending, each
checked by hand on the reference with the result given in its reason.

SREP 72's PREC1 (srep-0072-precision-3d-note) reached main on 2026-10-11 (285a6931); the same run passes it, and its
entry was removed.

The failed-render cases of SREPs 66, 69 and 87 (eight, one and three cases) left PENDING on 2026-10-24, once run.py
checked the "failure" form they carry: `run.py --run-pending` retires all twelve on a release build of scene-render
main e586b57 (0.7.4, binary sha256 prefix b7285fa1d0fba26f) on llvmpipe. Only render comparisons stay pending.
"""

_RENDER_COMPARISON = ("the check is a comparison with another render, which run.py cannot express yet; checked by hand "
                      "on the Rust reference (release/0.4.0 at 6e0e4f71, 2026-10-11): {what}")

SREP87 = "SREP 87 on rs-scene-render main 6602b81d"
_SREP87_COMPARISON = ("the check is a comparison with another render, which run.py cannot express yet; checked by hand "
                      "on the Rust reference (" + SREP87 + ", 2026-10-11): {what}")

PENDING = {
    # SREP 71: render comparisons
    "srep-0071-subsurface-zero-neutral": _RENDER_COMPARISON.format(
        what='with subsurface="0" the render is pixel-identical to the scene without the subsurface attributes'),
    "srep-0071-subsurface-wraps-terminator": _RENDER_COMPARISON.format(
        what='with subsurface="1", 20574 pixels are brighter than with "0" and none darker, and the lit span on row 180 '
             'reaches column 400 instead of 364'),
    # SREP 87: a render comparison
    "srep-0087-program-ids-seed-local": _SREP87_COMPARISON.format(
        what="the picture at 0.5 s equals that of srep-0087-program-ids-seed-local-by-hand, pixel for pixel"),
    "srep-0087-program-ids-seed-local-by-hand": _SREP87_COMPARISON.format(
        what="the reference picture of srep-0087-program-ids-seed-local, which equals it pixel for pixel at 0.5 s"),
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
