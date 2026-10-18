"""Map the reasoner and the BFO lint to consistency, coherence and entailment findings.

Severity follows spec section 4: `partition` when a class straddles continuant
and occurrent, `within` when its two categories are disjoint on the same side,
`info` when the reasoner proves a class empty for a reason that is not a simple
placement under two categories.
"""

from __future__ import annotations

from collections import deque

import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from bfo.catalog import BFO_IRI_PREFIX
from bfo_lint import CONTINUANT_IRI, OCCURRENT_IRI, bfo_lint
from kindwork.bundle import local_name
from kindwork.findings import make_finding
from kindwork.reasoning import IAO_ICE, OBO, bridge_iao

# Plain phrases for BFO and IAO categories, used in titles.
PLAIN = {
    "BFO_0000002": "something that lasts through time",
    "BFO_0000003": "something that unfolds in time",
    "BFO_0000015": "something that happens",
    "BFO_0000016": "something someone has",
    "BFO_0000017": "something that can be acted out",
    "BFO_0000019": "a feature of something",
    "BFO_0000023": "a role",
    "BFO_0000024": "a part of a thing",
    "BFO_0000027": "a group of things",
    "BFO_0000029": "a place",
    "BFO_0000030": "a physical object",
    "BFO_0000031": "something that can be copied",
    "BFO_0000034": "a function",
    "BFO_0000035": "a moment",
    "BFO_0000038": "a span of time",
    "BFO_0000040": "a physical thing",
    "BFO_0000141": "something without matter",
    "IAO_0000030": "a written record",
}
IAO_LABELS = {str(IAO_ICE): "information content entity"}


def _is_obo(iri: str) -> bool:
    return iri.startswith(OBO)


def _plain(iri: str, catalog) -> str:
    return PLAIN.get(local_name(iri)) or f"a {_category_label(iri, catalog)}"


def _category_label(iri: str, catalog) -> str:
    return IAO_LABELS.get(iri) or (catalog.label_for(iri) if catalog else local_name(iri))


def named_parents(graph: rdflib.Graph):
    edges = {}
    for s, o in graph.subject_objects(RDFS.subClassOf):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            edges.setdefault(str(s), set()).add(str(o))
    return edges


def _path(edges, start, goal):
    """Shortest list of subclass edges from start up to goal, or []."""
    prev = {start: None}
    q = deque([start])
    while q:
        node = q.popleft()
        if node == goal:
            out = []
            while prev[node] is not None:
                out.append((prev[node], node))
                node = prev[node]
            return out[::-1]
        if _is_obo(node) and node not in (start, str(IAO_ICE)):
            continue  # climb through the IAO bridge only, never into BFO itself
        for p in sorted(edges.get(node, ())):
            if p not in prev:
                prev[p] = node
                q.append(p)
    return []


def _render_edges(edges_path, catalog):
    out = []
    for child, parent in edges_path:
        if _is_obo(child):
            break  # stop at the first BFO or IAO category
        target = (f"obo:{local_name(parent)} ({_category_label(parent, catalog)})"
                  if _is_obo(parent) else local_name(parent))
        out.append(f"{local_name(child)} SubClassOf {target}")
    return out


def _entry(edges, cls, category):
    """The category as the user sees it: IAO ICE rather than the GDC it bridges to."""
    p = _path(edges, cls, category)
    for child, parent in p:
        if _is_obo(parent):
            return parent, p
    return category, p


