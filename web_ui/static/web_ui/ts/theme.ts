/**
 * My Tracks - Theme Management.
 *
 * Functions for toggling between light and dark themes.
 * Extracted from main.ts for testability.
 */

/**
 * CSS custom properties that must be defined in both light and dark themes.
 * Keep in sync with main.css [data-theme="light"] and [data-theme="dark"].
 */
export const REQUIRED_THEME_VARIABLES = [
    '--bg-main',
    '--bg-left',
    '--text-main',
    '--text-secondary',
    '--text-left',
    '--border-color',
    '--endpoint-bg',
    '--endpoint-border',
    '--code-bg',
    '--log-entry-bg',
    '--log-entry-border',
    '--log-time-color',
    '--link-color',
    '--status-color',
    '--log-device-color',
    '--log-coords-color',
    '--right-header-color',
] as const;

export type Theme = 'dark' | 'light';

/**
 * Get the user's preferred theme.
 * Checks localStorage first, then falls back to system preference.
 * @returns 'dark' or 'light'
 */
export function getPreferredTheme(): Theme {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark' || savedTheme === 'light') {
        return savedTheme;
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * Set the application theme.
 * Updates the data-theme attribute, persists to localStorage, and
 * updates the toggle button icon.
 * @param theme - 'dark' or 'light'
 */
export function setTheme(theme: Theme): void {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
        toggle.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
}

/**
 * Toggle between dark and light themes.
 * @returns The new theme that was applied
 */
export function toggleTheme(): Theme {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme: Theme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    return newTheme;
}
