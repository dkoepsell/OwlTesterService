/**
 * Ontology Development Sandbox
 * JavaScript for managing the interactive editing of ontologies
 */

// Current entity selections
let selectedClassId = null;
let selectedPropertyId = null;
let selectedIndividualId = null;

// Functions to show/hide forms
function showClassForm(show = true) {
    const emptyState = document.getElementById('class-empty-state');
    const form = document.getElementById('class-form');
    
    if (!emptyState || !form) return;
    
    if (show) {
        emptyState.style.display = 'none';
        form.style.display = 'block';
    } else {
        emptyState.style.display = 'block';
        form.style.display = 'none';
    }
}

function showPropertyForm(show = true) {
    const emptyState = document.getElementById('property-empty-state');
    const form = document.getElementById('property-form');
    
    if (!emptyState || !form) return;
    
    if (show) {
        emptyState.style.display = 'none';
        form.style.display = 'block';
    } else {
        emptyState.style.display = 'block';
        form.style.display = 'none';
    }
}

function showIndividualForm(show = true) {
    const emptyState = document.getElementById('individual-empty-state');
    const form = document.getElementById('individual-form');
    
    if (!emptyState || !form) return;
    
    if (show) {
        emptyState.style.display = 'none';
        form.style.display = 'block';
    } else {
        emptyState.style.display = 'block';
        form.style.display = 'none';
    }
}

// AI Assistant functions
function requestAISuggestions(domain, subject, callback, type = 'all', ontologyId = null) {
    // Make a request to our AI suggestions endpoint
    // type can be 'all', 'classes', or 'properties'
    let url = `/api/sandbox/ai/suggestions?domain=${encodeURIComponent(domain)}&subject=${encodeURIComponent(subject)}&type=${encodeURIComponent(type)}`;
    
    // Add ontologyId parameter if provided (needed for both properties and classes)
    if (ontologyId) {
        url += `&ontology_id=${encodeURIComponent(ontologyId)}`;
    }
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (callback && typeof callback === 'function') {
                callback(data, type);
            }
        })
        .catch(error => {
            console.error('Error getting AI suggestions:', error);
        });
}

function suggestBFOCategory(className, description, callback) {
    // Make a request to suggest appropriate BFO category
    fetch('/api/sandbox/ai/bfo-category', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            class_name: className,
            description: description
        })
    })
    .then(response => response.json())
    .then(data => {
        if (callback && typeof callback === 'function') {
            callback(data);
        }
    })
    .catch(error => {
        console.error('Error getting BFO category suggestion:', error);
    });
}

function generateDescription(className, callback) {
    // Generate a description for a class
    fetch('/api/sandbox/ai/description', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            class_name: className
        })
    })
    .then(response => response.json())
    .then(data => {
        if (callback && typeof callback === 'function') {
            callback(data);
        }
    })
    .catch(error => {
        console.error('Error generating description:', error);
    });
}

// Initialize the sandbox when the document is ready
document.addEventListener('DOMContentLoaded', function() {
    // Get ontology ID from the page
    const ontologyIdElement = document.getElementById('ontology-id');
    if (!ontologyIdElement) return;
    
    const ontologyId = ontologyIdElement.value;
    
    // Set up class-related event handlers
    initializeClassFunctionality(ontologyId);
    
    // Set up property-related event handlers
    initializePropertyFunctionality(ontologyId);
    
    // Set up individual-related event handlers
    initializeIndividualFunctionality(ontologyId);
    
    // Initialize forms to hidden state
    showClassForm(false);
    showPropertyForm(false);
    showIndividualForm(false);
    
    // Set up AI assistant buttons if they exist
    setupAIAssistantButtons(ontologyId);
});

