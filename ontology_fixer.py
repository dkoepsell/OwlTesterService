"""
Ontology remediation: apply a chosen fix to a partition straddle.

The BFO conformance lint flags classes placed under two disjoint BFO categories.
The only remediation offered here is "reassign": drop one of the two clashing
rdfs:subClassOf edges, keeping the category the user chose. This produces a
corrected ontology that can be downloaded or re-analyzed for full coherence.

This module only rewrites; it does not decide which edge to drop. It refuses to
remove anything other than a subClassOf edge to a BFO category that actually
exists in the file, so it cannot be used to strip arbitrary axioms.
"""

import rdflib
from rdflib.namespace import RDFS

from bfo.catalog import BFO_IRI_PREFIX


def fix_straddle(src_path, class_iri, drop_category_iri):
    """Remove the (class_iri, rdfs:subClassOf, drop_category_iri) edge.

    Args:
        src_path: path to the original ontology file (any rdflib-parseable format).
        class_iri: IRI of the straddling user class.
        drop_category_iri: IRI of the BFO category to stop subclassing.

    Returns:
        bytes: the corrected ontology serialized as RDF/XML.

    Raises:
        ValueError: if drop_category_iri is not a BFO category, or the edge to
            remove is not present in the file.
    """
    if not drop_category_iri or not drop_category_iri.startswith(BFO_IRI_PREFIX):
        raise ValueError("Refusing to drop a non-BFO superclass edge")

    graph = rdflib.Graph()
    graph.parse(src_path)

    triple = (rdflib.URIRef(class_iri), RDFS.subClassOf, rdflib.URIRef(drop_category_iri))
    if triple not in graph:
        raise ValueError(
            "The subClassOf edge to remove was not found; the ontology may have "
            "changed since it was analyzed"
        )

    graph.remove(triple)
    return graph.serialize(format="xml", encoding="utf-8")
