"""The owltester-findings document (KINDWORK-ECOSYSTEM-SPEC.md, section 4).

Titles and explanations are read by the person who answered the Kindwork
interview, so they must be plain words. Logic notation belongs in `axioms`;
make_finding refuses it anywhere else.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

CHECKS = {"consistency", "coherence", "entailment", "conformance", "chain"}
SEVERITIES = {"partition", "within", "chain", "info"}
VERDICTS = {"fail", "undetermined", "pass"}

_NOTATION = re.compile(
    r"[⊑⊒⊓⊔∃∀¬⊥⊤≡→←↔∧∨⊆⊂∈]"
    r"|\b(SubClassOf|EquivalentClass(es)?|DisjointWith|DisjointClasses|ObjectSomeValuesFrom)\b"
    r"|\b(owl|rdfs|rdf|obo|kwv|sh):\w"
    r"|\b(BFO|IAO|RO)_\d{7}\b"
)


class NotationError(ValueError):
    """Logic notation found in text meant for the interviewee."""


def has_notation(text: str) -> bool:
    return bool(_NOTATION.search(text or ""))


def make_finding(fid, check, severity, verdict, classes, title, explanation, axioms):
    if check not in CHECKS or severity not in SEVERITIES or verdict not in VERDICTS:
        raise ValueError(f"bad finding enum: {check}/{severity}/{verdict}")
    for field_name, text in (("title", title), ("explanation", explanation)):
        if has_notation(text):
            raise NotationError(f"{fid}: logic notation in {field_name}: {text!r}")
    return {
        "id": fid,
        "check": check,
        "severity": severity,
        "verdict": verdict,
        "classes": list(classes),
        "title": title,
        "explanation": explanation,
        "axioms": list(axioms),
    }


def findings_document(ontology_iri, reasoner, consistent, coherent, findings):
    return {
        "format": "owltester-findings",
        "version": "0.1",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ontology": ontology_iri,
        "reasoner": reasoner,
        "verdict": {"consistent": consistent, "coherent": coherent},
        "findings": findings,
    }
