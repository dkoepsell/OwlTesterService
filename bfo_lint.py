"""
BFO conformance lint: a fast, pre-reasoner check for partition straddles.

Most real BFO modelling errors are partition straddles: a class placed (directly
or transitively) under two BFO categories that are disjoint, such as a class that
is both a Quality and a Disposition, or both a Continuant and an Occurrent. These
are catchable by a graph walk over asserted subclass edges, with far better error
locality than a raw owl:Nothing from a DL reasoner, and without invoking one.

The lint reuses the rdflib graph already parsed during structural extraction (no
second parse) and the disjointness closure from the bfo/ catalog. It runs in well
under a second and never calls Pellet.
"""

import rdflib
from rdflib.namespace import RDFS

from bfo.catalog import BFO_IRI_PREFIX

CONTINUANT_IRI = "http://purl.obolibrary.org/obo/BFO_0000002"
OCCURRENT_IRI = "http://purl.obolibrary.org/obo/BFO_0000003"
MATERIAL_ENTITY_IRI = "http://purl.obolibrary.org/obo/BFO_0000040"
IMMATERIAL_ENTITY_IRI = "http://purl.obolibrary.org/obo/BFO_0000141"


class LintFinding:
    """One partition straddle: a user class under two clashing BFO categories.

    Carries the IRIs (not just labels) so a remediation step can identify the
    exact subClassOf edges to rewrite.
    """

    def __init__(self, cls, category_a, category_b, message,
                 cls_iri="", category_a_iri="", category_b_iri=""):
        self.cls = cls
        self.category_a = category_a
        self.category_b = category_b
        self.message = message
        self.cls_iri = cls_iri
        self.category_a_iri = category_a_iri
        self.category_b_iri = category_b_iri

    def to_dict(self):
        return {
            "class": self.cls,
            "category_a": self.category_a,
            "category_b": self.category_b,
            "message": self.message,
            "class_iri": self.cls_iri,
            "category_a_iri": self.category_a_iri,
            "category_b_iri": self.category_b_iri,
        }

    def to_derivation_step(self):
        """Render as a derivation-trace step so the lint can populate the
        otherwise-empty Derivation Trace panel when the reasoner finds nothing."""
        return {
            "axiom_type": "Inconsistency",
            "origin": "BFO Lint",
            "confidence": "High",
            "description": (
                f"{self.cls} is placed under both {self.category_a} and "
                f"{self.category_b}, which are disjoint."
            ),
            "reason": self.message,
            "supporting_facts": [
                f"{self.cls} transitively subclasses {self.category_a}",
                f"{self.cls} transitively subclasses {self.category_b}",
                f"{self.category_a} and {self.category_b} are disjoint in BFO 2020",
            ],
        }


def _is_bfo(iri):
    return iri.startswith(BFO_IRI_PREFIX)


def _build_subclass_edges(graph):
    """child_iri -> set(parent_iri) over named (URIRef) rdfs:subClassOf edges."""
    edges = {}
    for s, _, o in graph.triples((None, RDFS.subClassOf, None)):
        if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
            edges.setdefault(str(s), set()).add(str(o))
    return edges


def _bfo_parents(cls_iri, edges):
    """The set of BFO category IRIs the class reaches by walking subclass edges
    upward. Stop expanding once a BFO node is reached: the disjointness closure
    already accounts for BFO ancestors, so we only need the entry points."""
    reached = set()
    seen = set()
    stack = list(edges.get(cls_iri, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        if _is_bfo(node):
            reached.add(node)
            continue  # do not climb into BFO's own hierarchy
        stack.extend(edges.get(node, ()))
    return reached


def _message(cls_name, label_a, iri_a, label_b, iri_b, catalog):
    """Produce localized, actionable copy for a straddle. No em-dashes."""
    anc_a = catalog.ancestors(iri_a)
    anc_b = catalog.ancestors(iri_b)

    def under(anc_x, anc_y, root_x, root_y):
        return (root_x in anc_x and root_y in anc_y) or (
            root_y in anc_x and root_x in anc_y
        )

    labels = {label_a.lower(), label_b.lower()}

    if labels == {"quality", "disposition"}:
        return (
            f"{cls_name} is placed under both Quality and Disposition, which are "
            f"disjoint. Pick one. If {cls_name} is a realizable that the bearer is "
            f"engineered for, model it as a Disposition (or Function) and give the "
            f"measured magnitude a separate Quality."
        )
    if under(anc_a, anc_b, CONTINUANT_IRI, OCCURRENT_IRI):
        return (
            f"{cls_name} is both a {label_a} and a {label_b}. Continuant and "
            f"Occurrent are disjoint. Separate the continuant aspect from the "
            f"process or other occurrent it participates in."
        )
    if under(anc_a, anc_b, MATERIAL_ENTITY_IRI, IMMATERIAL_ENTITY_IRI):
        return (
            f"{cls_name} is both a {label_a} and a {label_b}. Material entity and "
            f"immaterial entity are disjoint. Decide whether {cls_name} bears matter "
            f"or is a boundary, site, or spatial region."
        )
    return (
        f"{cls_name} is placed under both {label_a} and {label_b}, which are "
        f"disjoint in BFO 2020. A single class cannot be both. Split {cls_name} "
        f"into separate classes, one per category, or pick the category that fits."
    )


def bfo_lint(graph, catalog):
    """Return the list of BFO partition-straddle findings for a user ontology.

    Args:
        graph: the already-parsed rdflib.Graph for the user ontology.
        catalog: a bfo.catalog.BfoCatalog.

    Pure graph walking plus the precomputed disjointness closure. Does not invoke
    a DL reasoner. Returns an empty list when the catalog is unavailable.
    """
    if catalog is None:
        return []

    edges = _build_subclass_edges(graph)
    findings = []

    for cls_iri in edges:
        if _is_bfo(cls_iri):
            continue  # only lint user classes, not BFO itself
        parents = _bfo_parents(cls_iri, edges)
        if len(parents) < 2:
            continue
        parents = sorted(parents)
        cls_name = cls_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        for i in range(len(parents)):
            for j in range(i + 1, len(parents)):
                a, b = parents[i], parents[j]
                if catalog.clash(a, b):
                    label_a = catalog.label_for(a)
                    label_b = catalog.label_for(b)
                    findings.append(
                        LintFinding(
                            cls_name,
                            label_a,
                            label_b,
                            _message(cls_name, label_a, a, label_b, b, catalog),
                            cls_iri=cls_iri,
                            category_a_iri=a,
                            category_b_iri=b,
                        )
                    )

    return findings
