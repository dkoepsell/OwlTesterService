"""
CLIF -> Prover9 translation of the vendored BFO-2020 theory.

This turns bfo/bfo-2020.clif (ISO Common Logic, 13 normative cl:text modules) into
a single Prover9 (LADR) assumptions block so the prover cross-check can use the
*complete* first-order BFO axiomatization as background theory, not just the
lightweight derived-disjointness export.

Pipeline:
  clif_lexer.parse      -> nested s-expressions (string-literal aware)
  iter_axioms           -> the real axiom forms, with cl: wrappers stripped
  collect_predicates    -> the predicate signature actually used (for the map test)
  render_prover9_theory -> Prover9 text, via bfo.clif_signature

The translated background is cached once per process (it is a fixed input).
"""
import logging
import os

from bfo import clif_signature as _sig
from clif_lexer import CLString, parse

logger = logging.getLogger(__name__)

# Logical operators (plain CL names, no cl: prefix in the BFO file).
_QUANTIFIERS = {"forall", "exists"}
_CONNECTIVES = {"if", "and", "or", "not", "iff"}
_LOGICAL = _QUANTIFIERS | _CONNECTIVES | {"="}

# CL wrappers carrying no logical content of their own. We descend into the ones
# that embed axioms (cl:text, cl:ttl, cl:comment, cl:module) and drop the purely
# declarative ones (cl:outdiscourse, cl:imports). Both cl: and cl- spellings are
# accepted so the same code reads tester input and the vendored file.
_PASSTHROUGH = {"cl:text", "cl-text", "cl:module", "cl-module",
                "cl:ttl", "cl-ttl", "cl:comment", "cl-comment"}
_DECLARATIONS = {"cl:outdiscourse", "cl-outdiscourse", "cl:imports", "cl-imports"}

_DEFAULT_BFO_CLIF = os.path.join(os.path.dirname(__file__), "bfo", "bfo-2020.clif")


def _head_symbol(node):
    """The lower-cased head name of a list node, or None if it has no name head."""
    if not isinstance(node, list) or not node:
        return None
    head = node[0]
    if isinstance(head, CLString) or not isinstance(head, str):
        return None
    return head.lower()


def iter_axioms(forms):
    """Yield the real axiom s-expressions from parsed CLIF, stripping cl: wrappers.

    cl:text / cl:ttl / cl:comment / cl:module are unwrapped to reach the axioms
    they enclose (quoted-string arguments such as comment prose, titles, and
    module names are skipped). cl:outdiscourse / cl:imports declarations yield
    nothing. Everything else is a genuine axiom (a logical form or atomic
    predicate) and is yielded as-is.
    """
    for node in forms:
        yield from _unwrap(node)


def _unwrap(node):
    if not isinstance(node, list) or not node:
        return
    h = _head_symbol(node)
    if h in _DECLARATIONS:
        return
    if h in _PASSTHROUGH:
        for child in node[1:]:
            # Quoted prose / titles / module-name strings carry no axiom.
            if isinstance(child, CLString):
                continue
            yield from _unwrap(child)
        return
    # A genuine axiom: a logical form or an atomic predicate application.
    yield node


def collect_predicates(forms):
    """Return {(predicate_name, arity)} over the real axioms in parsed CLIF.

    Walks through quantifiers and connectives; equality is not collected (it is a
    logical primitive, not a domain predicate). This is the Phase 1 acceptance
    harness: over a clean tokenization it yields only real BFO predicates.
    """
    acc = set()
    for axiom in iter_axioms(forms):
        _collect(axiom, acc)
    return acc


def _collect(node, acc):
    if not isinstance(node, list) or not node:
        return
    h = _head_symbol(node)
    if h in _QUANTIFIERS:
        # (forall (vars...) body...) -- variable list is node[1], skip it.
        for child in node[2:]:
            _collect(child, acc)
        return
    if h in _CONNECTIVES:
        for child in node[1:]:
            _collect(child, acc)
        return
    if h == "=":
        return  # equality of terms, not a domain predicate
    if h is not None:
        # Atomic predicate application: head plus its term arguments.
        acc.add((node[0], len(node) - 1))
        return
    # Head is itself a list (no name): descend defensively.
    for child in node:
        _collect(child, acc)


def load_clif(path=None):
    """Parse a CLIF file (defaults to the vendored BFO-2020 theory)."""
    path = path or _DEFAULT_BFO_CLIF
    with open(path, "r", encoding="utf-8") as fh:
        return parse(fh.read())


# -- CLIF -> Prover9 translation (Phase 3) -----------------------------------

class ClifTranslationError(ValueError):
    """A CLIF form that the Prover9 translator cannot faithfully render.

    Raised on anything beyond plain first-order BFO: a predicate absent from the
    signature map, an arity that drifted, a string literal or functional term in
    argument position, or a malformed connective. The measured BFO-2020 vocabulary
    contains none of these, so this is a guard against silent mistranslation if a
    future BFO bump introduces a feature the map does not cover.
    """


