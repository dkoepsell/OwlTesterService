"""Reading OWL class expressions as graph structure.

The structural detectors need to know which named classes a definition mentions
and, crucially, *in what polarity*. A term appearing under a complement is doing
opposite work to the same term appearing as a conjunct, and the difference is
what separates a residual definition from an ordinary one and an equivocation
from a coincidence.

rdflib gives us blank-node trees; these helpers flatten them.
"""

try:
    from rdflib import BNode, OWL, RDF, RDFS, URIRef
    _RDFLIB = True
except Exception:  # noqa: BLE001 - detectors degrade to no-ops without rdflib
    _RDFLIB = False


def available():
    return _RDFLIB


def rdf_list(graph, node):
    """A well-formed RDF collection as a Python list; [] if malformed."""
    items = []
    seen = set()
    while node is not None and node != RDF.nil and node not in seen:
        seen.add(node)
        first = graph.value(node, RDF.first)
        if first is not None:
            items.append(first)
        node = graph.value(node, RDF.rest)
    return items


def _walk(graph, node, polarity, positive, negative, seen, restrictions):
    # Keyed by polarity, not by node alone. A term required in one conjunct and
    # excluded in another must be recorded on both sides -- that co-occurrence
    # *is* the equivocation signature. A node-only guard would see the second
    # visit as a repeat and drop it, and K-B2 would never fire.
    if node is None:
        return
    key = (node, polarity)
    if key in seen:
        return
    seen.add(key)

    if isinstance(node, URIRef):
        (positive if polarity > 0 else negative).add(str(node))
        return

    complement = graph.value(node, OWL.complementOf)
    if complement is not None:
        _walk(graph, complement, -polarity, positive, negative, seen, restrictions)
        return

    for collection_property in (OWL.intersectionOf, OWL.unionOf):
        collection = graph.value(node, collection_property)
        if collection is not None:
            for member in rdf_list(graph, collection):
                _walk(graph, member, polarity, positive, negative, seen,
                      restrictions)
            return

    on_property = graph.value(node, OWL.onProperty)
    if on_property is not None:
        restrictions.add(str(on_property))
        for filler_property in (OWL.someValuesFrom, OWL.allValuesFrom,
                                OWL.onClass, OWL.hasValue):
            filler = graph.value(node, filler_property)
            if filler is not None:
                _walk(graph, filler, polarity, positive, negative, seen,
                      restrictions)
        return

    one_of = graph.value(node, OWL.oneOf)
    if one_of is not None:
        for member in rdf_list(graph, one_of):
            if isinstance(member, URIRef):
                (positive if polarity > 0 else negative).add(str(member))


def expression_terms(graph, node):
    """``(positive, negative, properties)`` named IRIs used in an expression.

    ``positive`` are terms the expression requires, ``negative`` are terms it
    excludes. Polarity flips under every ``owl:complementOf``, so a term nested
    in two complements comes back positive, which is correct.
    """
    positive, negative, properties = set(), set(), set()
    if not _RDFLIB:
        return positive, negative, properties
    _walk(graph, node, 1, positive, negative, set(), properties)
    return positive, negative, properties


def definition_nodes(graph, cls_iri):
    """Every expression node that defines or constrains ``cls_iri``."""
    if not _RDFLIB:
        return []
    subject = URIRef(cls_iri)
    nodes = []
    for _s, _p, o in graph.triples((subject, OWL.equivalentClass, None)):
        nodes.append(o)
    for _s, _p, o in graph.triples((subject, RDFS.subClassOf, None)):
        nodes.append(o)
    return nodes


def equivalence_nodes(graph, cls_iri):
    """Only the full definitions -- ``owl:equivalentClass`` right-hand sides."""
    if not _RDFLIB:
        return []
    return [o for _s, _p, o in
            graph.triples((URIRef(cls_iri), OWL.equivalentClass, None))]


def union_members(graph, node):
    """Named members of a top-level ``owl:unionOf``, or [] if it is not one."""
    if not _RDFLIB or isinstance(node, URIRef):
        return []
    collection = graph.value(node, OWL.unionOf)
    if collection is None:
        return []
    return [str(m) for m in rdf_list(graph, collection) if isinstance(m, URIRef)]


def disjoint_with(graph, cls_iri):
    """Named classes asserted disjoint from ``cls_iri``, both directions."""
    if not _RDFLIB:
        return set()
    subject = URIRef(cls_iri)
    out = set()
    for _s, _p, o in graph.triples((subject, OWL.disjointWith, None)):
        if isinstance(o, URIRef):
            out.add(str(o))
    for s, _p, _o in graph.triples((None, OWL.disjointWith, subject)):
        if isinstance(s, URIRef):
            out.add(str(s))
    return out


def declared_types(graph, iri):
    """The OWL vocabulary types an IRI is declared under."""
    if not _RDFLIB:
        return set()
    interesting = {OWL.Class, OWL.NamedIndividual, OWL.ObjectProperty,
                   OWL.DatatypeProperty, OWL.AnnotationProperty,
                   OWL.Restriction, RDFS.Datatype}
    return {str(o) for _s, _p, o in graph.triples((URIRef(iri), RDF.type, None))
            if o in interesting}
