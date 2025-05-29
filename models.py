import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """Model for user accounts."""
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    ontology_files = db.relationship('OntologyFile', backref='user', lazy=True)
    fol_expressions = db.relationship('FOLExpression', backref='user', lazy=True)
    # Sandbox ontologies relationship is defined in the SandboxOntology model
    
    def set_password(self, password):
        """Set the user's password hash from a plain text password."""
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        """Check if the provided password matches the stored hash."""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f"<User {self.username}>"

class OntologyFile(db.Model):
    """Model for storing uploaded ontology files."""
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    upload_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    mime_type = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for legacy files
    from_sandbox = db.Column(db.Boolean, default=False)  # Flag to indicate if the file came from sandbox
    sandbox_ontology_id = db.Column(db.Integer, db.ForeignKey('sandbox_ontology.id'), nullable=True)  # Link to source sandbox if applicable
    archived = db.Column(db.Boolean, default=False)  # Flag to indicate if the file is archived
    
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
    real_world_implications = db.Column(db.JSON, nullable=True)
    implications_generated = db.Column(db.Boolean, default=False)
    implications_generation_date = db.Column(db.DateTime, nullable=True)
    
    # Entity lists for direct display
    class_list = db.Column(db.JSON, nullable=True)
    object_property_list = db.Column(db.JSON, nullable=True)
    data_property_list = db.Column(db.JSON, nullable=True)
    individual_list = db.Column(db.JSON, nullable=True)
    
    # Transparency fields
    reasoning_methodology = db.Column(db.JSON, nullable=True) 
    derivation_steps = db.Column(db.JSON, nullable=True)
    
    def __repr__(self):
        return f"<OntologyAnalysis {self.id} for {self.ontology_file_id}>"


class FOLExpression(db.Model):
    """Model for storing tested FOL expressions."""
    
    id = db.Column(db.Integer, primary_key=True)
    expression = db.Column(db.Text, nullable=False)
    test_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_valid = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for legacy expressions
    
    # Store test results as JSON
    test_results = db.Column(db.JSON, nullable=True)
    issues = db.Column(db.JSON, nullable=True)
    bfo_classes_used = db.Column(db.JSON, nullable=True)
    bfo_relations_used = db.Column(db.JSON, nullable=True)
    non_bfo_terms = db.Column(db.JSON, nullable=True)
    
    def __repr__(self):
        return f"<FOLExpression {self.id}: {self.expression[:30]}...>"


class SandboxOntology(db.Model):
    """Model for storing sandbox ontology development projects."""
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    domain = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creation_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_modified = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for anonymous users
    
    # Store the ontology structure as JSON
    classes = db.Column(db.JSON, default=list)
    properties = db.Column(db.JSON, default=list)
    individuals = db.Column(db.JSON, default=list)
    
    # Reference to the user (optional)
    user = db.relationship('User', backref=db.backref('sandbox_ontologies', lazy=True))
    
    # Reference to exported ontology files
    exported_files = db.relationship('OntologyFile', backref='sandbox_source', lazy=True)
    
    def __repr__(self):
        return f"<SandboxOntology {self.id}: {self.title}>"
        
        
class OntologyClass(db.Model):
    """Model for storing class definitions in sandbox ontologies."""
    
    id = db.Column(db.Integer, primary_key=True)
    ontology_id = db.Column(db.Integer, db.ForeignKey('sandbox_ontology.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    bfo_category = db.Column(db.String(100), nullable=True)  # Link to BFO class if applicable
    creation_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Parent class (for subclass relationships)
    parent_id = db.Column(db.Integer, db.ForeignKey('ontology_class.id'), nullable=True)
    children = db.relationship('OntologyClass', backref=db.backref('parent', remote_side=[id]), lazy=True)
    
    # Reference to the ontology
    ontology = db.relationship('SandboxOntology', backref=db.backref('ontology_classes', lazy=True, cascade="all, delete-orphan"))
    
    # Custom properties as JSON
    properties = db.Column(db.JSON, default=dict)
    
    def __repr__(self):
        return f"<OntologyClass {self.id}: {self.name}>"
        
        
class OntologyProperty(db.Model):
    """Model for storing property/relationship definitions in sandbox ontologies."""
    
    id = db.Column(db.Integer, primary_key=True)
    ontology_id = db.Column(db.Integer, db.ForeignKey('sandbox_ontology.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    property_type = db.Column(db.String(50), nullable=False)  # 'object', 'data', 'annotation'
    creation_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Domain and range (for object properties)
    domain_class_id = db.Column(db.Integer, db.ForeignKey('ontology_class.id'), nullable=True)
    range_class_id = db.Column(db.Integer, db.ForeignKey('ontology_class.id'), nullable=True)
    
    # References to domain and range classes
    domain_class = db.relationship('OntologyClass', foreign_keys=[domain_class_id], backref=db.backref('as_domain_properties', lazy=True))
    range_class = db.relationship('OntologyClass', foreign_keys=[range_class_id], backref=db.backref('as_range_properties', lazy=True))
    
    # Reference to the ontology
    ontology = db.relationship('SandboxOntology', backref=db.backref('ontology_properties', lazy=True, cascade="all, delete-orphan"))
    
    # Custom property metadata as JSON
    property_metadata = db.Column(db.JSON, default=dict)
    
    def __repr__(self):
        return f"<OntologyProperty {self.id}: {self.name}>"


class OntologyIndividual(db.Model):
    """Model for storing individual instances in sandbox ontologies."""
    
    id = db.Column(db.Integer, primary_key=True)
    ontology_id = db.Column(db.Integer, db.ForeignKey('sandbox_ontology.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creation_date = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Class membership
    class_id = db.Column(db.Integer, db.ForeignKey('ontology_class.id'), nullable=False)
    
    # Reference to the class
    ontology_class = db.relationship('OntologyClass', backref=db.backref('individuals', lazy=True))
    
    # Reference to the ontology
    ontology = db.relationship('SandboxOntology', backref=db.backref('ontology_individuals', lazy=True, cascade="all, delete-orphan"))
    
    # Property values as JSON
    property_values = db.Column(db.JSON, default=dict)
    
    def __repr__(self):
        return f"<OntologyIndividual {self.id}: {self.name}>"