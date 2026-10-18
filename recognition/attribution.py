"""The artifact-versus-source discipline (paper §10).

Every result depends on a distinction no tool enforces: whether a detected
defect belongs to the classification or to our translation of it. The paper
states its own audit in full on the grounds that "an instrument that cannot
catch error in its own output should not be trusted on anyone else's", and
reports one occasion where its reporting layer described residual unsatisfiable
classes as inconsistencies in the source text when they were inconsistencies in
the translation.

This module encodes the one extraction defect the paper names precisely enough
to detect mechanically. Everything else stays ``undetermined``: attribution is a
discipline the analyst enforces, and a tool that guessed here would be
reintroducing exactly the conflation the discipline exists to prevent.
"""

from .finding import ARTIFACT

_OBO = "http://purl.obolibrary.org/obo/"

# Properties that hang a realizable on a bearer. BFO 2020 has only "bearer of";
# the RO shorthands are what LLM extractors actually emit.
BEARER_PROPERTIES = {
    _OBO + "BFO_0000196",   # bearer of
    _OBO + "RO_0000053",    # bearer of
    _OBO + "RO_0000091",    # has disposition
    _OBO + "RO_0000087",    # has role
    _OBO + "RO_0000085",    # has function
}

# The realizable branch a correctly-grounded disposition already sits in.
REALIZABLE_IRIS = {
    _OBO + "BFO_0000017",   # realizable entity
    _OBO + "BFO_0000016",   # disposition
    _OBO + "BFO_0000023",   # role
    _OBO + "BFO_0000034",   # function
}

REIFIED_REALIZABLE = "reified-realizable-on-bearer"


def _restriction_properties(graph, cls_iri):
    """Object properties used in existential restrictions on ``cls_iri``."""
    try:
        from rdflib import BNode, OWL, RDFS, URIRef
    except Exception:  # noqa: BLE001
        return set()

    props = set()
    subject = URIRef(cls_iri)
    for _s, _p, sup in graph.triples((subject, RDFS.subClassOf, None)):
        if not isinstance(sup, BNode):
            continue
        prop = graph.value(sup, OWL.onProperty)
        if prop is not None:
            props.add(str(prop))
    for _s, _p, eq in graph.triples((subject, OWL.equivalentClass, None)):
        if isinstance(eq, BNode):
            prop = graph.value(eq, OWL.onProperty)
            if prop is not None:
                props.add(str(prop))
    return props


def reified_realizables(ctx):
    """Classes exhibiting the extraction defect described in §10.1.

    The signature: a class that is *already* correctly grounded in the
    realizable branch and *additionally* carries a restriction hanging a
    realizable on a bearer. The extractor has reified the disposition and hung
    it on its own bearer, so the class is forced under two disjoint BFO
    categories at once.

    The defect concentrates on the most mind-independent entities in a corpus,
    since material entities are what get wrongly minted as bearers of
    realizables -- which is exactly why leaving it unattributed would libel the
    source ontology's least controversial content.
    """
    hits = {}
    for cls_iri in ctx.classes:
        anchors = ctx.bfo_parents(cls_iri)
        if not (anchors & REALIZABLE_IRIS):
            continue
        used = _restriction_properties(ctx.graph, cls_iri) & BEARER_PROPERTIES
        if used:
            hits[cls_iri] = sorted(used)
    return hits


def apply(findings, ctx):
    """Mark findings that our own translation is responsible for.

    Mutates and returns ``findings``. Only the named rule fires; everything
    else keeps its ``undetermined`` default.
    """
    hits = reified_realizables(ctx)
    if not hits:
        return findings
    for f in findings:
        if f.iri in hits and f.kernel in ("K-A1", "K-A2", "K-C1"):
            f.attribution = ARTIFACT
            f.evidence["artifact_rule"] = REIFIED_REALIZABLE
            f.evidence["bearer_properties"] = hits[f.iri]
            f.evidence["artifact_rule_note"] = (
                "This class is already grounded as a realizable and also hangs "
                "a realizable on a bearer. That is a known extraction defect, "
                "not a defect of the source classification.")
    return findings
