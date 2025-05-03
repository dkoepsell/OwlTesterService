import re
import os
import nltk
import uuid
import owlready2
import logging
from owlready2 import *
from nltk.sem.logic import LogicalExpressionException
from nltk.sem import Expression
from openai_utils import generate_real_world_implications
from plantuml_generator import PlantUMLGenerator

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
        # Initialize flags for tracking the loading method
        self.is_rdflib_model = False
        self.is_xml_fallback = False
        self.is_rdf_xml_manual = False
        self.rdflib_graph = None
        self.ontology_iri = None
        self.subclass_relations = []
        
        # Initialize logical expressions reader
        self.read_expr = Expression.fromstring
        
        # Initialize report data
        self.axioms = []
        self.inconsistencies = []
        self.inferred_axioms = []
        
        # Load default BFO ontology if no custom path provided
        if ontology_path is None:
            try:
                self.onto = get_ontology("http://purl.obolibrary.org/obo/bfo.owl").load()
                self.ontology_source = "BFO (default)"
                # Prepare ontology for testing
                self.prepare_ontology()
            except Exception as e:
                print(f"Failed to load default BFO ontology: {str(e)}")
                # Fallback to empty ontology
                self.onto = None
                self.ontology_source = "Empty (failed to load BFO)"
                self.bfo_classes = []
                self.bfo_relations = []
        else:
            # Try to load the custom ontology using our robust method
            result = self.load_ontology_from_file(ontology_path)
            
            # Handle result
            if result is not True:
                # If loading failed and returned an error message
                if isinstance(result, tuple) and len(result) == 2 and not result[0]:
                    raise Exception(f"Failed to load ontology: {result[1]}")
                # If loading failed with an unknown result format
                elif result is not True:
                    raise Exception("Failed to load ontology for unknown reason")
    
    def prepare_ontology(self):
        """Prepare the ontology for testing by collecting classes and relations."""
        self.bfo_classes = []
        self.bfo_relations = []
        self.data_properties = []
        self.individuals = []
        self.annotation_properties = []
        
        try:
            # Collect classes - convert generator to list first
            ontology_classes = list(self.onto.classes())
            for c in ontology_classes:
                classname = c.name
                if classname is not None:
                    self.bfo_classes.append(classname)
        except Exception as e:
            print(f"Error collecting classes: {str(e)}")
        
        try:
            # Collect object properties (relations) - convert generator to list first
            obj_properties = list(self.onto.object_properties())
            for op in obj_properties:
                propname = op.name
                if propname is not None:
                    self.bfo_relations.append(propname)
        except Exception as e:
            print(f"Error collecting object properties: {str(e)}")
        
        try:
            # Collect data properties - convert generator to list first
            data_properties = list(self.onto.data_properties())
            for dp in data_properties:
                propname = dp.name
                if propname is not None:
                    self.data_properties.append(propname)
        except Exception as e:
            print(f"Error collecting data properties: {str(e)}")
        
        try:
            # Collect individuals - convert generator to list first
            indiv_list = list(self.onto.individuals())
            for i in indiv_list:
                indname = i.name
                if indname is not None:
                    self.individuals.append(indname)
        except Exception as e:
            print(f"Error collecting individuals: {str(e)}")
                
        try:
            # Collect annotation properties - convert generator to list first
            annot_properties = list(self.onto.annotation_properties())
            for ap in annot_properties:
                propname = ap.name
                if propname is not None:
                    self.annotation_properties.append(propname)
        except Exception as e:
            print(f"Error collecting annotation properties: {str(e)}")
    
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
        # Create case-insensitive lookup maps for BFO classes and relations
        lower_bfo_classes = {cls.lower(): cls for cls in self.bfo_classes}
        lower_bfo_relations = {rel.lower(): rel for rel in self.bfo_relations}
        
        for term in terms:
            # Skip variables and logical operators
            if term.islower() or term in ['and', 'or', 'not', 'implies', 'iff', 'exists', 'forall']:
                continue
                
            # Case-insensitive check for BFO classes
            if term.lower() in lower_bfo_classes:
                original_term = lower_bfo_classes[term.lower()]
                if original_term not in result["bfo_classes_used"]:
                    result["bfo_classes_used"].append(original_term)
                    if term != original_term:
                        result["issues"].append(f"Note: '{term}' was interpreted as BFO class '{original_term}'. Consider using the exact case.")
            # Case-insensitive check for BFO relations
            elif term.lower() in lower_bfo_relations:
                original_term = lower_bfo_relations[term.lower()]
                if original_term not in result["bfo_relations_used"]:
                    result["bfo_relations_used"].append(original_term)
                    if term != original_term:
                        result["issues"].append(f"Note: '{term}' was interpreted as BFO relation '{original_term}'. Consider using the exact case.")
            else:
                # Term not found even with case-insensitive matching
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
        # Handle differently based on if we're using RDFLib or Owlready2
        if self.is_rdflib_model:
            return self._analyze_ontology_rdflib()
        else:
            return self._analyze_ontology_owlready()
    
    def _analyze_ontology_rdflib(self):
        """
        Analyze the loaded ontology using RDFLib's limited capabilities.
        
        Returns:
            dict: A simplified report for RDFLib-parsed ontologies
        """
        # We can only do limited analysis with RDFLib
        # Create a simplified report based on the extracted information
        
        # For ontology IRI, use the one extracted during loading or a placeholder
        ontology_iri = self.ontology_iri or "Unknown (RDFLib parsing)"
        
        # Generate basic FOL premises from class and property info
        fol_premises = []
        
        # Generate premises for class hierarchy
        try:
            if self.rdflib_graph:
                # Extract subclass relationships if possible
                from rdflib import RDFS
                
                # Find subclass relationships
                for s, p, o in self.rdflib_graph.triples((None, RDFS.subClassOf, None)):
                    subclass = str(s).split('#')[-1] if '#' in str(s) else str(s).split('/')[-1]
                    superclass = str(o).split('#')[-1] if '#' in str(o) else str(o).split('/')[-1]
                    
                    # Add a simple FOL premise for subclass
                    fol_premises.append({
                        "type": "subclass",
                        "fol": f"forall x ({subclass}(x) -> {superclass}(x))",
                        "description": f"{subclass} is a subclass of {superclass}"
                    })
        except Exception as e:
            print(f"Error generating FOL premises for RDFLib model: {str(e)}")
        
        # Create report
        report = {
            "ontology_name": self.ontology_source,
            "ontology_iri": ontology_iri,
            "stats": {
                "class_count": len(self.bfo_classes),
                "object_property_count": len(self.bfo_relations),
                "data_property_count": 0,  # We don't extract these separately in RDFLib mode
                "individual_count": 0,     # We don't extract individuals in RDFLib mode
                "annotation_property_count": 0  # We don't extract annotation properties in RDFLib mode
            },
            "axioms": [],  # No detailed axioms available in RDFLib mode
            "consistency": {"consistent": True, "issues": ["Limited consistency checking in RDFLib mode"]},
            "inferred": [],  # No inference in RDFLib mode
            "fol_premises": fol_premises,
            "real_world_implications": []
        }
        
        # Add metrics
        report["metrics"] = {
            "expressivity": "Unknown (RDFLib parsing)",
            "complexity": len(self.bfo_classes) + len(self.bfo_relations)
        }
        
        return report
    
    def _analyze_ontology_owlready(self):
        """
        Analyze the loaded ontology using full Owlready2 capabilities.
        
        Returns:
            dict: A complete report for Owlready2-parsed ontologies
        """
        # Extract data first to ensure proper conversion of generators to lists
        axioms = self.extract_axioms()
        consistency = self.check_consistency()
        inferred_axioms = self.get_inferred_axioms()
        expressivity = self.get_ontology_expressivity()
        fol_premises = self.generate_fol_premises()
        
        # Ensure axioms and inferred_axioms are lists, not generators
        if not isinstance(axioms, list):
            axioms = list(axioms)
        if not isinstance(inferred_axioms, list):
            inferred_axioms = list(inferred_axioms)
        
        # Get the ontology IRI safely
        try:
            ontology_iri = str(self.onto.base_iri) if hasattr(self.onto, 'base_iri') else "Unknown"
        except:
            ontology_iri = "Unknown"
            
        report = {
            "ontology_name": self.ontology_source,
            "ontology_iri": ontology_iri,
            "stats": {
                "class_count": len(self.bfo_classes),
                "object_property_count": len(self.bfo_relations),
                "data_property_count": len(self.data_properties),
                "individual_count": len(self.individuals),
                "annotation_property_count": len(self.annotation_properties)
            },
            "axioms": axioms,
            "consistency": consistency,
            "inferred": inferred_axioms,
            "fol_premises": fol_premises,
            "real_world_implications": []
        }
        
        # Add additional metrics
        report["metrics"] = {
            "expressivity": expressivity,
            "complexity": len(axioms) + len(inferred_axioms)
        }
        
        return report
        
    def generate_fol_premises(self):
        """
        Generate First Order Logic (FOL) premises from the ontology axioms.
        
        Returns:
            list: A list of FOL premises as strings
        """
        fol_premises = []
        
        try:
            # Convert class hierarchies to FOL
            # SubClassOf(A, B) -> ∀x: A(x) → B(x)
            classes_list = list(self.onto.classes())
            for cls in classes_list:
                if cls.name is None:
                    continue
                
                try:
                    # Process subclasses
                    is_a_list = list(cls.is_a) if hasattr(cls, 'is_a') else []
                    for parent in is_a_list:
                        if hasattr(parent, 'name') and parent.name is not None:
                            fol_premises.append({
                                "type": "SubClassOf",
                                "fol": f"∀x: {cls.name}(x) → {parent.name}(x)",
                                "description": f"All instances of {cls.name} are also instances of {parent.name}"
                            })
                except Exception as e:
                    print(f"Error processing class {cls.name}: {str(e)}")
                
            # Convert object properties to FOL
            obj_properties = list(self.onto.object_properties())
            for prop in obj_properties:
                if prop.name is None:
                    continue
                
                try:
                    # Handle domain restrictions
                    # Domain(prop, C) -> ∀x,y: prop(x,y) → C(x)
                    if hasattr(prop, 'domain') and prop.domain:
                        domain_list = list(prop.domain) if hasattr(prop.domain, '__iter__') else []
                        for domain in domain_list:
                            if hasattr(domain, 'name') and domain.name is not None:
                                fol_premises.append({
                                    "type": "PropertyDomain",
                                    "fol": f"∀x,y: {prop.name}(x,y) → {domain.name}(x)",
                                    "description": f"If x relates to y via {prop.name}, then x is a {domain.name}"
                                })
                    
                    # Handle range restrictions
                    # Range(prop, C) -> ∀x,y: prop(x,y) → C(y)
                    if hasattr(prop, 'range') and prop.range:
                        range_list = list(prop.range) if hasattr(prop.range, '__iter__') else []
                        for range_cls in range_list:
                            if hasattr(range_cls, 'name') and range_cls.name is not None:
                                fol_premises.append({
                                    "type": "PropertyRange",
                                    "fol": f"∀x,y: {prop.name}(x,y) → {range_cls.name}(y)",
                                    "description": f"If x relates to y via {prop.name}, then y is a {range_cls.name}"
                                })
                    
                    # Handle property characteristics
                    if hasattr(prop, 'transitive') and prop.transitive:
                        fol_premises.append({
                            "type": "Transitive",
                            "fol": f"∀x,y,z: ({prop.name}(x,y) ∧ {prop.name}(y,z)) → {prop.name}(x,z)",
                            "description": f"Property {prop.name} is transitive"
                        })
                    
                    if hasattr(prop, 'symmetric') and prop.symmetric:
                        fol_premises.append({
                            "type": "Symmetric",
                            "fol": f"∀x,y: {prop.name}(x,y) → {prop.name}(y,x)",
                            "description": f"Property {prop.name} is symmetric"
                        })
                    
                    if hasattr(prop, 'functional') and prop.functional:
                        fol_premises.append({
                            "type": "Functional",
                            "fol": f"∀x,y,z: ({prop.name}(x,y) ∧ {prop.name}(x,z)) → y = z",
                            "description": f"Property {prop.name} is functional"
                        })
                except Exception as e:
                    print(f"Error processing property {prop.name}: {str(e)}")
            
            # Add disjoint class axioms
            # DisjointClasses(A, B) -> ∀x: ¬(A(x) ∧ B(x))
            for cls in classes_list:
                if cls.name is None:
                    continue
                
                try:
                    if hasattr(cls, 'disjoints'):
                        disjoints = list(cls.disjoints())
                        for disjoint in disjoints:
                            entities = list(disjoint.entities)
                            for entity in entities:
                                if entity != cls and hasattr(entity, 'name') and entity.name is not None:
                                    fol_premises.append({
                                        "type": "DisjointClasses",
                                        "fol": f"∀x: ¬({cls.name}(x) ∧ {entity.name}(x))",
                                        "description": f"No instance can be both a {cls.name} and a {entity.name}"
                                    })
                except Exception as e:
                    print(f"Error processing disjoints for {cls.name}: {str(e)}")
            
            # Handle equivalent classes
            # EquivalentClasses(A, B) -> ∀x: A(x) ↔ B(x)
            for cls in classes_list:
                if cls.name is None:
                    continue
                
                try:
                    if hasattr(cls, 'equivalent_to') and cls.equivalent_to:
                        equiv_list = list(cls.equivalent_to)
                        for equiv in equiv_list:
                            if hasattr(equiv, 'name') and equiv.name is not None:
                                fol_premises.append({
                                    "type": "EquivalentClasses",
                                    "fol": f"∀x: {cls.name}(x) ↔ {equiv.name}(x)",
                                    "description": f"A thing is a {cls.name} if and only if it is a {equiv.name}"
                                })
                except Exception as e:
                    print(f"Error processing equivalents for {cls.name}: {str(e)}")
                
        except Exception as e:
            fol_premises.append({
                "type": "Error",
                "fol": f"Error generating FOL premises: {str(e)}",
                "description": "An error occurred during FOL generation"
            })
            
        return fol_premises
    
    def extract_axioms(self):
        """
        Extract all axioms from the ontology.
        
        Returns:
            list: A list of axioms as dictionaries with their properties
        """
        axioms = []
        
        try:
            # Extract class axioms - convert to list first
            classes_list = list(self.onto.classes())
            for cls in classes_list:
                if cls.name is None:
                    continue
                    
                try:    
                    # Get subclass relationships
                    # Convert is_a to list in case it's a generator
                    is_a_list = list(cls.is_a) if hasattr(cls, 'is_a') else []
                    for parent in is_a_list:
                        if hasattr(parent, 'name') and parent.name is not None:
                            axioms.append({
                                "type": "SubClassOf",
                                "subject": cls.name,
                                "object": parent.name,
                                "description": f"{cls.name} is a subclass of {parent.name}"
                            })
                except Exception as e:
                    axioms.append({
                        "type": "Error",
                        "subject": cls.name,
                        "description": f"Error processing subclass relationships: {str(e)}"
                    })
                
                try:
                    # Get equivalent classes
                    if hasattr(cls, 'equivalent_to') and cls.equivalent_to:
                        # Convert equivalent_to to list in case it's a generator
                        equiv_list = list(cls.equivalent_to)
                        for equiv in equiv_list:
                            if hasattr(equiv, 'name') and equiv.name is not None:
                                axioms.append({
                                    "type": "EquivalentClasses",
                                    "subject": cls.name,
                                    "object": equiv.name,
                                    "description": f"{cls.name} is equivalent to {equiv.name}"
                                })
                except Exception as e:
                    axioms.append({
                        "type": "Error",
                        "subject": cls.name,
                        "description": f"Error processing equivalent classes: {str(e)}"
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
                    
        except Exception as e:
            # Add error information for entire classes extraction
            axioms.append({
                "type": "Error",
                "description": f"Error processing classes: {str(e)}"
            })
            
        try:
            # Extract property axioms - convert to list first
            object_properties = list(self.onto.object_properties())
            for prop in object_properties:
                if prop.name is None:
                    continue
                    
                try:
                    # Domain and range
                    if hasattr(prop, 'domain') and prop.domain:
                        # Convert domain to list in case it's a generator
                        domain_list = list(prop.domain) if hasattr(prop.domain, '__iter__') else []
                        for domain in domain_list:
                            if hasattr(domain, 'name') and domain.name is not None:
                                axioms.append({
                                    "type": "ObjectPropertyDomain",
                                    "subject": prop.name,
                                    "object": domain.name,
                                    "description": f"{prop.name} has domain {domain.name}"
                                })
                
                    if hasattr(prop, 'range') and prop.range:
                        # Convert range to list in case it's a generator
                        range_list = list(prop.range) if hasattr(prop.range, '__iter__') else []
                        for range_cls in range_list:
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
                except Exception as e:
                    axioms.append({
                        "type": "Error",
                        "subject": prop.name if hasattr(prop, 'name') else "Unknown property",
                        "description": f"Error processing property: {str(e)}"
                    })
                    
        except Exception as e:
            # Add error information for property extraction
            axioms.append({
                "type": "Error",
                "description": f"Error processing object properties: {str(e)}"
            })
            
        try:
            # Extract data property axioms - convert to list first
            data_properties = list(self.onto.data_properties())
            for prop in data_properties:
                if prop.name is None:
                    continue
                
                try:
                    # Domain
                    if hasattr(prop, 'domain') and prop.domain:
                        # Convert domain to list in case it's a generator
                        domain_list = list(prop.domain) if hasattr(prop.domain, '__iter__') else []
                        for domain in domain_list:
                            if hasattr(domain, 'name') and domain.name is not None:
                                axioms.append({
                                    "type": "DataPropertyDomain",
                                    "subject": prop.name,
                                    "object": domain.name,
                                    "description": f"{prop.name} has domain {domain.name}"
                                })
                
                    # Range (data property ranges are different)
                    if hasattr(prop, 'range') and prop.range:
                        # Convert range to list in case it's a generator
                        range_list = list(prop.range) if hasattr(prop.range, '__iter__') else []
                        for range_item in range_list:
                            range_name = str(range_item)
                            axioms.append({
                                "type": "DataPropertyRange",
                                "subject": prop.name,
                                "object": range_name,
                                "description": f"{prop.name} has range {range_name}"
                            })
                except Exception as e:
                    axioms.append({
                        "type": "Error",
                        "subject": prop.name if hasattr(prop, 'name') else "Unknown data property",
                        "description": f"Error processing data property: {str(e)}"
                    })
        except Exception as e:
            # Add error information for data property extraction
            axioms.append({
                "type": "Error",
                "description": f"Error processing data properties: {str(e)}"
            })
        
        try:
            # Extract individual axioms - convert to list first
            individuals = list(self.onto.individuals())
            for ind in individuals:
                if ind.name is None:
                    continue
                    
                try:
                    # Class assertions
                    is_a_list = list(ind.is_a) if hasattr(ind.is_a, '__iter__') else []
                    for cls in is_a_list:
                        if hasattr(cls, 'name') and cls.name is not None:
                            axioms.append({
                                "type": "ClassAssertion",
                                "subject": ind.name,
                                "object": cls.name,
                                "description": f"{ind.name} is an instance of {cls.name}"
                            })
                
                    # Object property assertions
                    obj_props = list(self.onto.object_properties())
                    for prop in obj_props:
                        if prop.name is None:
                            continue
                            
                        if hasattr(ind, prop.name):
                            values = getattr(ind, prop.name)
                            if values:
                                # Convert values to list in case it's a generator
                                values_list = list(values) if hasattr(values, '__iter__') else [values]
                                for val in values_list:
                                    if hasattr(val, 'name') and val.name is not None:
                                        axioms.append({
                                            "type": "ObjectPropertyAssertion",
                                            "subject": ind.name,
                                            "property": prop.name,
                                            "object": val.name,
                                            "description": f"{ind.name} {prop.name} {val.name}"
                                        })
                
                    # Data property assertions
                    data_props = list(self.onto.data_properties())
                    for prop in data_props:
                        if prop.name is None:
                            continue
                            
                        if hasattr(ind, prop.name):
                            values = getattr(ind, prop.name)
                            if values:
                                # Convert values to list in case it's a generator
                                values_list = list(values) if hasattr(values, '__iter__') else [values]
                                for val in values_list:
                                    axioms.append({
                                        "type": "DataPropertyAssertion",
                                        "subject": ind.name,
                                        "property": prop.name,
                                        "object": str(val),
                                        "description": f"{ind.name} {prop.name} {val}"
                                    })
                except Exception as e:
                    axioms.append({
                        "type": "Error",
                        "subject": ind.name if hasattr(ind, 'name') else "Unknown individual",
                        "description": f"Error processing individual: {str(e)}"
                    })
        except Exception as e:
            # Add error information for individual extraction
            axioms.append({
                "type": "Error",
                "description": f"Error processing individuals: {str(e)}"
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
            # Check if Java is available
            import shutil
            java_path = shutil.which('java')
            
            if not java_path:
                # Java is not available, provide a detailed message
                consistency_report["consistent"] = None  # None means we can't determine
                consistency_report["issues"].append(
                    "Cannot check consistency: Java is not installed. " +
                    "The Pellet reasoner requires Java to run consistency checks. " +
                    "This doesn't mean the ontology is inconsistent, just that we can't verify it."
                )
                return consistency_report
                
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
                        
        except Exception as e:
            # Handle the specific java not found error with a clearer message
            if "No such file or directory: 'java'" in str(e):
                consistency_report["consistent"] = None  # None means we can't determine
                consistency_report["issues"].append(
                    "Cannot check consistency: Java is not installed. " +
                    "The Pellet reasoner requires Java to run consistency checks. " +
                    "This doesn't mean the ontology is inconsistent, just that we can't verify it."
                )
            else:
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
            # Check if Java is available
            import shutil
            java_path = shutil.which('java')
            
            if not java_path:
                # Java is not available, provide a detailed message
                inferred_axioms.append({
                    "type": "Info",
                    "description": "Cannot infer axioms: Java is not installed. " +
                                 "The Pellet reasoner requires Java to run inference. " +
                                 "Basic axiom extraction will still work."
                })
                return inferred_axioms
            
            # Create a reasoner to infer axioms
            with self.onto:
                try:
                    # Run the reasoner with inference
                    sync_reasoner_pellet(infer_property_values=True,
                                        infer_data_property_values=True)
                    
                    # Extract inferred class subsumptions
                    classes_list = list(self.onto.classes())
                    for cls in classes_list:
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
                except Exception as e:
                    # If reasoning fails, provide more details
                    inferred_axioms.append({
                        "type": "Error",
                        "description": f"Error during reasoning: {str(e)}"
                    })
        except Exception as e:
            # Handle the specific java not found error with a clearer message
            if "No such file or directory: 'java'" in str(e):
                inferred_axioms.append({
                    "type": "Info",
                    "description": "Cannot infer axioms: Java is not installed. " +
                                 "The Pellet reasoner requires Java to run inference. " +
                                 "Basic axiom extraction will still work."
                })
            else:
                # Add error information
                inferred_axioms.append({
                    "type": "Error",
                    "description": f"Error inferring axioms: {str(e)}"
                })
        
        return inferred_axioms
    
    def generate_real_world_implications(self, num_implications=5):
        """
        Generate real-world implications based on the ontology's FOL premises.
        
        Args:
            num_implications (int): Number of implications to generate
            
        Returns:
            list: A list of dictionaries containing the generated implications
        """
        try:
            logging.info(f"Generating real-world implications for {self.ontology_source}")
            
            # Get FOL premises
            fol_premises = self.generate_fol_premises()
            
            # Extract domain classes (non-BFO classes) with their descriptions
            domain_classes = []
            
            try:
                # Get all classes
                classes_list = list(self.onto.classes())
                for cls in classes_list:
                    if cls.name is None:
                        continue
                        
                    # Skip BFO classes (typically have URIs with purl.obolibrary.org/obo/BFO)
                    if 'obo/BFO' in str(cls.iri):
                        continue
                    
                    # Get class description from comments/annotations if available
                    description = ""
                    if hasattr(cls, 'comment') and cls.comment:
                        try:
                            comment_list = list(cls.comment)
                            if comment_list:
                                description = comment_list[0]
                        except Exception:
                            pass
                    
                    domain_classes.append({
                        "name": cls.name,
                        "description": description or f"A type of {cls.name}"
                    })
            except Exception as e:
                logging.error(f"Error extracting domain classes: {str(e)}")
            
            # Generate implications using OpenAI
            implications = generate_real_world_implications(
                self.ontology_source, 
                domain_classes, 
                fol_premises,
                num_implications
            )
            
            return implications
            
        except Exception as e:
            logging.error(f"Error generating real-world implications: {str(e)}")
            return [{"error": str(e), "title": "Error generating implications"}]
            
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
        try:
            # Convert individuals to list first
            individuals = list(self.onto.individuals())
            if len(individuals) > 0:
                has_nominals = True
        except Exception:
            # Safely handle generator issues
            pass
        
        # Check for transitive properties
        for prop in self.onto.object_properties():
            if hasattr(prop, 'transitive') and prop.transitive:
                has_transitive = True
                break
        
        # Check for data properties
        try:
            # Convert data_properties to list first
            data_props = list(self.onto.data_properties())
            if len(data_props) > 0:
                has_datatype = True
        except Exception:
            # Safely handle generator issues
            pass
        
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
            bool or tuple: True if loaded successfully, or (False, error_message) if failed
        """
        # Store the file extension for reference throughout the method
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Track errors for better debugging
        all_errors = []
        
        # Method 1: Try loading with owlready2's standard mechanism
        try:
            # Determine file format based on extension
            if file_ext in ['.owx', '.own', '.ofn', '.ttl', '.rdf', '.xml']:
                # Special handling for OWL XML and other formats
                from owlready2 import World, onto_path
                
                # Create a new world for this ontology
                world = World()
                
                # Set the file path in the ontology search path
                onto_path.append(os.path.dirname(file_path))
                
                # Map extensions to format names
                format_map = {
                    '.owx': 'owlxml',
                    '.own': 'ntriples',
                    '.ofn': 'functional',
                    '.ttl': 'turtle',
                    '.rdf': 'rdfxml',
                    '.xml': 'rdfxml'
                }
                
                format_name = format_map.get(file_ext, None)
                
                # Try with explicit format if we have a mapping
                if format_name:
                    try:
                        self.onto = world.get_ontology(file_path).load(format=format_name)
                        print(f"Successfully loaded with format {format_name}")
                    except Exception as format_error:
                        all_errors.append(f"Error loading with format {format_name}: {str(format_error)}")
                        # If explicit format fails, try without specifying format
                        self.onto = world.get_ontology(file_path).load()
                        print("Successfully loaded without specifying format")
                else:
                    # Standard loading without format specification
                    self.onto = world.get_ontology(file_path).load()
                    print("Successfully loaded without format specification")
            else:
                # Standard loading for common formats
                self.onto = get_ontology(file_path).load()
                print("Successfully loaded with standard mechanism")
                
            self.ontology_source = os.path.basename(file_path)
            
            # Reset report data
            self.axioms = []
            self.inconsistencies = []
            self.inferred_axioms = []
            
            # Re-prepare the ontology
            self.prepare_ontology()
            return True
            
        except Exception as e:
            error_msg = f"Method 1 (owlready2) failed: {str(e)}"
            print(error_msg)
            all_errors.append(error_msg)
        
        # Method 2: Try using rdflib as an alternative for all file types
        try:
            import rdflib
            g = rdflib.Graph()
            
            # Determine the parser format based on extension
            rdflib_format_map = {
                '.owx': 'xml',
                '.own': 'nt',
                '.ofn': 'xml',  # Functional syntax might need special handling
                '.ttl': 'turtle',
                '.rdf': 'xml',
                '.xml': 'xml',
                '.owl': 'xml'
            }
            
            rdf_format = rdflib_format_map.get(file_ext, 'xml')
            
            # Try to parse the file
            print(f"Attempting RDFLib parsing with format: {rdf_format}")
            g.parse(file_path, format=rdf_format)
            
            # Extract basic ontology information
            self.ontology_source = os.path.basename(file_path)
            self.bfo_classes = []
            self.bfo_relations = []
            
            # Extract classes
            for s, p, o in g.triples((None, rdflib.RDF.type, rdflib.OWL.Class)):
                class_name = str(s).split('#')[-1] if '#' in str(s) else str(s).split('/')[-1]
                self.bfo_classes.append(str(class_name))
            
            # Extract object properties
            for s, p, o in g.triples((None, rdflib.RDF.type, rdflib.OWL.ObjectProperty)):
                prop_name = str(s).split('#')[-1] if '#' in str(s) else str(s).split('/')[-1]
                self.bfo_relations.append(str(prop_name))
            
            # Extract data properties
            for s, p, o in g.triples((None, rdflib.RDF.type, rdflib.OWL.DatatypeProperty)):
                prop_name = str(s).split('#')[-1] if '#' in str(s) else str(s).split('/')[-1]
                # Store in relations for simplicity
                self.bfo_relations.append(str(prop_name))
                
            # Get ontology IRI if possible
            ontology_iri = None
            for s, p, o in g.triples((None, rdflib.RDF.type, rdflib.OWL.Ontology)):
                ontology_iri = str(s)
                break
                
            # Reset report data
            self.axioms = []
            self.inconsistencies = []
            self.inferred_axioms = []
            
            print(f"Successfully used RDFLib parsing for {file_path}")
            print(f"Loaded {len(self.bfo_classes)} classes and {len(self.bfo_relations)} relations")
            
            # Store special flag to indicate this is a limited RDFLib-based model
            self.is_rdflib_model = True
            self.rdflib_graph = g
            self.ontology_iri = ontology_iri
            
            return True
                
        except ImportError as ie:
            error_msg = f"Method 2 (RDFLib) failed - not available: {str(ie)}"
            print(error_msg)
            all_errors.append(error_msg)
        except Exception as alt_e:
            error_msg = f"Method 2 (RDFLib) failed: {str(alt_e)}"
            print(error_msg)
            all_errors.append(error_msg)
        
        # Method 3: Try basic XML parsing as a last resort for XML-based formats
        if file_ext in ['.owx', '.rdf', '.xml', '.owl']:
            try:
                import xml.etree.ElementTree as ET
                
                print(f"Attempting basic XML parsing as last resort for {file_path}")
                
                # Initialize empty lists for storing extracted data
                self.ontology_source = os.path.basename(file_path)
                self.bfo_classes = []
                self.bfo_relations = []
                self.data_properties = []
                self.individuals = []
                self.annotation_properties = []
                
                # First, try to handle RDF/XML format which has a different structure
                try:
                    # Method 3a: Try manual RDF/XML parsing
                    with open(file_path, 'r') as file:
                        content = file.read()
                        
                    # Check if it's RDF/XML format by looking for key indicators
                    if '<rdf:RDF' in content and 'xmlns:rdf=' in content:
                        print("Detected RDF/XML format, using specialized RDF/XML parsing")
                        
                        # Extract all class definitions from rdf:about attributes
                        class_pattern = r'<owl:Class[^>]*rdf:about="([^"]+)"'
                        class_matches = re.findall(class_pattern, content)
                        for class_uri in class_matches:
                            class_name = class_uri.split('#')[-1] if '#' in class_uri else class_uri.split('/')[-1]
                            if class_name and class_name not in self.bfo_classes:
                                self.bfo_classes.append(class_name)
                        
                        # Extract object properties
                        obj_prop_pattern = r'<owl:ObjectProperty[^>]*rdf:about="([^"]+)"'
                        obj_prop_matches = re.findall(obj_prop_pattern, content)
                        for prop_uri in obj_prop_matches:
                            prop_name = prop_uri.split('#')[-1] if '#' in prop_uri else prop_uri.split('/')[-1]
                            if prop_name and prop_name not in self.bfo_relations:
                                self.bfo_relations.append(prop_name)
                        
                        # Extract individuals
                        individual_pattern = r'<owl:NamedIndividual[^>]*rdf:about="([^"]+)"'
                        individual_matches = re.findall(individual_pattern, content)
                        for indiv_uri in individual_matches:
                            indiv_name = indiv_uri.split('#')[-1] if '#' in indiv_uri else indiv_uri.split('/')[-1]
                            if indiv_name and indiv_name not in self.individuals:
                                self.individuals.append(indiv_name)
                        
                        # Extract ontology IRI
                        ontology_pattern = r'<owl:Ontology[^>]*rdf:about="([^"]+)"'
                        ontology_matches = re.findall(ontology_pattern, content)
                        if ontology_matches:
                            self.ontology_iri = ontology_matches[0]
                        
                        # Extract subclass relationships for hierarchy
                        subclass_pattern = r'<rdfs:subClassOf[^>]*rdf:resource="([^"]+)"'
                        subclass_matches = re.finditer(subclass_pattern, content)
                        subclass_relations = []
                        
                        for match in subclass_matches:
                            # Try to find the containing class element
                            pos = match.start()
                            class_start = content.rfind('<owl:Class', 0, pos)
                            class_end = content.find('>', class_start)
                            
                            if class_start >= 0 and class_end > class_start:
                                class_content = content[class_start:class_end+1]
                                # Extract the subclass (child)
                                about_match = re.search(r'rdf:about="([^"]+)"', class_content)
                                if about_match:
                                    child_uri = about_match.group(1)
                                    child_name = child_uri.split('#')[-1] if '#' in child_uri else child_uri.split('/')[-1]
                                    
                                    # Extract the superclass (parent)
                                    parent_uri = match.group(1)
                                    parent_name = parent_uri.split('#')[-1] if '#' in parent_uri else parent_uri.split('/')[-1]
                                    
                                    subclass_relations.append((child_name, parent_name))
                        
                        # Store subclass relationships for later use
                        self.subclass_relations = subclass_relations
                        
                        # Reset report data
                        self.axioms = []
                        self.inconsistencies = []
                        self.inferred_axioms = []
                        
                        print(f"Successfully used manual RDF/XML parsing for {file_path}")
                        print(f"Loaded {len(self.bfo_classes)} classes, {len(self.bfo_relations)} relations, and {len(self.individuals)} individuals")
                        
                        # Set flags for specialized RDF/XML parsing
                        self.is_rdflib_model = True  # We'll use the RDFLib model methods
                        self.is_xml_fallback = True
                        self.is_rdf_xml_manual = True
                        
                        return True
                
                except Exception as rdf_e:
                    print(f"Manual RDF/XML parsing failed, falling back to general XML parsing: {str(rdf_e)}")
                
                # Method 3b: Try general XML parsing if RDF/XML parsing failed
                # Parse the XML
                tree = ET.parse(file_path)
                root = tree.getroot()
                
                # Extract namespaces from root element attributes
                namespaces = {}
                for key, value in root.attrib.items():
                    if key.startswith('{http://www.w3.org/2000/xmlns/}') or key.startswith('xmlns:'):
                        prefix = key.split('}')[-1] if '}' in key else key.split(':')[-1]
                        namespaces[prefix] = value
                
                # Add known namespaces if not present
                if 'owl' not in namespaces:
                    namespaces['owl'] = 'http://www.w3.org/2002/07/owl#'
                if 'rdf' not in namespaces:
                    namespaces['rdf'] = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
                if 'rdfs' not in namespaces:
                    namespaces['rdfs'] = 'http://www.w3.org/2000/01/rdf-schema#'
                
                # Helper function to handle namespaces in tags
                def find_elements_with_namespace(element, tag_name, ns=None):
                    # Try with namespace first
                    if ns:
                        elements = element.findall(f".//{{{ns}}}{tag_name}")
                        if elements:
                            return elements
                    
                    # Try without namespace
                    elements = element.findall(f".//{tag_name}")
                    if elements:
                        return elements
                    
                    # Try every possible namespace in our map
                    for prefix, ns_uri in namespaces.items():
                        elements = element.findall(f".//{{{ns_uri}}}{tag_name}")
                        if elements:
                            return elements
                    
                    # Try every possible namespace combination in the document
                    for prefix in root.attrib.keys():
                        if prefix.startswith('{') and prefix.endswith('}'):
                            ns_uri = prefix[1:-1]
                            elements = element.findall(f".//{{{ns_uri}}}{tag_name}")
                            if elements:
                                return elements
                    
                    return []
                
                # Extract classes
                class_elements = find_elements_with_namespace(root, "Class", namespaces.get('owl'))
                for cls in class_elements:
                    # Try to get the IRI attribute
                    iri = cls.get('IRI') or cls.get('rdf:about') or cls.get(f"{{{namespaces.get('rdf')}}}about")
                    if iri:
                        class_name = iri.split('#')[-1] if '#' in iri else iri.split('/')[-1]
                        if class_name not in self.bfo_classes:
                            self.bfo_classes.append(class_name)
                
                # Extract object properties
                obj_prop_elements = find_elements_with_namespace(root, "ObjectProperty", namespaces.get('owl'))
                for prop in obj_prop_elements:
                    iri = prop.get('IRI') or prop.get('rdf:about') or prop.get(f"{{{namespaces.get('rdf')}}}about")
                    if iri:
                        prop_name = iri.split('#')[-1] if '#' in iri else iri.split('/')[-1]
                        if prop_name not in self.bfo_relations:
                            self.bfo_relations.append(prop_name)
                
                # Extract individuals
                indiv_elements = find_elements_with_namespace(root, "NamedIndividual", namespaces.get('owl'))
                for indiv in indiv_elements:
                    iri = indiv.get('IRI') or indiv.get('rdf:about') or indiv.get(f"{{{namespaces.get('rdf')}}}about")
                    if iri:
                        indiv_name = iri.split('#')[-1] if '#' in iri else iri.split('/')[-1]
                        if indiv_name not in self.individuals:
                            self.individuals.append(indiv_name)
                
                # Handle declarations - these might contain nested class definitions
                decl_elements = find_elements_with_namespace(root, "Declaration", namespaces.get('owl'))
                for decl in decl_elements:
                    # Look for Class declarations
                    cls_elements = find_elements_with_namespace(decl, "Class", namespaces.get('owl'))
                    for cls in cls_elements:
                        iri = cls.get('IRI') or cls.get('rdf:about') or cls.get(f"{{{namespaces.get('rdf')}}}about")
                        if iri:
                            class_name = iri.split('#')[-1] if '#' in iri else iri.split('/')[-1]
                            if class_name not in self.bfo_classes:
                                self.bfo_classes.append(class_name)
                    
                    # Look for ObjectProperty declarations
                    prop_elements = find_elements_with_namespace(decl, "ObjectProperty", namespaces.get('owl'))
                    for prop in prop_elements:
                        iri = prop.get('IRI') or prop.get('rdf:about') or prop.get(f"{{{namespaces.get('rdf')}}}about")
                        if iri:
                            prop_name = iri.split('#')[-1] if '#' in iri else iri.split('/')[-1]
                            if prop_name not in self.bfo_relations:
                                self.bfo_relations.append(prop_name)
                                
                    # Look for NamedIndividual declarations
                    indiv_elements = find_elements_with_namespace(decl, "NamedIndividual", namespaces.get('owl'))
                    for indiv in indiv_elements:
                        iri = indiv.get('IRI') or indiv.get('rdf:about') or indiv.get(f"{{{namespaces.get('rdf')}}}about")
                        if iri:
                            indiv_name = iri.split('#')[-1] if '#' in iri else iri.split('/')[-1]
                            if indiv_name not in self.individuals:
                                self.individuals.append(indiv_name)
                
                # Get ontology IRI if possible
                self.ontology_iri = None
                # Try to get the base attribute from the root Ontology element
                base = root.get('{http://www.w3.org/XML/1998/namespace}base')
                if base:
                    self.ontology_iri = base
                
                # Also check for Ontology elements
                ontology_elements = find_elements_with_namespace(root, "Ontology", namespaces.get('owl'))
                for onto in ontology_elements:
                    iri = onto.get('rdf:about') or onto.get(f"{{{namespaces.get('rdf')}}}about")
                    if iri:
                        self.ontology_iri = iri
                        break
                
                # Reset report data
                self.axioms = []
                self.inconsistencies = []
                self.inferred_axioms = []
                
                print(f"Successfully used XML fallback parsing for {file_path}")
                print(f"Loaded {len(self.bfo_classes)} classes, {len(self.bfo_relations)} relations, and {len(self.individuals)} individuals")
                
                # Set flag for XML fallback mode
                self.is_rdflib_model = True  # We'll use the RDFLib model methods since the capabilities are similar
                self.is_xml_fallback = True
                
                return True
                
            except ImportError as ie:
                error_msg = f"Method 3 (XML fallback) failed - XML parser not available: {str(ie)}"
                print(error_msg)
                all_errors.append(error_msg)
            except Exception as xml_e:
                error_msg = f"Method 3 (XML fallback) failed: {str(xml_e)}"
                print(error_msg)
                all_errors.append(error_msg)
        
        # If all methods failed, return False with error details
        return False, f"Failed to load ontology. Errors: {'; '.join(all_errors)}"
            
    def generate_uml_diagram(self, include_individuals=False, 
                           include_data_properties=True, include_annotation_properties=False,
                           max_classes=1000):
        """
        Generate PlantUML code for the loaded ontology.
        
        Args:
            include_individuals (bool): Whether to include individuals in the diagram
            include_data_properties (bool): Whether to include data properties
            include_annotation_properties (bool): Whether to include annotation properties
            max_classes (int): Maximum number of classes to include in the diagram (default: 1000)
            
        Returns:
            dict: PlantUML code generation result
        """
        # Handle differently based on if we're using RDFLib or Owlready2
        if self.is_rdflib_model:
            return self._generate_uml_diagram_rdflib(
                include_individuals=include_individuals,
                include_data_properties=include_data_properties,
                include_annotation_properties=include_annotation_properties,
                max_classes=max_classes
            )
        else:
            return self._generate_uml_diagram_owlready(
                include_individuals=include_individuals,
                include_data_properties=include_data_properties,
                include_annotation_properties=include_annotation_properties,
                max_classes=max_classes
            )
            
    def _generate_uml_diagram_owlready(self, include_individuals=False,
                                      include_data_properties=True, 
                                      include_annotation_properties=False,
                                      max_classes=1000):
        """
        Generate PlantUML code for an Owlready2-loaded ontology.
        
        Returns:
            dict: PlantUML code generation result
        """
        try:
            # Initialize the PlantUML generator
            generator = PlantUMLGenerator()
            
            # Generate only the PlantUML code
            plantuml_code = generator._generate_plantuml_code(
                self.onto,
                include_individuals=include_individuals,
                include_data_properties=include_data_properties,
                include_annotation_properties=include_annotation_properties,
                max_classes=max_classes
            )
            
            # Return just the PlantUML code in a success response
            return {
                "plantuml_code": plantuml_code,
                "success": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "plantuml_code": None
            }
            
    def _generate_uml_diagram_rdflib(self, include_individuals=False,
                                    include_data_properties=True, 
                                    include_annotation_properties=False,
                                    max_classes=1000):
        """
        Generate a simple PlantUML diagram for an RDFLib-parsed ontology.
        
        Returns:
            dict: PlantUML code generation result
        """
        try:
            # We'll generate a simple PlantUML diagram directly from the extracted RDFLib data
            from rdflib import RDFS, RDF, OWL
            
            # Start the PlantUML code
            plantuml_code = "@startuml\n\n"
            plantuml_code += "' PlantUML diagram generated from RDFLib parsing\n"
            plantuml_code += "' Limited representation based on extracted classes and properties\n\n"
            plantuml_code += "skinparam class {\n"
            plantuml_code += "    BackgroundColor white\n"
            plantuml_code += "    ArrowColor black\n"
            plantuml_code += "    BorderColor black\n"
            plantuml_code += "}\n\n"
            
            # Add classes
            class_count = 0
            added_classes = set()
            for cls_name in self.bfo_classes:
                if class_count >= max_classes:
                    break
                
                # Clean the class name for PlantUML
                clean_name = cls_name.replace(' ', '_').replace('-', '_')
                if clean_name in added_classes:
                    continue
                    
                plantuml_code += f"class \"{cls_name}\" as {clean_name}\n"
                added_classes.add(clean_name)
                class_count += 1
            
            # Add class hierarchy
            if self.rdflib_graph:
                for s, p, o in self.rdflib_graph.triples((None, RDFS.subClassOf, None)):
                    if isinstance(o, str) or not o.startswith(str(OWL.NS)):  # Skip OWL built-ins
                        subclass = str(s).split('#')[-1] if '#' in str(s) else str(s).split('/')[-1]
                        superclass = str(o).split('#')[-1] if '#' in str(o) else str(o).split('/')[-1]
                        
                        # Clean names for PlantUML
                        clean_subclass = subclass.replace(' ', '_').replace('-', '_')
                        clean_superclass = superclass.replace(' ', '_').replace('-', '_')
                        
                        if clean_subclass in added_classes and clean_superclass in added_classes:
                            plantuml_code += f"{clean_subclass} --|> {clean_superclass}\n"
            
            # Add object properties as associations
            for prop_name in self.bfo_relations:
                # Clean the property name for PlantUML
                clean_name = prop_name.replace(' ', '_').replace('-', '_')
                
                # Try to find domain and range if available
                found_domain_range = False
                if self.rdflib_graph:
                    for s, p, o in self.rdflib_graph.triples((None, RDF.type, OWL.ObjectProperty)):
                        prop_uri = str(s)
                        prop_local = prop_uri.split('#')[-1] if '#' in prop_uri else prop_uri.split('/')[-1]
                        
                        if prop_local == prop_name:
                            # Find domain
                            domain_class = None
                            for _, _, d in self.rdflib_graph.triples((s, RDFS.domain, None)):
                                domain_uri = str(d)
                                domain_local = domain_uri.split('#')[-1] if '#' in domain_uri else domain_uri.split('/')[-1]
                                domain_class = domain_local.replace(' ', '_').replace('-', '_')
                                if domain_class not in added_classes:
                                    domain_class = None
                                break
                            
                            # Find range
                            range_class = None
                            for _, _, r in self.rdflib_graph.triples((s, RDFS.range, None)):
                                range_uri = str(r)
                                range_local = range_uri.split('#')[-1] if '#' in range_uri else range_uri.split('/')[-1]
                                range_class = range_local.replace(' ', '_').replace('-', '_')
                                if range_class not in added_classes:
                                    range_class = None
                                break
                            
                            # Add the relationship if domain and range were found
                            if domain_class and range_class:
                                plantuml_code += f"{domain_class} --> {range_class} : {prop_name}\n"
                                found_domain_range = True
                
                # If we couldn't find domain/range, just list the property
                if not found_domain_range:
                    plantuml_code += f"note \"Object Property: {prop_name}\" as note_{clean_name}\n"
            
            # Close the diagram
            plantuml_code += "\n@enduml"
            
            return {
                "plantuml_code": plantuml_code,
                "success": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error generating RDFLib diagram: {str(e)}",
                "plantuml_code": None
            }
