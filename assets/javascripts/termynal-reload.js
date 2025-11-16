// Re-initialize termynal after each page load
document$.subscribe(function() {
    // Wait for the DOM to be updated
    setTimeout(function() {
        // Find all termynal blocks and re-initialize them
        document.querySelectorAll('[data-termynal]').forEach(function(element) {
            if (!element.dataset.termynalInitialized) {
                new Termynal(element);
                element.dataset.termynalInitialized = 'true';
            }
        });
    }, 100);
});
