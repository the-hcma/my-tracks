/**
 * Live activity toolbar actions (button clicks and related UI behavior).
 */

import type { LiveActivityRefreshRequest } from './liveActivity';
import { extractResultsList } from './utils';

export const LIVE_ACTIVITY_BUTTON_IDS = {
    load30m: 'load-history-button',
    refreshLatest: 'refresh-live-latest-button',
    lastKnownOnly: 'last-known-only-button',
    pollDevices: 'request-location-button',
    reset: 'reset-button',
} as const;

export type LiveActivityToolbarAction =
    | { action: 'refresh'; request: LiveActivityRefreshRequest }
    | { action: 'reset' }
    | { action: 'toggle-last-known-only' }
    | { action: 'poll-devices' };

export type SkipHistoryFetchResolution =
    | { blocked: true; skipHistoryFetch: true }
    | { blocked: false; skipHistoryFetch: boolean };

/**
 * After Reset, incremental HTTP refresh stays disabled but explicit history
 * toolbar loads (hour / 30m / latest) re-enable history fetch.
 */
export function resolveSkipHistoryFetchForRefresh(
    skipHistoryFetch: boolean,
    request: LiveActivityRefreshRequest,
): SkipHistoryFetchResolution {
    if (!skipHistoryFetch) {
        return { blocked: false, skipHistoryFetch: false };
    }
    if (request === 'incremental') {
        return { blocked: true, skipHistoryFetch: true };
    }
    return { blocked: false, skipHistoryFetch: false };
}

/** Map a toolbar button id to the action it should trigger. */
export function resolveLiveActivityToolbarClick(buttonId: string): LiveActivityToolbarAction | null {
    switch (buttonId) {
        case LIVE_ACTIVITY_BUTTON_IDS.load30m:
            return { action: 'refresh', request: '30m' };
        case LIVE_ACTIVITY_BUTTON_IDS.refreshLatest:
            return { action: 'refresh', request: 'latest' };
        case LIVE_ACTIVITY_BUTTON_IDS.reset:
            return { action: 'reset' };
        case LIVE_ACTIVITY_BUTTON_IDS.lastKnownOnly:
            return { action: 'toggle-last-known-only' };
        case LIVE_ACTIVITY_BUTTON_IDS.pollDevices:
            return { action: 'poll-devices' };
        default:
            return null;
    }
}

export type LiveDeviceFilterAction =
    | { action: 'refresh-hour'; resetCursor: true }
    | { action: 'historic-trail' };

/** Device filter change in live mode reloads the last hour; historic mode reloads the trail. */
export function resolveLiveDeviceFilterChange(isLiveMode: boolean): LiveDeviceFilterAction {
    if (isLiveMode) {
        return { action: 'refresh-hour', resetCursor: true };
    }
    return { action: 'historic-trail' };
}

export interface LiveActivityResetPatch {
    eventCount: number;
    lastTimestamp: number;
    lastSeenLocationId: null;
    skipHistoryFetch: true;
    needsFitBounds: true;
    incrementalLocations: Record<string, never>;
    showLastKnownOnly: false;
}

/** State applied when the user clicks Reset in live activity. */
export function createLiveActivityResetPatch(nowUnix: number): LiveActivityResetPatch {
    return {
        eventCount: 0,
        lastTimestamp: nowUnix,
        lastSeenLocationId: null,
        skipHistoryFetch: true,
        needsFitBounds: true,
        incrementalLocations: {},
        showLastKnownOnly: false,
    };
}

export function toggleLastKnownOnlyFlag(current: boolean): boolean {
    return !current;
}

export type LiveLocationIngestPath = 'direct' | 'http-incremental' | 'ignored';

/**
 * After Reset, WebSocket locations are written directly to the log.
 * Otherwise HTTP incremental refresh owns ingest.
 */
export function resolveLiveLocationIngestPath(options: {
    isLiveMode: boolean;
    skipHistoryFetch: boolean;
    matchesDeviceFilter: boolean;
}): LiveLocationIngestPath {
    if (!options.isLiveMode || !options.matchesDeviceFilter) {
        return 'ignored';
    }
    if (options.skipHistoryFetch) {
        return 'direct';
    }
    return 'http-incremental';
}

export interface LocationWithDeviceName {
    device_name?: string;
}

export function shouldFilterLiveActivityByDevice(options: {
    selectedDevice?: string;
    skipHistoryFetch: boolean;
}): boolean {
    return Boolean(options.selectedDevice) && !options.skipHistoryFetch;
}

/**
 * Staff use an unfiltered last-known request; non-staff pass explicit device params
 * for devices visible to the logged-in user.
 */
