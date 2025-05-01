import os
import logging
from flask import Flask, render_template, request, jsonify
from owl_tester import OwlTester

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key-for-development")

# Load the OwlTester
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