function initializeClassFunctionality(ontologyId) {
    // New class button
    const newClassBtn = document.getElementById('new-class-btn');
    if (newClassBtn) {
        newClassBtn.addEventListener('click', function() {
            // Clear form
            document.getElementById('class-id').value = '';
            document.getElementById('class-name').value = '';
            document.getElementById('class-description').value = '';
            document.getElementById('class-parent').value = '';
            document.getElementById('class-bfo-category').value = '';
            
            // Update form title
            document.getElementById('class-form-title').textContent = 'New Class';
            
            // Show form
            showClassForm(true);
            
            // Clear selection
            const selected = document.querySelector('#class-list .entity-item.active');
            if (selected) {
                selected.classList.remove('active');
            }
            selectedClassId = null;
        });
    }
    
    // Clear class button
    const clearClassBtn = document.getElementById('clear-class-btn');
    if (clearClassBtn) {
        clearClassBtn.addEventListener('click', function() {
            document.getElementById('class-name').value = '';
            document.getElementById('class-description').value = '';
            document.getElementById('class-parent').value = '';
            document.getElementById('class-bfo-category').value = '';
        });
    }
    
    // Add event listeners to class items
    document.querySelectorAll('#class-list .entity-item').forEach(item => {
        item.addEventListener('click', function(e) {
            // Ignore if the delete button was clicked
            if (e.target.closest('.delete-class-btn')) {
                return;
            }
            
            // Remove active class from all items
            document.querySelectorAll('#class-list .entity-item').forEach(i => {
                i.classList.remove('active');
            });
            
            // Add active class to clicked item
            this.classList.add('active');
            
            // Get class ID
            const classId = this.dataset.id;
            selectedClassId = classId;
            
            // Update form title
            document.getElementById('class-form-title').textContent = 'Edit Class';
            
            // Fetch class details
            fetch(`/api/sandbox/${ontologyId}/classes/${classId}`)
                .then(response => response.json())
                .then(data => {
                    // Populate form fields
                    document.getElementById('class-id').value = data.id;
                    document.getElementById('class-name').value = data.name;
                    document.getElementById('class-description').value = data.description || '';
                    document.getElementById('class-parent').value = data.parent_id || '';
                    document.getElementById('class-bfo-category').value = data.bfo_category || '';
                    
                    // Show form
                    showClassForm(true);
                })
                .catch(error => {
                    console.error('Error fetching class details:', error);
                    alert('Error fetching class details');
                });
        });
    });
    
    // Add event listeners to delete class buttons
    document.querySelectorAll('.delete-class-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const classId = this.dataset.id;
            if (confirm('Are you sure you want to delete this class? This will also delete any subclasses or associated entities.')) {
                // Delete class
                fetch(`/api/sandbox/${ontologyId}/classes/${classId}`, {
                    method: 'DELETE'
                })
                .then(response => {
                    if (response.ok) {
                        // Refresh the page
                        window.location.reload();
                    } else {
                        return response.json().then(data => {
                            throw new Error(data.error || 'Failed to delete class');
                        });
                    }
                })
                .catch(error => {
                    console.error('Error deleting class:', error);
                    alert('Error: ' + error.message);
                });
            }
        });
    });
    
    // Handle class form submission
    const classForm = document.getElementById('class-form');
    if (classForm) {
        classForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const classId = document.getElementById('class-id').value;
            const data = {
                name: document.getElementById('class-name').value,
                description: document.getElementById('class-description').value,
                parent_id: document.getElementById('class-parent').value || null,
                bfo_category: document.getElementById('class-bfo-category').value || null
            };
            
            let url, method;
            if (classId) {
                // Update existing class
                url = `/api/sandbox/${ontologyId}/classes/${classId}`;
                method = 'PUT';
            } else {
                // Create new class
                url = `/api/sandbox/${ontologyId}/classes`;
                method = 'POST';
            }
            
            fetch(url, {
                method: method,
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            })
            .then(response => {
                if (response.ok) {
                    // Refresh the page
                    window.location.reload();
                } else {
                    return response.json().then(data => {
                        throw new Error(data.error || 'Failed to save class');
                    });
                }
            })
            .catch(error => {
                console.error('Error saving class:', error);
                alert('Error: ' + error.message);
            });
        });
    }
}

