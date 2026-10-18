"""Phase 1 of the coherence generalization (SPEC-coverage-coherence-demo.md §11):
labeled FOL export + proof cores in the prover cross-check.

The label side-table and the labeled rendering must stay in lockstep — that
alignment is what makes a proof's used labels trustworthy as a justification.
"""
import re
import shutil

import pytest

from fol_export import axiom_table, build_theory, render_prover9
from prover9_runner import cross_check

requires_provers = pytest.mark.skipif(
    shutil.which("prover9") is None or shutil.which("mace4") is None,
    reason="prover9/mace4 binaries not on PATH")

STRADDLE = "tests/fixtures/quality_disposition_straddle.owl"


@pytest.fixture(scope="module")
def straddle_theory():
    return build_theory(file_path=STRADDLE)


def test_labels_off_by_default(straddle_theory):
    """The user-facing download export must be unchanged."""
    assert "# label(" not in render_prover9(straddle_theory)


def test_labeled_render_matches_axiom_table(straddle_theory):
    """Every emitted label resolves in the side-table and vice versa."""
    rendered = render_prover9(straddle_theory, labels=True)
    emitted = set(re.findall(r"# label\((\w+)\)", rendered))
    table = axiom_table(straddle_theory)
    assert emitted == set(table.keys())
    assert emitted  # the fixture has axioms; an empty match means labeling broke


def test_axiom_table_contents(straddle_theory):
    table = axiom_table(straddle_theory)
    texts = {e["text"] for e in table.values()}
    assert any("Force SubClassOf" in t for t in texts)
    disjoints = [e for e in table.values() if e["kind"] == "disjointness"]
    assert all(e["origin"] in ("asserted", "bfo") for e in disjoints)


def test_labeled_alignment_with_bfo_align(straddle_theory):
    """align_bfo changes formula shape but must not disturb the label indexing."""
    rendered = render_prover9(straddle_theory, align_bfo=True, labels=True)
    emitted = set(re.findall(r"# label\((\w+)\)", rendered))
    assert emitted == set(axiom_table(straddle_theory).keys())


@requires_provers
def test_cross_check_extracts_proof_core(straddle_theory):
    """The straddle: Force ⊑ quality, Force ⊑ disposition, quality/disposition
    disjoint. The proof core must be exactly those three axioms."""
    result = cross_check(straddle_theory)
    assert result["prover_unsatisfiable"] == ["Force"]
    cores = result["proof_cores"]
    assert len(cores) == 1
    core = cores[0]
    assert core["class"] == "Force"
    assert core["may_use_background"] is False
    kinds = sorted(ax["kind"] for ax in core["axioms"])
    assert kinds == ["disjointness", "subsumption", "subsumption"]
    texts = " | ".join(ax["text"] for ax in core["axioms"])
    assert "Force SubClassOf quality" in texts
    assert "Force SubClassOf disposition" in texts
    assert "disposition DisjointWith quality" in texts


@requires_provers
def test_no_cores_key_when_all_satisfiable():
    theory = build_theory(file_path="tests/fixtures/coherent_tiny.owl")
    result = cross_check(theory)
    assert result["prover_unsatisfiable"] == []
    assert "proof_cores" not in result
