// Admin dashboard theme toggle: localStorage persistence + Chart.js sync.
(function () {
    var STORAGE_KEY = 'powerwize-theme';

    function resolvedTheme() {
        var explicit = document.documentElement.getAttribute('data-theme');
        if (explicit === 'light' || explicit === 'dark') return explicit;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function updateIcon(theme) {
        var icon = document.getElementById('theme-toggle-icon');
        if (!icon) return;
        icon.className = theme === 'dark' ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
    }

    function themeAwareChartColors(theme) {
        return theme === 'dark'
            ? { text: '#B0B8C4', grid: 'rgba(255,255,255,0.08)' }
            : { text: '#4B5563', grid: 'rgba(0,0,0,0.06)' };
    }

    function applyChartTheme() {
        if (typeof Chart === 'undefined') return;
        var colors = themeAwareChartColors(resolvedTheme());
        Chart.defaults.color = colors.text;
        Chart.defaults.borderColor = colors.grid;
        if (Chart.instances) {
            Object.keys(Chart.instances).forEach(function (key) {
                Chart.instances[key].update();
            });
        }
    }

    window.toggleTheme = function () {
        var next = resolvedTheme() === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem(STORAGE_KEY, next);
        updateIcon(next);
        applyChartTheme();
    };

    document.addEventListener('DOMContentLoaded', function () {
        updateIcon(resolvedTheme());
        applyChartTheme();
    });
})();