export function resolveLastKnownQueryDeviceNames(options: {
    isStaff: boolean;
    visibleDeviceNames: readonly string[];
}): string[] | null {
    if (options.isStaff) {
        return null;
    }
    return [...options.visibleDeviceNames];
}

/** Build the last-known API URL; null queryDeviceNames means unfiltered (staff). */
export function buildLastKnownLocationsUrl(options: { queryDeviceNames: string[] | null }): string {
    if (options.queryDeviceNames === null) {
        return '/api/locations/last-known/';
    }
    const params = new URLSearchParams();
    for (const deviceName of options.queryDeviceNames) {
        params.append('device', deviceName);
    }
    const query = params.toString();
    return query ? `/api/locations/last-known/?${query}` : '/api/locations/last-known/';
}

export function filterLastKnownLocationsToMissingDevices<T extends LocationWithDeviceName>(
    locations: T[],
    renderedDeviceNames: Iterable<string>,
): T[] {
    const rendered = new Set(renderedDeviceNames);
    return locations.filter((location) => {
        const deviceName = location.device_name;
        return deviceName !== undefined && !rendered.has(deviceName);
    });
}

export interface LastKnownLogEntry {
    deviceName: string;
    locationKey: string;
    timestampUnix: number;
}

/** Newest log row per device — used for Last Known dimming as live rows arrive. */
export function lastKnownLocationKeysFromLogEntries(entries: LastKnownLogEntry[]): Set<string> {
    const locationKeys = new Set<string>();
    const seenDevices = new Set<string>();
    for (const entry of [...entries].sort((a, b) => b.timestampUnix - a.timestampUnix)) {
        if (!entry.deviceName || !entry.locationKey || seenDevices.has(entry.deviceName)) {
            continue;
        }
        seenDevices.add(entry.deviceName);
        locationKeys.add(entry.locationKey);
    }
    return locationKeys;
}

/**
 * Prefer keys derived from the current log so new websocket rows update highlighting.
 * Fall back to the last-known API snapshot only while the log is still empty.
 */
export function resolveLastKnownHighlightKeys(
    logKeys: Set<string>,
    apiSnapshot: Set<string> | null,
): Set<string> {
    if (logKeys.size > 0) {
        return logKeys;
    }
    return apiSnapshot ?? logKeys;
}

/** Highlight keys for Last Known dimming — matches main.ts locationKeyFor for API rows with id. */
export function buildLastKnownHighlightKeys<T extends LocationWithDeviceName & { id?: number | null }>(
    locations: T[],
): Set<string> {
    const keys = new Set<string>();
    for (const location of locations) {
        if (location.id !== undefined && location.id !== null) {
            keys.add(`id:${location.id}`);
        }
    }
    return keys;
}

export type LastKnownMergeStrategy = 'replace' | 'append';

/** Thrown when the last-known locations API returns a non-OK HTTP status or network failure. */
export class LastKnownFetchError extends Error {
    readonly status: number;

    constructor(status: number) {
        super(status > 0 ? `last-known fetch failed: ${status}` : 'last-known fetch failed: network error');
        this.name = 'LastKnownFetchError';
        this.status = status;
    }
}

/** Last-known API rows always replace the log — partial append left stale rows after Latest. */
export function resolveLastKnownMergeStrategy(_options: {
    skipHistoryFetch: boolean;
    renderedDeviceCount: number;
}): LastKnownMergeStrategy {
    return 'replace';
}

export interface LastKnownUiPlan<T extends LocationWithDeviceName & { id?: number | null }> {
    highlightKeys: Set<string> | null;
    mergeStrategy: LastKnownMergeStrategy | null;
    locations: T[];
}

/** Plan highlight keys and log merge after a last-known API response. */
export function planLastKnownUiUpdate<T extends LocationWithDeviceName & { id?: number | null }>(options: {
    locations: T[];
    skipHistoryFetch: boolean;
    renderedDeviceCount: number;
    renderedDeviceNames: Iterable<string>;
}): LastKnownUiPlan<T> {
    if (options.locations.length === 0) {
        return { highlightKeys: null, mergeStrategy: null, locations: [] };
    }
    const mergeStrategy = resolveLastKnownMergeStrategy({
        skipHistoryFetch: options.skipHistoryFetch,
        renderedDeviceCount: options.renderedDeviceCount,
    });
    const locationsToMerge =
        mergeStrategy === 'append'
            ? filterLastKnownLocationsToMissingDevices(options.locations, options.renderedDeviceNames)
            : options.locations;
    return {
        highlightKeys: buildLastKnownHighlightKeys(options.locations),
        mergeStrategy,
        locations: locationsToMerge,
    };
}

