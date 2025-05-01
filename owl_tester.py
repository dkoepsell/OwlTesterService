import re
import os
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
    def __init__(self, ontology_path=None):
        """
        Initialize the OwlTester with default ontology and settings.
        
        Args:
            ontology_path (str, optional): Path to custom OWL file. If None, uses BFO ontology.
        """
        # Load default BFO ontology if no custom path provided
        if ontology_path is None:
            self.onto = get_ontology("http://purl.obolibrary.org/obo/bfo.owl").load()
            self.ontology_source = "BFO (default)"
        else:
            # Load custom ontology from file
            self.onto = get_ontology(ontology_path).load()
            self.ontology_source = os.path.basename(ontology_path)
        
        # Initialize logical expressions reader
        self.read_expr = Expression.fromstring
        
        # Initialize report data
        self.axioms = []
        self.inconsistencies = []
        self.inferred_axioms = []
        
        # Prepare ontology for testing
        self.prepare_ontology()
    
    def prepare_ontology(self):
        """Prepare the ontology for testing by collecting classes and relations."""
        self.bfo_classes = []
        self.bfo_relations = []
        self.data_properties = []
        self.individuals = []
        self.annotation_properties = []
        
        # Collect classes
        for c in self.onto.classes():
            classname = c.name
            if classname is not None:
                self.bfo_classes.append(classname)
        
        # Collect object properties (relations)
        for op in self.onto.object_properties():
            propname = op.name
            if propname is not None:
                self.bfo_relations.append(propname)
        
        # Collect data properties
        for dp in self.onto.data_properties():
            propname = dp.name
            if propname is not None:
                self.data_properties.append(propname)
        
        # Collect individuals
        for i in self.onto.individuals():
            indname = i.name
            if indname is not None:
                self.individuals.append(indname)
                
        # Collect annotation properties
        for ap in self.onto.annotation_properties():
            propname = ap.name
            if propname is not None:
                self.annotation_properties.append(propname)
    
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
        
    def get_data_properties(self):
        """Return all available data properties."""
        return sorted(self.data_properties)
        
    def get_annotation_properties(self):
        """Return all available annotation properties."""
        return sorted(self.annotation_properties)
        
    def get_individuals(self):
        """Return all individuals in the ontology."""
        return sorted(self.individuals)
    
    def analyze_ontology(self):
        """
        Analyze the loaded ontology for axioms, consistency and generate report.
        
        Returns:
            dict: A report containing ontology statistics, axioms, and consistency issues
        """
        # Extract data first to ensure proper conversion of generators to lists
        axioms = self.extract_axioms()
        consistency = self.check_consistency()
        inferred_axioms = self.get_inferred_axioms()
        expressivity = self.get_ontology_expressivity()
        
        # Ensure axioms and inferred_axioms are lists, not generators
        if not isinstance(axioms, list):
            axioms = list(axioms)
        if not isinstance(inferred_axioms, list):
            inferred_axioms = list(inferred_axioms)
            
        report = {
            "ontology_name": self.ontology_source,
            "ontology_iri": str(self.onto.base_iri),
            "stats": {
                "class_count": len(self.bfo_classes),
                "object_property_count": len(self.bfo_relations),
                "data_property_count": len(self.data_properties),
                "individual_count": len(self.individuals),
                "annotation_property_count": len(self.annotation_properties)
            },
            "axioms": axioms,
            "consistency": consistency,
            "inferred": inferred_axioms
        }
        
        # Add additional metrics
        report["metrics"] = {
            "expressivity": expressivity,
            "complexity": len(axioms) + len(inferred_axioms)
        }
        
        return report
    
    def extract_axioms(self):
        """
        Extract all axioms from the ontology.
        
        Returns:
            list: A list of axioms as dictionaries with their properties
        """
        axioms = []
        
        # Extract class axioms
        for cls in self.onto.classes():
            if cls.name is None:
                continue
                
            # Get subclass relationships
            for parent in cls.is_a:
                if hasattr(parent, 'name') and parent.name is not None:
                    axioms.append({
                        "type": "SubClassOf",
                        "subject": cls.name,
                        "object": parent.name,
                        "description": f"{cls.name} is a subclass of {parent.name}"
                    })
            
            # Get equivalent classes
            if hasattr(cls, 'equivalent_to') and cls.equivalent_to:
                for equiv in cls.equivalent_to:
                    if hasattr(equiv, 'name') and equiv.name is not None:
                        axioms.append({
                            "type": "EquivalentClasses",
                            "subject": cls.name,
                            "object": equiv.name,
                            "description": f"{cls.name} is equivalent to {equiv.name}"
                        })
            
            # Get disjoint classes
            if hasattr(cls, 'disjoints'):
                try:
                    # Convert to list in case disjoints() returns a generator
                    disjoints = list(cls.disjoints())
                    for disjoint in disjoints:
                        for entity in disjoint.entities:
                            if entity != cls and hasattr(entity, 'name') and entity.name is not None:
                                axioms.append({
                                    "type": "DisjointClasses",
                                    "subject": cls.name,
                                    "object": entity.name,
                                    "description": f"{cls.name} is disjoint with {entity.name}"
                                })
                except Exception as e:
                    # In case of error, add information about what failed
                    axioms.append({
                        "type": "Error",
                        "subject": cls.name if hasattr(cls, 'name') else "Unknown",
                        "description": f"Error processing disjoints: {str(e)}"
                    })
        
        # Extract property axioms
        for prop in self.onto.object_properties():
            if prop.name is None:
                continue
                
            # Domain and range
            if hasattr(prop, 'domain') and prop.domain:
                for domain in prop.domain:
                    if hasattr(domain, 'name') and domain.name is not None:
                        axioms.append({
                            "type": "ObjectPropertyDomain",
                            "subject": prop.name,
                            "object": domain.name,
                            "description": f"{prop.name} has domain {domain.name}"
                        })
            
            if hasattr(prop, 'range') and prop.range:
                for range_cls in prop.range:
                    if hasattr(range_cls, 'name') and range_cls.name is not None:
                        axioms.append({
                            "type": "ObjectPropertyRange",
                            "subject": prop.name,
                            "object": range_cls.name,
                            "description": f"{prop.name} has range {range_cls.name}"
                        })
            
            # Property characteristics
            characteristics = []
            if hasattr(prop, 'transitive') and prop.transitive:
                characteristics.append("Transitive")
            if hasattr(prop, 'symmetric') and prop.symmetric:
                characteristics.append("Symmetric")
            if hasattr(prop, 'asymmetric') and prop.asymmetric:
                characteristics.append("Asymmetric")
            if hasattr(prop, 'functional') and prop.functional:
                characteristics.append("Functional")
            if hasattr(prop, 'inverse_functional') and prop.inverse_functional:
                characteristics.append("InverseFunctional")
            if hasattr(prop, 'reflexive') and prop.reflexive:
                characteristics.append("Reflexive")
            if hasattr(prop, 'irreflexive') and prop.irreflexive:
                characteristics.append("Irreflexive")
                
            for characteristic in characteristics:
                axioms.append({
                    "type": characteristic,
                    "subject": prop.name,
                    "object": None,
                    "description": f"{prop.name} is {characteristic.lower()}"
                })
        
        # Extract data property axioms
        for prop in self.onto.data_properties():
            if prop.name is None:
                continue
            
            # Domain
            if hasattr(prop, 'domain') and prop.domain:
                for domain in prop.domain:
                    if hasattr(domain, 'name') and domain.name is not None:
                        axioms.append({
                            "type": "DataPropertyDomain",
                            "subject": prop.name,
                            "object": domain.name,
                            "description": f"{prop.name} has domain {domain.name}"
                        })
            
            # Range (data property ranges are different)
            if hasattr(prop, 'range') and prop.range:
                for range_item in prop.range:
                    range_name = str(range_item)
                    axioms.append({
                        "type": "DataPropertyRange",
                        "subject": prop.name,
                        "object": range_name,
                        "description": f"{prop.name} has range {range_name}"
                    })
        
        # Extract individual axioms
        for ind in self.onto.individuals():
            if ind.name is None:
                continue
                
            # Class assertions
            for cls in ind.is_a:
                if hasattr(cls, 'name') and cls.name is not None:
                    axioms.append({
                        "type": "ClassAssertion",
                        "subject": ind.name,
                        "object": cls.name,
                        "description": f"{ind.name} is an instance of {cls.name}"
                    })
            
            # Object property assertions
            for prop in self.onto.object_properties():
                if prop.name is None:
                    continue
                    
                if hasattr(ind, prop.name):
                    values = getattr(ind, prop.name)
                    if values:
                        for val in values:
                            if hasattr(val, 'name') and val.name is not None:
                                axioms.append({
                                    "type": "ObjectPropertyAssertion",
                                    "subject": ind.name,
                                    "property": prop.name,
                                    "object": val.name,
                                    "description": f"{ind.name} {prop.name} {val.name}"
                                })
            
            # Data property assertions
            for prop in self.onto.data_properties():
                if prop.name is None:
                    continue
                    
                if hasattr(ind, prop.name):
                    values = getattr(ind, prop.name)
                    if values:
                        for val in values:
                            axioms.append({
                                "type": "DataPropertyAssertion",
                                "subject": ind.name,
                                "property": prop.name,
                                "object": str(val),
                                "description": f"{ind.name} {prop.name} {val}"
                            })
        
        return axioms
    
    def check_consistency(self):
        """
        Check ontology for consistency using the HermiT reasoner.
        
        Returns:
            dict: Consistency report with status and issues
        """
        consistency_report = {
            "consistent": True,
            "issues": []
        }
        
        try:
            # Create a reasoner
            with self.onto:
                try:
                    # Try running the reasoner
                    sync_reasoner_pellet(infer_property_values=True, 
                                         infer_data_property_values=True)
                    
                    # If we get here, the ontology is consistent
                    consistency_report["consistent"] = True
                except owlready2.base.OwlReadyInconsistentOntologyError as e:
                    # Ontology is inconsistent
                    consistency_report["consistent"] = False
                    consistency_report["issues"].append(str(e))
                    
                    # Try to extract more detailed inconsistency info
                    try:
                        # Convert to list in case inconsistency_explanations() returns a generator
                        explanations = list(self.onto.inconsistency_explanations())
                        for explanation in explanations:
                            consistency_report["issues"].append(str(explanation))
                    except Exception as e:
                        consistency_report["issues"].append(f"Error getting explanations: {str(e)}")
                        pass
                        
        except Exception as e:
            consistency_report["consistent"] = False
            consistency_report["issues"].append(f"Error during consistency check: {str(e)}")
        
        return consistency_report
    
    def get_inferred_axioms(self):
        """
        Get inferred axioms using a reasoner.
        
        Returns:
            list: A list of inferred axioms
        """
        inferred_axioms = []
        
        try:
            # Create a reasoner to infer axioms
            with self.onto:
                try:
                    # Run the reasoner with inference
                    sync_reasoner_pellet(infer_property_values=True,
                                        infer_data_property_values=True)
                    
                    # Extract inferred class subsumptions
                    for cls in self.onto.classes():
                        if cls.name is None:
                            continue
                            
                        # Get inferred subclass relationships
                        if hasattr(cls, 'INDIRECT_is_a'):
                            try:
                                # Convert to list in case INDIRECT_is_a is a generator
                                indirect_parents = list(cls.INDIRECT_is_a)
                                for inf_parent in indirect_parents:
                                    if (hasattr(inf_parent, 'name') and 
                                        inf_parent.name is not None and 
                                        inf_parent not in cls.is_a):
                                        
                                        inferred_axioms.append({
                                            "type": "InferredSubClassOf",
                                            "subject": cls.name,
                                            "object": inf_parent.name,
                                            "description": f"Inferred: {cls.name} is a subclass of {inf_parent.name}"
                                        })
                            except Exception as e:
                                inferred_axioms.append({
                                    "type": "Error",
                                    "subject": cls.name,
                                    "description": f"Error processing inferred parents: {str(e)}"
                                })
                except:
                    # If reasoning fails, just return empty inferred axioms
                    pass
        except Exception as e:
            # Add error information
            inferred_axioms.append({
                "type": "Error",
                "description": f"Error inferring axioms: {str(e)}"
            })
        
        return inferred_axioms
    
    def get_ontology_expressivity(self):
        """
        Determine the ontology expressivity (ALC, SHOIN, etc.).
        
        Returns:
            str: A string describing the ontology expressivity
        """
        # Default expressivity
        expressivity = "AL"  # Attributive Language (basic)
        
        # Check for additional expressivity features
        has_complement = False
        has_union = False
        has_full_existential = False
        has_cardinality = False
        has_inverse = False
        has_role_hierarchy = False
        has_nominals = False
        has_transitive = False
        has_datatype = False
        
        # Check classes for complex definitions
        for cls in self.onto.classes():
            if hasattr(cls, 'equivalent_to') and cls.equivalent_to:
                for equiv in cls.equivalent_to:
                    # Check for constructs in the class expression
                    expr_str = str(equiv)
                    if "Complement" in expr_str:
                        has_complement = True
                    if "Or" in expr_str:
                        has_union = True
                    if "some" in expr_str:
                        has_full_existential = True
                    if "min" in expr_str or "max" in expr_str or "exactly" in expr_str:
                        has_cardinality = True
                    if "Inverse" in expr_str:
                        has_inverse = True
        
        # Check for role hierarchy (subproperties)
        for prop in self.onto.object_properties():
            if hasattr(prop, 'is_a') and len(prop.is_a) > 1:
                has_role_hierarchy = True
                break
        
        # Check for nominals (enumerated classes or hasValue restrictions)
        if len(self.onto.individuals()) > 0:
            has_nominals = True
        
        # Check for transitive properties
        for prop in self.onto.object_properties():
            if hasattr(prop, 'transitive') and prop.transitive:
                has_transitive = True
                break
        
        # Check for data properties
        if len(self.onto.data_properties()) > 0:
            has_datatype = True
        
        # Build expressivity string
        if has_complement or has_union:
            expressivity += "C"  # Complex concept negation
        if has_full_existential:
            expressivity += "E"  # Full existential qualification
        if has_role_hierarchy:
            expressivity += "H"  # Role hierarchy
        if has_inverse:
            expressivity += "I"  # Inverse roles
        if has_nominals:
            expressivity += "O"  # Nominals/enumerations
        if has_cardinality:
            expressivity += "N"  # Cardinality restrictions
        if has_transitive:
            expressivity += "R+"  # Transitive roles
        if has_datatype:
            expressivity += "(D)"  # Data properties
        
        return expressivity
        
    def load_ontology_from_file(self, file_path):
        """
        Load an ontology from a file path.
        
        Args:
            file_path (str): Path to the OWL file
            
        Returns:
            bool: True if loaded successfully, False otherwise
        """
        try:
            # Load the ontology
            self.onto = get_ontology(file_path).load()
            self.ontology_source = os.path.basename(file_path)
            
            # Reset report data
            self.axioms = []
            self.inconsistencies = []
            self.inferred_axioms = []
            
            # Re-prepare the ontology
            self.prepare_ontology()
            return True
        except Exception as e:
            return False, str(e)
