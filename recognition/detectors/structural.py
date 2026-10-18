"""What structural analysis of axioms can see (paper §6.3, Table 7).

    K-A3  indeterminacy -- disjunctive families with no shared essence
    K-B1  circularity   -- grounding and definitional cycles
    K-B2  equivocation  -- one term doing conflicting double duty
    K-B3  residual definition -- membership fixed only negatively
    K-C2  level confusion -- one element at two representational levels

This is the half of the kernel a description-logic reasoner cannot reach, and
it is not a tooling gap. K-B3 and K-C2 fire on artifacts that are perfectly
consistent; a reasoner asked about them has nothing to report because nothing
is wrong with the theory *as a theory*. That is why the paper insists a
reasoner is necessary and never sufficient, and why a pipeline that stops at
Stage C is reporting Stratum A plus part of C and scoring the rest zero.

Instantiated over a classification's recognition chain, four of these five land
squarely on the criteria locus and give CT-2 through CT-5 -- criterion
circularity, polythetic incoherence, criterion double-duty, and the "other
specified / unspecified" pattern.
"""

import re

from . import _expr
from ..finding import DetectorResult, RecognitionFinding

INSTRUMENT = "structural"

PRIMITIVES = {"K-A3", "K-B1", "K-B2", "K-B3", "K-C2"}

# A disjunctive definition with at least this many alternatives, and no shared
# essence among them, reads as a polythetic family rather than a genuine union.
POLYTHETIC_MIN = 3


# --- K-B3: residual definition ------------------------------------------------
#
# Two routes, because the pattern shows up both ways. Axiomatically it is a
# definition whose every conjunct is a complement -- membership fixed purely by
# what remains once the positive categories are exhausted. Lexically it is the
# "other specified / unspecified / NOS" family, which classifications use
# constantly and which is the same defect wearing a label instead of an axiom.

_RESIDUAL_LABEL_RE = re.compile(
    r"\b("
    r"other\s+specified|unspecified|not\s+otherwise\s+specified|"
    r"not\s+elsewhere\s+classified|nos|nec|"
    r"other\s+and\s+unspecified|residual|miscellaneous|"
    r"other\s+disorders?\s+of|other\s+forms?\s+of"
    r")\b", re.IGNORECASE)


def residual_definitions(ctx, binding=None, labels=None):
    """K-B3. Terms whose membership is fixed only negatively."""
    findings = []
    labels = labels or {}
    for cls_iri in ctx.classes:
        axiomatic = _is_axiomatically_residual(ctx, cls_iri)
        label = labels.get(cls_iri, "")
        text = label or cls_iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        lexical = bool(_RESIDUAL_LABEL_RE.search(_spaced(text)))

        if not (axiomatic or lexical):
            continue

        routes = [r for r, hit in (("axiomatic", axiomatic),
                                   ("lexical", lexical)) if hit]
        findings.append(RecognitionFinding(
            kernel="K-B3",
            message=("Membership is fixed only negatively, as what remains "
                     f"once the positive categories are exhausted: {text}"),
            iri=cls_iri, locus=_locus(binding, cls_iri), instrument=INSTRUMENT,
            evidence={"routes": routes,
                      "note": "Parasitic and unstable under revision: every "
                              "change to a sibling silently changes this "
                              "term's extension."}))
    return findings


def _is_axiomatically_residual(ctx, cls_iri):
    """True when the definition has negative conjuncts and no positive differentia.

    "No positive differentia" is not "no positive terms". The canonical residual
    category names its genus and then subtracts its siblings -- "an anxiety
    disorder that is not panic disorder and not a phobia" -- and that is exactly
    the pattern, not an exception to it. So a positive term only counts as a
    differentia if it is something other than an ancestor the class already has.
    """
    ancestors = _ancestors(ctx, cls_iri)
    for node in _expr.equivalence_nodes(ctx.graph, cls_iri):
        positive, negative, _props = _expr.expression_terms(ctx.graph, node)
        if negative and not (positive - ancestors - {cls_iri}):
            return True
    return False


