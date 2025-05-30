document.addEventListener('DOMContentLoaded', function() {
    // DOM elements
    const expressionForm = document.getElementById('expression-form');
    const expressionInput = document.getElementById('expression-input');
    const clearBtn = document.getElementById('clear-btn');
    const resultsContainer = document.getElementById('results-container');
    const expressionText = document.getElementById('expression-text');
    const formatDetected = document.getElementById('format-detected');
    const formatBadge = document.getElementById('format-badge');
    const validityResult = document.getElementById('validity-result');
    const issuesContainer = document.getElementById('issues-container');
    const issuesList = document.getElementById('issues-list');
    const classesUsedList = document.getElementById('classes-used-list');
    const relationsUsedList = document.getElementById('relations-used-list');
    const nonBfoTermsList = document.getElementById('non-bfo-terms-list');
    const searchClassesInput = document.getElementById('search-classes');
    const searchRelationsInput = document.getElementById('search-relations');
    const bfoClassesList = document.getElementById('bfo-classes-list');
    const bfoRelationsList = document.getElementById('bfo-relations-list');
    const useExampleBtns = document.querySelectorAll('.use-example');
    const copyBtns = document.querySelectorAll('.copy-btn');

    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    if (typeof bootstrap !== 'undefined') {
        const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Handle form submission
    if (expressionForm) {
        expressionForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const expression = expressionInput.value.trim();
            
            if (!expression) {
                showError('Please enter a FOL expression');
                return;
            }
            
            testExpression(expression);
        });
        
        // Clear button functionality if it exists
        if (clearBtn) {
            clearBtn.addEventListener('click', function() {
                expressionInput.value = '';
                if (resultsContainer) {
                    resultsContainer.classList.add('d-none');
                }
                expressionInput.focus();
            });
        }
    }
    
    // Use example buttons
    if (useExampleBtns && useExampleBtns.length > 0 && expressionInput) {
        useExampleBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                const example = this.getAttribute('data-example');
                if (expressionInput && example) {
                    expressionInput.value = example;
                    expressionInput.focus();
                    // Optionally auto-submit the example
                    // testExpression(example);
                }
            });
        });
    }
    
    // Copy buttons for BFO terms
    if (copyBtns && copyBtns.length > 0 && expressionInput) {
        copyBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                const term = this.getAttribute('data-term');
                const buttonType = this.textContent.trim();
                
                if (expressionInput && term) {
                    // Get current cursor position
                    const cursorPos = expressionInput.selectionStart;
                    const currentValue = expressionInput.value;
                    let insertText = term;
                    
                    // Format based on button type
                    if (buttonType.includes('ID')) {
                        // For ID button, format with instance_of syntax
                        insertText = `instance_of(x, ${term}, t)`;
                    } else {
                        // For Label button, just use the term directly
                        insertText = term;
                    }
                    
                    // Insert the formatted text at cursor position
                    expressionInput.value = 
                        currentValue.substring(0, cursorPos) + 
                        insertText + 
                        currentValue.substring(cursorPos);
                    
                    // Set focus back to the input and place cursor after inserted term
                    expressionInput.focus();
                    expressionInput.setSelectionRange(cursorPos + insertText.length, cursorPos + insertText.length);
                    
                    // Show feedback (temporary visual indication)
                    const originalHTML = this.innerHTML;
                    this.innerHTML = '<i class="fas fa-check"></i>';
                    setTimeout(() => {
                        this.innerHTML = originalHTML;
                    }, 1000);
                }
            });
        });
    }
    
    // Search functionality for BFO classes
    if (searchClassesInput && bfoClassesList) {
        searchClassesInput.addEventListener('input', function() {
            filterList(bfoClassesList, '.bfo-class-item', this.value);
        });
    }
    
    // Search functionality for BFO relations
    if (searchRelationsInput && bfoRelationsList) {
        searchRelationsInput.addEventListener('input', function() {
            filterList(bfoRelationsList, '.bfo-relation-item', this.value);
        });
    }
    
    // Filter a list based on search input
    function filterList(listElement, itemSelector, searchText) {
        if (!listElement) return;
        
        const items = listElement.querySelectorAll(itemSelector);
        
        // If search text is empty, show all items
        if (!searchText || searchText.trim() === '') {
            items.forEach(item => {
                item.style.display = '';
            });
            return;
        }
        
        const searchLower = searchText.toLowerCase();
        
        items.forEach(item => {
            const text = item.textContent.trim().toLowerCase();
            if (text.includes(searchLower)) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    }
    
    // Function to test the expression via API
    function testExpression(expression) {
        // Show loading state
        validityResult.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="spinner-border text-primary me-2" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <span>Testing expression...</span>
            </div>
        `;
        resultsContainer.classList.remove('d-none');
        
        // Make API request
        fetch('/api/test-expression', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ expression: expression })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Server error: ' + response.statusText);
            }
            return response.json();
        })
        .then(data => {
            displayResults(data);
        })
        .catch(error => {
            showError('Error: ' + error.message);
        });
    }
    
    // Display test results
    function displayResults(data) {
        // Set expression text - use original expression if preprocessing was applied
        expressionText.textContent = data.original_expression || data.expression;
        
        // Create or update preprocessed expression display
        const preprocessedContainer = document.getElementById('preprocessed-container') || 
            document.createElement('div');
        preprocessedContainer.id = 'preprocessed-container';
        
        // If there was preprocessing applied, show it
        if (data.preprocessed && data.preprocessed_expression) {
            preprocessedContainer.innerHTML = `
                <div class="alert alert-info mt-2">
                    <div class="d-flex align-items-center mb-2">
                        <i class="fas fa-info-circle me-2"></i>
                        <strong>Preprocessed Expression:</strong>
                    </div>
                    <pre class="bg-dark text-light p-2 rounded">${data.preprocessed_expression}</pre>
                    <small class="text-muted">Multi-variable quantifiers were converted to nested quantifiers for processing.</small>
                </div>
            `;
            
            // Add after the expression text if not already there
            if (!document.getElementById('preprocessed-container')) {
                expressionText.parentNode.insertBefore(preprocessedContainer, expressionText.nextSibling);
            }
        } else if (preprocessedContainer.parentNode) {
            // Remove the preprocessed container if it exists but no preprocessing happened
            preprocessedContainer.parentNode.removeChild(preprocessedContainer);
        }
        
        // Display format detected if available
        if (data.format_detected) {
            formatDetected.classList.remove('d-none');
            
            // Set appropriate badge color and text based on format
            let badgeClass, badgeText;
            
            switch (data.format_detected) {
                case 'instance_of':
                    badgeClass = 'bg-success';
                    badgeText = 'BFO Standard Notation';
                    break;
                case 'traditional':
                    badgeClass = 'bg-warning text-dark';
                    badgeText = 'Traditional Notation';
                    break;
                default:
                    badgeClass = 'bg-secondary';
                    badgeText = 'Unknown Notation';
            }
            
            formatBadge.className = `badge rounded-pill ${badgeClass}`;
            formatBadge.textContent = badgeText;
        } else {
            formatDetected.classList.add('d-none');
        }
        
        // Show validity result
        if (data.valid) {
            validityResult.innerHTML = `
                <div class="alert alert-success">
                    <i class="fas fa-check-circle me-2"></i>
                    <strong>Valid Expression</strong>: The expression is syntactically correct and uses recognized BFO terms.
                </div>
            `;
        } else {
            validityResult.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-times-circle me-2"></i>
                    <strong>Invalid Expression</strong>: The expression has issues that need to be addressed.
                </div>
            `;
        }
        
        // Display issues if any
        if (data.issues && data.issues.length > 0) {
            issuesList.innerHTML = '';
            data.issues.forEach(issue => {
                issuesList.innerHTML += `
                    <li class="list-group-item list-group-item-danger">
                        <i class="fas fa-exclamation-circle me-2"></i>${issue}
                    </li>
                `;
            });
            issuesContainer.classList.remove('d-none');
        } else {
            issuesContainer.classList.add('d-none');
        }
        
        // Display BFO classes used
        displayTermsList(classesUsedList, data.bfo_classes_used, 'No BFO classes used');
        
        // Display BFO relations used
        displayTermsList(relationsUsedList, data.bfo_relations_used, 'No BFO relations used');
        
        // Display non-BFO terms
        displayTermsList(nonBfoTermsList, data.non_bfo_terms, 'No non-BFO terms found');
        
        // Smooth scroll to results if not in view
        if (!isElementInViewport(resultsContainer)) {
            resultsContainer.scrollIntoView({ behavior: 'smooth' });
        }
    }
    
    // Helper function to display terms in a list
    function displayTermsList(listElement, terms, emptyMessage) {
        listElement.innerHTML = '';
        
        if (terms && terms.length > 0) {
            terms.forEach(term => {
                listElement.innerHTML += `
                    <li>
                        <span class="badge bg-light text-dark me-1">${term}</span>
                    </li>
                `;
            });
        } else {
            listElement.innerHTML = `<li class="text-muted">${emptyMessage}</li>`;
        }
    }
    
    // Show error message
    function showError(message) {
        validityResult.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>${message}
            </div>
        `;
        resultsContainer.classList.remove('d-none');
    }
    
    // Check if element is in viewport
    function isElementInViewport(el) {
        const rect = el.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
    }
});
