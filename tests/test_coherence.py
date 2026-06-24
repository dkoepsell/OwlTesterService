"""End-to-end coherence tests (SPEC Task 2).

These exercise the in-process Pellet path, so they require a Java runtime and are
skipped when Java is absent (the catalog and lint tests still run).
"""

from tests.conftest import requires_java


@requires_java
def test_straddle_is_consistent_but_incoherent(straddle_owl):
    from owl_tester import OwlTester

    tester = OwlTester()
    info = tester.load_ontology_from_file(straddle_owl)
    result = tester.analyze_ontology(info["ontology"], file_path=straddle_owl)

    # The whole point: consistency and coherence are now distinct.
    assert result["is_consistent"] is True
    assert result["coherence_status"] == "incoherent"

    names = {c["name"] for c in result["unsatisfiable_classes"]}
    assert "Force" in names

    # Each unsatisfiable class carries a justification (lint fallback).
    force = next(c for c in result["unsatisfiable_classes"] if c["name"] == "Force")
    assert force["justification"]


@requires_java
def test_coherent_fixture_is_coherent(coherent_owl):
    from owl_tester import OwlTester

    tester = OwlTester()
    info = tester.load_ontology_from_file(coherent_owl)
    result = tester.analyze_ontology(info["ontology"], file_path=coherent_owl)

    assert result["is_consistent"] is True
    assert result["coherence_status"] == "coherent"
    assert result["unsatisfiable_classes"] == []
    assert result["lint_findings"] == []
