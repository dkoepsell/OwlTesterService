"""Phase 1 (SPEC-bfo-clif-background): the CLIF tokenizer is string-literal aware.

Acceptance: extracting predicates from the vendored BFO-2020 CLIF yields only real
BFO predicates and zero noise atoms (no comment prose like 'ISO/IEC', 'both', 'at',
no escaped-apostrophe fragments).
"""
import re

from clif_lexer import CLString, parse, tokenize
from clif_theory import collect_predicates, iter_axioms, load_clif


def test_single_quoted_prose_is_one_token():
    toks = tokenize("(cl:comment 'role is a universal [ewm-1]' (universal role))")
    assert toks[0] == "("
    assert toks[1] == "cl:comment"
    assert isinstance(toks[2], CLString)
    assert toks[2] == "role is a universal [ewm-1]"
    # the real axiom is intact after the prose
    assert "universal" in toks and "role" in toks


def test_backslash_escaped_quote_stays_inside_the_literal():
    # there\'s must not close the string early and spill prose as atoms.
    toks = tokenize(r"(cl:comment 'there\'s one time' (entity x))")
    strings = [t for t in toks if isinstance(t, CLString)]
    assert strings == ["there's one time"]
    assert "one" not in toks and "time" not in toks  # no leaked prose


def test_double_quoted_url_is_one_token():
    toks = tokenize('(cl:ttl "https://example.org/x.cl" (cl:text foo))')
    assert any(isinstance(t, CLString) and t.startswith("https://") for t in toks)


def test_parse_round_trips_nested_structure():
    forms = parse("(forall (x t) (if (instance-of x role t) (entity x)))")
    expected = ["forall", ["x", "t"],
                ["if", ["instance-of", "x", "role", "t"], ["entity", "x"]]]
    assert forms == [expected]


def test_unbalanced_parens_raise():
    import pytest
    with pytest.raises(ValueError):
        parse("(forall (x) (entity x)")


# -- Acceptance: zero noise over the real BFO file ---------------------------

def test_bfo_predicate_extraction_has_no_noise():
    preds = collect_predicates(load_clif())
    names = {p for p, _ in preds}
    # Every predicate name is a lower-case hyphenated identifier. Any comment
    # prose would show up as a name with spaces, punctuation, or capitals.
    ident = re.compile(r"^[a-z][a-z0-9-]*$")
    bad = sorted(n for n in names if not ident.match(n))
    assert bad == [], f"noise atoms leaked into the predicate set: {bad}"


def test_bfo_predicate_set_is_the_known_signature():
    preds = collect_predicates(load_clif())
    by_name = {}
    for name, arity in preds:
        by_name.setdefault(name, set()).add(arity)
    # No predicate is used at two different arities (would signal a parse error).
    multi = {n: sorted(a) for n, a in by_name.items() if len(a) > 1}
    assert multi == {}, f"predicates parsed at inconsistent arities: {multi}"
    # The measured BFO-2020 signature (Phase 0/1 inventory): 50 predicates.
    assert len(by_name) == 50


def test_known_core_predicates_present_with_expected_arity():
    preds = dict(collect_predicates(load_clif()))
    # ternary time-indexed continuant relations / instantiation
    assert preds["instance-of"] == 3
    assert preds["continuant-part-of"] == 3
    assert preds["participates-in"] == 3
    # binary occurrent / dependence relations
    assert preds["inheres-in"] == 2
    assert preds["temporal-part-of"] == 2
    assert preds["precedes"] == 2
    # unary type guards
    assert preds["universal"] == 1
    assert preds["entity"] == 1


def test_outdiscourse_and_comments_are_not_axioms():
    # cl:outdiscourse declares vocabulary; it must not appear as an axiom.
    forms = parse(
        "(cl:text m (cl:outdiscourse entity universal) "
        "(cl:comment 'note' (universal role)))"
    )
    axioms = list(iter_axioms(forms))
    assert axioms == [["universal", "role"]]
