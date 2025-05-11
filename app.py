import os
import logging
import uuid
import datetime
import base64
import re
from html import escape
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, session, make_response
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
from improved_openai_utils import suggest_ontology_classes, suggest_bfo_category, generate_class_description  
from openai_utils import generate_real_world_implications
# Import the preprocess_expression function for handling comma-separated quantifiers
from owl_preprocessor import preprocess_expression

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

# Load the default OwlTester
logger.info("Initializing OwlTester...")
try:
    owl_tester = OwlTester()
    logger.info(f"Successfully loaded {len(owl_tester.get_bfo_classes())} BFO classes and {len(owl_tester.get_bfo_relations())} relations")
except Exception as e:
    logger.error(f"Error initializing OwlTester: {str(e)}")
    owl_tester = None

@app.route('/')
def index():
    """Render the main page."""
    if owl_tester is None:
        return render_template('index.html', error="OwlTester is not initialized properly")
    
    # Format BFO classes as a list with id and label attributes for the template
    bfo_classes_dict = owl_tester.get_bfo_classes()
    bfo_classes = []
    for key, data in bfo_classes_dict.items():
        bfo_classes.append({
            'id': key,
            'label': data['label'],
            'description': data.get('description', '')
        })
    
    # Format BFO relations as a list with id and label attributes for the template
    bfo_relations_dict = owl_tester.get_bfo_relations()
    bfo_relations = []
    for key, data in bfo_relations_dict.items():
        bfo_relations.append({
            'id': key,
            'label': data['label'],
            'description': data.get('description', '')
        })
    
    return render_template('index.html', 
                           bfo_classes=bfo_classes,
                           bfo_relations=bfo_relations)

@app.route('/about')
def about():
    """Render the about page with information about FOL-BFO-OWL testing."""
    return render_template('about.html')

@app.route('/api/test', methods=['POST'])
def test_expression():
    """API endpoint to test a FOL expression."""
    if owl_tester is None:
        return jsonify({"error": "OwlTester is not initialized properly"}), 500
    
    data = request.get_json()
    if not data or 'expression' not in data:
        return jsonify({"error": "No expression provided"}), 400
    
    expression = data['expression']
    logger.debug(f"Testing expression: {expression}")
    
    # Check if the expression contains comma-separated quantifiers and needs preprocessing
    needs_preprocessing = ',' in expression and re.search(r'(forall|exists)\s+\w+\s*,', expression)
    if needs_preprocessing:
        processed_expr = preprocess_expression(expression)
        logger.debug(f"Preprocessed expression: {processed_expr}")
    else:
        processed_expr = expression
    
    try:
        result = owl_tester.test_expression(processed_expr)
        
        # Add preprocessing info to the result
        if needs_preprocessing:
            result['preprocessed'] = True
            result['original_expression'] = expression
            result['preprocessed_expression'] = processed_expr
        
        # Save the test result to the database
        # Associate expression with current user if logged in
        user_id = current_user.id if current_user.is_authenticated else None
        
        fol_expression = FOLExpression()
        fol_expression.expression = expression
        fol_expression.is_valid = result.get('valid', False)
        fol_expression.test_results = result
        fol_expression.issues = result.get('issues', [])
        fol_expression.bfo_classes_used = result.get('bfo_classes_used', [])
        fol_expression.bfo_relations_used = result.get('bfo_relations_used', []) 
        fol_expression.non_bfo_terms = result.get('non_bfo_terms', [])
        fol_expression.user_id = user_id
        db.session.add(fol_expression)
        db.session.commit()
        logger.info(f"Saved FOL expression test results to database with ID {fol_expression.id}")
        
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error testing expression: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/api/bfo-classes')
def get_bfo_classes():
    """API endpoint to get all BFO classes."""
    if owl_tester is None:
        return jsonify({"error": "OwlTester is not initialized properly"}), 500
    
    # Format BFO classes as a list with id and label attributes
    bfo_classes_dict = owl_tester.get_bfo_classes()
    bfo_classes = []
    for key, data in bfo_classes_dict.items():
        bfo_classes.append({
            'id': key,
            'label': data['label'],
            'description': data.get('description', '')
        })
    
    return jsonify({"classes": bfo_classes})

@app.route('/api/bfo-relations')
def get_bfo_relations():
    """API endpoint to get all BFO relations."""
    if owl_tester is None:
        return jsonify({"error": "OwlTester is not initialized properly"}), 500
    
    # Format BFO relations as a list with id and label attributes
    bfo_relations_dict = owl_tester.get_bfo_relations()
    bfo_relations = []
    for key, data in bfo_relations_dict.items():
        bfo_relations.append({
            'id': key,
            'label': data['label'],
            'description': data.get('description', '')
        })
    
    return jsonify({"relations": bfo_relations})

@app.route('/api/validate-completeness/<int:analysis_id>', methods=['GET'])
def validate_ontology_completeness(analysis_id):
    """
    Validate the completeness of an ontology by checking if all elements are included in FOL premises.
    
    Returns detailed report about missing classes, properties, and individuals.
    """
    try:
        # Find the analysis
        analysis = OntologyAnalysis.query.get(analysis_id)
        if not analysis:
            return jsonify({"error": "Analysis not found"}), 404
            
        # Get the ontology file
        ontology_file = OntologyFile.query.get(analysis.ontology_file_id)
        if not ontology_file:
            return jsonify({"error": "Ontology file not found"}), 404
            
        # Create a custom tester for this ontology
        try:
            custom_tester = OwlTester()
            # Load the ontology file
            result = custom_tester.load_ontology_from_file(ontology_file.file_path)
            
            if isinstance(result, dict) and not result.get('loaded', False):
                # If load_ontology_from_file returns a dictionary with loaded=False
                error_msg = result.get('error', 'Unknown error')
                raise Exception(f"Failed to load ontology for completeness validation: {error_msg}")
            
            # Get the ontology object from the result
            onto = None
            if isinstance(result, dict) and 'ontology' in result:
                onto = result.get('ontology')
            
            if not onto:
                raise Exception("Loaded ontology object not found in result")
        except Exception as e:
            logger.error(f"Error loading ontology for completeness validation: {str(e)}")
            raise e
        
        # Perform completeness validation
        completeness_report = custom_tester.validate_completeness(onto)
        
        # Store the result in the database if possible
        # Update analysis model if needed - for now just return
        
        logger.info(f"Validated completeness for analysis ID {analysis_id}: {completeness_report.get('complete')}")
        
        return jsonify({
            "success": True,
            "completeness": completeness_report
        })
        
    except Exception as e:
        logger.error(f"Error validating completeness: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Error validating completeness: {str(e)}"
        }), 500

