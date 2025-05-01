import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class OntologyFile(db.Model):
    """Model for storing uploaded ontology files."""
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    upload_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    mime_type = db.Column(db.String(100), nullable=True)
    
    # Relationship with analysis results
    analyses = db.relationship('OntologyAnalysis', backref='ontology_file', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<OntologyFile {self.original_filename}>"


class OntologyAnalysis(db.Model):
    """Model for storing ontology analysis results."""
    
    id = db.Column(db.Integer, primary_key=True)
    ontology_file_id = db.Column(db.Integer, db.ForeignKey('ontology_file.id'), nullable=False)
    analysis_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Basic ontology information
    ontology_name = db.Column(db.String(255), nullable=True)
    ontology_iri = db.Column(db.String(500), nullable=True)
    is_consistent = db.Column(db.Boolean, nullable=True, default=True)
    
    # Statistics
    class_count = db.Column(db.Integer, default=0)
    object_property_count = db.Column(db.Integer, default=0)
    data_property_count = db.Column(db.Integer, default=0)
    individual_count = db.Column(db.Integer, default=0)
    annotation_property_count = db.Column(db.Integer, default=0)
    axiom_count = db.Column(db.Integer, default=0)
    
    # Metrics
    expressivity = db.Column(db.String(50), nullable=True)
    complexity = db.Column(db.Integer, default=0)
    
    # Store detailed results as JSON
    axioms = db.Column(db.JSON, nullable=True)
    consistency_issues = db.Column(db.JSON, nullable=True)
    inferred_axioms = db.Column(db.JSON, nullable=True)
    fol_premises = db.Column(db.JSON, nullable=True)
    
    def __repr__(self):
        return f"<OntologyAnalysis {self.id} for {self.ontology_file_id}>"


class FOLExpression(db.Model):
    """Model for storing tested FOL expressions."""
    
    id = db.Column(db.Integer, primary_key=True)
    expression = db.Column(db.Text, nullable=False)
    test_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_valid = db.Column(db.Boolean, default=False)
    
    # Store test results as JSON
    test_results = db.Column(db.JSON, nullable=True)
    issues = db.Column(db.JSON, nullable=True)
    bfo_classes_used = db.Column(db.JSON, nullable=True)
    bfo_relations_used = db.Column(db.JSON, nullable=True)
    non_bfo_terms = db.Column(db.JSON, nullable=True)
    
    def __repr__(self):
        return f"<FOLExpression {self.id}: {self.expression[:30]}...>"