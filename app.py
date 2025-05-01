import os
import logging
import uuid
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
from owl_tester import OwlTester
from models import db, OntologyFile, OntologyAnalysis, FOLExpression

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key-for-development")

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///owl_tester.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Initialize database
db.init_app(app)

# Configure file uploads
app.config['UPLOADED_OWLS_DEST'] = os.path.join(app.root_path, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'owl', 'rdf', 'xml', 'ttl', 'n3', 'nt'}

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
        fol_expression = FOLExpression(
            expression=expression,
            is_valid=result.get('valid', False),
            test_results=result,
            issues=result.get('issues', []),
            bfo_classes_used=result.get('bfo_classes_used', []),
            bfo_relations_used=result.get('bfo_relations_used', []),
            non_bfo_terms=result.get('non_bfo_terms', [])
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
            flash('Invalid file type. Please upload an OWL/RDF file (.owl, .rdf, .xml, .ttl, .n3, .nt)', 'error')
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
            
            ontology_file = OntologyFile(
                filename=unique_filename,
                original_filename=original_filename,
                file_path=file_path,
                file_size=file_size,
                mime_type=mime_type
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
        custom_tester = OwlTester(ontology_path=file_path)
        
        # Generate analysis report
        analysis = custom_tester.analyze_ontology()
        
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
                        is_consistent=analysis.get('is_consistent', True),
                        class_count=analysis.get('class_count', 0),
                        object_property_count=analysis.get('object_property_count', 0),
                        data_property_count=analysis.get('data_property_count', 0),
                        individual_count=analysis.get('individual_count', 0),
                        annotation_property_count=analysis.get('annotation_property_count', 0),
                        axiom_count=analysis.get('axiom_count', 0),
                        expressivity=analysis.get('expressivity', ''),
                        complexity=analysis.get('complexity', 0),
                        axioms=analysis.get('axioms', []),
                        consistency_issues=analysis.get('consistency_issues', []),
                        inferred_axioms=analysis.get('inferred_axioms', [])
                    )
                    db.session.add(ontology_analysis)
                    db.session.commit()
                    logger.info(f"Saved analysis to database with ID {ontology_analysis.id}")
            except Exception as e:
                logger.error(f"Error saving analysis to database: {str(e)}")
                # Continue with the analysis even if saving to DB fails
        
        # Render analysis template with results
        return render_template('analysis.html', 
                              original_filename=original_name,
                              analysis=analysis,
                              classes=custom_tester.get_bfo_classes(),
                              relations=custom_tester.get_bfo_relations(),
                              data_properties=custom_tester.get_data_properties(),
                              individuals=custom_tester.get_individuals(),
                              annotation_properties=custom_tester.get_annotation_properties())
                              
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
        custom_tester = OwlTester(ontology_path=file_path)
        
        # Generate analysis report
        analysis = custom_tester.analyze_ontology()
        
        return jsonify(analysis)
        
    except Exception as e:
        logger.error(f"Error in API analyzing OWL file: {str(e)}")
        return jsonify({"error": f"Error analyzing OWL file: {str(e)}"}), 500

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

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error="Page not found"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('index.html', error=f"Server error: {str(e)}"), 500

if __name__ == '__main__':
    # Run the app on host 0.0.0.0 to make it accessible externally
    app.run(host='0.0.0.0', port=5000, debug=True)
