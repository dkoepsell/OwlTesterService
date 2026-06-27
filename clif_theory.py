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
