"""
BVSS (Barwise Visual Symbol System) Model Converter for OWL Ontologies

This module converts OWL ontologies to BVSS-compatible graph structures
for visualization, with special focus on BFO (Basic Formal Ontology) alignment.
"""

import logging
from owlready2 import get_ontology
from bfo_2020_definitions import BFO_2020_CLASSES, BFO_2020_RELATIONS

logger = logging.getLogger(__name__)

class BVSSConverter:
    """
    Converts OWL ontologies to BVSS visualization format.
    """
    
    def __init__(self):
        self.bfo_classes = BFO_2020_CLASSES
        self.bfo_relations = BFO_2020_RELATIONS
    
    def extract_bvss_graph(self, ontology_path):
        """
        Extract a BVSS-compatible graph structure from an OWL ontology.
        
        Args:
            ontology_path (str): Path to the OWL ontology file
            
        Returns:
            dict: Graph structure with nodes and edges for BVSS visualization
        """
        try:
            onto = get_ontology(ontology_path).load()
            nodes = []
            edges = []
            
            # Extract classes as nodes
            for cls in onto.classes():
                if cls.name:  # Skip anonymous classes
                    node = {
                        "id": str(cls.iri),
                        "name": cls.name,
                        "label": cls.name,
                        "type": self.classify_bfo_type(cls),
                        "description": self.get_class_description(cls),
                        "temporal": self.has_temporal_aspects(cls)
                    }
                    nodes.append(node)
                    
                    # Extract inheritance relationships
                    for parent in cls.is_a:
                        if hasattr(parent, 'iri') and parent.name:
                            edge = {
                                "source": str(parent.iri),
                                "target": str(cls.iri),
                                "relation": "is_a",
                                "type": "inheritance"
                            }
                            edges.append(edge)
            
            # Extract object properties as relationships
            for prop in onto.object_properties():
                if prop.name:
                    # Add property as a node if it represents a significant relationship
                    prop_node = {
                        "id": str(prop.iri),
                        "name": prop.name,
                        "label": prop.name,
                        "type": "Relation",
                        "description": self.get_property_description(prop),
                        "temporal": False
                    }
                    nodes.append(prop_node)
                    
                    # Connect domains and ranges if specified
                    if prop.domain:
                        for domain_cls in prop.domain:
                            if hasattr(domain_cls, 'iri'):
                                edge = {
                                    "source": str(domain_cls.iri),
                                    "target": str(prop.iri),
                                    "relation": "has_property",
                                    "type": "domain"
                                }
                                edges.append(edge)
                    
                    if prop.range:
                        for range_cls in prop.range:
                            if hasattr(range_cls, 'iri'):
                                edge = {
                                    "source": str(prop.iri),
                                    "target": str(range_cls.iri),
                                    "relation": "points_to",
                                    "type": "range"
                                }
                                edges.append(edge)
            
            return {
                "nodes": nodes,
                "edges": edges,
                "classes": [{"id": n["id"], "name": n["name"]} for n in nodes if n["type"] != "Relation"],
                "properties": [{"id": n["id"], "name": n["name"]} for n in nodes if n["type"] == "Relation"],
                "inheritance": [{"source": e["source"], "target": e["target"], "relation": e["relation"]} for e in edges],
                "ontology_info": {
                    "name": onto.name or "Unknown",
                    "base_iri": onto.base_iri,
                    "class_count": len([n for n in nodes if n["type"] != "Relation"]),
                    "property_count": len([n for n in nodes if n["type"] == "Relation"])
                }
            }
            
        except Exception as e:
            logger.error(f"Error extracting BVSS graph from {ontology_path}: {str(e)}")
            return {
                "nodes": [],
                "edges": [],
                "error": str(e),
                "ontology_info": {
                    "name": "Error",
                    "base_iri": "",
                    "class_count": 0,
                    "property_count": 0
                }
            }
    
    def classify_bfo_type(self, cls):
        """
        Classify a class according to BFO categories for BVSS visualization.
        
        Args:
            cls: OWL class from owlready2
            
        Returns:
            str: BFO type category
        """
        class_name = cls.name.lower() if cls.name else ""
        class_iri = str(cls.iri).lower()
        
        # Check for direct BFO class matches
        for bfo_class_id, bfo_info in self.bfo_classes.items():
            if (bfo_class_id.lower() in class_name or 
                bfo_class_id.lower().replace('_', '') in class_name.replace('_', '')):
                return bfo_info.get('category', 'IndependentContinuant')
        
        # Heuristic classification based on naming patterns
        if any(term in class_name for term in ['process', 'event', 'activity', 'action']):
            return "Process"
        elif any(term in class_name for term in ['role', 'function', 'disposition', 'quality']):
            return "DependentContinuant"
        elif any(term in class_name for term in ['entity', 'object', 'material', 'substance']):
            return "IndependentContinuant"
        elif any(term in class_name for term in ['temporal', 'time', 'moment', 'interval']):
            return "TemporalRegion"
        elif any(term in class_name for term in ['spatial', 'region', 'location', 'place']):
            return "SpatialRegion"
        else:
            # Default classification
            return "IndependentContinuant"
    
    def has_temporal_aspects(self, cls):
        """
        Determine if a class has temporal aspects for BVSS visualization.
        
        Args:
            cls: OWL class from owlready2
            
        Returns:
            bool: True if the class has temporal aspects
        """
        class_name = cls.name.lower() if cls.name else ""
        temporal_keywords = ['temporal', 'time', 'moment', 'interval', 'duration', 'period']
        
        return any(keyword in class_name for keyword in temporal_keywords)
    
    def get_class_description(self, cls):
        """
        Extract description/comment from a class.
        
        Args:
            cls: OWL class from owlready2
            
        Returns:
            str: Description of the class
        """
        if cls.comment:
            return str(cls.comment[0]) if cls.comment else ""
        return f"OWL class: {cls.name}"
    
    def get_property_description(self, prop):
        """
        Extract description/comment from a property.
        
        Args:
            prop: OWL property from owlready2
            
        Returns:
            str: Description of the property
        """
        if prop.comment:
            return str(prop.comment[0]) if prop.comment else ""
        return f"OWL property: {prop.name}"

def extract_bvss_graph(ontology_path):
    """
    Convenience function to extract BVSS graph from an ontology file.
    
    Args:
        ontology_path (str): Path to the OWL ontology file
        
    Returns:
        dict: BVSS graph structure
    """
    converter = BVSSConverter()
    return converter.extract_bvss_graph(ontology_path)