// Public-site theme toggle. Shares its localStorage key with admin-theme.js
// so a preference set in either place applies in both.
(function () {
    var STORAGE_KEY = 'powerwize-theme';

    function resolvedTheme() {
        return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    }

    function updateToggle(theme) {
        var btn = document.getElementById('theme-toggle');
        if (!btn) return;
        btn.setAttribute('aria-label', theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme');
    }

    window.toggleTheme = function () {
        var next = resolvedTheme() === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem(STORAGE_KEY, next);
        updateToggle(next);
    };

    document.addEventListener('DOMContentLoaded', function () {
        updateToggle(resolvedTheme());
    });
})();
