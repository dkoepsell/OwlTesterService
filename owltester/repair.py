"""Conservative, logged repair — the replacement for the destructive "autofix".

Repair is opt-in and minimal:

1. Check the artifact. If it already passes coherence (Stage C), return it
   unchanged.
2. If it is incoherent because of BFO partition straddles, relax *only* the
   offending subClassOf edges, choosing the edge to drop per the kernel-grounding
   heuristic (the same minimal relaxation the existing fixer used), and log every
   removal to quarantine with its justification.
3. The number of removed axioms is bounded (default 2% of input). Exceeding the
   bound fails with E_OVER_RELAXED rather than hollowing the ontology out.
4. Re-run the full pipeline with the input as baseline. Repair "succeeds" only if
   the result passes A-E and the removal log fully accounts for every delta — so
   a deletion-style repair can never pass (it trips Stage E).

Anything the gate cannot minimally relax is left in place and reported, never
bulk-deleted; quarantine is the default disposition for the untranslatable.
"""

import rdflib
from rdflib import RDFS, URIRef

from . import errors
from .counts import count, load_graph
from .pipeline import check, _load_catalog
from .kernel import load_kernel


def _local(iri):
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def repair(path, kernel_path=None, max_removed=0.02, catalog=None):
    """Return (repaired_serialization_or_None, result_dict).

    result_dict = {
        "status": "unchanged" | "repaired" | "failed",
        "quarantine": [ {axiom, justification, core} ... ],
        "report": <gate report dict on the repaired artifact>,
        "error": <code or None>,
    }
    """
    if catalog is None:
        catalog = _load_catalog()
    kernel = load_kernel(kernel_path)

    baseline = count(load_graph(path))

    # 1. Already coherent? Run the gate; if Stage C passes, no repair.
    pre = check(path, kernel_path=kernel_path, all_stages=False, catalog=catalog)
    c_stage = pre.stages.get("C", {})
    coherent = c_stage.get("skipped") or (
        c_stage.get("pass") and "E_INCONSISTENT" not in c_stage.get("failures", []))
    if coherent and "E_DISJOINT" not in pre.stages.get("B", {}).get("failures", []):
        return None, {"status": "unchanged", "quarantine": [],
                      "report": pre.to_dict(), "error": None}

    # 2. Relax BFO partition straddles, minimally and with logging.
    try:
        from bfo_lint import bfo_lint
        from ontology_fixer import choose_drop_iri
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "failed", "quarantine": [],
                      "report": pre.to_dict(),
                      "error": f"repair backend unavailable: {exc}"}

    g = load_graph(path)
    findings = bfo_lint(g, catalog) if catalog is not None else []

    bound = max(1, int(baseline.axioms * max_removed))
    quarantine = []
    removed = 0

    for f in findings:
        if removed >= bound:
            break
        drop_iri = choose_drop_iri(f.category_a_iri, f.category_b_iri, catalog)
        if not drop_iri:
            continue
        triple = (URIRef(f.cls_iri), RDFS.subClassOf, URIRef(drop_iri))
        if triple in g:
            g.remove(triple)
            removed += 1
            quarantine.append({
                "axiom": f"SubClassOf({_local(f.cls_iri)} {_local(drop_iri)})",
                "axiom_iri": [f.cls_iri, str(RDFS.subClassOf), drop_iri],
                "justification": f.message,
                "core": [f.category_a_iri, f.category_b_iri],
                "kind": "subclass_edge",
            })

    if removed == 0:
        return None, {"status": "failed", "quarantine": [],
                      "report": pre.to_dict(),
                      "error": "no minimally-relaxable straddle edge found; "
                               "nothing removed (no silent deletion)"}

    # Over-relaxation guard.
    if removed >= bound and len(findings) > removed:
        return None, {"status": "failed", "quarantine": quarantine,
                      "report": pre.to_dict(), "error": errors.E_OVER_RELAXED}

    serialized = g.serialize(format="xml", encoding="utf-8")

    # 4. Re-run the full pipeline on the repaired artifact, with the input as
    #    baseline so Stage E audits the delta against the removal log.
    import tempfile
    import os
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as fh:
            tmp = fh.name
            fh.write(serialized if isinstance(serialized, bytes) else serialized.encode())
        post = check(tmp, kernel_path=kernel_path, all_stages=True,
                     baseline_counts=baseline, removals=quarantine, catalog=catalog)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)

    ok = post.verdict == "pass"
    return (serialized if ok else None), {
        "status": "repaired" if ok else "failed",
        "quarantine": quarantine,
        "report": post.to_dict(),
        "error": None if ok else "; ".join(post.all_failures),
    }
