"""Failure taxonomy and exit codes for the owltesterservice gate.

These mirror section 5 of owltesterservice-spec.md. Each code is both a stable
string (used in JSON reports and tests) and maps to a process exit code for the
CLI gate. The whole point of the gate is that the destructive-autofix outcome
(axioms in, zero axioms out) is a guaranteed non-zero exit, never a pass.
"""

# Stage A — structural smoke test
E_NO_AXIOMS = "E_NO_AXIOMS"        # A1: artifact has no logical axioms
E_FLAT = "E_FLAT"                  # A2/A3: no subClassOf / no object-property axioms
E_NO_BFO = "E_NO_BFO"              # A4: BFO anchors absent or unpopulated
E_BLOATED = "E_BLOATED"            # A5: class count exceeds kernel x max_factor
E_ANTIPATTERN = "E_ANTIPATTERN"    # A6/D4: privation/compound class present

# Stage B — BFO grounding
E_ORPHAN = "E_ORPHAN"              # B1: class not grounded to a BFO upper category
E_DISJOINT = "E_DISJOINT"          # B2: Continuant/Occurrent (or other) conflation
E_MISTYPED = "E_MISTYPED"          # B3: node BFO type != kernel

# Stage C — reasoner coherence and non-triviality
E_INCONSISTENT = "E_INCONSISTENT"  # C1: reasoner inconsistency (+ MUPS)
E_TRIVIAL = "E_TRIVIAL"            # C2: coherent only because vacuous

# Stage D — SOoL competency constraints
E_COMPETENCY = "E_COMPETENCY"      # D: SHACL / competency-question violation

# Stage E — delta invariant (repair / baseline)
E_TRIVIALIZED = "E_TRIVIALIZED"    # E3: input had axioms, output has none
E_OVER_RELAXED = "E_OVER_RELAXED"  # repair removed more than the configured bound

# Operational (not a conformance failure of the artifact itself)
E_PARSE = "E_PARSE"                # artifact could not be parsed at all

DESCRIPTIONS = {
    E_NO_AXIOMS: "artifact has no logical axioms",
    E_FLAT: "no subClassOf / no object-property axioms",
    E_NO_BFO: "BFO anchors absent or unpopulated",
    E_BLOATED: "class count exceeds kernel x max_factor",
    E_ANTIPATTERN: "privation/compound class present",
    E_ORPHAN: "class not grounded to BFO",
    E_DISJOINT: "Continuant/Occurrent conflation",
    E_MISTYPED: "node BFO type does not match kernel",
    E_INCONSISTENT: "reasoner inconsistency",
    E_TRIVIAL: "coherent only because vacuous",
    E_COMPETENCY: "SHACL / competency-question violation",
    E_TRIVIALIZED: "input had axioms, output has none",
    E_OVER_RELAXED: "repair removed more than the bound",
    E_PARSE: "artifact could not be parsed",
}

# Which stage each code belongs to (for the report's stage grouping).
STAGE_OF = {
    E_NO_AXIOMS: "A", E_FLAT: "A", E_NO_BFO: "A", E_BLOATED: "A", E_ANTIPATTERN: "A",
    E_ORPHAN: "B", E_DISJOINT: "B", E_MISTYPED: "B",
    E_INCONSISTENT: "C", E_TRIVIAL: "C",
    E_COMPETENCY: "D",
    E_TRIVIALIZED: "E", E_OVER_RELAXED: "E",
    E_PARSE: "A",
}

# A single non-zero exit code is enough for CI; 1 == "the gate rejected it".
EXIT_PASS = 0
EXIT_FAIL = 1
