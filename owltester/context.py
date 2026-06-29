"""Shared, parse-once context handed to every stage."""

import rdflib
from rdflib import RDFS, URIRef

from .counts import load_graph, count, named_classes
from .kernel import ANCHOR_IRIS

BFO_PREFIX = "http://purl.obolibrary.org/obo/BFO_"


class GateContext:
    """Everything the stages need, computed once from a single parse.

    ``baseline`` is the input Counts when checking a *repair* output (Stage E);
    it is None for a plain ``check``.
    """

    def __init__(self, path, kernel, catalog=None, baseline=None, removals=None):
        self.path = str(path)
        self.kernel = kernel
        self.catalog = catalog
        self.baseline = baseline
        self.removals = removals or []

        self.graph = load_graph(path)
        self.counts = count(self.graph)
        self.classes = named_classes(self.graph)

        # child_iri -> set(parent_iri) over named subClassOf edges. Counts come
        # from the artifact alone, but *grounding* is judged with the kernel as
        # background: an artifact class grounds to BFO through the SOoL categories
        # the kernel defines, so we merge the kernel's subClassOf edges in here.
        self.edges = {}
        self._add_edges(self.graph)
        if kernel is not None and getattr(kernel, "path", None):
            try:
                kg = rdflib.Graph()
                kg.parse(kernel.path, format="turtle")
                self._add_edges(kg)
            except Exception:  # noqa: BLE001 - kernel grounding is best-effort
                pass

    def _add_edges(self, g):
        for s, _, o in g.triples((None, RDFS.subClassOf, None)):
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                self.edges.setdefault(str(s), set()).add(str(o))

    @staticmethod
    def is_bfo(iri):
        return iri.startswith(BFO_PREFIX)

    def bfo_parents(self, cls_iri):
        """BFO anchor/category IRIs reachable upward from cls_iri (entry points
        into BFO; does not climb BFO's own hierarchy)."""
        reached, seen = set(), set()
        stack = list(self.edges.get(cls_iri, ()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            if self.is_bfo(node):
                reached.add(node)
                continue
            stack.extend(self.edges.get(node, ()))
        return reached

    def reaches(self, cls_iri, target_iri):
        """True if cls_iri reaches target_iri via subClassOf*. Uses the BFO
        catalog's ancestor closure to bridge into BFO's internal hierarchy."""
        if cls_iri == target_iri:
            return True
        seen = set()
        stack = list(self.edges.get(cls_iri, ()))
        while stack:
            node = stack.pop()
            if node == target_iri:
                return True
            if node in seen:
                continue
            seen.add(node)
            if self.catalog is not None and self.is_bfo(node):
                if target_iri in self.catalog.ancestors(node):
                    return True
            stack.extend(self.edges.get(node, ()))
        return False
