"""OwlTester's reasoner pipeline for the Kindwork module (SPEC-OWLTESTER-KINDWORK-MODULE.md, section 4).

Takes the ontology text that the sidecar's `prepare` returns and produces the
reasoner result object the sidecar's `findings` op consumes:

    {status, consistent, unsatisfiable: [{iri, label, partition, axioms}], axioms, detail}

HermiT decides; Pellet cross-checks. Both run on the vendored BFO 2020 plus the
one-axiom IAO bridge, offline. A run that does not finish is never `ok`.
Justifications are rebuilt from the asserted hierarchy: the shortest label path
from the class up to each side of the BFO disjointness that empties it.
"""

from __future__ import annotations

import concurrent.futures
import functools
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from collections import deque

import owlready2
import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from bfo.catalog import BFO_IRI_PREFIX, DEFAULT_OWL_PATH, load_catalog
from kindwork.bundle import local_name
from kindwork.reasoning import IAO_ICE, prepare

logger = logging.getLogger(__name__)

CONTINUANT = BFO_IRI_PREFIX + "0000002"
OCCURRENT = BFO_IRI_PREFIX + "0000003"
REASONER = {"name": "HermiT", "version": "1.3.8 via owlready2, Pellet cross-check",
            "profile": "OWL 2 DL"}

_SLOTS = threading.BoundedSemaphore(2)


def timeout_seconds() -> float:
    try:
        return max(0.001, int(os.environ.get("KINDWORK_REASONER_TIMEOUT_MS", "60000")) / 1000)
    except ValueError:
        return 60.0


def _result(status, detail="", consistent=None, unsatisfiable=None, axioms=None):
    return {"status": status, "consistent": consistent, "unsatisfiable": unsatisfiable or [],
            "axioms": axioms or [], "detail": detail}


@functools.lru_cache(maxsize=1)
def _bfo_edges():
    g = rdflib.Graph().parse(os.environ.get("BFO_PATH") or DEFAULT_OWL_PATH)
    edges = {}
    for s, o in g.subject_objects(RDFS.subClassOf):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            edges.setdefault(str(s), set()).add(str(o))
    edges.setdefault(str(IAO_ICE), set()).add(BFO_IRI_PREFIX + "0000031")
    return edges


class _Labels:
    def __init__(self, graph, catalog):
        self.graph, self.catalog = graph, catalog

    def __call__(self, iri):
        if iri == str(IAO_ICE):
            return "information content entity"
        if iri.startswith(BFO_IRI_PREFIX):
            return self.catalog.label_for(iri)
        best = None
        for lit in self.graph.objects(URIRef(iri), RDFS.label):
            if getattr(lit, "language", None) in (None, "en"):
                return str(lit)
            best = best or str(lit)
        return best or local_name(iri)


def _shortest_paths(edges, start):
    """BFS up the hierarchy: {ancestor: [(child, parent), ...]} shortest edge path."""
    prev, q = {start: None}, deque([start])
    while q:
        node = q.popleft()
        for p in sorted(edges.get(node, ())):
            if p not in prev:
                prev[p] = node
                q.append(p)
    paths = {}
    for node in prev:
        path, cur = [], node
        while prev[cur] is not None:
            path.append((prev[cur], cur))
            cur = prev[cur]
        paths[node] = path[::-1]
    return paths


def justify(graph, cls, catalog=None):
    """(axioms, partition) for an unsatisfiable class, or ([], None) when no
    asserted BFO disjointness explains it."""
    catalog = catalog or load_catalog()
    edges = {k: set(v) for k, v in _bfo_edges().items()}
    for s, o in graph.subject_objects(RDFS.subClassOf):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            edges.setdefault(str(s), set()).add(str(o))
    paths = _shortest_paths(edges, cls)
    best = None
    for a, b in catalog.disjoint_pairs:
        if a in paths and b in paths:
            partition = {a, b} == {CONTINUANT, OCCURRENT}
            cost = (len(paths[a]) + len(paths[b]), not partition, a, b)
            if best is None or cost < best[0]:
                best = (cost, a, b, partition)
    if best is None:
        return [], None
    _, a, b, partition = best
    label = _Labels(graph, catalog)
    axioms = []
    for child, parent in paths[a] + paths[b]:
        line = f"{label(child)} SubClassOf {label(parent)}"
        if line not in axioms:
            axioms.append(line)
    first, second = (a, b) if (a, b) != (OCCURRENT, CONTINUANT) else (b, a)
    axioms.append(f"{label(first)} DisjointWith {label(second)}")
    return axioms, partition


def _kill_java():
    try:
        from owl_tester import OwlTester
        OwlTester._kill_stray_java_children()
    except Exception as e:  # noqa: BLE001
        logger.warning("could not kill stray reasoner: %s", e)


def _run(which, owl_path, budget, with_bfo=True):
    """('ok', set(unsat IRIs)) | ('inconsistent', None) | ('timeout'|'error', detail)."""
    world = owlready2.World()
    try:
        onto = world.get_ontology("file://" + owl_path).load()
        if with_bfo:
            bfo = world.get_ontology("file://" + os.path.abspath(
                os.environ.get("BFO_PATH") or DEFAULT_OWL_PATH)).load()
            onto.imported_ontologies.append(bfo)
    except Exception as e:  # noqa: BLE001
        return "error", f"The ontology could not be loaded for reasoning ({type(e).__name__})."
    sync = owlready2.sync_reasoner_hermit if which == "hermit" else owlready2.sync_reasoner_pellet

    def go():
        with onto:
            sync(world, infer_property_values=False, debug=0)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        executor.submit(go).result(timeout=budget)
    except concurrent.futures.TimeoutError:
        _kill_java()
        return "timeout", f"The reasoner did not finish within {budget:g} seconds."
    except owlready2.OwlReadyInconsistentOntologyError:
        return "inconsistent", None
    except Exception as e:  # noqa: BLE001
        logger.warning("kindwork %s run failed: %s", which, e)
        return "error", "The reasoner stopped with an error before reaching a verdict."
    finally:
        executor.shutdown(wait=False)
    return "ok", {c.iri for c in world.inconsistent_classes()
                  if c is not owlready2.Nothing and getattr(c, "iri", None)}


