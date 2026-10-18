"""Recognition-chain checks over asserted axioms (spec section 5, step 4).

A `status` needs a kwv:issuedBy restriction, and each issuer needs a
kwv:canGrant restriction back to the status. An `obligation` needs a
kwv:owedTo restriction. Restrictions inherited from named superclasses count.
"""

from __future__ import annotations

from rdflib import OWL, RDFS, URIRef

from kindwork.bundle import KWV, local_name
from kindwork.findings import make_finding

FILLERS = (OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass)


def restrictions(graph, cls):
    """{property IRI: set(filler IRIs)} from cls and its named user superclasses."""
    out, seen, stack = {}, set(), [URIRef(cls)]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for parent in graph.objects(node, RDFS.subClassOf):
            prop = graph.value(parent, OWL.onProperty)
            if prop is not None:
                fillers = out.setdefault(str(prop), set())
                for p in FILLERS:
                    f = graph.value(parent, p)
                    if isinstance(f, URIRef):
                        fillers.add(str(f))
            elif isinstance(parent, URIRef):
                stack.append(parent)
    return out


def _keyword_classes(graph, keyword):
    return sorted(str(c) for c, k in graph.subject_objects(KWV.keyword)
                  if isinstance(c, URIRef) and str(k) == keyword)


def chain_findings(bundle):
    g = bundle.ontology
    found = []
    for cls in _keyword_classes(g, "status"):
        name = bundle.label_for(cls)
        issuers = restrictions(g, cls).get(str(KWV.issuedBy), set())
        if not issuers:
            found.append(make_finding(
                "", "chain", "chain", "fail", [cls],
                f"{name} has no issuer",
                f"A status exists because some authority grants it. Nothing in the model says "
                f"who grants {name.lower()}, so the chain from authority to holder does not "
                f"close. Link it to the authority that issues it.",
                [f'{local_name(cls)} kwv:keyword "status"',
                 f"{local_name(cls)} has no kwv:issuedBy restriction"]))
            continue
        for issuer in sorted(issuers):
            grants = restrictions(g, issuer).get(str(KWV.canGrant), set())
            if cls in grants:
                continue
            iname = bundle.label_for(issuer)
            found.append(make_finding(
                "", "chain", "chain", "fail", [cls, issuer],
                f"{iname} is not set up to grant {name.lower()}",
                f"{name} is issued by {iname}, but nothing gives {iname} the power to grant it. "
                f"Give {iname} that power, or name a different issuer.",
                [f"{local_name(cls)} kwv:issuedBy {local_name(issuer)}",
                 f"{local_name(issuer)} has no kwv:canGrant {local_name(cls)} restriction"]))
    for cls in _keyword_classes(g, "obligation"):
        if restrictions(g, cls).get(str(KWV.owedTo)):
            continue
        name = bundle.label_for(cls)
        found.append(make_finding(
            "", "chain", "chain", "fail", [cls],
            f"{name} is not owed to anyone",
            f"An obligation binds someone for the benefit of someone who can claim it. Nothing "
            f"in the model says who can claim {name.lower()}. Name the party it is owed to.",
            [f'{local_name(cls)} kwv:keyword "obligation"',
             f"{local_name(cls)} has no kwv:owedTo restriction"]))
    return found
