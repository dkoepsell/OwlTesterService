import os
import logging
import uuid
import datetime
import base64
import re
import typing
from typing import Optional, List, Dict, Any, Union, Tuple

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
from html import escape
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, session, make_response, Response
from werkzeug.utils import secure_filename
# We'll use urllib for URL parsing instead of werkzeug
from urllib.parse import urlparse
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, EmailField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from owl_tester import OwlTester
from models import db, User, OntologyFile, OntologyAnalysis, FOLExpression, SandboxOntology, OntologyClass, OntologyProperty, OntologyIndividual
# Import from improved OpenAI utils to avoid hanging issues
from improved_openai_utils import suggest_ontology_classes, suggest_ontology_properties, suggest_bfo_category, generate_class_description  
from openai_utils import generate_real_world_implications
# Import the preprocess_expression function for handling comma-separated quantifiers
from owl_preprocessor import preprocess_expression
from bvss_model import extract_bvss_graph

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key-for-development")

# Add custom Jinja filters
@app.template_filter('b64encode')
def b64encode_filter(s):
    """Filter to base64 encode a string for PlantUML URLs"""
    if isinstance(s, str):
        return base64.b64encode(s.encode('utf-8')).decode('utf-8')
    return s

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///owl_tester.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Initialize database
db.init_app(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # type: ignore
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Configure file uploads
app.config['UPLOADED_OWLS_DEST'] = os.path.join(app.root_path, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'owl', 'rdf', 'xml', 'ttl', 'n3', 'nt', 'ofn', 'own', 'owx'}

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOADED_OWLS_DEST']):
    os.makedirs(app.config['UPLOADED_OWLS_DEST'])

# Helper function to check if a file has an allowed extension
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Create database tables
with app.app_context():
    db.create_all()
    logger.info("Database tables created")

# Create Authentication Forms
class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Log In')
    
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = EmailField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')
    
    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Please use a different username.')
            
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('Please use a different email address.')

# Initialize OwlTester
owl_tester = OwlTester()
app.logger.info("Initializing OwlTester...")

# Home page
@app.route('/')
def index():
    """Render the main page."""
    # Get latest FOL expression from session if it exists
    last_expression = session.get('last_expression', '')
    
    # Get any messages/errors from session
    message = session.pop('message', None)
    error = session.pop('error', None)
    
    detected_format = session.pop('detected_format', None)
    
    # Get BFO classes and relations for display
    bfo_class_dict = owl_tester.get_bfo_classes()
    bfo_relation_dict = owl_tester.get_bfo_relations()
    
    # Convert dictionaries to lists of objects with label and id properties
    bfo_classes = []
    for key, value in bfo_class_dict.items():
        # If value is already a dict with 'label', use it; otherwise, create a dict
        if isinstance(value, dict) and 'label' in value:
            class_obj = {'label': value['label'], 'id': key}
            bfo_classes.append(class_obj)
        else:
            bfo_classes.append({'label': key, 'id': key})
    
    bfo_relations = []
    for key, value in bfo_relation_dict.items():
        # If value is already a dict with 'label', use it; otherwise, create a dict
        if isinstance(value, dict) and 'label' in value:
            relation_obj = {'label': value['label'], 'id': key}
            bfo_relations.append(relation_obj)
        else:
            bfo_relations.append({'label': key, 'id': key})
    
    return render_template('index.html', 
                          expression=last_expression, 
                          message=message, 
                          error=error,
                          detected_format=detected_format,
                          bfo_classes=bfo_classes,
                          bfo_relations=bfo_relations)

# About page
@app.route('/about')
def about():
    """Render the about page with information about FOL-BFO-OWL testing."""
    return render_template('about.html')

# API Endpoints
@app.route('/api/test-expression', methods=['POST'])
def test_expression():
    """API endpoint to test a FOL expression."""
    try:
        data = request.get_json()
        if not data or 'expression' not in data:
            return jsonify({'error': 'No expression provided'}), 400
        
        expression = data['expression']
        
        # Check if expression was provided
        if not expression or not expression.strip():
            return jsonify({'error': 'No expression provided'}), 400
        
        # Preprocess the expression and get the detected format
        try:
            expression, detected_format = preprocess_expression(expression)
        except Exception as e:
            app.logger.error(f"Error preprocessing expression: {str(e)}")
            # If there's an error, just use the original expression and no format
            detected_format = None
        
        # Store the expression in session
        session['last_expression'] = expression
        session['detected_format'] = detected_format
        
        # Test the expression
        result = owl_tester.test_expression(expression)
        
        # Add the detected format to the result if available
        if detected_format and 'format_detected' not in result:
            result['format_detected'] = detected_format
        
        # Log the expression and result for debugging
        app.logger.info(f"Tested expression: {expression}")
        app.logger.info(f"Result: {result}")
        
        # Save the test results to database
        if current_user.is_authenticated:
            user_id = current_user.id
        else:
            user_id = None
            
        fol_expr = FOLExpression(
            expression=expression,
            is_valid=result.get('valid', False),
            test_results=result.get('results'),
            issues=result.get('issues'),
            bfo_classes_used=result.get('bfo_classes_used'),
            bfo_relations_used=result.get('bfo_relations_used'),
            non_bfo_terms=result.get('non_bfo_terms'),
            user_id=user_id
        )
        
        db.session.add(fol_expr)
        db.session.commit()
        app.logger.info(f"Saved FOL expression test results to database with ID {fol_expr.id}")
        
        return jsonify(result)
        
    except Exception as e:
        app.logger.error(f"Error testing expression: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-bfo-display')
def test_bfo_display():
    """Test page for displaying BFO classes and relations."""
    return render_template('test_bfo_display.html')

@app.route('/fol-syntax-guide')
def fol_syntax_guide():
    """Documentation page for FOL syntax rules."""
    return render_template('fol_syntax_guide.html')

@app.route('/api/get-bfo-classes')
def get_bfo_classes():
    """API endpoint to get all BFO classes."""
    try:
        bfo_classes = owl_tester.get_bfo_classes()
        return jsonify({
            'classes': bfo_classes
        })
    except Exception as e:
        app.logger.error(f"Error getting BFO classes: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-bfo-relations')
def get_bfo_relations():
    """API endpoint to get all BFO relations."""
    try:
        bfo_relations = owl_tester.get_bfo_relations()
        return jsonify({
            'relations': bfo_relations
        })
    except Exception as e:
        app.logger.error(f"Error getting BFO relations: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/<analysis_id>/validate-completeness')
def validate_ontology_completeness(analysis_id):
    """
    Validate the completeness of an ontology by checking if all elements are included in FOL premises.
    
    Returns detailed report about missing classes, properties, and individuals.
    """
    try:
        analysis = OntologyAnalysis.query.get_or_404(analysis_id)
        ontology_file = OntologyFile.query.get_or_404(analysis.ontology_file_id)
        
        # Create an OwlTester instance
        tester = OwlTester()
        
        # Load the ontology file
        result = tester.load_ontology_from_file(ontology_file.file_path)
        
        if isinstance(result, dict) and not result.get('loaded', False):
            # If load_ontology_from_file returns a dictionary with loaded=False
            error_msg = result.get('error', 'Unknown error')
            return jsonify({'error': f"Failed to load ontology: {error_msg}"}), 500
        
        # Get the ontology object from the result
        onto = None
        if isinstance(result, dict) and 'ontology' in result:
            onto = result.get('ontology')
        
        if not onto:
            return jsonify({'error': "Loaded ontology object not found in result"}), 500
        
        # Get all classes, properties, and individuals from the ontology
        all_classes = list(onto.classes())
        all_object_properties = list(onto.object_properties())
        all_data_properties = list(onto.data_properties())
        all_individuals = list(onto.individuals())
        
        # Get the FOL premises from the analysis
        fol_premises = analysis.fol_premises or []
        
        # Check which classes, properties, and individuals are not included in the FOL premises
        missing_classes = []
        for cls in all_classes:
            if hasattr(cls, 'name') and cls.name:
                # Check if the class appears in any premise
                found = False
                for premise in fol_premises:
                    if cls.name in premise:
                        found = True
                        break
                
                if not found:
                    missing_classes.append({
                        'name': cls.name,
                        'iri': str(cls.iri) if hasattr(cls, 'iri') else None
                    })
        
        missing_properties = []
        for prop in all_object_properties + all_data_properties:
            if hasattr(prop, 'name') and prop.name:
                # Check if the property appears in any premise
                found = False
                for premise in fol_premises:
                    if prop.name in premise:
                        found = True
                        break
                
                if not found:
                    missing_properties.append({
                        'name': prop.name,
                        'iri': str(prop.iri) if hasattr(prop, 'iri') else None,
                        'type': 'object_property' if prop in all_object_properties else 'data_property'
                    })
        
        missing_individuals = []
        for ind in all_individuals:
            if hasattr(ind, 'name') and ind.name:
                # Check if the individual appears in any premise
                found = False
                for premise in fol_premises:
                    if ind.name in premise:
                        found = True
                        break
                
                if not found:
                    missing_individuals.append({
                        'name': ind.name,
                        'iri': str(ind.iri) if hasattr(ind, 'iri') else None
                    })
        
        # Return the completeness report
        return jsonify({
            'complete': len(missing_classes) == 0 and len(missing_properties) == 0 and len(missing_individuals) == 0,
            'missing_classes': missing_classes,
            'missing_properties': missing_properties,
            'missing_individuals': missing_individuals,
            'total_classes': len(all_classes),
            'total_object_properties': len(all_object_properties),
            'total_data_properties': len(all_data_properties),
            'total_individuals': len(all_individuals),
            'total_premises': len(fol_premises)
        })
        
    except Exception as e:
        app.logger.error(f"Error validating ontology completeness: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analysis/<analysis_id>/check-enhanced-consistency')
def check_enhanced_consistency(analysis_id):
    """
    Perform enhanced consistency checking using multiple reasoners.
    
    Returns detailed report about contradictions and problematic axioms.
    """
    try:
        analysis = OntologyAnalysis.query.get_or_404(analysis_id)
        ontology_file = OntologyFile.query.get_or_404(analysis.ontology_file_id)
        
        # Create an OwlTester instance
        tester = OwlTester()
        
        # Load the ontology file
        result = tester.load_ontology_from_file(ontology_file.file_path)
        
        if isinstance(result, dict) and not result.get('loaded', False):
            # If load_ontology_from_file returns a dictionary with loaded=False
            error_msg = result.get('error', 'Unknown error')
            return jsonify({'error': f"Failed to load ontology: {error_msg}"}), 500
        
        # Get the ontology object from the result
        onto = None
        if isinstance(result, dict) and 'ontology' in result:
            onto = result.get('ontology')
        
        if not onto:
            return jsonify({'error': "Loaded ontology object not found in result"}), 500
        
        # Perform enhanced consistency checking
        # For now, we'll just return a simple result
        # In the future, this could integrate with multiple reasoners
        is_consistent = True
        issues = []
        
        if analysis.consistency_issues and len(analysis.consistency_issues) > 0:
            is_consistent = False
            issues = analysis.consistency_issues
        
        # Return the consistency report
        return jsonify({
            'is_consistent': is_consistent,
            'issues': issues,
            'reasoners_used': ['HermiT'],  # For future expansion
            'ontology_name': analysis.ontology_name
        })
        
    except Exception as e:
        app.logger.error(f"Error checking enhanced consistency: {str(e)}")
        return jsonify({'error': str(e)}), 500

# File Upload and Analysis
@app.route('/upload', methods=['GET', 'POST'])
def upload_owl():
    """Handle OWL file upload and redirection to analysis page."""
    if request.method == 'GET':
        return render_template('upload.html')
    try:
        # Check if a file was uploaded
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('index'))
            
        file = request.files['file']
        
        # Check if the file has a name
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('index'))
        
        # Check if the file has a valid extension
        if not allowed_file(file.filename):
            flash(f'Invalid file type. Allowed types: {", ".join(app.config["ALLOWED_EXTENSIONS"])}', 'error')
            return redirect(url_for('index'))
        
        # Generate a secure filename
        original_filename = secure_filename(file.filename)
        filename = f"{uuid.uuid4().hex}.{original_filename.rsplit('.', 1)[1].lower()}"
        
        # Save the file
        file_path = os.path.join(app.config['UPLOADED_OWLS_DEST'], filename)
        file.save(file_path)
        
        # Create a record in the database
        file_size = os.path.getsize(file_path)
        file_record = OntologyFile(
            filename=filename,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            user_id=current_user.id if current_user.is_authenticated else None
        )
        
        db.session.add(file_record)
        db.session.commit()
        
        # Redirect to the analysis page
        return redirect(url_for('analyze_owl', filename=filename))
        
    except Exception as e:
        app.logger.error(f"Error uploading file: {str(e)}")
        flash(f"Error uploading file: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/analyze/<filename>')
def analyze_owl(filename):
    """Analyze an uploaded OWL file and display results."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Check if an analysis already exists for this file
        analysis = OntologyAnalysis.query.filter_by(ontology_file_id=file_record.id).order_by(OntologyAnalysis.id.desc()).first()
        
        if analysis:
            # Use the existing analysis
            # Extract class list and other entities from the analysis data
            class_list = analysis.class_list if analysis.class_list else []
            object_properties = analysis.object_property_list if hasattr(analysis, 'object_property_list') and analysis.object_property_list else []
            data_properties = analysis.data_property_list if hasattr(analysis, 'data_property_list') and analysis.data_property_list else []
            individuals = analysis.individual_list if hasattr(analysis, 'individual_list') and analysis.individual_list else []
            
            # Ensure we have non-null values for all statistics
            if analysis.class_count is None and class_list:
                analysis.class_count = len(class_list)
                db.session.commit()
                
            if analysis.object_property_count is None and object_properties:
                analysis.object_property_count = len(object_properties)
                db.session.commit()
                
            if analysis.data_property_count is None and data_properties:
                analysis.data_property_count = len(data_properties)
                db.session.commit()
                
            if analysis.individual_count is None and individuals:
                analysis.individual_count = len(individuals)
                db.session.commit()
                
            # Default values for everything
            if analysis.class_count is None:
                analysis.class_count = 0
            if analysis.object_property_count is None:
                analysis.object_property_count = 0
            if analysis.data_property_count is None:
                analysis.data_property_count = 0
            if analysis.individual_count is None:
                analysis.individual_count = 0
                
            return render_template('analysis.html', 
                                 file=file_record, 
                                 analysis=analysis,
                                 classes=class_list,
                                 relations=object_properties,
                                 data_properties=data_properties,
                                 individuals=individuals)
        else:
            # Create a new analysis
            return redirect(url_for('api_analyze_owl', filename=filename))
            
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        app.logger.error(f"Error analyzing OWL file: {str(e)}\nTraceback: {trace}")
        flash(f"Error analyzing OWL file: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/api/analyze/<filename>')
def api_analyze_owl(filename):
    """API endpoint for analyzing an uploaded OWL file."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Create an OwlTester instance
        tester = OwlTester()
        
        # First load the ontology
        load_result = tester.load_ontology_from_file(file_record.file_path)
        
        if not load_result.get('loaded', False) or not load_result.get('ontology'):
            raise Exception(f"Failed to load ontology: {load_result.get('error', 'Unknown error')}")
        
        # Then analyze the loaded ontology
        analysis_result = tester.analyze_ontology(load_result.get('ontology'))
        
        if not analysis_result or not isinstance(analysis_result, dict):
            raise Exception("Invalid analysis result")
            
        # Extract the relevant information
        ontology_name = analysis_result.get('ontology_name', 'Unknown Ontology')
        ontology_iri = analysis_result.get('ontology_iri', '')
        is_consistent = analysis_result.get('is_consistent', True)
        
        # Get counts - ensure we have non-zero values when we have list data
        class_list = analysis_result.get('class_list', [])
        object_property_list = analysis_result.get('object_property_list', [])
        data_property_list = analysis_result.get('data_property_list', [])
        individual_list = analysis_result.get('individual_list', [])
        
        # Now set the counts, using the list lengths if available
        class_count = analysis_result.get('classes', 0) or len(class_list)
        object_property_count = analysis_result.get('object_properties', 0) or len(object_property_list)
        data_property_count = analysis_result.get('data_properties', 0) or len(data_property_list)
        individual_count = analysis_result.get('individuals', 0) or len(individual_list)
        annotation_property_count = analysis_result.get('annotation_properties', 0)
        
        # For axioms, make sure we have a count
        axioms = analysis_result.get('axioms', [])
        axiom_count = analysis_result.get('axiom_count', 0) or len(axioms)
        
        # We already loaded the lists above, no need to do it again
        
        expressivity = analysis_result.get('expressivity', '')
        complexity = analysis_result.get('complexity', 0)
        
        axioms = analysis_result.get('axioms', [])
        consistency_issues = analysis_result.get('consistency_issues', [])
        inferred_axioms = analysis_result.get('inferred_axioms', [])
        
        # Extract transparency information
        reasoning_methodology = analysis_result.get('reasoning_methodology', {})
        derivation_steps = analysis_result.get('derivation_steps', [])
            
        # Create a new analysis record
        analysis = OntologyAnalysis(
            ontology_file_id=file_record.id,
            ontology_name=ontology_name,
            ontology_iri=ontology_iri,
            is_consistent=is_consistent,
            class_count=class_count,
            object_property_count=object_property_count,
            data_property_count=data_property_count,
            individual_count=individual_count,
            annotation_property_count=annotation_property_count,
            axiom_count=axiom_count,
            expressivity=expressivity,
            complexity=complexity,
            axioms=axioms,
            consistency_issues=consistency_issues,
            inferred_axioms=inferred_axioms,
            class_list=class_list,
            object_property_list=object_property_list,
            data_property_list=data_property_list,
            individual_list=individual_list,
            reasoning_methodology=reasoning_methodology,
            derivation_steps=derivation_steps
        )
        
        # Attempt to extract FOL premises from the ontology
        try:
            app.logger.info("Attempting to extract FOL premises...")
            # We've already loaded the ontology earlier in this function
            # Reuse it instead of loading it again
            onto = load_result.get('ontology')
            
            if onto:
                premises = []
                found_premises = False
                
                # Try to extract annotations if available
                structured_premises = []
                for cls in onto.classes():
                    if hasattr(cls, 'comment'):
                        for comment in cls.comment:
                            if "FOL:" in comment:
                                fol_expr = comment.split("FOL:")[1].strip()
                                
                                # Create a structured premise with type, fol, and description
                                structured_premise = {
                                    'type': 'annotation',
                                    'fol': fol_expr,
                                    'description': f"Extracted from annotation on {cls.name}",
                                    'entity_name': cls.name
                                }
                                
                                structured_premises.append(structured_premise)
                                found_premises = True
                                
                premises = structured_premises
                
                # If no premises were found in annotations, generate default ones
                if not found_premises:
                    app.logger.info(f"★★★ NO FOL PREMISES FOUND IN ANNOTATIONS. GENERATING DEFAULTS... ★★★")
                    app.logger.info(f"★★★ FOUND {class_count} CLASSES AND {object_property_count} PROPERTIES FOR DEFAULT PREMISES ★★★")
                    
                    # Generate default premises for classes
                    structured_premises = []
                    for cls in onto.classes():
                        if hasattr(cls, 'name') and cls.name:
                            # Skip some common base classes that might create noise
                            if cls.name in ['Thing', 'Nothing', 'Entity']:
                                continue
                                
                            # Create a premise in BFO format: instance_of(x, ClassName, t)
                            fol_expr = f"instance_of(x, {cls.name}, t)"
                            
                            # Create a structured premise with type, fol, and description
                            structured_premise = {
                                'type': 'class',
                                'fol': fol_expr,
                                'description': f"Entities that are instances of {cls.name}",
                                'entity_name': cls.name
                            }
                            
                            structured_premises.append(structured_premise)
                            app.logger.info(f"★★★ Added default class FOL premise for: {cls.name} ★★★")
                    
                    # Generate default premises for object properties
                    for prop in onto.object_properties():
                        if hasattr(prop, 'name') and prop.name:
                            # Create a premise in BFO format: PropertyName(x, y, t)
                            fol_expr = f"{prop.name}(x, y, t)"
                            
                            # Create a structured premise with type, fol, and description
                            structured_premise = {
                                'type': 'property',
                                'fol': fol_expr,
                                'description': f"Relation {prop.name} between entities",
                                'entity_name': prop.name
                            }
                            
                            structured_premises.append(structured_premise)
                            app.logger.info(f"★★★ Added default property FOL premise for: {prop.name} ★★★")
                    
                    premises = structured_premises
                        
                    app.logger.info(f"★★★ GENERATED {len(premises)} DEFAULT FOL PREMISES ★★★")
                    
                    # Add the premises to the analysis
                    analysis.fol_premises = premises
            else:
                app.logger.warning(f"Could not extract FOL premises: {load_result.get('error', 'Unknown error')}")
        except Exception as e:
            app.logger.error(f"Error extracting FOL premises: {str(e)}")
        
        # Make sure we have non-zero values for statistics if they're missing or zero
        # This prevents empty white boxes in the UI
        if analysis.class_count == 0 and len(class_list) > 0:
            analysis.class_count = len(class_list)
            
        if analysis.object_property_count == 0 and len(object_property_list) > 0:
            analysis.object_property_count = len(object_property_list)
            
        if analysis.data_property_count == 0 and len(data_property_list) > 0:
            analysis.data_property_count = len(data_property_list)
            
        if analysis.individual_count == 0 and len(individual_list) > 0:
            analysis.individual_count = len(individual_list)
            
        if analysis.axiom_count == 0 and len(axioms) > 0:
            analysis.axiom_count = len(axioms)
        
        # Save the analysis to the database
        db.session.add(analysis)
        db.session.commit()
        
        app.logger.info(f"Using analysis ID {analysis.id} for API calls")
        app.logger.info(f"Statistics: Classes={analysis.class_count}, Object Props={analysis.object_property_count}, Data Props={analysis.data_property_count}, Individuals={analysis.individual_count}")
        
        # Redirect to the analysis page
        return redirect(url_for('analyze_owl', filename=filename))
        
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        app.logger.error(f"Error in API analyze_owl: {str(e)}\nTraceback: {trace}")
        flash(f"Error analyzing OWL file: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/api/analysis/<analysis_id>/implications', methods=['GET', 'POST'])
def generate_implications(analysis_id):
    """
    Generate or retrieve real-world implications for an ontology analysis.
    
    GET: Retrieve previously generated implications
    POST: Generate new implications
    """
    try:
        analysis = OntologyAnalysis.query.get_or_404(analysis_id)
        
        if request.method == 'GET':
            # Return the existing implications if they exist
            if analysis.real_world_implications and len(analysis.real_world_implications) > 0:
                return jsonify({
                    'success': True,
                    'implications': analysis.real_world_implications,
                    'generated': analysis.implications_generated,
                    'generated_date': analysis.implications_generation_date.isoformat() if analysis.implications_generation_date else None
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'No implications have been generated for this analysis yet',
                    'generated': False
                })
        
        elif request.method == 'POST':
            # Generate new implications
            fol_premises = analysis.fol_premises
            
            if not fol_premises or len(fol_premises) == 0:
                return jsonify({
                    'success': False,
                    'message': 'No FOL premises found for this analysis'
                }), 400
            
            # Generate implications using OpenAI
            try:
                # Extract domain classes from analysis class_list if available
                domain_classes = []
                if analysis.class_list:
                    # Check if class_list contains dictionaries with 'name' field
                    if isinstance(analysis.class_list, list) and len(analysis.class_list) > 0:
                        if isinstance(analysis.class_list[0], dict) and 'name' in analysis.class_list[0]:
                            domain_classes = [cls['name'] for cls in analysis.class_list if 'name' in cls]
                        else:
                            domain_classes = analysis.class_list  # Assume it's already a list of class names
                
                # Get the ontology name
                ontology_name = analysis.ontology_name if analysis.ontology_name else "Unknown Ontology"
                
                # Log what we're passing to the implications generator
                app.logger.info(f"Generating implications for ontology '{ontology_name}'")
                app.logger.info(f"Domain classes: {domain_classes}")
                app.logger.info(f"FOL premises count: {len(fol_premises) if fol_premises else 0}")
                
                # Call the function with the correct parameters
                implications = generate_real_world_implications(
                    ontology_name=ontology_name,
                    domain_classes=domain_classes,
                    fol_premises=fol_premises
                )
                
                # Update the analysis record
                analysis.real_world_implications = implications
                analysis.implications_generated = True
                analysis.implications_generation_date = datetime.datetime.utcnow()
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'implications': implications
                })
                
            except Exception as e:
                app.logger.error(f"Error generating implications: {str(e)}")
                return jsonify({
                    'success': False,
                    'message': f"Error generating implications: {str(e)}"
                }), 500
        
    except Exception as e:
        app.logger.error(f"Error in generate_implications: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error generating implications: {str(e)}"
        }), 500

@app.route('/implications/<filename>')
def show_implications(filename):
    """Show real-world implications for an ontology file."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Get the latest analysis for this file
        analysis = OntologyAnalysis.query.filter_by(ontology_file_id=file_record.id).order_by(OntologyAnalysis.id.desc()).first_or_404()
        
        return render_template('implications.html', 
                             file=file_record, 
                             analysis=analysis)
            
    except Exception as e:
        app.logger.error(f"Error showing implications: {str(e)}")
        flash(f"Error showing implications: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/history')
def view_history():
    """View history of uploaded ontologies and analyses."""
    try:
        # Get all ontology files with their analyses, ordered by upload date (newest first)
        ontologies = OntologyFile.query.order_by(OntologyFile.upload_date.desc()).all()
        
        # Get all FOL expressions, ordered by test date (newest first)
        expressions = FOLExpression.query.order_by(FOLExpression.test_date.desc()).limit(20).all()
        
        return render_template('history.html', 
                              ontologies=ontologies,
                              expressions=expressions)
    except Exception as e:
        logger.error(f"Error viewing history: {str(e)}")
        flash(f"Error viewing history: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/import_to_sandbox/<int:file_id>')
def import_to_sandbox(file_id):
    """Import an ontology file from history to the sandbox."""
    success = False
    error_message = None
    
    try:
        # Get the file or return 404
        file = OntologyFile.query.get_or_404(file_id)
        
        # Add debug logging
        logger.debug(f"Importing file ID {file_id} - Original filename: {file.original_filename}")
        
        # Create a base ontology first, before doing anything that might fail
        ontology = SandboxOntology()
        ontology.title = f"{file.original_filename.rsplit('.', 1)[0]}"
        ontology.domain = "Imported Ontology"
        ontology.subject = "Imported from History"
        ontology.description = f"Imported from file '{file.original_filename}'."
        ontology.user_id = current_user.id if not current_user.is_anonymous else None
        
        # Save and COMMIT to get a permanent ID before creating related records
        db.session.add(ontology)
        db.session.commit()
        
        # Log the newly created ontology ID for debugging
        logger.debug(f"Created new sandbox ontology with ID: {ontology.id}")
        
        # Get the file path
        file_path = file.file_path
        
        # Handle missing files by creating a basic ontology structure from database records
        # This allows us to work with ontologies even if the original file is missing
        if not os.path.exists(file_path):
            logger.warning(f"File not found at {file_path}. Using database records instead.")
            
            # Update the existing ontology description to note the missing file
            ontology.description = f"Imported from file '{file.original_filename}'. Note: The original file could not be found, but class and property data was imported from database records."
            
            # Use existing analyses if available
            if file.analyses:
                analysis = file.analyses[0]
                ontology.domain = analysis.ontology_name or "Imported Ontology"
                
                # If we have class and property lists, use them
                try:
                    # Debugging information
                    logger.debug(f"class_list type: {type(analysis.class_list)}")
                    logger.debug(f"class_list: {analysis.class_list}")
                    
                    # Wrap in a try-except to catch all possible data format issues
                    try:
                        if analysis.class_list:
                            # Convert anything into a list of strings for safety
                            class_names = []
                            
                            # Try to handle possible formats
                            if isinstance(analysis.class_list, list):
                                for item in analysis.class_list:
                                    try:
                                        if isinstance(item, dict) and 'name' in item:
                                            class_names.append(item['name'])
                                        elif isinstance(item, str):
                                            class_names.append(item)
                                        else:
                                            # Handle non-string, non-dict objects by converting to string
                                            class_names.append(str(item))
                                    except Exception as e:
                                        logger.warning(f"Error processing list item in class_list: {str(e)}")
                                        class_names.append("Unknown_Class")
                            elif isinstance(analysis.class_list, dict):
                                # If it's a dictionary (e.g. a single class object)
                                try:
                                    if 'name' in analysis.class_list:
                                        class_names.append(analysis.class_list['name'])
                                    else:
                                        # Handle dictionaries without name by taking first value
                                        values = list(analysis.class_list.values())
                                        if values:
                                            class_names.append(str(values[0]))
                                        else:
                                            # Last resort: use the keys
                                            keys = list(analysis.class_list.keys())
                                            if keys:
                                                class_names.append(str(keys[0]))
                                            else:
                                                # Nothing to use, add a placeholder
                                                class_names.append("Unknown_Class")
                                except Exception as e:
                                    logger.warning(f"Error processing dict in class_list: {str(e)}")
                                    class_names.append("Unknown_Class")
                            elif isinstance(analysis.class_list, str):
                                # If it's a JSON string, try to parse it
                                try:
                                    import json
                                    parsed = json.loads(analysis.class_list)
                                    if isinstance(parsed, list):
                                        for item in parsed:
                                            try:
                                                if isinstance(item, dict) and 'name' in item:
                                                    class_names.append(item['name'])
                                                elif isinstance(item, str):
                                                    class_names.append(item)
                                                else:
                                                    class_names.append(str(item))
                                            except Exception:
                                                class_names.append("Unknown_Class")
                                    elif isinstance(parsed, dict):
                                        if 'name' in parsed:
                                            class_names.append(parsed['name'])
                                        else:
                                            # Use first value or key as fallback
                                            values = list(parsed.values())
                                            if values:
                                                class_names.append(str(values[0]))
                                            else:
                                                keys = list(parsed.keys())
                                                if keys:
                                                    class_names.append(str(keys[0]))
                                                else:
                                                    class_names.append("Unknown_Class")
                                except Exception as e:
                                    logger.warning(f"Error parsing JSON in class_list: {str(e)}")
                                    # Just treat it as a single class name
                                    class_names.append(str(analysis.class_list))
                            else:
                                # Handle any other type by converting to string
                                class_names.append(str(analysis.class_list))
                        else:
                            # Handle empty class list
                            class_names = []
                    except Exception as e:
                        logger.error(f"Error in overall class_list processing: {str(e)}")
                        # Provide a default class if everything fails
                        class_names = ["Default_Class"]
                        
                    # Log the processed class names
                    logger.debug(f"Processed class_names: {class_names}")
                    
                    # Create a list to hold class objects for the SandboxOntology
                    class_objects = []
                    
                    # Add the classes
                    for class_name in class_names:
                        # Create a class object for the SandboxOntology.classes list
                        class_obj = {
                            "name": class_name,
                            "description": f"Class '{class_name}' imported from '{file.original_filename}'",
                            "bfo_category": None
                        }
                        class_objects.append(class_obj)
                        
                        # Also create the class in the OntologyClass table
                        cls = OntologyClass(
                            ontology_id=ontology.id,
                            name=class_name,
                            description=f"Class '{class_name}' imported from '{file.original_filename}'",
                            creation_date=datetime.datetime.utcnow()
                        )
                        db.session.add(cls)
                    
                    # Update the SandboxOntology with the class list
                    ontology.classes = class_objects
                except Exception as e:
                    logger.error(f"Error processing class_list: {str(e)}")
                
                try:
                    # Debugging information
                    logger.debug(f"object_property_list type: {type(analysis.object_property_list)}")
                    logger.debug(f"object_property_list: {analysis.object_property_list}")
                    
                    # Wrap in a try-except to catch all possible data format issues
                    try:
                        if analysis.object_property_list:
                            # Convert anything into a list of strings for safety
                            property_names = []
                            
                            # Try to handle possible formats
                            if isinstance(analysis.object_property_list, list):
                                for item in analysis.object_property_list:
                                    try:
                                        if isinstance(item, dict) and 'name' in item:
                                            property_names.append(item['name'])
                                        elif isinstance(item, str):
                                            property_names.append(item)
                                        else:
                                            # Handle non-string, non-dict objects by converting to string
                                            property_names.append(str(item))
                                    except Exception as e:
                                        logger.warning(f"Error processing list item in object_property_list: {str(e)}")
                                        property_names.append("Unknown_Property")
                            elif isinstance(analysis.object_property_list, dict):
                                # If it's a dictionary (e.g. a single property object)
                                try:
                                    if 'name' in analysis.object_property_list:
                                        property_names.append(analysis.object_property_list['name'])
                                    else:
                                        # Handle dictionaries without name by taking first value
                                        values = list(analysis.object_property_list.values())
                                        if values:
                                            property_names.append(str(values[0]))
                                        else:
                                            # Last resort: use the keys
                                            keys = list(analysis.object_property_list.keys())
                                            if keys:
                                                property_names.append(str(keys[0]))
                                            else:
                                                # Nothing to use, add a placeholder
                                                property_names.append("Unknown_Property")
                                except Exception as e:
                                    logger.warning(f"Error processing dict in object_property_list: {str(e)}")
                                    property_names.append("Unknown_Property")
                            elif isinstance(analysis.object_property_list, str):
                                # If it's a JSON string, try to parse it
                                try:
                                    import json
                                    parsed = json.loads(analysis.object_property_list)
                                    if isinstance(parsed, list):
                                        for item in parsed:
                                            try:
                                                if isinstance(item, dict) and 'name' in item:
                                                    property_names.append(item['name'])
                                                elif isinstance(item, str):
                                                    property_names.append(item)
                                                else:
                                                    property_names.append(str(item))
                                            except Exception:
                                                property_names.append("Unknown_Property")
                                    elif isinstance(parsed, dict):
                                        if 'name' in parsed:
                                            property_names.append(parsed['name'])
                                        else:
                                            # Use first value or key as fallback
                                            values = list(parsed.values())
                                            if values:
                                                property_names.append(str(values[0]))
                                            else:
                                                keys = list(parsed.keys())
                                                if keys:
                                                    property_names.append(str(keys[0]))
                                                else:
                                                    property_names.append("Unknown_Property")
                                except Exception as e:
                                    logger.warning(f"Error parsing JSON in object_property_list: {str(e)}")
                                    # Just treat it as a single property name
                                    property_names.append(str(analysis.object_property_list))
                            else:
                                # Handle any other type by converting to string
                                property_names.append(str(analysis.object_property_list))
                        else:
                            # Handle empty property list
                            property_names = []
                    except Exception as e:
                        logger.error(f"Error in overall object_property_list processing: {str(e)}")
                        # Provide a default property if everything fails
                        property_names = ["Default_Property"]
                    
                    # Log the processed property names
                    logger.debug(f"Processed property_names: {property_names}")
                    
                    # Create a list to hold property objects for the SandboxOntology
                    property_objects = []
                    
                    # Add the properties
                    for property_name in property_names:
                        # Create a property object for the SandboxOntology.properties list
                        property_obj = {
                            "name": property_name,
                            "description": f"Property '{property_name}' imported from '{file.original_filename}'",
                            "property_type": "object"
                        }
                        property_objects.append(property_obj)
                        
                        # Also create the property in the OntologyProperty table
                        prop = OntologyProperty(
                            ontology_id=ontology.id,
                            name=property_name,
                            description=f"Property '{property_name}' imported from '{file.original_filename}'",
                            property_type='object',
                            creation_date=datetime.datetime.utcnow()
                        )
                        db.session.add(prop)
                    
                    # Update the SandboxOntology with the property list
                    ontology.properties = property_objects
                except Exception as e:
                    logger.error(f"Error processing object_property_list: {str(e)}")
            
            # Final commit for any remaining changes
            db.session.commit()
            
            # Success message
            flash(f"Successfully imported '{file.original_filename}' to sandbox with {len(ontology.classes)} classes and {len(ontology.properties)} properties.", 'success')
            return redirect(url_for('sandbox_edit', ontology_id=ontology.id))
        
        # We'll try to use Owlready2 to parse the ontology to get classes, properties, etc.
        from owlready2 import get_ontology
        import tempfile
        
        # Check if there's already an analysis we can use
        if file.analyses:
            # Use the analysis data to create a sandbox ontology
            analysis = file.analyses[0]  # Use the first analysis
            
            # Create a new SandboxOntology
            ontology = SandboxOntology()
            ontology.title = f"{file.original_filename.rsplit('.', 1)[0]}"
            ontology.domain = analysis.ontology_name or "Imported Ontology"
            ontology.subject = "Imported from History"
            ontology.description = f"Imported from file '{file.original_filename}'. Original IRI: {analysis.ontology_iri or 'Unknown'}"
            ontology.user_id = current_user.id if not current_user.is_anonymous else None
            
            # Save to get an ID
            db.session.add(ontology)
            db.session.flush()
            
            # Add classes
            if analysis.class_list:
                for cls_data in analysis.class_list:
                    cls = OntologyClass()
                    cls.ontology_id = ontology.id
                    
                    # Handle different data types that might be in class_list
                    if isinstance(cls_data, dict):
                        cls.name = cls_data.get('name', 'Unknown Class')
                        cls.description = cls_data.get('description', f"Imported from '{file.original_filename}'")
                        cls.bfo_category = cls_data.get('bfo_category')
                    elif isinstance(cls_data, str):
                        # If we have a string, use it as the class name
                        cls.name = cls_data
                        cls.description = f"Imported from '{file.original_filename}'"
                        cls.bfo_category = None
                    else:
                        # For any other type, convert to string
                        cls.name = str(cls_data)
                        cls.description = f"Imported from '{file.original_filename}'"
                        cls.bfo_category = None
                    
                    db.session.add(cls)
            
            # Add properties
            if analysis.object_property_list:
                for prop_data in analysis.object_property_list:
                    prop = OntologyProperty()
                    prop.ontology_id = ontology.id
                    
                    # Handle different data types that might be in object_property_list
                    if isinstance(prop_data, dict):
                        prop.name = prop_data.get('name', 'Unknown Property')
                        prop.description = prop_data.get('description', f"Imported from '{file.original_filename}'")
                        prop.property_type = prop_data.get('property_type', 'object')
                    elif isinstance(prop_data, str):
                        # If we have a string, use it as the property name
                        prop.name = prop_data
                        prop.description = f"Imported from '{file.original_filename}'"
                        prop.property_type = 'object'
                    else:
                        # For any other type, convert to string
                        prop.name = str(prop_data)
                        prop.description = f"Imported from '{file.original_filename}'"
                        prop.property_type = 'object'
                    
                    db.session.add(prop)
                    
            # Add data properties
            if analysis.data_property_list:
                for prop_data in analysis.data_property_list:
                    prop = OntologyProperty()
                    prop.ontology_id = ontology.id
                    
                    # Handle different data types that might be in data_property_list
                    if isinstance(prop_data, dict):
                        prop.name = prop_data.get('name', 'Unknown Property')
                        prop.description = prop_data.get('description', f"Imported from '{file.original_filename}'")
                        prop.property_type = 'data'
                    elif isinstance(prop_data, str):
                        # If we have a string, use it as the property name
                        prop.name = prop_data
                        prop.description = f"Imported from '{file.original_filename}'"
                        prop.property_type = 'data'
                    else:
                        # For any other type, convert to string
                        prop.name = str(prop_data)
                        prop.description = f"Imported from '{file.original_filename}'"
                        prop.property_type = 'data'
                    
                    db.session.add(prop)
            
            # Final commit for all changes
            db.session.commit()
            
            logger.debug(f"Successfully imported ontology to sandbox with ID: {ontology.id}")
            flash(f"Ontology '{file.original_filename}' successfully imported to Sandbox.", 'success')
            return redirect(url_for('sandbox_edit', ontology_id=ontology.id))
        
        # If no analysis, try to parse with Owlready2 directly
        try:
            onto = get_ontology(file_path).load()
            
            # Create a new SandboxOntology
            ontology = SandboxOntology()
            ontology.title = f"{file.original_filename.rsplit('.', 1)[0]}"
            ontology.domain = onto.name or "Imported Ontology"
            ontology.subject = "Imported from History" 
            ontology.description = f"Imported from file '{file.original_filename}'. Original IRI: {onto.base_iri or 'Unknown'}"
            ontology.user_id = current_user.id if not current_user.is_anonymous else None
            
            # Save to get an ID
            db.session.add(ontology)
            db.session.flush()
            
            # Add classes
            for cls in onto.classes():
                ontology_class = OntologyClass()
                ontology_class.ontology_id = ontology.id
                ontology_class.name = cls.name
                # Get comment or description if available
                desc = None
                for p in cls.get_properties():
                    if p.name.lower() in ['comment', 'description', 'definition']:
                        desc = p[cls]
                        break
                ontology_class.description = desc or f"Class imported from '{file.original_filename}'"
                db.session.add(ontology_class)
            
            # Add properties
            for prop in onto.object_properties():
                ontology_prop = OntologyProperty()
                ontology_prop.ontology_id = ontology.id
                ontology_prop.name = prop.name
                # Get comment or description if available
                desc = None
                for p in prop.get_properties():
                    if p.name.lower() in ['comment', 'description', 'definition']:
                        desc = p[prop]
                        break
                ontology_prop.description = desc or f"Object property imported from '{file.original_filename}'"
                ontology_prop.property_type = 'object'
                db.session.add(ontology_prop)
            
            # Add data properties
            for prop in onto.data_properties():
                ontology_prop = OntologyProperty()
                ontology_prop.ontology_id = ontology.id
                ontology_prop.name = prop.name
                # Get comment or description if available
                desc = None
                for p in prop.get_properties():
                    if p.name.lower() in ['comment', 'description', 'definition']:
                        desc = p[prop]
                        break
                ontology_prop.description = desc or f"Data property imported from '{file.original_filename}'"
                ontology_prop.property_type = 'data'
                db.session.add(ontology_prop)
            
            # Final commit for all changes
            db.session.commit()
            
            logger.debug(f"Successfully imported ontology to sandbox with ID: {ontology.id}")
            flash(f"Ontology '{file.original_filename}' successfully imported to Sandbox.", 'success')
            return redirect(url_for('sandbox_edit', ontology_id=ontology.id))
        except Exception as e:
            logger.warning(f"Could not parse ontology with Owlready2: {str(e)}")
            
            # Create a basic sandbox ontology
            ontology = SandboxOntology()
            ontology.title = f"{file.original_filename.rsplit('.', 1)[0]}"
            ontology.domain = "Imported Ontology"
            ontology.subject = "Imported from History"
            ontology.description = f"Imported from file '{file.original_filename}'. Note: Unable to parse classes and properties automatically."
            ontology.user_id = current_user.id if not current_user.is_anonymous else None
            
            db.session.add(ontology)
            db.session.commit()
            
            flash(f"Created sandbox ontology from '{file.original_filename}', but could not parse classes and properties. You'll need to add them manually.", 'warning')
            return redirect(url_for('sandbox_edit', ontology_id=ontology.id))
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error importing file to sandbox: {str(e)}")
        flash(f"Error importing file to sandbox: {str(e)}", 'error')
        return redirect(url_for('view_history'))

@app.route('/delete_file/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    """Delete an ontology file and all its analyses."""
    try:
        # Get the file or return 404
        file = OntologyFile.query.get_or_404(file_id)
        
        # Get file path to delete the physical file
        file_path = file.file_path
        
        # Store information for flash message
        filename = file.original_filename
        
        # Delete the file from database (cascade will delete analyses)
        db.session.delete(file)
        db.session.commit()
        
        # Try to delete the physical file, but don't worry if it fails
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete physical file {file_path}: {str(e)}")
        
        flash(f"File '{filename}' deleted successfully.", 'success')
        return redirect(url_for('view_history'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting file: {str(e)}")
        flash(f"Error deleting file: {str(e)}", 'error')
        return redirect(url_for('view_history'))

# UML Diagram generation with D3.js
@app.route('/analyze/<filename>/diagram')
def generate_diagram(filename):
    """Generate an interactive diagram for an ontology file using D3.js."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Create an OwlTester instance
        tester = OwlTester()
        
        # Load the ontology file
        result = tester.load_ontology_from_file(file_record.file_path)
        
        if isinstance(result, dict) and not result.get('loaded', False):
            # If load_ontology_from_file returns a dictionary with loaded=False
            error_msg = result.get('error', 'Unknown error')
            raise Exception(f"Failed to load ontology for diagram: {error_msg}")
        
        # Get the ontology object from the result
        onto = None
        if isinstance(result, dict) and 'ontology' in result:
            onto = result.get('ontology')
        
        if not onto:
            raise Exception("Loaded ontology object not found in result")
        
        # Get ontology information for display
        ontology_name = getattr(onto, 'name', os.path.basename(file_record.original_filename))
        class_count = len(list(onto.classes()))
        property_count = len(list(onto.object_properties()))
        
        # Render the D3.js visualization template
        return render_template('d3_diagram.html', 
                             filename=filename,
                             ontology_name=ontology_name,
                             class_count=class_count,
                             property_count=property_count)
            
    except Exception as e:
        logger.error(f"Error generating D3.js diagram: {str(e)}")
        flash(f"Error generating diagram: {str(e)}", 'error')
        return redirect(url_for('analyze_owl', filename=filename))

@app.route('/api/diagram-data/<filename>')
def api_diagram_data(filename):
    """API endpoint to get ontology data in JSON format for D3.js visualization."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Get the latest analysis for this file to use stored data if loading fails
        analysis = OntologyAnalysis.query.filter_by(ontology_file_id=file_record.id).order_by(OntologyAnalysis.id.desc()).first_or_404()
        
        # Extract class list and property list from analysis
        class_list = []
        if analysis.class_list:
            if isinstance(analysis.class_list, list):
                class_list = analysis.class_list
            elif isinstance(analysis.class_list, dict):
                # Handle case where class_list is a dict
                class_list = list(analysis.class_list.keys())
            else:
                # Try to convert to a list if it's a string or other type
                try:
                    class_list = list(analysis.class_list)
                except:
                    class_list = []
        
        object_property_list = []
        if hasattr(analysis, 'object_property_list') and analysis.object_property_list:
            if isinstance(analysis.object_property_list, list):
                object_property_list = analysis.object_property_list
            elif isinstance(analysis.object_property_list, dict):
                # Handle case where object_property_list is a dict
                object_property_list = list(analysis.object_property_list.keys())
            else:
                # Try to convert to a list if it's a string or other type
                try:
                    object_property_list = list(analysis.object_property_list)
                except:
                    object_property_list = []
        
        # Always default to fallback mode using analysis data for now
        # This gives us more consistent visualization
        use_fallback = True
        
        # Try loading the ontology only if we need to
        onto = None
        if not use_fallback:
            try:
                # Create an OwlTester instance
                tester = OwlTester()
                
                # Load the ontology file with a timeout
                result = tester.load_ontology_from_file(file_record.file_path)
                
                if isinstance(result, dict) and result.get('loaded', False) and 'ontology' in result:
                    onto = result.get('ontology')
                else:
                    use_fallback = True
                    logger.warning(f"Failed to load ontology for visualization: {result.get('error', 'Unknown error')}")
            except Exception as e:
                use_fallback = True
                logger.warning(f"Exception loading ontology for visualization: {str(e)}")
        
        # Process the ontology data into a format suitable for D3.js
        classes = []
        inheritance = []
        properties = []
        
        # Generate visualization data from analysis database record
        if use_fallback:
            logger.info(f"Using fallback visualization from analysis data for {filename}")
            logger.info(f"Classes: {len(class_list)}, Object Properties: {len(object_property_list)}")
            
            # If we have no classes but have FOL premises, try to extract classes from there
            if not class_list and analysis.fol_premises:
                logger.info("Extracting classes from FOL premises")
                extracted_classes = set()
                try:
                    for premise in analysis.fol_premises:
                        if isinstance(premise, dict) and 'fol' in premise:
                            fol_text = premise['fol']
                            # Look for instance_of(x, Class, t) pattern
                            matches = re.findall(r'instance_of\([^,]+,\s*([^,\)]+)', fol_text)
                            for match in matches:
                                extracted_classes.add(match.strip())
                    
                    class_list = list(extracted_classes)
                    logger.info(f"Extracted {len(class_list)} classes from FOL premises")
                except Exception as extract_e:
                    logger.error(f"Error extracting classes from FOL premises: {str(extract_e)}")
            
            # Create classes from class_list
            for cls_name in class_list:
                if not cls_name or not isinstance(cls_name, str):
                    continue
                    
                is_bfo = False  # Assume not a BFO class
                if 'BFO_' in cls_name or 'IAO_' in cls_name:
                    is_bfo = True
                    
                classes.append({
                    'id': cls_name,
                    'name': cls_name,
                    'bfo': is_bfo
                })
            
            # Add a root "Thing" class if there are classes
            if classes:
                root_exists = False
                for cls in classes:
                    if cls['name'] == 'Thing':
                        root_exists = True
                        break
                
                if not root_exists:
                    classes.append({
                        'id': 'Thing',
                        'name': 'Thing',
                        'bfo': True
                    })
                
                # Create basic inheritance structure - connect all to Thing
                for cls in classes:
                    if cls['name'] != 'Thing':
                        inheritance.append({
                            'source': cls['id'],
                            'target': 'Thing',
                            'type': 'subClassOf'
                        })
            
            # Create property connections if we have object properties
            if object_property_list and len(classes) > 1:
                classes_names = [cls['id'] for cls in classes if cls['name'] != 'Thing']
                for i, prop_name in enumerate(object_property_list):
                    if not prop_name or not isinstance(prop_name, str):
                        continue
                        
                    if classes_names:  # Make sure we have classes to connect
                        # Create connections between classes using round-robin
                        source_idx = i % len(classes_names)
                        target_idx = (i + 1) % len(classes_names)
                        
                        properties.append({
                            'source': classes_names[source_idx],
                            'target': classes_names[target_idx],
                            'label': prop_name,
                            'type': 'objectProperty'
                        })
        elif onto is not None:  # Only run this if we have a valid ontology object
            logger.info(f"Using direct ontology processing for visualization of {filename}")
            
            # Process classes from the fully loaded ontology
            for cls in onto.classes():
                if hasattr(cls, 'name') and cls.name:
                    # Determine if it's a BFO class
                    is_bfo = False
                    if hasattr(cls, 'iri'):
                        is_bfo = 'BFO' in str(cls.iri) or 'IAO' in str(cls.iri)
                    
                    classes.append({
                        'id': cls.name,
                        'name': cls.name,
                        'bfo': is_bfo
                    })
                    
                    # Process inheritance relationships
                    for parent in cls.is_a:
                        if hasattr(parent, 'name') and parent.name:
                            inheritance.append({
                                'source': cls.name,
                                'target': parent.name,
                                'type': 'subClassOf'
                            })
            
            # Process object properties
            for prop in onto.object_properties():
                if hasattr(prop, 'name') and prop.name:
                    if hasattr(prop, 'domain') and prop.domain and hasattr(prop, 'range') and prop.range:
                        for domain_cls in prop.domain:
                            for range_cls in prop.range:
                                if hasattr(domain_cls, 'name') and domain_cls.name and hasattr(range_cls, 'name') and range_cls.name:
                                    properties.append({
                                        'source': domain_cls.name,
                                        'target': range_cls.name,
                                        'label': prop.name,
                                        'type': 'objectProperty'
                                    })
        
        # Return data as JSON, but only if we actually have data
        if classes:
            logger.info(f"Returning visualization data with {len(classes)} classes, {len(inheritance)} inheritance links, and {len(properties)} properties")
            return jsonify({
                'classes': classes,
                'inheritance': inheritance,
                'properties': properties
            })
        else:
            # Create minimal data with a basic structure
            logger.warning("No classes found. Creating minimal default structure.")
            classes = [
                {'id': 'Thing', 'name': 'Thing', 'bfo': True},
                {'id': 'Ontology', 'name': 'Ontology', 'bfo': False}
            ]
            inheritance = [
                {'source': 'Ontology', 'target': 'Thing', 'type': 'subClassOf'}
            ]
            return jsonify({
                'classes': classes,
                'inheritance': inheritance,
                'properties': []
            })
        
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        logger.error(f"Error generating diagram data: {str(e)}\nTraceback: {trace}")
        # Return a minimal valid structure so the visualization doesn't break
        classes = [
            {'id': 'Error', 'name': 'Error Loading Diagram', 'bfo': False},
            {'id': 'Thing', 'name': 'Thing', 'bfo': True}
        ]
        inheritance = [
            {'source': 'Error', 'target': 'Thing', 'type': 'subClassOf'}
        ]
        return jsonify({
            'classes': classes,
            'inheritance': inheritance,
            'properties': [],
            'error': str(e)
        })

@app.route('/api/diagram/<filename>', methods=['GET'])
def api_generate_diagram(filename):
    """Legacy API endpoint - redirects to the new interactive diagram."""
    # Redirect to the new interactive diagram
    return redirect(url_for('generate_diagram', filename=filename))

@app.route('/analyze/<filename>/bvss')
def bvss_visualize(filename):
    """Generate a BVSS visualization for an ontology file."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Get the file path
        file_path = file_record.file_path
        
        # Check if file exists
        if not os.path.exists(file_path):
            flash(f"Ontology file not found: {filename}", 'error')
            return redirect(url_for('view_history'))
        
        # Extract BVSS graph data
        bvss_data = extract_bvss_graph(file_path)
        
        return render_template('bvss_fixed.html', 
                             file=file_record,
                             filename=filename,
                             bvss_data=bvss_data)
            
    except Exception as e:
        app.logger.error(f"Error generating BVSS visualization: {str(e)}")
        flash(f"Error generating BVSS visualization: {str(e)}", 'error')
        return redirect(url_for('view_history'))

@app.route('/api/bvss/<filename>')
def api_bvss_data(filename):
    """API endpoint to get BVSS visualization data in JSON format."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Get the file path
        file_path = file_record.file_path
        
        # Check if file exists
        if not os.path.exists(file_path):
            return jsonify({
                'error': 'File not found',
                'nodes': [],
                'edges': []
            }), 404
        
        # Extract BVSS graph data
        bvss_data = extract_bvss_graph(file_path)
        
        return jsonify(bvss_data)
        
    except Exception as e:
        app.logger.error(f"Error getting BVSS data: {str(e)}")
        return jsonify({
            'error': str(e),
            'nodes': [],
            'edges': []
        }), 500

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('index.html', error=f"Server error: {str(e)}"), 500

# User Authentication
@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    form = LoginForm()
    
    if form.validate_on_submit():
        # Find the user by email
        user = User.query.filter_by(email=form.email.data).first()
        
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))
            
        # Log the user in
        login_user(user, remember=form.remember_me.data)
        
        # Update last login timestamp
        user.last_login = datetime.datetime.utcnow()
        db.session.commit()
        
        # Redirect to the page the user was trying to access
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('index')
            
        flash('Login successful', 'success')
        return redirect(next_page)
        
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    form = RegistrationForm()
    
    if form.validate_on_submit():
        # Create a new user
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Congratulations, you are now a registered user! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html', form=form)

@app.route('/logout')
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard with personalized analysis history"""
    try:
        # Get all ontology files for the current user, ordered by upload date (newest first)
        ontologies = OntologyFile.query.filter_by(user_id=current_user.id).order_by(OntologyFile.upload_date.desc()).all()
        
        # Get all FOL expressions for the current user, ordered by test date (newest first)
        expressions = FOLExpression.query.filter_by(user_id=current_user.id).order_by(FOLExpression.test_date.desc()).limit(20).all()
        
        # Calculate statistics
        ontology_count = len(ontologies)
        analysis_count = OntologyAnalysis.query.join(OntologyFile).filter(OntologyFile.user_id == current_user.id).count()
        expression_count = FOLExpression.query.filter_by(user_id=current_user.id).count()
        
        # Get recent activity
        recent_analyses = OntologyAnalysis.query.join(OntologyFile).filter(
            OntologyFile.user_id == current_user.id
        ).order_by(OntologyAnalysis.analysis_date.desc()).limit(5).all()
        
        stats = {
            'ontology_count': ontology_count,
            'analysis_count': analysis_count,
            'expression_count': expression_count
        }
        
        return render_template('dashboard.html', 
                              title="User Dashboard",
                              ontologies=ontologies,
                              expressions=expressions,
                              recent_analyses=recent_analyses,
                              stats=stats)
    except Exception as e:
        app.logger.error(f"Error accessing dashboard: {str(e)}")
        flash(f"Error accessing dashboard: {str(e)}", 'error')
        return redirect(url_for('index'))

# Sandbox for ontology development
class DomainForm(FlaskForm):
    """Form for creating a new ontology in the sandbox."""
    title = StringField('Title', validators=[DataRequired(), Length(min=3, max=255)])
    domain = StringField('Domain', validators=[DataRequired(), Length(min=2, max=100)])
    subject = StringField('Subject', validators=[DataRequired(), Length(min=2, max=100)])
    description = StringField('Description', validators=[Length(max=500)])
    submit = SubmitField('Create Ontology')

@app.route('/sandbox')
def sandbox_list():
    """Show a list of sandbox ontologies for the current user or public ones."""
    try:
        if current_user.is_authenticated:
            # Get ontologies for the current user
            ontologies = SandboxOntology.query.filter_by(user_id=current_user.id).order_by(SandboxOntology.last_modified.desc()).all()
            # Get history files for the import from history modal
            history_files = OntologyFile.query.filter_by(user_id=current_user.id).order_by(OntologyFile.upload_date.desc()).all()
        else:
            # Get public ontologies
            # For anonymous users, we'll get a subset of history files
            ontologies = []
            history_files = OntologyFile.query.filter_by(user_id=None).order_by(OntologyFile.upload_date.desc()).limit(10).all()
            ontologies = SandboxOntology.query.order_by(SandboxOntology.last_modified.desc()).limit(20).all()
            
        return render_template('sandbox_list.html', ontologies=ontologies, history_files=history_files)
    except Exception as e:
        logger.error(f"Error listing sandbox ontologies: {str(e)}")
        flash(f"Error listing sandbox ontologies: {str(e)}", 'error')
        return redirect(url_for('index'))

@app.route('/sandbox/new', methods=['GET', 'POST'])
def sandbox_new():
    """Create a new sandbox ontology."""
    try:
        form = DomainForm()
        
        if form.validate_on_submit():
            # Create a new ontology
            ontology = SandboxOntology(
                title=form.title.data,
                domain=form.domain.data,
                subject=form.subject.data,
                description=form.description.data,
                user_id=current_user.id if current_user.is_authenticated else None
            )
            
            db.session.add(ontology)
            db.session.commit()
            
            flash('Ontology created successfully', 'success')
            return redirect(url_for('sandbox_view', ontology_id=ontology.id))
            
        return render_template('sandbox_new.html', form=form)
    except Exception as e:
        logger.error(f"Error creating sandbox ontology: {str(e)}")
        flash(f"Error creating sandbox ontology: {str(e)}", 'error')
        return redirect(url_for('sandbox_list'))

@app.route('/sandbox/<int:ontology_id>')
def sandbox_view(ontology_id):
    """View a sandbox ontology."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        
        # Get the ontology's classes, properties, and individuals
        classes = OntologyClass.query.filter_by(ontology_id=ontology_id).all()
        properties = OntologyProperty.query.filter_by(ontology_id=ontology_id).all()
        individuals = OntologyIndividual.query.filter_by(ontology_id=ontology_id).all()
        
        return render_template('sandbox_view.html', 
                             ontology=ontology,
                             classes=classes,
                             properties=properties,
                             individuals=individuals)
    except Exception as e:
        logger.error(f"Error viewing sandbox ontology: {str(e)}")
        flash(f"Error viewing sandbox ontology: {str(e)}", 'error')
        return redirect(url_for('sandbox_list'))

@app.route('/sandbox/<int:ontology_id>/edit')
def sandbox_edit(ontology_id):
    """Edit a sandbox ontology."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        
        # Check if the current user can edit this ontology
        if current_user.is_authenticated and ontology.user_id == current_user.id:
            # Get the ontology's classes and properties from the database
            ontology_classes = OntologyClass.query.filter_by(ontology_id=ontology_id).all()
            ontology_properties = OntologyProperty.query.filter_by(ontology_id=ontology_id).all()
            ontology_individuals = OntologyIndividual.query.filter_by(ontology_id=ontology_id).all()
            
            # Add the related objects to the ontology model for the template
            ontology.ontology_classes = ontology_classes
            ontology.ontology_properties = ontology_properties 
            ontology.ontology_individuals = ontology_individuals
            
            return render_template('sandbox_edit.html', ontology=ontology)
        else:
            flash('You do not have permission to edit this ontology', 'error')
            return redirect(url_for('sandbox_view', ontology_id=ontology_id))
    except Exception as e:
        logger.error(f"Error editing sandbox ontology: {str(e)}")
        flash(f"Error editing sandbox ontology: {str(e)}", 'error')
        return redirect(url_for('sandbox_list'))

@app.route('/sandbox/<int:ontology_id>/export_to_history')
def export_to_history(ontology_id):
    """Export a sandbox ontology to history for analysis."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        
        # Get the ontology's classes, properties, and individuals
        classes = OntologyClass.query.filter_by(ontology_id=ontology_id).all()
        properties = OntologyProperty.query.filter_by(ontology_id=ontology_id).all()
        individuals = OntologyIndividual.query.filter_by(ontology_id=ontology_id).all()
        
        # Generate OWL/RDF XML
        owl_xml = generate_owl_xml(ontology, classes, properties, individuals)
        
        # Create a temp file to save the OWL content
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.owl')
        temp_file.write(owl_xml.encode('utf-8'))
        temp_file_path = temp_file.name
        temp_file.close()
        
        # Generate a unique filename
        unique_filename = f"{ontology.title.replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.owl"
        
        # Define the destination path (uploads directory)
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        dest_path = os.path.join(upload_dir, unique_filename)
        
        # Copy the temp file to the uploads directory
        import shutil
        shutil.copy2(temp_file_path, dest_path)
        
        # Clean up the temp file
        os.unlink(temp_file_path)
        
        # Create a new OntologyFile record
        file_size = os.path.getsize(dest_path)
        file_record = OntologyFile(
            filename=unique_filename,
            original_filename=f"{ontology.title}.owl",
            file_path=dest_path,
            file_size=file_size,
            mime_type='application/rdf+xml',
            user_id=current_user.id if not current_user.is_anonymous else None,
            from_sandbox=True,
            sandbox_ontology_id=ontology.id
        )
        
        db.session.add(file_record)
        db.session.commit()
        
        flash(f"Ontology '{ontology.title}' exported to History.", 'success')
        
        # Redirect to analyze the new file
        return redirect(url_for('analyze_owl', filename=unique_filename, original_name=f"{ontology.title}.owl", file_id=file_record.id))
    except Exception as e:
        logger.error(f"Error exporting sandbox ontology to history: {str(e)}")
        flash(f"Error exporting sandbox ontology to history: {str(e)}", 'error')
        return redirect(url_for('sandbox_view', ontology_id=ontology_id))

@app.route('/sandbox/<int:ontology_id>/download')
def sandbox_download(ontology_id):
    """Download a sandbox ontology as OWL/RDF."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        
        # Get the ontology's classes, properties, and individuals
        classes = OntologyClass.query.filter_by(ontology_id=ontology_id).all()
        properties = OntologyProperty.query.filter_by(ontology_id=ontology_id).all()
        individuals = OntologyIndividual.query.filter_by(ontology_id=ontology_id).all()
        
        # Generate OWL/RDF XML
        owl_xml = generate_owl_xml(ontology, classes, properties, individuals)
        
        # Create a response with the XML
        response = make_response(owl_xml)
        response.headers['Content-Type'] = 'application/rdf+xml'
        response.headers['Content-Disposition'] = f'attachment; filename={ontology.title.replace(" ", "_")}.owl'
        
        return response
    except Exception as e:
        logger.error(f"Error downloading sandbox ontology: {str(e)}")
        flash(f"Error downloading sandbox ontology: {str(e)}", 'error')
        return redirect(url_for('sandbox_view', ontology_id=ontology_id))

@app.route('/api/sandbox/<int:ontology_id>/classes', methods=['GET', 'POST'])
def api_sandbox_classes(ontology_id: int) -> Union[Response, tuple[Response, int]]:
    """API for sandbox ontology classes."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        
        if request.method == 'GET':
            # Return all classes for this ontology
            classes = OntologyClass.query.filter_by(ontology_id=ontology_id).all()
            
            result = []
            for cls in classes:
                result.append({
                    'id': cls.id,
                    'name': cls.name,
                    'description': cls.description,
                    'bfo_category': cls.bfo_category,
                    'parent_id': cls.parent_id,
                    'properties': cls.properties
                })
            
            return jsonify(result)
            
        elif request.method == 'POST':
            # Check if the current user can edit this ontology
            if not current_user.is_authenticated or ontology.user_id != current_user.id:
                return jsonify({'error': 'You do not have permission to edit this ontology'}), 403
                
            # Create a new class
            data = request.get_json()
            
            if not data or 'name' not in data:
                return jsonify({'error': 'Name is required'}), 400
                
            name = data.get('name')
            description = data.get('description', '')
            bfo_category = data.get('bfo_category')
            parent_id = data.get('parent_id')
            properties = data.get('properties', {})
            
            # Create the class
            cls = OntologyClass(
                ontology_id=ontology_id,
                name=name,
                description=description,
                bfo_category=bfo_category,
                parent_id=parent_id,
                properties=properties
            )
            
            db.session.add(cls)
            db.session.commit()
            
            # Update the ontology's last_modified timestamp
            ontology.last_modified = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'id': cls.id,
                'name': cls.name,
                'description': cls.description,
                'bfo_category': cls.bfo_category,
                'parent_id': cls.parent_id,
                'properties': cls.properties
            })
            
    except Exception as e:
        logger.error(f"Error in API sandbox classes: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sandbox/<int:ontology_id>/classes/<int:class_id>', methods=['GET', 'PUT', 'DELETE'])
def api_sandbox_class(ontology_id, class_id):
    """API for a specific sandbox ontology class."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        cls = OntologyClass.query.filter_by(id=class_id, ontology_id=ontology_id).first_or_404()
        
        if request.method == 'GET':
            # Return the class
            return jsonify({
                'id': cls.id,
                'name': cls.name,
                'description': cls.description,
                'bfo_category': cls.bfo_category,
                'parent_id': cls.parent_id,
                'properties': cls.properties
            })
            
        elif request.method == 'PUT':
            # Check if the current user can edit this ontology
            if not current_user.is_authenticated or ontology.user_id != current_user.id:
                return jsonify({'error': 'You do not have permission to edit this ontology'}), 403
                
            # Update the class
            data = request.get_json()
            
            if 'name' in data:
                cls.name = data.get('name')
            if 'description' in data:
                cls.description = data.get('description')
            if 'bfo_category' in data:
                cls.bfo_category = data.get('bfo_category')
            if 'parent_id' in data:
                cls.parent_id = data.get('parent_id')
            if 'properties' in data:
                cls.properties = data.get('properties')
            
            # Update the ontology's last_modified timestamp
            ontology.last_modified = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'id': cls.id,
                'name': cls.name,
                'description': cls.description,
                'bfo_category': cls.bfo_category,
                'parent_id': cls.parent_id,
                'properties': cls.properties
            })
            
        elif request.method == 'DELETE':
            # Check if the current user can edit this ontology
            if not current_user.is_authenticated or ontology.user_id != current_user.id:
                return jsonify({'error': 'You do not have permission to edit this ontology'}), 403
                
            # Delete the class
            db.session.delete(cls)
            
            # Update the ontology's last_modified timestamp
            ontology.last_modified = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({'success': True})
            
    except Exception as e:
        logger.error(f"Error in API sandbox class: {str(e)}")
        return jsonify({'error': str(e)}), 500

