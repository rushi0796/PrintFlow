/**
 * PrintFlow — Global Authentication & Authorization Guard
 * Runs synchronously in <head> before <body> render to prevent flash of unauthenticated content.
 */
(function () {
    try {
        const pathParts = window.location.pathname.split('/');
        const rawPage = (pathParts[pathParts.length - 1] || 'index.html').toLowerCase();
        const currentPage = rawPage.split('?')[0].split('#')[0];
        const isLogoutParam = window.location.search.includes('logout=true');

        if (isLogoutParam) {
            localStorage.removeItem('mobileNumber');
            sessionStorage.removeItem('printflowAdminUnlocked');
        }

        const publicPages = ['login.html', 'index.html', '', 'privacy-policy.html', 'terms.html', 'refund-policy.html'];
        const isPublicPage = publicPages.includes(currentPage);

        const storedMobile = (localStorage.getItem('mobileNumber') || '').trim();
        const isAuthenticated = storedMobile.length === 10 && /^\d{10}$/.test(storedMobile);

        // 1. Unauthenticated user trying to access ANY protected page (home, upload, dashboard, orders, profile, success, admin, etc.)
        if (!isPublicPage && !isAuthenticated) {
            if (document.documentElement) {
                document.documentElement.style.display = 'none';
            }
            window.location.replace('login.html');
            return;
        }

        // 2. Authenticated user accessing login.html or index.html without logout param -> redirect to home.html
        if ((currentPage === 'login.html' || currentPage === 'index.html') && isAuthenticated && !isLogoutParam) {
            window.location.replace('home.html');
            return;
        }

        // Always ensure document element is visible on allowed public or authenticated pages
        if (document.documentElement) {
            document.documentElement.style.display = '';
        }
    } catch (err) {
        console.warn('Auth guard note:', err);
        if (document.documentElement) {
            document.documentElement.style.display = '';
        }
    }
})();