def _ancestors(ctx, cls_iri):
    out, stack = set(), list(ctx.edges.get(cls_iri, ()))
    while stack:
        node = stack.pop()
        if node in out:
            continue
        out.add(node)
        stack.extend(ctx.edges.get(node, ()))
    return out


def _spaced(text):
    return re.sub(r"[_\-]+", " ", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text))


# --- K-B2: equivocation -------------------------------------------------------

def equivocations(ctx, binding=None, labels=None):
    """K-B2. One term bound to roles whose satisfaction conditions conflict.

    The detectable case in OWL: a term the definition of C requires and also
    excludes -- present as a positive conjunct and under a complement, or
    required while C is asserted disjoint from it. In a classification this is
    CT-4, criterion double-duty: one condition doing inclusion work in one
    place and exclusion work in another, so which reading applies decides the
    case.
    """
    findings = []
    labels = labels or {}
    for cls_iri in ctx.classes:
        positive, negative = set(), set()
        for node in _expr.definition_nodes(ctx.graph, cls_iri):
            pos, neg, _props = _expr.expression_terms(ctx.graph, node)
            positive |= pos
            negative |= neg
        excluded = negative | _expr.disjoint_with(ctx.graph, cls_iri)
        conflicted = sorted(positive & excluded)
        if not conflicted:
            continue
        findings.append(RecognitionFinding(
            kernel="K-B2",
            message=("Condition bound to conflicting inclusion and exclusion "
                     "roles in the same definition: "
                     + ", ".join(_short(c) for c in conflicted)),
            iri=cls_iri, locus=_locus(binding, cls_iri), instrument=INSTRUMENT,
            evidence={"terms": conflicted,
                      "label": labels.get(cls_iri, "")}))
    return findings


# --- K-C2: level confusion ----------------------------------------------------

_CLASS = "http://www.w3.org/2002/07/owl#Class"
_INDIVIDUAL = "http://www.w3.org/2002/07/owl#NamedIndividual"
_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#ObjectProperty"
_DATA_PROPERTY = "http://www.w3.org/2002/07/owl#DatatypeProperty"

# Pairs whose disciplines conflict: a universal treated as a particular, or a
# term used at once as a category and as a relation between categories.
_CONFLICTING_LEVELS = [
    ({_CLASS, _INDIVIDUAL}, "a universal is also declared a particular"),
    ({_CLASS, _OBJECT_PROPERTY}, "a class is also declared a relation"),
    ({_CLASS, _DATA_PROPERTY}, "a class is also declared a data property"),
    ({_OBJECT_PROPERTY, _INDIVIDUAL}, "a relation is also declared a particular"),
]


def level_confusions(ctx, binding=None, labels=None):
    """K-C2. One element occupying two representational levels.

    OWL 2 punning makes some of this legal, which is exactly why it needs a
    structural check rather than a reasoner: the artifact is consistent and the
    conflation is invisible to it. Only genuinely conflicting pairs are
    reported -- annotation-property punning is idiomatic and harmless.
    """
    findings = []
    labels = labels or {}
    for cls_iri in ctx.classes:
        types = _expr.declared_types(ctx.graph, cls_iri)
        for pair, reading in _CONFLICTING_LEVELS:
            if pair <= types:
                findings.append(RecognitionFinding(
                    kernel="K-C2",
                    message=f"Level confusion: {reading} ({_short(cls_iri)})",
                    iri=cls_iri, locus=_locus(binding, cls_iri),
                    instrument=INSTRUMENT,
                    evidence={"declared_types": sorted(types),
                              "label": labels.get(cls_iri, "")}))
                break
    return findings


# --- K-B1: definitional and grounding cycles ----------------------------------

