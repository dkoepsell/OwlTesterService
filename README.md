# FOL-BFO-OWL Analysis System

A sophisticated web service for comprehensive ontology analysis that leverages advanced reasoning technologies and interactive visualization tools.

## Overview

This application provides a comprehensive platform for testing and analyzing ontologies with support for First-Order Logic (FOL), Basic Formal Ontology (BFO), and Web Ontology Language (OWL). It enables users to validate ontologies, test for consistency, check for contradictions, and generate interactive visualizations of ontological structures.

## Key Features

### Ontology Analysis

- **File Upload**: Support for uploading OWL ontology files in various formats (RDF/XML, Turtle, etc.)
- **Multi-layer Parsing**: Uses both Owlready2 and RDFlib for robust file parsing with fallback mechanisms
- **Comprehensive Statistics**: Detailed counts and metrics for classes, properties, individuals, and axioms
- **Expressivity Detection**: Analysis of DL expressivity (ALC, SHOIN, SROIQ, etc.)
- **Case-insensitive Entity Matching**: Accommodates varied capitalization in entity references

### Reasoning and Consistency

- **Transparent Reasoning**: Detailed information about the reasoning methodology used
- **Derivation Tracing**: Visual representation of inference chains with supporting evidence
- **Multi-reasoner Approach**: Uses Pellet and other reasoners for robust consistency checking
- **Contradiction Detection**: Clear identification of logical inconsistencies in ontologies
- **Performance Metrics**: Timing information for reasoning operations

For more details about the reasoning enhancements, see the [Reasoning README](README_REASONING.md).

### FOL Integration

- **Expression Testing**: Test FOL expressions for validity and BFO compatibility
- **Notation Support**: Handles both traditional notation (Class(x)) and BFO-style notation (instance_of(x,Class,t))
- **Premise Extraction**: Automatic generation of FOL premises from ontology axioms
- **Implication Generation**: Uses OpenAI to generate real-world implications from FOL premises

### Visualization

- **Interactive Diagrams**: D3.js-based visualization of ontology structure
- **Entity Relationship Display**: Clear visual representation of classes, properties, and individuals
- **Axiom Browser**: Tabbed interface for exploring different types of axioms
- **Derivation Trace Visualization**: Visual representation of reasoning steps

### User Management

- **User Authentication**: Support for registered users with personalized dashboards
- **Anonymous Access**: Core functionality available without login
- **History Tracking**: Record of previously uploaded ontologies and analyses
- **User Dashboard**: Personalized view of ontology analysis history

### Ontology Development

- **Sandbox Environment**: Create and edit ontologies directly in the browser
- **AI Assistance**: Suggestions for classes, properties, and BFO categories
- **Domain-specific Support**: Tailored suggestions based on ontology domain and subject
- **OWL/RDF Export**: Download created ontologies in standard formats

### Kindwork: Ontologies for Non-Ontologists

Kindwork, at `/kindwork`, guides people with no ontology training to a working BFO 2020 ontology by asking plain yes/no questions about their own terms.

- **Bring Your Terms**: Paste a list, or upload a spreadsheet, data dictionary, JSON Schema, or SQL table definitions
- **AI-proposed Answers**: With your own OpenAI or Anthropic (Claude) key, AI proposes an answer to each question; nothing counts until you confirm the term yourself
- **Connect Your Terms**: A guided step that turns the sorted list (a taxonomy) into an ontology, by connecting terms: who holds a license, what an inspection is about, which step comes first, what is part of what. Each connection is shown as the rule it becomes ("Every Wheel is part of some Car"), only connections that make sense for the two kinds are offered, missing terms can be added on the spot, and AI can suggest connections that you keep or leave out
- **Reasoner-checked Confirmation**: Every confirmation runs HermiT, cross-checked by Pellet, against BFO 2020; terms that cross or split a basic kind are held back with a card explaining why in plain words
- **Downloads**: The classified list (CSV), the ontology (Turtle), SHACL shapes, keyword source, and a standalone tracker app
- **Kindwork Workbench**: At `/kindwork/workbench`, lint keyword source, check a model or ontology, or check a Kindwork export with its shapes
- **API and MCP**: JSON routes under `/kindwork/v1` and an MCP endpoint at `/kindwork/mcp` with six tools

## Technology Stack

- **Backend**: Flask-based Python web application
- **Database**: PostgreSQL for data persistence
- **Reasoning**: Owlready2 with Pellet reasoner integration
- **Parsing**: Combined Owlready2 and RDFlib approach
- **Visualization**: D3.js for interactive diagrams
- **AI Integration**: OpenAI API for generating implications and descriptions; your own OpenAI or Anthropic key for implications and Kindwork proposals
- **Kindwork Core**: Node.js 20 sidecar running the vendored Kindwork generators (`kindwork_core/`)
- **Authentication**: Flask-Login for user management
- **Forms**: Flask-WTF for secure form handling

## Getting Started

### Prerequisites

- Python 3.7+
- PostgreSQL
- Java (for the Pellet reasoner)
- Node.js 20+ (for Kindwork)

### Installation

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`, then `npm ci` in `kindwork_core/`
3. Set up PostgreSQL database
4. Configure environment variables
5. Run the application: `python main.py`

## Usage Examples

### Testing FOL Expressions

```
forall x,t (instance_of(x,Continuant,t) -> exists p (instance_of(p,Process,t) & participates_in(x,p,t)))
```

### Analyzing Ontologies

Upload an OWL file through the web interface to receive:
- Comprehensive statistics
- Consistency check results
- Visualization of class hierarchy
- Extracted FOL premises
- Generated real-world implications

### Building an Ontology with Kindwork

1. Open `/kindwork` and paste your terms, or upload a spreadsheet
2. Optionally add your own AI key in the bar at the top, and press Propose answers
3. Check each term's answers and press Confirm; the reasoner runs before the term counts
4. Connect the terms: read each connection as a rule and keep only the ones true of every case
5. Resolve any held-back terms, then download the results

### Creating Ontologies

Use the Sandbox environment to:
1. Specify domain and subject
2. Add classes with BFO categories
3. Define properties and relationships
4. Export as standard OWL/RDF

## Acknowledgments

- The BFO community for foundational ontology resources
- Owlready2 and RDFlib developers for excellent parsing tools
- OpenAI for API access for implication generation
- D3.js community for visualization capabilities

## License

This project is licensed under the MIT License - see the LICENSE file for details.