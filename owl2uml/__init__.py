"""owl2uml: convert OWL/RDFS ontologies to UML class diagrams in SVG."""
from .parse import parse_ontology
from .layout import layout
from .render import render_svg

__all__ = ["parse_ontology", "layout", "render_svg"]
__version__ = "0.1.0"
