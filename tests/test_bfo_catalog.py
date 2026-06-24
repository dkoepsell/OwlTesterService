"""Tests for the vendored BFO 2020 catalog (SPEC Task 1)."""

from bfo import as_ui_dict

QUALITY = "http://purl.obolibrary.org/obo/BFO_0000019"
DISPOSITION = "http://purl.obolibrary.org/obo/BFO_0000016"
CONTINUANT = "http://purl.obolibrary.org/obo/BFO_0000002"
OCCURRENT = "http://purl.obolibrary.org/obo/BFO_0000003"


def test_catalog_loads_classes(catalog):
    ui = as_ui_dict(catalog)
    assert len(ui) > 20
    assert "quality" in ui


def test_disjoint_pairs_exceed_seven(catalog):
    # SPEC Task 1 acceptance: more than the seven hand-copied pairs.
    assert len(catalog.disjoint_pairs) > 7


def test_labels_resolve(catalog):
    assert catalog.label_for(QUALITY) == "quality"
    assert catalog.label_for(DISPOSITION) == "disposition"


def test_closure_catches_quality_disposition(catalog):
    # Not asserted disjoint directly; only via the closure (quality vs
    # realizable entity, with disposition under realizable entity).
    assert catalog.clash(QUALITY, DISPOSITION) is True


def test_closure_catches_continuant_occurrent(catalog):
    assert catalog.clash(CONTINUANT, OCCURRENT) is True


def test_unrelated_categories_do_not_clash(catalog):
    assert catalog.clash(QUALITY, QUALITY) is False
