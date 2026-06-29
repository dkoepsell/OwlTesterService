"""Regression suite for the owltesterservice gate (spec section 7).

The headline guarantee: the SOOL_autofixed.owl outcome (axioms in, zero axioms
out) is a hard failure, never a pass. If golden_bad ever passes, the gate is
broken.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "fixtures")
GOOD = os.path.join(FIX, "golden_good.ttl")
BAD = os.path.join(FIX, "golden_bad.owl")

sys.path.insert(0, ROOT)

from owltester import check, repair, baseline_for, errors  # noqa: E402


# 1. Golden-bad fixture -------------------------------------------------------

def test_golden_bad_fails_with_expected_codes():
    report = check(BAD, all_stages=True)
    assert report.verdict == "fail"
    codes = set(report.all_failures)
    for expected in (errors.E_NO_AXIOMS, errors.E_FLAT, errors.E_NO_BFO,
                     errors.E_BLOATED, errors.E_ANTIPATTERN):
        assert expected in codes, f"{expected} missing from {codes}"


def test_golden_bad_cli_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "owltester.cli", "check", BAD],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode != 0


# 2. Golden-good fixture ------------------------------------------------------

def test_golden_good_passes_all_stages():
    report = check(GOOD, all_stages=True)
    assert report.verdict == "pass", report.all_failures
    for letter in ("A", "B", "C", "D"):
        st = report.stages[letter]
        assert st.get("skipped") or st.get("pass"), f"stage {letter}: {st}"


# 3. Trivialization guard (E3) ------------------------------------------------

def test_trivialization_tripwire():
    # A valid baseline (golden_good has axioms) and a deletion-style "repair"
    # output (golden_bad has 0 axioms) must trip E_TRIVIALIZED at Stage E.
    base = baseline_for(GOOD)
    assert base.axioms > 0
    report = check(BAD, all_stages=True, baseline_counts=base, removals=[])
    assert errors.E_TRIVIALIZED in report.stages["E"]["failures"]


# 4. Non-vacuity guard (C2) ---------------------------------------------------

def test_non_vacuity_guard(tmp_path):
    # An artifact stripped to consistent-but-empty (only declarations) must trip
    # E_TRIVIAL at C2 when stages are forced to run.
    import rdflib
    from rdflib import RDF, OWL, URIRef
    g = rdflib.Graph()
    for i in range(3):
        g.add((URIRef(f"http://ex/Empty{i}"), RDF.type, OWL.Class))
    p = tmp_path / "empty.owl"
    g.serialize(destination=str(p), format="xml")
    report = check(str(p), all_stages=True)
    c = report.stages["C"]
    if c.get("skipped"):
        pytest.skip("reasoner unavailable: " + c["skipped"])
    assert errors.E_TRIVIAL in c["failures"]


# 5. Delta accounting (E1) ----------------------------------------------------

def test_delta_accounting_requires_logged_removals():
    # Output has fewer axioms than baseline but nothing logged -> Stage E fails.
    base = baseline_for(GOOD)
    inflated = type(base)(**{**base.to_dict(), "axioms": base.axioms + 5})
    report = check(GOOD, all_stages=True, baseline_counts=inflated, removals=[])
    fails = report.stages["E"]["failures"]
    assert errors.E_OVER_RELAXED in fails or errors.E_TRIVIALIZED in fails


# 6. Repair is conservative and gated ----------------------------------------

def test_repair_on_coherent_artifact_is_noop():
    serialized, result = repair(GOOD)
    assert result["status"] == "unchanged"
    assert serialized is None
    assert result["quarantine"] == []


def test_repair_never_trivializes(tmp_path):
    # Even a maximally-aggressive repair request must not hollow out an artifact:
    # the Stage E gate rejects any result whose delta the log does not cover.
    serialized, result = repair(GOOD, max_removed=1.0)
    assert result["status"] in ("unchanged", "repaired")
    if result["status"] == "repaired":
        assert result["report"]["counts"]["axioms"] > 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
