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
            
            # Encode the PlantUML for use with the PlantUML server
            import base64
            import zlib
            
            def deflate_and_encode(content):
                """Deflate and encode content for PlantUML server URL."""
                zlibbed_str = zlib.compress(content.encode('utf-8'))
                compressed_str = zlibbed_str[2:-4]  # Remove zlib headers and checksum
                return base64.b64encode(compressed_str).decode('utf-8')
            
            try:
                # Encode the PlantUML code for the server URL
                encoded_uml = deflate_and_encode(plantuml_code)
                plantuml_url = f"https://www.plantuml.com/plantuml/img/{encoded_uml}"
                logger.info(f"Generated PlantUML URL: {plantuml_url}")
            except Exception as e:
                logger.error(f"Error encoding PlantUML: {str(e)}")
                plantuml_url = "https://www.plantuml.com/plantuml/img/SoWkIImgAStDuNBAJrBGjLDmpCbCJbMmKiX8pSd9vt98pKi1IW80"  # Default image
            
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
        .diagram-container {{ text-align: center; margin: 20px 0; }}
        .diagram-container img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="container mt-4">
        <h1>Ontology Diagram - {filename_base}</h1>
        
        <div class="card mb-4">
            <div class="card-header">
                <h5>UML Class Diagram</h5>
            </div>
            <div class="card-body">
                <div class="diagram-container">
                    <img src="{plantuml_url}" alt="Ontology Class Diagram" />
                </div>
                <p class="mt-3 text-center">
                    <a href="{plantuml_url}" target="_blank" class="btn btn-primary">View Full Size Diagram</a>
                </p>
            </div>
        </div>
        
        <div class="card mb-4">
            <div class="card-header">
                <h5>PlantUML Code</h5>
            </div>
            <div class="card-body">
                <p>You can visualize this by copying the code to the 
                <a href="https://www.plantuml.com/plantuml/uml/" target="_blank">PlantUML web server</a>.</p>
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
        # Start with PlantUML header - ultra simple version
        uml_code = [
            "@startuml",
            "' Ontology Class Diagram",
            f"' Ontology: {ontology.name}",
            "' Generated by FOL-BFO-OWL Tester",
            "",
            "' Simple styling",
            "skinparam monochrome false",
            "skinparam shadowing false",
            "skinparam defaultFontName Arial",
            "skinparam defaultFontSize 12",
            "",
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
            
            # Add simpler class definition without stereotypes
            class_name = self._sanitize_name(cls.name)
            uml_code.append(f"class {class_name}")
            
            # Add data properties if requested
            if include_data_properties:
                # Get both data properties and annotation properties
                all_properties = []
                
                # Try to get all data properties from the ontology first
                try:
                    data_properties = list(ontology.data_properties())
                    for prop in data_properties:
                        if hasattr(prop, 'domain') and cls in prop.domain:
                            all_properties.append(prop)
                except:
                    # If data_properties() method fails, continue with other methods
                    pass
                    
                # Try to get annotation properties if requested
                if include_annotation_properties:
                    try:
                        annotation_properties = list(ontology.annotation_properties())
                        for prop in annotation_properties:
                            if hasattr(prop, 'domain') and cls in prop.domain:
                                all_properties.append(prop)
                    except:
                        # If annotation_properties() method fails, continue with other methods
                        pass
                
                # Get all properties directly associated with the class
                for prop in cls.get_class_properties():
                    if hasattr(prop, 'name') and prop.name:
                        all_properties.append(prop)
                
                # Add properties from the ontology that have this class in their domain
                for prop in ontology.properties():
                    if hasattr(prop, 'domain') and cls in prop.domain:
                        all_properties.append(prop)
                
                # Add the properties to the class, checking if they're data properties
                for prop in all_properties:
                    if hasattr(prop, 'name') and prop.name:
                        prop_name = self._sanitize_name(prop.name)
                        
                        # Skip properties that are clearly object properties
                        is_object_prop = False
                        if hasattr(prop, 'range') and prop.range and len(prop.range) > 0:
                            for range_cls in prop.range:
                                if range_cls in classes:
                                    is_object_prop = True
                                    break
                        
                        if not is_object_prop:
                            # It's likely a data property or annotation property
                            range_type = "string"
                            if hasattr(prop, 'range') and prop.range and len(prop.range) > 0:
                                range_type = str(prop.range[0])
                            uml_code.append(f"{class_name} : +{prop_name} : {range_type}")
            
            # Add parents
            for parent in cls.is_a:
                if hasattr(parent, 'name') and parent.name and parent in classes:
                    parent_name = self._sanitize_name(parent.name)
                    uml_code.append(f"{parent_name} <|-- {class_name}")
        
        # Process object properties with more details
        uml_code.append("\n' Object properties")
        relations = set()
        
        # Get all object properties from the ontology
        try:
            all_object_properties = list(ontology.object_properties())
        except:
            # If object_properties() method fails, try to get them a different way
            all_object_properties = [p for p in ontology.properties() 
                               if hasattr(p, 'range') and p.range and 
                               len(p.range) > 0 and 
                               any(r in classes for r in p.range)]
        
        for prop in all_object_properties:
            if hasattr(prop, 'name') and prop.name:
                rel_name = self._sanitize_name(prop.name)
                
                # Handle the case where domain and range are explicitly defined
                if hasattr(prop, 'domain') and prop.domain and hasattr(prop, 'range') and prop.range:
                    for domain_cls in prop.domain:
                        for range_cls in prop.range:
                            if domain_cls in classes and range_cls in classes:
                                source = self._sanitize_name(domain_cls.name)
                                target = self._sanitize_name(range_cls.name)
                                
                                relation = f"{source} --> {target} : {rel_name}"
                                if relation not in relations:
                                    relations.add(relation)
                                    uml_code.append(relation)
                                    
        # Also check properties that might be found through class_properties
        for cls in classes:
            for prop in cls.get_class_properties():
                # Check if this is an object property
                if hasattr(prop, 'range') and prop.range and len(prop.range) > 0:
                    for range_cls in prop.range:
                        if range_cls in classes:
                            source = self._sanitize_name(cls.name)
                            target = self._sanitize_name(range_cls.name)
                            rel_name = self._sanitize_name(prop.name)
                            
                            relation = f"{source} --> {target} : {rel_name}"
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
                        
                        uml_code.append(f"object {ind_name}")
                        uml_code.append(f"{class_name} <.. {ind_name} : instance")
        
        # Add PlantUML footer
        uml_code.append("\n@enduml")
        
        return "\n".join(uml_code)
    
    def _sanitize_name(self, name):
        """Sanitize names for PlantUML by removing problematic characters."""
        if name is None:
            return "Unknown"
            
        # Replace problematic characters
        result = name.replace("#", "_").replace(":", "_")
        result = result.replace("'", "").replace("\"", "")
        result = result.replace(" ", "_").replace("-", "_")
        result = result.replace("(", "").replace(")", "")
        result = result.replace("<", "").replace(">", "")
        result = result.replace("/", "_").replace("\\", "_")
        
        # Make sure it starts with a letter to comply with PlantUML naming rules
        if result and not result[0].isalpha():
            result = "C_" + result
            
        return result