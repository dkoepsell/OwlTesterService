import os
import re
import csv
import logging
import nltk
import datetime
import importlib.util
import owlready2
import json
from io import StringIO, BytesIO
from owlready2 import *
from nltk.sem import Expression
from nltk.sem.logic import LogicalExpressionException, LogicParser

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to download required NLTK data
try:
    nltk.data.find('corpora/wordnet')
except LookupError:
    nltk.download('wordnet')

try:
    nltk.data.find('corpora/omw-1.4')
except LookupError:
    nltk.download('omw-1.4')

# Path to the BFO OWL file
BFO_PATH = os.environ.get('BFO_PATH', os.path.join(os.path.dirname(__file__), 'attached_assets/integrated_ontology_cyberspace (1).owl'))

class OwlTester:
    """
    Class for testing OWL ontologies.
    """
    
    def __init__(self):
        """
        Initialize the OwlTester with BFO classes and relations.
        """
        self.bfo_classes = {}
        self.bfo_relations = {}
        self.read_parser = LogicParser()
        
        # Load BFO classes and relations
        self.load_bfo_classes()
    
    def load_bfo_classes(self):
        """
        Load BFO classes and relations from the BFO OWL file.
        If the file doesn't exist, proceed with default BFO dictionaries.
        """
        try:
            # Try to load the BFO ontology
            self.bfo_onto = owlready2.get_ontology(BFO_PATH).load()
            
            # Extract classes and store them in a dictionary with URI as key
            for cls in self.bfo_onto.classes():
                # Use rdfs:label if available, otherwise use the class name
                label = str(cls.label.first()) if cls.label else cls.name
                self.bfo_classes[label.lower()] = {
                    'label': label,
                    'uri': cls.iri,
                    'description': str(cls.comment.first()) if cls.comment else ''
                }
            
            # Extract object properties (relations)
            for prop in self.bfo_onto.object_properties():
                # Use rdfs:label if available, otherwise use the property name
                label = str(prop.label.first()) if prop.label else prop.name
                self.bfo_relations[label.lower()] = {
                    'label': label,
                    'uri': prop.iri,
                    'description': str(prop.comment.first()) if prop.comment else '',
                    'domain': str(prop.domain[0].name) if prop.domain else '',
                    'range': str(prop.range[0].name) if prop.range else ''
                }
            
            logging.info(f"Successfully loaded {len(self.bfo_classes)} BFO classes and {len(self.bfo_relations)} relations")
        except Exception as e:
            logging.warning(f"Could not load BFO ontology: {e}. Loading default BFO class/relation dictionaries.")
            
            # Add fundamental BFO classes as a fallback
            default_bfo_classes = [
                "entity", "continuant", "occurrent", "independent_continuant", "dependent_continuant", 
                "material_entity", "immaterial_entity", "quality", "role", "disposition", 
                "function", "spatial_region", "process", "process_boundary", "temporal_region",
                "continuant_fiat_boundary", "site", "object", "object_aggregate", "fiat_object_part"
            ]
            
            for cls_name in default_bfo_classes:
                self.bfo_classes[cls_name.lower()] = {
                    'label': cls_name,
                    'uri': f"http://purl.obolibrary.org/obo/BFO_{cls_name}",
                    'description': f"BFO {cls_name.replace('_', ' ')}"
                }
            
            # Add fundamental BFO relations as a fallback
            default_bfo_relations = [
                "part_of", "has_part", "located_in", "contains", "participates_in", 
                "has_participant", "bearer_of", "inheres_in", "realized_in", "realizes",
                "exists_at", "instance_of", "occurs_in", "has_quality", "quality_of"
            ]
            
            for rel_name in default_bfo_relations:
                self.bfo_relations[rel_name.lower()] = {
                    'label': rel_name,
                    'uri': f"http://purl.obolibrary.org/obo/BFO_{rel_name}",
                    'description': f"BFO relation {rel_name.replace('_', ' ')}"
                }
                
            logging.info(f"Loaded {len(self.bfo_classes)} default BFO classes and {len(self.bfo_relations)} default relations")
    
    def test_expression(self, expr_string):
        """
        Test a FOL expression for validity and BFO compatibility.
        
        Args:
            expr_string (str): The FOL expression to test
            
        Returns:
            dict: A dictionary containing the test results
        """
        results = {
            'expression': expr_string,
            'valid': False,
            'parsed': False,
            'issues': [],
        }
        
        try:
            # Check if the expression is empty
            if not expr_string.strip():
                results['issues'].append('Empty expression provided')
                return results
            
            # Try to parse the expression
            expr = self.read_parser.parse(expr_string)
            results['parsed'] = True
            
            # Extract terms from the expression
            terms = self.extract_terms(expr_string)
            
            # Check if terms are recognized BFO classes or relations
            bfo_classes_used = []
            bfo_relations_used = []
            non_bfo_terms = []
            
            for term in terms:
                term_lower = term.lower()
                partial_matches = []
                
                # Check for exact match in BFO classes
                if term_lower in self.bfo_classes:
                    bfo_classes_used.append(self.bfo_classes[term_lower])
                # Check for exact match in BFO relations
                elif term_lower in self.bfo_relations:
                    bfo_relations_used.append(self.bfo_relations[term_lower])
                else:
                    # Check for partial matches
                    for bfo_class in self.bfo_classes:
                        if term_lower in bfo_class or bfo_class in term_lower:
                            partial_matches.append({
                                'term': term,
                                'match': self.bfo_classes[bfo_class]['label'],
                                'type': 'class',
                                'partial': True
                            })
                    
                    for bfo_relation in self.bfo_relations:
                        if term_lower in bfo_relation or bfo_relation in term_lower:
                            partial_matches.append({
                                'term': term,
                                'match': self.bfo_relations[bfo_relation]['label'],
                                'type': 'relation',
                                'partial': True
                            })
                    
                    if partial_matches:
                        # Add the first partial match with a note
                        match = partial_matches[0]
                        results['issues'].append(f"Note: '{term}' was interpreted as BFO {match['type']} '{match['match']}'. This is a partial match.")
                    else:
                        # No match found
                        non_bfo_terms.append(term)
                        results['issues'].append(f"Term '{term}' is not recognized as a BFO class or relation.")
            
            # Detect the format used in the expression
            format_detected = self.detect_format(expr_string)
            if format_detected:
                results['format_detected'] = format_detected
            
            # Store the terms found
            results['bfo_classes_used'] = bfo_classes_used
            results['bfo_relations_used'] = bfo_relations_used
            results['non_bfo_terms'] = non_bfo_terms
            
            # Determine overall validity
            results['valid'] = len(non_bfo_terms) == 0 and results['parsed'] and not results['issues']
            
            return results
            
        except LogicalExpressionException as e:
            results['issues'].append(f"Parsing error: {str(e)}")
            return results
        except Exception as e:
            results['issues'].append(f"Error testing expression: {str(e)}")
            return results
    
    def detect_format(self, expr_string):
        """
        Detect whether the expression uses traditional notation (Class(x)) or BFO-style notation (instance_of(x,Class,t)).
        
        Args:
            expr_string (str): The expression string to analyze
            
        Returns:
            str: 'traditional', 'instance_of', or None if undetermined
        """
        # Check for instance_of patterns
        instance_of_pattern = r'instance_of\s*\(\s*\w+\s*,\s*\w+\s*,\s*\w+\s*\)'
        if re.search(instance_of_pattern, expr_string):
            return 'instance_of'
        
        # Check for traditional patterns
        traditional_pattern = r'[A-Z][a-zA-Z]*\s*\(\s*\w+\s*\)'
        if re.search(traditional_pattern, expr_string):
            return 'traditional'
        
        return None
    
    def preprocess_expression(self, expr_string):
        """
        Preprocess the input expression to handle BFO-style multi-variable quantifiers.
        
        Converts expressions like "forall x,t (...)" to "forall x (forall t (...))"
        to make them compatible with NLTK's parser.
        
        Args:
            expr_string (str): The original expression string
            
        Returns:
            str: The preprocessed expression
        """
        # Return original if no preprocessing needed
        if ',' not in expr_string:
            return expr_string
            
        # Pattern to match quantifiers with comma-separated variables
        pattern = r'(forall|exists)\s+([a-zA-Z0-9_]+)(?:,\s*([a-zA-Z0-9_,\s]+))\s*\('
        
        def replacement(match):
            quantifier = match.group(1)  # 'forall' or 'exists'
            first_var = match.group(2)   # First variable
            other_vars = match.group(3)  # Remaining variables (comma-separated)
            
            # Split remaining variables and strip whitespace
            var_list = [var.strip() for var in other_vars.split(',')]
            
            # Build nested quantifiers from inside out
            inner_expr = '('  # This will be closed by the original expression
            
            # Build the nested quantifier structure from the innermost outward
            for var in reversed(var_list):
                if var:  # Skip empty strings
                    inner_expr = f"{quantifier} {var} {inner_expr}"
            
            # Add the outermost quantifier with the first variable
            result = f"{quantifier} {first_var} {inner_expr}"
            
            return result
        
        # Apply the regex replacement for all matches
        preprocessed = re.sub(pattern, replacement, expr_string)
        
        return preprocessed
        
    def extract_terms(self, expr_string):
        """
        Extract all terms from the expression string.
        Handles both traditional notation (Class(x)) and BFO-style (instance_of(x,Class,t)) formats.
        """
        # Initialize variables to store extracted terms
        extracted_terms = []
        
        # Pattern for extracting instance_of expressions: instance_of(x, Class, t)
        instance_of_pattern = r'instance_of\s*\(\s*\w+\s*,\s*(\w+)\s*,\s*\w+\s*\)'
        
        # Pattern for extracting traditional class expressions: Class(x)
        traditional_pattern = r'(\w+)\s*\(\s*\w+\s*\)'
        
        # Pattern for extracting binary relations: relation(x, y)
        relation_pattern = r'(\w+)\s*\(\s*\w+\s*,\s*\w+(?:\s*,\s*\w+)?\s*\)'
        
        # Find all instance_of expressions and extract the class names
        for match in re.finditer(instance_of_pattern, expr_string):
            class_name = match.group(1)
            if class_name and class_name not in ['instance_of']:
                extracted_terms.append(class_name)
        
        # Find all traditional class expressions
        for match in re.finditer(traditional_pattern, expr_string):
            class_name = match.group(1)
            if class_name and class_name not in ['instance_of', 'forall', 'exists']:
                extracted_terms.append(class_name)
        
        # Find all binary relation expressions
        for match in re.finditer(relation_pattern, expr_string):
            relation_name = match.group(1)
            if relation_name and relation_name not in ['instance_of', 'forall', 'exists']:
                extracted_terms.append(relation_name)
        
        # Remove duplicates and return
        return list(set(extracted_terms))
        
    def get_bfo_classes(self):
        """
        Return the BFO classes dictionary.
        
        Returns:
            dict: Dictionary of BFO classes
        """
        return self.bfo_classes
    
    def get_bfo_relations(self):
        """
        Return the BFO relations dictionary.
        
        Returns:
            dict: Dictionary of BFO relations
        """
        return self.bfo_relations
        
    def load_ontology_from_file(self, ontology_path):
        """
        Load an ontology from a file.
        
        Args:
            ontology_path (str): Path to the ontology file
            
        Returns:
            dict: Information about the loaded ontology
        """
        # First try direct loading with owlready2
        try:
            # Try to load the ontology
            onto = owlready2.get_ontology(ontology_path).load()
            
            # Return basic information about the ontology
            return {
                'name': onto.name,
                'base_iri': onto.base_iri,
                'ontology': onto,
                'loaded': True
            }
        except Exception as e:
            logging.warning(f"Initial owlready2 loading failed for {ontology_path}: {e}")
            
            # Try alternate loading methods using rdflib as an intermediary
            try:
                import rdflib
                import tempfile
                
                # Load with rdflib first
                g = rdflib.Graph()
                g.parse(ontology_path)
                
                if len(g) > 0:
                    logging.info(f"Successfully loaded {len(g)} triples with rdflib")
                    
                    # Create a temporary file
                    with tempfile.NamedTemporaryFile(suffix='.owl', delete=False) as temp:
                        # Serialize to RDF/XML with explicit namespaces
                        temp_path = temp.name
                        g.serialize(destination=temp_path, format='xml')
                    
                    try:
                        # Try to load the re-serialized file with owlready2
                        onto = owlready2.get_ontology(temp_path).load()
                        
                        # Return basic information about the ontology
                        return {
                            'name': onto.name or "Unknown",
                            'base_iri': onto.base_iri or "Not specified",
                            'ontology': onto,
                            'loaded': True
                        }
                    except Exception as inner_e:
                        logging.error(f"Failed to load re-serialized ontology: {inner_e}")
                        return {
                            'loaded': False,
                            'error': f"Failed to load re-serialized ontology: {inner_e}"
                        }
                else:
                    logging.error("No triples found in the ontology file")
                    return {
                        'loaded': False,
                        'error': "No triples found in the ontology file"
                    }
            except Exception as rdf_e:
                logging.error(f"Error loading ontology with rdflib from {ontology_path}: {rdf_e}")
                return {
                    'loaded': False,
                    'error': f"Failed with both owlready2 and rdflib: {e}; {rdf_e}"
                }
    
    def analyze_ontology(self, onto):
        """
        Analyze an ontology and extract key information.
        
        Args:
            onto: The owlready2 ontology object
            
        Returns:
            dict: Analysis results
        """
        try:
            # Get basic counts from the ontology
            classes_list = list(onto.classes())
            object_properties_list = list(onto.object_properties())
            data_properties_list = list(onto.data_properties())
            individuals_list = list(onto.individuals())
            annotation_properties_list = list(onto.annotation_properties())
            
            # Count axioms - This is a rough approximation since owlready2 doesn't directly expose axiom counts
            axiom_count = 0
            
            # Count class axioms (subclass relationships, equivalence, etc.)
            for cls in classes_list:
                # Count subclass relationships
                if hasattr(cls, 'is_a') and cls.is_a:
                    if isinstance(cls.is_a, list) or hasattr(cls.is_a, '__len__'):
                        axiom_count += len(cls.is_a)
                    else:
                        axiom_count += 1  # Count as single axiom if it's not a collection
                
                # Count class restrictions
                if hasattr(cls, 'equivalent_to') and cls.equivalent_to:
                    if isinstance(cls.equivalent_to, list) or hasattr(cls.equivalent_to, '__len__'):
                        axiom_count += len(cls.equivalent_to)
                    else:
                        axiom_count += 1  # Count as single axiom if it's not a collection
                
                # Count disjoint class relationships
                if hasattr(cls, 'disjoints') and cls.disjoints():
                    axiom_count += len(list(cls.disjoints()))
            
            # Count property axioms
            for prop in object_properties_list + data_properties_list:
                # Domain and range axioms
                if hasattr(prop, 'domain') and prop.domain:
                    if isinstance(prop.domain, list) or hasattr(prop.domain, '__len__'):
                        axiom_count += len(prop.domain)
                    else:
                        axiom_count += 1  # Count as single axiom if it's not a collection
                        
                if hasattr(prop, 'range') and prop.range:
                    if isinstance(prop.range, list) or hasattr(prop.range, '__len__'):
                        axiom_count += len(prop.range)
                    else:
                        axiom_count += 1  # Count as single axiom if it's not a collection
                
                # Property characteristics
                for characteristic in ['functional', 'inverse_functional', 'transitive', 
                                       'symmetric', 'asymmetric', 'reflexive', 'irreflexive']:
                    if hasattr(prop, characteristic) and getattr(prop, characteristic):
                        axiom_count += 1
            
            # Count annotations
            for entity in classes_list + object_properties_list + data_properties_list + individuals_list:
                if hasattr(entity, 'comment') and entity.comment:
                    axiom_count += len(entity.comment)
                if hasattr(entity, 'label') and entity.label:
                    axiom_count += len(entity.label)
            
            # Build the result dictionary
            result = {
                'classes': len(classes_list),
                'object_properties': len(object_properties_list),
                'data_properties': len(data_properties_list),
                'individuals': len(individuals_list),
                'annotation_properties': len(annotation_properties_list),
                'imported_ontologies': [o.base_iri for o in onto.imported_ontologies],
                'axioms': axiom_count,
                'class_list': [cls.name for cls in classes_list if hasattr(cls, 'name')],
                'object_property_list': [prop.name for prop in object_properties_list if hasattr(prop, 'name')],
                'data_property_list': [prop.name for prop in data_properties_list if hasattr(prop, 'name')],
                'individual_list': [ind.name for ind in individuals_list if hasattr(ind, 'name')]
            }
            
            # Check consistency
            try:
                # owlready2's reasoner for consistency checking
                with onto:
                    consistency = owlready2.sync_reasoner_pellet(infer_property_values=True, 
                                                               infer_data_property_values=True)
                result['consistency'] = 'Consistent'
            except Exception as e:
                result['consistency'] = 'Inconsistent'
                result['consistency_error'] = str(e)
            
            # Get expressivity (this is a placeholder, as owlready2 doesn't directly expose DL expressivity)
            result['expressivity'] = self._determine_expressivity(onto)
            
            return result
        except Exception as e:
            logging.error(f"Error analyzing ontology: {e}")
            # Return empty values on error
            return {
                'classes': 0,
                'object_properties': 0,
                'data_properties': 0,
                'individuals': 0,
                'annotation_properties': 0,
                'imported_ontologies': [],
                'axioms': 0,
                'consistency': 'Unknown',
                'expressivity': 'Unknown',
                'error': str(e)
            }
    
    def _determine_expressivity(self, onto):
        """
        Determine the DL expressivity of an ontology.
        This is a rough approximation as owlready2 doesn't expose this directly.
        """
        expressivity = "AL"  # Start with basic expressivity
        
        # Check for complex classes that would indicate higher expressivity
        has_union = False
        has_complement = False
        has_cardinality = False
        has_nominals = False
        has_inverse = False
        has_role_hierarchy = False
        has_transitivity = False
        has_functionality = False
        
        # Check classes for complex expressions
        for cls in onto.classes():
            # Check for union (U)
            if hasattr(cls, 'equivalent_to'):
                for eq in cls.equivalent_to:
                    if isinstance(eq, owlready2.Or):
                        has_union = True
                    elif isinstance(eq, owlready2.Not):
                        has_complement = True
                    elif isinstance(eq, owlready2.Restriction):
                        if eq.type == owlready2.SOME:  # Existential (E)
                            expressivity = expressivity.replace("AL", "ALE")
                        elif eq.type == owlready2.ONLY:  # Universal (U)
                            pass  # Already included in AL
                        elif eq.type in [owlready2.MIN, owlready2.MAX, owlready2.EXACTLY]:  # Number restrictions (N)
                            has_cardinality = True
                        if eq.value and isinstance(eq.value, owlready2.Thing):  # Nominals (O)
                            has_nominals = True
        
        # Check properties for complex characteristics
        for prop in onto.object_properties():
            # Check for inverse properties (I)
            if hasattr(prop, 'inverse') and prop.inverse:
                has_inverse = True
            
            # Check for role hierarchy (H)
            if hasattr(prop, 'is_a') and len(prop.is_a) > 1:  # More than just owl:ObjectProperty
                has_role_hierarchy = True
            
            # Check for transitivity (R+)
            if hasattr(prop, 'transitive') and prop.transitive:
                has_transitivity = True
            
            # Check for functionality (F)
            if hasattr(prop, 'functional') and prop.functional:
                has_functionality = True
        
        # Build the expressivity string
        if has_union:
            expressivity += "U"
        if has_complement:
            expressivity += "C"
        if has_cardinality:
            expressivity += "N"
        if has_inverse:
            expressivity += "I"
        if has_role_hierarchy:
            expressivity += "H"
        if has_transitivity:
            expressivity += "R+"
        if has_functionality:
            expressivity += "F"
        if has_nominals:
            expressivity += "O"
        
        # Check for ALC (which requires both U and C)
        if "U" in expressivity and "C" in expressivity:
            expressivity = expressivity.replace("AL", "ALC")
        
        # Check for SHOIN(D) (OWL DL)
        if all([has_transitivity, has_role_hierarchy, has_nominals, has_inverse, has_cardinality]):
            expressivity = "SHOIN(D)"
        
        # Check for SROIQ(D) (OWL 2 DL)
        if all([has_transitivity, has_role_hierarchy, has_nominals, has_inverse, 
                has_cardinality, has_functionality]):
            expressivity = "SROIQ(D)"
        
        return expressivity
    
    def validate_completeness(self, onto):
        """
        Validate the completeness of an ontology.
        
        Args:
            onto: The owlready2 ontology object
            
        Returns:
            dict: Validation results
        """
        # Placeholder implementation
        return {
            'is_complete': True,
            'missing_elements': []
        }
    
    def check_consistency(self, onto):
        """
        Check the consistency of an ontology.
        
        Args:
            onto: The owlready2 ontology object
            
        Returns:
            dict: Consistency check results
        """
        # Placeholder implementation
        return {
            'is_consistent': True,
            'inconsistency_explanations': []
        }
    
    def generate_uml_diagram(self, onto):
        """
        Generate a UML diagram for an ontology.
        
        Args:
            onto: The owlready2 ontology object
            
        Returns:
            str: PlantUML diagram code
        """
        # Simple implementation to render a basic class diagram
        plantuml_code = "@startuml\n"
        plantuml_code += "' Ontology UML Diagram\n"
        plantuml_code += "' Generated at " + datetime.datetime.now().isoformat() + "\n\n"
        
        # Add classes
        for cls in onto.classes():
            class_name = cls.name
            plantuml_code += f"class \"{class_name}\" as {class_name}\n"
        
        # Add inheritance relationships
        for cls in onto.classes():
            for parent in cls.is_a:
                if hasattr(parent, 'name'):  # Make sure parent is a class
                    plantuml_code += f"{cls.name} --|> {parent.name}\n"
        
        # Close the diagram
        plantuml_code += "\n@enduml"
        
        return plantuml_code
        
    def generate_fol_premises(self, onto):
        """
        Generate First Order Logic premises from an ontology.
        
        Args:
            onto: The owlready2 ontology object
            
        Returns:
            list: FOL premises
        """
        # Placeholder implementation
        return []
        
    def generate_all_implications(self, premises):
        """
        Generate real-world implications from FOL premises.
        
        Args:
            premises (list): FOL premises
            
        Returns:
            list: Real-world implications
        """
        # Placeholder implementation
        return []