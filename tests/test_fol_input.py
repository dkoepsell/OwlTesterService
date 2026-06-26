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
