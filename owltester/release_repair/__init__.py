"""Guided release repair (SPEC-audit-repair.md).

Turns a finished audit report into a fix plan, lets the user decide each
remedy, applies only the accepted changes to a copy of the release, and proves
the result with a second audit.

Modules:
    model     Remedy, RemedyOption, Plan (plain dataclasses, JSON round-trip)
    ops       the closed set of change operations and their guards
    catalog   remedy builders, one per finding code
    planner   build a plan from a report and a release, record decisions
    apply     apply a plan to a copy of the release, write outputs, re-audit
    storage   plan sidecars under uploads/audits/<job_id>/repair/<plan_id>/
    access    who may repair (REPAIR_ALLOWED_USERS, fail closed) and plan roles
"""
