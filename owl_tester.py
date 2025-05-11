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
from nltk.sem.logic import LogicalExpressionException

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
        self.read_parser = nltk.sem.logic.LogicParser()
        
        # Load BFO classes and relations
        self.load_bfo_classes()
    
    def load_bfo_classes(self):
        """
        Load BFO classes and relations from the BFO OWL file.
        If the file doesn't exist, proceed with empty dictionaries.
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
            logging.warning(f"Could not load BFO ontology: {e}. Proceeding with empty BFO class/relation dictionaries.")
    
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