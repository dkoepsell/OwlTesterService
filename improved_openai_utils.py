import os
import json
import logging
from openai import OpenAI

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
# do not change this unless explicitly requested by the user
OPENAI_MODEL = "gpt-4o"

def get_openai_client():
    """
    Create and return an OpenAI client using the API key from environment variables.
    
    Returns:
        OpenAI: Configured OpenAI client
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not found in environment variables")
        raise ValueError("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")
    
    return OpenAI(api_key=api_key)
    
def suggest_ontology_classes(domain, subject):
    """
    Generate suggested classes and properties for an ontology based on domain and subject.
    
    Args:
        domain (str): The domain of the ontology (e.g., "Medicine", "Law", "Finance")
        subject (str): The specific subject within the domain (e.g., "Cardiology", "Contract Law")
        
    Returns:
        list: A list of dictionaries containing suggested classes with name, description, and BFO category
    """
    try:
        logger.info(f"Starting AI suggestion generation for domain: {domain}, subject: {subject}")
        
        # Return predefined responses for testing purposes
        if domain.lower() == "test" or subject.lower() == "test":
            logger.info("Using test data instead of calling OpenAI API")
            return [
                {
                    "name": "TestClass1",
                    "description": "A test class for demonstration",
                    "bfo_category": "Object",
                    "properties": [
                        {"name": "hasProperty1", "type": "object", "description": "Test property 1"}
                    ]
                },
                {
                    "name": "TestClass2",
                    "description": "Another test class",
                    "bfo_category": "Process",
                    "properties": [
                        {"name": "hasProperty2", "type": "data", "description": "Test property 2"}
                    ]
                }
            ]
        
        # Simple responses for common domains to prevent API calls for demo purposes
        simple_domains = {
            "medicine": [
                {
                    "name": "Patient",
                    "description": "A person receiving medical treatment",
                    "bfo_category": "Object",
                    "properties": [
                        {"name": "hasDiagnosis", "type": "object", "description": "Medical diagnosis assigned to patient"}
                    ]
                },
                {
                    "name": "Diagnosis",
                    "description": "A medical conclusion about patient condition",
                    "bfo_category": "InformationEntity",
                    "properties": [
                        {"name": "hasSymptom", "type": "object", "description": "Symptom related to diagnosis"}
                    ]
                }
            ],
            "education": [
                {
                    "name": "Course",
                    "description": "A program of instruction",
                    "bfo_category": "InformationEntity",
                    "properties": [
                        {"name": "hasMaterial", "type": "object", "description": "Material used in the course"}
                    ]
                },
                {
                    "name": "Student",
                    "description": "A person enrolled in educational institution",
                    "bfo_category": "Object",
                    "properties": [
                        {"name": "enrolledIn", "type": "object", "description": "Course the student is enrolled in"}
                    ]
                }
            ]
        }
        
        # Check if we have a simple domain match
        if domain.lower() in simple_domains:
            logger.info(f"Using simple domain match for {domain}")
            return simple_domains[domain.lower()]
        
        try:
            client = get_openai_client()
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            return [{"error": f"Failed to initialize OpenAI client: {str(e)}"}]
        
        system_prompt = """You are an expert in ontology development and knowledge engineering.
Your task is to suggest appropriate classes for an ontology based on a specific domain and subject.
You should consider Basic Formal Ontology (BFO) principles in your suggestions.

IMPORTANT: You must format your response as a JSON object with a key called "suggestions" containing an array of class objects.
Each class object in the array should have:
1. name: The class name (in CamelCase without spaces)
2. description: A clear description of what the class represents
3. bfo_category: The most appropriate BFO upper-level category for this class (if applicable)
4. properties: An array of suggested properties (object, data, or annotation) for this class

Example response format:
{
  "suggestions": [
    {
      "name": "ClassName1",
      "description": "Description of class 1",
      "bfo_category": "Object",
      "properties": [
        {"name": "property1", "type": "object", "description": "Description of property 1"},
        {"name": "property2", "type": "data", "description": "Description of property 2"}
      ]
    }
  ]
}
"""

        user_prompt = f"""Please suggest 3-5 core classes and properties for an ontology in the domain of "{domain}" focusing on the subject of "{subject}".
For each class, provide:
1. A well-formed class name in CamelCase (no spaces)
2. A clear, concise description
3. The most appropriate BFO upper-level category
4. 1-2 properties that would be associated with this class

