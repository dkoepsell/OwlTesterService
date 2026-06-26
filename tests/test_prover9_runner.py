"""Tests for the Prover9/Mace4 cross-check wrapper (SPEC Task 5).

The prover binaries are not assumed present in CI, so these tests focus on the
graceful-degradation contract and the input shaping. When prover9 IS on PATH the
last test exercises a real proof of the Force straddle.
"""

import shutil

import pytest

from fol_export import build_theory, render_prover9
from prover9_runner import cross_check, check_class_unsat, _goal_block


def test_cross_check_degrades_without_binary(straddle_owl, catalog, monkeypatch):
    monkeypatch.setattr("prover9_runner.prover9_available", lambda: False)
    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    out = cross_check(theory, reasoner_unsat_names=["Force"])
    assert out["ran"] is False
    assert out["available"] is False
    assert "prover9" in out["reason"].lower()
    # Reasoner verdict is still echoed back for the UI.
    assert out["reasoner_unsatisfiable"] == ["Force"]


def test_check_class_unsat_unknown_without_binary(straddle_owl, catalog, monkeypatch):
    monkeypatch.setattr("prover9_runner.prover9_available", lambda: False)
    p9 = render_prover9(build_theory(file_path=straddle_owl, catalog=catalog))
    assert check_class_unsat(p9, "force", "continuant") == "unknown"


def test_goal_block_arity():
    assert "instance_of(X,force,T)" in _goal_block("force", "continuant")
    assert "instance_of_at(X,flight)" in _goal_block("flight", "occurrent")


@pytest.mark.skipif(shutil.which("prover9") is None,
                    reason="prover9 binary not installed")
def test_real_prover_finds_force_unsatisfiable(straddle_owl, catalog):
    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    out = cross_check(theory, reasoner_unsat_names=["Force"])
    assert out["ran"] is True
    assert "Force" in out["prover_unsatisfiable"]
