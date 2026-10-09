"""Authoritative rdfs:label for Basic Formal Ontology (BFO) classes.

Ontologies routinely import BFO and reference its upper-level classes by their
opaque numeric IRIs (``.../BFO_0000001``). When such an ontology is loaded
without following ``owl:imports`` (rdflib does not by default), those classes
arrive with no ``rdfs:label`` and would otherwise render as the bare ID.

These names are BFO's *own* published labels — extracted verbatim from the
official BFO 2020 release (``http://purl.obolibrary.org/obo/bfo.owl``), not
invented here. They are used only as a fallback: an ``rdfs:label`` present in
the loaded ontology always wins.
"""
from __future__ import annotations

# Keyed by the IRI local name (works for the OBO PURL and any prefix reusing
# the same ``BFO_0000000`` fragment).
BFO_LABELS: dict[str, str] = {
    "BFO_0000001": "entity",
    "BFO_0000002": "continuant",
    "BFO_0000003": "occurrent",
    "BFO_0000004": "independent continuant",
    "BFO_0000006": "spatial region",
    "BFO_0000008": "temporal region",
    "BFO_0000009": "two-dimensional spatial region",
    "BFO_0000011": "spatiotemporal region",
    "BFO_0000015": "process",
    "BFO_0000016": "disposition",
    "BFO_0000017": "realizable entity",
    "BFO_0000018": "zero-dimensional spatial region",
    "BFO_0000019": "quality",
    "BFO_0000020": "specifically dependent continuant",
    "BFO_0000023": "role",
    "BFO_0000024": "fiat object part",
    "BFO_0000026": "one-dimensional spatial region",
    "BFO_0000027": "object aggregate",
    "BFO_0000028": "three-dimensional spatial region",
    "BFO_0000029": "site",
    "BFO_0000030": "object",
    "BFO_0000031": "generically dependent continuant",
    "BFO_0000034": "function",
    "BFO_0000035": "process boundary",
    "BFO_0000038": "one-dimensional temporal region",
    "BFO_0000040": "material entity",
    "BFO_0000140": "continuant fiat boundary",
    "BFO_0000141": "immaterial entity",
    "BFO_0000142": "one-dimensional continuant fiat boundary",
    "BFO_0000144": "process profile",
    "BFO_0000145": "relational quality",
    "BFO_0000146": "two-dimensional continuant fiat boundary",
    "BFO_0000147": "zero-dimensional continuant fiat boundary",
    "BFO_0000148": "zero-dimensional temporal region",
    "BFO_0000182": "history",
}
