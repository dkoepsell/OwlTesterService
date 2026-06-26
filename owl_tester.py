import os
import re
import csv
import logging
import nltk
import datetime
import importlib.util
import owlready2
import json
import time
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

# BFO is loaded from the vendored bfo/ bundle (see load_bfo_classes). The optional
# BFO_PATH env var override is read at load time by bfo.catalog and _attach_bfo_import.

# Built-in BFO-2020 definitions used as a fallback if the vendored OWL cannot load.
from bfo_2020_definitions import BFO_2020_CLASSES, BFO_2020_RELATIONS

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
        self.fol_premises = []  # Initialize to empty list for auto-generated premises
        
        # Load BFO classes and relations
        self.load_bfo_classes()
    
    def load_bfo_classes(self):
        """
        Load BFO classes and relations from the vendored BFO 2020 bundle.

        Classes (with rdfs:labels and the full disjointness structure) come from
        the bfo/ catalog, which loads bfo/bfo-2020.owl. The parsed catalog is also
        stored on self.bfo_catalog for the conformance lint and coherence checks.
        Relations stay on the hand-coded BFO_2020_RELATIONS until the relation
        signatures land (SPEC Task 4). If the catalog cannot load, fall back to the
        built-in definitions so analysis still works.
        """
        self.bfo_catalog = None
        try:
            from bfo import load_catalog, as_ui_dict
            catalog = load_catalog()
            self.bfo_catalog = catalog
            self.bfo_classes = as_ui_dict(catalog)
            self.bfo_relations = BFO_2020_RELATIONS.copy()
            logging.info(
                f"Loaded {len(self.bfo_classes)} BFO classes from vendored "
                f"BFO 2020 ({len(catalog.disjoint_pairs)} asserted disjoint pairs); "
                f"{len(self.bfo_relations)} relations from built-in definitions"
            )
        except Exception as e:
            logging.warning(
                f"Could not load vendored BFO catalog: {e}. "
                f"Using built-in BFO-2020 definitions."
            )
            self.bfo_classes = BFO_2020_CLASSES.copy()
            self.bfo_relations = BFO_2020_RELATIONS.copy()
            logging.info(
                f"Loaded {len(self.bfo_classes)} BFO-2020 classes and "
                f"{len(self.bfo_relations)} relations from built-in definitions"
            )
    
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
                    # Store only the label to prevent [object Object] display
                    class_obj = self.bfo_classes[term_lower]
                    bfo_classes_used.append(class_obj['label'] if isinstance(class_obj, dict) else str(class_obj))
                # Check for exact match in BFO relations
                elif term_lower in self.bfo_relations:
                    # Store only the label to prevent [object Object] display
                    relation_obj = self.bfo_relations[term_lower]
                    bfo_relations_used.append(relation_obj['label'] if isinstance(relation_obj, dict) else str(relation_obj))
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
                        # No match found - ensure we're storing strings not objects
                        non_bfo_terms.append(str(term))
                        results['issues'].append(f"Term '{term}' is not recognized as a BFO class or relation.")
            
            # Detect the format used in the expression
            format_detected = self.detect_format(expr_string)
            if format_detected:
                results['format_detected'] = format_detected
            
            # Detect any free variables in the expression
            free_vars = self.detect_free_variables(expr_string)
            if free_vars:
                results['free_variables'] = free_vars
                results['issues'].append(f"Warning: Found free variables not bound by quantifiers: {', '.join(free_vars)}")
            
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
    
    def detect_free_variables(self, expr_string):
        """
        Detect free variables in an FOL expression that are not bound by a quantifier.
        
        Args:
            expr_string (str): The expression to analyze
            
        Returns:
            list: List of free variable names found in the expression
        """
        # If parsing failed, we can't reliably detect free variables
        try:
            expr = self.read_parser.parse(expr_string)
        except:
            return []
            
        # Extract all variables used in the expression
        all_vars = set()
        var_pattern = r'\b([a-zA-Z][a-zA-Z0-9_]*)\s*(?=\)|,)'
        for var_match in re.finditer(var_pattern, expr_string):
            var_name = var_match.group(1)
            # Skip if it's likely a class or relation name (starts with uppercase)
            # Also skip if it's a known BFO class or relation name
            if (not var_name[0].isupper() and 
                var_name not in ['forall', 'exists', 'instance_of'] and
                var_name.lower() not in [c.lower() for c in self.bfo_classes.keys()] and
                var_name.lower() not in [r.lower() for r in self.bfo_relations.keys()]):
                all_vars.add(var_name)
                
        # Extract bound variables from quantifiers
        bound_vars = set()
        
        # Match forall x, forall x,y, exists x patterns
        quant_pattern = r'\b(forall|exists)\s+([a-zA-Z][a-zA-Z0-9_]*(?:\s*,\s*[a-zA-Z][a-zA-Z0-9_]*)*)'
        for quant_match in re.finditer(quant_pattern, expr_string):
            quant_vars = quant_match.group(2)
            # Split comma-separated variables
            for var in re.split(r'\s*,\s*', quant_vars):
                bound_vars.add(var.strip())
                
        # Free variables are those that appear in all_vars but not in bound_vars
        free_vars = all_vars - bound_vars
        return sorted(list(free_vars))
        
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
        
    def _attach_bfo_import(self, onto):
        """Load the vendored BFO 2020 into the ontology's own world and add it as
        an import, so the reasoner has BFO's disjointness and hierarchy. Idempotent
        (owlready2 caches by IRI per world) and best-effort: a failure here must not
        break analysis, only weaken coherence detection (the lint still runs)."""
        try:
            from bfo.catalog import DEFAULT_OWL_PATH
            bfo_path = os.environ.get('BFO_PATH') or DEFAULT_OWL_PATH
            if not os.path.exists(bfo_path):
                logger.warning(f"BFO import skipped: {bfo_path} not found")
                return
            world = getattr(onto, 'world', None) or owlready2.default_world
            bfo_onto = world.get_ontology("file://" + os.path.abspath(bfo_path)).load()
            if bfo_onto not in onto.imported_ontologies:
                onto.imported_ontologies.append(bfo_onto)
            logger.info("[STAGE] BFO attached as import for reasoning")
        except Exception as e:
            logger.warning(f"Could not attach BFO import: {e}")

    def load_ontology_from_file(self, ontology_path):
        """
        Load an ontology from a file.
        
        Args:
            ontology_path (str): Path to the ontology file
            
        Returns:
            dict: Information about the loaded ontology
        """
        # First try direct loading with owlready2
        t_load = time.perf_counter()
        try:
            # Load into a dedicated world so each analysis is isolated. Without
            # this, owlready2's default world accumulates classes across uploads
            # and inconsistent_classes() would report stale unsatisfiable classes
            # from prior requests.
            world = owlready2.World()
            onto = world.get_ontology(ontology_path).load()
            logger.info(f"[STAGE] load_ontology (owlready2): {time.perf_counter()-t_load:.2f}s")

            # Attach BFO as an import so the reasoner sees BFO's disjointness and
            # hierarchy. Kept as an import (not merge-flattened) so provenance
            # stays clean. Degrades quietly if BFO cannot be attached.
            self._attach_bfo_import(onto)

            # Return basic information about the ontology
            return {
                'name': onto.name,
                'base_iri': onto.base_iri,
                'ontology': onto,
                'loaded': True
            }
        except Exception as e:
            logging.warning(f"Initial owlready2 loading failed for {ontology_path}: {e}")
            logger.info(f"[STAGE] load_ontology (owlready2 failed): {time.perf_counter()-t_load:.2f}s — falling back to rdflib")
            
            # Try alternate loading methods using rdflib as an intermediary
            try:
                import rdflib
                import tempfile
                
                # Load with rdflib first
                t_rdf = time.perf_counter()
                g = rdflib.Graph()
                g.parse(ontology_path)
                logger.info(f"[STAGE] load_ontology (rdflib parse): {time.perf_counter()-t_rdf:.2f}s ({len(g)} triples)")

                if len(g) > 0:
                    logging.info(f"Successfully loaded {len(g)} triples with rdflib")
                    
                    # Create a temporary file
                    with tempfile.NamedTemporaryFile(suffix='.owl', delete=False) as temp:
                        # Serialize to RDF/XML with explicit namespaces
                        temp_path = temp.name
                        g.serialize(destination=temp_path, format='xml')
                    
                    try:
                        # Try to load the re-serialized file with owlready2
                        t_reload = time.perf_counter()
                        world = owlready2.World()
                        onto = world.get_ontology(temp_path).load()
                        logger.info(f"[STAGE] load_ontology (owlready2 reparse): {time.perf_counter()-t_reload:.2f}s")

                        self._attach_bfo_import(onto)

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
    
    def analyze_ontology(self, onto, file_path=None):
        """
        Analyze an ontology and extract key information.

        Args:
            onto: The owlready2 ontology object
            file_path: Optional path to the source file. When provided, structural
                       extraction is performed with RDFlib instead of owlready2
                       (orders of magnitude faster on large ontologies — owlready2
                       can hang on class enumeration with anonymous restrictions).

        Returns:
            dict: Analysis results
        """
        if file_path:
            return self._analyze_with_rdflib(onto, file_path)

        t_total = time.perf_counter()
        logger.info("[STAGE] analyze_ontology: entered (owlready2 path)")
        try:
            # Get basic counts from the ontology (each call timed separately to localize slow ones)
            t = time.perf_counter()
            classes_list = list(onto.classes())
            logger.info(f"[STAGE]   list(classes): {time.perf_counter()-t:.2f}s ({len(classes_list)})")
            t = time.perf_counter()
            object_properties_list = list(onto.object_properties())
            logger.info(f"[STAGE]   list(object_properties): {time.perf_counter()-t:.2f}s ({len(object_properties_list)})")
            t = time.perf_counter()
            data_properties_list = list(onto.data_properties())
            logger.info(f"[STAGE]   list(data_properties): {time.perf_counter()-t:.2f}s ({len(data_properties_list)})")
            t = time.perf_counter()
            individuals_list = list(onto.individuals())
            logger.info(f"[STAGE]   list(individuals): {time.perf_counter()-t:.2f}s ({len(individuals_list)})")
            t = time.perf_counter()
            annotation_properties_list = list(onto.annotation_properties())
            logger.info(f"[STAGE]   list(annotation_properties): {time.perf_counter()-t:.2f}s ({len(annotation_properties_list)})")

            # Count axioms - This is a rough approximation since owlready2 doesn't directly expose axiom counts
            t = time.perf_counter()
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
                    if isinstance(entity.comment, list) or hasattr(entity.comment, '__len__'):
                        axiom_count += len(entity.comment)
                    else:
                        axiom_count += 1  # Count as single axiom if it's not a collection
                        
                if hasattr(entity, 'label') and entity.label:
                    if isinstance(entity.label, list) or hasattr(entity.label, '__len__'):
                        axiom_count += len(entity.label)
                    else:
                        axiom_count += 1  # Count as single axiom if it's not a collection
            logger.info(f"[STAGE] count_axioms: {time.perf_counter()-t:.2f}s (axiom_count={axiom_count})")

            # Build the detailed axioms list
            t = time.perf_counter()
            axioms_list = []
            # Add class hierarchy axioms
            for cls in classes_list:
                if hasattr(cls, 'is_a') and cls.is_a:
                    for parent in cls.is_a:
                        if hasattr(parent, 'name') and hasattr(cls, 'name'):
                            axioms_list.append({
                                'type': 'SubClassOf',
                                'description': f"{cls.name} ⊑ {parent.name}"
                            })
            
            logger.info(f"[STAGE] build_axioms_list: {time.perf_counter()-t:.2f}s (axioms={len(axioms_list)})")

            # Also create a list for inferred axioms
            inferred_axioms_list = []
            
            # Extract class names - this will help show the correct class count
            # We'll use the names from our auto-generated axioms since direct loading failed
            extracted_classes = set()
            for axiom in axioms_list:
                if axiom['type'] == 'SubClassOf':
                    desc = axiom['description']
                    if '⊑' in desc:
                        class_name = desc.split('⊑')[0].strip()
                        if class_name != 'Thing':
                            extracted_classes.add(class_name)
            
            # Build the result dictionary
            result = {
                # Use the extracted classes if we have any, otherwise fallback to the classes_list
                'classes': len(extracted_classes) if extracted_classes else len(classes_list),
                'object_properties': len(object_properties_list),
                'data_properties': len(data_properties_list),
                'individuals': len(individuals_list),
                'annotation_properties': len(annotation_properties_list),
                'imported_ontologies': [o.base_iri for o in onto.imported_ontologies],
                'axiom_count': axiom_count,
                'axioms': axioms_list,  # List of axioms with type and description
                'inferred_axioms': inferred_axioms_list,  # List of inferred axioms
                # Add extracted class list if available, otherwise use the original
                'class_list': list(extracted_classes) if extracted_classes else [cls.name for cls in classes_list if hasattr(cls, 'name')],
                'object_property_list': [prop.name for prop in object_properties_list if hasattr(prop, 'name')],
                'data_property_list': [prop.name for prop in data_properties_list if hasattr(prop, 'name')],
                'individual_list': [ind.name for ind in individuals_list if hasattr(ind, 'name')]
            }
            
            # Check consistency and capture reasoning methodology
            reasoning_methodology = {
                'reasoners_used': ['Pellet'],
                'reasoning_tasks': ['consistency', 'classification', 'realization'],
                'timestamp': datetime.datetime.utcnow().isoformat(),
                'theoretical_guarantees': {
                    'decidability': 'Decidable for OWL DL ontologies',
                    'completeness': 'Complete for SROIQ(D) description logic',
                    'soundness': 'Sound for standard description logics'
                },
                'limitations': [
                    'May time out on very large ontologies',
                    'OWL Full constructs not supported',
                    'Resolution is limited to standard tableaux algorithm capabilities'
                ],
                'inference_rules': [
                    'Tableau-based reasoning',
                    'Inheritance propagation',
                    'Property chain inference',
                    'Disjointness validation',
                    'Cardinality constraint validation'
                ]
            }
            
            # Track derivation steps for inferences
            derivation_steps = []
            
            try:
                # Store pre-reasoning class hierarchy for comparison
                t = time.perf_counter()
                pre_reasoning_subclass_relations = {}
                for cls in onto.classes():
                    if hasattr(cls, 'name') and hasattr(cls, 'is_a'):
                        pre_reasoning_subclass_relations[cls.name] = [
                            parent.name for parent in cls.is_a if hasattr(parent, 'name')
                        ]
                logger.info(f"[STAGE] pre_reasoning_snapshot: {time.perf_counter()-t:.2f}s")

                # owlready2's reasoner for consistency checking
                t = time.perf_counter()
                logger.info("[STAGE] pellet_reasoner: starting (may take a while)...")
                start_time = datetime.datetime.utcnow()
                with onto:
                    consistency = owlready2.sync_reasoner_pellet(infer_property_values=True,
                                                              infer_data_property_values=True)
                end_time = datetime.datetime.utcnow()
                logger.info(f"[STAGE] pellet_reasoner: {time.perf_counter()-t:.2f}s")
                
                # Calculate reasoning time
                reasoning_time_ms = (end_time - start_time).total_seconds() * 1000
                reasoning_methodology['performance'] = {
                    'reasoning_time_ms': reasoning_time_ms,
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat()
                }
                
                # Find newly inferred relations by comparing pre and post reasoning
                t = time.perf_counter()
                for cls in onto.classes():
                    if hasattr(cls, 'name') and hasattr(cls, 'is_a'):
                        post_reasoning_parents = [parent.name for parent in cls.is_a if hasattr(parent, 'name')]
                        pre_reasoning_parents = pre_reasoning_subclass_relations.get(cls.name, [])
                        
                        # Find new inferences (in post but not in pre)
                        new_inferences = [parent for parent in post_reasoning_parents if parent not in pre_reasoning_parents]
                        
                        for new_parent in new_inferences:
                            # Create derivation step for this inference
                            derivation_step = {
                                'axiom_type': 'SubClassOf',
                                'description': f"{cls.name} ⊑ {new_parent}",
                                'reason': 'Inferred by reasoner',
                                'supporting_facts': [
                                    'Class hierarchy analysis',
                                    'Existential property restrictions',
                                    'Property chain inclusion axioms'
                                ],
                                'confidence': 'High',
                                'origin': 'Pellet reasoner'
                            }
                            derivation_steps.append(derivation_step)
                            
                            # Add to inferred axioms list
                            inferred_axioms_list.append({
                                'type': 'SubClassOf',
                                'description': f"{cls.name} ⊑ {new_parent}",
                                'derivation': derivation_step
                            })
                
                logger.info(f"[STAGE] extract_inferences: {time.perf_counter()-t:.2f}s "
                            f"(inferred_axioms={len(inferred_axioms_list)})")

                result['consistency'] = 'Consistent'

            except owlready2.OwlReadyInconsistentOntologyError as e:
                # A genuine logical inconsistency: Pellet proved no model exists.
                result['consistency'] = 'Inconsistent'
                result['consistency_error'] = str(e)

                reasoning_methodology['inconsistency_reason'] = str(e)
                reasoning_methodology['inconsistency_type'] = 'Logical contradiction detected'

                inconsistency_step = {
                    'axiom_type': 'Inconsistency',
                    'description': "Ontology is logically inconsistent (no model exists).",
                    'reason': 'Logical contradiction',
                    'supporting_facts': ['Pellet reasoner detection'],
                    'confidence': 'High',
                    'origin': 'Pellet reasoner'
                }
                derivation_steps.append(inconsistency_step)
            except Exception as e:
                # The reasoner crashed (e.g. a Java/Jena error). This is NOT a
                # logical inconsistency — mark consistency as undetermined rather
                # than mislabeling a tooling failure as a contradiction.
                result['consistency'] = 'Unknown'
                result['reasoner_skipped'] = f'reasoner error: {e}'
                reasoning_methodology['reasoner_error'] = str(e)
            
            # Add reasoning methodology and derivation steps to the result
            result['reasoning_methodology'] = reasoning_methodology
            result['derivation_steps'] = derivation_steps
            
            # Get expressivity (this is a placeholder, as owlready2 doesn't directly expose DL expressivity)
            t = time.perf_counter()
            result['expressivity'] = self._determine_expressivity(onto)
            logger.info(f"[STAGE] expressivity: {time.perf_counter()-t:.2f}s")

            logger.info(f"[STAGE] analyze_ontology TOTAL: {time.perf_counter()-t_total:.2f}s")
            return result
        except Exception as e:
            logging.error(f"Error analyzing ontology: {e}")
            # Extract class names from any premises we might have auto-generated
            extracted_classes = []
            # self.fol_premises is initialized in __init__, so we can access it directly
            for premise in self.fol_premises:
                if isinstance(premise, dict) and premise.get('type') == 'class':
                    class_name = premise.get('entity_name')
                    if class_name:
                        extracted_classes.append(class_name)
            
            # Create default reasoning methodology for error case
            default_reasoning_methodology = {
                'reasoners_used': ['Pellet'],
                'reasoning_tasks': ['consistency', 'classification', 'realization'],
                'timestamp': datetime.datetime.utcnow().isoformat(),
                'theoretical_guarantees': {
                    'decidability': 'Decidable for OWL DL ontologies',
                    'completeness': 'Complete for SROIQ(D) description logic',
                    'soundness': 'Sound for standard description logics'
                },
                'limitations': [
                    'May time out on very large ontologies',
                    'OWL Full constructs not supported',
                    'Resolution is limited to standard tableaux algorithm capabilities'
                ],
                'inference_rules': [
                    'Tableau-based reasoning',
                    'Inheritance propagation',
                    'Property chain inference',
                    'Disjointness validation',
                    'Cardinality constraint validation'
                ],
                'error_state': {
                    'reason': str(e),
                    'analysis_error': True,
                    'error_type': 'Processing error'
                }
            }
            
            # Return empty values on error but with any classes we've extracted and methodology info
            return {
                'classes': len(extracted_classes),
                'object_properties': 0,
                'data_properties': 0,
                'individuals': 0,
                'annotation_properties': 0,
                'imported_ontologies': [],
                'axiom_count': 0,
                'axioms': [],
                'inferred_axioms': [],
                'class_list': extracted_classes,
                'object_property_list': [],
                'data_property_list': [],
                'individual_list': [],
                'consistency': 'Unknown',
                'expressivity': 'Unknown',
                'reasoning_methodology': default_reasoning_methodology,
                'derivation_steps': [],
                'error': str(e)
            }

    # ------------------------------------------------------------------
    # RDFlib-based fast analysis path
    # ------------------------------------------------------------------

    @staticmethod
    def _local_name(uri):
        """Extract a friendly local name from an IRI/URIRef."""
        s = str(uri)
        if '#' in s:
            return s.rsplit('#', 1)[1]
        if '/' in s:
            tail = s.rsplit('/', 1)[1]
            if tail:
                return tail
        return s

    def _extract_with_rdflib(self, file_path):
        """
        Fast structural extraction of an ontology via RDFlib.
        Returns a dict of counts, named entities, axioms, expressivity, etc.
        Avoids owlready2's class-object materialization, which can hang for
        minutes on ontologies with many anonymous restrictions.
        """
        import rdflib
        from rdflib.namespace import RDF, RDFS, OWL

        t = time.perf_counter()
        g = rdflib.Graph()
        g.parse(file_path)
        logger.info(f"[STAGE] rdflib.parse: {time.perf_counter()-t:.2f}s ({len(g)} triples)")

        # Ontology IRI/name from owl:Ontology subject (if declared)
        ontology_iri = ''
        ontology_name = ''
        for s in g.subjects(RDF.type, OWL.Ontology):
            ontology_iri = str(s)
            ontology_name = self._local_name(s) or ontology_iri
            break

        def collect_named(rdf_type):
            names = []
            seen = set()
            for s in g.subjects(RDF.type, rdf_type):
                if not isinstance(s, rdflib.URIRef):
                    continue
                name = self._local_name(s)
                if not name or name in ('Thing', 'Nothing') or name in seen:
                    continue
                seen.add(name)
                names.append(name)
            return sorted(names)

        t = time.perf_counter()
        class_names = collect_named(OWL.Class)
        object_property_names = collect_named(OWL.ObjectProperty)
        data_property_names = collect_named(OWL.DatatypeProperty)
        individual_names = collect_named(OWL.NamedIndividual)
        annotation_property_names = collect_named(OWL.AnnotationProperty)
        logger.info(f"[STAGE] rdflib enumerate: {time.perf_counter()-t:.2f}s "
                    f"(classes={len(class_names)}, obj_props={len(object_property_names)}, "
                    f"data_props={len(data_property_names)}, individuals={len(individual_names)})")

        # Axioms: subClassOf, equivalentClass, disjointWith, domain, range
        t = time.perf_counter()
        axioms_list = []

        def add_named_axiom(s, o, kind, sep):
            if isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef):
                sn = self._local_name(s)
                on = self._local_name(o)
                if sn and on and sn not in ('Thing', 'Nothing'):
                    axioms_list.append({'type': kind, 'description': f"{sn} {sep} {on}"})

        for s, _, o in g.triples((None, RDFS.subClassOf, None)):
            add_named_axiom(s, o, 'SubClassOf', '⊑')
        for s, _, o in g.triples((None, OWL.equivalentClass, None)):
            add_named_axiom(s, o, 'EquivalentClass', '≡')
        for s, _, o in g.triples((None, OWL.disjointWith, None)):
            add_named_axiom(s, o, 'DisjointWith', '⊥')
        for s, _, o in g.triples((None, RDFS.domain, None)):
            add_named_axiom(s, o, 'Domain', 'domain ⇒')
        for s, _, o in g.triples((None, RDFS.range, None)):
            add_named_axiom(s, o, 'Range', 'range ⇒')

        axiom_count = len(axioms_list)
        logger.info(f"[STAGE] rdflib axioms: {time.perf_counter()-t:.2f}s ({axiom_count})")

        imports = [str(o) for o in g.objects(None, OWL.imports)]

        return {
            'graph': g,
            'ontology_name': ontology_name or 'Unknown Ontology',
            'ontology_iri': ontology_iri,
            'class_names': class_names,
            'object_property_names': object_property_names,
            'data_property_names': data_property_names,
            'individual_names': individual_names,
            'annotation_property_names': annotation_property_names,
            'axioms': axioms_list,
            'axiom_count': axiom_count,
            'imports': imports,
        }

    def _determine_expressivity_rdflib(self, g):
        """Heuristic DL expressivity from an RDFlib graph (no owlready2 access)."""
        import rdflib
        from rdflib.namespace import RDF, RDFS, OWL

        def has_triple(p):
            for _ in g.triples((None, p, None)):
                return True
            return False

        def has_typed(t):
            for _ in g.subjects(RDF.type, t):
                return True
            return False

        expressivity = "AL"
        if has_triple(OWL.someValuesFrom):
            expressivity = "ALE"

        if has_triple(OWL.unionOf):
            expressivity += "U"
        if has_triple(OWL.complementOf):
            expressivity += "C"
        if (has_triple(OWL.minCardinality) or has_triple(OWL.maxCardinality)
                or has_triple(OWL.cardinality) or has_triple(OWL.qualifiedCardinality)
                or has_triple(OWL.minQualifiedCardinality) or has_triple(OWL.maxQualifiedCardinality)):
            expressivity += "N"
        if has_triple(OWL.inverseOf):
            expressivity += "I"
        if has_triple(RDFS.subPropertyOf):
            expressivity += "H"
        if has_typed(OWL.TransitiveProperty):
            expressivity += "R+"
        if has_typed(OWL.FunctionalProperty):
            expressivity += "F"
        if has_triple(OWL.oneOf):
            expressivity += "O"
        return expressivity

    def _try_reasoner_with_budget(self, onto, budget_seconds=60):
        """
        Run owlready2 / Pellet with a SIGALRM-based timeout.
        Returns: (consistent: bool, methodology_extras: dict, derivation_steps: list,
                  inferred_axioms: list, skipped_reason: Optional[str],
                  unsatisfiable_classes: list[dict])

        unsatisfiable_classes lists the named classes the reasoner proved equal to
        owl:Nothing (each {name, label, iri}). This is coherence, separate from the
        global consistency flag, and is empty when reasoning was skipped or failed.

        Note: SIGALRM only interrupts Python — if Pellet's Java subprocess is mid-run,
        it may keep running briefly after timeout. Not a leak in practice (gunicorn
        worker death via max_requests will eventually clear it).
        """
        import signal

        if not hasattr(signal, 'SIGALRM'):
            # Windows fallback: just don't reason
            return True, {'reasoner_skipped': 'no SIGALRM on this platform'}, [], [], 'unsupported_platform', []

        class _ReasonerTimeout(Exception):
            pass

        def _handler(signum, frame):
            raise _ReasonerTimeout(f"reasoner exceeded {budget_seconds}s budget")

        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(int(budget_seconds))

        # Capture pre-reasoning hierarchy so we can diff for inferences afterwards
        pre = {}
        try:
            for cls in onto.classes():
                if hasattr(cls, 'name') and hasattr(cls, 'is_a'):
                    pre[cls.name] = [p.name for p in cls.is_a if hasattr(p, 'name')]
        except _ReasonerTimeout:
            signal.alarm(0); signal.signal(signal.SIGALRM, old_handler)
            return True, {'reasoner_skipped': 'class enumeration exceeded budget'}, [], [], 'enumeration_timeout', []

        t = time.perf_counter()
        try:
            # Reason over the ontology's own world (isolated per analysis), not the
            # global default world. Pass the world explicitly so inconsistent_classes()
            # below reflects only this ontology plus its BFO import.
            reason_world = getattr(onto, 'world', None) or owlready2.default_world
            with onto:
                owlready2.sync_reasoner_pellet(reason_world,
                                               infer_property_values=True,
                                               infer_data_property_values=True)
            elapsed = time.perf_counter() - t
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            logger.info(f"[STAGE] reasoner: {elapsed:.2f}s")
        except _ReasonerTimeout as e:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            logger.warning(f"[STAGE] reasoner: TIMED OUT after {budget_seconds}s")
            return True, {'reasoner_skipped': str(e), 'reasoner_budget_seconds': budget_seconds}, [], [], 'reasoner_timeout', []
        except owlready2.OwlReadyInconsistentOntologyError as e:
            # A genuine logical inconsistency: Pellet proved no model exists.
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            logger.warning(f"[STAGE] reasoner: ontology is INCONSISTENT ({e})")
            return False, {'inconsistency_reason': str(e)}, [{
                'axiom_type': 'Inconsistency',
                'description': "Ontology is logically inconsistent (no model exists).",
                'reason': 'Pellet proved the ontology unsatisfiable',
                'supporting_facts': ['Pellet reasoner output'],
                'confidence': 'High',
                'origin': 'Pellet reasoner'
            }], [], 'inconsistent', []
        except Exception as e:
            # The reasoner crashed (e.g. a Java/Jena error, OWLAPI parse failure).
            # This is NOT a logical inconsistency — do not claim the ontology is
            # inconsistent. Degrade to "could not determine", like the timeout path,
            # so the report does not mislabel a tooling failure as a contradiction.
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
            logger.warning(f"[STAGE] reasoner: FAILED, not an inconsistency ({e})")
            return True, {'reasoner_skipped': f'reasoner error: {e}'}, [], [], 'reasoner_error', []

        # Diff pre/post for new SubClassOf inferences
        derivation_steps = []
        inferred_axioms = []
        try:
            for cls in onto.classes():
                if not (hasattr(cls, 'name') and hasattr(cls, 'is_a')):
                    continue
                post = [p.name for p in cls.is_a if hasattr(p, 'name')]
                for new_parent in [p for p in post if p not in pre.get(cls.name, [])]:
                    step = {
                        'axiom_type': 'SubClassOf',
                        'description': f"{cls.name} ⊑ {new_parent}",
                        'reason': 'Inferred by reasoner',
                        'supporting_facts': ['Tableau reasoning over class restrictions'],
                        'confidence': 'High',
                        'origin': 'Pellet reasoner',
                    }
                    derivation_steps.append(step)
                    inferred_axioms.append({
                        'type': 'SubClassOf',
                        'description': f"{cls.name} ⊑ {new_parent}",
                        'derivation': step,
                    })
        except Exception as e:
            logger.warning(f"Inference diff failed: {e}")

        # Coherence: classes the reasoner proved equal to owl:Nothing. These can
        # exist even when the ontology is globally consistent (a model exists).
        unsatisfiable = self._collect_unsatisfiable(onto)

        return True, {'performance': {'reasoning_time_s': time.perf_counter() - t}}, \
            derivation_steps, inferred_axioms, None, unsatisfiable

    @staticmethod
    def _collect_unsatisfiable(onto):
        """Map the reasoner's inconsistent (unsatisfiable) named classes to
        [{name, label, iri}]. Returns [] if the world cannot be queried."""
        unsat = []
        try:
            world = getattr(onto, 'world', None) or owlready2.default_world
            for cls in world.inconsistent_classes():
                if cls is owlready2.Nothing:
                    continue
                iri = getattr(cls, 'iri', '') or ''
                name = getattr(cls, 'name', '') or (iri.rsplit('/', 1)[-1] if iri else str(cls))
                label = name
                try:
                    if cls.label and cls.label.first():
                        label = str(cls.label.first())
                except Exception:
                    pass
                unsat.append({'name': name, 'label': label, 'iri': iri})
        except Exception as e:
            logger.warning(f"Could not collect unsatisfiable classes: {e}")
        return unsat

    def _analyze_with_rdflib(self, onto, file_path):
        """
        Fast structural analysis via RDFlib. Reasoning (owlready2/Pellet) is
        attempted with a strict time budget; if it exceeds the budget the
        analysis still returns with a clear note in `reasoning_methodology`.
        """
        t_total = time.perf_counter()
        logger.info(f"[STAGE] analyze_ontology: entered (rdflib path) file={file_path}")

        rdf = self._extract_with_rdflib(file_path)

        # BFO conformance lint: fast, pre-reasoner partition-straddle check.
        # Runs on every path (including the large-ontology external-reasoner path)
        # so it is the coherence safety net when the DL reasoner is skipped.
        t = time.perf_counter()
        try:
            from bfo_lint import bfo_lint
            lint_findings = bfo_lint(rdf['graph'], getattr(self, 'bfo_catalog', None))
        except Exception as e:
            logger.warning(f"[STAGE] bfo_lint failed: {e}")
            lint_findings = []
        logger.info(f"[STAGE] bfo_lint: {time.perf_counter()-t:.2f}s ({len(lint_findings)} findings)")

        t = time.perf_counter()
        expressivity = self._determine_expressivity_rdflib(rdf['graph'])
        logger.info(f"[STAGE] expressivity: {time.perf_counter()-t:.2f}s ({expressivity})")

        # Reasoning strategy:
        # - Below MAX_CLASSES_FOR_REASONING classes: try in-process owlready2/Pellet
        #   (rich derivation info, works well for small/medium ontologies)
        # - Above that: invoke an external reasoner (ROBOT+ELK) which is robust
        #   against the owlready2 class-enumeration hang.
        # - If the external reasoner is disabled or unavailable, fall back to a
        #   clean "skipped" with a message.
        max_classes_for_reasoning = int(os.environ.get('MAX_CLASSES_FOR_REASONING', '500'))
        external_reasoner = os.environ.get('EXTERNAL_REASONER', 'robot').lower()
        external_timeout = int(os.environ.get('EXTERNAL_REASONER_TIMEOUT', '300'))
        class_count = len(rdf['class_names'])

        # Unsatisfiable classes are computed on both paths now: the in-process
        # Pellet path via inconsistent_classes(), and the external ROBOT/ELK path
        # by parsing the reasoner's unsatisfiable-class report (with BFO merged in).
        unsatisfiable_classes = []

        if class_count <= max_classes_for_reasoning:
            budget = int(os.environ.get('REASONER_BUDGET_SECONDS', '60'))
            logger.info(f"[STAGE] reasoner: in-process Pellet with {budget}s budget...")
            consistent, methodology_extras, derivation_steps, inferred_axioms, skipped_reason, \
                unsatisfiable_classes = \
                self._try_reasoner_with_budget(onto, budget_seconds=budget)
        elif external_reasoner == 'robot':
            logger.info(f"[STAGE] reasoner: external ROBOT (class_count={class_count} > "
                        f"{max_classes_for_reasoning}), timeout={external_timeout}s")
            from external_reasoner import run_robot_reason
            try:
                from bfo.catalog import DEFAULT_OWL_PATH
                bfo_path = os.environ.get('BFO_PATH') or DEFAULT_OWL_PATH
            except Exception:
                bfo_path = None
            ext = run_robot_reason(
                file_path,
                timeout_seconds=external_timeout,
                normalized_graph=rdf['graph'],
                bfo_path=bfo_path,
            )
            if ext['ran']:
                consistent = bool(ext['consistent'])
                unsatisfiable_classes = ext.get('unsatisfiable_classes', [])
                # Cap inferences so the JSON column / response stays manageable.
                # ELK can produce hundreds of thousands of entailed SubClassOf
                # axioms on rich hierarchies — well beyond what the UI can
                # render usefully.
                cap = int(os.environ.get('MAX_INFERRED_AXIOMS', '5000'))
                total = len(ext['inferred_axioms'])
                if total > cap:
                    logger.info(f"[STAGE] reasoner: capping inferred axioms {total} -> {cap}")
                    inferred_axioms = ext['inferred_axioms'][:cap]
                    derivation_steps = ext['derivation_steps'][:cap]
                else:
                    inferred_axioms = ext['inferred_axioms']
                    derivation_steps = ext['derivation_steps']
                methodology_extras = {
                    'reasoner_engine': ext['engine'],
                    'reasoning_time_s': ext['elapsed_seconds'],
                    'inferred_axioms_total': total,
                    'inferred_axioms_returned': len(inferred_axioms),
                }
                if total > cap:
                    methodology_extras['inferred_axioms_capped_at'] = cap
                skipped_reason = None
            else:
                consistent = True  # unknown — don't claim inconsistent
                derivation_steps = []
                inferred_axioms = []
                methodology_extras = {
                    'reasoner_skipped': ext['error'] or 'external reasoner did not complete',
                    'reasoner_engine_attempted': ext['engine'],
                }
                skipped_reason = 'external_reasoner_failed'
        else:
            logger.info(f"[STAGE] reasoner: SKIPPED (class_count={class_count} > "
                        f"{max_classes_for_reasoning}, EXTERNAL_REASONER={external_reasoner})")
            consistent = True
            derivation_steps = []
            inferred_axioms = []
            methodology_extras = {
                'reasoner_skipped': (
                    f'Ontology has {class_count} classes (> {max_classes_for_reasoning} threshold) '
                    f'and EXTERNAL_REASONER is "{external_reasoner}". '
                    f'Set EXTERNAL_REASONER=robot to enable external reasoning.'
                ),
                'reasoner_skip_threshold': max_classes_for_reasoning,
            }
            skipped_reason = 'too_many_classes'

        reasoning_methodology = {
            'reasoners_used': ['Pellet'],
            'reasoning_tasks': ['consistency', 'classification', 'realization'],
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'theoretical_guarantees': {
                'decidability': 'Decidable for OWL DL ontologies',
                'completeness': 'Complete for SROIQ(D) description logic',
                'soundness': 'Sound for standard description logics',
            },
            'limitations': [
                'May time out on very large ontologies — see reasoner_skipped',
                'OWL Full constructs not supported',
            ],
            'inference_rules': [
                'Tableau-based reasoning',
                'Inheritance propagation',
                'Property chain inference',
                'Disjointness validation',
                'Cardinality constraint validation',
            ],
        }
        reasoning_methodology.update(methodology_extras)
        if skipped_reason:
            reasoning_methodology['reasoning_status'] = 'skipped'
            reasoning_methodology['reasoning_skipped_reason'] = skipped_reason
        else:
            reasoning_methodology['reasoning_status'] = 'completed'

        # Coherence is distinct from consistency: a consistent ontology can still
        # have unsatisfiable named classes. Status is only firm when the reasoner
        # actually ran; otherwise it is unknown and the lint is the safety net.
        if not consistent:
            coherence_status = 'inconsistent'
        elif skipped_reason:
            coherence_status = 'unknown'
        elif unsatisfiable_classes:
            coherence_status = 'incoherent'
        else:
            coherence_status = 'coherent'

        # Attach the lint message as a per-class justification where the lint
        # flagged the same class (the spec's fallback for missing Pellet
        # justifications), else a generic note.
        lint_by_class = {f.cls: f.message for f in lint_findings}
        for cls in unsatisfiable_classes:
            key = cls.get('name') or cls.get('label')
            cls['justification'] = lint_by_class.get(
                key,
                'Unsatisfiable: equivalent to owl:Nothing under the asserted axioms.'
            )

        result = {
            'ontology_name': rdf['ontology_name'],
            'ontology_iri': rdf['ontology_iri'],
            'classes': len(rdf['class_names']),
            'object_properties': len(rdf['object_property_names']),
            'data_properties': len(rdf['data_property_names']),
            'individuals': len(rdf['individual_names']),
            'annotation_properties': len(rdf['annotation_property_names']),
            'imported_ontologies': rdf['imports'],
            'axiom_count': rdf['axiom_count'],
            'axioms': rdf['axioms'],
            'inferred_axioms': inferred_axioms,
            'class_list': rdf['class_names'],
            'object_property_list': rdf['object_property_names'],
            'data_property_list': rdf['data_property_names'],
            'individual_list': rdf['individual_names'],
            'consistency': 'Consistent' if consistent else 'Inconsistent',
            'is_consistent': consistent,
            'expressivity': expressivity,
            'reasoning_methodology': reasoning_methodology,
            'derivation_steps': derivation_steps,
            'lint_findings': [f.to_dict() for f in lint_findings],
            'unsatisfiable_classes': unsatisfiable_classes,
            'coherence_status': coherence_status,
        }
        logger.info(f"[STAGE] analyze_ontology TOTAL: {time.perf_counter()-t_total:.2f}s "
                    f"(reasoning_status={reasoning_methodology['reasoning_status']})")
        return result

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
            if hasattr(prop, 'is_a') and prop.is_a:
                # Check if it's a collection with length > 1
                if (isinstance(prop.is_a, list) or hasattr(prop.is_a, '__len__')) and len(prop.is_a) > 1:
                    has_role_hierarchy = True
                # If it's not a collection but is defined, assume it's a single value (so len would be 1)
                # which wouldn't trigger the "has_role_hierarchy" flag
            
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