/** Whether a device should appear in live activity markers/trails/websocket ingest. */
export function devicePassesLiveActivityFilter(options: {
    deviceName: string;
    selectedDevice?: string;
    skipHistoryFetch: boolean;
    showLastKnownOnly?: boolean;
}): boolean {
    if (options.showLastKnownOnly) {
        return true;
    }
    if (
        !shouldFilterLiveActivityByDevice({
            selectedDevice: options.selectedDevice,
            skipHistoryFetch: options.skipHistoryFetch,
        })
    ) {
        return true;
    }
    return options.deviceName === options.selectedDevice;
}

export async function fetchAllDeviceNamesFromApi(options: {
    fetchFn: typeof fetch;
    devicesApiUrl?: string;
}): Promise<string[]> {
    const names: string[] = [];
    let url: string | null = options.devicesApiUrl ?? '/api/devices/';
    while (url) {
        const devicesResp = await options.fetchFn(url, { credentials: 'same-origin' });
        if (!devicesResp.ok) {
            throw new Error(`device list fetch failed: ${devicesResp.status}`);
        }
        const data: { next?: string | null } = await devicesResp.json();
        const devices = extractResultsList<{ device_name?: string }>(data);
        for (const device of devices) {
            if (device.device_name) {
                names.push(device.device_name);
            }
        }
        url = typeof data.next === 'string' && data.next.length > 0 ? data.next : null;
    }
    return names;
}

export async function fetchLastKnownLocations<T extends LocationWithDeviceName & { id?: number | null }>(options: {
    fetchFn: typeof fetch;
    isStaff: boolean;
    visibleDeviceNames: readonly string[];
    extractResults: (data: unknown) => T[];
    devicesApiUrl?: string;
}): Promise<T[]> {
    let queryDeviceNames = resolveLastKnownQueryDeviceNames({
        isStaff: options.isStaff,
        visibleDeviceNames: options.visibleDeviceNames,
    });

    if (queryDeviceNames !== null && queryDeviceNames.length === 0) {
        try {
            queryDeviceNames = await fetchAllDeviceNamesFromApi({
                fetchFn: options.fetchFn,
                devicesApiUrl: options.devicesApiUrl,
            });
        } catch (error) {
            console.warn('Last Known: device list fetch failed; trying unfiltered last-known', error);
            queryDeviceNames = null;
        }
    }

    const url = buildLastKnownLocationsUrl({ queryDeviceNames });
    try {
        const response = await options.fetchFn(url, { credentials: 'same-origin' });
        if (!response.ok) {
            console.warn('Last Known: fetch failed', response.status, url);
            throw new LastKnownFetchError(response.status);
        }
        const data = await response.json();
        return options.extractResults(data);
    } catch (error) {
        if (error instanceof LastKnownFetchError) {
            throw error;
        }
        console.warn('Last Known: fetch error', error);
        throw new LastKnownFetchError(0);
    }
}

export type LastKnownOnlyToggleEffect = { loadLocations: true } | { refitMap: true };

export function resolveLastKnownOnlyToggleEffect(
    isLiveMode: boolean,
    enabledAfterToggle: boolean,
): LastKnownOnlyToggleEffect {
    if (!enabledAfterToggle) {
        return { refitMap: true };
    }
    if (isLiveMode) {
        return { loadLocations: true };
    }
    return { refitMap: true };
}

export interface PollableMqttDevice {
    mqtt_topic_id: string;
    is_online: boolean;
}

export const REPORT_LOCATION_API = '/api/commands/report-location/';

/** Online devices with an MQTT topic can receive a reportLocation command. */
export function selectOnlineMqttDevices<T extends PollableMqttDevice>(devices: T[]): T[] {
    return devices.filter((device) => Boolean(device.mqtt_topic_id) && device.is_online);
}

export function buildReportLocationBody(device: PollableMqttDevice): { device_id: string } {
    return { device_id: device.mqtt_topic_id };
}

export type DevicePollSummary =
    | { kind: 'fetch-failed' }
    | { kind: 'no-devices' }
    | { kind: 'all-success'; count: number }
    | { kind: 'partial'; succeeded: number; total: number }
    | { kind: 'all-failed'; total: number };

export function summarizeDevicePollResults(succeeded: number, total: number): DevicePollSummary {
    if (total === 0) {
        return { kind: 'no-devices' };
    }
    if (succeeded === total) {
        return { kind: 'all-success', count: total };
    }
    if (succeeded > 0) {
        return { kind: 'partial', succeeded, total };
    }
    return { kind: 'all-failed', total };
}

