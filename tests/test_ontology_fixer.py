"""Tests for the partition-straddle remediation (reassign / drop edge)."""

import rdflib
import pytest
from rdflib.namespace import RDFS

from bfo_lint import bfo_lint
from ontology_fixer import fix_straddle

QUALITY = "http://purl.obolibrary.org/obo/BFO_0000019"
DISPOSITION = "http://purl.obolibrary.org/obo/BFO_0000016"
FORCE = "http://example.org/aero#Force"


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