@app.route('/api/enhanced-consistency/<int:analysis_id>', methods=['GET'])
def check_enhanced_consistency(analysis_id):
    """
    Perform enhanced consistency checking using multiple reasoners.
    
    Returns detailed report about contradictions and problematic axioms.
    """
    try:
        # Find the analysis
        analysis = OntologyAnalysis.query.get(analysis_id)
        if not analysis:
            return jsonify({"error": "Analysis not found"}), 404
            
        # Get the ontology file
        ontology_file = OntologyFile.query.get(analysis.ontology_file_id)
        if not ontology_file:
            return jsonify({"error": "Ontology file not found"}), 404
            
        # Create a custom tester for this ontology
        try:
            custom_tester = OwlTester()
            # Load the ontology file
            result = custom_tester.load_ontology_from_file(ontology_file.file_path)
            
            if isinstance(result, dict) and not result.get('loaded', False):
                # If load_ontology_from_file returns a dictionary with loaded=False
                error_msg = result.get('error', 'Unknown error')
                raise Exception(f"Failed to load ontology for enhanced consistency: {error_msg}")
            
            # Get the ontology object from the result
            onto = None
            if isinstance(result, dict) and 'ontology' in result:
                onto = result.get('ontology')
            
            if not onto:
                raise Exception("Loaded ontology object not found in result")
        except Exception as e:
            logger.error(f"Error loading ontology for enhanced consistency: {str(e)}")
            raise e
        
        # Perform enhanced consistency checking
        consistency_report = custom_tester.check_consistency(onto)
        
        # Update the analysis record if possible
        analysis.consistency_issues = consistency_report
        db.session.commit()
        
        logger.info(f"Checked enhanced consistency for analysis ID {analysis_id}: {consistency_report.get('consistent')}")
        
        return jsonify({
            "success": True,
            "consistency": consistency_report
        })
        
    except Exception as e:
        logger.error(f"Error checking enhanced consistency: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"Error checking enhanced consistency: {str(e)}"
        }), 500

@app.route('/upload', methods=['GET', 'POST'])
def upload_owl():
    """Handle OWL file upload and redirection to analysis page."""
    if request.method == 'POST' and 'owl_file' in request.files:
        # Get the file
        file = request.files['owl_file']
        
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if not allowed_file(file.filename):
            flash('Invalid file type. Please upload an OWL/RDF file (.owl, .rdf, .xml, .ttl, .n3, .nt, .ofn, .own, .owx)', 'error')
            return redirect(request.url)
        
        try:
            # Generate a unique filename to avoid collisions
            filename = file.filename or "unknown_file.owl"
            original_filename = secure_filename(filename)
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            
            # Save the file
            file_path = os.path.join(app.config['UPLOADED_OWLS_DEST'], unique_filename)
            file.save(file_path)
            
            # Save file info to the database
            file_size = os.path.getsize(file_path)
            mime_type = file.content_type if hasattr(file, 'content_type') else 'application/rdf+xml'
            
            # Associate file with current user if logged in
            user_id = current_user.id if current_user.is_authenticated else None
            
            ontology_file = OntologyFile()
            ontology_file.filename = unique_filename
            ontology_file.original_filename = original_filename
            ontology_file.file_path = file_path
            ontology_file.file_size = file_size
            ontology_file.mime_type = mime_type
            ontology_file.user_id = user_id
            db.session.add(ontology_file)
            db.session.commit()
            
            logger.info(f"File uploaded: {original_filename} (saved as {unique_filename}) with ID {ontology_file.id}")
            
            # Redirect to the analysis page
            return redirect(url_for('analyze_owl', filename=unique_filename, 
                                   original_name=original_filename, 
                                   file_id=ontology_file.id))
            
        except Exception as e:
            logger.error(f"Error during file upload: {str(e)}")
            flash(f"Error during file upload: {str(e)}", 'error')
            return redirect(request.url)
    
    # GET request - render upload form
    return render_template('upload.html')

