"""Imports and BFO (SPEC-release.md, section 9.2).

Each ``owl:imports`` must be resolved by a supplied file (matched by ontology
IRI, version IRI or file name) or, for BFO, by the vendored BFO 2020: whole, or
a module extracted with ``robot extract --method BOT`` for the terms used (the
LOF pattern). Anything else unresolved stops the build until it is supplied or
removed. Writes ``imports/`` and ``catalog-v001.xml``.
"""

import os
import shutil
from xml.sax.saxutils import quoteattr

from rdflib import OWL, URIRef

from . import metadata

BFO_PREFIX = "http://purl.obolibrary.org/obo/BFO_"
BFO_IRIS = ("http://purl.obolibrary.org/obo/bfo.owl", "http://purl.obolibrary.org/obo/bfo/2020/bfo.owl",
            "http://purl.obolibrary.org/obo/bfo/2020/bfo-core.owl", "http://purl.obolibrary.org/obo/bfo/2.0/bfo.owl")
VENDORED_BFO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "bfo", "bfo-2020.owl")


class ImportError_(ValueError):
    """Unresolvable imports (named so as not to shadow the builtin)."""

    def __init__(self, unresolved):
        super().__init__("unresolved owl:imports: " + ", ".join(unresolved) +
                         ". Supply each file (--import), or remove the import.")
        self.unresolved = unresolved


def bfo_terms(g):
    return sorted({str(t) for t in g.all_nodes() if isinstance(t, URIRef) and str(t).startswith(BFO_PREFIX)})


def _identity(path):
    """(ontology IRI, version IRI, file name) of a supplied import."""
    try:
        g = metadata.read(path)
    except metadata.InputError:
        return None, None, os.path.basename(path)
    h = metadata.ontology_node(g)
    vi = g.value(h, OWL.versionIRI) if h is not None else None
    return (str(h) if h is not None else None), (str(vi) if vi else None), os.path.basename(path)


def detect(g):
    h = metadata.header(g)
    ext = {}
    own = metadata.own_terms(g, h.get("ontology_iri"))
    for t in g.all_nodes():
        if isinstance(t, URIRef) and str(t) not in own and str(t).startswith("http"):
            ns = metadata.namespace_of(str(t))
            if not ns.startswith(("http://www.w3.org/",)):
                ext[ns] = ext.get(ns, 0) + 1
    return {"imports": h.get("imports", []), "external_namespaces": dict(sorted(ext.items())),
            "bfo_terms": len(bfo_terms(g))}


def resolve(g, supplied, a, out_dir, budget, log):
    """Write ``imports/`` and the catalog under ``out_dir`` (src/ontology). Returns
    {"imports": [iri], "files": {iri: rel}, "bfo": mode} for the edit file's header."""
    from . import robot
    os.makedirs(os.path.join(out_dir, "imports"), exist_ok=True)
    known = {}
    for path in supplied:
        oi, vi, name = _identity(path)
        for key in (oi, vi, name):
            if key:
                known[key] = path
    wanted = metadata.header(g).get("imports", [])
    mapping, unresolved, keep = {}, [], []
    for iri in wanted:
        is_bfo = iri in BFO_IRIS or "/bfo" in iri.lower() and iri.startswith("http://purl.obolibrary.org/")
        path = known.get(iri) or known.get(iri.rsplit("/", 1)[-1])
        if path is not None:
            rel = "imports/" + os.path.basename(path)
            shutil.copyfile(path, os.path.join(out_dir, rel))
            mapping[iri] = rel
            keep.append(iri)
        elif is_bfo and a["bfo"] != "none":
            continue                     # replaced by the BFO import below
        else:
            unresolved.append(iri)
    if unresolved:
        raise ImportError_(unresolved)
    bfo_mode = a["bfo"]
    has_bfo_import = any("bfo" in os.path.basename(p).lower() for p in mapping.values())
    if bfo_mode != "none" and not has_bfo_import:
        if bfo_mode == "full":
            iri = f"{a['base']}/imports/bfo.owl"
            shutil.copyfile(VENDORED_BFO, os.path.join(out_dir, "imports", "bfo.owl"))
            mapping[iri] = "imports/bfo.owl"
        else:
            terms = bfo_terms(g)
            if not terms:
                raise ValueError("bfo is 'module' but the ontology uses no BFO terms; choose 'none' or 'full'")
            term_file = os.path.join(out_dir, "imports", "bfo_terms.txt")
            with open(term_file, "w", encoding="utf-8") as fh:
                fh.write("\n".join(terms) + "\n")
            iri = f"{a['base']}/imports/bfo_import.owl"
            robot.extract_bot(VENDORED_BFO, term_file, os.path.join(out_dir, "imports", "bfo_import.owl"),
                              iri, budget, log)
            os.remove(term_file)
            mapping[iri] = "imports/bfo_import.owl"
        keep.append(iri)
    write_catalog(os.path.join(out_dir, "catalog-v001.xml"), mapping)
    return {"imports": keep, "files": mapping, "bfo": bfo_mode}


def write_catalog(path, mapping):
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
             '<catalog prefer="public" xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">']
    lines += [f"  <uri name={quoteattr(iri)} uri={quoteattr(rel)}/>" for iri, rel in sorted(mapping.items())]
    lines.append("</catalog>")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
