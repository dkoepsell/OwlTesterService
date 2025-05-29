"""
BVSS Validation Module for Ontological Consistency Checking

This module extends the existing FOL-OWL tester with BVSS-specific validation
that can detect domain violations, logical contradictions, and structural inconsistencies
in ontologies and visualize them using the BVSS syntax.
"""

import json
from typing import Dict, List, Any, Optional
from owlready2 import *
import logging

logger = logging.getLogger(__name__)

class BVSSValidator:
    """
    Validates ontologies against BVSS semantic rules and BFO constraints.
    """
    
    def __init__(self):
        self.validation_rules = self._init_validation_rules()
        
    def _init_validation_rules(self):
        """Initialize the BVSS validation rules."""
        return {
            "domain_violations": [
                {
                    "rule_id": "quality_inheres_material",
                    "description": "Quality must inheres_in MaterialEntity",
                    "check": self._check_quality_inherence
                },
                {
                    "rule_id": "role_borne_independent", 
                    "description": "Role must be borne_by IndependentContinuant",
                    "check": self._check_role_bearer
                },
                {
                    "rule_id": "disposition_realizes_process",
                    "description": "Disposition must be realized_in Process",
                    "check": self._check_disposition_realization
                }
            ],
            "structural_violations": [
                {
                    "rule_id": "disjoint_classes",
                    "description": "Check for disjoint class violations",
                    "check": self._check_disjoint_violations
                }
            ]
        }
    
    def validate_ontology_graph(self, ontology_path: str, bvss_data: Dict) -> Dict[str, Any]:
        """
        Perform comprehensive BVSS validation on ontology and graph data.
        
        Args:
            ontology_path: Path to the OWL ontology file
            bvss_data: BVSS graph data with nodes and edges
            
        Returns:
            Validation results with errors, warnings, and valid elements
        """
        try:
            # Load ontology
            onto = get_ontology(f"file://{ontology_path}").load()
            
            validation_result = {
                "errors": [],
                "warnings": [],
                "valid": [],
                "metadata": {
                    "ontology_path": ontology_path,
                    "validation_timestamp": None,
                    "total_entities": len(bvss_data.get("nodes", [])),
                    "total_relations": len(bvss_data.get("edges", []))
                }
            }
            
            # Run domain violation checks
            for rule in self.validation_rules["domain_violations"]:
                try:
                    violations = rule["check"](onto, bvss_data)
                    validation_result["errors"].extend(violations)
                except Exception as e:
                    logger.error(f"Error in rule {rule['rule_id']}: {e}")
                    
            # Run structural violation checks
            for rule in self.validation_rules["structural_violations"]:
                try:
                    violations = rule["check"](onto, bvss_data)
                    validation_result["errors"].extend(violations)
                except Exception as e:
                    logger.error(f"Error in rule {rule['rule_id']}: {e}")
            
            # Check instance-level violations
            try:
                instance_violations = self._check_instance_level_violations(onto)
                validation_result["errors"].extend(instance_violations)
            except Exception as e:
                logger.error(f"Error checking instance violations: {e}")
            
            # Check valid relations
            validation_result["valid"] = self._find_valid_relations(onto, bvss_data)
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {
                "errors": [{
                    "type": "validation_error",
                    "description": f"Failed to validate ontology: {str(e)}",
                    "entity": "system"
                }],
                "warnings": [],
                "valid": []
            }
    
    def _check_quality_inherence(self, onto, bvss_data) -> List[Dict]:
        """Check if qualities properly inhere in material entities."""
        violations = []
        
        # Look for quality entities in the graph
        for edge in bvss_data.get("edges", []):
            if not edge or "source" not in edge or "target" not in edge:
                continue
                
            relation = edge.get("relation", "")
            if relation in ["inheres_in", "has_property", "points_to"]:
                source_name = self._extract_name(edge["source"])
                target_name = self._extract_name(edge["target"])
                
                # Check for Quality -> ImmaterialEntity violation
                if (self._is_quality_like(source_name) and 
                    self._is_immaterial_entity_like(target_name)):
                    violations.append({
                        "type": "domain_violation",
                        "rule_id": "quality_inheres_material",
                        "source": source_name,
                        "property": relation,
                        "target": target_name,
                        "expected": "MaterialEntity",
                        "description": f"Quality '{source_name}' cannot point to ImmaterialEntity '{target_name}' - qualities must be associated with MaterialEntities"
                    })
                
                # Check for inheres_in property pointing to wrong target
                if (source_name.lower() == "inheres_in" and 
                    target_name.lower() in ["immaterialentity", "voidspace"]):
                    violations.append({
                        "type": "domain_violation", 
                        "rule_id": "quality_inheres_material",
                        "source": "inheres_in property",
                        "property": relation,
                        "target": target_name,
                        "expected": "MaterialEntity",
                        "description": f"The 'inheres_in' property cannot have range '{target_name}' - it should point to MaterialEntity"
                    })
        
        # Check for any Quality class that might be defined to inhere in wrong entities
        for node in bvss_data.get("nodes", []):
            if not node:
                continue
            node_name = self._extract_name(node.get("name", "") or node.get("id", ""))
            if self._is_quality_like(node_name):
                # Look for edges from this quality node
                for edge in bvss_data.get("edges", []):
                    if (edge and "source" in edge and 
                        self._extract_name(edge["source"]) == node_name and
                        edge.get("relation") in ["inheres_in", "points_to", "has_property"]):
                        target_name = self._extract_name(edge["target"])
                        if self._is_immaterial_entity_like(target_name):
                            violations.append({
                                "type": "domain_violation",
                                "rule_id": "quality_inheres_material", 
                                "source": node_name,
                                "property": edge.get("relation"),
                                "target": target_name,
                                "expected": "MaterialEntity",
                                "description": f"Quality instance '{node_name}' violates BFO constraint by relating to ImmaterialEntity '{target_name}'"
                            })
                    
        return violations
    
    def _check_role_bearer(self, onto, bvss_data) -> List[Dict]:
        """Check if roles are properly borne by independent continuants."""
        violations = []
        
        for edge in bvss_data.get("edges", []):
            if edge.get("relation") in ["borne_by", "has_bearer"]:
                source_name = self._extract_name(edge["source"])
                target_name = self._extract_name(edge["target"])
                
                if self._is_role_like(source_name) and not self._is_independent_continuant_like(target_name):
                    violations.append({
                        "type": "domain_violation",
                        "rule_id": "role_borne_independent",
                        "source": source_name,
                        "property": "borne_by",
                        "target": target_name,
                        "expected": "IndependentContinuant",
                        "description": f"Role '{source_name}' should be borne by an IndependentContinuant, not '{target_name}'"
                    })
                    
        return violations
    
    def _check_disposition_realization(self, onto, bvss_data) -> List[Dict]:
        """Check if dispositions are properly realized in processes."""
        violations = []
        
        for edge in bvss_data.get("edges", []):
            if edge.get("relation") in ["realizes", "realized_in"]:
                source_name = self._extract_name(edge["source"])
                target_name = self._extract_name(edge["target"])
                
                if self._is_disposition_like(source_name) and not self._is_process_like(target_name):
                    violations.append({
                        "type": "domain_violation",
                        "rule_id": "disposition_realizes_process",
                        "source": source_name,
                        "property": "realized_in",
                        "target": target_name,
                        "expected": "Process",
                        "description": f"Disposition '{source_name}' should be realized in a Process, not '{target_name}'"
                    })
                    
        return violations
    
    def _check_disjoint_violations(self, onto, bvss_data) -> List[Dict]:
        """Check for violations of disjoint class constraints."""
        violations = []
        
        # Common disjoint pairs in legal ontologies
        disjoint_pairs = [
            ("MaterialEntity", "ImmaterialEntity"),
            ("IndependentContinuant", "DependentContinuant"),
            ("Process", "Continuant")
        ]
        
        for node in bvss_data.get("nodes", []):
            node_name = self._extract_name(node.get("name", ""))
            
            # Check if entity appears to belong to disjoint classes
            for class1, class2 in disjoint_pairs:
                if (self._belongs_to_class(node_name, class1) and 
                    self._belongs_to_class(node_name, class2)):
                    violations.append({
                        "type": "logical_contradiction",
                        "rule_id": "disjoint_classes",
                        "entity": node_name,
                        "description": f"Entity '{node_name}' cannot be both {class1} and {class2} (disjoint classes)"
                    })
                    
        return violations
    
    def _find_valid_relations(self, onto, bvss_data) -> List[Dict]:
        """Identify relations that pass all validation checks."""
        valid_relations = []
        
        for edge in bvss_data.get("edges", []):
            relation = edge.get("relation", "")
            source = self._extract_name(edge["source"])
            target = self._extract_name(edge["target"])
            
            # For now, mark is_a relations as generally valid
            if relation == "is_a":
                valid_relations.append({
                    "property": relation,
                    "source": source,
                    "target": target,
                    "validation_status": "passed"
                })
                
        return valid_relations
    
    def _extract_name(self, uri: str) -> str:
        """Extract entity name from URI."""
        if isinstance(uri, str):
            if '#' in uri:
                return uri.split('#')[-1]
            elif '/' in uri:
                return uri.split('/')[-1]
        return str(uri)
    
    def _is_quality_like(self, name: str) -> bool:
        """Check if entity name suggests it's a quality."""
        quality_indicators = ["quality", "color", "redness", "hue", "temperature", "weight"]
        return any(indicator in name.lower() for indicator in quality_indicators)
    
    def _is_material_entity_like(self, name: str) -> bool:
        """Check if entity name suggests it's a material entity."""
        material_indicators = ["entity", "object", "agent", "person", "document", "evidence", "materialentity"]
        return any(indicator in name.lower() for indicator in material_indicators)
    
    def _is_immaterial_entity_like(self, name: str) -> bool:
        """Check if entity name suggests it's an immaterial entity."""
        immaterial_indicators = ["immaterial", "void", "space", "region", "information", "immaterialentity", "voidspace"]
        return any(indicator in name.lower() for indicator in immaterial_indicators)
    
    def _is_role_like(self, name: str) -> bool:
        """Check if entity name suggests it's a role."""
        role_indicators = ["role", "judge", "attorney", "witness", "authority"]
        return any(indicator in name.lower() for indicator in role_indicators)
    
    def _is_independent_continuant_like(self, name: str) -> bool:
        """Check if entity name suggests it's an independent continuant."""
        independent_indicators = ["entity", "agent", "person", "court", "system", "organization"]
        return any(indicator in name.lower() for indicator in independent_indicators)
    
    def _is_disposition_like(self, name: str) -> bool:
        """Check if entity name suggests it's a disposition."""
        disposition_indicators = ["disposition", "ability", "capacity", "obligation", "right", "power"]
        return any(indicator in name.lower() for indicator in disposition_indicators)
    
    def _is_process_like(self, name: str) -> bool:
        """Check if entity name suggests it's a process."""
        process_indicators = ["process", "trial", "adjudication", "hearing", "procedure", "enforcement"]
        return any(indicator in name.lower() for indicator in process_indicators)
    
    def _belongs_to_class(self, entity_name: str, class_name: str) -> bool:
        """Check if entity belongs to a particular class based on naming patterns."""
        class_mappings = {
            "MaterialEntity": ["document", "evidence", "contract", "agent", "person"],
            "ImmaterialEntity": ["right", "obligation", "quality", "information"],
            "IndependentContinuant": ["entity", "agent", "court", "organization"],
            "DependentContinuant": ["role", "quality", "disposition", "claim"],
            "Process": ["trial", "process", "adjudication", "enforcement"],
            "Continuant": ["entity", "agent", "role", "quality", "document"]
        }
        
        if class_name in class_mappings:
            return any(indicator in entity_name.lower() for indicator in class_mappings[class_name])
        return False
    
    def _check_instance_level_violations(self, onto) -> List[Dict]:
        """
        Check for instance-level violations where individuals don't satisfy 
        their property domain/range constraints.
        """
        violations = []
        
        try:
            # Get all individuals and their property assertions
            for individual in onto.individuals():
                individual_name = self._extract_name(str(individual.iri))
                
                # Check all property relations for this individual
                for prop in individual.get_properties():
                    prop_name = self._extract_name(str(prop.iri))
                    
                    # Get property values
                    for value in prop[individual]:
                        if hasattr(value, 'iri'):  # Object property
                            value_name = self._extract_name(str(value.iri))
                            
                            # Check specific BFO constraint violations
                            if prop_name == "inheres_in":
                                # Check if subject is Quality and object is ImmaterialEntity
                                if (self._is_quality_like(individual_name) and 
                                    self._is_immaterial_entity_like(value_name)):
                                    violations.append({
                                        "type": "instance_violation",
                                        "rule_id": "quality_inheres_material_instance",
                                        "source": individual_name,
                                        "property": prop_name,
                                        "target": value_name,
                                        "expected": "MaterialEntity",
                                        "description": f"Instance violation: Quality '{individual_name}' cannot inhere in ImmaterialEntity '{value_name}' - violates BFO constraint"
                                    })
                                    
        except Exception as e:
            # Log error but don't fail validation
            pass
            
        return violations