def coherence_findings(bundle, reasoned, catalog):
    graph = bridge_iao(bundle.ontology)
    edges = named_parents(graph)
    lint = {}
    for lf in bfo_lint(graph, catalog):
        lint.setdefault(lf.cls_iri, []).append(lf)

    unsat = set(reasoned.unsatisfiable if reasoned.status == "ok" else [])
    findings = []
    for cls in sorted(unsat | set(lint)):
        name = bundle.label_for(cls)
        straddles = lint.get(cls)
        if not straddles:
            findings.append(make_finding(
                "", "coherence", "info", "fail", [cls],
                f"{name} can have no instances",
                f"The reasoner proves that nothing can be {name.lower()}, but not because it sits "
                f"under two kinds of thing at once. One of its conditions rules it out. Any "
                f"conclusion that touches it is unsound until that condition is fixed.",
                []))
            continue
        lf = next((s for s in straddles if _crosses(s, catalog)), straddles[0])
        a, path_a = _entry(edges, cls, lf.category_a_iri)
        b, path_b = _entry(edges, cls, lf.category_b_iri)
        axioms = []
        for line in _render_edges(path_a, catalog) + _render_edges(path_b, catalog):
            if line not in axioms:
                axioms.append(line)
        title = f"{name} is both {_plain(a, catalog)} and {_plain(b, catalog)}"
        la, lb = _category_label(a, catalog), _category_label(b, catalog)
        if _crosses(lf, catalog):
            findings.append(make_finding(
                "", "coherence", "partition", "fail", [cls], title,
                f"It sits under {la} through one parent and under {lb} through another. "
                f"BFO keeps things that happen apart from things that last, so the class can "
                f"have no instances and every inference that touches it is unsound.",
                axioms))
        else:
            findings.append(make_finding(
                "", "coherence", "within", "fail", [cls], title,
                f"BFO keeps {la} and {lb} apart, so nothing can be both and the class can have "
                f"no instances. It needs to be one or the other, or be split into two classes, "
                f"one for each.",
                axioms))
    return findings


def _crosses(lint_finding, catalog):
    anc_a = catalog.ancestors(lint_finding.category_a_iri) | {lint_finding.category_a_iri}
    anc_b = catalog.ancestors(lint_finding.category_b_iri) | {lint_finding.category_b_iri}
    return ((CONTINUANT_IRI in anc_a and OCCURRENT_IRI in anc_b)
            or (OCCURRENT_IRI in anc_a and CONTINUANT_IRI in anc_b))


def user_classes(graph: rdflib.Graph):
    return sorted({str(c) for c in graph.subjects(RDF.type, OWL.Class)
                   if isinstance(c, URIRef) and not _is_obo(str(c))})


def entailment_findings(bundle, flagged):
    """Classes with no asserted path to BFO: nothing can be concluded about them."""
    edges = named_parents(bridge_iao(bundle.ontology))
    findings = []
    for cls in user_classes(bundle.ontology):
        if cls in flagged:
            continue
        seen, stack, placed = set(), [cls], False
        while stack and not placed:
            node = stack.pop()
            for p in edges.get(node, ()):
                if p.startswith(BFO_IRI_PREFIX):
                    placed = True
                    break
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        if placed:
            continue
        name = bundle.label_for(cls)
        findings.append(make_finding(
            "", "entailment", "info", "undetermined", [cls],
            f"{name} has no BFO category, so nothing can be concluded about it",
            "The class has no path to BFO. The reasoner accepts it but cannot say what kind "
            "of thing it is. Placing it would let the other checks reach it.",
            []))
    return findings


def consistency_findings(bundle, reasoned):
    title_name = bundle.label_for(bundle.ontology_iri) if bundle.ontology_iri else "The model"
    if reasoned.status == "inconsistent":
        return [make_finding(
            "", "consistency", "info", "fail", [],
            f"{title_name} contradicts itself",
            "No situation can satisfy everything the model says at once, so every conclusion "
            "drawn from it is unsound. The coherence findings, if any, point to where to look.",
            [reasoned.detail] if reasoned.detail else [])]
    if not reasoned.finished:
        why = ("ran out of time" if reasoned.status == "timeout"
               else "stopped with an error")
        return [make_finding(
            "", "consistency", "info", "undetermined", [],
            f"The reasoner {why}, so consistency is open",
            "Whether the model holds together could not be decided. Findings below that do "
            "not depend on the reasoner still stand. Try again, or split the model into "
            "smaller parts.",
            [reasoned.detail] if reasoned.detail else [])]
    if reasoned.unresolved_imports:
        return [make_finding(
            "", "entailment", "info", "undetermined", [],
            "Some imported ontologies were not loaded",
            "The model imports other ontologies that were not part of the upload. The checks "
            "ran without them, so anything they would add is not covered. Include them in "
            "the upload, or a zip, to check the whole model.",
            reasoned.unresolved_imports)]
    return []