function initializePropertyFunctionality(ontologyId) {
    // New property button
    const newPropertyBtn = document.getElementById('new-property-btn');
    if (newPropertyBtn) {
        newPropertyBtn.addEventListener('click', function() {
            // Clear form
            document.getElementById('property-id').value = '';
            document.getElementById('property-name').value = '';
            document.getElementById('property-description').value = '';
            document.getElementById('property-type').value = 'object';
            document.getElementById('property-domain').value = '';
            document.getElementById('property-range').value = '';
            
            // Update form title
            document.getElementById('property-form-title').textContent = 'New Property';
            
            // Show form
            showPropertyForm(true);
            
            // Clear selection
            const selected = document.querySelector('#property-list .entity-item.active');
            if (selected) {
                selected.classList.remove('active');
            }
            selectedPropertyId = null;
        });
    }
    
    // Clear property button
    const clearPropertyBtn = document.getElementById('clear-property-btn');
    if (clearPropertyBtn) {
        clearPropertyBtn.addEventListener('click', function() {
            document.getElementById('property-name').value = '';
            document.getElementById('property-description').value = '';
            document.getElementById('property-type').value = 'object';
            document.getElementById('property-domain').value = '';
            document.getElementById('property-range').value = '';
        });
    }
    
    // Add event listeners to property items
    document.querySelectorAll('#property-list .entity-item').forEach(item => {
        item.addEventListener('click', function(e) {
            // Ignore if the delete button was clicked
            if (e.target.closest('.delete-property-btn')) {
                return;
            }
            
            // Remove active class from all items
            document.querySelectorAll('#property-list .entity-item').forEach(i => {
                i.classList.remove('active');
            });
            
            // Add active class to clicked item
            this.classList.add('active');
            
            // Get property ID
            const propertyId = this.dataset.id;
            selectedPropertyId = propertyId;
            
            // Update form title
            document.getElementById('property-form-title').textContent = 'Edit Property';
            
            // Fetch property details - you'd need to implement this API
            fetch(`/api/sandbox/${ontologyId}/properties/${propertyId}`)
                .then(response => response.json())
                .then(data => {
                    // Populate form fields
                    document.getElementById('property-id').value = data.id;
                    document.getElementById('property-name').value = data.name;
                    document.getElementById('property-description').value = data.description || '';
                    document.getElementById('property-type').value = data.property_type;
                    document.getElementById('property-domain').value = data.domain_class_id || '';
                    document.getElementById('property-range').value = data.range_class_id || '';
                    
                    // Show form
                    showPropertyForm(true);
                })
                .catch(error => {
                    console.error('Error fetching property details:', error);
                    alert('Error fetching property details');
                });
        });
    });
    
    // Add event listeners to delete property buttons
    document.querySelectorAll('.delete-property-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const propertyId = this.dataset.id;
            if (confirm('Are you sure you want to delete this property?')) {
                // Delete property - you'd need to implement this API
                fetch(`/api/sandbox/${ontologyId}/properties/${propertyId}`, {
                    method: 'DELETE'
                })
                .then(response => {
                    if (response.ok) {
                        // Refresh the page
                        window.location.reload();
                    } else {
                        return response.json().then(data => {
                            throw new Error(data.error || 'Failed to delete property');
                        });
                    }
                })
                .catch(error => {
                    console.error('Error deleting property:', error);
                    alert('Error: ' + error.message);
                });
            }
        });
    });
    
    // Handle property form submission
    const propertyForm = document.getElementById('property-form');
    if (propertyForm) {
        propertyForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const propertyId = document.getElementById('property-id').value;
            const data = {
                name: document.getElementById('property-name').value,
                description: document.getElementById('property-description').value,
                property_type: document.getElementById('property-type').value,
                domain_class_id: document.getElementById('property-domain').value || null,
                range_class_id: document.getElementById('property-range').value || null
            };
            
            let url, method;
            if (propertyId) {
                // Update existing property
                url = `/api/sandbox/${ontologyId}/properties/${propertyId}`;
                method = 'PUT';
            } else {
                // Create new property
                url = `/api/sandbox/${ontologyId}/properties`;
                method = 'POST';
            }
            
            fetch(url, {
                method: method,
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            })
            .then(response => {
                if (response.ok) {
                    // Refresh the page
                    window.location.reload();
                } else {
                    return response.json().then(data => {
                        throw new Error(data.error || 'Failed to save property');
                    });
                }
            })
            .catch(error => {
                console.error('Error saving property:', error);
                alert('Error: ' + error.message);
            });
        });
    }
}

