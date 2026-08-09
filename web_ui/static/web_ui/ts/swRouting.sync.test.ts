import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
    isShellHtmlPath,
    resolveServiceWorkerFetchRoute,
    shouldBypassServiceWorker,
} from './swRouting';

describe('sw.js stays aligned with swRouting.ts', () => {
    const swJs = readFileSync(join(__dirname, '../sw.js'), 'utf8');

    it('inlines the same API bypass guard as swRouting.ts', () => {
        expect(swJs).toContain('function shouldBypassServiceWorker(pathname)');
        expect(swJs).toContain('pathname.startsWith("/api/")');
        expect(swJs).toContain('pathname.startsWith("/ws/")');
        for (const path of ['/api/locations/last-known/', '/api/devices/', '/ws/locations/']) {
            expect(shouldBypassServiceWorker(path)).toBe(true);
            expect(resolveServiceWorkerFetchRoute(path)).toBe('bypass');
        }
    });

    it('bumps the cache version and keeps HTML shells network-first', () => {
        expect(swJs).toContain('my-tracks-pwa-v6');
        expect(swJs).not.toMatch(/const PRECACHE = \[\s*"\/"/);
        expect(swJs).toContain('function isShellHtmlPath(pathname)');
        expect(swJs).toContain('request.mode === "navigate"');
        for (const path of ['/', '/login/', '/logout/']) {
            expect(isShellHtmlPath(path)).toBe(true);
            expect(resolveServiceWorkerFetchRoute(path)).toBe('network-first');
        }
    });
});
