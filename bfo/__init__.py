"""
bfo: the shared BFO 2020 bundle.

A self-contained, reusable view of BFO 2020 (vendored OWL, disjointness closure,
relation signatures) with a stable internal API. This tester and the sibling
bfo-agent project both consume this bundle so the two tools never disagree about
what BFO says.

Public API:
    load_catalog()          -> BfoCatalog (process-wide singleton)
    disjointness_closure(c) -> set of frozenset({iri, iri})
    as_ui_dict(c)           -> {key: {id, label, uri, description}}
    relation_signatures()   -> {} (placeholder, see relations.py)
    BFO_VERSION             -> pinned release string
"""

from bfo.catalog import (
    BFO_VERSION,
    BfoCatalog,
    as_ui_dict,
    disjointness_closure,
    load_catalog,
)
from bfo.relations import relation_signatures

# Convenience alias matching the documented bundle surface.
bfo_catalog = load_catalog

__all__ = [
    "BFO_VERSION",
    "BfoCatalog",
    "as_ui_dict",
    "bfo_catalog",
    "disjointness_closure",
    "load_catalog",
    "relation_signatures",
]