@app.route('/analyze/<filename>')
def analyze_owl(filename):
    """Analyze an uploaded OWL file and display results."""
    try:
        # Get the original filename from query parameters
        original_name = request.args.get('original_name', filename)
        file_id = request.args.get('file_id')
        
        # Construct full path to the file
        file_path = os.path.join(app.config['UPLOADED_OWLS_DEST'], filename)
        
        if not os.path.exists(file_path):
            flash('File not found', 'error')
            return redirect(url_for('upload_owl'))
        
        # Create a new OwlTester instance
        custom_tester = OwlTester()
        
        # Load the ontology file
        result = custom_tester.load_ontology_from_file(file_path)
        
        if isinstance(result, dict) and not result.get('loaded', False):
            # If load_ontology_from_file returns a dictionary with loaded=False
            error_msg = result.get('error', 'Unknown error')
            flash(f"Failed to load ontology: {error_msg}", 'error')
            return redirect(url_for('upload_owl'))
        
        # Get the ontology object from the result
        onto = None
        if isinstance(result, dict) and 'ontology' in result:
            onto = result.get('ontology')
        
        if not onto:
            flash("Loaded ontology object not found in result", 'error')
            return redirect(url_for('upload_owl'))
        
        # Generate analysis report with the ontology object
        analysis = custom_tester.analyze_ontology(onto)
        
        # Generate PlantUML diagram code
        from plantuml_generator import PlantUMLGenerator
        plant_generator = PlantUMLGenerator()
        plantuml_code, diagram_path, svg_path = plant_generator.generate_class_diagram(
            onto, 
            filename_base=os.path.splitext(filename)[0],  # Use the current filename as base
            include_individuals=False,
            include_data_properties=True,
            include_annotation_properties=False,
            max_classes=1000  # Increased to show more classes
        )
        
        # plantuml_code is already populated from generate_class_diagram
        
        # Save analysis to database if we have a file_id
        if file_id:
            try:
                ontology_file = OntologyFile.query.get(int(file_id))
                if ontology_file:
                    # Create analysis record
                    ontology_analysis = OntologyAnalysis()
                    ontology_analysis.ontology_file_id = ontology_file.id
                    ontology_analysis.ontology_name = analysis.get('ontology_name', 'Unknown')
                    ontology_analysis.ontology_iri = analysis.get('ontology_iri', '')
                    ontology_analysis.is_consistent = analysis.get('consistency', {}).get('consistent', True)
                    ontology_analysis.class_count = analysis.get('class_count', 0)
                    ontology_analysis.object_property_count = analysis.get('object_property_count', 0)
                    ontology_analysis.data_property_count = analysis.get('data_property_count', 0)
                    ontology_analysis.individual_count = analysis.get('individual_count', 0)
                    ontology_analysis.annotation_property_count = analysis.get('annotation_property_count', 0)
                    ontology_analysis.axiom_count = analysis.get('axiom_count', 0)
                    ontology_analysis.expressivity = analysis.get('expressivity', '')
                    ontology_analysis.complexity = analysis.get('complexity', 0)
                    ontology_analysis.axioms = analysis.get('axioms', [])
                    ontology_analysis.consistency_issues = analysis.get('consistency', {}).get('issues', [])
                    ontology_analysis.inferred_axioms = analysis.get('inferred', [])
                    ontology_analysis.fol_premises = analysis.get('fol_premises', [])
                    db.session.add(ontology_analysis)
                    db.session.commit()
                    logger.info(f"Saved analysis to database with ID {ontology_analysis.id}")
            except Exception as e:
                logger.error(f"Error saving analysis to database: {str(e)}")
                # Continue with the analysis even if saving to DB fails
        
        # Debug log to see what fields are in the analysis
        logger.info(f"Analysis keys: {list(analysis.keys())}")
        if 'stats' in analysis:
            logger.info(f"Stats: {analysis['stats']}")
        
        # Move stats to the top level for easier access in the template
        if 'stats' in analysis:
            # Move stats fields to the top level of the analysis object
            for key, value in analysis['stats'].items():
                analysis[key] = value
        
        # Add total axiom count if not present
        if 'axioms' in analysis and isinstance(analysis['axioms'], list):
            analysis['axiom_count'] = len(analysis['axioms'])
            
        # Add expressivity from metrics if available
        if 'metrics' in analysis and 'expressivity' in analysis['metrics']:
            analysis['expressivity'] = analysis['metrics']['expressivity']
            
        # Add complexity from metrics if available
        if 'metrics' in analysis and 'complexity' in analysis['metrics']:
            analysis['complexity'] = analysis['metrics']['complexity']
            
        # Debug log to show what fields are now in the analysis
        logger.info(f"Updated analysis keys: {list(analysis.keys())}")
        logger.info(f"Class count: {analysis.get('class_count')}")
        logger.info(f"Object property count: {analysis.get('object_property_count')}")
        logger.info(f"Data property count: {analysis.get('data_property_count')}")
        logger.info(f"Individual count: {analysis.get('individual_count')}")
        logger.info(f"Axiom count: {analysis.get('axiom_count')}")
        
        # Update analysis with completeness validation if available
        if 'completeness' in analysis:
            logger.info(f"Completeness data available: {analysis['completeness']}")
        
        # Add analysis ID for API calls
        analysis_id = None
        try:
            # Try to get the analysis ID if we saved to DB
            if file_id:
                ont_analysis = OntologyAnalysis.query.filter_by(ontology_file_id=int(file_id)).order_by(OntologyAnalysis.id.desc()).first()
                if ont_analysis:
                    analysis_id = ont_analysis.id
                    logger.info(f"Using analysis ID {analysis_id} for API calls")
        except Exception as e:
            logger.error(f"Error getting analysis ID: {str(e)}")
        
        # Render enhanced analysis template with results
        return render_template('analysis_enhanced.html', 
                              original_filename=original_name,
                              filename=filename,
                              file_id=file_id,
                              analysis_id=analysis_id,
                              analysis=analysis,
                              plantuml_code=plantuml_code)
                              
    except Exception as e:
        logger.error(f"Error analyzing OWL file: {str(e)}")
        flash(f"Error analyzing OWL file: {str(e)}", 'error')
        return redirect(url_for('upload_owl'))

@app.route('/api/analyze/<filename>', methods=['GET'])
def api_analyze_owl(filename):
    """API endpoint for analyzing an uploaded OWL file."""
    try:
        # Construct full path to the file
        file_path = os.path.join(app.config['UPLOADED_OWLS_DEST'], filename)
        
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404
        
        # Create a new OwlTester instance
        custom_tester = OwlTester()
        
        # Load the ontology file
        result = custom_tester.load_ontology_from_file(file_path)
        
        if isinstance(result, dict) and not result.get('loaded', False):
            # If load_ontology_from_file returns a dictionary with loaded=False
            error_msg = result.get('error', 'Unknown error')
            return jsonify({"error": f"Failed to load ontology: {error_msg}"}), 400
        
        # Get the ontology object from the result
        onto = None
        if isinstance(result, dict) and 'ontology' in result:
            onto = result.get('ontology')
        
        if not onto:
            return jsonify({"error": "Loaded ontology object not found in result"}), 400
        
        # Generate analysis report with the ontology object
        analysis = custom_tester.analyze_ontology(onto)
        
        # Move stats to top level for API consistency
        if 'stats' in analysis:
            for key, value in analysis['stats'].items():
                analysis[key] = value
            # Log the update for debugging
            logger.info(f"API endpoint updated keys: {list(analysis.keys())}")
            
        # Add total axiom count if not present
        if 'axioms' in analysis and isinstance(analysis['axioms'], list):
            analysis['axiom_count'] = len(analysis['axioms'])
        
        # Add expressivity and complexity from metrics if available
        if 'metrics' in analysis:
            if 'expressivity' in analysis['metrics']:
                analysis['expressivity'] = analysis['metrics']['expressivity']
            if 'complexity' in analysis['metrics']:
                analysis['complexity'] = analysis['metrics']['complexity']
        
        return jsonify(analysis)
        
    except Exception as e:
        logger.error(f"Error in API analyzing OWL file: {str(e)}")
        return jsonify({"error": f"Error analyzing OWL file: {str(e)}"}), 500

