import re
import nltk
import owlready2
from owlready2 import *
from nltk.sem.logic import LogicalExpressionException
from nltk.sem import Expression

# Load required NLTK resources if needed
try:
    # Check if punkt tokenizer is available
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

class OwlTester:
    def __init__(self):
        """Initialize the OwlTester with default ontology and settings."""
        # Load BFO ontology
        self.onto = get_ontology("http://purl.obolibrary.org/obo/bfo.owl").load()
        # Initialize logical expressions reader
        self.read_expr = Expression.fromstring
        # Prepare ontology for testing
        self.prepare_ontology()
    
    def prepare_ontology(self):
        """Prepare the ontology for testing by collecting classes and relations."""
        self.bfo_classes = []
        self.bfo_relations = []
        
        # Collect BFO classes
        for c in self.onto.classes():
            classname = c.name
            if classname is not None:
                self.bfo_classes.append(classname)
        
        # Collect BFO relations (object properties)
        for op in self.onto.object_properties():
            propname = op.name
            if propname is not None:
                self.bfo_relations.append(propname)
    
    def test_expression(self, input_expr):
        """
        Test a FOL expression against BFO-OWL guidelines.
        
        Args:
            input_expr (str): The FOL expression to test
            
        Returns:
            dict: Results of the test including validity, issues, and metadata
        """
        result = {
            "valid": False,
            "issues": [],
            "expression": input_expr,
            "bfo_classes_used": [],
            "bfo_relations_used": [],
            "non_bfo_terms": []
        }
        
        # Check if input is empty
        if not input_expr or input_expr.strip() == "":
            result["issues"].append("Empty expression provided")
            return result
            
        # Parse the expression
        try:
            expr = self.read_expr(input_expr)
            result["parsed_expr"] = str(expr)
        except LogicalExpressionException as e:
            result["issues"].append(f"Parsing error: {str(e)}")
            return result
        
        # Extract terms from the expression
        terms = self.extract_terms(input_expr)
        
        # Check terms against BFO classes and relations
        self.check_terms_against_bfo(terms, result)
        
        # Check syntax and structure
        self.check_syntax_and_structure(input_expr, result)
        
        # If no issues, mark as valid
        if not result["issues"]:
            result["valid"] = True
        
        return result
    
    def extract_terms(self, expr_string):
        """Extract all terms from the expression string."""
        # Remove logical operators and separators
        cleaned = re.sub(r'[&|~()<>.-]', ' ', expr_string)
        # Remove logical words
        for word in ['exists', 'forall', 'implies', 'iff', 'lambda', 'if', 'then', 'and', 'or', 'not']:
            cleaned = re.sub(r'\b' + word + r'\b', ' ', cleaned, flags=re.IGNORECASE)
        
        # Split by spaces and filter out empty strings
        terms = [term.strip() for term in cleaned.split() if term.strip()]
        return terms
    
    def check_terms_against_bfo(self, terms, result):
        """Check terms against BFO classes and relations."""
        for term in terms:
            if term in self.bfo_classes:
                if term not in result["bfo_classes_used"]:
                    result["bfo_classes_used"].append(term)
            elif term in self.bfo_relations:
                if term not in result["bfo_relations_used"]:
                    result["bfo_relations_used"].append(term)
            else:
                # Check if it's a variable (typically lowercase)
                if not term.islower() and term not in result["non_bfo_terms"]:
                    result["non_bfo_terms"].append(term)
                    result["issues"].append(f"Term '{term}' is not recognized as a BFO class or relation")
    
    def check_syntax_and_structure(self, expr_string, result):
        """Check the syntax and structure of the expression."""
        # Check for balanced parentheses
        if expr_string.count('(') != expr_string.count(')'):
            result["issues"].append("Unbalanced parentheses in the expression")
        
        # Check for common syntax issues
        if re.search(r'\(\s*\)', expr_string):
            result["issues"].append("Empty parentheses found")
        
        if re.search(r'[&|]\s*[&|]', expr_string):
            result["issues"].append("Consecutive logical operators found")
        
        # Check for proper quantifier usage
        quantifiers = re.findall(r'\b(exists|forall)\b\s*[a-zA-Z]+', expr_string)
        if not quantifiers and ('exists' in expr_string or 'forall' in expr_string):
            result["issues"].append("Quantifier used without a variable")

    def get_bfo_classes(self):
        """Return all available BFO classes."""
        return sorted(self.bfo_classes)
    
    def get_bfo_relations(self):
        """Return all available BFO relations."""
        return sorted(self.bfo_relations)