def generate_owl_xml(ontology, classes, properties, individuals):
    """Generate OWL/RDF XML for a sandbox ontology."""
    # Basic structure for the OWL/RDF XML
    xml = f"""<?xml version="1.0"?>
<rdf:RDF xmlns="http://www.w3.org/2002/07/owl#"
     xml:base="http://www.semanticweb.org/ontology/{ontology.id}"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:xml="http://www.w3.org/XML/1998/namespace"
     xmlns:xsd="http://www.w3.org/2001/XMLSchema#"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
    <Ontology rdf:about="http://www.semanticweb.org/ontology/{ontology.id}">
        <rdfs:label>{escape(ontology.title)}</rdfs:label>
        <rdfs:comment>{escape(ontology.description or '')}</rdfs:comment>
    </Ontology>
    
    <!-- Classes -->
"""
    
    # Add classes
    for cls in classes:
        xml += f"""    <Class rdf:about="#{cls.name}">
        <rdfs:label>{escape(cls.name)}</rdfs:label>
        <rdfs:comment>{escape(cls.description or '')}</rdfs:comment>
"""
        
        # Add BFO category if defined
        if cls.bfo_category:
            xml += f"""        <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/BFO_{cls.bfo_category}"/>
"""
        
        # Add parent class if defined
        if cls.parent_id:
            parent = next((c for c in classes if c.id == cls.parent_id), None)
            if parent:
                xml += f"""        <rdfs:subClassOf rdf:resource="#{parent.name}"/>
"""
        
        xml += """    </Class>
"""
    
    # Add properties
    xml += """
    <!-- Object Properties -->
"""
    for prop in properties:
        if prop.property_type == 'object':
            xml += f"""    <ObjectProperty rdf:about="#{prop.name}">
        <rdfs:label>{escape(prop.name)}</rdfs:label>
        <rdfs:comment>{escape(prop.description or '')}</rdfs:comment>
"""
            
            # Add domain and range if defined
            if prop.domain_class_id:
                domain_class = next((c for c in classes if c.id == prop.domain_class_id), None)
                if domain_class:
                    xml += f"""        <rdfs:domain rdf:resource="#{domain_class.name}"/>
"""
            
            if prop.range_class_id:
                range_class = next((c for c in classes if c.id == prop.range_class_id), None)
                if range_class:
                    xml += f"""        <rdfs:range rdf:resource="#{range_class.name}"/>
"""
            
            xml += """    </ObjectProperty>
"""
    
    # Add data properties
    xml += """
    <!-- Data Properties -->
"""
    for prop in properties:
        if prop.property_type == 'data':
            xml += f"""    <DatatypeProperty rdf:about="#{prop.name}">
        <rdfs:label>{escape(prop.name)}</rdfs:label>
        <rdfs:comment>{escape(prop.description or '')}</rdfs:comment>
"""
            
            # Add domain if defined
            if prop.domain_class_id:
                domain_class = next((c for c in classes if c.id == prop.domain_class_id), None)
                if domain_class:
                    xml += f"""        <rdfs:domain rdf:resource="#{domain_class.name}"/>
"""
            
            # Add range - typically xsd:string for data properties
            xml += """        <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#string"/>
    </DatatypeProperty>
"""
    
    # Add annotation properties
    xml += """
    <!-- Annotation Properties -->
"""
    for prop in properties:
        if prop.property_type == 'annotation':
            xml += f"""    <AnnotationProperty rdf:about="#{prop.name}">
        <rdfs:label>{escape(prop.name)}</rdfs:label>
        <rdfs:comment>{escape(prop.description or '')}</rdfs:comment>
    </AnnotationProperty>
"""
    
    # Add individuals
    xml += """
    <!-- Individuals -->
"""
    for ind in individuals:
        xml += f"""    <NamedIndividual rdf:about="#{ind.name}">
        <rdfs:label>{escape(ind.name)}</rdfs:label>
        <rdfs:comment>{escape(ind.description or '')}</rdfs:comment>
"""
        
        # Add type/class
        if ind.class_id:
            ind_class = next((c for c in classes if c.id == ind.class_id), None)
            if ind_class:
                xml += f"""        <rdf:type rdf:resource="#{ind_class.name}"/>
"""
        
        # Add property values
        if ind.property_values:
            for prop_id, value in ind.property_values.items():
                prop = next((p for p in properties if p.id == int(prop_id)), None)
                if prop:
                    if prop.property_type == 'object':
                        # Object property - reference another individual
                        target_ind = next((i for i in individuals if i.id == int(value)), None)
                        if target_ind:
                            xml += f"""        <{prop.name} rdf:resource="#{target_ind.name}"/>
"""
                    elif prop.property_type == 'data':
                        # Data property - literal value
                        xml += f"""        <{prop.name}>{escape(value)}</{prop.name}>
"""
                    elif prop.property_type == 'annotation':
                        # Annotation property
                        xml += f"""        <{prop.name}>{escape(value)}</{prop.name}>
"""
        
        xml += """    </NamedIndividual>
"""
    
    # Close the RDF element
    xml += """</rdf:RDF>
"""
    
    return xml

