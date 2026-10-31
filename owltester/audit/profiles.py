"""Audit profiles (SPEC-audit.md, section 7).

A profile is a small dict: which stages run, how BFO alignment counts, which
gate stages run, severity overrides, placeholder hosts and the data-set names
treated as legacy.
"""

import copy

ALL_STAGES = ("R1", "R2", "R2b", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10")

PLACEHOLDER_HOSTS = ("example.org", "example.com", "example.net", "example.edu",
                     "localhost", "127.0.0.1", "system.org", "tempuri.org")
LEGACY_NAMES = ("other", "legacy", "old", "deprecated", "archive", "obsolete")

_BASE = {
    "stages": ALL_STAGES,
    "bfo": "advisory",          # advisory | gate
    "gate": (),                 # gate stages (A..E) run beside the audit
    "reason_with_bfo": False,   # attach vendored BFO to the TBox for R3
    "severity_overrides": {},
    "placeholder_hosts": PLACEHOLDER_HOSTS,
    "legacy_names": LEGACY_NAMES,
    "lenses": ("law",),
}

PROFILES = {
    "general": {**_BASE},
    "bfo": {**_BASE, "bfo": "gate", "gate": ("B",), "reason_with_bfo": True},
    "sool": {**_BASE, "bfo": "gate", "gate": ("A", "B", "C", "D", "E"),
             "reason_with_bfo": True, "lenses": ("law", "sool")},
}


def get_profile(name="general"):
    if name not in PROFILES:
        raise ValueError(f"unknown profile {name!r}; choose one of {', '.join(PROFILES)}")
    p = copy.deepcopy(PROFILES[name])
    p["name"] = name
    return p
