"""Artifact loading and structural counting.

Counts are the raw material for Stage A (smoke test) and Stage E (delta
invariant). They are computed from a single rdflib parse so the gate never needs
a DL reasoner just to decide an artifact is hollow.

The key counting decision: an *axiom* here means a logical axiom, not any RDF
triple. Bare `owl:Class` declarations, labels, and annotations do not count. This
is exactly what makes a 6,881-declaration / 0-axiom artifact register as
``axioms == 0`` rather than ``axioms == 6881``.
"""

from dataclasses import dataclass, asdict

import rdflib
from rdflib import RDF, RDFS, OWL, URIRef
from rdflib.term import BNode

# Triples whose object is one of these are trivial subclassings, not logical content.
_TRIVIAL_SUPERCLASSES = {OWL.Thing, RDFS.Resource}

# rdflib parse formats to try, in order, when the extension is ambiguous.
_FORMAT_BY_EXT = {
    ".ttl": "turtle", ".n3": "n3", ".nt": "nt", ".rdf": "xml", ".owl": "xml",
    ".xml": "xml", ".owx": "xml", ".jsonld": "json-ld", ".trig": "trig",
}
_FALLBACK_FORMATS = ["xml", "turtle", "n3", "nt", "json-ld"]


@dataclass
class Counts:
    classes: int = 0
    subClassOf: int = 0          # logical, non-trivial named subclass edges
    objectProperties: int = 0    # declared owl:ObjectProperty
    objectPropertyAxioms: int = 0  # assertions/axioms actually *using* an obj prop
    dataProperties: int = 0
    individuals: int = 0
    axioms: int = 0              # total logical axioms (see _count_axioms)

    def to_dict(self):
        return asdict(self)


def load_graph(path):
    """Parse an artifact into an rdflib.Graph, trying formats by extension then
    falling back. Raises ValueError if nothing parses."""
    import os

    ext = os.path.splitext(str(path))[1].lower()
    tried = []
    ordered = []
    if ext in _FORMAT_BY_EXT:
        ordered.append(_FORMAT_BY_EXT[ext])
    for fmt in _FALLBACK_FORMATS:
        if fmt not in ordered:
            ordered.append(fmt)

    last_err = None
    for fmt in ordered:
        g = rdflib.Graph()
        try:
            g.parse(str(path), format=fmt)
            return g
        except Exception as exc:  # noqa: BLE001 - we genuinely want to try the next format
            tried.append(fmt)
            last_err = exc
    raise ValueError(f"could not parse {path} (tried {tried}): {last_err}")


def _named(term):
    return isinstance(term, URIRef)


def _is_class(g, term):
    return (term, RDF.type, OWL.Class) in g or (term, RDF.type, RDFS.Class) in g


def named_classes(g):
    """Set of IRIs declared as owl:Class / rdfs:Class (named, not blank nodes)."""
    out = set()
    for s, _, o in g.triples((None, RDF.type, None)):
        if o in (OWL.Class, RDFS.Class) and _named(s):
            out.add(str(s))
    return out


def object_properties(g):
    return {str(s) for s, _, o in g.triples((None, RDF.type, OWL.ObjectProperty)) if _named(s)}


def data_properties(g):
    return {str(s) for s, _, o in g.triples((None, RDF.type, OWL.DatatypeProperty)) if _named(s)}


def named_individuals(g):
    out = {str(s) for s, _, o in g.triples((None, RDF.type, OWL.NamedIndividual)) if _named(s)}
    # also any subject typed to a user class counts as an individual
    classes = named_classes(g)
    for s, _, o in g.triples((None, RDF.type, None)):
        if _named(s) and str(o) in classes:
            out.add(str(s))
    return out


# Predicates that, on their own, constitute a logical axiom about classes/props.
_LOGICAL_PREDICATES = {
    RDFS.subClassOf, OWL.equivalentClass, OWL.disjointWith, OWL.complementOf,
    RDFS.subPropertyOf, OWL.equivalentProperty, OWL.inverseOf, OWL.propertyDisjointWith,
    RDFS.domain, RDFS.range, OWL.hasKey, OWL.disjointUnionOf,
}
# Property characteristic types (rdf:type X) that are logical axioms.
_CHARACTERISTIC_TYPES = {
    OWL.FunctionalProperty, OWL.InverseFunctionalProperty, OWL.TransitiveProperty,
    OWL.SymmetricProperty, OWL.AsymmetricProperty, OWL.ReflexiveProperty,
    OWL.IrreflexiveProperty,
}


def _count_axioms(g, obj_props, classes):
    """Count logical axioms. Declarations, labels and annotations are excluded."""
    n = 0

    # Class/property relational axioms (skip trivial subClassOf owl:Thing).
    for s, p, o in g:
        if p == RDFS.subClassOf:
            if o not in _TRIVIAL_SUPERCLASSES:
                n += 1
        elif p in _LOGICAL_PREDICATES:
            n += 1
        elif p == RDF.type and o in _CHARACTERISTIC_TYPES:
            n += 1

    # Class expression axioms attached via blank nodes (restrictions, intersections).
    for s in g.subjects(RDF.type, OWL.Restriction):
        if isinstance(s, BNode):
            n += 1
    for pred in (OWL.intersectionOf, OWL.unionOf, OWL.oneOf):
        n += sum(1 for _ in g.triples((None, pred, None)))

    # Object/data property assertions between individuals: (a P b) with P a property.
    prop_set = set(obj_props) | data_properties(g)
    for s, p, o in g:
        if str(p) in prop_set:
            n += 1

    # Class assertions: (individual rdf:type SomeUserClass).
    for s, _, o in g.triples((None, RDF.type, None)):
        if _named(o) and str(o) in classes and str(o) not in (str(OWL.Class),):
            n += 1

    return n


def object_property_axioms(g, obj_props):
    """Count axioms/assertions that actually use a declared object property.
    A3 requires at least one of these in addition to a bare declaration."""
    if not obj_props:
        return 0
    n = 0
    obj_set = set(obj_props)
    # domain/range/subPropertyOf/inverse/characteristics on the property itself
    for s, p, o in g:
        if str(s) in obj_set and p in (
            RDFS.domain, RDFS.range, RDFS.subPropertyOf, OWL.inverseOf,
            OWL.equivalentProperty, OWL.propertyDisjointWith,
        ):
            n += 1
        elif str(s) in obj_set and p == RDF.type and o in _CHARACTERISTIC_TYPES:
            n += 1
    # restrictions referencing the property
    for s, _, prop in g.triples((None, OWL.onProperty, None)):
        if str(prop) in obj_set:
            n += 1
    # assertions using the property between individuals
    for s, p, o in g:
        if str(p) in obj_set:
            n += 1
    return n


def count(g):
    """Compute the full Counts for a parsed graph."""
    classes = named_classes(g)
    obj_props = object_properties(g)
    dprops = data_properties(g)

    subclass = 0
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        if _named(s) and _named(o) and o not in _TRIVIAL_SUPERCLASSES:
            subclass += 1

    return Counts(
        classes=len(classes),
        subClassOf=subclass,
        objectProperties=len(obj_props),
        objectPropertyAxioms=object_property_axioms(g, obj_props),
        dataProperties=len(dprops),
        individuals=len(named_individuals(g)),
        axioms=_count_axioms(g, obj_props, classes),
    )


def count_path(path):
    return count(load_graph(path))
