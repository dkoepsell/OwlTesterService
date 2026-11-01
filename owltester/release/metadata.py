"""Identity and metadata (SPEC-release.md, section 9.1).

Reads what the input already declares, so the builder asks only for what is
missing or wrong, and checks the ontology IRI against the IRIs of the
ontology's own terms (a mismatch is the LOMO namespace problem waiting to
happen).
"""

import collections
import os

from rdflib import OWL, RDF, RDFS, Literal, Namespace, URIRef

DCT = Namespace("http://purl.org/dc/terms/")
DC = Namespace("http://purl.org/dc/elements/1.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
IAO_DEF = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
KINDS = {"class": OWL.Class, "object property": OWL.ObjectProperty,
         "data property": OWL.DatatypeProperty, "annotation property": OWL.AnnotationProperty,
         "individual": OWL.NamedIndividual}
# Namespaces that are never the ontology's own.
FOREIGN = ("http://www.w3.org/", "http://purl.org/dc/", "http://xmlns.com/foaf/",
           "http://purl.obolibrary.org/obo/BFO_", "http://purl.obolibrary.org/obo/RO_",
           "http://purl.obolibrary.org/obo/IAO_", "http://schema.org/", "https://schema.org/",
           "http://purl.org/pav/", "http://www.geneontology.org/")
# Header predicates the builder manages; others in the input header are kept.
MANAGED = (DCT.title, DCT.description, DCT.license, DCT.creator, DCT.contributor,
           OWL.versionInfo, OWL.versionIRI, OWL.priorVersion, RDFS.label)


class InputError(ValueError):
    pass


def read(path):
    """The input as an rdflib Graph (any format the audit reads; OFN and OWX via ROBOT)."""
    from ..audit.files import _parse
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    graph, error = _parse(os.path.abspath(path), ext)
    if graph is None or error:
        raise InputError(f"{os.path.basename(path)} could not be read: {error or 'not RDF'}")
    if len(graph) == 0:
        raise InputError(f"{os.path.basename(path)} has no statements")
    return graph


def ontology_node(g):
    return next((s for s in g.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)), None)


def _first(g, s, preds):
    for p in preds:
        for o in g.objects(s, p):
            return str(o)
    return None


def header(g):
    """What the file already declares, as defaults for the answers."""
    h = ontology_node(g)
    if h is None:
        return {"ontology_iri": None, "imports": []}
    people = lambda preds: [{"name": str(o)} if isinstance(o, Literal) else {"name": str(o).rsplit("/", 1)[-1],
                                                                              "orcid": str(o) if "orcid.org" in str(o) else None}
                            for p in preds for o in g.objects(h, p)]
    return {"ontology_iri": str(h),
            "title": _first(g, h, (DCT.title, DC.title, RDFS.label)),
            "description": _first(g, h, (DCT.description, DC.description, RDFS.comment)),
            "version": _first(g, h, (OWL.versionInfo,)),
            "version_iri": _first(g, h, (OWL.versionIRI,)),
            "license": _first(g, h, (DCT.license, DC.rights)),
            "creators": people((DCT.creator, DC.creator)),
            "contributors": people((DCT.contributor, DC.contributor)),
            "imports": sorted(str(o) for o in g.objects(h, OWL.imports))}


def own_terms(g, ontology_iri=None):
    """Declared terms that are not from a well-known foreign vocabulary."""
    out = {}
    for kind, cls in KINDS.items():
        for s in g.subjects(RDF.type, cls):
            if isinstance(s, URIRef) and not str(s).startswith(FOREIGN) and str(s) != ontology_iri:
                out.setdefault(str(s), kind)
    return out


def namespace_of(iri):
    """The namespace of a term IRI: up to the last # or /, or an OBO-style ``PREFIX_`` before digits."""
    import re
    m = re.match(r"^(.*[/#])([A-Za-z][A-Za-z0-9]*_)\d+$", iri)
    if m:
        return m.group(1) + m.group(2)
    cut = max(iri.rfind("#"), iri.rfind("/"))
    return iri[:cut + 1] if cut > iri.find("://") + 2 else iri


def check_namespace(g, ontology_iri, base):
    """Do the ontology's own terms live under its base? (section 9.1, the LOMO problem)."""
    terms = own_terms(g, ontology_iri)
    spaces = collections.Counter(namespace_of(t) for t in terms)
    stem = (base or "").rsplit("/", 1)[0] + "/" if base else ""
    outside = {ns: n for ns, n in spaces.items() if stem and not ns.startswith(stem)}
    return {"terms": len(terms), "namespaces": dict(spaces.most_common()),
            "outside_base": outside, "ok": not outside}


def labels(g):
    """IRI -> English (or untagged) label."""
    out = {}
    for s, o in g.subject_objects(RDFS.label):
        if isinstance(o, Literal) and (o.language in (None, "", "en") or str(s) not in out):
            if str(s) not in out or o.language in (None, "", "en"):
                out[str(s)] = str(o)
    return out


def definition(g, s):
    return _first(g, URIRef(s), (SKOS.definition, IAO_DEF, RDFS.comment))


def apply_header(g, a, import_iris):
    """Write the answers into the ontology header (managed predicates replaced, the rest kept)."""
    from .answers import LICENSES
    old = ontology_node(g)
    new = URIRef(a["ontology_iri"])
    if old is not None and old != new:
        for p, o in list(g.predicate_objects(old)):
            g.remove((old, p, o))
            g.add((new, p, o))
        g.remove((old, RDF.type, OWL.Ontology))
    g.add((new, RDF.type, OWL.Ontology))
    for p in MANAGED + (OWL.imports,):
        g.remove((new, p, None))
    g.add((new, DCT.title, Literal(a["title"], lang="en")))
    g.add((new, DCT.description, Literal(a["description"], lang="en")))
    g.add((new, DCT.license, URIRef(LICENSES[a["license"]][1])))
    for field, pred in (("creators", DCT.creator), ("contributors", DCT.contributor)):
        for person in a[field]:
            g.add((new, pred, Literal(person["name"])))
    if a.get("prior_version"):
        g.add((new, OWL.priorVersion, URIRef(a["prior_version"])))
    for iri in import_iris:
        g.add((new, OWL.imports, URIRef(iri)))
    return g