function initializeIndividualFunctionality(ontologyId) {
    // Similar structure to the class and property functionality
    // Implementation for individual-related event handlers
    // This would follow a similar pattern to the class and property functionality
}

// Set up the AI assistant buttons
function setupAIAssistantButtons(ontologyId) {
    // Add BFO category suggestion button
    const suggestBFOBtn = document.getElementById('suggest-bfo-btn');
    if (suggestBFOBtn) {
        suggestBFOBtn.addEventListener('click', function() {
            const className = document.getElementById('class-name').value;
            const description = document.getElementById('class-description').value;
            
            if (!className) {
                alert('Please enter a class name first');
                return;
            }
            
            // Show loading state
            suggestBFOBtn.disabled = true;
            suggestBFOBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Thinking...';
            
            // Request BFO category suggestion
            suggestBFOCategory(className, description, function(data) {
                // Reset button state
                suggestBFOBtn.disabled = false;
                suggestBFOBtn.innerHTML = '<i class="fas fa-magic"></i> Suggest BFO Category';
                
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                
                // Set the suggested BFO category
                if (data.bfo_category) {
                    document.getElementById('class-bfo-category').value = data.bfo_category;
                    
                    // Show explanation if provided
                    if (data.explanation) {
                        alert('AI Suggestion: ' + data.explanation);
                    }
                } else {
                    alert('No appropriate BFO category found');
                }
            });
        });
    }
    
    // Add description generation button
    const generateDescBtn = document.getElementById('generate-description-btn');
    if (generateDescBtn) {
        generateDescBtn.addEventListener('click', function() {
            const className = document.getElementById('class-name').value;
            
            if (!className) {
                alert('Please enter a class name first');
                return;
            }
            
            // Show loading state
            generateDescBtn.disabled = true;
            generateDescBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
            
            // Generate description
            generateDescription(className, function(data) {
                // Reset button state
                generateDescBtn.disabled = false;
                generateDescBtn.innerHTML = '<i class="fas fa-pen"></i> Generate Description';
                
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                
                // Set the generated description
                if (data.description) {
                    document.getElementById('class-description').value = data.description;
                } else {
                    alert('Could not generate a description');
                }
            });
        });
    }
    
    // Add classes suggestion button in the classes tab
    const suggestClassesBtn = document.getElementById('suggestClassesBtn');
    if (suggestClassesBtn) {
        suggestClassesBtn.addEventListener('click', function() {
            // Get domain and subject from the settings tab
            const domainInput = document.getElementById('ontologyDomain');
            const subjectInput = document.getElementById('ontologySubject');
            
            if (!domainInput || !subjectInput) {
                alert('Domain and subject information not found');
                return;
            }
            
            const domain = domainInput.value.trim();
            const subject = subjectInput.value.trim();
            
            if (!domain || !subject) {
                alert('Domain and subject must be specified');
                return;
            }
            
            // Show loading state
            suggestClassesBtn.disabled = true;
            suggestClassesBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Loading...';
            
            // Request class suggestions
            fetch('/api/sandbox/ai/suggestions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    domain: domain,
                    subject: subject
                })
            })
            .then(response => response.json())
            .then(data => {
                // Reset button state
                suggestClassesBtn.disabled = false;
                suggestClassesBtn.innerHTML = '<i class="fas fa-lightbulb me-1"></i> Suggest Classes';
                
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                
                // Display suggested classes
                if (Array.isArray(data) && data.length > 0) {
                    showSuggestionsList(data, ontologyId, 'classes');
                } else if (data.suggestions && data.suggestions.length > 0) {
                    showSuggestionsList(data.suggestions, ontologyId, 'classes');
                } else {
                    alert('No class suggestions generated');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                suggestClassesBtn.disabled = false;
                suggestClassesBtn.innerHTML = '<i class="fas fa-lightbulb me-1"></i> Suggest Classes';
                alert('Error getting AI suggestions: ' + error.message);
            });
        });
    }
    
    // Add properties suggestion button
    const suggestPropertiesBtn = document.getElementById('suggestPropertiesBtn');
    if (suggestPropertiesBtn) {
        suggestPropertiesBtn.addEventListener('click', function() {
            // Get domain and subject from the settings tab
            const domainInput = document.getElementById('ontologyDomain');
            const subjectInput = document.getElementById('ontologySubject');
            
            if (!domainInput || !subjectInput) {
                alert('Domain and subject information not found');
                return;
            }
            
            const domain = domainInput.value.trim();
            const subject = subjectInput.value.trim();
            
            if (!domain || !subject) {
                alert('Domain and subject must be specified');
                return;
            }
            
            // Show loading state
            suggestPropertiesBtn.disabled = true;
            suggestPropertiesBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Loading...';
            
            // Request property suggestions
            fetch('/api/sandbox/ai/suggestions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    domain: domain,
                    subject: subject
                })
            })
            .then(response => response.json())
            .then(data => {
                // Reset button state
                suggestPropertiesBtn.disabled = false;
                suggestPropertiesBtn.innerHTML = '<i class="fas fa-lightbulb me-1"></i> Suggest Properties';
                
                if (data.error) {
                    alert('Error: ' + data.error);
                    return;
                }
                
                // Display suggested properties
                if (Array.isArray(data) && data.length > 0) {
                    showSuggestionsList(data, ontologyId, 'properties');
                } else if (data.suggestions && data.suggestions.length > 0) {
                    showSuggestionsList(data.suggestions, ontologyId, 'properties');
                    
                    // Log information about existing classes
                    if (data.existing_classes && data.existing_classes.length > 0) {
                        console.log(`Found ${data.existing_classes.length} existing classes for linking properties`);
                    }
                } else {
                    alert('No property suggestions generated');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                suggestPropertiesBtn.disabled = false;
                suggestPropertiesBtn.innerHTML = '<i class="fas fa-lightbulb me-1"></i> Suggest Properties';
                alert('Error getting AI suggestions: ' + error.message);
            });
        });
    }
}

