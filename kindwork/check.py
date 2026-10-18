"""Run every Kindwork check on a bundle and assemble the findings document."""

from __future__ import annotations

from bfo.catalog import load_catalog
from kindwork.chain import chain_findings
from kindwork.conformance import conformance_findings
from kindwork.findings import findings_document
from kindwork.mapping import (coherence_findings, consistency_findings,
                              entailment_findings)
from kindwork.reasoning import REASONER, reason

PREFIX = {"consistency": "con", "coherence": "coh", "entailment": "ent",
          "chain": "chn", "conformance": "cnf"}


def check_bundle(bundle, reasoner_budget: float = 60):
    catalog = load_catalog()
    reasoned = reason(bundle.ontology, reasoner_budget)

    coherence = coherence_findings(bundle, reasoned, catalog)
    flagged = {c for f in coherence for c in f["classes"]}
    findings = (consistency_findings(bundle, reasoned) + coherence
                + entailment_findings(bundle, flagged)
                + chain_findings(bundle) + conformance_findings(bundle))

    counts = {}
    for f in findings:
        p = PREFIX[f["check"]]
        counts[p] = counts.get(p, 0) + 1
        f["id"] = f"{p}-{counts[p]:03d}"

    # Never claim a positive verdict the reasoner did not reach. A lint straddle is
    # certain without the reasoner, so it can still settle coherence as false.
    certain = reasoned.finished and not reasoned.unresolved_imports
    if reasoned.status == "inconsistent":
        consistent, coherent = False, False
    elif reasoned.status == "ok":
        consistent = True if certain else None
        coherent = False if coherence else (True if certain else None)
    else:
        consistent = None
        coherent = False if coherence else None

    ontology = bundle.ontology_iri or (bundle.manifest or {}).get("namespace")
    return findings_document(ontology, dict(REASONER), consistent, coherent, findings)
