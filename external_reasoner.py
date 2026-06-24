"""
External-reasoner wrapper. Runs ROBOT (with ELK as the backend) in a subprocess
to reason over an OWL file, then diffs the reasoned ontology against the input
to extract newly entailed axioms. Used for ontologies too large for in-process
owlready2/Pellet (which can hang on class enumeration).
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time

import rdflib
from rdflib.namespace import OWL, RDFS

logger = logging.getLogger(__name__)

# ROBOT/ELK logs one line per unsatisfiable class when reasoning aborts, e.g.
#   ERROR ... ReasonerHelper -     unsatisfiable: http://example.org/x#Force
_UNSAT_RE = re.compile(r"unsatisfiable:\s*(\S+)", re.IGNORECASE)


def robot_available():
    """True if the ROBOT CLI is on PATH."""
    return shutil.which("robot") is not None


def extract_unsatisfiable(text):
    """Parse ROBOT/ELK reasoner output for unsatisfiable class IRIs.

    ROBOT logs one "unsatisfiable: <IRI>" line per class when reasoning aborts on
    an incoherent (but consistent) ontology. Returns [{name, label, iri}], de-duped,
    excluding owl:Thing / owl:Nothing.
    """
    out = []
    seen = set()
    for iri in _UNSAT_RE.findall(text or ""):
        iri = iri.strip().strip(".,")
        local = _local_name(iri)
        if not iri or local in ("Nothing", "Thing") or iri in seen:
            continue
        seen.add(iri)
        out.append({"name": local, "label": local, "iri": iri})
    return out


def _local_name(uri):
    s = str(uri)
    if "#" in s:
        return s.rsplit("#", 1)[1]
    if "/" in s:
        tail = s.rsplit("/", 1)[1]
        if tail:
            return tail
    return s


def run_robot_reason(input_path, timeout_seconds=300, reasoner="ELK",
                     normalized_graph=None, bfo_path=None):
    """
    Run ROBOT to reason over `input_path` and return entailed axioms.

    If `normalized_graph` (an rdflib.Graph) is provided, it is serialized to a
    fresh RDF/XML file and used as ROBOT's input instead of `input_path`. This
    bypasses OWL-API's quirky parser on certain RDF/XML dialects (e.g. files
    with mixed default namespaces) which can otherwise be rejected as
    "INVALID ONTOLOGY FILE ERROR" even though they parse fine in rdflib.

    Returns a dict:
        {
          'ran':              bool,        # the reasoner actually executed
          'consistent':       Optional[bool],
          'inferred_axioms':  list[dict],  # new SubClassOf / EquivalentClass triples
          'derivation_steps': list[dict],
          'engine':           'robot+<reasoner>',
          'elapsed_seconds':  float,
          'error':            Optional[str],
        }

    Failure modes (ROBOT missing, timeout, non-zero exit) return ran=False with
    `error` populated — callers should treat that as "skipped" rather than
    crashing the request.
    """
    started = time.perf_counter()
    result = {
        "ran": False,
        "consistent": None,
        "inferred_axioms": [],
        "derivation_steps": [],
        "unsatisfiable_classes": [],
        "engine": f"robot+{reasoner}",
        "elapsed_seconds": 0.0,
        "error": None,
    }

    if not robot_available():
        result["error"] = "robot binary not found on PATH"
        return result

    out_path = None
    normalized_path = None
    try:
        # Optionally pre-normalize the input via rdflib so OWL-API doesn't
        # misclassify the format. The graph the caller hands us is the same
        # one we used for structural extraction, so no extra parse cost.
        robot_input_path = input_path
        if normalized_graph is not None:
            # Use Turtle, not RDF/XML — rdflib's default RDF/XML uses
            # <rdf:Description> + rdf:type triples instead of <owl:Class>/etc.,
            # which OWL-API rejects as "INVALID ONTOLOGY FILE". Turtle is
            # parsed cleanly by ROBOT.
            with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as tmp_in:
                normalized_path = tmp_in.name
            t_norm = time.perf_counter()
            normalized_graph.serialize(destination=normalized_path, format="turtle")
            logger.info(f"[STAGE] robot: normalized input (turtle) in "
                        f"{time.perf_counter()-t_norm:.2f}s -> {normalized_path}")
            robot_input_path = normalized_path

        with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as tmp:
            out_path = tmp.name

        # Merge BFO in (when provided) so ELK sees BFO's disjointness and can
        # detect partition-straddle unsatisfiability, matching the in-process
        # path. ROBOT chains merge -> reason in a single invocation.
        cmd = ["robot", "merge", "--input", robot_input_path]
        if bfo_path and os.path.exists(bfo_path):
            cmd += ["--input", bfo_path]
        cmd += [
            "reason",
            "--reasoner", reasoner,
            "--output", out_path,
            "--axiom-generators", "SubClass EquivalentClass",
            "--include-indirect", "false",
        ]
        logger.info(f"[STAGE] robot: invoking {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        result["elapsed_seconds"] = time.perf_counter() - started

        if proc.returncode != 0:
            # ROBOT logs unsatisfiable classes and the inconsistency verdict to
            # stdout (its logger), not stderr, so inspect both.
            combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
            low = combined.lower()

            # Unsatisfiable classes: the ontology is consistent (a model exists)
            # but incoherent. ROBOT reason aborts with exit 1 and lists them, so
            # no reasoned output is produced (hence no inferred-axiom diff here).
            unsat_iris = extract_unsatisfiable(combined)
            if unsat_iris:
                result["ran"] = True
                result["consistent"] = True
                result["unsatisfiable_classes"] = unsat_iris
                logger.info(f"[STAGE] robot: {len(unsat_iris)} unsatisfiable classes")
                return result

            # ROBOT writes "Ontology is inconsistent" when that's the verdict
            if "inconsistent" in low:
                result["ran"] = True
                result["consistent"] = False
                result["error"] = combined.strip()[:2000]
                return result
            result["error"] = (
                f"robot exited {proc.returncode}: {combined.strip()[:1500]}"
            )
            return result

        # Successful reasoning. Diff the output against the actual ROBOT input
        # (either original or normalized copy) to find new axioms.
        if normalized_graph is not None:
            original = normalized_graph
        else:
            original = rdflib.Graph()
            original.parse(input_path)
        reasoned = rdflib.Graph()
        reasoned.parse(out_path)

        new_triples = reasoned - original
        # BFO was merged into the reasoner input, so subtract its asserted axioms
        # to keep them out of the "newly inferred" set for the user's ontology.
        if bfo_path and os.path.exists(bfo_path):
            bfo_graph = rdflib.Graph()
            try:
                bfo_graph.parse(bfo_path)
                new_triples = new_triples - bfo_graph
            except Exception as e:
                logger.warning(f"[STAGE] robot: could not subtract BFO baseline: {e}")
        for s, _, o in new_triples.triples((None, RDFS.subClassOf, None)):
            if not (isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef)):
                continue
            sn, on = _local_name(s), _local_name(o)
            if not sn or not on or sn in ("Thing", "Nothing"):
                continue
            step = {
                "axiom_type": "SubClassOf",
                "description": f"{sn} ⊑ {on}",
                "reason": "Entailed by external reasoner",
                "supporting_facts": [f"{reasoner} classification over class hierarchy"],
                "confidence": "High",
                "origin": f"ROBOT/{reasoner}",
            }
            result["derivation_steps"].append(step)
            result["inferred_axioms"].append({
                "type": "SubClassOf",
                "description": f"{sn} ⊑ {on}",
                "derivation": step,
            })

        for s, _, o in new_triples.triples((None, OWL.equivalentClass, None)):
            if not (isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef)):
                continue
            sn, on = _local_name(s), _local_name(o)
            if not sn or not on:
                continue
            step = {
                "axiom_type": "EquivalentClass",
                "description": f"{sn} ≡ {on}",
                "reason": "Entailed by external reasoner",
                "supporting_facts": [f"{reasoner} classification"],
                "confidence": "High",
                "origin": f"ROBOT/{reasoner}",
            }
            result["derivation_steps"].append(step)
            result["inferred_axioms"].append({
                "type": "EquivalentClass",
                "description": f"{sn} ≡ {on}",
                "derivation": step,
            })

        result["ran"] = True
        result["consistent"] = True
        logger.info(
            f"[STAGE] robot: {result['elapsed_seconds']:.2f}s "
            f"({len(result['inferred_axioms'])} new axioms)"
        )
        return result

    except subprocess.TimeoutExpired:
        result["elapsed_seconds"] = time.perf_counter() - started
        result["error"] = f"robot exceeded {timeout_seconds}s timeout"
        logger.warning(f"[STAGE] robot: TIMED OUT after {timeout_seconds}s")
        return result
    except Exception as e:
        result["elapsed_seconds"] = time.perf_counter() - started
        result["error"] = f"{type(e).__name__}: {e}"
        logger.warning(f"[STAGE] robot: ERROR {e}")
        return result
    finally:
        for p in (out_path, normalized_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
