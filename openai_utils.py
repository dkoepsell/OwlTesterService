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

# Anthropic model for the Bring-Your-Own-Key Claude path (implication generation).
ANTHROPIC_MODEL = "claude-opus-4-8"

# Structured-output schema so Claude returns exactly the shape the parser expects.
_IMPLICATIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "implications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "scenario": {"type": "string"},
                    "premises_used": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                },
                "required": ["title", "scenario", "premises_used", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["implications"],
    "additionalProperties": False,
}


def _generate_implications_anthropic(system_prompt, user_prompt, api_key):
    """Generate implications with Claude (BYO Anthropic key); return raw JSON text.

    Prefers structured outputs so the response is a single JSON object matching
    _IMPLICATIONS_SCHEMA, which the shared parser then handles exactly like the
    OpenAI path. Falls back to a JSON-only prompt instruction if the installed
    SDK predates output_config, stripping any stray markdown code fences.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    base = dict(
        model=ANTHROPIC_MODEL,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    try:
        message = client.messages.create(
            output_config={"format": {"type": "json_schema",
                                      "schema": _IMPLICATIONS_SCHEMA}},
            **base,
        )
    except Exception as struct_err:  # noqa: BLE001 - older SDK / unsupported field
        logger.info("Anthropic structured outputs unavailable (%s); "
                    "falling back to JSON-only prompt", struct_err)
        base["system"] = system_prompt + (
            "\n\nReturn ONLY a single JSON object of the form "
            '{"implications": [...]} with no prose and no markdown code fences.')
        message = client.messages.create(**base)

    if getattr(message, "stop_reason", None) == "refusal":
        raise ValueError("Claude declined to generate implications for this input.")

    text = "".join(
        getattr(b, "text", "") for b in message.content
        if getattr(b, "type", None) == "text"
    ).strip()
    # Strip a ```json ... ``` fence if the fallback path produced one.
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    return text


def get_openai_client(api_key=None):
    """
    Create and return an OpenAI client.

    The key is resolved by api_key_utils: an explicit argument, then a
    user-supplied key in the Flask session (Bring Your Own Key), then the
    server's OPENAI_API_KEY environment variable.

    Returns:
        OpenAI: Configured OpenAI client
    """
    from api_key_utils import resolve_openai_key
    api_key = resolve_openai_key(api_key)
    if not api_key:
        logger.error("No OpenAI API key available (session or environment)")
        raise ValueError(
            "No OpenAI API key available. Add your own key in the AI settings, "
            "or set the OPENAI_API_KEY environment variable on the server."
        )

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
_IMPLICATIONS_SYSTEM_PROMPT = """You are an expert in formal ontology, description logic and first-order logic, working for the authors of one specific ontology.
Your job is to show them what THEIR axioms commit them to in the real world: consequences they may not have noticed, including surprising, restrictive or counter-intuitive ones.

Rules:
- Every implication must follow from specific items in the material you are given. Cite those items by ID (A# asserted axiom, I# inferred axiom, D# definition) in "premises_used". Never cite anything else.
- Prefer consequences that combine two or more axioms: subclass chains, domain/range constraints forcing an individual's type, disjointness ruling out a classification, restrictions (some/only/min/max) requiring or forbidding a relation, equivalences that make classification automatic, inferred subsumptions.
- Use the ontology's own class, property and individual names, and its own definitions. Build each scenario around concrete named instances of those classes.
- In "explanation", walk through the derivation step by step, citing the IDs as you go, and say what the ontology would force or forbid in that scenario.
- Do NOT restate a single axiom as a scenario ("an X is a Y"), do NOT make claims that would hold for any ontology in this field, and do NOT draw on domain knowledge that the axioms do not support. If the axioms say less than common sense would, that gap is itself a worthwhile implication: point it out.
- If an axiom combination produces a consequence a domain expert would likely reject, say so plainly: that is the most valuable kind of implication."""


def generate_real_world_implications(context, num_implications=5):
    """
    Generate real-world implications grounded in one ontology's own axioms.

    Args:
        context (dict): From implication_context.build_context -- the
            ontology's terms, label-rendered asserted/inferred axioms and
            definitions, each with a citable ID.
        num_implications (int): Number of implications to generate (default: 5)

    Returns:
        list: A list of implication dicts, or [{"error": ..., "title": ...}]
    """
    from implication_context import render_context, resolve_citations

    try:
        # Resolve the AI provider (OpenAI or Anthropic) from the BYO key / env.
        from api_key_utils import resolve_ai
        provider, api_key = resolve_ai()
        if not api_key:
            raise ValueError(
                "No AI API key available. Add your own OpenAI or Anthropic key in "
                "the AI settings, or set OPENAI_API_KEY or ANTHROPIC_API_KEY on the "
                "server."
            )
        if not (context.get('axioms') or context.get('inferred') or context.get('definitions')):
            raise ValueError(
                "This ontology has no axioms or definitions about its own terms to "
                "draw implications from (only declarations, or only BFO axioms).")

        user_prompt = f"""{render_context(context)}

Generate {num_implications} implications of this ontology's axioms, as a JSON object {{"implications": [...]}} where each item has:
- "title": a short, specific title naming the ontology terms involved
- "scenario": a concrete situation with named instances, showing what the axioms force or forbid (1-2 paragraphs)
- "premises_used": the IDs (A#, I#, D#) of the items the implication rests on
- "explanation": the step-by-step derivation from those items (1 paragraph)

Each implication must depend on this ontology specifically: if swapping in a different ontology of the same field would leave it true, replace it."""

        # Make the API call (provider-specific), then parse the JSON uniformly.
        if provider == "anthropic":
            result_text = _generate_implications_anthropic(
                _IMPLICATIONS_SYSTEM_PROMPT, user_prompt, api_key)
        else:
            response = get_openai_client(api_key).chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _IMPLICATIONS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.4
            )
            if response is None or not response.choices:
                logger.error("OpenAI API returned an empty response when generating implications")
                return [{"error": "The OpenAI API returned an empty response. Please try again later.", "title": "Error"}]
            result_text = response.choices[0].message.content

        if not result_text or not result_text.strip():
            logger.error("%s returned empty content when generating implications", provider)
            return [{"error": "The AI provider returned empty content. Please try again later.", "title": "Error"}]

        logger.info(f"Raw {provider} implications response: {result_text[:500]}")
        try:
            result = json.loads(result_text)
        except ValueError as e:
            logger.error(f"Error parsing implications response: {e}")
            return [{"error": "The AI provider returned malformed JSON. Please try again.", "title": "Error"}]

        if isinstance(result, list):
            implications = result
        elif isinstance(result.get("implications"), list):
            implications = result["implications"]
        elif isinstance(result.get("examples"), list):
            implications = result["examples"]
        elif "title" in result and "scenario" in result:
            implications = [result]
        else:
            implications = [v for v in result.values() if isinstance(v, dict) and "title" in v]

        implications = [i for i in implications if isinstance(i, dict) and i.get("title")]
        if not implications:
            logger.warning("No implications parsed from the %s response", provider)
            return [{"error": "The AI provider's response contained no implications. Please try again.", "title": "Error"}]

        implications = resolve_citations(implications, context)
        logger.info(f"Generated {len(implications)} grounded implications")
        return implications

    except Exception as e:
        logger.error(f"Error generating real-world implications: {str(e)}")
        return [{"error": str(e), "title": "Error generating implications"}]
