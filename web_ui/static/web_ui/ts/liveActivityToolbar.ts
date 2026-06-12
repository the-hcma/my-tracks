/**
 * Live activity toolbar actions (button clicks and related UI behavior).
 */

import type { LiveActivityRefreshRequest } from './liveActivity';

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

export interface LastKnownDeviceRow {
    device_id: string;
    name: string;
    owner_username?: string;
}

export interface LastKnownDeviceTarget {
    device_id: string;
    display_name: string;
}

/** Match LocationSerializer device_name: owner/label where label is name or device_id. */
export function formatDeviceDisplayName(device: LastKnownDeviceRow): string {
    const trimmedName = device.name?.trim() ?? '';
    const label = trimmedName && !trimmedName.startsWith('Device ') ? trimmedName : device.device_id;
    return device.owner_username ? `${device.owner_username}/${label}` : label;
}

/** Match LocationSerializer device_id_display: owner/device_id or plain device_id. */
export function buildDeviceIdDisplay(device: LastKnownDeviceRow): string {
    return device.owner_username ? `${device.owner_username}/${device.device_id}` : device.device_id;
}

export function buildLastKnownDeviceTargets(
    devices: LastKnownDeviceRow[],
    selectedDevice?: string,
): LastKnownDeviceTarget[] {
    return devices
        .map((device) => ({
            device_id: device.device_id,
            display_name: formatDeviceDisplayName(device),
        }))
        .filter((target) => !selectedDevice || target.display_name === selectedDevice);
}

/**
 * Build Last Known fetch targets. After reset, ignore the device selector and
 * use every device returned by /api/devices/ (owned, shared, or all for staff).
 */
export function buildLastKnownFetchTargets(
    devices: LastKnownDeviceRow[],
    options: { selectedDevice?: string; skipHistoryFetch: boolean },
): LastKnownDeviceTarget[] {
    const selectedDevice = options.skipHistoryFetch ? undefined : options.selectedDevice;
    return buildLastKnownDeviceTargets(devices, selectedDevice);
}

export function findDevicesMissingFromActivityLog(
    targets: LastKnownDeviceTarget[],
    renderedDeviceNames: Iterable<string>,
): LastKnownDeviceTarget[] {
    const rendered = new Set(renderedDeviceNames);
    return targets.filter((target) => !rendered.has(target.display_name));
}

/**
 * After reset, fetch the latest location for every visible device even if the
 * log already has organic websocket rows for some of them.
 */
export function selectLastKnownDevicesToFetch(
    targets: LastKnownDeviceTarget[],
    renderedDeviceNames: Iterable<string>,
    options: { skipHistoryFetch: boolean },
): LastKnownDeviceTarget[] {
    if (options.skipHistoryFetch) {
        return targets;
    }
    return findDevicesMissingFromActivityLog(targets, renderedDeviceNames);
}

export function buildDeviceLatestLocationUrl(deviceId: string): string {
    return `/api/devices/${encodeURIComponent(deviceId)}/locations/?limit=1`;
}

export function buildLastKnownBulkLocationsUrl(): string {
    return '/api/locations/?ordering=-timestamp&limit=500';
}

export type LastKnownLoadPlan = 'bulk-all-visible' | 'fill-missing-per-device';

/**
 * Post-reset Last Known loads use the bulk locations API (like Latest).
 * An empty activity log also uses bulk fetch. Otherwise fetch only missing devices.
 */
export function resolveLastKnownLoadPlan(options: {
    skipHistoryFetch: boolean;
    targets: LastKnownDeviceTarget[];
    renderedDeviceNames: Iterable<string>;
}): LastKnownLoadPlan {
    if (options.skipHistoryFetch) {
        return 'bulk-all-visible';
    }
    const renderedCount = [...options.renderedDeviceNames].length;
    if (renderedCount === 0) {
        return 'bulk-all-visible';
    }
    return 'fill-missing-per-device';
}

