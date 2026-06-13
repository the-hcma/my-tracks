import { describe, expect, it } from 'vitest';
import {
    isMainBundlePath,
    resolveServiceWorkerFetchRoute,
    shouldBypassServiceWorker,
} from './swRouting';

describe('shouldBypassServiceWorker', () => {
    it('bypasses last-known and device API paths', () => {
        expect(shouldBypassServiceWorker('/api/locations/last-known/')).toBe(true);
        expect(shouldBypassServiceWorker('/api/devices/')).toBe(true);
        expect(shouldBypassServiceWorker('/api/health/')).toBe(true);
    });

    it('bypasses websocket paths', () => {
        expect(shouldBypassServiceWorker('/ws/locations/')).toBe(true);
    });

    it('does not bypass static shell assets', () => {
        expect(shouldBypassServiceWorker('/')).toBe(false);
        expect(shouldBypassServiceWorker('/static/web_ui/css/main.css')).toBe(false);
        expect(shouldBypassServiceWorker('/static/web_ui/js/main.js')).toBe(false);
    });
});

describe('isMainBundlePath', () => {
    it('matches unhashed and hashed main bundles', () => {
        expect(isMainBundlePath('/static/web_ui/js/main.js')).toBe(true);
        expect(isMainBundlePath('/static/web_ui/js/main.abc123.js')).toBe(true);
    });

    it('ignores other scripts', () => {
        expect(isMainBundlePath('/static/web_ui/js/messages.js')).toBe(false);
        expect(isMainBundlePath('/static/web_ui/js/swRouting.js')).toBe(false);
    });
});

describe('resolveServiceWorkerFetchRoute', () => {
    it('prioritizes API bypass over main bundle matching', () => {
        expect(resolveServiceWorkerFetchRoute('/api/locations/last-known/')).toBe('bypass');
    });

    it('routes main bundle to stale-while-revalidate handling', () => {
        expect(resolveServiceWorkerFetchRoute('/static/web_ui/js/main.js')).toBe('main-bundle');
    });

    it('routes other same-origin GETs to cache-first', () => {
        expect(resolveServiceWorkerFetchRoute('/static/web_ui/css/main.css')).toBe('cache-first');
    });
});
