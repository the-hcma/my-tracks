import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { resolveServiceWorkerFetchRoute, shouldBypassServiceWorker } from './swRouting';

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
});
