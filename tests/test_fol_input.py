"""Tests for Prover9 / CLIF input detection and conversion (SPEC Task 5, input side)."""

from nltk.sem.logic import LogicParser

from fol_input import detect_syntax, prepare_expression, clif_to_internal, prover9_to_internal

_lp = LogicParser()


def _parses(s):
    try:
        _lp.parse(s)
        return True
    except Exception:
        return False


def test_detect_prover9():
    assert detect_syntax("all X all T (instance_of(X,force,T) -> instance_of(X,q,T)).") == "prover9"


def test_detect_clif():
    assert detect_syntax("(forall (x t) (if (instance_of x f t) (instance_of x q t)))") == "clif"


def test_detect_existing_formats_unchanged():
    assert detect_syntax("instance_of(x, Quality, t)") == "instance_of"
    assert detect_syntax("Continuant(x)") == "traditional"


def test_prover9_conversion_parses():
    out = prover9_to_internal("all X all T (instance_of(X,force,T) -> instance_of(X,quality,T)).")
    assert _parses(out)
    assert "all X.all T." in out


def test_clif_conversion_parses():
    out = clif_to_internal("(forall (x t) (if (instance_of x force t) (instance_of x quality t)))")
    assert _parses(out)
    assert "->" in out


def test_clif_negation_and_conjunction():
    out = clif_to_internal("(forall (x) (not (and (instance_of x a t) (instance_of x b t))))")
    assert _parses(out)
    assert "-(" in out and "&" in out


def test_prepare_expression_reports_note():
    _, syn, note = prepare_expression("(exists (x) (instance_of x quality t))")
    assert syn == "clif"
    assert note and "CLIF" in note


def test_prepare_expression_noop_for_internal():
    expr, syn, note = prepare_expression("all x.(P(x) -> Q(x))")
    assert note is None  # nothing converted


def test_converted_clif_has_no_false_free_variables():
    """Bound x,t and the constant 'force' must not be reported as free variables
    after CLIF conversion (regression: the old regex only knew 'forall')."""
    from owl_tester import OwlTester
    internal, _, _ = prepare_expression(
        "(forall (x t) (if (instance_of x force t) (instance_of x quality t)))"
    )
    assert OwlTester().detect_free_variables(internal) == []


def test_converted_prover9_has_no_false_free_variables():
    from owl_tester import OwlTester
    internal, _, _ = prepare_expression(
        "all X all T (instance_of(X,force,T) -> instance_of(X,quality,T))."
    )
    assert OwlTester().detect_free_variables(internal) == []


def test_non_bfo_term_is_well_formed_not_invalid():
    """A closed FOL formula that uses a non-BFO term is well formed (soft verdict),
    with the non-BFO term reported as a note rather than a blocking issue."""
    from owl_tester import OwlTester
    from owl_preprocessor import preprocess_expression
    internal, _, _ = prepare_expression(
        "(forall (x t) (if (instance_of x force t) (instance_of x quality t)))"
    )
    internal, _ = preprocess_expression(internal)
    r = OwlTester().test_expression(internal)
    assert r["well_formed"] is True
    assert r["bfo_compatible"] is False
    assert r["valid"] is False
    assert r["issues"] == []            # non-BFO term is not a blocking issue
    assert any("force" in n for n in r["notes"])
