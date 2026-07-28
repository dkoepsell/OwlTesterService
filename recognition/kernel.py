"""The contradiction kernel, the recognition chain, and their product.

Pure data, no logic. Everything downstream (detectors, measure, profile, the
report page) reads its vocabulary from here so that the paper's tables and the
running code cannot drift apart.

Sources, by paper section:
  §5.1/§5.2  CHAIN_LOCI            the recognition chain
  §6.1       KERNEL, STRATA        the twelve primitives in four strata
  §6.2       CLASSIFICATORY_TYPES  kernel x chain, for a classification
  §6.3       INSTRUMENTS           the detectability partition
  §6.4       SYSTEM_CLASSES        the stratum profile as institutional fingerprint
"""

# --- the recognition chain (§5) ----------------------------------------------
#
# A status is conferred by an authority, under criteria, applied by an assessor
# occupying a role, to presenting facts, through a recognition act, producing
# effects, subject to a remedy. Chains differ in *thickness*: a classification
# has no acts of its own and no internal remedy, a legal order has both.

CHAIN_LOCI = [
    {"key": "authority",
     "name": "Authority",
     "gloss": "The institution empowered to confer the status.",
     "clinical": "WHO / the professional association issuing the manual"},
    {"key": "criteria",
     "name": "Criteria",
     "gloss": "The conditions under which the status is conferred.",
     "clinical": "the diagnostic criteria"},
    {"key": "assessor",
     "name": "Assessor in role",
     "gloss": "The occupant licensed to apply the criteria.",
     "clinical": "the clinician"},
    {"key": "facts",
     "name": "Presenting facts",
     "gloss": "What the assessor assesses.",
     "clinical": "the patient's presentation"},
    {"key": "act",
     "name": "Recognition act",
     "gloss": "The act that confers the status.",
     "clinical": "the diagnosis"},
    {"key": "effect",
     "name": "Effect",
     "gloss": "The normative consequences the status carries.",
     "clinical": "treatment entitlement, reimbursement, exemption"},
    {"key": "remedy",
     "name": "Remedy",
     "gloss": "The route by which a wrong conferral is corrected.",
     "clinical": "second opinion, appeal, revision cycle"},
]

LOCUS_KEYS = [locus["key"] for locus in CHAIN_LOCI]


# --- the four strata (§6.1) ---------------------------------------------------

STRATA = [
    {"key": "A", "name": "Logical",
     "gloss": "Failures of the theory as a theory."},
    {"key": "B", "name": "Definitional",
     "gloss": "Failures in how terms are fixed."},
    {"key": "C", "name": "Ontological",
     "gloss": "Failures against the categorial structure of what there is."},
    {"key": "D", "name": "Pragmatic",
     "gloss": "Failures that require acts. Fires only where there are acts."},
]


# --- the twelve primitives (§6.1) ---------------------------------------------
#
# ``instrument`` is not a note about current tooling maturity: per §6.3 the
# partition is a matter of principle. ``partial`` marks a primitive an
# instrument can see only some cases of.

