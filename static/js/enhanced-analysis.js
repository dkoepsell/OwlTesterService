/**
 * Enhanced Analysis JavaScript for OWL Tester
 * 
 * This script handles AJAX interactions for the enhanced analysis features:
 * - Enhanced consistency checks with multiple reasoners
 * - Completeness validation for FOL premises
 * - Comprehensive implications generation
 */

$(document).ready(function() {
    // Enhanced consistency check
    $('#runEnhancedConsistency').click(function() {
        const analysisId = $(this).data('analysis-id');
        const $button = $(this);
        
        if (!analysisId) {
            alert('Analysis ID not found. Please save the analysis first.');
            return;
        }
        
        $button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Running...');
        
        $.ajax({
            url: `/api/enhanced-consistency/${analysisId}`,
            method: 'GET',
            success: function(response) {
                if (response.success) {
                    // Show success notification
                    showNotification('success', 'Enhanced consistency check complete!');
                    
                    // Reload the page to show updated consistency info
                    setTimeout(function() {
                        location.reload();
                    }, 1500);
                } else {
                    showNotification('error', 'Error: ' + (response.message || 'Unknown error'));
                    $button.prop('disabled', false).html('<i class="fas fa-sync me-2"></i>Run Enhanced Consistency Check');
                }
            },
            error: function(xhr, status, error) {
                showNotification('error', 'Error: ' + (xhr.responseJSON?.message || error || 'Server error'));
                $button.prop('disabled', false).html('<i class="fas fa-sync me-2"></i>Run Enhanced Consistency Check');
            }
        });
    });
    
    // Completeness validation
    $('#validateCompleteness').click(function() {
        const analysisId = $(this).data('analysis-id');
        const $button = $(this);
        
        if (!analysisId) {
            alert('Analysis ID not found. Please save the analysis first.');
            return;
        }
        
        $button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Validating...');
        
        $.ajax({
            url: `/api/validate-completeness/${analysisId}`,
            method: 'GET',
            success: function(response) {
                if (response.success) {
                    // Show success notification
                    showNotification('success', 'Completeness validation finished!');
                    
                    // Reload the page to show completeness info
                    setTimeout(function() {
                        location.reload();
                    }, 1500);
                } else {
                    showNotification('error', 'Error: ' + (response.message || 'Unknown error'));
                    $button.prop('disabled', false).html('<i class="fas fa-sync me-2"></i>Validate Completeness');
                }
            },
            error: function(xhr, status, error) {
                showNotification('error', 'Error: ' + (xhr.responseJSON?.message || error || 'Server error'));
                $button.prop('disabled', false).html('<i class="fas fa-sync me-2"></i>Validate Completeness');
            }
        });
    });
    
    // Generate standard implications
    $('#generateImplications').click(function() {
        const analysisId = $(this).data('analysis-id');
        const $button = $(this);
        
        if (!analysisId) {
            alert('Analysis ID not found. Please save the analysis first.');
            return;
        }
        
        $button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...');
        
        $.ajax({
            url: `/api/implications/${analysisId}`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ count: 5, comprehensive: false }),
            success: function(response) {
                if (response.implications) {
                    // Show success notification
                    showNotification('success', 'Implications generated successfully!');
                    
                    // Reload the page to show implications
                    setTimeout(function() {
                        location.reload();
                    }, 1500);
                } else {
                    showNotification('error', 'Error generating implications');
                    $button.prop('disabled', false).html('<i class="fas fa-magic me-2"></i>Generate Implications');
                }
            },
            error: function(xhr, status, error) {
                showNotification('error', 'Error: ' + (xhr.responseJSON?.message || error || 'Server error'));
                $button.prop('disabled', false).html('<i class="fas fa-magic me-2"></i>Generate Implications');
            }
        });
    });
    
    // Generate comprehensive implications
    $('#generateComprehensiveImplications').click(function() {
        const analysisId = $(this).data('analysis-id');
        const $button = $(this);
        
        if (!analysisId) {
            alert('Analysis ID not found. Please save the analysis first.');
            return;
        }
        
        // Show warning dialog about comprehensive generation
        if (confirm('Comprehensive generation can take longer as it systematically generates implications for all premise types. Continue?')) {
            $button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...');
            
            $.ajax({
                url: `/api/implications/${analysisId}`,
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ count: 3, comprehensive: true }),
                success: function(response) {
                    if (response.implications) {
                        // Show success notification
                        showNotification('success', 'Comprehensive implications generated successfully!');
                        
                        // Reload the page to show implications
                        setTimeout(function() {
                            location.reload();
                        }, 1500);
                    } else {
                        showNotification('error', 'Error generating comprehensive implications');
                        $button.prop('disabled', false).html('<i class="fas fa-brain me-2"></i>Generate Comprehensive Implications');
                    }
                },
                error: function(xhr, status, error) {
                    showNotification('error', 'Error: ' + (xhr.responseJSON?.message || error || 'Server error'));
                    $button.prop('disabled', false).html('<i class="fas fa-brain me-2"></i>Generate Comprehensive Implications');
                }
            });
        }
    });
    
    // Helper function to show notifications
    function showNotification(type, message) {
        // Create notification container if it doesn't exist
        if ($('#notification-container').length === 0) {
            $('body').append('<div id="notification-container" style="position: fixed; top: 20px; right: 20px; z-index: 9999;"></div>');
        }
        
        // Create notification element
        const $notification = $(`
            <div class="toast align-items-center text-white bg-${type === 'success' ? 'success' : 'danger'} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">
                        <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'} me-2"></i>
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `);
        
        // Append notification to container
        $('#notification-container').append($notification);
        
        // Initialize and show the toast
        const toast = new bootstrap.Toast($notification, {
            delay: 5000
        });
        toast.show();
        
        // Remove notification after it's hidden
        $notification.on('hidden.bs.toast', function() {
            $(this).remove();
        });
    }
});