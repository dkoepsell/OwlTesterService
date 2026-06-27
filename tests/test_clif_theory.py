"""Tests for the CLIF -> Prover9 translation of the BFO-2020 theory (Phase 3).

These cover the translator in isolation (every vendored axiom renders, no
hyphens leak into identifiers, the structural connective/quantifier rendering is
faithful, and malformed input is rejected rather than silently mistranslated).

The Phase 3 acceptance test proper -- Mace4 finding a model of the background
*alone*, proving it is consistent and was not translated into a contradiction --
needs the mace4 binary and is skipped when it is absent (as on plain CI), exactly
like the prover9 tests.
"""

import re
import shutil

import pytest

import clif_theory as ct
from bfo import clif_signature as sig
from clif_lexer import parse, CLString


def _body_lines(text):
    """The rendered assumption lines (indented, inside formulas(assumptions))."""
    return [ln for ln in text.splitlines() if ln.startswith("  ")]


def test_every_vendored_axiom_translates():
    """The full BFO-2020 theory renders with no ClifTranslationError, one line
    per real axiom -- nothing is silently dropped."""
    forms = ct.load_clif()
    axioms = list(ct.iter_axioms(forms))
    text = ct.render_prover9_theory()
    assert len(_body_lines(text)) == len(axioms)
    assert len(axioms) > 300  # the measured theory is ~343 axioms


def test_output_is_a_well_formed_assumptions_block():
    text = ct.render_prover9_theory()
    assert "set(prolog_style_variables)." in text
    assert "formulas(assumptions)." in text
    assert text.rstrip().endswith("end_of_list.")
    for ln in _body_lines(text):
        assert ln.rstrip().endswith("."), ln


def test_no_hyphen_leaks_into_an_identifier():
    """Prover9 identifiers cannot contain hyphens. Every BFO `-` must be either a
    negation operator or part of `->` / `<->`, never inside a symbol name."""
    text = ct.render_prover9_theory()
    noncomment = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("%"))
    stripped = noncomment.replace("<->", " ").replace("->", " ")
    assert not re.search(r"[A-Za-z0-9_]-[A-Za-z0-9_]", stripped)


def test_every_predicate_in_output_is_a_mapped_symbol():
    """Every predicate-looking token `name(` in the output is a known Prover9
    symbol from the signature map -- no stray CLIF predicate slipped through."""
    text = ct.render_prover9_theory()
    body = "\n".join(_body_lines(text))
    mapped = {sig.to_prover9_symbol(p) for p in sig.PREDICATES}
    called = set(re.findall(r"\b([a-z][a-z0-9_]*)\(", body))
    assert called <= mapped, f"unmapped predicates in output: {called - mapped}"


def test_translation_is_cached_per_path():
    a = ct.render_prover9_theory()
    b = ct.render_prover9_theory()
    assert a is b


# -- structural rendering of individual forms --------------------------------

def _render_one(clif_src):
    """Parse and render a single CLIF sentence (no quantifier context)."""
    (form,) = parse(clif_src)
    return ct._render_formula(form, frozenset())


def test_quantifier_implication_and_guard():
    out = _render_one("(forall (x t) (if (instance-of x role t) (entity x)))")
    assert out == "(all X all T (instance_of(X,role,T) -> entity(X)))"


def test_connectives_and_negation():
    assert _render_one("(and (entity x) (not (universal x)))") == \
        "(entity(x) & -universal(x))"
    assert _render_one("(or (entity x) (particular x))") == \
        "(entity(x) | particular(x))"
    assert _render_one("(iff (entity x) (particular x))") == \
        "(entity(x) <-> particular(x))"


def test_equality_renders_as_infix():
    assert _render_one("(= x y)") == "(x = y)"


def test_free_term_is_a_constant_bound_term_is_a_variable():
    # x is bound by the quantifier -> variable X; role and t are free -> constants.
    out = _render_one("(forall (x) (instance-of x role t))")
    assert out == "(all X instance_of(X,role,t))"


# -- guards against silent mistranslation ------------------------------------

def test_unmapped_predicate_is_rejected():
    with pytest.raises(ct.ClifTranslationError):
        _render_one("(not-a-bfo-predicate x)")


def test_arity_mismatch_is_rejected():
    # instance-of is arity 3 in the map; give it 2.
    with pytest.raises(ct.ClifTranslationError):
        _render_one("(instance-of x role)")


def test_string_literal_in_term_position_is_rejected():
    form = ["entity", CLString("a comment")]
    with pytest.raises(ct.ClifTranslationError):
        ct._render_formula(form, frozenset())


def test_functional_term_is_rejected():
    with pytest.raises(ct.ClifTranslationError):
        _render_one("(entity (f x))")


def test_malformed_quantifier_var_list_is_rejected():
    with pytest.raises(ct.ClifTranslationError):
        ct._render_formula(["forall", "x", ["entity", "x"]], frozenset())


# -- Phase 3 acceptance: the background is self-consistent -------------------

@pytest.mark.skipif(shutil.which("mace4") is None,
                    reason="mace4 binary not installed")
def test_background_alone_has_a_model():
    """Mace4 must find a finite model of the translated BFO background on its own.
    A model proves the theory is consistent and was not mistranslated into a
    contradiction (the Phase 3 acceptance criterion)."""
    import subprocess

    theory = ct.render_prover9_theory()
    proc = subprocess.run(
        ["mace4", "-n", "2"], input=theory,
        capture_output=True, text=True, timeout=120)
    out = proc.stdout or ""
    assert re.search(r"MODEL|Exiting with \d+ model", out), \
        f"mace4 found no model (rc={proc.returncode}):\n{out[-2000:]}"