def definition_cycles(ctx, binding=None, labels=None):
    """K-B1 beyond subsumption: a cycle in the definition-dependency graph.

    A category whose defining conditions depend transitively on the category
    itself. Over a classification's criteria locus this is CT-2, criterion
    circularity -- and unlike a subsumption cycle it leaves the artifact
    perfectly consistent, so only a structural walk finds it.
    """
    from .dl import _strongly_connected

    depends = {}
    for cls_iri in ctx.classes:
        mentioned = set()
        for node in _expr.equivalence_nodes(ctx.graph, cls_iri):
            pos, neg, _props = _expr.expression_terms(ctx.graph, node)
            mentioned |= pos | neg
        depends[cls_iri] = {m for m in mentioned if m in ctx.classes
                            and m != cls_iri} or set()

    findings = []
    for component in _strongly_connected(depends, ctx.classes):
        members = sorted(component)
        findings.append(RecognitionFinding(
            kernel="K-B1",
            message=("Definitional cycle: the conditions defining "
                     + " <-> ".join(_short(m) for m in members)
                     + " depend transitively on each other"),
            iri=members[0], locus=_locus(binding, members[0]),
            instrument=INSTRUMENT,
            evidence={"cycle": members, "kind": "definitional"}))
    return findings


# --- K-A3: polythetic families ------------------------------------------------

def polythetic_families(ctx, binding=None, labels=None):
    """K-A3. A disjunctive family whose alternatives share no essence.

    The formal residue of a "any N of these M features" criterion, which OWL
    cannot state and classifications state constantly. Membership ends up
    underconstrained: the admitted models diverge from the intended ones, and
    borderline cases stay underivable where the governing practice requires a
    decision. Over the criteria locus this is CT-3.

    Reported as a candidate. A union whose members do share a superclass is an
    ordinary disjunction and is not flagged.
    """
    findings = []
    labels = labels or {}
    for cls_iri in ctx.classes:
        for node in _expr.equivalence_nodes(ctx.graph, cls_iri):
            members = _expr.union_members(ctx.graph, node)
            if len(members) < POLYTHETIC_MIN:
                continue
            shared = _shared_ancestors(ctx, members) - {cls_iri}
            if shared:
                continue
            findings.append(RecognitionFinding(
                kernel="K-A3",
                message=(f"Disjunctive family of {len(members)} alternatives "
                         "with no shared essence; membership is "
                         f"underconstrained: {_short(cls_iri)}"),
                iri=cls_iri, locus=_locus(binding, cls_iri),
                instrument=INSTRUMENT,
                evidence={"alternatives": members,
                          "label": labels.get(cls_iri, ""),
                          "note": "Candidate. The usual source is a threshold "
                                  "criterion ('any N of M') that OWL cannot "
                                  "express."}))
            break
    return findings


def _shared_ancestors(ctx, iris):
    """Named superclasses common to every member of ``iris``."""
    common = None
    for iri in iris:
        ancestors, stack = set(), list(ctx.edges.get(iri, ()))
        while stack:
            node = stack.pop()
            if node in ancestors:
                continue
            ancestors.add(node)
            stack.extend(ctx.edges.get(node, ()))
        common = ancestors if common is None else (common & ancestors)
        if not common:
            return set()
    return common or set()


# --- CT-1 / K-A1 latent: unasserted disjointness ------------------------------

# Reporting one finding per *parent*, never per sibling pair. A classification
# with several thousand disease classes has millions of pairs, and a report that
# emits one row each is not a report.
MAX_LATENT_OVERLAPS = 50


