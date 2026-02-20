/**
 * Tests for theme management functions.
 *
 * Verifies that dark/light mode toggle, persistence, and system
 * preference detection all work correctly.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { getPreferredTheme, setTheme, toggleTheme, REQUIRED_THEME_VARIABLES } from './theme';

/**
 * Create a mock localStorage for testing.
 * Node/jsdom may not have a fully functional localStorage.
 */
function createMockLocalStorage(): Storage {
    let store: Record<string, string> = {};
    return {
        getItem: (key: string) => store[key] ?? null,
        setItem: (key: string, value: string) => { store[key] = value; },
        removeItem: (key: string) => { delete store[key]; },
        clear: () => { store = {}; },
        get length() { return Object.keys(store).length; },
        key: (index: number) => Object.keys(store)[index] ?? null,
    };
}

/**
 * Create a matchMedia mock that defaults to light mode.
 * jsdom does not implement window.matchMedia.
 */
function createMatchMediaMock(prefersDark = false): typeof window.matchMedia {
    return vi.fn().mockImplementation((query: string) => ({
        matches: prefersDark && query === '(prefers-color-scheme: dark)',
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
    }));
}

describe('theme', () => {
    let mockStorage: Storage;

    beforeEach(() => {
        mockStorage = createMockLocalStorage();
        vi.stubGlobal('localStorage', mockStorage);
        vi.stubGlobal('matchMedia', createMatchMediaMock(false));
        document.documentElement.removeAttribute('data-theme');
        document.body.innerHTML = '';
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        document.documentElement.removeAttribute('data-theme');
    });

    describe('REQUIRED_THEME_VARIABLES', () => {
        it('contains all essential CSS custom properties', () => {
            expect(REQUIRED_THEME_VARIABLES).toContain('--bg-main');
            expect(REQUIRED_THEME_VARIABLES).toContain('--text-main');
            expect(REQUIRED_THEME_VARIABLES).toContain('--bg-left');
            expect(REQUIRED_THEME_VARIABLES).toContain('--border-color');
            expect(REQUIRED_THEME_VARIABLES).toContain('--link-color');
            expect(REQUIRED_THEME_VARIABLES).toContain('--log-device-color');
            expect(REQUIRED_THEME_VARIABLES).toContain('--log-coords-color');
            expect(REQUIRED_THEME_VARIABLES).toContain('--right-header-color');
        });

        it('has at least 15 variables for comprehensive theming', () => {
            expect(REQUIRED_THEME_VARIABLES.length).toBeGreaterThanOrEqual(15);
        });
    });

    describe('getPreferredTheme', () => {
        it('returns saved theme from localStorage when present', () => {
            localStorage.setItem('theme', 'dark');
            expect(getPreferredTheme()).toBe('dark');
        });

        it('returns light when saved as light', () => {
            localStorage.setItem('theme', 'light');
            expect(getPreferredTheme()).toBe('light');
        });

        it('falls back to system preference when no saved theme', () => {
            // jsdom defaults to light (prefers-color-scheme: dark = false)
            const result = getPreferredTheme();
            expect(result).toBe('light');
        });

        it('returns dark when system prefers dark', () => {
            vi.stubGlobal('matchMedia', createMatchMediaMock(true));

            const result = getPreferredTheme();
            expect(result).toBe('dark');
        });

        it('ignores invalid localStorage values', () => {
            localStorage.setItem('theme', 'blue');
            // Should fall back to system preference (light), not return 'blue'
            const result = getPreferredTheme();
            expect(result).toBe('light');
        });
    });

    describe('setTheme', () => {
        it('sets data-theme attribute to dark', () => {
            setTheme('dark');
            expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
        });

        it('sets data-theme attribute to light', () => {
            setTheme('light');
            expect(document.documentElement.getAttribute('data-theme')).toBe('light');
        });

        it('persists theme to localStorage', () => {
            setTheme('dark');
            expect(localStorage.getItem('theme')).toBe('dark');

            setTheme('light');
            expect(localStorage.getItem('theme')).toBe('light');
        });

        it('updates toggle button to sun icon for dark theme', () => {
            document.body.innerHTML = '<button id="theme-toggle">🌙</button>';

            setTheme('dark');
            const toggle = document.getElementById('theme-toggle');
            expect(toggle?.textContent).toBe('☀️');
        });

        it('updates toggle button to moon icon for light theme', () => {
            document.body.innerHTML = '<button id="theme-toggle">☀️</button>';

            setTheme('light');
            const toggle = document.getElementById('theme-toggle');
            expect(toggle?.textContent).toBe('🌙');
        });

        it('handles missing toggle button gracefully', () => {
            // No toggle button in DOM - should not throw
            expect(() => setTheme('dark')).not.toThrow();
            expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
        });
    });

    describe('toggleTheme', () => {
        it('switches from dark to light', () => {
            document.documentElement.setAttribute('data-theme', 'dark');

            const newTheme = toggleTheme();
            expect(newTheme).toBe('light');
            expect(document.documentElement.getAttribute('data-theme')).toBe('light');
        });

        it('switches from light to dark', () => {
            document.documentElement.setAttribute('data-theme', 'light');

            const newTheme = toggleTheme();
            expect(newTheme).toBe('dark');
            expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
        });

        it('defaults to dark when no data-theme attribute is set', () => {
            // When no data-theme attribute exists, getAttribute returns null
            // null !== 'dark', so toggleTheme treats it as non-dark → toggles to dark
            const newTheme = toggleTheme();
            expect(newTheme).toBe('dark');
        });

        it('persists the toggled theme', () => {
            document.documentElement.setAttribute('data-theme', 'dark');

            toggleTheme();
            expect(localStorage.getItem('theme')).toBe('light');

            toggleTheme();
            expect(localStorage.getItem('theme')).toBe('dark');
        });

        it('round-trips correctly through multiple toggles', () => {
            setTheme('dark');

            toggleTheme(); // -> light
            expect(document.documentElement.getAttribute('data-theme')).toBe('light');

            toggleTheme(); // -> dark
            expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

            toggleTheme(); // -> light
            expect(document.documentElement.getAttribute('data-theme')).toBe('light');
        });
    });
});
