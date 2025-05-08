/**
 * Ontology Development Sandbox
 * JavaScript for managing the interactive editing of ontologies
 */

// Current entity selections
let selectedClassId = null;
let selectedPropertyId = null;
let selectedIndividualId = null;

// Functions to switch between tabs
function showClassForm(show = true) {
    if (show) {
        document.getElementById('class-empty-state').style.display = 'none';
        document.getElementById('class-form').style.display = 'block';
    } else {
        document.getElementById('class-empty-state').style.display = 'block';
        document.getElementById('class-form').style.display = 'none';
    }
}

function showPropertyForm(show = true) {
    if (show) {
        document.getElementById('property-empty-state').style.display = 'none';
        document.getElementById('property-form').style.display = 'block';
    } else {
        document.getElementById('property-empty-state').style.display = 'block';
        document.getElementById('property-form').style.display = 'none';
    }
}

function showIndividualForm(show = true) {
    if (show) {
        document.getElementById('individual-empty-state').style.display = 'none';
        document.getElementById('individual-form').style.display = 'block';
    } else {
        document.getElementById('individual-empty-state').style.display = 'block';
        document.getElementById('individual-form').style.display = 'none';
    }
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
    // This is a placeholder for the individual-related JavaScript code
    // You would follow a similar pattern to the class and property functionality
}