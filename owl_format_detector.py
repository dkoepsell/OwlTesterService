"""
Ontology Format Detection and Conversion Module

This module automatically detects and converts between different ontology file formats
including OWL XML, RDF/XML, Turtle, N-Triples, and other RDF serializations.
"""

import rdflib
import os
import tempfile
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class OntologyFormatConverter:
    """
    Automatically detects and converts ontology files between different formats.
    """
    
    # Supported RDF formats and their file extensions
    FORMAT_MAPPINGS = {
        'xml': 'xml',           # RDF/XML, OWL/XML
        'turtle': 'turtle',     # Turtle (.ttl)
        'n3': 'n3',            # Notation3 (.n3)
        'nt': 'nt',            # N-Triples (.nt)
        'json-ld': 'json-ld',  # JSON-LD (.jsonld)
        'trig': 'trig',        # TriG (.trig)
        'nquads': 'nquads',    # N-Quads (.nq)
    }
    
    def __init__(self):
        self.temp_files = []
    
    def detect_and_convert(self, file_path: str, target_format: str = 'xml') -> str:
        """
        Automatically detect the format of an ontology file and convert it to the target format.
        
        Args:
            file_path (str): Path to the input ontology file
            target_format (str): Target format ('xml' for OWL/XML)
            
        Returns:
            str: Path to the converted file, or original path if conversion wasn't needed
        """
        try:
            # First, try to detect the format by reading the file content
            detected_format = self._detect_format(file_path)
            logger.info(f"Detected format: {detected_format} for file: {file_path}")
            
            # If already in target format, return original path
            if detected_format == target_format:
                return file_path
            
            # Try to parse and convert the file
            converted_path = self._convert_format(file_path, detected_format, target_format)
            
            if converted_path:
                logger.info(f"Successfully converted {file_path} to {target_format}")
                return converted_path
            else:
                logger.warning(f"Failed to convert {file_path}, returning original")
                return file_path
                
        except Exception as e:
            logger.error(f"Error in format detection/conversion: {e}")
            return file_path
    
    def _detect_format(self, file_path: str) -> str:
        """
        Detect the format of an ontology file by examining its content.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(1000)  # Read first 1000 characters
            
            # XML-based formats (OWL/XML, RDF/XML)
            if content.strip().startswith('<?xml') or '<rdf:RDF' in content or '<owl:Ontology' in content:
                return 'xml'
            
            # Turtle format
            if (content.startswith('@prefix') or content.startswith('@base') or 
                any(line.strip().startswith('@') for line in content.split('\n')[:10])):
                return 'turtle'
            
            # N-Triples format (simple triples with dots)
            if all(line.strip().endswith('.') or line.strip() == '' or line.strip().startswith('#') 
                  for line in content.split('\n')[:10] if line.strip()):
                return 'nt'
            
            # JSON-LD format
            if content.strip().startswith('{') and '"@context"' in content:
                return 'json-ld'
            
            # Default to turtle for most text-based RDF
            return 'turtle'
            
        except Exception as e:
            logger.error(f"Error detecting format: {e}")
            return 'xml'  # Default fallback
    
    def _convert_format(self, input_path: str, input_format: str, output_format: str) -> str:
        """
        Convert an ontology file from one format to another using rdflib.
        """
        try:
            # Create RDF graph
            g = rdflib.Graph()
            
            # Parse the input file
            g.parse(input_path, format=input_format)
            
            # Create output file path
            input_name = Path(input_path).stem
            output_dir = Path(input_path).parent
            output_extension = 'owl' if output_format == 'xml' else output_format
            output_path = output_dir / f"{input_name}_converted.{output_extension}"
            
            # Serialize to target format
            with open(output_path, 'w', encoding='utf-8') as f:
                if output_format == 'xml':
                    # For OWL/XML, use pretty formatting
                    serialized = g.serialize(format='xml')
                    if isinstance(serialized, bytes):
                        f.write(serialized.decode('utf-8'))
                    else:
                        f.write(serialized)
                else:
                    serialized = g.serialize(format=output_format)
                    if isinstance(serialized, bytes):
                        f.write(serialized.decode('utf-8'))
                    else:
                        f.write(serialized)
            
            # Keep track of temp files for cleanup
            self.temp_files.append(str(output_path))
            
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Error converting format: {e}")
            
            # Try alternative parsing approaches
            return self._try_alternative_parsing(input_path, output_format)
    
    def _try_alternative_parsing(self, input_path: str, output_format: str) -> str:
        """
        Try alternative parsing methods when the primary approach fails.
        """
        try:
            g = rdflib.Graph()
            
            # Try different format parsers
            formats_to_try = ['turtle', 'xml', 'nt', 'n3']
            
            for fmt in formats_to_try:
                try:
                    g.parse(input_path, format=fmt)
                    logger.info(f"Successfully parsed with format: {fmt}")
                    break
                except:
                    continue
            
            if len(g) == 0:
                logger.error("Could not parse file with any format")
                return None
            
            # Convert to target format
            input_name = Path(input_path).stem
            output_dir = Path(input_path).parent
            output_extension = 'owl' if output_format == 'xml' else output_format
            output_path = output_dir / f"{input_name}_converted.{output_extension}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                serialized = g.serialize(format=output_format)
                if isinstance(serialized, bytes):
                    f.write(serialized.decode('utf-8'))
                else:
                    f.write(serialized)
            
            self.temp_files.append(str(output_path))
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Alternative parsing also failed: {e}")
            return None
    
    def cleanup(self):
        """Clean up temporary converted files."""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as e:
                logger.error(f"Error cleaning up temp file {temp_file}: {e}")
        
        self.temp_files.clear()


def auto_convert_ontology(file_path: str, target_format: str = 'xml') -> str:
    """
    Convenience function to automatically detect and convert an ontology file.
    
    Args:
        file_path (str): Path to the ontology file
        target_format (str): Target format ('xml' for OWL/XML)
        
    Returns:
        str: Path to the converted file (or original if no conversion needed)
    """
    converter = OntologyFormatConverter()
    try:
        return converter.detect_and_convert(file_path, target_format)
    finally:
        # Don't cleanup here - let the calling code manage cleanup
        pass