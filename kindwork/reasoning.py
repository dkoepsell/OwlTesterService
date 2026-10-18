"""Run Pellet over a Kindwork ontology with BFO resolved locally.

The bundle's owl:imports of BFO are replaced by the vendored bfo/bfo-2020.owl.
Other imports are not fetched; they are reported so the caller can mark positive
verdicts as undetermined. Kindwork uses a handful of IAO and RO terms that the
BFO file does not declare, so they are declared here, and IAO's information
content entity is placed under generically dependent continuant as IAO does.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import tempfile
from dataclasses import dataclass, field

import owlready2
import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from bfo.catalog import BFO_IRI_PREFIX, DEFAULT_OWL_PATH

logger = logging.getLogger(__name__)

OBO = "http://purl.obolibrary.org/obo/"
IAO_ICE = URIRef(OBO + "IAO_0000030")
BFO_GDC = URIRef(OBO + "BFO_0000031")
XSD = "http://www.w3.org/2001/XMLSchema#"

REASONER = {"name": "Pellet", "version": "2.3.1", "profile": "OWL 2 DL"}


@dataclass
class ReasonResult:
    status: str  # ok | inconsistent | timeout | error
    unsatisfiable: list = field(default_factory=list)
    unresolved_imports: list = field(default_factory=list)
    detail: str = ""

    @property
    def finished(self):
        return self.status in ("ok", "inconsistent")


def is_bfo_import(iri: str) -> bool:
    return iri.startswith(OBO + "bfo") or iri.startswith(BFO_IRI_PREFIX)


def bridge_iao(graph: rdflib.Graph) -> rdflib.Graph:
    """A copy of graph with IAO information content entity placed under GDC."""
    g = rdflib.Graph()
    g += graph
    if any(graph.triples((None, None, IAO_ICE))) or any(graph.triples((IAO_ICE, None, None))):
        g.add((IAO_ICE, RDF.type, OWL.Class))
        g.add((IAO_ICE, RDFS.subClassOf, BFO_GDC))
    return g


def prepare(graph: rdflib.Graph):
    """Graph ready for owlready2, plus the imports it could not resolve."""
    g = bridge_iao(graph)
    unresolved = []
    for s, o in list(g.subject_objects(OWL.imports)):
        g.remove((s, OWL.imports, o))
        if not is_bfo_import(str(o)):
            unresolved.append(str(o))
    for restriction, prop in list(g.subject_objects(OWL.onProperty)):
        if not isinstance(prop, URIRef) or str(prop).startswith(BFO_IRI_PREFIX):
            continue
        if (prop, RDF.type, None) in g:
            continue
        filler = g.value(restriction, OWL.someValuesFrom) or g.value(restriction, OWL.allValuesFrom)
        datatype = isinstance(filler, URIRef) and str(filler).startswith(XSD)
        g.add((prop, RDF.type, OWL.DatatypeProperty if datatype else OWL.ObjectProperty))
    return g, unresolved


def _kill_java():
    try:
        from owl_tester import OwlTester
        OwlTester._kill_stray_java_children()
    except Exception as e:  # noqa: BLE001
        logger.warning("could not kill stray reasoner: %s", e)


def reason(graph: rdflib.Graph, budget_seconds: float = 60) -> ReasonResult:
    g, unresolved = prepare(graph)
    world = owlready2.World()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "kindwork.owl")
        g.serialize(destination=path, format="xml")
        try:
            onto = world.get_ontology("file://" + path).load()
            bfo = world.get_ontology("file://" + os.path.abspath(
                os.environ.get("BFO_PATH") or DEFAULT_OWL_PATH)).load()
            onto.imported_ontologies.append(bfo)
        except Exception as e:  # noqa: BLE001
            return ReasonResult("error", unresolved_imports=unresolved, detail=f"load failed: {e}")

        def run():
            with onto:
                owlready2.sync_reasoner_pellet(world, infer_property_values=False, debug=0)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            executor.submit(run).result(timeout=budget_seconds)
        except concurrent.futures.TimeoutError:
            _kill_java()
            return ReasonResult("timeout", unresolved_imports=unresolved,
                                detail=f"reasoner exceeded {budget_seconds}s")
        except owlready2.OwlReadyInconsistentOntologyError as e:
            return ReasonResult("inconsistent", unresolved_imports=unresolved, detail=str(e))
        except Exception as e:  # noqa: BLE001
            return ReasonResult("error", unresolved_imports=unresolved, detail=str(e))
        finally:
            executor.shutdown(wait=False)

        unsat = sorted({c.iri for c in world.inconsistent_classes()
                        if c is not owlready2.Nothing and getattr(c, "iri", None)})
        return ReasonResult("ok", unsatisfiable=unsat, unresolved_imports=unresolved)
