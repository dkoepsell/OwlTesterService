"""Stage E — delta invariant.

Runs only when a baseline (the input artifact's counts) is supplied: on repair,
or on a check given ``--baseline``. This is the stage that makes the exact
SOOL_autofixed.owl outcome a guaranteed build failure.

E1 out.axioms >= in.axioms - |logged_removals|   (any unlogged reduction fails)
E2 out.objectProperties >= in.objectProperties     (unless each drop is logged)
E3 in.axioms > 0 and out.axioms == 0  ->  E_TRIVIALIZED, immediately.
"""

from ..model import StageResult
from .. import errors


def run(ctx):
    r = StageResult("E")
    base = ctx.baseline
    if base is None:
        r.skipped = "no baseline supplied (E runs on repair or with --baseline)"
        return r

    out = ctx.counts
    logged = ctx.removals or []
    n_logged = len(logged)

    # E3 — hard tripwire first; this is the headline failure mode.
    if base.axioms > 0 and out.axioms == 0:
        r.add(errors.E_TRIVIALIZED,
              f"Input had {base.axioms} axioms; output has 0. This is the "
              f"destructive-autofix failure (E_TRIVIALIZED).")
        return r

    # E1 — axiom delta must be accounted for by the removal log.
    floor = base.axioms - n_logged
    if out.axioms < floor:
        r.add(errors.E_TRIVIALIZED if out.axioms == 0 else errors.E_OVER_RELAXED,
              f"Axiom count dropped from {base.axioms} to {out.axioms}, more than "
              f"the {n_logged} logged removal(s) account for (floor {floor}).")

    # E2 — object properties must not silently disappear.
    logged_prop_drops = sum(1 for x in logged if x.get("kind") == "object_property")
    if out.objectProperties < base.objectProperties - logged_prop_drops:
        r.add(errors.E_OVER_RELAXED,
              f"Object properties dropped from {base.objectProperties} to "
              f"{out.objectProperties} with only {logged_prop_drops} logged.")

    r.notes["delta"] = {
        "in_axioms": base.axioms, "out_axioms": out.axioms,
        "logged_removals": n_logged,
        "in_object_properties": base.objectProperties,
        "out_object_properties": out.objectProperties,
    }
    return r
