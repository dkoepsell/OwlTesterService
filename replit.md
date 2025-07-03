# FOL-BFO-OWL Analysis System

## Overview

This application is a comprehensive web service for testing and analyzing ontologies using First-Order Logic (FOL), Basic Formal Ontology (BFO), and Web Ontology Language (OWL). It provides advanced reasoning capabilities, interactive visualization tools, and AI-powered analysis features for ontology development and validation.

## System Architecture

### Backend Architecture
- **Framework**: Flask-based web application
- **Database**: PostgreSQL with SQLAlchemy ORM
- **OWL Processing**: Dual-layer approach using both Owlready2 and RDFlib for robust parsing
- **Reasoning**: Multi-reasoner system leveraging Pellet, HermiT, and other OWL reasoners
- **AI Integration**: OpenAI GPT-4o for generating implications and suggestions

### Frontend Architecture
- **UI Framework**: Bootstrap 5 with dark theme
- **Visualization**: D3.js for interactive ontology diagrams
- **Templating**: Jinja2 templates with modular components
- **JavaScript**: Modern ES6+ with async/await patterns

## Key Components

### 1. Ontology Analysis Engine (`owl_tester.py`)
- Comprehensive OWL file parsing and analysis
- Consistency checking with detailed reporting
- Expressivity detection (ALC, SHOIN, SROIQ)
- Axiom extraction and categorization
- FOL premise generation from ontology structures

### 2. Reasoning System
- **Transparent Reasoning**: Detailed methodology reporting
- **Derivation Tracing**: Visual representation of inference chains
- **Multi-reasoner Approach**: Robust consistency checking
- **Performance Metrics**: Timing and efficiency tracking

### 3. BFO Integration
- **BFO-2020 Definitions**: Complete class and relation mappings
- **Validation**: BFO-compatible expression testing
- **Notation Support**: Both traditional and BFO-style syntax

### 4. BVSS Visualization System
- **Visual Grammar**: Standardized symbols for BFO entities
- **Interactive Diagrams**: D3.js-based ontology visualization
- **Validation Interface**: Visual contradiction detection
- **Export Capabilities**: SVG and PNG diagram generation

### 5. User Management
- **Authentication**: Flask-Login with session management
- **User Dashboards**: Personalized analysis history
- **Anonymous Access**: Core functionality without registration

### 6. Sandbox Environment
- **Ontology Builder**: Interactive ontology creation
- **AI Suggestions**: Intelligent class and property recommendations
- **Export System**: Convert sandbox ontologies to formal OWL

## Data Flow

1. **File Upload**: Users upload OWL files through web interface
2. **Format Detection**: Automatic format detection and conversion
3. **Parsing**: Dual-layer parsing with fallback mechanisms
4. **Analysis**: Comprehensive ontology analysis including:
   - Statistics extraction
   - Consistency checking
   - Axiom categorization
   - Expressivity detection
5. **Visualization**: Interactive diagram generation
6. **AI Processing**: Real-world implications generation
7. **Storage**: Results stored in PostgreSQL database
8. **Presentation**: Rich web interface with detailed reporting

## External Dependencies

### Core Libraries
- **owlready2**: Primary OWL ontology handling
- **rdflib**: Alternative RDF parsing and serialization
- **nltk**: Natural language processing for FOL parsing
- **Flask**: Web framework with extensions
- **SQLAlchemy**: Database ORM
- **psycopg2**: PostgreSQL adapter

### AI Services
- **OpenAI API**: GPT-4o for generating implications and suggestions
- **Model**: Uses gpt-4o (latest available model)

### Frontend Dependencies
- **Bootstrap 5**: UI framework with dark theme
- **D3.js v7**: Data visualization library
- **Font Awesome**: Icon library
- **jQuery**: DOM manipulation and AJAX

### Development Tools
- **PlantUML**: UML diagram generation
- **Gunicorn**: WSGI HTTP server for production

## Deployment Strategy

### Environment Configuration
- **Development**: Local Flask development server
- **Production**: Gunicorn WSGI server
- **Database**: PostgreSQL with automatic migrations
- **File Storage**: Local filesystem with organized directory structure

### Database Schema
- **Users**: Authentication and profile management
- **OntologyFile**: Uploaded file metadata
- **OntologyAnalysis**: Analysis results and metrics
- **SandboxOntology**: User-created ontologies
- **FOLExpression**: Tested expressions history

### Migration System
- Automated database schema updates
- Backward compatibility maintenance
- Data preservation during updates

## Changelog

- July 03, 2025. Enhanced automatic format detection and conversion system
  - Implemented robust format detection for mislabeled ontology files
  - Added automatic conversion from Turtle, N-Triples, and other RDF formats to OWL/XML
  - Improved error handling and file validation during upload process
  - Added database cleanup for orphaned records
  - System now gracefully handles format mismatches and provides transparent conversion
- July 03, 2025. Initial setup

## User Preferences

Preferred communication style: Simple, everyday language.