KERNEL = [
    {"id": "K-A1", "stratum": "A", "name": "Inconsistency",
     "definition": "The theory admits no model; some sentence and its negation "
                   "are jointly derivable. Variants: assertional, deontic, analytic.",
     "signature": "O |= _|_ globally; locally, jointly unsatisfiable assertions",
     "instrument": "dl"},
    {"id": "K-A2", "stratum": "A", "name": "Term Incoherence",
     "definition": "The theory is satisfiable overall, but some term is not: a "
                   "class equivalent to the empty class.",
     "signature": "O consistent, yet O |= C [= _|_ for some class C",
     "instrument": "dl"},
    {"id": "K-A3", "stratum": "A", "name": "Indeterminacy",
     "definition": "Underconstraint: unintended models admitted, or membership "
                   "undecided where the governing practice requires decision.",
     "signature": "divergence of intended from admitted models; underivable "
                  "borderline membership",
     "instrument": "structural"},

    {"id": "K-B1", "stratum": "B", "name": "Circularity",
     "definition": "Non-wellfounded definition or grounding: a term's conditions "
                   "depend transitively on the term itself, or a grounding order "
                   "is inverted. The temporal case is grounding inversion "
                   "projected into time.",
     "signature": "a cycle in the dependency graph of definitions, or inversion "
                  "of a required grounding order",
     "instrument": "structural", "also": ["dl"]},
    {"id": "K-B2", "stratum": "B", "name": "Equivocation",
     "definition": "One item playing incompatible semantic or functional roles: "
                   "a term, condition, or occupant doing double duty across "
                   "contexts imposing conflicting demands.",
     "signature": "a single element bound to two roles whose satisfaction "
                  "conditions conflict",
     "instrument": "structural"},
    {"id": "K-B3", "stratum": "B", "name": "Residual Definition",
     "definition": "A term defined solely by complement: membership fixed only "
                   "negatively, as what remains once the positive categories are "
                   "exhausted. Parasitic and unstable under revision.",
     "signature": "C = !D1 & !D2 & ... with no positive differentia",
     "instrument": "structural"},

    {"id": "K-C1", "stratum": "C", "name": "Category Violation",
     "definition": "An entity forced under disjoint upper-ontological "
                   "categories: the formalized category mistake.",
     "signature": "a : C and a : D, with C and D disjoint at the upper level",
     "instrument": "dl"},
    {"id": "K-C2", "stratum": "C", "name": "Level Confusion",
     "definition": "Conflation of representational levels: a universal treated "
                   "as a particular, a class as an instance, a proposition as a "
                   "class, use as mention.",
     "signature": "an element occupying positions at two representational levels "
                  "whose disciplines conflict",
     "instrument": "structural"},
    {"id": "K-C3", "stratum": "C", "name": "Dependence Violation",
     "definition": "A dependent entity posited without its bearer, or a "
                   "grounding link severed. Includes the asymmetric case, where "
                   "one direction of a mutual dependence is enforced and the "
                   "other denied.",
     "signature": "a specifically dependent continuant without a bearer; a "
                  "relation over a relatum that cannot sustain it",
     "instrument": "dl", "partial": True},

    {"id": "K-D1", "stratum": "D", "name": "Falsification",
     "definition": "World-facing evidence contradicts the classification while "
                   "the artifact remains internally coherent.",
     "signature": "adjudication or audit outcome incompatible with the "
                  "conferred status",
     "instrument": "world"},
    {"id": "K-D2", "stratum": "D", "name": "Performative Self-Defeat",
     "definition": "The act undermines the conditions of its own success.",
     "signature": "an act whose effects negate one of its own preconditions",
     "instrument": "process"},
    {"id": "K-D3", "stratum": "D", "name": "Modal Clash",
     "definition": "What the institution's structure permits, its practice "
                   "forecloses.",
     "signature": "<>-in-structure and !<>-in-practice for the same possibility",
     "instrument": "process"},
]

_BY_ID = {k["id"]: k for k in KERNEL}


def primitive(kernel_id):
    """The kernel primitive record for ``kernel_id``, or None."""
    return _BY_ID.get(kernel_id)


def stratum_of(kernel_id):
    """The stratum letter for ``kernel_id``, or "" if unknown."""
    k = _BY_ID.get(kernel_id)
    return k["stratum"] if k else ""


# --- the detectability partition (§6.3, Table 7) -------------------------------
#
# Read this the way the paper intends: as a statement about what each kind of
# instrument *can* see, not about what this codebase has got round to. The
# report's coverage footer is derived from here, so a stratum with no available
# instrument is reported unassessed rather than clean.

INSTRUMENTS = {
    "dl": {
        "name": "Description-logic reasoner",
        "detects": ["K-A1", "K-A2", "K-C1"],
        "detects_partially": {
            "K-B1": "cyclic subsumption only",
            "K-C3": "via domain, range, and cardinality axioms",
        },
    },
    "structural": {
        "name": "Structural analysis of axioms",
        "detects": ["K-A3", "K-B2", "K-B3", "K-C2"],
        "detects_partially": {
            "K-B1": "grounding cycles and temporal inversions",
        },
    },
    "world": {
        "name": "World-facing data",
        "detects": ["K-D1"],
        "detects_partially": {},
        "requires": "an institutional record (adjudication, audit, evidence)",
    },
    "process": {
        "name": "Process-level modelling or simulation",
        "detects": ["K-D2", "K-D3"],
        "detects_partially": {},
        "requires": "an institutional record (declared acts and modal pairs)",
    },
}


def primitives_for(instrument_key):
    """Every primitive ``instrument_key`` can see, fully or partially."""
    spec = INSTRUMENTS.get(instrument_key)
    if not spec:
        return []
    return list(spec["detects"]) + list(spec.get("detects_partially", {}))