export function devicePollSummaryMessage(summary: DevicePollSummary): string {
    switch (summary.kind) {
        case 'fetch-failed':
            return 'Could not load device list to poll.';
        case 'no-devices':
            return 'No online MQTT devices to poll.';
        case 'all-success': {
            const deviceWord = summary.count === 1 ? 'device' : 'devices';
            return `Location request sent to ${summary.count} ${deviceWord}.`;
        }
        case 'partial':
            return `Location request sent to ${summary.succeeded} of ${summary.total} devices; ${summary.total - summary.succeeded} failed.`;
        case 'all-failed':
            return 'Failed to send location request to any device.';
    }
}

export function devicePollSummaryToastType(summary: DevicePollSummary): 'success' | 'warning' | 'error' {
    switch (summary.kind) {
        case 'all-success':
            return 'success';
        case 'partial':
        case 'no-devices':
            return 'warning';
        case 'fetch-failed':
        case 'all-failed':
            return 'error';
    }
}

export async function pollOnlineMqttDevices(options: {
    fetchFn: typeof fetch;
    getCsrfToken: () => string;
    devices: PollableMqttDevice[];
}): Promise<{ succeeded: number; total: number }> {
    const { fetchFn, getCsrfToken, devices } = options;
    const mqttDevices = selectOnlineMqttDevices(devices);
    if (mqttDevices.length === 0) {
        return { succeeded: 0, total: 0 };
    }

    const csrfToken = getCsrfToken();
    const results = await Promise.allSettled(
        mqttDevices.map((device) =>
            fetchFn(REPORT_LOCATION_API, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify(buildReportLocationBody(device)),
            }),
        ),
    );

    const succeeded = results.filter(
        (result) => result.status === 'fulfilled' && result.value.ok,
    ).length;
    return { succeeded, total: mqttDevices.length };
}

export async function fetchAndPollOnlineMqttDevices(options: {
    fetchFn: typeof fetch;
    getCsrfToken: () => string;
    devicesApiUrl?: string;
}): Promise<DevicePollSummary> {
    const devicesResp = await options.fetchFn(options.devicesApiUrl ?? '/api/devices/');
    if (!devicesResp.ok) {
        return { kind: 'fetch-failed' };
    }

    const data = await devicesResp.json();
    const devices = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : [];
    const pollable = selectOnlineMqttDevices(devices as PollableMqttDevice[]);
    if (pollable.length === 0) {
        return { kind: 'no-devices' };
    }

    const { succeeded, total } = await pollOnlineMqttDevices({
        fetchFn: options.fetchFn,
        getCsrfToken: options.getCsrfToken,
        devices: pollable,
    });
    return summarizeDevicePollResults(succeeded, total);
}

export interface LiveActivityToolbarHandlers {
    onRefresh: (request: LiveActivityRefreshRequest) => void;
    onReset: () => void;
    onToggleLastKnownOnly: () => void;
    onPollDevices: () => void | Promise<void>;
}

function bindToolbarButton(
    buttonId: string,
    listener: () => void | Promise<void>,
): void {
    const button = document.getElementById(buttonId);
    if (button) {
        button.addEventListener('click', () => {
            void listener();
        });
    }
}

/** Wire live activity toolbar buttons to application handlers. */
export function attachLiveActivityToolbar(handlers: LiveActivityToolbarHandlers): void {
    bindToolbarButton(LIVE_ACTIVITY_BUTTON_IDS.load30m, () => {
        handlers.onRefresh('30m');
    });
    bindToolbarButton(LIVE_ACTIVITY_BUTTON_IDS.refreshLatest, () => {
        handlers.onRefresh('latest');
    });
    bindToolbarButton(LIVE_ACTIVITY_BUTTON_IDS.reset, () => {
        handlers.onReset();
    });
    bindToolbarButton(LIVE_ACTIVITY_BUTTON_IDS.lastKnownOnly, () => {
        handlers.onToggleLastKnownOnly();
    });
    bindToolbarButton(LIVE_ACTIVITY_BUTTON_IDS.pollDevices, () => handlers.onPollDevices());
}

/** Update an icon/label button while preserving `.btn-icon` / `.btn-label` spans. */
export function setIconLabelButton(button: HTMLButtonElement, icon: string, label: string): void {
    const iconSpan = button.querySelector<HTMLElement>('.btn-icon');
    const labelSpan = button.querySelector<HTMLElement>('.btn-label');
    if (iconSpan && labelSpan) {
        iconSpan.textContent = icon;
        labelSpan.textContent = label;
        return;
    }
    button.textContent = `${icon} ${label}`;
}