// Show a modal with entity suggestions
function showSuggestionsList(suggestions, ontologyId, type = 'all') {
    // Create or get the suggestions modal
    let modal = document.getElementById('suggestions-modal');
    
    // Set title and descriptive text based on suggestion type
    let modalTitle = "Suggested Classes";
    let modalDescription = "Here are some suggested classes for your ontology domain:";
    
    if (type === 'properties') {
        modalTitle = "Suggested Properties";
        modalDescription = "Here are some suggested properties for your ontology domain:";
    } else if (type === 'all') {
        modalTitle = "Suggested Ontology Components";
        modalDescription = "Here are some suggested classes and properties for your ontology domain:";
    }
    
    // If the modal doesn't exist, create it
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'suggestions-modal';
        modal.className = 'modal fade';
        modal.setAttribute('tabindex', '-1');
        modal.setAttribute('aria-hidden', 'true');
        
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content bg-dark">
                    <div class="modal-header">
                        <h5 class="modal-title">${modalTitle}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <p id="suggestions-description">${modalDescription}</p>
                        <div id="suggestions-list" class="list-group mb-3">
                            <!-- Suggestions will be inserted here -->
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        <button type="button" class="btn btn-primary" id="add-selected-btn">Add Selected</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    } else {
        // Update the title and description for the existing modal
        modal.querySelector('.modal-title').textContent = modalTitle;
        modal.querySelector('#suggestions-description').textContent = modalDescription;
    }
    
    // Get the suggestions list container
    const suggestionsList = document.getElementById('suggestions-list');
    suggestionsList.innerHTML = ''; // Clear existing suggestions
    
    // Add each suggestion to the list
    suggestions.forEach((suggestion, index) => {
        const item = document.createElement('div');
        item.className = 'list-group-item bg-dark d-flex align-items-start';
        
        // Different formats for properties vs classes
        if (type === 'properties') {
            // Property format
            item.innerHTML = `
                <div class="form-check me-2">
                    <input class="form-check-input" type="checkbox" value="${index}" id="suggestion-${index}">
                </div>
                <div class="w-100">
                    <h6 class="mb-1">${suggestion.name}</h6>
                    <p class="mb-1 small">${suggestion.description || 'No description provided'}</p>
                    <div class="d-flex justify-content-between">
                        <span class="badge bg-secondary">${suggestion.type || 'object'} property</span>
                        ${suggestion.class_name ? `<span class="badge bg-info">Class: ${suggestion.class_name}</span>` : ''}
                    </div>
                </div>
            `;
        } else {
            // Class format
            item.innerHTML = `
                <div class="form-check me-2">
                    <input class="form-check-input" type="checkbox" value="${index}" id="suggestion-${index}">
                </div>
                <div class="w-100">
                    <h6 class="mb-1">${suggestion.name}</h6>
                    <p class="mb-1 small">${suggestion.description || 'No description provided'}</p>
                    ${suggestion.bfo_category ? `<span class="badge bg-info">BFO: ${suggestion.bfo_category}</span>` : ''}
                </div>
            `;
        }
        
        suggestionsList.appendChild(item);
    });
    
    // Set up the "Add Selected" button
    const addSelectedBtn = document.getElementById('add-selected-btn');
    addSelectedBtn.onclick = function() {
        const selected = [];
        
        // Get all selected suggestions
        suggestionsList.querySelectorAll('input[type="checkbox"]:checked').forEach(checkbox => {
            const index = parseInt(checkbox.value);
            selected.push(suggestions[index]);
        });
        
        if (selected.length === 0) {
            alert('Please select at least one suggestion');
            return;
        }
        
        // Add all selected suggestions based on type
        let added = 0;
        let total = selected.length;
        
        if (type === 'properties') {
            // Handle adding properties
            function addNextProperty(i) {
                if (i >= total) {
                    // All properties added, close modal and refresh page
                    bootstrap.Modal.getInstance(modal).hide();
                    alert(`Added ${added} out of ${total} properties.`);
                    window.location.reload();
                    return;
                }
                
                const suggestion = selected[i];
                
                // Create the property
                fetch(`/api/sandbox/${ontologyId}/properties`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        name: suggestion.name,
                        description: suggestion.description || '',
                        property_type: suggestion.type || 'object',
                        // Optional fields - we might not have these for AI suggestions
                        domain_class_id: suggestion.domain_class_id || null,
                        range_class_id: suggestion.range_class_id || null
                    })
                })
                .then(response => {
                    if (response.ok) {
                        added++;
                    }
                    // Continue with the next property regardless of success
                    addNextProperty(i + 1);
                })
                .catch(error => {
                    console.error('Error adding property:', error);
                    // Continue with the next property despite the error
                    addNextProperty(i + 1);
                });
            }
            
            // Start adding properties
            addNextProperty(0);
            
        } else {
            // Handle adding classes (original code)
            function addNextClass(i) {
                if (i >= total) {
                    // All classes added, close modal and refresh page
                    bootstrap.Modal.getInstance(modal).hide();
                    alert(`Added ${added} out of ${total} classes.`);
                    window.location.reload();
                    return;
                }
                
                const suggestion = selected[i];
                
                // Create the class
                fetch(`/api/sandbox/${ontologyId}/classes`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        name: suggestion.name,
                        description: suggestion.description || '',
                        bfo_category: suggestion.bfo_category || null
                    })
                })
                .then(response => {
                    if (response.ok) {
                        added++;
                    }
                    // Continue with the next class regardless of success
                    addNextClass(i + 1);
                })
                .catch(error => {
                    console.error('Error adding class:', error);
                    // Continue with the next class despite the error
                    addNextClass(i + 1);
                });
            }
            
            // Start adding classes
            addNextClass(0);
        }
    };
    
    // Show the modal
    const modalInstance = new bootstrap.Modal(modal);
    modalInstance.show();
}