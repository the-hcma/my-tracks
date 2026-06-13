/**
 * Workflow-level tests for Last Known Only — scenarios that unit tests on
 * individual helpers would miss.
 */
import { describe, it, expect, vi } from 'vitest';
import {
    devicePassesLiveActivityFilter,
    fetchLastKnownLocations,
    filterLastKnownLocationsToMissingDevices,
    LAST_KNOWN_FETCH_INIT,
    planLastKnownUiUpdate,
    resolveLastKnownMergeStrategy,
} from './liveActivityToolbar';

function jsonFetchResponse(body: unknown, ok = true, status = 200) {
    return {
        ok,
        status,
        text: async () => JSON.stringify(body),
    };
}

describe('Latest → Last Known', () => {
    const alice = { id: 11, device_name: 'alice/phone', timestamp: 200 };
    const bob = { id: 12, device_name: 'bob/phone', timestamp: 100 };
    const apiResults = [alice, bob];

    it('staff fetches unfiltered last-known even when log only shows alice', async () => {
        const fetchFn = vi.fn().mockResolvedValue(jsonFetchResponse({ results: apiResults }));

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: true,
            visibleDeviceNames: ['alice/phone'],
            extractResults: (data) => (data as { results: typeof apiResults }).results,
        });

        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith('/api/locations/last-known/', LAST_KNOWN_FETCH_INIT);
        expect(locations).toEqual(apiResults);
    });

    it('non-staff scopes last-known fetch to visible devices', async () => {
        const fetchFn = vi.fn().mockResolvedValue(jsonFetchResponse({ results: apiResults }));

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: false,
            visibleDeviceNames: ['alice/phone', 'bob/phone'],
            extractResults: (data) => (data as { results: typeof apiResults }).results,
        });

        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith(
            '/api/locations/last-known/?device=alice%2Fphone&device=bob%2Fphone',
            LAST_KNOWN_FETCH_INIT,
        );
        expect(locations).toEqual(apiResults);
    });

    it('planLastKnownUiUpdate replaces log with full API even when alice is already rendered', () => {
        const plan = planLastKnownUiUpdate({
            locations: apiResults,
            skipHistoryFetch: false,
            renderedDeviceCount: 1,
            renderedDeviceNames: ['alice/phone'],
        });

        expect(plan.mergeStrategy).toBe('replace');
        expect(plan.highlightKeys).toEqual(new Set(['id:11', 'id:12']));
        expect(plan.locations).toEqual(apiResults);
    });
});

describe('Reset → Last Known', () => {
    const alice = { id: 11, device_name: 'alice/phone', timestamp: 200 };
    const bob = { id: 12, device_name: 'bob/phone', timestamp: 100 };

    it('planLastKnownUiUpdate uses replace when skipHistoryFetch even with rendered devices', () => {
        expect(
            resolveLastKnownMergeStrategy({
                skipHistoryFetch: true,
                renderedDeviceCount: 2,
            }),
        ).toBe('replace');

        const plan = planLastKnownUiUpdate({
            locations: [alice, bob],
            skipHistoryFetch: true,
            renderedDeviceCount: 2,
            renderedDeviceNames: ['alice/phone', 'bob/phone'],
        });

        expect(plan.mergeStrategy).toBe('replace');
        expect(plan.highlightKeys).toEqual(new Set(['id:11', 'id:12']));
    });

    it('devicePassesLiveActivityFilter allows bob when selectedDevice=alice and skipHistoryFetch', () => {
        expect(
            devicePassesLiveActivityFilter({
                deviceName: 'bob/phone',
                selectedDevice: 'alice/phone',
                skipHistoryFetch: true,
            }),
        ).toBe(true);

        expect(
            devicePassesLiveActivityFilter({
                deviceName: 'bob/phone',
                selectedDevice: 'alice/phone',
                skipHistoryFetch: false,
            }),
        ).toBe(false);
    });

    it('devicePassesLiveActivityFilter shows all devices when Last Known Only is on', () => {
        expect(
            devicePassesLiveActivityFilter({
                deviceName: 'bob/phone',
                selectedDevice: 'alice/phone',
                skipHistoryFetch: false,
                showLastKnownOnly: true,
            }),
        ).toBe(true);
    });
});

describe('Regression guard', () => {
    const alice = { id: 11, device_name: 'alice/phone', timestamp: 200 };
    const bob = { id: 12, device_name: 'bob/phone', timestamp: 100 };
    const apiResults = [alice, bob];

    it('filterLastKnownLocationsToMissingDevices still filters for append callers', () => {
        expect(filterLastKnownLocationsToMissingDevices(apiResults, ['alice/phone'])).toEqual([bob]);
    });

    it('fetchLastKnownLocations returns full API; planLastKnownUiUpdate replaces with all rows', async () => {
        const fetchFn = vi.fn().mockResolvedValue(jsonFetchResponse({ results: apiResults }));

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: false,
            visibleDeviceNames: ['alice/phone', 'bob/phone'],
            extractResults: (data) => (data as { results: typeof apiResults }).results,
        });

        expect(locations).toEqual(apiResults);

        const plan = planLastKnownUiUpdate({
            locations,
            skipHistoryFetch: false,
            renderedDeviceCount: 1,
            renderedDeviceNames: ['alice/phone'],
        });
        expect(plan.locations).toEqual(apiResults);
    });
});
