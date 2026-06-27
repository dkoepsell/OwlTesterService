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


def choose_drop_iri(category_a_iri, category_b_iri, catalog):
    """Pick which of two clashing BFO categories to drop, keeping the more specific.

    Specificity is the size of a category's BFO ancestor set (deeper in the BFO
    tree means more ancestors). We keep the deeper category and drop the broader
    one. When the two are equally specific (for example top-level disjoint
    siblings like Continuant and Occurrent), the choice is genuinely arbitrary,
    so we break the tie deterministically by IRI: keep the earlier IRI, drop the
    later one. Returns the IRI to drop.
    """
    spec_a = len(catalog.ancestors(category_a_iri)) if catalog else 0
    spec_b = len(catalog.ancestors(category_b_iri)) if catalog else 0
    if spec_a > spec_b:
        return category_b_iri
    if spec_b > spec_a:
        return category_a_iri
    return max(category_a_iri, category_b_iri)


def fix_all_straddles(src_path, findings, catalog):
    """Resolve every partition straddle in one pass, keeping the more specific
    BFO category in each.

    Args:
        src_path: path to the original ontology file (any rdflib-parseable format).
        findings: the stored lint findings (list of dicts with class_iri,
            category_a_iri, category_b_iri), as produced by bfo_lint.
        catalog: a bfo.catalog.BfoCatalog, used to decide which edge to drop.

    Returns:
        (bytes, int): the corrected ontology as RDF/XML, and the number of
        subClassOf edges removed.

    Raises:
        ValueError: if none of the flagged edges are present in the file.

    Parses and serializes once. Applying the per-pair "keep the more specific"
    rule across all findings converges to keeping a single most-specific category
    even when a class straddles three or more disjoint categories.
    """
    graph = rdflib.Graph()
    graph.parse(src_path)

    removed = 0
    for finding in (findings or []):
        class_iri = finding.get("class_iri")
        a = finding.get("category_a_iri")
        b = finding.get("category_b_iri")
        if not (class_iri and a and b):
            continue
        drop_iri = choose_drop_iri(a, b, catalog)
        if not drop_iri.startswith(BFO_IRI_PREFIX):
            continue
        triple = (rdflib.URIRef(class_iri), RDFS.subClassOf, rdflib.URIRef(drop_iri))
        if triple in graph:
            graph.remove(triple)
            removed += 1

    if removed == 0:
        raise ValueError(
            "No straddle edges were found to remove; the ontology may have "
            "changed since it was analyzed"
        )
    return graph.serialize(format="xml", encoding="utf-8"), removed
