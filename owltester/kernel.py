"""Kernel abstraction.

The kernel is the reference point for several stages:

* A4 — the BFO anchor classes that must be present *and populated*.
* A5 — ``kernel_size`` sets the lower bound and ``kernel_size x max_factor`` the
  upper bound on a conformant artifact's class count.
* B3 — SOoL node typing: each SOoL top-category (Norm, Role, ...) declares the
  BFO category it must ground to; a domain class under that category that also
  reaches a *disjoint* BFO category is mistyped.
* D  — competency constraints reference the same typing.

The gate ships a minimal, BFO-grounded ``sool-kernel.ttl`` (see fixtures/) so the
typing-dependent stages have something to run against. A larger published kernel
can be supplied with ``--kernel`` and the same logic applies, since everything is
derived from the kernel graph rather than hard-coded vocabulary.
"""

import os
from dataclasses import dataclass, field

import rdflib
from rdflib import RDF, RDFS, OWL, URIRef

from .counts import named_classes

# BFO 2020 anchor IRIs required to be present and populated by A4.
BFO = "http://purl.obolibrary.org/obo/"
ANCHORS = {
    "Continuant": BFO + "BFO_0000002",
    "Occurrent": BFO + "BFO_0000003",
    "SpecificallyDependentContinuant": BFO + "BFO_0000020",
    "RealizableEntity": BFO + "BFO_0000017",
    "Role": BFO + "BFO_0000023",
    "MaterialEntity": BFO + "BFO_0000040",
    "GenericallyDependentContinuant": BFO + "BFO_0000031",
}
ANCHOR_IRIS = set(ANCHORS.values())

_DEFAULT_KERNEL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "sool-kernel.ttl",
)


@dataclass
class SoolCategory:
    """A SOoL top-category declared in the kernel and the BFO anchor it must
    ground to (its directly-asserted BFO superclass)."""
    iri: str
    label: str
    required_anchor: str  # BFO IRI


@dataclass
class Kernel:
    path: str
    size: int                                   # class count, for A5
    categories: list = field(default_factory=list)   # list[SoolCategory]
    contradiction_types: set = field(default_factory=set)  # IRIs, for D3
    version: str = "sool-kernel/unversioned"

    def category_for_anchor(self, anchor_iri):
        return [c for c in self.categories if c.required_anchor == anchor_iri]


def _label(g, iri):
    for o in g.objects(URIRef(iri), RDFS.label):
        return str(o)
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def default_kernel_path():
    return _DEFAULT_KERNEL


def load_kernel(path=None):
    """Load a kernel from TTL. Falls back to the bundled sool-kernel.ttl."""
    path = path or _DEFAULT_KERNEL
    g = rdflib.Graph()
    g.parse(path, format="turtle")

    classes = named_classes(g)
    size = len(classes)

    # SOoL categories: any *non-BFO* class whose asserted superclass is a BFO
    # anchor. Its required anchor is that superclass.
    categories = []
    for c in classes:
        if c.startswith(BFO):
            continue
        for parent in g.objects(URIRef(c), RDFS.subClassOf):
            if isinstance(parent, URIRef) and str(parent) in ANCHOR_IRIS:
                categories.append(SoolCategory(
                    iri=c, label=_label(g, c), required_anchor=str(parent)))

    # Contradiction types: subclasses (any depth, asserted) of a class labelled
    # like a contradiction, used by D3.
    contradiction_roots = {
        c for c in classes
        if "contradiction" in _label(g, c).lower()
    }
    contradiction_types = set()
    if contradiction_roots:
        # transitive closure over asserted subClassOf within the kernel
        children = {}
        for s, _, o in g.triples((None, RDFS.subClassOf, None)):
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                children.setdefault(str(o), set()).add(str(s))
        stack = list(contradiction_roots)
        while stack:
            node = stack.pop()
            for ch in children.get(node, ()):
                if ch not in contradiction_types:
                    contradiction_types.add(ch)
                    stack.append(ch)

    version = "sool-kernel/unversioned"
    for o in g.objects(None, OWL.versionInfo):
        version = str(o)
        break

    return Kernel(path=path, size=size, categories=categories,
                  contradiction_types=contradiction_types, version=version)