def _prover9_var(name):
    """Render a CLIF variable as a Prover9 (prolog-style) variable.

    Under set(prolog_style_variables) Prover9 reads an upper-case-initial token as
    a variable and a lower-case one as a constant/predicate. BFO's variables are
    lower-case, so upper-casing them (after the total hyphen rule) yields a valid,
    collision-free variable that the lower-case class constants can never shadow.
    """
    return _sig.to_prover9_symbol(name).upper()


def _render_term(node, bound):
    """Render a CLIF term: a bound variable (-> Prover9 variable) or a constant.

    Anything not bound by an enclosing quantifier is a constant (a BFO universal
    name such as `history` or `material-entity`), rendered via the hyphen rule.
    """
    if isinstance(node, CLString):
        raise ClifTranslationError(f"string literal in term position: {node!r}")
    if isinstance(node, list):
        raise ClifTranslationError(f"functional term not supported: {node!r}")
    if node in bound:
        return _prover9_var(node)
    return _sig.to_prover9_symbol(node)


def _render_formula(node, bound):
    """Render one CLIF sentence as a Prover9 formula string (no trailing dot)."""
    if not isinstance(node, list) or not node:
        raise ClifTranslationError(f"not a formula: {node!r}")
    h = _head_symbol(node)
    if h is None:
        raise ClifTranslationError(f"formula has no operator head: {node!r}")

    if h in _QUANTIFIERS:
        varlist = node[1] if len(node) > 1 else None
        if not isinstance(varlist, list) or any(
            not isinstance(v, str) or isinstance(v, CLString) for v in varlist
        ):
            raise ClifTranslationError(f"malformed quantifier var list: {node!r}")
        inner_bound = bound | {v for v in varlist}
        body = node[2:]
        if not body:
            raise ClifTranslationError(f"quantifier with no body: {node!r}")
        rendered = [_render_formula(b, inner_bound) for b in body]
        # CL quantifiers bind a single sentence; conjoin defensively if more.
        inner = rendered[0] if len(rendered) == 1 else "(" + " & ".join(rendered) + ")"
        quant = _sig.QUANTIFIERS[h]
        prefix = " ".join(f"{quant} {_prover9_var(v)}" for v in varlist)
        return f"({prefix} {inner})"

    if h == "not":
        if len(node) != 2:
            raise ClifTranslationError(f"`not` takes one argument: {node!r}")
        return f"-{_render_formula(node[1], bound)}"

    if h in ("and", "or"):
        if len(node) < 3:
            raise ClifTranslationError(f"`{h}` needs >= 2 arguments: {node!r}")
        op = _sig.CONNECTIVES[h]
        return "(" + f" {op} ".join(_render_formula(c, bound) for c in node[1:]) + ")"

    if h in ("if", "iff"):
        if len(node) != 3:
            raise ClifTranslationError(f"`{h}` takes two arguments: {node!r}")
        op = _sig.CONNECTIVES[h]
        return (f"({_render_formula(node[1], bound)} {op} "
                f"{_render_formula(node[2], bound)})")

    if h == "=":
        if len(node) != 3:
            raise ClifTranslationError(f"`=` takes two arguments: {node!r}")
        return f"({_render_term(node[1], bound)} = {_render_term(node[2], bound)})"

    # Atomic predicate application, validated against the signature map.
    head = node[0]
    arity = len(node) - 1
    expected = _sig.PREDICATES.get(head)
    if expected is None:
        raise ClifTranslationError(f"predicate absent from BFO signature map: {head!r}")
    if expected != arity:
        raise ClifTranslationError(
            f"arity mismatch for {head!r}: got {arity}, map expects {expected}")
    sym = _sig.to_prover9_symbol(head)
    if arity == 0:
        return sym
    return f"{sym}(" + ",".join(_render_term(a, bound) for a in node[1:]) + ")"


_HEADER = (
    "% BFO-2020 full first-order theory as Prover9 / Mace4 background.\n"
    "% Translated from bfo/bfo-2020.clif (ISO Common Logic) by clif_theory.py.\n"
    "% Continuants and instantiation are time-indexed: instance_of(x, C, t).\n"
)

_THEORY_CACHE = {}


def render_prover9_theory(path=None):
    """Translate a CLIF theory (default: vendored BFO-2020) into a Prover9 block.

    Returns a complete, runnable assumptions section:

        set(prolog_style_variables).
        formulas(assumptions).
          <one rendered axiom per line>
        end_of_list.

    Duplicate set() directives and multiple assumptions lists are harmless in
    Prover9/Mace4, so this block can also be prepended to the ontology export
    (Phase 5). The translation is cached per file path: the BFO background is a
    fixed input rendered once per process. Raises ClifTranslationError if any form
    falls outside plain first-order BFO.
    """
    key = os.path.abspath(path or _DEFAULT_BFO_CLIF)
    cached = _THEORY_CACHE.get(key)
    if cached is not None:
        return cached

    forms = load_clif(path)
    body = [f"  {_render_formula(a, frozenset())}." for a in iter_axioms(forms)]
    text = (_HEADER + "set(prolog_style_variables).\n\n"
            "formulas(assumptions).\n" + "\n".join(body) + "\nend_of_list.\n")
    _THEORY_CACHE[key] = text
    return text