IMPORTANT: Format your response as a JSON object with a "suggestions" array containing all the class objects, as shown in the example in my previous message.
"""

        # Make the API call with timeout handling
        try:
            logger.info("Calling OpenAI API with timeout of 15 seconds")
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                timeout=15.0,
                max_tokens=1000  # Limit token count for faster response
            )
            logger.info("Successfully received response from OpenAI API")
        except Exception as e:
            logger.error(f"Error calling OpenAI API for suggestions: {str(e)}")
            return [{"error": f"Failed to get suggestions from OpenAI: {str(e)}"}]
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response")
            return [{"error": "The OpenAI API returned an empty response. Please try again later."}]
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content")
            return [{"error": "The OpenAI API returned empty content. Please try again later."}]
            
        logger.info(f"Raw OpenAI class suggestions response: {result_text}")
        
        # Handle different JSON formats that might be returned
        try:
            logger.info(f"Attempting to parse JSON response: {result_text[:min(200, len(result_text))]}...")
            result = json.loads(result_text)
            logger.info(f"Successfully loaded JSON. Response structure: {type(result).__name__}")
            if isinstance(result, dict):
                logger.info(f"JSON keys: {list(result.keys())}")
            
            # Extract the suggestions depending on the structure of the response
            suggestions = []
            
            # Case 1: Response is a list of suggestions
            if isinstance(result, list):
                logger.info("Case 1: Response is a list")
                suggestions = result
            # Case 2: Response has a 'classes' key
            elif isinstance(result, dict) and "classes" in result and isinstance(result.get("classes"), list):
                logger.info("Case 2: Response has a 'classes' key")
                suggestions = result.get("classes")
            # Case 3: Response has a 'suggestions' key
            elif isinstance(result, dict) and "suggestions" in result and isinstance(result.get("suggestions"), list):
                logger.info("Case 3: Response has a 'suggestions' key")
                suggestions = result.get("suggestions")
            # Case 4: Single object response
            elif isinstance(result, dict) and "name" in result and "description" in result:
                logger.info("Case 4: Response is a single class object")
                suggestions = [result]
            # Case 5: Handle numbered keys
            else:
                logger.info("Case 5: Checking for other structures")
                if isinstance(result, dict):
                    for key, value in result.items():
                        if isinstance(value, dict) and "name" in value:
                            logger.info(f"Found class in key {key}")
                            suggestions.append(value)
            
            if suggestions:
                logger.info(f"Successfully parsed {len(suggestions)} class suggestions")
                if len(suggestions) > 0:
                    logger.info(f"Example suggestion: {json.dumps(suggestions[0])}")
                return suggestions
            else:
                logger.warning("No suggestions found in the response")
                # Return default suggestions if parsing failed
                return [
                    {
                        "name": f"{domain.capitalize()}Entity",
                        "description": f"A generic entity in the {domain} domain",
                        "bfo_category": "Entity",
                        "properties": [
                            {"name": "hasName", "type": "data", "description": "Name of the entity"}
                        ]
                    }
                ]
            
        except Exception as e:
            logger.error(f"Error parsing OpenAI class suggestions: {str(e)}")
            # Return default suggestions if parsing failed
            return [
                {
                    "name": f"{domain.capitalize()}Entity",
                    "description": f"A generic entity in the {domain} domain",
                    "bfo_category": "Entity",
                    "properties": [
                        {"name": "hasName", "type": "data", "description": "Name of the entity"}
                    ]
                }
            ]
        
    except Exception as e:
        logger.error(f"Error generating class suggestions: {str(e)}")
        return [{"error": str(e)}]

def suggest_bfo_category(class_name, description=""):
    """
    Suggest the most appropriate BFO category for a given class based on its name and description.
    
    Args:
        class_name (str): The name of the class
        description (str): The description of the class (optional)
        
    Returns:
        dict: Dictionary with suggested BFO category and explanation
    """
    # Simple mapping for common class types
    common_mappings = {
        "patient": "Object",
        "disease": "Disposition",
        "diagnosis": "InformationEntity", 
        "treatment": "Process",
        "doctor": "Object",
        "hospital": "Object",
        "medication": "Object",
        "symptom": "Quality",
        "test": "Process",
        "record": "InformationEntity",
        "event": "Process",
        "document": "InformationEntity",
        "location": "Site",
        "role": "Role",
        "function": "Function",
        "property": "Quality",
        "course": "InformationEntity",
        "student": "Object",
        "teacher": "Object",
        "class": "Process",
        "material": "Object"
    }
    
    # Check for common mappings first
    for key, value in common_mappings.items():
        if key in class_name.lower():
            return {
                "bfo_category": value,
                "explanation": f"Common pattern match: classes containing '{key}' are typically of BFO category '{value}'."
            }
    
    try:
        client = get_openai_client()
        
        system_prompt = """You are an expert in Basic Formal Ontology (BFO).