def consistency(owl_path, budget, with_bfo=True, cross_check=True, pellet_path=None):
    """HermiT verdict on an RDF file, with a Pellet cross-check.

    Returns {status: ok|inconsistent|timeout|error, unsatisfiable: set, detail,
    disagreement}. ``ok`` means consistent. Used by the full artifact audit,
    which reasons over artifacts that need not import BFO. ``pellet_path`` is an
    optional variant of the input for Pellet, for constructs Pellet 2.3 lacks."""
    if not _SLOTS.acquire(timeout=budget):
        return {"status": "timeout", "unsatisfiable": set(), "disagreement": "",
                "detail": "The reasoner is busy with other checks."}
    try:
        h_status, h = _run("hermit", owl_path, budget, with_bfo)
        out = {"status": h_status, "unsatisfiable": h if h_status == "ok" else set(),
               "detail": h if isinstance(h, str) else "", "disagreement": ""}
        if not cross_check or h_status in ("timeout", "error"):
            return out
        p_status, p = _run("pellet", pellet_path or owl_path, budget, with_bfo)
    finally:
        _SLOTS.release()
    if p_status in ("ok", "inconsistent") and p_status != h_status:
        out["disagreement"] = (f"HermiT says the input is {'consistent' if h_status == 'ok' else 'inconsistent'}"
                               f", Pellet says it is {'consistent' if p_status == 'ok' else 'inconsistent'}.")
    elif p_status == "ok" and h_status == "ok" and p != h:
        out["disagreement"] = ("HermiT and Pellet disagree on which classes are unsatisfiable: "
                               + ", ".join(sorted(h ^ p)[:10]))
        out["unsatisfiable"] = h & p
    return out


def _robot_cmd():
    jar = os.environ.get("ROBOT_JAR")
    if jar and os.path.exists(jar):
        return ["java", "-jar", jar]
    return [shutil.which("robot")] if shutil.which("robot") else None


def explain_inconsistency(owl_path, budget):
    """One minimal inconsistency explanation as plain axioms, via ROBOT when present."""
    cmd = _robot_cmd()
    if not cmd:
        return []
    out = owl_path + ".md"
    bfo = os.path.abspath(os.environ.get("BFO_PATH") or DEFAULT_OWL_PATH)
    try:
        subprocess.run(cmd + ["merge", "--input", owl_path, "--input", bfo, "explain",
                              "--reasoner", "HermiT", "--mode", "inconsistency",
                              "--explanation", out],
                       capture_output=True, timeout=budget, check=False)
        with open(out, encoding="utf-8") as f:
            lines = [ln.strip()[2:] for ln in f if ln.strip().startswith("- ")]
    except (OSError, subprocess.TimeoutExpired):
        return []
    import re
    delink = re.compile(r"\[([^\]]*)\]\([^)]*\)")
    return [delink.sub(r"\1", ln).strip() for ln in lines if ln][:20]


def _parse(text, ext):
    g = rdflib.Graph()
    fmt = "xml" if ext in ("owl", "rdf", "xml") or text.lstrip().startswith("<") else "turtle"
    g.parse(data=text, format=fmt)
    return g


def reason_text(text: str, ext: str = "ttl") -> dict:
    """The section 4 reasoner result for ontology text from the sidecar's prepare."""
    try:
        source = _parse(text, ext)
    except Exception:  # noqa: BLE001
        return _result("error", "The ontology could not be read, so it was not checked.")
    graph, unresolved = prepare(source)
    budget = timeout_seconds()
    if not _SLOTS.acquire(timeout=budget):
        return _result("timeout", "The reasoner is busy with other checks. Try again shortly.")
    try:
        with tempfile.TemporaryDirectory(prefix="kindwork-") as tmp:
            owl_path = os.path.join(tmp, "input.owl")
            graph.serialize(destination=owl_path, format="xml")
            h_status, h = _run("hermit", owl_path, budget)
            if h_status in ("timeout", "error"):
                return _result(h_status, h)
            p_status, p = _run("pellet", owl_path, budget)
            if h_status == "inconsistent":
                if p_status == "ok":
                    return _result("error", "HermiT and Pellet disagree on whether the "
                                            "ontology is consistent.")
                return _result("ok", consistent=False,
                               axioms=explain_inconsistency(owl_path, budget))
            if p_status == "inconsistent":
                return _result("error", "HermiT and Pellet disagree on whether the "
                                        "ontology is consistent.")
    finally:
        _SLOTS.release()

    unsat = h
    details = []
    if p_status == "ok" and p != h:
        disputed = sorted(h ^ p)
        unsat = h & p
        label = _Labels(graph, load_catalog())
        details.append(f"HermiT and Pellet disagree on {', '.join(label(i) for i in disputed)}.")
    if unresolved:
        n = len(unresolved)
        details.append(f"{n} imported ontolog{'y was' if n == 1 else 'ies were'} not loaded, "
                       f"so anything {'it adds' if n == 1 else 'they add'} is not checked.")

    catalog = load_catalog()
    label = _Labels(graph, catalog)
    out = []
    for iri in sorted(unsat):
        axioms, partition = justify(graph, iri, catalog)
        out.append({"iri": iri, "label": label(iri), "partition": partition, "axioms": axioms})
    return _result("ok", " ".join(details), consistent=True, unsatisfiable=out)
