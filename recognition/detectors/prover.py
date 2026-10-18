"""Witnessing unintended models with a finite model finder.

K-A3 is defined as a divergence between the models a theory *admits* and the
models it was *intended* to have. The structural detector finds the syntactic
shapes that usually produce such a divergence -- a polythetic family, a set of
siblings never made disjoint -- but a shape is a suspicion, not a demonstration.

Mace4 turns the suspicion into evidence. Given the sibling categories under a
parent, ask for a finite model in which one individual falls under two of them
at once. If Mace4 returns one, the artifact demonstrably admits the overlap:
that model *is* the unintended model, and CT-1's "formal signature of
artifactual comorbidity" stops being a diagnosis by pattern-matching.

This is a promotion step, not a new source of findings. It upgrades evidence on
structural findings that already exist, and it never introduces a primitive the
structural pass did not already attempt -- so it cannot change which strata are
reported assessed.
"""

import logging

from ..finding import DetectorResult

logger = logging.getLogger(__name__)

INSTRUMENT = "structural"   # a witness for a structural finding, not a new class

DEFAULT_TIMEOUT = 3
MAX_PROBES = 10


def _symbol(iri, index):
    """A Prover9-safe predicate name for a class IRI.

    Prover9 wants lowercase alphanumerics; IRIs are neither, and two IRIs can
    share a local name. Index-suffixing keeps the mapping injective.
    """
    local = iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in local).strip("_")
    return f"c{index}_{cleaned.lower() or 'x'}"


def overlap_theory(symbols):
    """Assumptions asserting one individual falls under both categories."""
    left, right = symbols
    return ("set(prolog_style_variables).\n\n"
            "formulas(assumptions).\n"
            f"  exists X ({left}(X) & {right}(X)).\n"
            "end_of_list.\n")


def witness_overlaps(findings, timeout=DEFAULT_TIMEOUT, max_probes=MAX_PROBES):
    """Attach a model witness to latent-overlap findings where one exists.

    Mutates and returns ``findings``. Silently does nothing when Mace4 is
    unavailable -- the structural finding stands on its own, it simply keeps
    the weaker "candidate" evidence it already had.
    """
    try:
        from prover9_runner import find_model, prover9_available
    except Exception as exc:  # noqa: BLE001
        logger.debug("prover unavailable, no overlap witnesses: %s", exc)
        return findings
    if not prover9_available():
        return findings

    probed = 0
    for f in findings:
        if probed >= max_probes:
            break
        siblings = f.evidence.get("siblings") if f.evidence.get("latent") else None
        if not siblings or len(siblings) < 2:
            continue

        pair = siblings[:2]
        symbols = [_symbol(iri, i) for i, iri in enumerate(pair)]
        probed += 1
        try:
            model = find_model(overlap_theory(symbols), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - a probe must never break a report
            logger.debug("overlap probe failed for %s: %s", f.iri, exc)
            continue

        if model.get("found"):
            f.evidence["unintended_model"] = {
                "witnessed": True,
                "pair": pair,
                "note": ("A finite model exists in which one individual falls "
                         "under both categories. The overlap is admitted by "
                         "the theory, not merely unprohibited by its syntax."),
            }
        elif model.get("found") is False:
            f.evidence["unintended_model"] = {
                "witnessed": False,
                "pair": pair,
                "note": "No model of the overlap was found.",
            }

    if probed:
        logger.debug("probed %d latent overlaps for unintended models", probed)
    return findings


def run(findings, timeout=DEFAULT_TIMEOUT):
    """Promote evidence on existing findings. Attempts no new primitive."""
    result = DetectorResult(findings=witness_overlaps(findings, timeout))
    return result