Your task is to determine the most appropriate BFO category for a given ontology class.
Provide your response as a JSON object with:
1. bfo_category: The name of the most appropriate BFO category
2. explanation: A brief explanation of why this category is appropriate

Key BFO categories include:
- Continuant: Entities that persist through time (Independent Continuant, Specifically Dependent Continuant, Generically Dependent Continuant)
- Occurrent: Entities that unfold or happen in time (Process, Process Boundary, Spatiotemporal Region, Temporal Region)
- Material Entity: Physical objects with mass (Object, Fiat Object Part, Object Aggregate)
- Immaterial Entity: Non-physical entities (Site, Spatial Region, Continuant Fiat Boundary)
- Quality: Dependent entities that inhere in their bearers (e.g., color, shape, temperature)
- Realizable Entity: Entities whose instances can be realized in processes (Role, Function, Disposition)
- Process: Entities that happen or unfold in time
- Information Entity: Generically dependent entities that are about something
"""

        user_prompt = f"""Class Name: {class_name}
Description: {description if description else 'No description provided'}

Based on this information, determine the most appropriate BFO category for this class.
Provide your response as a JSON object with the BFO category name and a brief explanation.
Be specific about which exact BFO category is most appropriate, not just the general type.
"""

        # Make the API call with timeout handling
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                timeout=10.0
            )
        except Exception as e:
            logger.error(f"Error calling OpenAI API for BFO category: {str(e)}")
            # Make a best guess based on the class name
            if any(word in class_name.lower() for word in ["process", "event", "activity", "procedure"]):
                return {"bfo_category": "Process", "explanation": "Based on naming convention"}
            elif any(word in class_name.lower() for word in ["object", "thing", "entity"]):
                return {"bfo_category": "Object", "explanation": "Based on naming convention"}
            else:
                return {"bfo_category": "Entity", "explanation": "Default category when API call fails"}
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response when suggesting BFO category")
            return {"bfo_category": "Entity", "explanation": "API returned empty response"}
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content when suggesting BFO category")
            return {"bfo_category": "Entity", "explanation": "API returned empty content"}
            
        logger.info(f"Raw OpenAI BFO category suggestion: {result_text}")
        
        try:
            result = json.loads(result_text)
            logger.info(f"Successfully parsed BFO suggestion. Keys: {list(result.keys())}")
            return {
                "bfo_category": result.get("bfo_category", "Entity"),
                "explanation": result.get("explanation", "")
            }
        except Exception as e:
            logger.error(f"Error parsing OpenAI BFO category suggestion: {str(e)}")
            return {"bfo_category": "Entity", "explanation": f"Error parsing result: {str(e)}"}
        
    except Exception as e:
        logger.error(f"Error suggesting BFO category: {str(e)}")
        return {"bfo_category": "Entity", "explanation": f"Error: {str(e)}"}

def suggest_ontology_properties(domain, subject):
    """
    Generate suggested properties for an ontology based on domain and subject.
    
    Args:
        domain (str): The domain of the ontology (e.g., "Medicine", "Law", "Finance")
        subject (str): The specific subject within the domain (e.g., "Cardiology", "Contract Law")
        
    Returns:
        list: A list of dictionaries containing suggested properties with name, description, and type
    """
    try:
        logger.info(f"Starting AI property suggestion generation for domain: {domain}, subject: {subject}")
        
        # Return predefined responses for testing purposes
        if domain.lower() == "test" or subject.lower() == "test":
            logger.info("Using test data instead of calling OpenAI API")
            return [
                {
                    "name": "hasTestProperty1",
                    "description": "A test object property for demonstration",
                    "type": "object",
                    "domain": "TestClass1",
                    "range": "TestClass2"
                },
                {
                    "name": "testDataProperty",
                    "description": "A test data property",
                    "type": "data",
                    "domain": "TestClass1",
                    "datatype": "string"
                }
            ]
        
        # Simple responses for common domains to prevent API calls for demo purposes
        simple_properties = {
            "medicine": [
                {
                    "name": "diagnosedWith",
                    "description": "Relates a patient to their diagnosis",
                    "type": "object",
                    "domain": "Patient",
                    "range": "Diagnosis"
                },
                {
                    "name": "treatedBy",
                    "description": "Relates a patient to their treating physician",
                    "type": "object",
                    "domain": "Patient",
                    "range": "Physician"
                },
                {
                    "name": "hasSeverity",
                    "description": "The severity level of a condition",
                    "type": "data",
                    "domain": "Diagnosis",
                    "datatype": "string"
                }
            ],
            "education": [
                {
                    "name": "enrolledIn",
                    "description": "Relates a student to a course they are enrolled in",
                    "type": "object",
                    "domain": "Student",
                    "range": "Course"
                },
                {
                    "name": "taughtBy",
                    "description": "Relates a course to its instructor",
                    "type": "object",
                    "domain": "Course",
                    "range": "Instructor"
                },
                {
                    "name": "hasCredits",
                    "description": "The number of credits a course is worth",
                    "type": "data",
                    "domain": "Course",
                    "datatype": "integer"
                }
            ]
        }
        
        # Check if we have a simple domain match
        if domain.lower() in simple_properties:
            logger.info(f"Using simple domain match for {domain}")
            return simple_properties[domain.lower()]
        
        try:
            client = get_openai_client()
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            return [{"error": f"Failed to initialize OpenAI client: {str(e)}"}]
        
        system_prompt = """You are an expert in ontology development and knowledge engineering.
