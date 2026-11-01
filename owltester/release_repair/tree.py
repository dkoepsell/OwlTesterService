"""The working copy of a release (``Tree``) and how graphs are read and written back."""

import os

import rdflib
from rdflib import BNode
from rdflib.compare import isomorphic, to_canonical_graph

WRITE_FORMATS = {"ttl": "turtle", "n3": "n3", "nt": "nt", "jsonld": "json-ld"}


class OpError(Exception):
    """A guard failed; nothing from this apply may be published."""


def n3(t):
    if isinstance(t, BNode):
        return "_:" + str(t)
    return t.n3()


# -- the working copy --------------------------------------------------------------------

class Tree:
    """A release's files on disk, with RDF graphs parsed on demand."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self._graphs = {}

    def path(self, rel):
        rel = str(rel or "").replace("\\", "/").lstrip("/")
        if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
            raise OpError(f"not a path inside the release: {rel!r}")
        ab = os.path.realpath(os.path.join(self.root, *rel.split("/")))
        if not ab.startswith(self.root + os.sep):
            raise OpError(f"outside the release: {rel!r}")
        return ab

    def exists(self, rel):
        return os.path.isfile(self.path(rel))

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def write(self, rel, text):
        ab = self.path(rel)
        os.makedirs(os.path.dirname(ab), exist_ok=True)
        with open(ab, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        self.forget(rel)

    def remove(self, rel):
        os.remove(self.path(rel))
        self.forget(rel)

    def graph(self, rel):
        """The file's graph. A file with blank nodes gets canonical labels, and the
        same object is kept (and mutated) across ops until the file is rewritten
        as text, so blank-node references stay valid within one apply."""
        if rel not in self._graphs:
            fmt = read_format(self.path(rel))
            if fmt is None:
                raise OpError(f"{rel} is not in an RDF syntax repair can rewrite "
                              "(OWL Functional, Manchester and OWL/XML are read-only here)")
            g = rdflib.Graph()
            try:
                g.parse(self.path(rel), format=fmt)
            except Exception as e:  # noqa: BLE001 - rdflib raises many parser types
                raise OpError(f"{rel} could not be parsed: {str(e)[:200]}")
            if any(isinstance(x, BNode) for t in g for x in t):
                g = canonical_graph(g)
            self._graphs[rel] = g
        return self._graphs[rel]

    def save(self, rel, g):
        """Write ``g`` over ``rel`` in the file's own syntax and keep ``g`` cached.

        Turtle files are spliced statement by statement so that unchanged
        statements keep their text; the splice is kept only if it parses to
        exactly ``g``. Anything else is serialised in full."""
        ab = self.path(rel)
        if read_format(ab) == "turtle" and os.path.isfile(ab):
            from .turtle_splice import splice
            current = self.read(rel)
            text = splice(current, g)
            if text is not None:
                self.write(rel, text)
                try:
                    check = rdflib.Graph().parse(data=text, format="turtle")
                    if _same(canonical_graph(check), canonical_graph(g)):
                        self._graphs[rel] = g
                        return
                except Exception:  # noqa: BLE001 - fall back to a full rewrite
                    pass
                self.write(rel, current)
        self.write(rel, serialize(g, ab))
        self._graphs[rel] = g

    def forget(self, rel):
        self._graphs.pop(rel, None)

    def files(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames.sort()
            for fn in sorted(filenames):
                ab = os.path.join(dirpath, fn)
                if not os.path.islink(ab):
                    out.append(os.path.relpath(ab, self.root).replace(os.sep, "/"))
        return out


def _ext(path):
    base = os.path.basename(path)
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def read_format(abspath):
    """rdflib format for reading and writing this file, or None if repair cannot write it."""
    ext = _ext(abspath)
    if ext in WRITE_FORMATS:
        return WRITE_FORMATS[ext]
    if ext in ("owl", "rdf", "xml"):
        with open(abspath, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
        start = head.lstrip()
        if start.startswith(("Prefix(", "Ontology(", "Prefix:", "Ontology:")):
            return None
        if "rdf:RDF" in head or "22-rdf-syntax-ns" in head:
            return "xml"
        if "<Ontology" in head:
            return None
        return "turtle" if ext == "owl" else None
    return None


def canonical_graph(g):
    out = rdflib.Graph()
    for prefix, ns in g.namespaces():
        out.bind(prefix, ns, override=True, replace=True)
    for t in to_canonical_graph(g):
        out.add(t)
    return out


# -- writing a graph back ----------------------------------------------------------------

def _ordered(g):
    """A copy whose insertion order is sorted, so serialisation is deterministic."""
    out = rdflib.Graph()
    for prefix, ns in sorted(g.namespaces(), key=lambda x: (str(x[0]), str(x[1]))):
        out.bind(prefix, ns, override=True, replace=True)
    for t in sorted(g, key=lambda t: tuple(n3(x) for x in t)):
        out.add(t)
    return out


def serialize(g, abspath):
    fmt = read_format(abspath)
    if fmt is None:
        raise OpError(f"{os.path.basename(abspath)} cannot be rewritten by repair")
    if any(isinstance(x, BNode) for t in g for x in t):
        g = canonical_graph(g)
    text = _ordered(g).serialize(format=fmt)
    return text if text.endswith("\n") else text + "\n"


def save_graph(tree, rel, g):
    """Write ``g`` over ``rel`` in the file's own syntax."""
    tree.save(rel, g)


def _same(a, b):
    if len(a) != len(b):
        return False
    if any(isinstance(x, BNode) for t in a for x in t):
        return isomorphic(a, b)
    return set(a) == set(b)


