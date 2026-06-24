"""Tests for the BFO conformance lint (SPEC Task 3)."""

import time

import rdflib

from bfo_lint import bfo_lint


def _lint(path, catalog):
    g = rdflib.Graph()
    g.parse(path)
    return bfo_lint(g, catalog)


def test_straddle_yields_exactly_one_finding(straddle_owl, catalog):
    findings = _lint(straddle_owl, catalog)
    assert len(findings) == 1
    f = findings[0]
    assert f.cls == "Force"
    assert {f.category_a, f.category_b} == {"quality", "disposition"}
    assert "disjoint" in f.message.lower()


def test_coherent_fixture_yields_no_findings(coherent_owl, catalog):
    assert _lint(coherent_owl, catalog) == []


def test_lint_is_fast(straddle_owl, catalog):
    g = rdflib.Graph()
    g.parse(straddle_owl)
    start = time.perf_counter()
    bfo_lint(g, catalog)
    assert time.perf_counter() - start < 1.0


def test_lint_finding_serializes(straddle_owl, catalog):
    f = _lint(straddle_owl, catalog)[0]
    d = f.to_dict()
    assert d["class"] == "Force"
    step = f.to_derivation_step()
    assert step["axiom_type"] == "Inconsistency"
    assert step["origin"] == "BFO Lint"