@app.route('/api/implications/<int:analysis_id>', methods=['GET', 'POST'])
def generate_implications(analysis_id):
    """
    Generate or retrieve real-world implications for an ontology analysis.
    
    GET: Retrieve previously generated implications
    POST: Generate new implications
    """
    try:
        # Find the analysis
        analysis = OntologyAnalysis.query.get(analysis_id)
        if not analysis:
            return jsonify({"error": "Analysis not found"}), 404
            
        # Check if implications already exist and this is a GET request
        if request.method == 'GET' and analysis.implications_generated and analysis.real_world_implications:
            return jsonify({"implications": analysis.real_world_implications})
        
        # For POST requests, generate new implications
        if request.method == 'POST':
            # Get the ontology file
            ontology_file = OntologyFile.query.get(analysis.ontology_file_id)
            if not ontology_file:
                return jsonify({"error": "Ontology file not found"}), 404
                
            # Create a custom tester for this ontology
            custom_tester = OwlTester()
            
            # Load the ontology file
            result = custom_tester.load_ontology_from_file(ontology_file.file_path)
            
            if isinstance(result, dict) and not result.get('loaded', False):
                # If load_ontology_from_file returns a dictionary with loaded=False
                error_msg = result.get('error', 'Unknown error')
                raise Exception(f"Failed to load ontology for implications: {error_msg}")
            
            # Get the ontology object from the result
            onto = None
            if isinstance(result, dict) and 'ontology' in result:
                onto = result.get('ontology')
            
            if not onto:
                raise Exception("Loaded ontology object not found in result")
            
            # Get parameters
            num_implications = request.args.get('count', 5, type=int)
            comprehensive = request.args.get('comprehensive', False, type=bool)
            
            implications = []
            
            if comprehensive:
                # Use the new comprehensive method that generates implications for all premise types
                logger.info(f"Generating comprehensive implications for analysis ID {analysis_id}")
                implications = custom_tester.generate_all_implications(
                    onto,
                    num_implications_per_premise=max(1, int(num_implications/5))
                )
            else:
                # Use the original method
                logger.info(f"Generating standard implications for analysis ID {analysis_id}")
                # Get domain classes and ontology name for the generate_real_world_implications function
                domain_classes = custom_tester.bfo_classes
                ontology_name = analysis.ontology_name or "Ontology"
                
                # Get FOL premises
                fol_premises = analysis.fol_premises or custom_tester.generate_fol_premises(onto)
                
                # Generate implications using the OpenAI integration
                implications = generate_real_world_implications(
                    ontology_name=ontology_name,
                    domain_classes=domain_classes,
                    fol_premises=fol_premises,
                    num_implications=num_implications
                )
            
            # Save the implications to the database
            analysis.real_world_implications = implications
            analysis.implications_generated = True
            analysis.implications_generation_date = datetime.datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Generated {len(implications)} real-world implications for analysis ID {analysis_id}")
            
            return jsonify({
                "implications": implications, 
                "comprehensive": comprehensive,
                "count": len(implications)
            })
        
        # GET request but no implications yet
        return jsonify({"implications": [], "message": "No implications generated yet. Use POST to generate."}), 200
        
    except Exception as e:
        logger.error(f"Error generating implications: {str(e)}")
        return jsonify({"error": f"Error generating implications: {str(e)}"}), 500
        
@app.route('/analyze/<filename>/implications')
def show_implications(filename):
    """Show real-world implications for an ontology file."""
    try:
        # Get the file ID from query parameters
        file_id = request.args.get('file_id')
        analysis_id = request.args.get('analysis_id')
        
        if not file_id and not analysis_id:
            flash('Missing file or analysis ID', 'error')
            return redirect(url_for('view_history'))
            
        # Try to get the analysis
        analysis = None
        if analysis_id:
            analysis = OntologyAnalysis.query.get(int(analysis_id))
        elif file_id:
            # Find the most recent analysis for this file
            analysis = OntologyAnalysis.query.filter_by(
                ontology_file_id=int(file_id)
            ).order_by(OntologyAnalysis.analysis_date.desc()).first()
            
        if not analysis:
            flash('Analysis not found', 'error')
            return redirect(url_for('view_history'))
            
        ontology_file = OntologyFile.query.get(analysis.ontology_file_id)
        if not ontology_file:
            flash('Ontology file not found', 'error')
            return redirect(url_for('view_history'))
            
        # Render the implications template
        return render_template('implications.html',
                              analysis=analysis,
                              ontology_file=ontology_file,
                              original_filename=ontology_file.original_filename)
                              
    except Exception as e:
        logger.error(f"Error showing implications: {str(e)}")
        flash(f"Error showing implications: {str(e)}", 'error')
        return redirect(url_for('view_history'))

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

# UML Diagram generation
@app.route('/analyze/<filename>/diagram')
def generate_diagram(filename):
    """Generate a UML diagram for an ontology file."""
    try:
        # Get query parameters
        include_individuals = request.args.get('individuals', 'false').lower() == 'true'
        include_data_properties = request.args.get('data_properties', 'true').lower() == 'true'
        include_annotation_properties = request.args.get('annotation_properties', 'false').lower() == 'true'
        max_classes = int(request.args.get('max_classes', 100))
        
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
        
        # Generate PlantUML code directly with increased max_classes
        from plantuml_generator import PlantUMLGenerator
        plant_generator = PlantUMLGenerator()
        plantuml_code, diagram_path, svg_path = plant_generator.generate_class_diagram(
            onto, 
            filename_base=os.path.splitext(os.path.basename(filename))[0],
            include_individuals=include_individuals,
            include_data_properties=include_data_properties,
            include_annotation_properties=include_annotation_properties,
            max_classes=1000  # Increased to show more classes
        )
        
        # Format result to match existing code expectations
        result = {
            "success": plantuml_code is not None,
            "plantuml_code": plantuml_code,
            "diagram_url": diagram_path,
            "svg_url": svg_path
        }
        
        if not result["success"]:
            logger.error(f"Error generating diagram code: {result.get('error', 'Unknown error')}")
            flash(f"Error generating diagram code: {result.get('error', 'Unknown error')}", 'error')
            return redirect(url_for('analyze_owl', filename=filename))
        
        # Render the diagram page with the PlantUML code
        return render_template('diagram.html', 
                             file=file_record,
                             plantuml_code=result["plantuml_code"])
            
    except Exception as e:
        logger.error(f"Error generating diagram: {str(e)}")
        flash(f"Error generating diagram: {str(e)}", 'error')
        return redirect(url_for('analyze_owl', filename=filename))