# --- kernel x chain, for a classification (§6.2, Table 6) ----------------------
#
# These are not an enumerated list. Each is the kernel primitive named, taken at
# the chain locus named; the paper derives them as theorems. We carry the names
# because they are what a domain expert recognises, not because they are
# primitive.

CLASSIFICATORY_TYPES = [
    {"id": "CT-1", "name": "Disjointness / Overlap Failure",
     "kernel": "K-A1", "locus": "criteria", "to_locus": "act", "latent": True,
     "reading": "Intended disjointness left unasserted, so jointly satisfiable "
                "models survive. The formal signature of artifactual comorbidity."},
    {"id": "CT-2", "name": "Criterion Circularity",
     "kernel": "K-B1", "locus": "criteria",
     "reading": "A category's defining conditions depend transitively on the "
                "category itself."},
    {"id": "CT-3", "name": "Threshold / Polythetic Incoherence",
     "kernel": "K-A3", "locus": "criteria",
     "reading": "A disjunctive family without shared essence; membership "
                "underconstrained."},
    {"id": "CT-4", "name": "Criterion Double-Duty",
     "kernel": "K-B2", "locus": "criteria",
     "reading": "One condition bound to conflicting inclusion and exclusion roles."},
    {"id": "CT-5", "name": "Residual Indeterminacy",
     "kernel": "K-B3", "locus": "criteria",
     "reading": "The 'other specified / unspecified' pattern."},
    {"id": "CT-6", "name": "Recognition Failure",
     "kernel": "K-C3", "locus": "criteria", "to_locus": "act",
     "reading": "The diagnostic act cannot track the criteria; grounding severed."},
    {"id": "CT-7", "name": "Type Contradiction",
     "kernel": "K-C1", "locus": "upper",
     "reading": "An entity forced under disjoint BFO categories."},
]


def classificatory_type(kernel_id, locus=None):
    """The CT record for a primitive at a locus, or None if the pair names none.

    ``locus=None`` matches on the kernel id alone, which is what a detector that
    could not bind the finding to a chain locus should pass. CT-7 is reported
    for K-C1 regardless of locus because its locus is the upper level, which is
    not part of any domain's chain.
    """
    for ct in CLASSIFICATORY_TYPES:
        if ct["kernel"] != kernel_id:
            continue
        if locus is None or ct["locus"] == "upper" or ct["locus"] == locus:
            return ct
    return None


# --- the stratum profile as fingerprint (§6.4, Table 8) ------------------------
#
# The empty cells are as informative as the filled ones. Strata A-C apply to any
# ontology whatsoever; Stratum D fires only where there are acts. That yields a
# principled account of what distinguishes an institutional ontology from a
# scientific one: institutional ontologies are exactly those capable of
# pragmatic contradiction.

SYSTEM_CLASSES = [
    {"key": "scientific",
     "name": "Scientific reference ontology",
     "examples": "GO, ChEBI, FMA; MF and MDO as artifacts",
     "chain_thickness": "no chain of its own",
     "active_strata": ["A", "B", "C"],
     "character": "No acts; all contradiction is artifact-internal.",
     "required_loci": [],
     "act_thick": False, "repair_thick": False},
    {"key": "recognition-only",
     "name": "Recognition-only institution",
     "examples": "DSM-5-TR, ICD-11; technical standards",
     "chain_thickness": "act-thin, repair-external",
     "active_strata": ["A", "B", "C", "D(thin)"],
     "character": "Criteria layer thick; assessment and revision both external.",
     "required_loci": ["authority", "criteria"],
     "act_thick": False, "repair_thick": False},
    {"key": "act-thick",
     "name": "Full legal system, licensure, refugee status determination",
     "examples": "statutory orders, professional licensure, RSD",
     "chain_thickness": "act-thick, repair-thick",
     "active_strata": ["A", "B", "C", "D"],
     "character": "The only class in which all twelve primitives can fire.",
     "required_loci": ["authority", "criteria", "assessor", "act", "effect", "remedy"],
     "act_thick": True, "repair_thick": True},
]

_BY_SYSTEM_KEY = {s["key"]: s for s in SYSTEM_CLASSES}


def system_class(key):
    """The system-class record for ``key``, or None."""
    return _BY_SYSTEM_KEY.get(key)


# Version of the vocabulary itself, so a stored report can be read back knowing
# which edition of the tables produced it.
VOCABULARY_VERSION = "recognition-layer/1"
