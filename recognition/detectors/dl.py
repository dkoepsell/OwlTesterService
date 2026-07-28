"""What a description-logic reasoner can see (paper §6.3, Table 7).

    K-A1  inconsistency
    K-A2  term incoherence (a class equivalent to the empty class)
    K-C1  category violation, given upper-level disjointness
    K-B1  circularity -- cyclic subsumption only
    K-C3  dependence violation -- partially, via domain, range, cardinality

The reasoner work is not redone here. Stage C of the gate already runs HermiT
via owlready2 and already reports unsatisfiable classes, and ``bfo_lint``
already finds disjoint-category clashes. This module's job is to *retype* their
output onto the kernel and index it to the recognition chain, so a finding
stops being "E_INCONSISTENT on some IRI" and becomes "K-A2 at the criteria
locus, which is CT-3".

The half of the kernel this module cannot reach is not a gap to be closed by
better DL tooling. It is Table 7 working as designed.
"""

from ..finding import BLANKET, DetectorResult, RecognitionFinding

INSTRUMENT = "dl"

# Split by what each arm needs. K-A1 and K-A2 require a working reasoner; the
# rest are graph walks over asserted axioms and run whether or not Java and
# HermiT are present. Conflating the two would let a machine with no reasoner
# report Stratum A as clean.
REASONER_PRIMITIVES = {"K-A1", "K-A2"}
ASSERTED_PRIMITIVES = {"K-C1", "K-B1", "K-C3"}

_OBO = "http://purl.obolibrary.org/obo/"

# Relations whose relatum cannot sustain them if the bearer is absent. Used for
# the partial K-C3 reading Table 7 allows.
_DEPENDENCE_PROPERTIES = {
    _OBO + "BFO_0000197",   # inheres in
    _OBO + "RO_0000052",    # inheres in
    _OBO + "BFO_0000196",   # bearer of
    _OBO + "RO_0000053",    # bearer of
}

_SPECIFICALLY_DEPENDENT = _OBO + "BFO_0000020"


def _locus(binding, iri):
    return binding.locus_of(iri) or "" if binding else ""


# --- K-A1 / K-A2 --------------------------------------------------------------

def from_stage_c(stage_result, binding=None):
    """Retype an ``owltester.stages.stage_c`` result onto K-A1 / K-A2.

    Stage C reports both whole-ontology inconsistency and per-class
    unsatisfiability under the same ``E_INCONSISTENT`` code. The kernel
    separates them: K-A1 is the theory admitting no model at all, K-A2 is the
    theory remaining satisfiable while some *term* is not. The distinction
    matters because K-A2 is compatible with a perfectly usable artifact and
    K-A1 is not.
    """
    findings = []
    if stage_result is None or stage_result.skipped:
        return findings

    unsat = stage_result.notes.get("unsatisfiable_classes", [])
    for f in stage_result.findings:
        if f.code != "E_INCONSISTENT":
            continue
        if not f.iri:
            findings.append(RecognitionFinding(
                kernel="K-A1", message=f.message, instrument=INSTRUMENT,
                evidence={"source": "stage_c"}))
        else:
            findings.append(RecognitionFinding(
                kernel="K-A2", message=f.message, iri=f.iri,
                locus=_locus(binding, f.iri), instrument=INSTRUMENT,
                evidence={"source": "stage_c"}))
    if not findings and unsat:
        for iri in unsat:
            findings.append(RecognitionFinding(
                kernel="K-A2",
                message=f"Class is unsatisfiable (equivalent to owl:Nothing): {iri}",
                iri=iri, locus=_locus(binding, iri), instrument=INSTRUMENT,
                evidence={"source": "stage_c"}))
    return findings


# --- K-C1 ---------------------------------------------------------------------

def from_bfo_lint(lint_findings, ctx=None, binding=None):
    """Retype ``bfo_lint`` clashes onto K-C1, marking inherited ones blanket.

    A class that clashes only because its parent does is not an independent
    discovery. The paper's ICD-11 measurement turned on exactly this: a single
    contestable typing decision on one parent propagated to all 154 traditional
    medicine patterns, and the resulting density figure collapsed by an order
    of magnitude once the blanket flag was separated out. Marking scope here is
    what lets the measure report both readings.
    """
    findings = []
    flagged = {lf.cls_iri for lf in lint_findings}
    for lf in lint_findings:
        scope = "per-entity"
        if ctx is not None:
            parents = set(ctx.edges.get(lf.cls_iri, ()))
            if parents & flagged:
                scope = BLANKET
        findings.append(RecognitionFinding(
            kernel="K-C1", message=lf.message, iri=lf.cls_iri,
            locus=_locus(binding, lf.cls_iri), instrument=INSTRUMENT,
            flag_scope=scope,
            evidence={"source": "bfo_lint",
                      "category_a": lf.category_a_iri,
                      "category_b": lf.category_b_iri}))
    return findings


