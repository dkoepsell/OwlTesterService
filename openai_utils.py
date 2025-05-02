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
    try:
        client = get_openai_client()
        
        # Extract class names and descriptions for context
        class_info = []
        for cls in domain_classes:
            if isinstance(cls, dict) and 'name' in cls and 'description' in cls:
                class_info.append(f"{cls['name']}: {cls['description']}")
            elif isinstance(cls, str):
                class_info.append(cls)
                
        # Extract FOL formulas and descriptions
        fol_info = []
        for premise in fol_premises:
            if isinstance(premise, dict) and 'fol' in premise and 'description' in premise:
                fol_info.append(f"Formula: {premise['fol']}\nExplanation: {premise['description']}")
        
        # Prepare the prompt
        system_prompt = """You are an expert in ontology analysis and first-order logic. 
Your task is to generate real-world implications and examples based on the given ontology and its First-Order Logic (FOL) premises.
Focus on practical, concrete scenarios that demonstrate how the logical rules in the ontology would manifest in the real world.
Provide specific examples that domain experts would find valuable in understanding the ontology's practical applications.
Each example should clearly connect to one or more FOL premises and explain which rules it demonstrates.
Format your response as a JSON array of objects with 'title', 'scenario', 'premises_used', and 'explanation' fields.
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
- "premises_used": List of the specific premises being demonstrated (can be indices of the FOL premises list)
- "explanation": Clear explanation of how the scenario demonstrates the logical rules (1 paragraph)

Ensure your examples are domain-appropriate, concrete, and clearly connected to the ontology's logical structure.
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
        result_text = response.choices[0].message.content
        logger.info(f"Raw OpenAI response: {result_text}")
        
        # Handle different JSON formats that might be returned
        implications = []
        
        try:
            result = json.loads(result_text)
            
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
        
        logger.info(f"Successfully generated {len(implications)} real-world implications")
        
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