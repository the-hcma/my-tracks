import { afterEach, describe, expect, it, vi } from 'vitest';
import { LAST_KNOWN_FETCH_INIT, LastKnownFetchError } from './liveActivityToolbar';
import {
    lastKnownFetchErrorMessage,
    resetLastKnownLoadStateForTests,
    runLastKnownLoad,
} from './lastKnownLoad';
import { jsonFetchResponse } from './test/fetchMock';

describe('runLastKnownLoad', () => {
    afterEach(() => {
        resetLastKnownLoadStateForTests();
    });

    const hcma = { id: 32660, device_name: 'hcma/pixel7pro', timestamp: 200 };
    const kristen = { id: 32740, device_name: 'kristen/pixel7', timestamp: 100 };
    const apiResults = [hcma, kristen];

    it('staff replace applies every device from unfiltered last-known even when visible list is partial', async () => {
        const fetchFn = vi.fn().mockResolvedValue(jsonFetchResponse({ results: apiResults }));
        const replaced: typeof apiResults[] = [];

        const result = await runLastKnownLoad(
            {
                fetchFn: fetchFn as unknown as typeof fetch,
                isStaff: true,
                visibleDeviceNames: ['hcma/pixel7pro'],
                skipHistoryFetch: true,
                renderedDeviceNames: new Set<string>(),
                extractResults: (data) => (data as { results: typeof apiResults }).results,
            },
            {
                onReplace: (locations) => {
                    replaced.push(locations);
                },
                onEmpty: () => {
                    throw new Error('unexpected empty');
                },
                onError: () => {
                    throw new Error('unexpected error');
                },
            },
        );

        expect(result).toBe('success');
        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith('/api/locations/last-known/', LAST_KNOWN_FETCH_INIT);
        expect(replaced).toHaveLength(1);
        expect(replaced[0]).toEqual(apiResults);
    });

    it('stale failed load does not overwrite a newer successful load', async () => {
        let resolveSlow: ((value: ReturnType<typeof jsonFetchResponse>) => void) | undefined;
        const slowPromise = new Promise<ReturnType<typeof jsonFetchResponse>>((resolve) => {
            resolveSlow = resolve;
        });
        const fetchFn = vi
            .fn()
            .mockImplementationOnce(() => slowPromise)
            .mockResolvedValueOnce(jsonFetchResponse({ results: apiResults }));

        const errors: string[] = [];
        const replaced: typeof apiResults[] = [];

        const slowLoad = runLastKnownLoad(
            {
                fetchFn: fetchFn as unknown as typeof fetch,
                isStaff: true,
                visibleDeviceNames: [],
                skipHistoryFetch: true,
                renderedDeviceNames: new Set<string>(),
                extractResults: (data) => (data as { results: typeof apiResults }).results,
            },
            {
                onReplace: (locations) => {
                    replaced.push(locations);
                },
                onEmpty: () => undefined,
                onError: (message) => {
                    errors.push(message);
                },
            },
        );

        const fastLoad = runLastKnownLoad(
            {
                fetchFn: fetchFn as unknown as typeof fetch,
                isStaff: true,
                visibleDeviceNames: [],
                skipHistoryFetch: true,
                renderedDeviceNames: new Set<string>(),
                extractResults: (data) => (data as { results: typeof apiResults }).results,
            },
            {
                onReplace: (locations) => {
                    replaced.push(locations);
                },
                onEmpty: () => undefined,
                onError: (message) => {
                    errors.push(message);
                },
            },
        );

        const fastResult = await fastLoad;
        expect(fastResult).toBe('success');

        resolveSlow?.({ ok: false, status: 503, text: async () => '' });
        const slowResult = await slowLoad;
        expect(slowResult).toBe('stale');

        expect(replaced).toHaveLength(1);
        expect(replaced[0]).toEqual(apiResults);
        expect(errors).toEqual([]);
    });

    it('waits for an in-flight live refresh before fetching last-known', async () => {
        let resolveRefresh: (() => void) | undefined;
        const refreshGate = new Promise<void>((resolve) => {
            resolveRefresh = resolve;
        });
        const fetchFn = vi.fn().mockResolvedValue(jsonFetchResponse({ results: apiResults }));

        const loadPromise = runLastKnownLoad(
            {
                fetchFn: fetchFn as unknown as typeof fetch,
                isStaff: true,
                visibleDeviceNames: [],
                skipHistoryFetch: false,
                renderedDeviceNames: new Set<string>(),
                extractResults: (data) => (data as { results: typeof apiResults }).results,
                waitForRefresh: () => refreshGate,
            },
            {
                onReplace: () => undefined,
                onEmpty: () => undefined,
                onError: () => {
                    throw new Error('unexpected error');
                },
            },
        );

        await Promise.resolve();
        expect(fetchFn).not.toHaveBeenCalled();

        resolveRefresh?.();
        await loadPromise;
        expect(fetchFn).toHaveBeenCalledOnce();
    });

    it('maps fetch failures to user-visible messages', () => {
        expect(lastKnownFetchErrorMessage(new LastKnownFetchError('network'))).toBe(
            'Last Known: fetch failed (network error).',
        );
        expect(lastKnownFetchErrorMessage(new LastKnownFetchError('http', 503))).toBe(
            'Last Known: fetch failed (503).',
        );
    });
});