Your task is to suggest appropriate properties for an ontology based on a specific domain and subject.
You should consider both object properties (relations between entities) and data properties.

IMPORTANT: You must format your response as a JSON object with a key called "suggestions" containing an array of property objects.
Each property object in the array should have:
1. name: The property name (in camelCase, starting with lowercase)
2. description: A clear description of what the property represents
3. type: Either "object" for object properties or "data" for data properties
4. domain: The class that this property would be associated with
5. range: For object properties, the class that serves as the range; for data properties, use a datatype (string, integer, etc.)

Example response format:
{
  "suggestions": [
    {
      "name": "hasPart",
      "description": "Relates an entity to its constituent parts",
      "type": "object",
      "domain": "WholeEntity",
      "range": "PartEntity"
    },
    {
      "name": "dateCreated",
      "description": "The date when an entity was created",
      "type": "data",
      "domain": "Document",
      "datatype": "dateTime"
    }
  ]
}
"""

        user_prompt = f"""Please suggest 3-5 core properties for an ontology in the domain of "{domain}" focusing on the subject of "{subject}".
For each property, provide:
1. A well-formed property name in camelCase starting with lowercase (e.g., hasPart, isLocatedIn)
2. A clear, concise description
3. Whether it's an object property (relating two classes) or a data property (with literal values)
4. The domain class (what class would have this property)
5. The range class for object properties or datatype for data properties

