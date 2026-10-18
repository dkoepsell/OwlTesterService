"""Parse an OWL/RDFS ontology (any rdflib-supported format) into a UModel."""
from __future__ import annotations

from rdflib import Graph, RDF, RDFS, OWL, URIRef, BNode
from rdflib.namespace import XSD

from .bfo_labels import BFO_LABELS
from .model import Attr, Edge, UModel


def _local(term) -> str:
    """Human-friendly local name from a URI/BNode."""
    if isinstance(term, BNode):
        return ""
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            tail = s.rsplit(sep, 1)[-1]
            if tail:
                return tail
    return s


# Language tags we treat as "preferred" when an entity carries rdfs:labels in
# several languages (untagged literals are assumed English / canonical).
_PREFERRED_LANGS = ("", "en", "en-us", "en-gb")


def _build_labels(g: Graph) -> dict[URIRef, str]:
    """Map each URI to its best rdfs:label.

    Ontologies like ECO/GO/OBO name classes with opaque numeric IDs
    (``ECO_0000001``) and put the readable name in ``rdfs:label``. Showing the
    label instead of the bare ID is what makes the diagram legible. When an
    entity has labels in multiple languages we prefer an English/untagged one.
    """
    chosen: dict[URIRef, tuple[bool, str]] = {}
    for s, o in g.subject_objects(RDFS.label):
        if not isinstance(s, URIRef):
            continue
        text = " ".join(str(o).split()).strip()
        if not text:
            continue
        lang = (getattr(o, "language", None) or "").lower()
        preferred = lang in _PREFERRED_LANGS
        prev = chosen.get(s)
        # Keep the first label seen, but let a preferred-language label win.
        if prev is None or (preferred and not prev[0]):
            chosen[s] = (preferred, text)
    return {uri: text for uri, (_pref, text) in chosen.items()}


def _display(term, labels: dict[URIRef, str]) -> str:
    """Readable name for a term: its rdfs:label if known, else the local name."""
    if isinstance(term, URIRef):
        lbl = labels.get(term)
        if lbl:
            return lbl
    name = _local(term)
    # Fall back to BFO's own published label for imported upper-level classes
    # that arrive without an rdfs:label (e.g. "BFO_0000001" -> "entity").
    return BFO_LABELS.get(name, name)


# Formats to try, in order, when auto-detection is requested or the
# extension-guessed format fails (e.g. a `.owl` file that is actually Turtle).
_FALLBACK_FORMATS = ("xml", "turtle", "n3", "nt", "json-ld", "trig")


def _parse_graph(path: str, fmt: str | None) -> Graph:
    """Parse into a Graph, trying fallback formats when fmt is unspecified.

    rdflib guesses the serialization from the file extension, which fails for
    mislabeled files (a Turtle ontology saved as `.owl`, etc.). When no explicit
    format is given we let rdflib guess first, then fall back through the common
    serializations so a wrong extension doesn't block rendering.
    """
    if fmt:
        g = Graph()
        g.parse(path, format=fmt)
        return g

    errors: list[str] = []
    # 1. Let rdflib guess from the extension.
    try:
        g = Graph()
        g.parse(path)
        return g
    except Exception as exc:  # noqa: BLE001
        errors.append(f"auto: {exc}")

    # 2. Try each known serialization explicitly.
    for candidate in _FALLBACK_FORMATS:
        try:
            g = Graph()
            g.parse(path, format=candidate)
            return g
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate}: {exc}")

    raise ValueError(
        "could not parse ontology in any known format. "
        "If this is OWL/XML (.owx), Manchester (.omn) or Functional (.ofn) "
        "syntax, rdflib cannot read it — re-export as RDF/XML or Turtle. "
        "Tried:\n  " + "\n  ".join(errors)
    )


def parse_ontology(path: str, fmt: str | None = None) -> UModel:
    g = _parse_graph(path, fmt)

    m = UModel()
    labels = _build_labels(g)

    # --- 1. Named classes -------------------------------------------------
    class_uris: set[URIRef] = set()
    for ctype in (OWL.Class, RDFS.Class):
        for s in g.subjects(RDF.type, ctype):
            if isinstance(s, URIRef):
                class_uris.add(s)

    def register_class(uri: URIRef) -> str:
        cid = str(uri)
        m.cls(cid, _display(uri, labels))
        return cid

    for uri in class_uris:
        register_class(uri)

    # --- 2. Subclass (generalization) edges -------------------------------
    for sub, sup in g.subject_objects(RDFS.subClassOf):
        if isinstance(sub, URIRef) and isinstance(sup, URIRef):
            register_class(sub)
            register_class(sup)
            m.edges.append(Edge(src=str(sub), dst=str(sup), kind="generalization"))

    # --- 3. Properties ----------------------------------------------------
    prop_uris: set[URIRef] = set()
    for ptype in (OWL.ObjectProperty, OWL.DatatypeProperty,
                  RDF.Property, OWL.FunctionalProperty):
        for s in g.subjects(RDF.type, ptype):
            if isinstance(s, URIRef):
                prop_uris.add(s)

    for p in prop_uris:
        name = _display(p, labels)
        domains = [d for d in g.objects(p, RDFS.domain) if isinstance(d, URIRef)]
        ranges = [r for r in g.objects(p, RDFS.range) if isinstance(r, URIRef)]
        is_object = (p, RDF.type, OWL.ObjectProperty) in g
        is_data = (p, RDF.type, OWL.DatatypeProperty) in g

        # Classify: datatype -> attribute; object/class-range -> association.
        def is_class_range(r: URIRef) -> bool:
            return r in class_uris or (str(r).startswith(str(OWL)) is False
                                       and not str(r).startswith(str(XSD))
                                       and not is_data)

        if not domains:
            # Orphan property: skip (cannot attach to a class box).
            continue

        for d in domains:
            dcid = str(d)
            m.cls(dcid, _display(d, labels))
            if not ranges:
                # Unknown range -> show as attribute with no type.
                if not is_object:
                    m.classes[dcid].attrs.append(Attr(name=name))
                continue
            for r in ranges:
                if is_data or str(r).startswith(str(XSD)):
                    m.classes[dcid].attrs.append(Attr(name=name, type=_local(r)))
                elif is_object or r in class_uris:
                    rcid = str(r)
                    m.cls(rcid, _display(r, labels))
                    m.edges.append(
                        Edge(src=dcid, dst=rcid, kind="association", label=name)
                    )
                else:
                    m.classes[dcid].attrs.append(Attr(name=name, type=_local(r)))

    # Deduplicate attributes per class (stable order).
    for c in m.classes.values():
        seen: set[tuple[str, str]] = set()
        unique: list[Attr] = []
        for a in c.attrs:
            key = (a.name, a.type)
            if key not in seen:
                seen.add(key)
                unique.append(a)
        c.attrs = unique

    return m
