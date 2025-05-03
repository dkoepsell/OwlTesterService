import os
import logging
import uuid
import datetime
import base64
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, session
from werkzeug.utils import secure_filename
# We'll use urllib for URL parsing instead of werkzeug
from urllib.parse import urlparse
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, EmailField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from owl_tester import OwlTester
from models import db, User, OntologyFile, OntologyAnalysis, FOLExpression
from openai_utils import generate_real_world_implications

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
login_manager.login_view = 'login'
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
    
    return render_template('index.html', 
                           bfo_classes=owl_tester.get_bfo_classes(),
                           bfo_relations=owl_tester.get_bfo_relations())

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
    
    try:
        result = owl_tester.test_expression(expression)
        
        # Save the test result to the database
        # Associate expression with current user if logged in
        user_id = current_user.id if current_user.is_authenticated else None
        
        fol_expression = FOLExpression(
            expression=expression,
            is_valid=result.get('valid', False),
            test_results=result,
            issues=result.get('issues', []),
            bfo_classes_used=result.get('bfo_classes_used', []),
            bfo_relations_used=result.get('bfo_relations_used', []),
            non_bfo_terms=result.get('non_bfo_terms', []),
            user_id=user_id
        )
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
    
    return jsonify({"classes": owl_tester.get_bfo_classes()})

@app.route('/api/bfo-relations')
def get_bfo_relations():
    """API endpoint to get all BFO relations."""
    if owl_tester is None:
        return jsonify({"error": "OwlTester is not initialized properly"}), 500
    
    return jsonify({"relations": owl_tester.get_bfo_relations()})

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
            original_filename = secure_filename(file.filename)
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
            
            ontology_file = OntologyFile(
                filename=unique_filename,
                original_filename=original_filename,
                file_path=file_path,
                file_size=file_size,
                mime_type=mime_type,
                user_id=user_id
            )
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
        
        # Create a new OwlTester instance with the uploaded file
        try:
            # First try to create a custom tester with the uploaded file
            custom_tester = OwlTester(ontology_path=file_path)
            
            # Generate analysis report
            analysis = custom_tester.analyze_ontology()
        except Exception as e:
            # If the constructor approach fails, try with explicit load_ontology_from_file
            logger.error(f"Error creating OwlTester: {str(e)}")
            
            custom_tester = OwlTester()  # Create with default BFO ontology
            result = custom_tester.load_ontology_from_file(file_path)
            
            if isinstance(result, tuple) and not result[0]:
                # If load_ontology_from_file returns False with an error message
                raise Exception(f"Failed to load ontology: {result[1]}")
            
            # Generate analysis report
            analysis = custom_tester.analyze_ontology()
        
        # Generate PlantUML diagram code with increased max_classes
        diagram_result = custom_tester.generate_uml_diagram(
            include_individuals=False,
            include_data_properties=True,
            include_annotation_properties=False,
            max_classes=1000  # Increased to show more classes
        )
        
        # Get the PlantUML code if successful
        plantuml_code = diagram_result.get("plantuml_code", "") if diagram_result.get("success", False) else ""
        
        # Save analysis to database if we have a file_id
        if file_id:
            try:
                ontology_file = OntologyFile.query.get(int(file_id))
                if ontology_file:
                    # Create analysis record
                    ontology_analysis = OntologyAnalysis(
                        ontology_file_id=ontology_file.id,
                        ontology_name=analysis.get('ontology_name', 'Unknown'),
                        ontology_iri=analysis.get('ontology_iri', ''),
                        is_consistent=analysis.get('consistency', {}).get('consistent', True),
                        class_count=analysis.get('class_count', 0),
                        object_property_count=analysis.get('object_property_count', 0),
                        data_property_count=analysis.get('data_property_count', 0),
                        individual_count=analysis.get('individual_count', 0),
                        annotation_property_count=analysis.get('annotation_property_count', 0),
                        axiom_count=analysis.get('axiom_count', 0),
                        expressivity=analysis.get('expressivity', ''),
                        complexity=analysis.get('complexity', 0),
                        axioms=analysis.get('axioms', []),
                        consistency_issues=analysis.get('consistency', {}).get('issues', []),
                        inferred_axioms=analysis.get('inferred', []),
                        fol_premises=analysis.get('fol_premises', [])
                    )
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
        
        # Render analysis template with results
        return render_template('analysis_new.html', 
                              original_filename=original_name,
                              filename=filename,
                              file_id=file_id,  # Add file_id to be available in the template
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
        
        # Create a new OwlTester instance with the uploaded file
        try:
            # First try to create a custom tester with the uploaded file
            custom_tester = OwlTester(ontology_path=file_path)
            
            # Generate analysis report
            analysis = custom_tester.analyze_ontology()
        except Exception as e:
            # If the constructor approach fails, try with explicit load_ontology_from_file
            logger.error(f"Error creating OwlTester: {str(e)}")
            
            custom_tester = OwlTester()  # Create with default BFO ontology
            result = custom_tester.load_ontology_from_file(file_path)
            
            if isinstance(result, tuple) and not result[0]:
                # If load_ontology_from_file returns False with an error message
                raise Exception(f"Failed to load ontology: {result[1]}")
            
            # Generate analysis report
            analysis = custom_tester.analyze_ontology()
        
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
            try:
                custom_tester = OwlTester(ontology_path=ontology_file.file_path)
            except Exception as e:
                logger.error(f"Error creating OwlTester for implications: {str(e)}")
                # Try alternative loading method
                custom_tester = OwlTester()
                result = custom_tester.load_ontology_from_file(ontology_file.file_path)
                if isinstance(result, tuple) and not result[0]:
                    raise Exception(f"Failed to load ontology for implications: {result[1]}")
            
            # Generate the implications (default 5)
            num_implications = request.args.get('count', 5, type=int)
            implications = custom_tester.generate_real_world_implications(num_implications)
            
            # Save the implications to the database
            analysis.real_world_implications = implications
            analysis.implications_generated = True
            analysis.implications_generation_date = datetime.datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Generated {len(implications)} real-world implications for analysis ID {analysis_id}")
            
            return jsonify({"implications": implications})
        
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
        
        # Create an OwlTester instance with the file
        tester = OwlTester(file_record.file_path)
        
        # Generate PlantUML code directly with increased max_classes
        result = tester.generate_uml_diagram(
            include_individuals=include_individuals,
            include_data_properties=include_data_properties,
            include_annotation_properties=include_annotation_properties,
            max_classes=1000  # Increased to show more classes
        )
        
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
        
        # Create an OwlTester instance with the file
        tester = OwlTester(file_record.file_path)
        
        # Generate diagram using the updated method with increased max_classes
        result = tester.generate_uml_diagram(
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
        user = User(username=form.username.data, email=form.email.data)
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
    
    return render_template('dashboard.html', 
                         title=f"{current_user.username}'s Dashboard",
                         ontologies=user_ontologies,
                         expressions=user_expressions,
                         stats=stats)

if __name__ == '__main__':
    # Run the app on host 0.0.0.0 to make it accessible externally
    app.run(host='0.0.0.0', port=5000, debug=True)
