"""
PlantUML Generator for OWL Ontologies

This module generates PlantUML class diagrams from OWL ontologies, representing
the class hierarchy, object properties, and other ontological relationships.
"""

import os
import logging
import tempfile
from urllib.parse import quote

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlantUMLGenerator:
    """
    A class to generate PlantUML diagrams from OWL ontologies.
    """
    
    def __init__(self):
        """
        Initialize the PlantUML generator.
        """
        # Use absolute path to the static folder
        self.static_folder = os.path.abspath('static')
        self.diagrams_folder = os.path.join(self.static_folder, 'diagrams')
        
        logger.info(f"Static folder path: {self.static_folder}")
        logger.info(f"Diagrams folder path: {self.diagrams_folder}")
        
        # Create diagrams directory if it doesn't exist
        os.makedirs(self.diagrams_folder, exist_ok=True)
        
    def generate_class_diagram(self, ontology, filename_base, include_individuals=False, 
                              include_data_properties=True, include_annotation_properties=False,
                              max_classes=100):
        """
        Generate a PlantUML class diagram from an ontology.
        
        Args:
            ontology: The loaded Owlready2 ontology
            filename_base (str): Base filename for saving the diagram
            include_individuals (bool): Whether to include individuals in the diagram
            include_data_properties (bool): Whether to include data properties
            include_annotation_properties (bool): Whether to include annotation properties
            max_classes (int): Maximum number of classes to include in the diagram
            
        Returns:
            tuple: (plantuml_code, diagram_path, svg_path)
        """
        logger.info(f"Generating class diagram for ontology {ontology.name}")
        
        # Generate PlantUML code
        plantuml_code = self._generate_plantuml_code(
            ontology, 
            include_individuals=include_individuals,
            include_data_properties=include_data_properties,
            include_annotation_properties=include_annotation_properties,
            max_classes=max_classes
        )
        
        # Generate and save the diagram
        diagram_path = os.path.join('static', 'diagrams', f"{filename_base}.png")
        svg_path = os.path.join('static', 'diagrams', f"{filename_base}.svg")
        
        # Save full path to file system
        full_diagram_path = os.path.join(self.static_folder, 'diagrams', f"{filename_base}.png")
        full_svg_path = os.path.join(self.static_folder, 'diagrams', f"{filename_base}.svg")
        
        # Save PlantUML source
        plantuml_path = os.path.join(self.static_folder, 'diagrams', f"{filename_base}.plantuml")
        with open(plantuml_path, 'w') as f:
            f.write(plantuml_code)
            
        # Instead of generating the diagram, we'll just provide the PlantUML code
        # Since we're having issues with the PlantUML server, we'll return a direct link to the PlantUML web server
        try:
            logger.info(f"Writing PlantUML source to {plantuml_path}")
            
            # Create the diagrams directory
            os.makedirs(os.path.join(self.static_folder, 'diagrams'), exist_ok=True)
            
            # Create a simple HTML file with the PlantUML code in it
            html_path = os.path.join(self.static_folder, 'diagrams', f"{filename_base}.html")
            with open(html_path, 'w') as f:
                f.write(f"""<!DOCTYPE html>
<html>
<head>
    <title>Ontology Diagram - {filename_base}</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        pre {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container mt-4">
        <h1>Ontology Diagram - {filename_base}</h1>
        <p>The PlantUML code for the diagram is provided below. You can visualize this by copying the code to the 
        <a href="https://www.plantuml.com/plantuml/uml/" target="_blank">PlantUML web server</a>.</p>
        
        <div class="card mb-4">
            <div class="card-header">
                <h5>PlantUML Code</h5>
            </div>
            <div class="card-body">
                <pre><code>{plantuml_code}</code></pre>
            </div>
        </div>
        
        <h2>Class Structure</h2>
        <p>The diagram represents the ontology class hierarchy and relationships.</p>
        
        <div class="card mt-3">
            <div class="card-header">
                <h5>Diagram Information</h5>
            </div>
            <div class="card-body">
                <ul>
                    <li><strong>Ontology Name:</strong> {ontology.name}</li>
                    <li><strong>Classes:</strong> {len(list(ontology.classes()))}</li>
                    <li><strong>Shown in Diagram:</strong> {min(len(list(ontology.classes())), max_classes)}</li>
                </ul>
            </div>
        </div>
    </div>
</body>
</html>""")
            
            # Return the paths - we're using an HTML representation instead of PNG/SVG
            logger.info(f"Created HTML diagram view at: {html_path}")
            return plantuml_code, f"/static/diagrams/{filename_base}.html", None
            
        except Exception as e:
            logger.error(f"Error creating diagram view: {str(e)}")
            logger.error(f"Exception type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return plantuml_code, None, None
        
    def _generate_plantuml_code(self, ontology, include_individuals=False, 
                               include_data_properties=True, include_annotation_properties=False,
                               max_classes=100):
        """
        Generate PlantUML code for a class diagram from an ontology.
        
        Args:
            ontology: The loaded Owlready2 ontology
            include_individuals (bool): Whether to include individuals in the diagram
            include_data_properties (bool): Whether to include data properties
            include_annotation_properties (bool): Whether to include annotation properties
            max_classes (int): Maximum number of classes to include in the diagram
            
        Returns:
            str: PlantUML code
        """
        # Start with PlantUML header
        uml_code = [
            "@startuml",
            "' Ontology Class Diagram",
            f"' Ontology: {ontology.name}",
            "' Generated by FOL-BFO-OWL Tester",
            "",
            "' Use dark blue theme",
            "!theme cerulean-outline",
            "",
            "' Styling options",
            "skinparam class {",
            "  BackgroundColor<<BFO>> LightBlue",
            "  BorderColor<<BFO>> DarkBlue",
            "  BackgroundColor<<Domain>> LightGreen",
            "  BorderColor<<Domain>> DarkGreen",
            "  BackgroundColor<<Individual>> White",
            "  BorderColor<<Individual>> Gray",
            "}",
            "",
            "' Class definitions"
        ]
        
        # Process classes (limit to max_classes)
        classes = list(ontology.classes())[:max_classes]
        
        # Track processed classes to avoid duplicates
        processed_classes = set()
        
        # Process class hierarchy
        for cls in classes:
            if cls in processed_classes:
                continue
                
            processed_classes.add(cls)
            
            # Determine stereotype
            if "BFO" in cls.iri or "IAO" in cls.iri:
                stereotype = "<<BFO>>"
            else:
                stereotype = "<<Domain>>"
                
            # Add class definition
            class_name = self._sanitize_name(cls.name)
            uml_code.append(f"class \"{class_name}\" {stereotype}")
            
            # Add data properties if requested
            if include_data_properties:
                for prop in cls.get_class_properties():
                    # Skip object properties, handle later
                    if hasattr(prop, 'range') and prop.range and len(prop.range) > 0 and prop.range[0] in classes:
                        continue
                        
                    if hasattr(prop, 'name') and prop.name:
                        prop_name = self._sanitize_name(prop.name)
                        uml_code.append(f"\"{class_name}\" : +{prop_name}")
            
            # Add parents
            for parent in cls.is_a:
                if hasattr(parent, 'name') and parent.name and parent in classes:
                    parent_name = self._sanitize_name(parent.name)
                    uml_code.append(f"\"{parent_name}\" <|-- \"{class_name}\"")
        
        # Process object properties
        uml_code.append("\n' Object properties")
        relations = set()
        
        for cls in classes:
            for prop in cls.get_class_properties():
                # Check if this is an object property
                if hasattr(prop, 'range') and prop.range and len(prop.range) > 0 and prop.range[0] in classes:
                    for range_cls in prop.range:
                        if range_cls in classes:
                            source = self._sanitize_name(cls.name)
                            target = self._sanitize_name(range_cls.name)
                            rel_name = self._sanitize_name(prop.name)
                            
                            relation = f"\"{source}\" --> \"{target}\" : {rel_name}"
                            if relation not in relations:
                                relations.add(relation)
                                uml_code.append(relation)
        
        # Process individuals if requested
        if include_individuals:
            uml_code.append("\n' Individuals")
            
            for cls in classes:
                individuals = list(cls.instances())
                
                for individual in individuals:
                    if hasattr(individual, 'name') and individual.name:
                        ind_name = self._sanitize_name(individual.name)
                        class_name = self._sanitize_name(cls.name)
                        
                        uml_code.append(f"object \"{ind_name}\" <<Individual>>")
                        uml_code.append(f"\"{class_name}\" <.. \"{ind_name}\" : instance")
        
        # Add PlantUML footer
        uml_code.append("\n@enduml")
        
        return "\n".join(uml_code)
    
    def _sanitize_name(self, name):
        """Sanitize names for PlantUML by removing problematic characters."""
        if name is None:
            return "Unknown"
            
        # Replace problematic characters
        return name.replace("#", "_").replace(":", "_").replace("'", "").replace("\"", "")