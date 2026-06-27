"""Phase 2 (SPEC-bfo-clif-background): the CLIF -> Prover9 signature map.

Acceptance: the reviewed map in bfo/clif_signature.py covers every predicate the
Phase 1 tokenizer finds in bfo/bfo-2020.clif (zero unmapped symbols) and matches
each one's arity, so any new symbol or arity drift from a future BFO bump is
flagged here rather than silently mistranslated downstream.
"""
from bfo import clif_signature as sig
from clif_theory import collect_predicates, load_clif


def _found():
    return collect_predicates(load_clif())


def test_map_covers_every_predicate_in_the_vendored_theory():
    found = _found()
    missing = sig.unmapped(found)
    assert missing == [], f"predicates in BFO CLIF not in the signature map: {missing}"


def test_map_arities_match_the_vendored_theory():
    found = _found()
    drift = sig.arity_mismatches(found)
    assert drift == [], f"arity drift between map and BFO CLIF: {drift}"


def test_map_has_no_predicate_absent_from_the_theory():
    # The map should not carry stale entries the theory no longer uses; that would
    # mask a real removal in a BFO bump.
    found_names = {name for name, _ in _found()}
    extra = sorted(set(sig.PREDICATES) - found_names)
    assert extra == [], f"signature map carries predicates absent from BFO CLIF: {extra}"


def test_hyphen_to_underscore_is_deterministic_and_total():
    assert sig.to_prover9_symbol("continuant-part-of") == "continuant_part_of"
    assert sig.to_prover9_symbol("instance-of") == "instance_of"
    assert sig.to_prover9_symbol("entity") == "entity"
    # total: no hyphenated name survives
    for name in sig.PREDICATES:
        assert "-" not in sig.to_prover9_symbol(name)


def test_signature_for_known_predicates():
    assert sig.signature_for("instance-of") == {
        "clif": "instance-of", "prover9": "instance_of", "arity": 3}
    assert sig.signature_for("inheres-in") == {
        "clif": "inheres-in", "prover9": "inheres_in", "arity": 2}
    assert sig.signature_for("universal") == {
        "clif": "universal", "prover9": "universal", "arity": 1}
    assert sig.signature_for("not-a-bfo-predicate") is None


def test_logical_operator_map_is_complete():
    # The operators clif_theory walks must all have a Prover9 rendering.
    import clif_theory as ct
    mapped = set(sig.QUANTIFIERS) | set(sig.CONNECTIVES) | {sig.EQUALITY}
    assert ct._LOGICAL <= mapped, f"unmapped logical operators: {ct._LOGICAL - mapped}"
