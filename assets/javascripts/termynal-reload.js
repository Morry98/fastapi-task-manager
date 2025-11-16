// Flag to skip the first execution because is managed by termynal itself
let isFirstLoad = true;

// Re-initialize termynal after each page load
document$.subscribe(function() {
    if (isFirstLoad) {
        isFirstLoad = false;
        return;
    }

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
