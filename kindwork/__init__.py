"""Kindwork adapter (KINDWORK-ECOSYSTEM-SPEC.md, section 5).

Accepts what Kindwork exports (OWL in Turtle or RDF/XML, optional SHACL shapes,
optional kindwork-model manifest) and returns an owltester-findings document
Kindwork can import as cards.
"""

from kindwork.bundle import Bundle, BundleRefused, load_bundle
from kindwork.check import check_bundle

__all__ = ["Bundle", "BundleRefused", "load_bundle", "check_bundle"]