@app.route('/api/sandbox/ai/suggestions', methods=['GET', 'POST'])
def api_sandbox_ai_suggestions():
    """API endpoint to get AI-generated class and property suggestions for an ontology domain."""
    logger.info(f"AI suggestions endpoint called with method: {request.method}")
    try:
        request_type = 'classes'  # Default to classes
        
        if request.method == 'GET':
            # Handle GET requests
            domain = request.args.get('domain')
            subject = request.args.get('subject')
            request_type = request.args.get('type', 'classes')
            if not domain or not subject:
                return jsonify({'error': 'Domain and subject are required'}), 400
        else:
            # Handle POST requests
            data = request.get_json()
            if not data or 'domain' not in data or 'subject' not in data:
                return jsonify({'error': 'Domain and subject are required'}), 400
            domain = data.get('domain')
            subject = data.get('subject')
            request_type = data.get('type', 'classes')
        
        logger.info(f"Generating suggestions for domain: {domain}, subject: {subject}, type: {request_type}")
        
        # Call the OpenAI function to generate suggestions
        if request_type == 'properties':
            # Generate property suggestions
            suggestions = suggest_ontology_properties(domain, subject)
        else:
            # Generate class suggestions
            suggestions = suggest_ontology_classes(domain, subject)
        
        return jsonify(suggestions)
        
    except Exception as e:
        logger.error(f"Error generating AI suggestions: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sandbox/ai/bfo-category', methods=['POST'])
def api_sandbox_ai_bfo_category():
    """API endpoint to suggest a BFO category for a class."""
    try:
        data = request.get_json()
        
        if not data or 'class_name' not in data:
            return jsonify({'error': 'Class name is required'}), 400
            
        class_name = data.get('class_name')
        description = data.get('description', '')
        
        # Call the OpenAI function to suggest a BFO category
        suggestion = suggest_bfo_category(class_name, description)
        
        return jsonify(suggestion)
        
    except Exception as e:
        logger.error(f"Error suggesting BFO category: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sandbox/<int:ontology_id>/properties', methods=['GET', 'POST'])
def api_sandbox_properties(ontology_id: int) -> Union[Response, tuple[Response, int]]:
    """API for sandbox ontology properties."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        
        if request.method == 'GET':
            # Return all properties for this ontology
            properties = OntologyProperty.query.filter_by(ontology_id=ontology_id).all()
            
            result = []
            for prop in properties:
                result.append({
                    'id': prop.id,
                    'name': prop.name,
                    'description': prop.description,
                    'property_type': prop.property_type,
                    'domain_class_id': prop.domain_class_id,
                    'range_class_id': prop.range_class_id,
                    'property_metadata': prop.property_metadata
                })
            
            return jsonify(result)
            
        elif request.method == 'POST':
            # Check if the current user can edit this ontology
            if not current_user.is_authenticated or ontology.user_id != current_user.id:
                return jsonify({'error': 'You do not have permission to edit this ontology'}), 403
                
            # Create a new property
            data = request.get_json()
            
            if not data or 'name' not in data or 'property_type' not in data:
                return jsonify({'error': 'Name and property_type are required'}), 400
                
            name = data.get('name')
            description = data.get('description', '')
            property_type = data.get('property_type')
            domain_class_id = data.get('domain_class_id')
            range_class_id = data.get('range_class_id')
            property_metadata = data.get('property_metadata', {})
            
            # Create the property
            prop = OntologyProperty(
                ontology_id=ontology_id,
                name=name,
                description=description,
                property_type=property_type,
                domain_class_id=domain_class_id,
                range_class_id=range_class_id,
                property_metadata=property_metadata
            )
            
            db.session.add(prop)
            
            # Update the ontology's last_modified timestamp
            ontology.last_modified = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'id': prop.id,
                'name': prop.name,
                'description': prop.description,
                'property_type': prop.property_type,
                'domain_class_id': prop.domain_class_id,
                'range_class_id': prop.range_class_id,
                'property_metadata': prop.property_metadata
            })
            
    except Exception as e:
        logger.error(f"Error in API sandbox properties: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sandbox/<int:ontology_id>/properties/<int:property_id>', methods=['GET', 'PUT', 'DELETE'])
def api_sandbox_property(ontology_id: int, property_id: int) -> Union[Response, tuple[Response, int]]:
    """API for a specific sandbox ontology property."""
    try:
        ontology = SandboxOntology.query.get_or_404(ontology_id)
        prop = OntologyProperty.query.filter_by(id=property_id, ontology_id=ontology_id).first_or_404()
        
        if request.method == 'GET':
            # Return the property
            return jsonify({
                'id': prop.id,
                'name': prop.name,
                'description': prop.description,
                'property_type': prop.property_type,
                'domain_class_id': prop.domain_class_id,
                'range_class_id': prop.range_class_id,
                'property_metadata': prop.property_metadata
            })
            
        elif request.method == 'PUT':
            # Check if the current user can edit this ontology
            if not current_user.is_authenticated or ontology.user_id != current_user.id:
                return jsonify({'error': 'You do not have permission to edit this ontology'}), 403
                
            # Update the property
            data = request.get_json()
            
            if 'name' in data:
                prop.name = data.get('name')
            if 'description' in data:
                prop.description = data.get('description')
            if 'property_type' in data:
                prop.property_type = data.get('property_type')
            if 'domain_class_id' in data:
                prop.domain_class_id = data.get('domain_class_id')
            if 'range_class_id' in data:
                prop.range_class_id = data.get('range_class_id')
            if 'property_metadata' in data:
                prop.property_metadata = data.get('property_metadata')
            
            # Update the ontology's last_modified timestamp
            ontology.last_modified = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'id': prop.id,
                'name': prop.name,
                'description': prop.description,
                'property_type': prop.property_type,
                'domain_class_id': prop.domain_class_id,
                'range_class_id': prop.range_class_id,
                'property_metadata': prop.property_metadata
            })
            
        elif request.method == 'DELETE':
            # Check if the current user can edit this ontology
            if not current_user.is_authenticated or ontology.user_id != current_user.id:
                return jsonify({'error': 'You do not have permission to edit this ontology'}), 403
                
            # Delete the property
            db.session.delete(prop)
            
            # Update the ontology's last_modified timestamp
            ontology.last_modified = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({'success': True})
            
    except Exception as e:
        logger.error(f"Error in API sandbox property: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sandbox/ai/description', methods=['POST'])
def api_sandbox_ai_description():
    """API endpoint to generate a description for a class."""
    try:
        data = request.get_json()
        
        if not data or 'class_name' not in data:
            return jsonify({'error': 'Class name is required'}), 400
            
        class_name = data.get('class_name')
        
        # Call the OpenAI function to generate a description
        result = generate_class_description(class_name)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error generating class description: {str(e)}")
        return jsonify({'error': str(e)}), 500