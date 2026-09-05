/**
 * PrintFlow — Global Authentication & Authorization Guard
 * Runs synchronously in <head> before <body> render to prevent flash of unauthenticated content.
 */
(function () {
    try {
        const pathParts = window.location.pathname.split('/');
        const currentPage = (pathParts[pathParts.length - 1] || 'index.html').toLowerCase();

        const publicPages = ['login.html', 'index.html', '', 'privacy-policy.html', 'terms.html', 'refund-policy.html'];
        const isPublicPage = publicPages.includes(currentPage);
        const isAdminPage = currentPage === 'admin.html';
        const isCustomerPage = ['home.html', 'print-details.html', 'payment.html', 'success.html'].includes(currentPage);

        const storedMobile = (localStorage.getItem('mobileNumber') || '').trim();
        const isAuthenticated = storedMobile.length === 10 && /^\d{10}$/.test(storedMobile);
        const isAdminUnlocked = sessionStorage.getItem('printflowAdminUnlocked') === 'true';

        // 1. Unauthenticated user trying to access any protected customer or admin page
        if ((isCustomerPage || isAdminPage) && !isAuthenticated) {
            if (document.documentElement) {
                document.documentElement.style.display = 'none';
            }
            window.location.replace('login.html');
            return;
        }

        // 2. Authenticated user on login page -> redirect to home.html
        if (currentPage === 'login.html' && isAuthenticated) {
            window.location.replace('home.html');
            return;
        }

        // Ensure page is visible if authentication passes
        if (document.documentElement) {
            document.documentElement.style.display = '';
        }
    } catch (err) {
        console.warn('Auth guard note:', err);
    }
})();
