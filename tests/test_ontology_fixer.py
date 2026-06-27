"""Tests for the partition-straddle remediation (reassign / drop edge)."""

import rdflib
import pytest
from rdflib.namespace import RDFS

from bfo_lint import bfo_lint
from ontology_fixer import choose_drop_iri, fix_all_straddles, fix_straddle

QUALITY = "http://purl.obolibrary.org/obo/BFO_0000019"
DISPOSITION = "http://purl.obolibrary.org/obo/BFO_0000016"
FORCE = "http://example.org/aero#Force"


def _findings(owl_path, catalog):
    g = rdflib.Graph()
    g.parse(owl_path)
    return [f.to_dict() for f in bfo_lint(g, catalog)]


def test_fix_removes_chosen_edge_and_clears_straddle(straddle_owl, catalog):
    # Drop the disposition edge, keeping quality.
    corrected = fix_straddle(straddle_owl, FORCE, DISPOSITION)

    g = rdflib.Graph()
    g.parse(data=corrected, format="xml")

    assert (rdflib.URIRef(FORCE), RDFS.subClassOf, rdflib.URIRef(DISPOSITION)) not in g
    assert (rdflib.URIRef(FORCE), RDFS.subClassOf, rdflib.URIRef(QUALITY)) in g

    # The straddle is gone per the lint.
    assert bfo_lint(g, catalog) == []


def test_fix_refuses_non_bfo_superclass(straddle_owl):
    with pytest.raises(ValueError):
        fix_straddle(straddle_owl, FORCE, "http://example.org/aero#NotBfo")


def test_fix_refuses_absent_edge(coherent_owl):
    with pytest.raises(ValueError):
        fix_straddle(coherent_owl, FORCE, DISPOSITION)


def test_choose_drop_keeps_more_specific(catalog):
    # Disposition (realizable entity subtree) is deeper than Quality, so the
    # broader Quality edge is the one dropped.
    assert choose_drop_iri(QUALITY, DISPOSITION, catalog) == QUALITY
    assert choose_drop_iri(DISPOSITION, QUALITY, catalog) == QUALITY


def test_choose_drop_breaks_ties_by_iri(catalog):
    # Equal specificity -> deterministic: keep the earlier IRI, drop the later.
    a, b = "http://x/AA", "http://x/BB"
    assert choose_drop_iri(a, b, catalog) == b
    assert choose_drop_iri(b, a, catalog) == b


def test_auto_fix_clears_all_straddles_keeping_specific(straddle_owl, catalog):
    findings = _findings(straddle_owl, catalog)
    corrected, removed = fix_all_straddles(straddle_owl, findings, catalog)

    assert removed == len(findings)

    g = rdflib.Graph()
    g.parse(data=corrected, format="xml")

    # The broader category (quality) is dropped; the specific one (disposition) stays.
    assert (rdflib.URIRef(FORCE), RDFS.subClassOf, rdflib.URIRef(QUALITY)) not in g
    assert (rdflib.URIRef(FORCE), RDFS.subClassOf, rdflib.URIRef(DISPOSITION)) in g

    # And the lint is clean afterwards.
    assert bfo_lint(g, catalog) == []


def test_auto_fix_raises_when_nothing_to_remove(coherent_owl, catalog):
    with pytest.raises(ValueError):
        fix_all_straddles(coherent_owl, [], catalog)
