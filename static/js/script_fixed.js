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
    if (typeof bootstrap !== 'undefined') {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.forEach(function (tooltipTriggerEl) {
            new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Handle form submission
    if (expressionForm) {
        expressionForm.addEventListener('submit', function(e) {
            e.preventDefault();
            if (expressionInput) {
                const expression = expressionInput.value.trim();
                
                if (!expression) {
                    showError('Please enter a FOL expression');
                    return;
                }
                
                testExpression(expression);
            }
        });
    }
    
    // Clear button functionality
    if (clearBtn && expressionInput) {
        clearBtn.addEventListener('click', function() {
            expressionInput.value = '';
            if (resultsContainer) {
                resultsContainer.classList.add('d-none');
            }
            expressionInput.focus();
        });
    }
    
    // Use example buttons
    if (useExampleBtns) {
        useExampleBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                if (expressionInput) {
                    const example = this.getAttribute('data-example');
                    if (example) {
                        expressionInput.value = example;
                        expressionInput.focus();
                        // Optionally auto-submit the example
                        if (expressionForm) {
                            expressionForm.dispatchEvent(new Event('submit'));
                        }
                    }
                }
            });
        });
    }
    
    // Copy buttons for BFO terms
    if (copyBtns) {
        copyBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                if (expressionInput) {
                    const term = this.getAttribute('data-term');
                    if (term) {
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
                        const originalHtml = this.innerHTML;
                        this.innerHTML = '<i class="fas fa-check"></i>';
                        setTimeout(() => {
                            this.innerHTML = originalHtml;
                        }, 1000);
                    }
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
    
    // Function to filter lists
    function filterList(list, itemSelector, searchTerm) {
        if (!list) return;
        
        const items = list.querySelectorAll(itemSelector);
        const searchLower = searchTerm.toLowerCase();
        
        items.forEach(item => {
            const text = item.textContent.toLowerCase();
            if (text.includes(searchLower)) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    }

    // Function to test the expression
    function testExpression(expression) {
        if (!resultsContainer || !expressionText || !validityResult) return;
        
        // Show loading spinner
        resultsContainer.classList.remove('d-none');
        expressionText.textContent = expression;
        validityResult.innerHTML = '<div class="spinner-border spinner-border-sm text-primary" role="status"><span class="visually-hidden">Loading...</span></div> Validating...';
        
        if (issuesContainer) {
            issuesContainer.classList.add('d-none');
        }
        
        // Empty the lists
        if (classesUsedList) classesUsedList.innerHTML = '';
        if (relationsUsedList) relationsUsedList.innerHTML = '';
        if (nonBfoTermsList) nonBfoTermsList.innerHTML = '';
        
        // Send to API
        fetch('/api/test-expression', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
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
            // Update validity result
            if (data.is_valid) {
                validityResult.innerHTML = '<span class="text-success"><i class="fas fa-check-circle me-1"></i>Valid</span>';
            } else {
                validityResult.innerHTML = '<span class="text-danger"><i class="fas fa-times-circle me-1"></i>Invalid</span>';
                
                // Show issues if any
                if (issuesContainer && issuesList && data.issues && data.issues.length > 0) {
                    issuesContainer.classList.remove('d-none');
                    issuesList.innerHTML = '';
                    
                    data.issues.forEach(issue => {
                        const li = document.createElement('li');
                        li.className = 'list-group-item list-group-item-danger';
                        li.textContent = issue;
                        issuesList.appendChild(li);
                    });
                }
            }
            
            // Set the detected format
            if (formatDetected && formatBadge && data.detected_format) {
                formatDetected.classList.remove('d-none');
                
                if (data.detected_format === 'bfo') {
                    formatBadge.textContent = 'BFO Standard';
                    formatBadge.className = 'badge bg-success';
                } else {
                    formatBadge.textContent = 'Traditional';
                    formatBadge.className = 'badge bg-info';
                }
            } else if (formatDetected) {
                formatDetected.classList.add('d-none');
            }
            
            // Update used classes
            if (classesUsedList && data.bfo_classes_used && data.bfo_classes_used.length > 0) {
                data.bfo_classes_used.forEach(cls => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item d-flex justify-content-between align-items-center';
                    li.innerHTML = `<span>${cls}</span><span class="badge bg-primary">Class</span>`;
                    classesUsedList.appendChild(li);
                });
            }
            
            // Update used relations
            if (relationsUsedList && data.bfo_relations_used && data.bfo_relations_used.length > 0) {
                data.bfo_relations_used.forEach(rel => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item d-flex justify-content-between align-items-center';
                    li.innerHTML = `<span>${rel}</span><span class="badge bg-info">Relation</span>`;
                    relationsUsedList.appendChild(li);
                });
            }
            
            // Update non-BFO terms
            if (nonBfoTermsList && data.non_bfo_terms && data.non_bfo_terms.length > 0) {
                data.non_bfo_terms.forEach(term => {
                    const li = document.createElement('li');
                    li.className = 'list-group-item d-flex justify-content-between align-items-center';
                    li.innerHTML = `<span>${term}</span><span class="badge bg-warning text-dark">Custom</span>`;
                    nonBfoTermsList.appendChild(li);
                });
            }
        })
        .catch(error => {
            validityResult.innerHTML = `<span class="text-danger"><i class="fas fa-exclamation-triangle me-1"></i>${error.message}</span>`;
        });
    }
    
    // Show error message
    function showError(message) {
        if (!resultsContainer || !validityResult) return;
        
        resultsContainer.classList.remove('d-none');
        validityResult.innerHTML = `<span class="text-danger"><i class="fas fa-exclamation-triangle me-1"></i>${message}</span>`;
        
        if (classesUsedList) classesUsedList.innerHTML = '';
        if (relationsUsedList) relationsUsedList.innerHTML = '';
        if (nonBfoTermsList) nonBfoTermsList.innerHTML = '';
    }
    
    // Check if an element is in viewport
    function isElementInViewport(el) {
        if (!el) return false;
        
        const rect = el.getBoundingClientRect();
        return (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
    }
});