# --- K-B1 (cyclic subsumption only) -------------------------------------------

def _short(iri):
    return iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _strongly_connected(edges, nodes):
    """Tarjan's SCC, iterative. Yields components of size > 1 and self-loops.

    A per-node search would be O(V*E) and this runs over whole classifications
    -- ICD-11 alone is several thousand classes -- so one linear pass it is.
    """
    index = {}
    low = {}
    on_stack = set()
    stack = []
    counter = [0]

    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(edges.get(root, ())))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)

        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter[0]
                    counter[0] += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(edges.get(child, ()))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1 or node in edges.get(node, ()):
                    yield component


def subsumption_cycles(ctx, binding=None):
    """K-B1 restricted to what DL sees: a cycle in asserted subClassOf.

    Table 7 is explicit that a reasoner catches circularity only in this form.
    Definitional and grounding cycles need the structural detector.
    """
    findings = []
    for component in _strongly_connected(ctx.edges, ctx.classes):
        members = sorted(component)
        findings.append(RecognitionFinding(
            kernel="K-B1",
            message="Subsumption cycle: "
                    + " <-> ".join(_short(c) for c in members),
            iri=members[0], locus=_locus(binding, members[0]),
            instrument=INSTRUMENT,
            evidence={"cycle": members, "kind": "subsumption"}))
    return findings


# --- K-C3 (partial) -----------------------------------------------------------

def unborne_dependents(ctx, binding=None):
    """K-C3 as far as domain, range, and cardinality axioms reach.

    A specifically dependent continuant with no asserted bearer. Table 7 marks
    this partial for good reason: the reasoner sees a missing axiom, not a
    severed grounding, and the two coincide only when the artifact was meant to
    assert the bearer in the first place. Reported as a candidate accordingly.
    """
    findings = []
    for cls_iri in ctx.classes:
        if _SPECIFICALLY_DEPENDENT not in ctx.bfo_parents(cls_iri):
            continue
        if _has_dependence_axiom(ctx.graph, cls_iri):
            continue
        findings.append(RecognitionFinding(
            kernel="K-C3",
            message=("Specifically dependent continuant with no asserted "
                     f"bearer: {cls_iri}"),
            iri=cls_iri, locus=_locus(binding, cls_iri), instrument=INSTRUMENT,
            evidence={"partial": True,
                      "note": "Detected as a missing bearer axiom. Whether the "
                              "grounding is severed or merely unasserted needs "
                              "a look at the source."}))
    return findings


def _has_dependence_axiom(graph, cls_iri):
    try:
        from rdflib import BNode, OWL, RDFS, URIRef
    except Exception:  # noqa: BLE001
        return True     # cannot tell; do not accuse
    subject = URIRef(cls_iri)
    for _s, _p, sup in graph.triples((subject, RDFS.subClassOf, None)):
        if isinstance(sup, BNode):
            prop = graph.value(sup, OWL.onProperty)
            if prop is not None and str(prop) in _DEPENDENCE_PROPERTIES:
                return True
    return False


# --- entry point --------------------------------------------------------------

def run(ctx, binding=None, stage_c_result=None, lint_findings=None,
        lint_ran=True):
    """Every K-primitive this instrument can reach, for one artifact.

    ``stage_c_result=None`` means the reasoner did not run, so K-A1 and K-A2
    go unattempted rather than being reported as clean. Likewise ``lint_ran``
    for K-C1: without upper-level disjointness there is nothing for a category
    violation to violate.
    """
    result = DetectorResult()

    if stage_c_result is not None:
        result.findings.extend(from_stage_c(stage_c_result, binding))
        result.attempted |= REASONER_PRIMITIVES
    else:
        result.notes["K-A1/K-A2"] = "no reasoner verdict for this artifact"

    if lint_ran:
        result.findings.extend(from_bfo_lint(lint_findings or [], ctx, binding))
        result.attempted.add("K-C1")
    else:
        result.notes["K-C1"] = "upper-level disjointness unavailable"

    result.findings.extend(subsumption_cycles(ctx, binding))
    result.attempted.add("K-B1")

    result.findings.extend(unborne_dependents(ctx, binding))
    result.attempted.add("K-C3")

    return result
