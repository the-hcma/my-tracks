/**
 * Workflow-level tests for Last Known Only — scenarios that unit tests on
 * individual helpers would miss.
 */
import { describe, it, expect, vi } from 'vitest';
import {
    devicePassesLiveActivityFilter,
    fetchLastKnownLocations,
    filterLastKnownLocationsToMissingDevices,
    planLastKnownUiUpdate,
    resolveLastKnownMergeStrategy,
} from './liveActivityToolbar';

describe('Latest → Last Known', () => {
    const alice = { id: 11, device_name: 'alice/phone', timestamp: 200 };
    const bob = { id: 12, device_name: 'bob/phone', timestamp: 100 };
    const apiResults = [alice, bob];

    it('fetches full last-known API even when log only shows alice', async () => {
        const fetchFn = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ results: apiResults }),
        });

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            selectedDevice: undefined,
            skipHistoryFetch: false,
            extractResults: (data) => (data as { results: typeof apiResults }).results,
        });

        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith('/api/locations/last-known/');
        expect(locations).toEqual(apiResults);
    });

    it('planLastKnownUiUpdate highlight keys include both ids but append only missing devices', () => {
        const plan = planLastKnownUiUpdate({
            locations: apiResults,
            skipHistoryFetch: false,
            renderedDeviceCount: 1,
            renderedDeviceNames: ['alice/phone'],
        });

        expect(plan.mergeStrategy).toBe('append');
        expect(plan.highlightKeys).toEqual(new Set(['id:11', 'id:12']));
        expect(plan.locations).toEqual([bob]);
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
});

describe('Regression guard', () => {
    const alice = { id: 11, device_name: 'alice/phone', timestamp: 200 };
    const bob = { id: 12, device_name: 'bob/phone', timestamp: 100 };
    const apiResults = [alice, bob];

    it('fetchLastKnownLocations returns full API; planLastKnownUiUpdate filters append rows', async () => {
        const missingOnly = filterLastKnownLocationsToMissingDevices(apiResults, ['alice/phone']);
        expect(missingOnly).toEqual([bob]);

        const fetchFn = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ results: apiResults }),
        });

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            selectedDevice: undefined,
            skipHistoryFetch: false,
            extractResults: (data) => (data as { results: typeof apiResults }).results,
        });

        expect(locations).toEqual(apiResults);

        const plan = planLastKnownUiUpdate({
            locations,
            skipHistoryFetch: false,
            renderedDeviceCount: 1,
            renderedDeviceNames: ['alice/phone'],
        });
        expect(plan.locations).toEqual(missingOnly);
    });
});
