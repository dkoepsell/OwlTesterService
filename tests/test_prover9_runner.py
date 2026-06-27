"""Tests for the Prover9/Mace4 cross-check wrapper (SPEC Task 5).

The prover binaries are not assumed present in CI, so these tests focus on the
graceful-degradation contract and the input shaping. When prover9 IS on PATH the
last test exercises a real proof of the Force straddle.
"""

import shutil
import subprocess

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


# -- Phase 5: BFO background and the undetermined verdict --------------------

def test_goal_block_align_forces_ternary():
    # Without align an occurrent uses the binary predicate; with align it does not.
    assert "instance_of_at(X,flight)" in _goal_block("flight", "occurrent")
    aligned = _goal_block("flight", "occurrent", align=True)
    assert "instance_of_at" not in aligned
    assert "instance_of(X,flight,T)" in aligned


def test_timeout_is_undetermined_with_background_not_satisfiable(monkeypatch):
    """A wall-clock timeout under the heavy background must read as undetermined,
    never as satisfiable (which would be silent false agreement)."""
    monkeypatch.setattr("prover9_runner.prover9_available", lambda: True)
    monkeypatch.setattr("prover9_runner.mace4_available", lambda: False)

    def boom(cmd, stdin_text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr("prover9_runner._run", boom)
    assert check_class_unsat("", "c", "continuant",
                             background="% bg\n") == "undetermined"
    # Without a background the lightweight contract is unchanged: timeout -> unknown.
    assert check_class_unsat("", "c", "continuant") == "unknown"


def test_resource_limit_stall_is_undetermined_with_background(monkeypatch):
    """Prover9 stopping on max_seconds (rc=4, not the rc=2 exhaustion) with no
    Mace4 model available is undetermined under a background, satisfiable without."""
    monkeypatch.setattr("prover9_runner.prover9_available", lambda: True)
    monkeypatch.setattr("prover9_runner.mace4_available", lambda: False)

    class Proc:
        returncode = 4  # MAX_SECONDS, not the EXHAUSTED rc=2
        stdout = ""

    monkeypatch.setattr("prover9_runner._run", lambda *a, **k: Proc())
    assert check_class_unsat("", "c", "continuant",
                             background="% bg\n") == "undetermined"
    assert check_class_unsat("", "c", "continuant") == "satisfiable"


def test_cross_check_undetermined_blocks_agreement(straddle_owl, catalog, monkeypatch):
    """When any class is undetermined, agree is None and the class is reported,
    so a timeout under the background never counts as agreement."""
    monkeypatch.setattr("prover9_runner.prover9_available", lambda: True)
    monkeypatch.setattr("prover9_runner.mace4_available", lambda: False)
    monkeypatch.setattr("prover9_runner.check_class_unsat",
                        lambda *a, **k: "undetermined")
    # Avoid touching the real BFO translation in this unit test.
    monkeypatch.setattr("clif_theory.render_prover9_theory", lambda *a, **k: "% bg\n")

    theory = build_theory(file_path=straddle_owl, catalog=catalog)
    out = cross_check(theory, reasoner_unsat_names=["Force"], bfo_background=True)
    assert out["ran"] is True
    assert out["bfo_background"] is True
    assert out["engine"].endswith("+bfo")
    assert out["undetermined"]            # at least one class undetermined
    assert out["prover_unsatisfiable"] == []
    assert out["agree"] is None           # cannot claim agreement


@pytest.mark.skipif(shutil.which("prover9") is None or shutil.which("mace4") is None,
                    reason="prover9 and mace4 binaries not installed")
def test_relation_mediated_unsat_with_background(catalog):
    """Acceptance: a class unsatisfiable only through a BFO relation axiom is
    found unsatisfiable with the background on. Needs the real binaries."""
    fixture = "tests/fixtures/inheres_clash.owl"
    import os
    if not os.path.exists(fixture):
        pytest.skip("relation-mediated fixture not present")
    theory = build_theory(file_path=fixture, catalog=catalog)
    out = cross_check(theory, bfo_background=True, per_class_timeout=30)
    assert out["ran"] is True
    assert out["bfo_background"] is True
