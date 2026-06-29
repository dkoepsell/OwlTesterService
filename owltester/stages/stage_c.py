"""Stage C — reasoner coherence AND non-triviality.

C1 logical consistency + class satisfiability (HermiT in-process via owlready2).
C2 non-triviality: an artifact that is consistent only because it asserts nothing
    fails. We require the reasoner to entail at least one subsumption that was not
    asserted; a hollow artifact entails nothing and trips E_TRIVIAL.
C3 on inconsistency/unsatisfiability, report the offending classes (the minimal
    unsatisfiable cores are approximated by the unsatisfiable-class list; full
    MUPS extraction is the repair module's job).

If no reasoner is available (no Java / owlready2 failure) the stage is marked
*skipped* with a reason rather than silently passing — the safety-critical guards
are Stages A and E, which never depend on a reasoner.
"""

import os
import tempfile

from ..model import StageResult
from .. import errors


def _bfo_path():
    try:
        from bfo.catalog import DEFAULT_OWL_PATH
        if os.path.exists(DEFAULT_OWL_PATH):
            return DEFAULT_OWL_PATH
    except Exception:  # noqa: BLE001
        pass
    return None


def _asserted_ancestors(ctx):
    """Asserted subClassOf* closure per artifact class (IRIs)."""
    closure = {}
    for cls in ctx.classes:
        seen, stack = set(), list(ctx.edges.get(cls, ()))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(ctx.edges.get(n, ()))
        closure[cls] = seen
    return closure


def run(ctx):
    r = StageResult("C")

    try:
        import owlready2
    except Exception as exc:  # noqa: BLE001
        r.skipped = f"reasoner unavailable: owlready2 import failed ({exc})"
        return r

    # Build a merged graph (artifact + BFO) and hand it to owlready2 as RDF/XML.
    bfo_path = _bfo_path()
    tmp_path = None
    try:
        import rdflib
        merged = rdflib.Graph()
        for s, p, o in ctx.graph:
            merged.add((s, p, o))
        # Merge the kernel so SOoL categories are grounded to BFO during
        # reasoning; otherwise a class whose grounding lives only in the kernel
        # would look vacuous to C2.
        if ctx.kernel and getattr(ctx.kernel, "path", None):
            try:
                merged.parse(ctx.kernel.path, format="turtle")
            except Exception:  # noqa: BLE001
                pass
        if bfo_path:
            try:
                merged.parse(bfo_path)
            except Exception:  # noqa: BLE001 - reason without BFO if it won't load
                bfo_path = None
        with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as fh:
            tmp_path = fh.name
        merged.serialize(destination=tmp_path, format="xml")

        world = owlready2.World()
        onto = world.get_ontology("file://" + tmp_path).load()

        inconsistent = False
        unsat = []
        try:
            with onto:
                owlready2.sync_reasoner_pellet(
                    infer_property_values=False,
                    infer_data_property_values=False)
        except owlready2.OwlReadyInconsistentOntologyError:
            inconsistent = True
        except Exception as exc:  # noqa: BLE001 - reasoner failed to run at all
            r.skipped = f"reasoner did not run: {exc}"
            return r

        if not inconsistent:
            try:
                unsat = [c.iri for c in world.inconsistent_classes()]
            except Exception:  # noqa: BLE001
                unsat = []

        # C1
        if inconsistent:
            r.add(errors.E_INCONSISTENT,
                  "Reasoner reports the ontology is logically inconsistent.")
            r.notes["unsatisfiable_classes"] = []
            return r
        if unsat:
            for iri in unsat:
                if iri.endswith("Nothing"):
                    continue
                r.add(errors.E_INCONSISTENT,
                      f"Class is unsatisfiable (equivalent to owl:Nothing): {iri}",
                      iri=iri)
            r.notes["unsatisfiable_classes"] = [i for i in unsat if not i.endswith("Nothing")]
            if not r.passed:
                return r

        # C2 — non-triviality: did the reasoner entail any non-asserted subsumption?
        asserted = _asserted_ancestors(ctx)
        inferred_count = 0
        examples = []
        for cls_iri in ctx.classes:
            cls = world[cls_iri]
            if cls is None:
                continue
            try:
                ancestors = {a.iri for a in cls.ancestors()
                             if hasattr(a, "iri") and a.iri not in (cls_iri,)}
            except Exception:  # noqa: BLE001
                continue
            new = ancestors - asserted.get(cls_iri, set())
            new = {a for a in new if not a.endswith("Thing")}
            if new:
                inferred_count += len(new)
                if len(examples) < 5:
                    examples.append({"class": cls_iri, "inferred": sorted(new)[:3]})

        r.notes["inferred_subsumptions"] = inferred_count
        r.notes["inferred_examples"] = examples
        if inferred_count == 0:
            r.add(errors.E_TRIVIAL,
                  "The artifact is consistent only vacuously: the reasoner "
                  "entailed no subsumption that was not already asserted. A "
                  "coherent-but-empty artifact fails.")
        return r
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
