"""
BFO-2020 CLIF -> Prover9 signature map (SPEC-bfo-clif-background Phase 2).

A reviewed table that pins, for every predicate the BFO-2020 CLIF theory uses, its
Prover9 (LADR) symbol and arity, plus the logical-operator map and the
hyphen-to-underscore identifier rule. Phase 3's translator renders axioms through
this map; the Phase 2 test asserts the map covers every predicate the tokenizer
finds in bfo/bfo-2020.clif (zero unmapped symbols) and flags any new symbol or
arity drift a future BFO bump introduces.

It lives in bfo/ so the sibling bfo-agent repo can reuse one shared signature and
the two tools never disagree about BFO's vocabulary.

Two facts about the target:

  - Prover9 identifiers cannot contain hyphens, so `continuant-part-of` becomes
    `continuant_part_of`. The rule (to_prover9_symbol) is deterministic and total.
  - Common Logic has an untyped domain; BFO uses unary guard predicates
    (universal, particular, entity) rather than sorts. Prover9 is untyped
    first-order, so the guards translate directly as unary predicates and no sort
    machinery is needed.

The arity column records the time-indexing convention measured in Phase 0/1:
ternary (arity 3) predicates are the time-indexed continuant relations and
instantiation `instance-of(x, type, t)`; binary (arity 2) predicates are the
occurrent / temporal / dependence relations that carry their time intrinsically.
"""


# -- logical operators -------------------------------------------------------
# CLIF (ISO/IEC 24707) operator name -> Prover9 (LADR) token. BFO uses the plain
# spellings, no cl: prefix. `if` is binary material implication
# (if antecedent consequent); `iff` is the biconditional.
QUANTIFIERS = {"forall": "all", "exists": "exists"}
CONNECTIVES = {"and": "&", "or": "|", "not": "-", "if": "->", "iff": "<->"}
EQUALITY = "="


def to_prover9_symbol(clif_name):
    """Map a CLIF predicate name to its Prover9 identifier.

    Deterministic and total: Prover9 forbids hyphens in identifiers, so every
    hyphen becomes an underscore. BFO's CLIF names are already lower-case, which
    Prover9 (under set(prolog_style_variables)) reads as a constant/predicate
    rather than a variable, so no case folding is required.
    """
    return clif_name.replace("-", "_")


# -- predicate signature -----------------------------------------------------
# Reviewed table: BFO-2020 CLIF predicate -> arity. Grouped as in SPEC Section 2.
# The Prover9 symbol is derived from the name via to_prover9_symbol(); the arity
# is the reviewed datum (it decides how many term slots the translator renders).

# Type guards (arity 1): BFO's stand-ins for sorts.
_TYPE_GUARDS = {
    "universal": 1,
    "particular": 1,
    "entity": 1,
}

# Instantiation (arity 3): instance-of(x, type, t).
_INSTANTIATION = {
    "instance-of": 3,
}

# Continuant relations (arity 3): time-indexed.
_CONTINUANT_RELATIONS = {
    "continuant-part-of": 3,
    "has-continuant-part": 3,
    "proper-continuant-part-of": 3,
    "has-proper-continuant-part": 3,
    "member-part-of": 3,
    "has-member-part": 3,
    "participates-in": 3,
    "has-participant": 3,
    "located-in": 3,
    "location-of": 3,
    "occupies-spatial-region": 3,
    "spatially-projects-onto": 3,
    "generically-depends-on": 3,
    "concretizes": 3,
    "is-concretized-by": 3,
    "has-material-basis": 3,
    "material-basis-of": 3,
    "is-carrier-of": 3,
}

# Occurrent / temporal relations (arity 2): carry their time intrinsically.
_OCCURRENT_RELATIONS = {
    "temporal-part-of": 2,
    "proper-temporal-part-of": 2,
    "has-temporal-part": 2,
    "has-proper-temporal-part": 2,
    "occurrent-part-of": 2,
    "proper-occurrent-part-of": 2,
    "has-occurrent-part": 2,
    "has-proper-occurrent-part": 2,
    "precedes": 2,
    "preceded-by": 2,
    "occurs-in": 2,
    "environs": 2,
    "history-of": 2,
    "has-history": 2,
    "occupies-temporal-region": 2,
    "occupies-spatiotemporal-region": 2,
    "temporally-projects-onto": 2,
    "has-first-instant": 2,
    "first-instant-of": 2,
    "has-last-instant": 2,
    "last-instant-of": 2,
    "exists-at": 2,
}

# Dependence / realizable relations (arity 2).
_DEPENDENCE_RELATIONS = {
    "specifically-depends-on": 2,
    "specifically-depended-on-by": 2,
    "inheres-in": 2,
    "bearer-of": 2,
    "realizes": 2,
    "has-realization": 2,
}

PREDICATES = {
    **_TYPE_GUARDS,
    **_INSTANTIATION,
    **_CONTINUANT_RELATIONS,
    **_OCCURRENT_RELATIONS,
    **_DEPENDENCE_RELATIONS,
}


def arity_of(clif_name):
    """Reviewed arity for a BFO CLIF predicate, or None if it is not in the map."""
    return PREDICATES.get(clif_name)


def signature_for(clif_name):
    """Return {clif, prover9, arity} for a mapped predicate, or None if unmapped."""
    arity = PREDICATES.get(clif_name)
    if arity is None:
        return None
    return {
        "clif": clif_name,
        "prover9": to_prover9_symbol(clif_name),
        "arity": arity,
    }


def unmapped(found):
    """Predicates present in `found` but absent from the reviewed map.

    `found` is any iterable of (name, arity) pairs (e.g. the output of
    clif_theory.collect_predicates). Returns the sorted list of unmapped names.
    """
    return sorted({name for name, _ in found if name not in PREDICATES})


def arity_mismatches(found):
    """(name, found_arity, expected_arity) for mapped predicates whose arity drifted.

    Catches a future BFO bump that reuses a predicate name at a new arity. Unmapped
    predicates are reported by unmapped(), not here.
    """
    out = []
    for name, arity in found:
        expected = PREDICATES.get(name)
        if expected is not None and expected != arity:
            out.append((name, arity, expected))
    return sorted(out)
