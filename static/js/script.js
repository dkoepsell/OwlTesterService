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
    const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Handle form submission
    expressionForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const expression = expressionInput.value.trim();
        
        if (!expression) {
            showError('Please enter a FOL expression');
            return;
        }
        
        testExpression(expression);
    });
    
    // Clear button functionality
    clearBtn.addEventListener('click', function() {
        expressionInput.value = '';
        resultsContainer.classList.add('d-none');
        expressionInput.focus();
    });
    
    // Use example buttons
    useExampleBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const example = this.getAttribute('data-example');
            expressionInput.value = example;
            expressionInput.focus();
            // Optionally auto-submit the example
            // testExpression(example);
        });
    });
    
    // Copy buttons for BFO terms
    copyBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const term = this.getAttribute('data-term');
            
            // Get current cursor position
            const cursorPos = expressionInput.selectionStart;
            const currentValue = expressionInput.value;
            
            // Insert the term at cursor position
            expressionInput.value = 
                currentValue.substring(0, cursorPos) + 
                term + 
                currentValue.substring(cursorPos);
            
            // Set focus back to the input and place cursor after inserted term
            expressionInput.focus();
            expressionInput.setSelectionRange(cursorPos + term.length, cursorPos + term.length);
            
            // Show feedback (temporary visual indication)
            this.innerHTML = '<i class="fas fa-check"></i>';
            setTimeout(() => {
                this.innerHTML = '<i class="fas fa-copy"></i>';
            }, 1000);
        });
    });
    
    // Search functionality for BFO classes
    searchClassesInput.addEventListener('input', function() {
        filterList(bfoClassesList, '.bfo-class-item', this.value);
    });
    
    // Search functionality for BFO relations
    searchRelationsInput.addEventListener('input', function() {
        filterList(bfoRelationsList, '.bfo-relation-item', this.value);
    });
    
    // Filter a list based on search input
    function filterList(listElement, itemSelector, searchText) {
        const items = listElement.querySelectorAll(itemSelector);
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
        fetch('/api/test', {
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
        // Set expression text
        expressionText.textContent = data.expression;
        
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