export interface LocationWithDeviceName {
    device_name?: string;
    device_id_display?: string;
}

/** True when a location row belongs to the given device row. */
export function locationMatchesDevice(
    location: LocationWithDeviceName,
    device: LastKnownDeviceRow,
): boolean {
    const locName = location.device_name?.trim();
    const locIdDisplay = location.device_id_display?.trim();
    if (!locName && !locIdDisplay) {
        return false;
    }
    const expectedName = formatDeviceDisplayName(device);
    const expectedIdDisplay = buildDeviceIdDisplay(device);
    const identifiers = [locName, locIdDisplay].filter(Boolean) as string[];
    return identifiers.some((id) => id === expectedName || id === expectedIdDisplay);
}

/** From API rows ordered by -timestamp, pick the newest row for each device. */
export function pickLatestLocationForDevices<T extends LocationWithDeviceName>(
    locations: T[],
    devices: LastKnownDeviceRow[],
): T[] {
    const picked: T[] = [];
    for (const device of devices) {
        const match = locations.find((location) => locationMatchesDevice(location, device));
        if (match) {
            picked.push(match);
        }
    }
    return picked;
}

/** From API rows ordered by -timestamp, keep the first row per visible device name. */
export function pickLatestLocationPerDevice<T extends LocationWithDeviceName>(
    locations: T[],
    visibleDeviceNames: Iterable<string>,
): T[] {
    const visible = new Set(visibleDeviceNames);
    const seen = new Set<string>();
    const picked: T[] = [];
    for (const location of locations) {
        const deviceName = location.device_name;
        if (!deviceName || !visible.has(deviceName) || seen.has(deviceName)) {
            continue;
        }
        seen.add(deviceName);
        picked.push(location);
    }
    return picked;
}

function devicesMissingLatestLocations<T extends LocationWithDeviceName>(
    devices: LastKnownDeviceRow[],
    locations: T[],
): LastKnownDeviceTarget[] {
    return buildLastKnownDeviceTargets(devices).filter((target) => {
        const device = devices.find((row) => row.device_id === target.device_id);
        return device && !locations.some((location) => locationMatchesDevice(location, device));
    });
}

export async function fetchLatestLocationsForVisibleDevices<T extends LocationWithDeviceName>(options: {
    fetchFn: typeof fetch;
    devices: LastKnownDeviceRow[];
    extractResults: (data: unknown) => T[];
    locationsApiUrl?: string;
}): Promise<T[]> {
    if (options.devices.length === 0) {
        return [];
    }

    let bulkLocations: T[] = [];
    try {
        const response = await options.fetchFn(options.locationsApiUrl ?? buildLastKnownBulkLocationsUrl());
        if (response.ok) {
            const data = await response.json();
            bulkLocations = options.extractResults(data);
        }
    } catch {
        // fall through to per-device fallback
    }

    const picked = pickLatestLocationForDevices(bulkLocations, options.devices);
    const missingDevices = devicesMissingLatestLocations(options.devices, picked);
    if (missingDevices.length === 0) {
        return picked;
    }

    const fallbackLocations = await fetchMissingLastKnownLocations<T>({
        fetchFn: options.fetchFn,
        missingDevices,
        extractResults: options.extractResults,
    });
    return [...picked, ...fallbackLocations];
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

export async function fetchMissingLastKnownLocations<T>(options: {
    fetchFn: typeof fetch;
    missingDevices: LastKnownDeviceTarget[];
    extractResults: (data: unknown) => T[];
}): Promise<T[]> {
    const locations = await Promise.all(
        options.missingDevices.map(async (device) => {
            try {
                const response = await options.fetchFn(buildDeviceLatestLocationUrl(device.device_id));
                if (!response.ok) {
                    return null;
                }
                const data = await response.json();
                return options.extractResults(data)[0] ?? null;
            } catch {
                return null;
            }
        }),
    );
    return locations.filter((location) => location !== null) as T[];
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
