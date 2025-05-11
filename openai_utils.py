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
        
        # Return predefined responses for testing if there's an issue with OpenAI API
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
    },
    {
      "name": "ClassName2",
      "description": "Description of class 2",
      "bfo_category": "Process",
      "properties": [
        {"name": "property3", "type": "object", "description": "Description of property 3"}
      ]
    }
  ]
}
"""

        user_prompt = f"""Please suggest 10-15 core classes and properties for an ontology in the domain of "{domain}" focusing on the subject of "{subject}".
For each class, provide:
1. A well-formed class name in CamelCase (no spaces)
2. A clear, concise description
3. The most appropriate BFO upper-level category
4. 2-3 properties that would be associated with this class

IMPORTANT: Format your response as a JSON object with a "suggestions" array containing all the class objects, as shown in the example in my previous message. Do not return a single class object.

Classes should cover the core concepts needed for this domain and subject.
Ensure the suggestions follow ontology best practices and would be useful for domain experts.
"""

        # Make the API call
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
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
            elif isinstance(result, dict) and result.get("classes") and isinstance(result.get("classes"), list):
                logger.info("Case 2: Response has a 'classes' key")
                suggestions = result.get("classes")
            # Case 3: Response has a 'suggestions' key
            elif isinstance(result, dict) and result.get("suggestions") and isinstance(result.get("suggestions"), list):
                logger.info("Case 3: Response has a 'suggestions' key")
                suggestions = result.get("suggestions")
            # Case 4: Single object response (as seen in our logs)
            elif isinstance(result, dict) and "name" in result and "description" in result:
                logger.info("Case 4: Response is a single class object")
                # Add single suggestion to the list
                suggestions = [result]
            # Case 5: Handle numbered keys
            else:
                logger.info("Case 5: Checking for other structures")
                if isinstance(result, dict):
                    for key, value in result.items():
                        logger.info(f"Checking key: {key}")
                        if isinstance(value, dict) and "name" in value:
                            logger.info(f"Found class in key {key}")
                            suggestions.append(value)
            
            if suggestions:
                logger.info(f"Successfully parsed {len(suggestions)} class suggestions")
                # Log the first suggestion as an example
                if len(suggestions) > 0:
                    logger.info(f"Example suggestion: {json.dumps(suggestions[0])}")
                return suggestions
            else:
                logger.warning("No suggestions found in the response")
                return []
            
        except Exception as e:
            logger.error(f"Error parsing OpenAI class suggestions: {str(e)}")
            return []
        
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

        # Make the API call
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response when suggesting BFO category")
            return {"error": "The OpenAI API returned an empty response. Please try again later."}
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content when suggesting BFO category")
            return {"error": "The OpenAI API returned empty content. Please try again later."}
            
        logger.info(f"Raw OpenAI BFO category suggestion: {result_text}")
        
        try:
            result = json.loads(result_text)
            logger.info(f"Successfully parsed BFO suggestion. Keys: {list(result.keys())}")
            return {
                "bfo_category": result.get("bfo_category", ""),
                "explanation": result.get("explanation", "")
            }
        except Exception as e:
            logger.error(f"Error parsing OpenAI BFO category suggestion: {str(e)}")
            return {"bfo_category": "", "error": str(e)}
        
    except Exception as e:
        logger.error(f"Error suggesting BFO category: {str(e)}")
        return {"error": str(e)}

def generate_class_description(class_name):
    """
    Generate a description for a class based on its name.
    
    Args:
        class_name (str): The name of the class
        
    Returns:
        dict: Dictionary with generated description
    """
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

        # Make the API call
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=200
        )
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response when generating description")
            return {"error": "The OpenAI API returned an empty response. Please try again later."}
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content when generating description")
            return {"error": "The OpenAI API returned empty content. Please try again later."}
            
        logger.info(f"Raw OpenAI description generation: {result_text}")
        
        try:
            result = json.loads(result_text)
            logger.info(f"Successfully parsed description. Keys: {list(result.keys())}")
            return {"description": result.get("description", "")}
        except Exception as e:
            logger.error(f"Error parsing OpenAI description generation: {str(e)}")
            return {"error": str(e)}
        
    except Exception as e:
        logger.error(f"Error generating class description: {str(e)}")
        return {"error": str(e)}

def generate_real_world_implications(ontology_name, domain_classes, fol_premises, num_implications=5):
    """
    Generate real-world implications from FOL premises using OpenAI.
    
    Args:
        ontology_name (str): The name of the ontology being analyzed
        domain_classes (list): List of main domain classes in the ontology
        fol_premises (list): List of FOL premises with type, fol, and description
        num_implications (int): Number of implications to generate (default: 5)
        
    Returns:
        list: A list of dictionaries containing generated implications
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        client = get_openai_client()
        
        # If no FOL premises provided or empty list, generate simple defaults based on classes
        if not fol_premises or len(fol_premises) == 0:
            logger.warning("No FOL premises provided, generating defaults from classes")
            fol_premises = []
            
            # Get class names from domain_classes
            class_names = []
            if domain_classes:
                for cls in domain_classes:
                    if isinstance(cls, dict) and 'name' in cls:
                        class_names.append(cls['name'])
                    elif isinstance(cls, str):
                        class_names.append(cls)
            
            # If no class names found, use some defaults from analysis
            if not class_names:
                # Try to use classes from the ontology analysis
                try:
                    from app import app
                    # Look for recent analysis in the database
                    with app.app_context():
                        from models import OntologyAnalysis
                        recent_analysis = OntologyAnalysis.query.order_by(OntologyAnalysis.id.desc()).first()
                        if recent_analysis and recent_analysis.class_list:
                            class_names = recent_analysis.class_list[:10]  # Use up to 10 classes
                except Exception as e:
                    logger.error(f"Error fetching classes from database: {str(e)}")
                    
                # If still no classes, use default placeholder
                if not class_names:
                    class_names = ["LegalFact", "LegalDomain", "LegalEntity", "Regulation"]
            
            # Generate basic premises for each class
            for cls in class_names[:10]:  # Limit to 10 classes
                fol_premises.append({
                    'type': 'class',
                    'fol': f"instance_of(x, {cls}, t)",
                    'description': f"Entities that are instances of {cls}"
                })
                
                # Add some relationship premises if we have multiple classes
                if len(class_names) > 1 and class_names.index(cls) < len(class_names) - 1:
                    next_cls = class_names[class_names.index(cls) + 1]
                    fol_premises.append({
                        'type': 'property',
                        'fol': f"related_to(x, y, t) & instance_of(x, {cls}, t) & instance_of(y, {next_cls}, t)",
                        'description': f"Relation between {cls} and {next_cls}"
                    })
        
        # Extract class names and descriptions for context
        class_info = []
        for cls in domain_classes:
            if isinstance(cls, dict) and 'name' in cls and 'description' in cls:
                class_info.append(f"{cls['name']}: {cls['description']}")
            elif isinstance(cls, str):
                class_info.append(cls)
        
        # If no class info, use class names from FOL premises
        if not class_info and fol_premises:
            for premise in fol_premises:
                if premise.get('type') == 'class' and 'instance_of' in premise.get('fol', ''):
                    fol_expr = premise.get('fol', '')
                    try:
                        class_name = fol_expr.split(',')[1].strip()
                        if class_name and class_name not in class_info:
                            class_info.append(class_name)
                    except:
                        pass
        
        # Extract FOL formulas and descriptions
        fol_info = []
        for premise in fol_premises:
            if isinstance(premise, dict) and 'fol' in premise and 'description' in premise:
                fol_info.append(f"Formula: {premise['fol']}\nExplanation: {premise['description']}")
        
        # If no domain name provided, use a placeholder
        if not ontology_name or ontology_name == "Unknown":
            ontology_name = "LegalFacts Ontology"
        
        # Ensure we have some class info
        if not class_info:
            class_info = ["UnknownClass"]
            
        # Ensure we have FOL info
        if not fol_info or (isinstance(fol_info, list) and len(fol_info) == 0):
            logger.warning("No FOL info for implications generation, using defaults")
            # These should have been generated in the earlier code
            fol_info = [
                "Formula: instance_of(x, LegalFact, t)\nExplanation: Entities that are instances of LegalFact",
                "Formula: instance_of(x, LegalEntity, t)\nExplanation: Entities that are instances of LegalEntity",
                "Formula: related_to(x, y, t)\nExplanation: Relation between entities"
            ]
        
        # Prepare the prompt
        system_prompt = """You are an expert in ontology analysis and first-order logic. 
Your task is to generate real-world implications and examples based on the given ontology and its First-Order Logic (FOL) premises.
Focus on practical, concrete scenarios that demonstrate how the logical rules in the ontology would manifest in the real world.
Provide specific examples that domain experts would find valuable in understanding the ontology's practical applications.
Each example should clearly connect to one or more FOL premises and explain which rules it demonstrates.
Format your response as a JSON array of objects with 'title', 'scenario', 'premises_used', and 'explanation' fields.

Important: If you received auto-generated FOL premises (which will be indicated by simple instance_of formulas), 
create implications that would be meaningful for the domain area mentioned in the ontology name.
"""

        user_prompt = f"""Ontology Name: {ontology_name}

Domain Classes:
{json.dumps(class_info, indent=2)}

FOL Premises:
{json.dumps(fol_info, indent=2)}

Please generate {num_implications} real-world implications or examples from these FOL premises. 
Each example should show how these logical structures would manifest in concrete situations.
Provide your response as a JSON array with objects containing:
- "title": A short descriptive title for the implication
- "scenario": A concrete real-world example demonstrating the logical rule in action (1-2 paragraphs)
- "premises_used": List of the specific premises being demonstrated (can be indices of the FOL premises list or the actual formulas)
- "explanation": Clear explanation of how the scenario demonstrates the logical rules (1 paragraph)

Ensure your examples are domain-appropriate, concrete, and clearly connected to the ontology's logical structure.
If the premises seem auto-generated (simple instance_of formulas), create meaningful implications that would be relevant
for a {ontology_name.replace("Ontology", "").strip()} domain.
"""

        # Make the API call
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        # Parse the response
        if response is None or response.choices is None or len(response.choices) == 0:
            logger.error("OpenAI API returned an empty response when generating implications")
            return [{"error": "The OpenAI API returned an empty response. Please try again later.", "title": "Error"}]
            
        result_text = response.choices[0].message.content
        if result_text is None or result_text.strip() == "":
            logger.error("OpenAI API returned empty content when generating implications")
            return [{"error": "The OpenAI API returned empty content. Please try again later.", "title": "Error"}]
            
        logger.info(f"Raw OpenAI response: {result_text}")
        
        # Handle different JSON formats that might be returned
        implications = []
        
        try:
            logger.info(f"Attempting to parse implications JSON: {result_text[:min(200, len(result_text))]}...")
            result = json.loads(result_text)
            logger.info(f"Successfully loaded implications JSON. Response structure: {type(result).__name__}")
            if isinstance(result, dict):
                logger.info(f"JSON keys for implications: {list(result.keys())}")
            
            # Case 1: Response is a list of implications
            if isinstance(result, list):
                implications = result
            # Case 2: Response has an 'implications' key
            elif result.get("implications") and isinstance(result.get("implications"), list):
                implications = result.get("implications")
            # Case 3: Response has an 'examples' key (like in our current response)
            elif result.get("examples") and isinstance(result.get("examples"), list):
                implications = result.get("examples")
            # Case 4: Response is a flat object with the expected fields
            elif "title" in result and "scenario" in result:
                implications = [result]  # Wrap single item in a list
            # Case 5: Response has numbered keys as strings (e.g., "1", "2", etc.)
            else:
                for key, value in result.items():
                    if isinstance(value, dict) and "title" in value:
                        implications.append(value)
                        
            logger.info(f"Parsed implications from response: {implications}")
        except Exception as e:
            logger.error(f"Error parsing OpenAI response: {str(e)}")
            implications = []
        
        if implications and isinstance(implications, list):
            logger.info(f"Successfully generated {len(implications)} real-world implications")
        else:
            logger.warning("No implications generated or implications not in list format")
        
        # If we still have no implications, create a default one for debugging
        if not implications:
            implications = [{
                "title": "Example Implication",
                "scenario": "This is an example implication generated as a fallback.",
                "premises_used": ["Example premise"],
                "explanation": "The OpenAI response didn't contain properly formatted implications."
            }]
            logger.warning("Using fallback implications because none were parsed from the response")
            
        return implications
        
    except Exception as e:
        logger.error(f"Error generating real-world implications: {str(e)}")
        return [{"error": str(e), "title": "Error generating implications"}]