@app.route('/api/diagram/<filename>', methods=['GET'])
def api_generate_diagram(filename):
    """API endpoint to generate a UML diagram for an ontology."""
    try:
        # Find the file in the database
        file_record = OntologyFile.query.filter_by(filename=filename).first_or_404()
        
        # Parse request parameters
        include_individuals = request.args.get('individuals', 'false').lower() == 'true'
        include_data_properties = request.args.get('data_properties', 'true').lower() == 'true'
        include_annotation_properties = request.args.get('annotation_properties', 'false').lower() == 'true'
        max_classes = int(request.args.get('max_classes', 100))
        
        # Create an OwlTester instance
        tester = OwlTester()
        
        # Load the ontology file
        result = tester.load_ontology_from_file(file_record.file_path)
        
        if isinstance(result, dict) and not result.get('loaded', False):
            # If load_ontology_from_file returns a dictionary with loaded=False
            error_msg = result.get('error', 'Unknown error')
            raise Exception(f"Failed to load ontology for API diagram: {error_msg}")
        
        # Get the ontology object from the result
        onto = None
        if isinstance(result, dict) and 'ontology' in result:
            onto = result.get('ontology')
        
        if not onto:
            raise Exception("Loaded ontology object not found in result")
        
        # Generate diagram using the updated method with increased max_classes
        result = tester.generate_uml_diagram(
            onto,
            include_individuals=include_individuals,
            include_data_properties=include_data_properties,
            include_annotation_properties=include_annotation_properties,
            max_classes=1000  # Increased to show more classes
        )
        
        if result["success"]:
            return jsonify({
                "success": True,
                "plantuml_code": result["plantuml_code"],
                "filename": file_record.original_filename,
                "file_id": file_record.id
            })
        else:
            logger.error(f"Error generating diagram code: {result.get('error', 'Unknown error')}")
            return jsonify({"success": False, "error": result.get('error', 'Unknown error')}), 500
    except Exception as e:
        logger.error(f"API error generating diagram: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('index.html', error=f"Server error: {str(e)}"), 500

# Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    # Check if the user is already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        # Find the user by email
        user = User.query.filter_by(email=form.email.data).first()
        
        # Check if user exists and password is correct
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password', 'danger')
            return redirect(url_for('login'))
        
        # Login the user
        login_user(user, remember=form.remember_me.data)
        
        # Update last login time
        user.last_login = datetime.datetime.utcnow()
        db.session.commit()
        
        # Redirect to the page the user was trying to access
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('dashboard')
            
        flash(f'Welcome back, {user.username}!', 'success')
        return redirect(next_page)
    
    return render_template('login.html', title='Login', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page"""
    # Check if the user is already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # Create a new user
        user = User()
        user.username = form.username.data
        user.email = form.email.data
        user.set_password(form.password.data)
        
        # Save the user to the database
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! You can now log in with your credentials.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html', title='Register', form=form)

@app.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard with personalized analysis history"""
    # Get user's ontology files with analyses, ordered by upload date (newest first)
    user_ontologies = OntologyFile.query.filter_by(user_id=current_user.id)\
                                   .order_by(OntologyFile.upload_date.desc()).all()
    
    # Get user's FOL expressions, ordered by test date (newest first)
    user_expressions = FOLExpression.query.filter_by(user_id=current_user.id)\
                                    .order_by(FOLExpression.test_date.desc()).limit(10).all()
    
    # Get statistics
    stats = {
        'ontology_count': len(user_ontologies),
        'expression_count': FOLExpression.query.filter_by(user_id=current_user.id).count(),
        'analysis_count': sum(len(ontology.analyses) for ontology in user_ontologies),
        'latest_activity': user_ontologies[0].upload_date if user_ontologies else None
    }
    
    # Get user's sandbox ontologies
    user_sandboxes = SandboxOntology.query.filter_by(user_id=current_user.id)\
                                 .order_by(SandboxOntology.last_modified.desc()).all()
    
    # Update stats to include sandbox ontologies
    stats['sandbox_count'] = len(user_sandboxes)
    
    return render_template('dashboard.html', 
                         title=f"{current_user.username}'s Dashboard",
                         ontologies=user_ontologies,
                         expressions=user_expressions,
                         sandboxes=user_sandboxes,
                         stats=stats)


# Ontology Development Sandbox Routes

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
    if current_user.is_authenticated:
        # Show user's own ontologies
        ontologies = SandboxOntology.query.filter_by(user_id=current_user.id)\
                                   .order_by(SandboxOntology.last_modified.desc()).all()
    else:
        # Show only public ontologies or a message to login
        ontologies = []
    
    return render_template('sandbox/list.html', 
                         title="Ontology Development Sandbox",
                         ontologies=ontologies)


@app.route('/sandbox/new', methods=['GET', 'POST'])
def sandbox_new():
    """Create a new sandbox ontology."""
    form = DomainForm()
    
    if form.validate_on_submit():
        user_id = current_user.id if current_user.is_authenticated else None
        
        # Create a new sandbox ontology
        ontology = SandboxOntology()
        ontology.title = form.title.data
        ontology.domain = form.domain.data
        ontology.subject = form.subject.data
        ontology.description = form.description.data
        ontology.user_id = user_id
        ontology.classes = []
        ontology.properties = []
        ontology.individuals = []
        
        db.session.add(ontology)
        db.session.commit()
        
        flash(f'Created new ontology: {ontology.title}', 'success')
        return redirect(url_for('sandbox_edit', ontology_id=ontology.id))
    
    return render_template('sandbox/new.html', 
                         title="Create New Ontology",
                         form=form)


@app.route('/sandbox/<int:ontology_id>')
def sandbox_view(ontology_id):
    """View a sandbox ontology."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        flash('You do not have permission to view this ontology', 'error')
        return redirect(url_for('sandbox_list'))
    
    # Get classes, properties, and individuals
    classes = OntologyClass.query.filter_by(ontology_id=ontology.id).all()
    properties = OntologyProperty.query.filter_by(ontology_id=ontology.id).all()
    individuals = OntologyIndividual.query.filter_by(ontology_id=ontology.id).all()
    
    return render_template('sandbox/view.html', 
                          title=f"View Ontology: {ontology.title}",
                          ontology=ontology, 
                          classes=classes, 
                          properties=properties,
                          individuals=individuals)


@app.route('/sandbox/<int:ontology_id>/edit')
def sandbox_edit(ontology_id):
    """Edit a sandbox ontology."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to edit this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        flash('You do not have permission to edit this ontology', 'error')
        return redirect(url_for('sandbox_list'))
    
    # Get classes, properties, and individuals
    classes = OntologyClass.query.filter_by(ontology_id=ontology.id).all()
    properties = OntologyProperty.query.filter_by(ontology_id=ontology.id).all()
    individuals = OntologyIndividual.query.filter_by(ontology_id=ontology.id).all()
    
    # Get BFO classes for reference
    bfo_classes = owl_tester.get_bfo_classes() if owl_tester else []
    
    return render_template('sandbox/edit.html', 
                          title=f"Edit Ontology: {ontology.title}",
                          ontology=ontology, 
                          classes=classes, 
                          properties=properties,
                          individuals=individuals,
                          bfo_classes=bfo_classes)


@app.route('/sandbox/<int:ontology_id>/download')
def sandbox_download(ontology_id):
    """Download a sandbox ontology as OWL/RDF."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        flash('You do not have permission to download this ontology', 'error')
        return redirect(url_for('sandbox_list'))
    
    # Get classes, properties, and individuals
    classes = OntologyClass.query.filter_by(ontology_id=ontology.id).all()
    properties = OntologyProperty.query.filter_by(ontology_id=ontology.id).all()
    individuals = OntologyIndividual.query.filter_by(ontology_id=ontology.id).all()
    
    # Generate OWL/RDF XML
    owl_xml = generate_owl_xml(ontology, classes, properties, individuals)
    
    # Return as downloadable file
    response = make_response(owl_xml)
    response.headers["Content-Disposition"] = f"attachment; filename={secure_filename(ontology.title)}.owl"
    response.headers["Content-Type"] = "application/rdf+xml"
    
    return response


# API routes for the sandbox

@app.route('/api/sandbox/<int:ontology_id>/classes', methods=['GET', 'POST'])
def api_sandbox_classes(ontology_id):
    """API for sandbox ontology classes."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 403
    
    if request.method == 'GET':
        # Return all classes for this ontology
        classes = OntologyClass.query.filter_by(ontology_id=ontology.id).all()
        return jsonify({
            "classes": [
                {
                    "id": cls.id,
                    "name": cls.name,
                    "description": cls.description,
                    "bfo_category": cls.bfo_category,
                    "parent_id": cls.parent_id
                } for cls in classes
            ]
        })
    
    elif request.method == 'POST':
        # Add a new class
        data = request.get_json()
        
        if not data or 'name' not in data:
            return jsonify({"error": "Name is required"}), 400
        
        try:
            new_class = OntologyClass()
            new_class.ontology_id = ontology.id
            new_class.name = data['name']
            new_class.description = data.get('description', '')
            new_class.bfo_category = data.get('bfo_category')
            new_class.parent_id = data.get('parent_id')
            
            db.session.add(new_class)
            db.session.commit()
            
            return jsonify({
                "id": new_class.id,
                "name": new_class.name,
                "message": f"Class {new_class.name} created successfully"
            }), 201
            
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500


@app.route('/api/sandbox/<int:ontology_id>/classes/<int:class_id>', methods=['GET', 'PUT', 'DELETE'])
def api_sandbox_class(ontology_id, class_id):
    """API for a specific sandbox ontology class."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Get the class
    cls = OntologyClass.query.filter_by(id=class_id, ontology_id=ontology.id).first_or_404()
    
    if request.method == 'GET':
        # Return class details
        return jsonify({
            "id": cls.id,
            "name": cls.name,
            "description": cls.description,
            "bfo_category": cls.bfo_category,
            "parent_id": cls.parent_id,
            "properties": cls.properties
        })
    
    elif request.method == 'PUT':
        # Update class
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        try:
            if 'name' in data:
                cls.name = data['name']
            if 'description' in data:
                cls.description = data['description']
            if 'bfo_category' in data:
                cls.bfo_category = data['bfo_category']
            if 'parent_id' in data:
                cls.parent_id = data['parent_id']
            if 'properties' in data:
                cls.properties = data['properties']
            
            # Update the ontology's last_modified time
            ontology.last_modified = datetime.datetime.utcnow()
            
            db.session.commit()
            
            return jsonify({
                "id": cls.id,
                "name": cls.name,
                "message": f"Class {cls.name} updated successfully"
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    elif request.method == 'DELETE':
        # Delete class
        try:
            # Check if there are any dependent entities
            children = OntologyClass.query.filter_by(parent_id=cls.id).all()
            
            if children:
                return jsonify({
                    "error": f"Cannot delete class {cls.name} because it has child classes. Please remove or reassign them first."
                }), 400
            
            # Check for individuals
            individuals = OntologyIndividual.query.filter_by(class_id=cls.id).all()
            
            if individuals:
                return jsonify({
                    "error": f"Cannot delete class {cls.name} because it has individuals. Please remove them first."
                }), 400
            
            # Check for properties with this class as domain or range
            domain_props = OntologyProperty.query.filter_by(domain_class_id=cls.id).all()
            range_props = OntologyProperty.query.filter_by(range_class_id=cls.id).all()
            
            if domain_props or range_props:
                return jsonify({
                    "error": f"Cannot delete class {cls.name} because it is used as domain or range in properties. Please remove or reassign them first."
                }), 400
            
            # Delete the class
            db.session.delete(cls)
            
            # Update the ontology's last_modified time
            ontology.last_modified = datetime.datetime.utcnow()
            
            db.session.commit()
            
            return jsonify({
                "message": f"Class {cls.name} deleted successfully"
            })
            
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500


# Helper function to generate OWL/RDF XML
def generate_owl_xml(ontology, classes, properties, individuals):
    """Generate OWL/RDF XML for a sandbox ontology."""
    # Create a base namespace for the ontology
    base_ns = f"http://example.org/ontology/{secure_filename(ontology.title).lower()}#"
    
    # Start XML document
    xml = '<?xml version="1.0"?>\n'
    xml += '<rdf:RDF xmlns="' + base_ns + '"\n'
    xml += '     xml:base="' + base_ns + '"\n'
    xml += '     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
    xml += '     xmlns:owl="http://www.w3.org/2002/07/owl#"\n'
    xml += '     xmlns:xml="http://www.w3.org/XML/1998/namespace"\n'
    xml += '     xmlns:xsd="http://www.w3.org/2001/XMLSchema#"\n'
    xml += '     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">\n\n'
    
    # Add ontology definition
    xml += '    <owl:Ontology rdf:about="' + base_ns + '">\n'
    xml += '        <rdfs:label>' + escape(ontology.title) + '</rdfs:label>\n'
    
    if ontology.description:
        xml += '        <rdfs:comment>' + escape(ontology.description) + '</rdfs:comment>\n'
    
    xml += '    </owl:Ontology>\n\n'
    
    # Add classes
    for cls in classes:
        xml += '    <owl:Class rdf:about="' + base_ns + escape(cls.name) + '">\n'
        
        if cls.description:
            xml += '        <rdfs:comment>' + escape(cls.description) + '</rdfs:comment>\n'
        
        # Add parent class if exists
        if cls.parent_id:
            parent = next((c for c in classes if c.id == cls.parent_id), None)
            if parent:
                xml += '        <rdfs:subClassOf rdf:resource="' + base_ns + escape(parent.name) + '"/>\n'
        
        # Add BFO category if exists
        if cls.bfo_category:
            xml += '        <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/BFO_' + escape(cls.bfo_category) + '"/>\n'
            
        xml += '    </owl:Class>\n\n'
    
    # Add properties
    for prop in properties:
        xml += '    <owl:ObjectProperty rdf:about="' + base_ns + escape(prop.name) + '">\n'
        
        if prop.description:
            xml += '        <rdfs:comment>' + escape(prop.description) + '</rdfs:comment>\n'
        
        # Add domain if exists
        if prop.domain_class_id:
            domain_class = next((c for c in classes if c.id == prop.domain_class_id), None)
            if domain_class:
                xml += '        <rdfs:domain rdf:resource="' + base_ns + escape(domain_class.name) + '"/>\n'
        
        # Add range if exists
        if prop.range_class_id:
            range_class = next((c for c in classes if c.id == prop.range_class_id), None)
            if range_class:
                xml += '        <rdfs:range rdf:resource="' + base_ns + escape(range_class.name) + '"/>\n'
                
        xml += '    </owl:ObjectProperty>\n\n'
    
    # Add individuals
    for indiv in individuals:
        xml += '    <owl:NamedIndividual rdf:about="' + base_ns + escape(indiv.name) + '">\n'
        
        if indiv.description:
            xml += '        <rdfs:comment>' + escape(indiv.description) + '</rdfs:comment>\n'
        
        # Add class membership
        cls = next((c for c in classes if c.id == indiv.class_id), None)
        if cls:
            xml += '        <rdf:type rdf:resource="' + base_ns + escape(cls.name) + '"/>\n'
        
        # Add property values
        if indiv.property_values:
            for prop_id, value_info in indiv.property_values.items():
                # Find the property
                prop = next((p for p in properties if str(p.id) == prop_id), None)
                if prop and value_info.get('value'):
                    value_id = value_info.get('value')
                    # Find the target individual
                    target = next((i for i in individuals if i.id == int(value_id)), None)
                    if target:
                        xml += '        <' + escape(prop.name) + ' rdf:resource="' + base_ns + escape(target.name) + '"/>\n'
                
        xml += '    </owl:NamedIndividual>\n\n'
    
    # Close the RDF root element
    xml += '</rdf:RDF>\n'
    
    return xml


# AI Assistance API Routes for the Ontology Sandbox
@app.route('/api/sandbox/ai/suggestions')
def api_sandbox_ai_suggestions():
    """API endpoint to get AI-generated class and property suggestions for an ontology domain."""
    domain = request.args.get('domain', '')
    subject = request.args.get('subject', '')
    suggestion_type = request.args.get('type', 'all')  # Default to 'all', other options: 'classes', 'properties'
    
    logger.info(f"AI suggestions requested for domain: '{domain}', subject: '{subject}', type: '{suggestion_type}'")
    
    if not domain or not subject:
        logger.warning("Missing parameters for AI suggestions")
        return jsonify({"error": "Both domain and subject parameters are required"}), 400
    
    try:
        # Call the OpenAI function to get suggestions
        logger.info(f"Calling OpenAI API to get suggestions for domain: '{domain}', subject: '{subject}'")
        all_suggestions = suggest_ontology_classes(domain, subject)
        
        if not all_suggestions:
            logger.warning(f"No suggestions generated for domain: '{domain}', subject: '{subject}'")
            return jsonify({"error": "No suggestions generated. Try with a different domain/subject."}), 404
            
        # Check if we got an error from the OpenAI function
        if len(all_suggestions) == 1 and "error" in all_suggestions[0]:
            error_msg = all_suggestions[0]["error"]
            logger.error(f"OpenAI API returned an error: {error_msg}")
            return jsonify({"error": error_msg}), 500
        
        # Filter the suggestions based on the requested type
        if suggestion_type == 'classes':
            # Return only the class information without properties
            filtered_suggestions = []
            for suggestion in all_suggestions:
                # Create a copy without the properties field
                class_suggestion = {k: v for k, v in suggestion.items() if k != 'properties'}
                filtered_suggestions.append(class_suggestion)
            logger.info(f"Filtered to {len(filtered_suggestions)} class suggestions (without properties)")
            response_data = {"suggestions": filtered_suggestions, "domain": domain, "subject": subject}
        elif suggestion_type == 'properties':
            # Extract only the properties from all classes
            all_properties = []
            
            # Get existing classes from the ontology
            ontology_id = request.args.get('ontology_id')
            if ontology_id:
                try:
                    ontology_id = int(ontology_id)
                    existing_classes = OntologyClass.query.filter_by(ontology_id=ontology_id).all()
                    existing_class_names = {cls.name.lower(): cls.id for cls in existing_classes}
                    logger.info(f"Found {len(existing_classes)} existing classes in ontology {ontology_id}")
                except (ValueError, TypeError):
                    existing_class_names = {}
                    logger.warning(f"Invalid ontology_id: {ontology_id}")
            else:
                existing_class_names = {}
                
            # Add both suggested classes and existing classes to a mapping
            all_class_names = {suggestion.get('name', '').lower(): None for suggestion in all_suggestions}
            for suggestion in all_suggestions:
                if 'properties' in suggestion and suggestion['properties']:
                    suggestion_name = suggestion.get('name', '')
                    # Find matching existing class if any
                    matching_class_id = existing_class_names.get(suggestion_name.lower())
                    
                    # Add the class name to each property for context
                    for prop in suggestion['properties']:
                        prop['class_name'] = suggestion_name
                        # If we found a matching existing class, use its ID as the domain
                        if matching_class_id:
                            prop['domain_class_id'] = matching_class_id
                            
                        # For the range, try to find a matching class in existing classes or suggested classes
                        if prop.get('type') == 'object' and 'range_class' not in prop:
                            # Try to guess a good range class based on property name
                            prop_name = prop.get('name', '').lower()
                            
                            if prop_name.startswith('has') and len(prop_name) > 3:
                                # For "hasX" properties, look for a class X
                                possible_range = prop_name[3:].lower()
                                # First letter uppercase for camelCase
                                possible_range = possible_range[0].upper() + possible_range[1:]
                                
                                # Check if a class with this name exists
                                for cls_name, cls_id in existing_class_names.items():
                                    if cls_name.lower() == possible_range.lower():
                                        prop['range_class_id'] = cls_id
                                        break
                        
                        all_properties.append(prop)
            
            logger.info(f"Extracted {len(all_properties)} property suggestions from classes")
            response_data = {
                "suggestions": all_properties, 
                "domain": domain, 
                "subject": subject,
                "existing_classes": [{"id": id, "name": name} for name, id in existing_class_names.items()]
            }
        else:
            # Return all suggestions unchanged
            logger.info(f"Returning all {len(all_suggestions)} suggestions with classes and properties")
            response_data = {"suggestions": all_suggestions, "domain": domain, "subject": subject}
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error generating AI suggestions: {str(e)}")
        return jsonify({"error": f"Failed to generate suggestions: {str(e)}"}), 500

@app.route('/api/sandbox/ai/bfo-category', methods=['POST'])
def api_sandbox_ai_bfo_category():
    """API endpoint to suggest a BFO category for a class."""
    data = request.get_json()
    
    if not data or 'class_name' not in data:
        return jsonify({"error": "Class name is required"}), 400
    
    class_name = data.get('class_name', '')
    description = data.get('description', '')
    
    try:
        # Call the OpenAI function to suggest a BFO category
        result = suggest_bfo_category(class_name, description)
        
        if "error" in result:
            return jsonify({"error": result["error"]}), 500
            
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error suggesting BFO category: {str(e)}")
        return jsonify({"error": f"Failed to suggest BFO category: {str(e)}"}), 500

@app.route('/api/sandbox/<int:ontology_id>/properties', methods=['GET', 'POST'])
def api_sandbox_properties(ontology_id):
    """API for sandbox ontology properties."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 403
    
    if request.method == 'GET':
        # Return all properties for this ontology
        properties = OntologyProperty.query.filter_by(ontology_id=ontology.id).all()
        return jsonify({
            "properties": [
                {
                    "id": prop.id,
                    "name": prop.name,
                    "description": prop.description,
                    "property_type": prop.property_type,
                    "domain_class_id": prop.domain_class_id,
                    "range_class_id": prop.range_class_id
                } for prop in properties
            ]
        })
    elif request.method == 'POST':
        # Create a new property
        data = request.get_json()
        
        if not data.get('name'):
            return jsonify({"error": "Property name is required"}), 400
        
        try:
            # Create the property
            prop = OntologyProperty()
            prop.name = data.get('name')
            prop.description = data.get('description', '')
            prop.property_type = data.get('property_type', 'object')  # Default to object property
            prop.domain_class_id = data.get('domain_class_id')
            prop.range_class_id = data.get('range_class_id')
            prop.ontology_id = ontology.id
            
            db.session.add(prop)
            
            # Update the last_modified timestamp on the ontology
            ontology.last_modified = datetime.datetime.utcnow()
            
            db.session.commit()
            
            return jsonify({
                "id": prop.id,
                "name": prop.name,
                "description": prop.description,
                "property_type": prop.property_type,
                "domain_class_id": prop.domain_class_id,
                "range_class_id": prop.range_class_id
            }), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating property: {str(e)}")
            return jsonify({"error": f"Failed to create property: {str(e)}"}), 500


@app.route('/api/sandbox/<int:ontology_id>/properties/<int:property_id>', methods=['GET', 'PUT', 'DELETE'])
def api_sandbox_property(ontology_id, property_id):
    """API for a specific sandbox ontology property."""
    ontology = SandboxOntology.query.get_or_404(ontology_id)
    
    # Check if the user has access to this ontology
    if ontology.user_id and ontology.user_id != current_user.id and not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Get the property
    prop = OntologyProperty.query.filter_by(id=property_id, ontology_id=ontology.id).first_or_404()
    
    if request.method == 'GET':
        # Return property details
        return jsonify({
            "id": prop.id,
            "name": prop.name,
            "description": prop.description,
            "property_type": prop.property_type,
            "domain_class_id": prop.domain_class_id,
            "range_class_id": prop.range_class_id
        })
    elif request.method == 'PUT':
        # Update the property
        data = request.get_json()
        
        if 'name' in data:
            prop.name = data['name']
        if 'description' in data:
            prop.description = data['description']
        if 'property_type' in data:
            prop.property_type = data['property_type']
        if 'domain_class_id' in data:
            prop.domain_class_id = data['domain_class_id']
        if 'range_class_id' in data:
            prop.range_class_id = data['range_class_id']
        
        # Update the last_modified timestamp on the ontology
        ontology.last_modified = datetime.datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            "id": prop.id,
            "name": prop.name,
            "description": prop.description,
            "property_type": prop.property_type,
            "domain_class_id": prop.domain_class_id,
            "range_class_id": prop.range_class_id
        })
    elif request.method == 'DELETE':
        # Delete the property
        db.session.delete(prop)
        
        # Update the last_modified timestamp on the ontology
        ontology.last_modified = datetime.datetime.utcnow()
        
        db.session.commit()
        
        return '', 204


@app.route('/api/sandbox/ai/description', methods=['POST'])
def api_sandbox_ai_description():
    """API endpoint to generate a description for a class."""
    data = request.get_json()
    
    if not data or 'class_name' not in data:
        return jsonify({"error": "Class name is required"}), 400
    
    class_name = data.get('class_name', '')
    
    try:
        # Call the OpenAI function to generate a description
        result = generate_class_description(class_name)
        
        if "error" in result:
            return jsonify({"error": result["error"]}), 500
            
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error generating class description: {str(e)}")
        return jsonify({"error": f"Failed to generate description: {str(e)}"}), 500


# This duplicate route was removed - see existing implementation

# This duplicate route was removed - add method to existing implementation

# This duplicate route was removed - add features to existing implementation


if __name__ == '__main__':
    # Run the app on host 0.0.0.0 to make it accessible externally
    app.run(host='0.0.0.0', port=5000, debug=True)
