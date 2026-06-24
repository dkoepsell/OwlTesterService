"""
BFO 2020 catalog: the single source of truth about what BFO says.

Loads the vendored BFO 2020 core OWL (ISO/IEC 21838-2) and exposes, for both the
tester UI and the conformance lint:

  - an IRI to rdfs:label map (so reports show "quality" not "BFO_0000019"),
  - the asserted subclass graph among BFO classes (plus ancestor/descendant closures),
  - the full set of asserted owl:disjointWith / owl:AllDisjointClasses pairs, and
  - the disjointness closure: every pair that clashes because the two classes are
    disjoint or sit under disjoint ancestors.

The bundle under bfo/ is intentionally pure BFO so the sibling bfo-agent project can
depend on the exact same view of BFO and the two tools never disagree.

Loading is done once per process into a dedicated owlready2 World (never the
default world) so it cannot contaminate the per-request analysis world. The parsed
catalog is cached behind a module-level singleton.
"""

import os
import threading

import owlready2

BFO_IRI_PREFIX = "http://purl.obolibrary.org/obo/BFO_"

# Resolve the vendored OWL relative to this package, not the process CWD, so it
# works under gunicorn regardless of the working directory.
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OWL_PATH = os.path.join(_PACKAGE_DIR, "bfo-2020.owl")
VERSION_PATH = os.path.join(_PACKAGE_DIR, "VERSION")

_CATALOG = None
_LOCK = threading.Lock()


def _read_version():
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


BFO_VERSION = _read_version()


class BfoCatalog:
    """An in-memory, read-only view of BFO 2020.

    All graph keys are full IRIs. Build once via load_catalog(); treat instances
    as immutable.
    """

    def __init__(self, owl_path):
        self.owl_path = owl_path
        self.version = BFO_VERSION

        # iri -> rdfs:label (falls back to a formatted local id)
        self.labels = {}
        # iri -> {id, label, uri, description}, shaped like BFO_2020_CLASSES
        self._ui_dict = {}
        # asserted subclass edges among BFO classes: child_iri -> set(parent_iri)
        self.subclass_graph = {}
        # ancestor/descendant closures (each set includes the node itself)
        self._ancestors = {}
        self._descendants = {}
        # asserted disjoint pairs as frozenset({iri_a, iri_b})
        self.disjoint_pairs = set()
        # memoized disjointness closure
        self._closure = None
        # lookup helpers
        self.iri_by_local = {}
        self.iri_by_label = {}

        self._load(owl_path)

    # -- construction -----------------------------------------------------

    def _load(self, owl_path):
        world = owlready2.World()
        onto = world.get_ontology("file://" + owl_path).load()
        self._world = world
        self._onto = onto

        bfo_classes = [c for c in onto.classes() if self._is_bfo(c.iri)]

        for cls in bfo_classes:
            iri = cls.iri
            local = iri.rsplit("/", 1)[-1]
            label = self._label_of(cls, local)
            self.labels[iri] = label
            self.iri_by_local[local] = iri
            self.iri_by_label[label.lower()] = iri

            key = label.lower().replace(" ", "_")
            description = ""
            if cls.comment and cls.comment.first():
                description = str(cls.comment.first())
            if not description:
                description = "BFO-2020 class: " + label
            self._ui_dict[key] = {
                "id": key,
                "label": label,
                "uri": iri,
                "description": description,
            }

            parents = set()
            for parent in cls.is_a:
                if isinstance(parent, owlready2.ThingClass) and self._is_bfo(parent.iri):
                    parents.add(parent.iri)
            self.subclass_graph[iri] = parents

        self._build_closures(bfo_classes)
        self._load_disjoint_pairs(onto)

    @staticmethod
    def _is_bfo(iri):
        return bool(iri) and iri.startswith(BFO_IRI_PREFIX)

    @staticmethod
    def _label_of(cls, local):
        if cls.label and cls.label.first():
            return str(cls.label.first())
        return local.replace("_", " ").title()

    def _build_closures(self, bfo_classes):
        # ancestors: walk subclass edges upward (transitive, reflexive)
        for cls in bfo_classes:
            seen = set()
            stack = [cls.iri]
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                for parent in self.subclass_graph.get(node, ()):
                    stack.append(parent)
            self._ancestors[cls.iri] = seen

        # descendants: invert the ancestor closure
        for iri in self._ancestors:
            self._descendants[iri] = set()
        for child, ancestors in self._ancestors.items():
            for anc in ancestors:
                self._descendants.setdefault(anc, set()).add(child)

    def _load_disjoint_pairs(self, onto):
        for axiom in onto.disjoint_classes():
            entities = [e for e in axiom.entities if isinstance(e, owlready2.ThingClass)]
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    a, b = entities[i].iri, entities[j].iri
                    if self._is_bfo(a) and self._is_bfo(b):
                        self.disjoint_pairs.add(frozenset((a, b)))

    # -- public lookups ---------------------------------------------------

    def ancestors(self, iri):
        """BFO ancestors of iri, including iri itself. Empty if unknown."""
        return self._ancestors.get(iri, {iri} if iri else set())

    def descendants(self, iri):
        return self._descendants.get(iri, {iri} if iri else set())

    def label_for(self, iri):
        return self.labels.get(iri, iri.rsplit("/", 1)[-1] if iri else "")

    def is_bfo_iri(self, iri):
        return self._is_bfo(iri)

    def clash(self, iri_a, iri_b):
        """True if the two BFO classes are disjoint or under disjoint ancestors."""
        if iri_a == iri_b:
            return False
        return frozenset((iri_a, iri_b)) in self.closure()

    def closure(self):
        """The memoized disjointness closure as a set of frozenset({iri, iri})."""
        if self._closure is None:
            self._closure = disjointness_closure(self)
        return self._closure

    def ui_dict(self):
        return self._ui_dict


# -- module API ----------------------------------------------------------


def load_catalog(owl_path=None):
    """Return the process-wide BfoCatalog singleton.

    Parsing BFO 2020 is cheap but we still do it once. Pass owl_path to load a
    specific file (used by tests); the singleton then reflects that path.
    """
    global _CATALOG
    path = owl_path or os.environ.get("BFO_PATH") or DEFAULT_OWL_PATH
    with _LOCK:
        if _CATALOG is None or (owl_path and _CATALOG.owl_path != path):
            _CATALOG = BfoCatalog(path)
        return _CATALOG


def disjointness_closure(catalog):
    """Expand asserted disjointness over the subclass hierarchy.

    Two classes clash when they are asserted disjoint, or when one descends from
    A and the other from B for some asserted disjoint pair (A, B). This catches,
    for example, quality vs disposition (both descend from classes that BFO
    asserts disjoint: quality vs realizable entity).
    """
    closure = set()
    for pair in catalog.disjoint_pairs:
        a, b = tuple(pair)
        desc_a = catalog.descendants(a)
        desc_b = catalog.descendants(b)
        for da in desc_a:
            for db in desc_b:
                if da != db:
                    closure.add(frozenset((da, db)))
    return closure


def as_ui_dict(catalog):
    """Return the {key: {id, label, uri, description}} shape used by the UI and
    /api/get-bfo-classes, matching the hand-coded BFO_2020_CLASSES layout."""
    return dict(catalog.ui_dict())