def latent_overlaps(ctx, binding=None, labels=None):
    """CT-1. Siblings the artifact intends as alternatives but never separates.

    Table 6 calls this "the formal signature of artifactual comorbidity": the
    intended disjointness is left unasserted, so jointly satisfiable models
    survive and nothing stops one case falling under two sibling categories at
    once. The kernel primitive is K-A1 in its *latent* form -- there is no
    contradiction in the artifact, only the absence of the axiom that would
    make one possible.

    That latency is why this detector does not mark K-A1 assessed. Finding an
    unasserted disjointness says nothing about whether the theory admits a
    model, and only a reasoner can answer that.
    """
    findings = []
    labels = labels or {}

    children = {}
    for cls_iri in ctx.classes:
        for parent in ctx.edges.get(cls_iri, ()):
            if parent in ctx.classes:
                children.setdefault(parent, []).append(cls_iri)

    candidates = []
    for parent, kids in children.items():
        if len(kids) < 2:
            continue
        if _any_disjointness_among(ctx, kids):
            continue
        candidates.append((parent, sorted(kids)))

    candidates.sort(key=lambda pair: (-len(pair[1]), pair[0]))
    truncated = max(0, len(candidates) - MAX_LATENT_OVERLAPS)

    for parent, kids in candidates[:MAX_LATENT_OVERLAPS]:
        findings.append(RecognitionFinding(
            kernel="K-A1",
            message=(f"{len(kids)} sibling categories under "
                     f"{_short(parent)} with no disjointness asserted between "
                     "them; nothing prevents one case falling under several "
                     "at once"),
            iri=parent, locus=_locus(binding, parent), instrument=INSTRUMENT,
            evidence={"latent": True, "siblings": kids,
                      "label": labels.get(parent, ""),
                      "note": "Latent: the absence of an axiom, not a "
                              "contradiction. Whether the disjointness was "
                              "intended is a question for the source."}))

    if truncated:
        findings.append(RecognitionFinding(
            kernel="K-A1",
            message=(f"{truncated} further parent categories have siblings "
                     "with no asserted disjointness; not listed individually"),
            instrument=INSTRUMENT,
            evidence={"latent": True, "truncated": truncated,
                      "reported": MAX_LATENT_OVERLAPS}))
    return findings


def _any_disjointness_among(ctx, kids):
    """True if the artifact separates any two of ``kids``."""
    kid_set = set(kids)
    for kid in kids:
        if _expr.disjoint_with(ctx.graph, kid) & kid_set:
            return True
    return _all_disjoint_covers(ctx.graph, kid_set)


def _all_disjoint_covers(graph, kid_set):
    """True if an owl:AllDisjointClasses axiom covers two or more of them."""
    try:
        from rdflib import OWL, RDF
    except Exception:  # noqa: BLE001
        return False
    for axiom, _p, _o in graph.triples((None, RDF.type, OWL.AllDisjointClasses)):
        members = graph.value(axiom, OWL.members)
        if members is None:
            continue
        named = {str(m) for m in _expr.rdf_list(graph, members)}
        if len(named & kid_set) >= 2:
            return True
    return False


# --- helpers ------------------------------------------------------------------

def _locus(binding, iri):
    return (binding.locus_of(iri) or "") if binding else ""


def _short(iri):
    return iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _labels(graph):
    out = {}
    try:
        from rdflib import RDFS, URIRef
    except Exception:  # noqa: BLE001
        return out
    for s, _p, o in graph.triples((None, RDFS.label, None)):
        if isinstance(s, URIRef) and str(s) not in out:
            out[str(s)] = str(o)
    return out


# --- entry point --------------------------------------------------------------

def run(ctx, binding=None):
    """Every K-primitive structural analysis can reach, for one artifact."""
    result = DetectorResult()
    if not _expr.available():
        result.notes["structural"] = "rdflib unavailable; no structural analysis"
        return result

    labels = _labels(ctx.graph)
    for detector in (residual_definitions, equivocations, level_confusions,
                     definition_cycles, polythetic_families):
        result.findings.extend(detector(ctx, binding, labels))
    result.attempted |= PRIMITIVES

    # CT-1 deliberately does not add K-A1 to ``attempted``: it detects a
    # missing axiom, which is silent about whether the theory admits a model.
    result.findings.extend(latent_overlaps(ctx, binding, labels))
    return result