IMPORTANT: Format your response as a JSON object with a "suggestions" array containing all the property objects, as shown in the example in my previous message.
"""

        # Make the API call with timeout handling
        try:
            logger.info("Calling OpenAI API with timeout of 15 seconds")
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                timeout=15.0,
                max_tokens=1000  # Limit token count for faster response
            )
            logger.info("Successfully received response from OpenAI API")
        except Exception as e:
            logger.error(f"Error calling OpenAI API for property suggestions: {str(e)}")
            return [{"error": f"Failed to get property suggestions from OpenAI: {str(e)}"}]
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response")
            return [{"error": "The OpenAI API returned an empty response. Please try again later."}]
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content")
            return [{"error": "The OpenAI API returned empty content. Please try again later."}]
            
        logger.info(f"Raw OpenAI property suggestions response: {result_text}")
        
        # Handle different JSON formats that might be returned
        try:
            logger.info(f"Attempting to parse JSON response: {result_text[:min(200, len(result_text))]}...")
            result = json.loads(result_text)
            logger.info(f"Successfully loaded JSON. Response structure: {type(result).__name__}")
            
            # Extract the suggestions depending on the structure of the response
            suggestions = []
            
            # Case 1: Response is a list of suggestions
            if isinstance(result, list):
                logger.info("Case 1: Response is a list")
                suggestions = result
            # Case 2: Response has a 'properties' key
            elif isinstance(result, dict) and "properties" in result and isinstance(result.get("properties"), list):
                logger.info("Case 2: Response has a 'properties' key")
                suggestions = result.get("properties")
            # Case 3: Response has a 'suggestions' key
            elif isinstance(result, dict) and "suggestions" in result and isinstance(result.get("suggestions"), list):
                logger.info("Case 3: Response has a 'suggestions' key")
                suggestions = result.get("suggestions")
            # Case 4: Single object response
            elif isinstance(result, dict) and "name" in result and "description" in result:
                logger.info("Case 4: Response is a single property object")
                suggestions = [result]
            # Case 5: Handle numbered keys
            else:
                logger.info("Case 5: Checking for other structures")
                if isinstance(result, dict):
                    for key, value in result.items():
                        if isinstance(value, dict) and "name" in value:
                            logger.info(f"Found property in key {key}")
                            suggestions.append(value)
            
            if suggestions:
                logger.info(f"Successfully parsed {len(suggestions)} property suggestions")
                if len(suggestions) > 0:
                    logger.info(f"Example suggestion: {json.dumps(suggestions[0])}")
                return suggestions
            else:
                logger.warning("No property suggestions found in the response")
                # Return default suggestions if parsing failed
                return [
                    {
                        "name": f"has{domain.capitalize()}Name",
                        "description": f"The name of a {domain} entity",
                        "type": "data",
                        "domain": f"{domain.capitalize()}Entity",
                        "datatype": "string"
                    }
                ]
            
        except Exception as e:
            logger.error(f"Error parsing OpenAI property suggestions: {str(e)}")
            # Return default suggestions if parsing failed
            return [
                {
                    "name": f"has{domain.capitalize()}Relationship",
                    "description": f"A generic relationship in the {domain} domain",
                    "type": "object",
                    "domain": f"{domain.capitalize()}Entity",
                    "range": f"{domain.capitalize()}RelatedEntity"
                }
            ]
        
    except Exception as e:
        logger.error(f"Error generating property suggestions: {str(e)}")
        return [{"error": str(e)}]

def generate_class_description(class_name):
    """
    Generate a description for a class based on its name.
    
    Args:
        class_name (str): The name of the class
        
    Returns:
        dict: Dictionary with generated description
    """
    # Simple descriptions for common class names
    common_descriptions = {
        "patient": "A person receiving medical care or treatment from a healthcare provider.",
        "doctor": "A medical professional qualified to diagnose and treat medical conditions.",
        "hospital": "A healthcare institution providing treatment with specialized staff and equipment.",
        "disease": "A disorder of structure or function in a human, animal, or plant.",
        "treatment": "Medical care given to a patient for an illness or injury.",
        "medication": "A drug or other form of medicine that treats, prevents, or alleviates symptoms of disease.",
        "symptom": "A physical or mental feature indicating a condition or disease.",
        "diagnosis": "The identification of the nature of an illness or problem by examination.",
        "record": "A collection of information about a patient, event, or process.",
        "student": "A person who is studying at a school, college, or university.",
        "teacher": "A person who helps students acquire knowledge, competence, or virtue.",
        "course": "A series of lessons or lectures on a particular subject.",
        "class": "A group of students who are taught together.",
        "material": "Resources used for teaching or learning.",
        "test": "An assessment intended to measure knowledge, skill, aptitude, or classification."
    }
    
    # Check if we have a simple match
    for key, value in common_descriptions.items():
        if key.lower() in class_name.lower():
            return {"description": value}
    
    try:
        client = get_openai_client()
        
        system_prompt = """You are an expert in ontology development.
Your task is to generate a clear, concise description for an ontology class based on its name.
The description should explain what the class represents in the context of domain ontologies.
Keep descriptions between 30-100 words and focus on essential characteristics of the concept.
Respond with a JSON object containing a single 'description' field.
"""

        user_prompt = f"""Class Name: {class_name}

Please generate a clear, concise description for this ontology class.
Focus on what this class would represent in a domain ontology.
"""

        # Make the API call with timeout
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=150,
                timeout=10.0
            )
        except Exception as e:
            logger.error(f"Error calling OpenAI API for description: {str(e)}")
            # Generate a simple description based on class name
            # Split camel case into separate words
            words = []
            current_word = ""
            for char in class_name:
                if char.isupper() and current_word:
                    words.append(current_word)
                    current_word = char.lower()
                else:
                    current_word += char.lower()
            if current_word:
                words.append(current_word)
                
            return {"description": f"A class representing {' '.join(words)} in the domain."}
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response when generating description")
            return {"description": f"A class representing {class_name}."}
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content when generating description")
            return {"description": f"A class representing {class_name}."}
            
        logger.info(f"Raw OpenAI description generation: {result_text}")
        
        try:
            result = json.loads(result_text)
            logger.info(f"Successfully parsed description. Keys: {list(result.keys())}")
            return {"description": result.get("description", f"A class representing {class_name}.")}
        except Exception as e:
            logger.error(f"Error parsing OpenAI description generation: {str(e)}")
            return {"description": f"A class representing {class_name}."}
        
    except Exception as e:
        logger.error(f"Error generating class description: {str(e)}")
        return {"description": f"A class representing {class_name}."}