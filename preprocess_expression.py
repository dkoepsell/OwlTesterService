"""
This module contains the preprocess_expression function to handle BFO-style multi-variable quantifiers
in First-Order Logic expressions. It converts expressions like "forall x,t (...)" to 
"forall x (forall t (...))" to make them compatible with NLTK's parser.
"""

import re

def preprocess_expression(expr_string):
    """
    Preprocess the input expression to handle BFO-style multi-variable quantifiers.
    
    Converts expressions like "forall x,t (...)" to "forall x (forall t (...))"
    to make them compatible with NLTK's parser.
    
    Args:
        expr_string (str): The original expression string
        
    Returns:
        str: The preprocessed expression
    """
    # Return original if no preprocessing needed
    if ',' not in expr_string:
        return expr_string
        
    # Pattern to match quantifiers with comma-separated variables
    pattern = r'(forall|exists)\s+([a-zA-Z0-9_]+)(?:,\s*([a-zA-Z0-9_,\s]+))\s*\('
    
    def replacement(match):
        quantifier = match.group(1)  # 'forall' or 'exists'
        first_var = match.group(2)   # First variable
        other_vars = match.group(3)  # Remaining variables (comma-separated)
        
        # Split remaining variables and strip whitespace
        var_list = [var.strip() for var in other_vars.split(',')]
        
        # Build nested quantifiers from inside out
        inner_expr = '('  # This will be closed by the original expression
        
        # Build the nested quantifier structure from the innermost outward
        for var in reversed(var_list):
            if var:  # Skip empty strings
                inner_expr = f"{quantifier} {var} {inner_expr}"
        
        # Add the outermost quantifier with the first variable
        result = f"{quantifier} {first_var} {inner_expr}"
        
        return result
    
    # Apply the regex replacement for all matches
    preprocessed = re.sub(pattern, replacement, expr_string)
    
    return preprocessed