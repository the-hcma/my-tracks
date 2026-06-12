/**
 * Tests for live activity toolbar button behavior.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
    LIVE_ACTIVITY_BUTTON_IDS,
    REPORT_LOCATION_API,
    attachLiveActivityToolbar,
    buildLastKnownHighlightKeys,
    buildLastKnownLocationsUrl,
    buildReportLocationBody,
    createLiveActivityResetPatch,
    devicePollSummaryMessage,
    devicePollSummaryToastType,
    fetchAndPollOnlineMqttDevices,
    fetchLastKnownLocations,
    filterLastKnownLocationsToMissingDevices,
    lastKnownLocationKeysFromLogEntries,
    pollOnlineMqttDevices,
    resolveLastKnownHighlightKeys,
    resolveLastKnownOnlyToggleEffect,
    resolveLastKnownQueryDeviceNames,
    resolveLiveActivityToolbarClick,
    resolveLiveDeviceFilterChange,
    resolveLiveLocationIngestPath,
    resolveSkipHistoryFetchForRefresh,
    selectOnlineMqttDevices,
    shouldFilterLiveActivityByDevice,
    summarizeDevicePollResults,
    toggleLastKnownOnlyFlag,
} from './liveActivityToolbar';

describe('resolveLiveActivityToolbarClick', () => {
    it('maps Last 30min to a 30m refresh', () => {
        expect(resolveLiveActivityToolbarClick(LIVE_ACTIVITY_BUTTON_IDS.load30m)).toEqual({
            action: 'refresh',
            request: '30m',
        });
    });

    it('maps Latest to a latest refresh', () => {
        expect(resolveLiveActivityToolbarClick(LIVE_ACTIVITY_BUTTON_IDS.refreshLatest)).toEqual({
            action: 'refresh',
            request: 'latest',
        });
    });

    it('maps Reset to reset action', () => {
        expect(resolveLiveActivityToolbarClick(LIVE_ACTIVITY_BUTTON_IDS.reset)).toEqual({
            action: 'reset',
        });
    });

    it('maps Last Known Only to toggle action', () => {
        expect(resolveLiveActivityToolbarClick(LIVE_ACTIVITY_BUTTON_IDS.lastKnownOnly)).toEqual({
            action: 'toggle-last-known-only',
        });
    });

    it('maps Poll Devices to poll action', () => {
        expect(resolveLiveActivityToolbarClick(LIVE_ACTIVITY_BUTTON_IDS.pollDevices)).toEqual({
            action: 'poll-devices',
        });
    });

    it('returns null for unknown buttons', () => {
        expect(resolveLiveActivityToolbarClick('theme-toggle')).toBeNull();
    });
});

describe('resolveSkipHistoryFetchForRefresh', () => {
    it('blocks incremental refresh while post-reset mode is active', () => {
        expect(resolveSkipHistoryFetchForRefresh(true, 'incremental')).toEqual({
            blocked: true,
            skipHistoryFetch: true,
        });
    });

    it('allows Last 30min after reset and re-enables history fetch', () => {
        expect(resolveSkipHistoryFetchForRefresh(true, '30m')).toEqual({
            blocked: false,
            skipHistoryFetch: false,
        });
    });

    it('allows Latest after reset and re-enables history fetch', () => {
        expect(resolveSkipHistoryFetchForRefresh(true, 'latest')).toEqual({
            blocked: false,
            skipHistoryFetch: false,
        });
    });

    it('allows hour reload after reset', () => {
        expect(resolveSkipHistoryFetchForRefresh(true, 'hour')).toEqual({
            blocked: false,
            skipHistoryFetch: false,
        });
    });

    it('does not block refresh when history fetch is already enabled', () => {
        expect(resolveSkipHistoryFetchForRefresh(false, '30m')).toEqual({
            blocked: false,
            skipHistoryFetch: false,
        });
    });
});

describe('resolveLiveDeviceFilterChange', () => {
    it('reloads last hour in live mode and resets cursor', () => {
        expect(resolveLiveDeviceFilterChange(true)).toEqual({
            action: 'refresh-hour',
            resetCursor: true,
        });
    });

    it('reloads historic trail outside live mode', () => {
        expect(resolveLiveDeviceFilterChange(false)).toEqual({ action: 'historic-trail' });
    });
});

describe('createLiveActivityResetPatch', () => {
    it('clears counters and skips history fetch after reset', () => {
        expect(createLiveActivityResetPatch(1_700_000_000)).toEqual({
            eventCount: 0,
            lastTimestamp: 1_700_000_000,
            lastSeenLocationId: null,
            skipHistoryFetch: true,
            needsFitBounds: true,
            incrementalLocations: {},
            showLastKnownOnly: false,
        });
    });

    it('turns Last Known Only off when reset is applied', () => {
        const patch = createLiveActivityResetPatch(1_700_000_000);
        expect(patch.showLastKnownOnly).toBe(false);
    });
});

describe('toggleLastKnownOnlyFlag', () => {
    it('toggles the last-known-only flag', () => {
        expect(toggleLastKnownOnlyFlag(false)).toBe(true);
        expect(toggleLastKnownOnlyFlag(true)).toBe(false);
    });
});

describe('resolveLiveLocationIngestPath', () => {
    it('writes websocket locations directly after reset without HTTP incremental refresh', () => {
        expect(
            resolveLiveLocationIngestPath({
                isLiveMode: true,
                skipHistoryFetch: true,
                matchesDeviceFilter: true,
            }),
        ).toBe('direct');
    });

    it('uses HTTP incremental refresh in normal live mode', () => {
        expect(
            resolveLiveLocationIngestPath({
                isLiveMode: true,
                skipHistoryFetch: false,
                matchesDeviceFilter: true,
            }),
        ).toBe('http-incremental');
    });

    it('ignores locations that do not match the active device filter', () => {
        expect(
            resolveLiveLocationIngestPath({
                isLiveMode: true,
                skipHistoryFetch: true,
                matchesDeviceFilter: false,
            }),
        ).toBe('ignored');
    });
});

describe('shouldFilterLiveActivityByDevice', () => {
    it('filters when a device is selected and history fetch is enabled', () => {
        expect(
            shouldFilterLiveActivityByDevice({
                selectedDevice: 'kristen/pixel7',
                skipHistoryFetch: false,
            }),
        ).toBe(true);
    });

    it('does not filter when no device is selected', () => {
        expect(
            shouldFilterLiveActivityByDevice({
                selectedDevice: undefined,
                skipHistoryFetch: false,
            }),
        ).toBe(false);
    });

    it('does not filter after reset even when a device remains selected in state', () => {
        expect(
            shouldFilterLiveActivityByDevice({
                selectedDevice: 'kristen/pixel7',
                skipHistoryFetch: true,
            }),
        ).toBe(false);
    });
});

describe('post-reset Last Known Only workflow', () => {
    it('reset turns Last Known Only off', () => {
        const resetPatch = createLiveActivityResetPatch(1_700_000_100);

        expect(resetPatch.showLastKnownOnly).toBe(false);
    });

    it('staff fetches unfiltered last-known after reset', async () => {
        const fetchFn = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                results: [
                    { id: 12, device_name: 'bob/phone', timestamp: 200 },
                    { id: 11, device_name: 'kristen/pixel7', timestamp: 100 },
                ],
            }),
        });

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: true,
            visibleDeviceNames: ['kristen/pixel7'],
            extractResults: (data) =>
                (data as { results: { id: number; device_name: string; timestamp: number }[] }).results,
        });

        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith('/api/locations/last-known/');
        expect(locations).toEqual([
            { id: 12, device_name: 'bob/phone', timestamp: 200 },
            { id: 11, device_name: 'kristen/pixel7', timestamp: 100 },
        ]);
    });

    it('non-staff passes visible device query params after reset', async () => {
        const fetchFn = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                results: [{ id: 11, device_name: 'kristen/pixel7', timestamp: 100 }],
            }),
        });

        const locations = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: false,
            visibleDeviceNames: ['kristen/pixel7', 'bob/phone'],
            extractResults: (data) =>
                (data as { results: { id: number; device_name: string; timestamp: number }[] }).results,
        });

        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith(
            '/api/locations/last-known/?device=kristen%2Fpixel7&device=bob%2Fphone',
        );
        expect(locations).toEqual([{ id: 11, device_name: 'kristen/pixel7', timestamp: 100 }]);
    });
});

describe('post-reset organic live updates', () => {
    it('keeps incremental HTTP blocked but allows direct websocket ingest after reset only', () => {
        const resetPatch = createLiveActivityResetPatch(1_700_000_100);

        expect(resetPatch.skipHistoryFetch).toBe(true);
        expect(resolveSkipHistoryFetchForRefresh(true, 'incremental')).toEqual({
            blocked: true,
            skipHistoryFetch: true,
        });
        expect(
            resolveLiveLocationIngestPath({
                isLiveMode: true,
                skipHistoryFetch: resetPatch.skipHistoryFetch,
                matchesDeviceFilter: true,
            }),
        ).toBe('direct');
    });
});

describe('Last Known Only helpers', () => {
    const locations = [
        { id: 11, device_name: 'kristen/pixel7' },
        { id: 12, device_name: 'bob/phone' },
    ];

    it('resolveLastKnownQueryDeviceNames returns null for staff', () => {
        expect(
            resolveLastKnownQueryDeviceNames({
                isStaff: true,
                visibleDeviceNames: ['kristen/pixel7'],
            }),
        ).toBeNull();
    });

    it('resolveLastKnownQueryDeviceNames copies visible names for non-staff', () => {
        expect(
            resolveLastKnownQueryDeviceNames({
                isStaff: false,
                visibleDeviceNames: ['kristen/pixel7', 'bob/phone'],
            }),
        ).toEqual(['kristen/pixel7', 'bob/phone']);
    });

    it('builds an unfiltered last-known URL for staff', () => {
        expect(buildLastKnownLocationsUrl({ queryDeviceNames: null })).toBe('/api/locations/last-known/');
    });

    it('builds a filtered last-known URL for non-staff devices', () => {
        expect(
            buildLastKnownLocationsUrl({ queryDeviceNames: ['kristen/pixel7', 'bob/phone'] }),
        ).toBe('/api/locations/last-known/?device=kristen%2Fpixel7&device=bob%2Fphone');
    });

    it('filters out devices that already have rows in the activity log', () => {
        expect(filterLastKnownLocationsToMissingDevices(locations, ['kristen/pixel7'])).toEqual([
            { id: 12, device_name: 'bob/phone' },
        ]);
    });

    it('non-staff fetches devices first when visible names are empty', async () => {
        const fetchFn = vi
            .fn()
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    results: [{ device_name: 'kristen/pixel7' }, { device_name: 'bob/phone' }],
                }),
            })
            .mockResolvedValueOnce({
                ok: true,
                json: async () => ({ results: locations }),
            });

        const result = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: false,
            visibleDeviceNames: [],
            extractResults: (data) => (data as { results: typeof locations }).results,
        });

        expect(fetchFn).toHaveBeenCalledTimes(2);
        expect(fetchFn).toHaveBeenNthCalledWith(1, '/api/devices/');
        expect(fetchFn).toHaveBeenNthCalledWith(
            2,
            '/api/locations/last-known/?device=kristen%2Fpixel7&device=bob%2Fphone',
        );
        expect(result).toEqual(locations);
    });

    it('staff fetches unfiltered last-known even when some devices are already in the log', async () => {
        const fetchFn = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ results: locations }),
        });

        const result = await fetchLastKnownLocations({
            fetchFn: fetchFn as unknown as typeof fetch,
            isStaff: true,
            visibleDeviceNames: ['kristen/pixel7'],
            extractResults: (data) => (data as { results: typeof locations }).results,
        });

        expect(fetchFn).toHaveBeenCalledWith('/api/locations/last-known/');
        expect(result).toEqual(locations);
    });

    it('builds highlight keys from last-known location ids', () => {
        expect(buildLastKnownHighlightKeys(locations)).toEqual(new Set(['id:11', 'id:12']));
    });

    it('prefers log-derived keys over API snapshot when live rows arrive', () => {
        const logKeys = lastKnownLocationKeysFromLogEntries([
            { deviceName: 'kristen/pixel7', locationKey: 'id:99', timestampUnix: 300 },
        ]);
        const apiSnapshot = new Set(['id:11', 'id:12']);
        expect(resolveLastKnownHighlightKeys(logKeys, apiSnapshot)).toEqual(new Set(['id:99']));
    });

    it('falls back to API snapshot only while the log is empty', () => {
        const logKeys = new Set<string>();
        const apiSnapshot = new Set(['id:11', 'id:12']);
        expect(resolveLastKnownHighlightKeys(logKeys, apiSnapshot)).toEqual(apiSnapshot);
    });

    it('loads locations when enabled in live mode and only refits the map when disabled', () => {
        expect(resolveLastKnownOnlyToggleEffect(true, true)).toEqual({ loadLocations: true });
        expect(resolveLastKnownOnlyToggleEffect(true, false)).toEqual({ refitMap: true });
        expect(resolveLastKnownOnlyToggleEffect(false, true)).toEqual({ refitMap: true });
    });
});

describe('selectOnlineMqttDevices', () => {
    it('keeps only online devices with an MQTT topic', () => {
        const devices = [
            { mqtt_topic_id: 'alice/phone', is_online: true },
            { mqtt_topic_id: '', is_online: true },
            { mqtt_topic_id: 'bob/phone', is_online: false },
            { mqtt_topic_id: 'carol/phone', is_online: true },
        ];
        expect(selectOnlineMqttDevices(devices)).toEqual([devices[0], devices[3]]);
    });
});

describe('buildReportLocationBody', () => {
    it('uses mqtt_topic_id as device_id for report-location', () => {
        expect(buildReportLocationBody({ mqtt_topic_id: 'kristen/pixel7', is_online: true })).toEqual({
            device_id: 'kristen/pixel7',
        });
    });
});

describe('summarizeDevicePollResults', () => {
    it('classifies full, partial, and failed poll outcomes', () => {
        expect(summarizeDevicePollResults(2, 2)).toEqual({ kind: 'all-success', count: 2 });
        expect(summarizeDevicePollResults(1, 2)).toEqual({ kind: 'partial', succeeded: 1, total: 2 });
        expect(summarizeDevicePollResults(0, 2)).toEqual({ kind: 'all-failed', total: 2 });
        expect(summarizeDevicePollResults(0, 0)).toEqual({ kind: 'no-devices' });
    });
});

describe('devicePollSummaryMessage', () => {
    it('formats user-facing poll result messages', () => {
        expect(devicePollSummaryMessage({ kind: 'all-success', count: 1 })).toBe(
            'Location request sent to 1 device.',
        );
        expect(devicePollSummaryMessage({ kind: 'partial', succeeded: 1, total: 3 })).toBe(
            'Location request sent to 1 of 3 devices; 2 failed.',
        );
        expect(devicePollSummaryMessage({ kind: 'no-devices' })).toBe('No online MQTT devices to poll.');
    });
});

describe('devicePollSummaryToastType', () => {
    it('maps poll outcomes to toast severities', () => {
        expect(devicePollSummaryToastType({ kind: 'all-success', count: 1 })).toBe('success');
        expect(devicePollSummaryToastType({ kind: 'partial', succeeded: 1, total: 2 })).toBe('warning');
        expect(devicePollSummaryToastType({ kind: 'fetch-failed' })).toBe('error');
    });
});

describe('pollOnlineMqttDevices', () => {
    it('posts report-location for each online MQTT device', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ ok: true });
        const result = await pollOnlineMqttDevices({
            fetchFn: fetchFn as unknown as typeof fetch,
            getCsrfToken: () => 'csrf-token',
            devices: [
                { mqtt_topic_id: 'alice/phone', is_online: true },
                { mqtt_topic_id: 'bob/phone', is_online: false },
            ],
        });

        expect(result).toEqual({ succeeded: 1, total: 1 });
        expect(fetchFn).toHaveBeenCalledOnce();
        expect(fetchFn).toHaveBeenCalledWith(
            REPORT_LOCATION_API,
            expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({ device_id: 'alice/phone' }),
                headers: expect.objectContaining({ 'X-CSRFToken': 'csrf-token' }),
            }),
        );
    });
});

describe('fetchAndPollOnlineMqttDevices', () => {
    it('returns fetch-failed when device list cannot be loaded', async () => {
        const fetchFn = vi.fn().mockResolvedValue({ ok: false, status: 500 });
        const summary = await fetchAndPollOnlineMqttDevices({
            fetchFn: fetchFn as unknown as typeof fetch,
            getCsrfToken: () => 'csrf',
        });
        expect(summary).toEqual({ kind: 'fetch-failed' });
    });

    it('returns no-devices when nothing is pollable', async () => {
        const fetchFn = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                results: [{ mqtt_topic_id: '', is_online: true }],
            }),
        });
        const summary = await fetchAndPollOnlineMqttDevices({
            fetchFn: fetchFn as unknown as typeof fetch,
            getCsrfToken: () => 'csrf',
        });
        expect(summary).toEqual({ kind: 'no-devices' });
    });
});

describe('attachLiveActivityToolbar', () => {
    let container: HTMLDivElement;

    beforeEach(() => {
        container = document.createElement('div');
        document.body.appendChild(container);
        for (const id of Object.values(LIVE_ACTIVITY_BUTTON_IDS)) {
            const button = document.createElement('button');
            button.id = id;
            container.appendChild(button);
        }
    });

    afterEach(() => {
        container.remove();
    });

    function clickButton(id: string): void {
        const button = document.getElementById(id);
        expect(button).not.toBeNull();
        button!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    }

    it('routes Last Known Only through onToggleLastKnownOnly after reset', () => {
        const onToggleLastKnownOnly = vi.fn();
        attachLiveActivityToolbar({
            onRefresh: vi.fn(),
            onReset: vi.fn(),
            onToggleLastKnownOnly,
            onPollDevices: vi.fn(),
        });

        clickButton(LIVE_ACTIVITY_BUTTON_IDS.reset);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.lastKnownOnly);

        expect(onToggleLastKnownOnly).toHaveBeenCalledOnce();
    });

    it('still routes Last 30min and Latest through onRefresh after a reset workflow', () => {
        const onRefresh = vi.fn();
        attachLiveActivityToolbar({
            onRefresh,
            onReset: vi.fn(),
            onToggleLastKnownOnly: vi.fn(),
            onPollDevices: vi.fn(),
        });

        clickButton(LIVE_ACTIVITY_BUTTON_IDS.reset);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.load30m);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.refreshLatest);

        expect(onRefresh).toHaveBeenNthCalledWith(1, '30m');
        expect(onRefresh).toHaveBeenNthCalledWith(2, 'latest');
    });

    it('invokes the correct handler for each toolbar button', async () => {
        const onRefresh = vi.fn();
        const onReset = vi.fn();
        const onToggleLastKnownOnly = vi.fn();
        const onPollDevices = vi.fn();

        attachLiveActivityToolbar({
            onRefresh,
            onReset,
            onToggleLastKnownOnly,
            onPollDevices,
        });

        clickButton(LIVE_ACTIVITY_BUTTON_IDS.load30m);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.refreshLatest);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.reset);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.lastKnownOnly);
        clickButton(LIVE_ACTIVITY_BUTTON_IDS.pollDevices);

        expect(onRefresh).toHaveBeenNthCalledWith(1, '30m');
        expect(onRefresh).toHaveBeenNthCalledWith(2, 'latest');
        expect(onReset).toHaveBeenCalledOnce();
        expect(onToggleLastKnownOnly).toHaveBeenCalledOnce();
        expect(onPollDevices).toHaveBeenCalledOnce();
    });
});
