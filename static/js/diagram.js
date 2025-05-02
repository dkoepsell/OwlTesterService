// Simple utility functions for the diagram page
function copyToClipboard(text) {
    // Create a temporary textarea element
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'absolute';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    
    // Select and copy the text
    textarea.select();
    document.execCommand('copy');
    
    // Clean up
    document.body.removeChild(textarea);
    
    // Display a success message
    alert('PlantUML code copied to clipboard!');
}

function regenerateDiagram() {
    // Get form values
    const includeIndividuals = document.getElementById('include-individuals').checked;
    const includeDataProps = document.getElementById('include-data-properties').checked;
    const includeAnnotationProps = document.getElementById('include-annotation-properties').checked;
    const maxClasses = document.getElementById('max-classes').value;
    
    // Build query string
    const queryParams = new URLSearchParams();
    queryParams.append('individuals', includeIndividuals ? 'true' : 'false');
    queryParams.append('data_properties', includeDataProps ? 'true' : 'false');
    queryParams.append('annotation_properties', includeAnnotationProps ? 'true' : 'false');
    queryParams.append('max_classes', maxClasses);
    
    // Get the current URL
    const currentUrl = window.location.href.split('?')[0];
    
    // Navigate to the URL with parameters
    window.location.href = currentUrl + '?' + queryParams.toString();
}