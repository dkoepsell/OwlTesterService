"""Tests for the Coverage Coherence Checker demo (SPEC-coverage-coherence-demo.md §8).

The live-prover tests skip when the binaries are missing; the cache-fallback and
page tests run everywhere, because the demo must work with the engines absent.
"""
import json
import shutil

import pytest

import coverage_demo
from coverage_demo import (build_assumptions, check_with_fallback, load_fixture,
                           list_fixtures, run_check)

requires_provers = pytest.mark.skipif(
    shutil.which("prover9") is None or shutil.which("mace4") is None,
    reason="prover9/mace4 binaries not on PATH")


# -- fixtures ------------------------------------------------------------------

def test_centerpiece_fixtures_load():
    ids = {f["id"] for f in list_fixtures()}
    assert {"cyber-sound", "cyber-illusory-carveback"} <= ids


def test_fixture_id_rejects_traversal():
    assert load_fixture("../models") is None
    assert load_fixture("no-such-fixture") is None


def test_baseline_scores_byte_identical():
    """SPEC §8.1 — the 'same score' beat requires identical baseline blocks."""
    a = load_fixture("cyber-sound")["baseline_score"]
    b = load_fixture("cyber-illusory-carveback")["baseline_score"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_assumptions_block_is_labeled():
    fix = load_fixture("cyber-illusory-carveback")
    block = build_assumptions(fix)
    for ax in fix["axioms"]:
        assert f"# label({ax['label']})" in block


# -- the live prover round-trip (SPEC §8.2/§8.3) --------------------------------

@requires_provers
def test_sound_fixture_is_coherent_live():
    verdict = run_check(load_fixture("cyber-sound"))
    assert verdict["coherent"] is True
    assert verdict["computed_live"] is True
    assert verdict["scenario"]  # the Mace4 witness sentence renders
    assert verdict["checked_positions"][0]["contradicting_clauses"] == []


@requires_provers
def test_illusory_fixture_core_is_proof_derived():
    """The highlighted clause set comes from the Prover9 proof, exactly E1/C1/D1."""
    verdict = run_check(load_fixture("cyber-illusory-carveback"))
    assert verdict["coherent"] is False
    assert verdict["computed_live"] is True
    core = verdict["checked_positions"][0]["contradicting_clauses"]
    assert set(core) == {"E1", "C1", "D1"}
    assert verdict["debug"]["used_labels"] == ["ax_c1", "ax_d1", "ax_e1"]


# -- cache fallback (SPEC §8.6 — works with engines absent) ----------------------

def test_cache_fallback_when_provers_absent(monkeypatch):
    monkeypatch.setattr(coverage_demo, "prover9_available", lambda: False)
    for fid, coherent in (("cyber-sound", True), ("cyber-illusory-carveback", False)):
        verdict = check_with_fallback(load_fixture(fid))
        assert verdict is not None, f"{fid}: no cache served"
        assert verdict["coherent"] is coherent
        assert verdict["computed_live"] is False


def test_cached_core_matches_live_shape():
    """The checked-in cache was itself prover-produced; its core must be the same."""
    fix = load_fixture("cyber-illusory-carveback")
    cache = coverage_demo._load_cache(fix)
    assert set(cache["checked_positions"][0]["contradicting_clauses"]) == {"E1", "C1", "D1"}


# -- routes ----------------------------------------------------------------------

@pytest.fixture()
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_coverage_page_smoke(client):
    resp = client.get("/coverage")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Coverage Coherence Checker" in html
    assert "Endorsement 7" in html
    # SPEC §8.4 — no mechanism on the page without ?debug=1.
    for forbidden in ("prover9", "Prover9", "mace4", "Mace4", "CLIF", "axiom",
                      "restored_by_c1"):
        assert forbidden not in html, f"mechanism leaked: {forbidden}"


def test_check_endpoint_strips_debug(client):
    resp = client.post("/api/coverage/check/cyber-illusory-carveback")
    assert resp.status_code == 200
    verdict = resp.get_json()
    assert verdict["coherent"] is False
    assert "debug" not in verdict


def test_check_endpoint_404_on_unknown(client):
    assert client.post("/api/coverage/check/nope").status_code == 404


def test_fixtures_endpoint(client):
    data = client.get("/api/coverage/fixtures").get_json()
    ids = {f["id"] for f in data["fixtures"]}
    assert {"cyber-sound", "cyber-illusory-carveback"} <= ids
