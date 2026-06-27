"""Tests for the Prover9 / CLIF FOL export (SPEC Task 5)."""

from fol_export import build_theory, render_prover9, render_clif, generate_exports


def test_straddle_theory_has_subsumptions_and_bfo_disjointness(straddle_owl, catalog):
    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    # Force is asserted under both quality and disposition.
    force_iri = next(i for i, c in theory.classes.items() if c["label"] == "Force")
    parents = {sup for sub, sup in theory.subsumptions if sub == force_iri}
    parent_labels = {theory.classes[p]["label"] for p in parents}
    assert "quality" in parent_labels
    assert "disposition" in parent_labels
    # The quality/disposition clash must appear as a BFO disjointness axiom so a
    # prover can rediscover the straddle.
    origins = {o for _, _, o in theory.disjoints}
    assert "bfo" in origins
    pair_labels = {
        frozenset((theory.classes[a]["label"], theory.classes[b]["label"]))
        for a, b, _ in theory.disjoints
    }
    assert frozenset(("quality", "disposition")) in pair_labels


def test_force_is_continuant_arity(straddle_owl, catalog):
    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    force = next(c for c in theory.classes.values() if c["label"] == "Force")
    assert force["kind"] == "continuant"


def test_prover9_render_is_runnable_shape(straddle_owl, catalog):
    p9 = render_prover9(build_theory(file_path=straddle_owl, catalog=catalog))
    assert "set(prolog_style_variables)." in p9
    assert "formulas(assumptions)." in p9
    assert "end_of_list." in p9
    assert "instance_of(" in p9
    # disjointness negation present
    assert "-(" in p9


def test_clif_render_is_well_formed(straddle_owl, catalog):
    clif = render_clif(build_theory(file_path=straddle_owl, catalog=catalog))
    assert "(cl-text" in clif
    assert "(forall" in clif
    assert "(if " in clif
    assert "(not (and" in clif
    # balanced parentheses
    assert clif.count("(") == clif.count(")")


def test_generate_exports_returns_both_and_stats(straddle_owl, catalog):
    out = generate_exports(file_path=straddle_owl, catalog=catalog)
    assert out["error"] is None
    assert out["prover9"] and out["clif"]
    assert out["stats"]["subsumptions"] >= 2
    assert out["stats"]["disjoint_axioms"] >= 1


def test_coherent_fixture_has_no_clashing_disjointness(coherent_owl, catalog):
    theory = build_theory(file_path=coherent_owl, catalog=catalog)
    # A coherent ontology should not yield a BFO-clash disjointness pair that
    # both of its classes straddle (no partition straddle present).
    out = generate_exports(file_path=coherent_owl, catalog=catalog)
    assert out["error"] is None


# -- Phase 4: alignment to the BFO background --------------------------------

def test_align_bfo_off_is_byte_identical_default(straddle_owl, catalog):
    """The acceptance criterion: with the flag off the export is unchanged."""
    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    assert render_prover9(theory, align_bfo=False) == render_prover9(theory)
    assert render_clif(theory, align_bfo=False) == render_clif(theory)


def test_align_bfo_uses_only_ternary_instantiation(straddle_owl, catalog):
    """Aligned, occurrents instantiate via the ternary instance_of(x, C, t) too,
    so the export shares one predicate set with the BFO background."""
    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    p9 = render_prover9(theory, align_bfo=True)
    clif = render_clif(theory, align_bfo=True)
    assert "instance_of_at" not in p9
    assert "instance_of_at" not in clif
    assert "instance_of(" in p9
    # Default export still distinguishes occurrents (proves the flag is the cause).
    assert "instance_of_at" in render_prover9(theory)
    assert clif.count("(") == clif.count(")")
