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

# Full artifact audit (SPEC-audit.md, stages R0..R10)
E_DATATYPE_PROFILE = "E_DATATYPE_PROFILE"    # R2: datatype outside the OWL 2 datatype map
E_UNSAT = "E_UNSAT"                          # R3: named unsatisfiable class
E_ABOX_INCONSISTENT = "E_ABOX_INCONSISTENT"  # R3: data file inconsistent with the TBox
E_SHACL = "E_SHACL"                          # R4: data violates the artifact's own shapes
E_UNDECLARED_TERM = "E_UNDECLARED_TERM"      # R5: owned-namespace IRI never declared
E_NS_MISMATCH = "E_NS_MISMATCH"              # R5: references use a variant of a declared namespace
E_LAYER_CONFLICT = "E_LAYER_CONFLICT"        # R6: OWL, SHACL and documentation disagree
E_SELF_EXAMPLE = "E_SELF_EXAMPLE"            # R7: the artifact's own example fails its shapes
E_REASONER_DISAGREE = "E_REASONER_DISAGREE"  # R3: HermiT and Pellet disagree (tool finding)
W_RANGE = "W_RANGE"                          # R5: value does not fit the declared range
W_UNENFORCED = "W_UNENFORCED"                # R6: documented MUST with no axiom or shape
W_TODO = "W_TODO"                            # R6: TODO/FIXME next to an axiom
W_DOC_TERM = "W_DOC_TERM"                    # R7: documentation names an undeclared term
W_SUBCLASS_COLLAPSE = "W_SUBCLASS_COLLAPSE"  # R8: data uses a superclass, never its subclasses
W_UNUSED_TERM = "W_UNUSED_TERM"              # R8: declared, never used in any data set
W_PLACEHOLDER_IRI = "W_PLACEHOLDER_IRI"      # R8: example.org and similar hosts
W_IDENTITY = "W_IDENTITY"                    # R8: one entity under several IRIs or labels
W_DUPLICATE_NODE = "W_DUPLICATE_NODE"        # R8: identical blank nodes on one subject
W_DOMAIN_RETYPING = "W_DOMAIN_RETYPING"      # R8: class membership only through a domain
W_NO_BFO = "W_NO_BFO"                        # R9: no BFO alignment (advisory)
W_HEADER = "W_HEADER"                        # R10: ontology header incomplete
W_VERSION = "W_VERSION"                      # R10: version numbers disagree
W_CI_NO_SHACL = "W_CI_NO_SHACL"              # R10: shapes ship, CI never runs SHACL
W_CI_NO_REASONER = "W_CI_NO_REASONER"        # R10: CI never runs a reasoner
W_CHANGELOG = "W_CHANGELOG"                  # R10: changelog names files that are absent
W_IMPORT = "W_IMPORT"                        # R0: import could not be resolved locally
W_CONFIG = "W_CONFIG"                        # R0: audit.yaml / audit.json could not be read
W_LINT_NO_CHARACTERISTICS = "W_LINT_NO_CHARACTERISTICS"   # R2b
W_LINT_INVERSE = "W_LINT_INVERSE"                         # R2b
W_LINT_TRANSITIVE = "W_LINT_TRANSITIVE"                   # R2b
W_LINT_DISJOINT = "W_LINT_DISJOINT"                       # R2b
W_LINT_FOREIGN_AXIOM = "W_LINT_FOREIGN_AXIOM"             # R2b
W_LINT_ONEOF_UNA = "W_LINT_ONEOF_UNA"                     # R2b
I_PROFILE = "I_PROFILE"                      # R2: OWL 2 profile membership
I_SHAPES_LINT = "I_SHAPES_LINT"              # R4: problems in the shapes themselves
I_EXTERNAL_REFS = "I_EXTERNAL_REFS"          # R5: references to other namespaces
I_FEATURE_USE = "I_FEATURE_USE"              # R8: feature use matrix

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
    E_DATATYPE_PROFILE: "datatype outside the OWL 2 datatype map",
    E_UNSAT: "named class can have no instances",
    E_ABOX_INCONSISTENT: "data file contradicts the ontology",
    E_SHACL: "data violates the artifact's own shapes",
    E_UNDECLARED_TERM: "term in an owned namespace is never declared",
    E_NS_MISMATCH: "references use a variant of a declared namespace",
    E_LAYER_CONFLICT: "OWL, SHACL and documentation disagree",
    E_SELF_EXAMPLE: "the artifact's own example fails its shapes",
    E_REASONER_DISAGREE: "HermiT and Pellet disagree",
    W_RANGE: "value does not fit the declared range",
    W_UNENFORCED: "documented requirement with no axiom or shape",
    W_TODO: "open TODO or FIXME next to an axiom",
    W_DOC_TERM: "documentation names an undeclared term",
    W_SUBCLASS_COLLAPSE: "data uses a superclass but none of its subclasses",
    W_UNUSED_TERM: "declared but never used in the data",
    W_PLACEHOLDER_IRI: "placeholder IRIs in the data",
    W_IDENTITY: "one entity appears under several IRIs or labels",
    W_DUPLICATE_NODE: "identical blank nodes repeated on one subject",
    W_DOMAIN_RETYPING: "class membership comes only from a property domain",
    W_NO_BFO: "no BFO alignment",
    W_HEADER: "ontology header incomplete",
    W_VERSION: "version numbers disagree",
    W_CI_NO_SHACL: "shapes ship but CI never runs SHACL",
    W_CI_NO_REASONER: "CI never runs a reasoner",
    W_CHANGELOG: "changelog names files that are not in the release",
    W_IMPORT: "import could not be resolved locally",
    W_CONFIG: "audit configuration could not be read",
    W_LINT_NO_CHARACTERISTICS: "no property declares any characteristic",
    W_LINT_INVERSE: "name-paired properties not declared inverse",
    W_LINT_TRANSITIVE: "likely-transitive property not declared transitive",
    W_LINT_DISJOINT: "classes that look disjoint are not declared so",
    W_LINT_FOREIGN_AXIOM: "domain or range added to another vocabulary's property",
    W_LINT_ONEOF_UNA: "value list without distinctness axioms",
    I_PROFILE: "OWL 2 profile membership",
    I_SHAPES_LINT: "problems in the shapes themselves",
    I_EXTERNAL_REFS: "references to other namespaces",
    I_FEATURE_USE: "how the data uses the ontology",
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
