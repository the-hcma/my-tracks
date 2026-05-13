/**
 * My Tracks - Main TypeScript application.
 *
 * Frontend for the OwnTracks backend server.
 */

import * as L from 'leaflet';
import noUiSlider, { type API as NoUiSliderAPI } from 'nouislider';
import 'nouislider/dist/nouislider.css';
import { getPreferredTheme, setTheme, toggleTheme } from './theme';
import { dateAndMinutesToTimestamps, extractResultsList, formatLatLonCoordinate, formatLatLonPair, formatMinutesAsTime, getTodayDateString, selectStablePaletteColor } from './utils';

// Configuration passed from Django template
interface MyTracksConfig {
    hostname: string;
    localIp: string;
    collapsePrecision: number;
    /** When true, exclude poor-GPS points from map polylines only (not the activity log). */
    locationAccuracyFilterEnabled?: boolean;
    /**
     * Minimum accuracy (meters): use a fix only when reported horizontal accuracy is unknown or
     * ≤ this value (discard when accuracy is greater than this).
     */
    locationAccuracyMinimumM?: number;
}

// Extend Window interface for our config
declare global {
    interface Window {
        MY_TRACKS_CONFIG: MyTracksConfig;
    }
}

const config = window.MY_TRACKS_CONFIG;

/** Whether a fix may contribute to live/historic trail polylines (server geofence uses DB settings). */
function locationPassesAccuracyForTrail(loc: TrackLocation): boolean {
    if (!config.locationAccuracyFilterEnabled) {
        return true;
    }
    const minimumAccuracyM = config.locationAccuracyMinimumM ?? 100;
    if (loc.accuracy === undefined || loc.accuracy === null) {
        return true;
    }
    const acc = typeof loc.accuracy === 'string' ? parseFloat(loc.accuracy) : Number(loc.accuracy);
    if (Number.isNaN(acc)) {
        return true;
    }
    return acc <= minimumAccuracyM;
}

/** Row is still listed in the activity log but excluded from map trails when the filter is on. */
function locationExcludedFromTrailByAccuracy(loc: TrackLocation): boolean {
    return Boolean(config.locationAccuracyFilterEnabled && !locationPassesAccuracyForTrail(loc));
}

function decorateActivityLogEntryForAccuracy(entry: HTMLElement, loc: TrackLocation): void {
    if (!locationExcludedFromTrailByAccuracy(loc)) {
        return;
    }
    entry.classList.add('log-entry-low-accuracy');
    const minM = config.locationAccuracyMinimumM ?? 100;
    const accRaw = loc.accuracy;
    const accStr = accRaw === undefined || accRaw === null ? '?' : String(accRaw);
    entry.title =
        `Omitted from map trail: accuracy ${accStr}m exceeds minimum (${minM}m). Still shown in this log.`;
    const pill = document.createElement('span');
    pill.className = 'log-low-accuracy-pill';
    pill.textContent = 'Low GPS accuracy';
    entry.appendChild(pill);
}

function locationTimestampUnix(loc: TrackLocation): number {
    return loc.timestamp_unix ?? 0;
}

/** Sort newest first (for live activity log and API-aligned lists). */
function compareLocationsByTimestampDesc(a: TrackLocation, b: TrackLocation): number {
    return locationTimestampUnix(b) - locationTimestampUnix(a);
}

/**
 * Insert a log row in strict timestamp order (newest at top).
 * Finds the first existing row strictly older than tsUnix and inserts before it.
 */
function insertLiveLogEntryInTimestampOrder(container: HTMLElement, entry: HTMLElement, tsUnix: number): void {
    entry.setAttribute('data-ts', String(tsUnix));
    for (const child of [...container.children]) {
        if (!(child instanceof HTMLElement)) continue;
        if (child.id === 'loading') continue;
        const raw = child.getAttribute('data-ts');
        if (raw === null) continue;
        const cts = Number(raw);
        if (!Number.isFinite(cts)) continue;
        if (cts < tsUnix) {
            container.insertBefore(entry, child);
            return;
        }
    }
    container.appendChild(entry);
}

// ============================================================================
// Type Definitions
// ============================================================================

/** Location data from the API */
interface TrackLocation {
    id?: number;
    device_name?: string;
    device_id_display?: string;
    tid_display?: string;
    latitude: string | number;
    longitude: string | number;
    accuracy?: number;
    altitude?: number;
    velocity?: number;
    battery_level?: number;
    connection_type?: string;
    ip_address?: string;
    received_via?: string;
    timestamp_unix?: number;
    /** Internal: number of collapsed waypoints at this location */
    _collapsedCount?: number;
}

/** API response for locations list */
interface LocationsApiResponse {
    results: TrackLocation[];
    count?: number;
    next?: string | null;
    previous?: string | null;
}

/** Trail elements displayed on the map */
interface TrailElements {
    polyline: L.Polyline | null;
    markers: L.Marker[];
}

type LocationMarker = L.Marker | L.CircleMarker;
type SelectableLocationMarker = LocationMarker & {
    _myTracksLocationKey?: string;
    _myTracksSelectionHandlerAttached?: boolean;
};

interface RegisteredLocationMarker {
    marker: LocationMarker;
    kind: 'device' | 'waypoint';
}

/** Saved UI state for persistence */
interface UIState {
    isLiveMode: boolean;
    selectedDevice: string;
    timeRangeHours: number;
    trailResolution: number;
    showLastKnownOnly?: boolean;
    historicDate?: string;
    historicStartMinutes?: number;
    historicEndMinutes?: number;
    mobileLayoutMode?: MobileLayoutMode;
}

/**
 * How the split between the map and the activity log is rendered on
 * phone-sized viewports. Only takes effect inside the mobile media query —
 * desktop continues to use the drag-resize handle.
 */
type MobileLayoutMode = 'map-only' | 'split' | 'table-only';

/** Saved map position for persistence */
interface MapPosition {
    lat: number;
    lng: number;
    zoom: number;
}

/** Geocoding queue item */
interface GeocodingQueueItem {
    lat: number;
    lon: number;
    resolve: (address: string) => void;
    reject: (error: Error) => void;
}

/** Network info response from server */
interface NetworkInfo {
    hostname: string;
    local_ip: string;
    local_ips: string[];
    port: number;
}

/** Device info from the API */
interface DeviceInfo {
    device_id: string;
    name: string;
    owner_username?: string;
}

/** WebSocket message from server */
interface WebSocketMessage {
    type: string;
    data?: TrackLocation;
    server_startup?: string;
}

// ============================================================================
// State Variables
// ============================================================================

/** Last bulk history the user asked for; tab focus reload uses this. */
type LiveActivityLoadKind = 'hour' | '30m' | 'latest';
let liveActivityLoadKind: LiveActivityLoadKind = 'hour';

let lastTimestamp: number | null = null;
let eventCount = 0;
let map: L.Map | null = null;
let deviceMarkers: Record<string, L.CircleMarker> = {};
let deviceTrails: Record<string, TrailElements> = {};
const locationMarkersByKey = new Map<string, RegisteredLocationMarker[]>();
let selectedLocationKey: string | null = null;
let showLastKnownOnly = false;
let mobileLayoutMode: MobileLayoutMode = 'split';
const devices = new Set<string>();
let selectedDevice = '';
let timeRangeHours = 2;
let trailResolution = 0; // 0 = precise (all points), 360 = coarse (~10/hour)
let isLiveMode = true; // Track current mode
let needsFitBounds = true; // Only fit bounds on initial trail load
let isRestoringState = false; // Flag to prevent saving during restore
let skipHistoryFetch = false; // Flag to skip history fetch after reset (only show new incoming data)

// Historic date+time range state
let historicDate = ''; // YYYY-MM-DD, defaults to today
let historicStartMinutes = 0; // Minutes from midnight (0 = 00:00)
let historicEndMinutes = 1439; // Minutes from midnight (1439 = 23:59)
let timeSliderApi: NoUiSliderAPI | null = null;

// Device color palette - ordered for MAXIMUM visual difference between adjacent colors
// First colors should be most distinct from each other (used when few devices)
const deviceColors: string[] = [
    '#c82333', // Red - most distinct primary
    '#0056b3', // Blue - opposite of red on color wheel
    '#28a745', // Green - distinct from red and blue
    '#e65100', // Orange - warm, distinct from blue/green
    '#6f42c1', // Purple - distinct from orange/green
    '#00bcd4', // Cyan - distinct from purple/orange
    '#d63384', // Magenta/Pink - distinct from cyan/green
    '#795548', // Brown - distinct from all bright colors
    '#00695c', // Teal - distinct from brown/magenta
    '#ff9800', // Amber - distinct from teal/brown
];
let deviceColorMap: Record<string, string> = {}; // Cache: device name -> stable color

// Cache for reverse geocoding results
const geocodeCache = new Map<string, string>();
const geocodingQueue: GeocodingQueueItem[] = [];
let isProcessingQueue = false;
const GEOCODING_DELAY = 1000; // 1 second delay between requests

// Store pending restore state for after devices are loaded
let pendingRestoreState: UIState | null = null;

// WebSocket connection state
let ws: WebSocket | null = null;
let wsReconnectAttempts = 0;
const maxReconnectAttempts = 5;
const reconnectDelay = 3000;
let serverStartupTimestamp: string | null = null; // Track server version
let lastWebSocketMessageAtMs: number | null = null;

// Track last known IP to detect changes
let lastKnownIP: string = config.localIp;

// Fallback polling for when WebSocket is not available
let pollingInterval: ReturnType<typeof setInterval> | null = null;

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Reset device color assignments.
 * Call this when switching views to ensure optimal color distribution.
 */
function resetDeviceColors(): void {
    deviceColorMap = {};
}

/**
 * Show device color legend when viewing multiple devices.
 * @param deviceNames - Array of device names to show in legend
 */
function showDeviceLegend(deviceNames: string[]): void {
    const legend = document.getElementById('device-legend');
    if (!legend) return;

    const validNames = Array.from(
        new Set(deviceNames.filter(name => name && name.trim() !== '')),
    ).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));

    // Only show legend when multiple devices can be visible on the map.
    if (validNames.length < 2) {
        legend.classList.add('hidden');
        return;
    }

    legend.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'device-legend-title';
    title.textContent = 'Devices';
    legend.appendChild(title);

    validNames.forEach((name) => {
        const color = getDeviceColor(name);
        const item = document.createElement('div');
        item.className = 'device-legend-item';

        const swatch = document.createElement('div');
        swatch.className = 'device-legend-color';
        swatch.style.backgroundColor = color;
        item.appendChild(swatch);

        const label = document.createElement('span');
        label.className = 'device-legend-name';
        label.textContent = name;
        item.appendChild(label);

        legend.appendChild(item);
    });

    legend.classList.remove('hidden');
}

/**
 * Hide the device color legend.
 */
function hideDeviceLegend(): void {
    const legend = document.getElementById('device-legend');
    if (legend) {
        legend.classList.add('hidden');
    }
}

function drawnMapDeviceNames(): string[] {
    return Array.from(
        new Set([
            ...Object.keys(deviceMarkers),
            ...Object.entries(deviceTrails)
                .filter(([, trail]) => Boolean(trail.polyline || trail.markers.length > 0))
                .map(([deviceName]) => deviceName),
        ]),
    );
}

function updateDeviceLegendVisibility(): void {
    if (selectedDevice) {
        hideDeviceLegend();
        return;
    }
    showDeviceLegend(drawnMapDeviceNames());
}

/**
 * Get color for a device - assigns colors sequentially for maximum visual difference.
 * Colors are selected deterministically from the palette based on the device identifier so a
 * given device always has the same color, regardless of event arrival order.
 * @param deviceName - Name of the device
 * @returns Hex color string
 */
function getDeviceColor(deviceName: string): string {
    if (!deviceColorMap[deviceName]) {
        deviceColorMap[deviceName] = selectStablePaletteColor(deviceName, deviceColors);
    }
    return deviceColorMap[deviceName];
}

/**
 * Format a Unix timestamp for display.
 * @param timestamp - Unix timestamp in seconds
 * @param includeDate - Whether to include the date
 * @returns Formatted time string
 */
function formatTime(timestamp: number, includeDate = false): string {
    const date = new Date(timestamp * 1000);
    const today = new Date();
    const isToday = date.toDateString() === today.toDateString();

    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    const tz = date.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop() ?? '';
    const timeStr = `${hours}:${minutes}:${seconds} ${tz}`;

    // Include date if requested or if not today
    if (includeDate || !isToday) {
        const month = date.toLocaleDateString('en-US', { month: 'short' });
        const day = date.getDate();
        return `${month} ${day} ${timeStr}`;
    }
    return timeStr;
}

/**
 * Format a date for title display.
 * @param date - Date object
 * @returns Formatted date string
 */
function formatDateForTitle(date: Date): string {
    const options: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

/**
 * Get a date range text for display.
 * @param hours - Number of hours to look back
 * @returns Date range string
 */
function getDateRangeText(hours: number): string {
    const now = new Date();
    const startDate = new Date(now.getTime() - hours * 60 * 60 * 1000);

    // If same day, just show one date
    if (startDate.toDateString() === now.toDateString()) {
        return formatDateForTitle(now);
    }
    // Otherwise show range
    return `${formatDateForTitle(startDate)} - ${formatDateForTitle(now)}`;
}

/**
 * Get the display text for historic date + time range.
 * @returns Formatted string like "Thu, Feb 20 · 08:00 – 17:30"
 */
function getHistoricRangeText(): string {
    const dateStr = historicDate || getTodayDateString();
    const [year, month, day] = dateStr.split('-').map(Number);
    const date = new Date(year, month - 1, day);
    const dateText = formatDateForTitle(date);
    const startTime = formatMinutesAsTime(historicStartMinutes);
    const endTime = formatMinutesAsTime(historicEndMinutes);
    return `${dateText} · ${startTime} – ${endTime}`;
}

/**
 * Compute start and end Unix timestamps from historic date + time range.
 * @returns [startTimestamp, endTimestamp] in seconds
 */
function getHistoricTimestamps(): [number, number] {
    return dateAndMinutesToTimestamps(
        historicDate || getTodayDateString(),
        historicStartMinutes,
        historicEndMinutes,
    );
}

/**
 * Update the time slider label text.
 */
function updateTimeSliderLabel(): void {
    const label = document.getElementById('time-slider-label');
    if (label) {
        const startTime = formatMinutesAsTime(historicStartMinutes);
        const endTime = formatMinutesAsTime(historicEndMinutes);
        label.textContent = `${startTime} – ${endTime}`;
    }
}

// ============================================================================
// Toast Notifications
// ============================================================================

/** Visual style of a toast message. */
type ToastType = 'info' | 'success' | 'warning' | 'error';

/** Optional knobs for {@link showToast}. */
interface ToastOptions {
    /** Auto-dismiss delay in milliseconds. Defaults to 4000 (4s). */
    duration?: number;
    /** Style variant. Defaults to `info`. */
    type?: ToastType;
}

/**
 * Display a transient toast notification anchored at the top of the viewport.
 * Toasts stack vertically and fade out automatically after `duration` ms; the
 * user can dismiss earlier via the close button.
 */
function showToast(message: string, options: ToastOptions = {}): void {
    const container = document.getElementById('toast-container');
    if (!container) {
        return;
    }
    const duration = options.duration ?? 4000;
    const type = options.type ?? 'info';

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

    const messageEl = document.createElement('span');
    messageEl.className = 'toast-message';
    messageEl.textContent = message;
    toast.appendChild(messageEl);

    const dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.className = 'toast-dismiss';
    dismissBtn.setAttribute('aria-label', 'Dismiss notification');
    dismissBtn.textContent = '×';
    toast.appendChild(dismissBtn);

    container.appendChild(toast);
    requestAnimationFrame(() => {
        toast.classList.add('toast-visible');
    });

    let timer: ReturnType<typeof setTimeout> | null = null;
    let dismissed = false;

    function dismiss(): void {
        if (dismissed) {
            return;
        }
        dismissed = true;
        if (timer !== null) {
            clearTimeout(timer);
            timer = null;
        }
        toast.classList.remove('toast-visible');
        toast.classList.add('toast-leaving');
        const cleanup = (): void => toast.remove();
        toast.addEventListener('transitionend', cleanup, { once: true });
        // Fallback if no transition fires (e.g. element already detached).
        setTimeout(cleanup, 400);
    }

    dismissBtn.addEventListener('click', dismiss);
    timer = setTimeout(dismiss, duration);
}

// ============================================================================
// Location Selection
// ============================================================================

function locationKeyFor(location: TrackLocation): string {
    if (location.id !== undefined && location.id !== null) {
        return `id:${location.id}`;
    }

    const device = location.device_name || 'Unknown';
    const timestamp = locationTimestampUnix(location);
    const lat = formatLatLonCoordinate(location.latitude);
    const lon = formatLatLonCoordinate(location.longitude);
    return `device:${device}|ts:${timestamp}|lat:${lat}|lon:${lon}`;
}

function unregisterLocationMarker(marker: LocationMarker): void {
    locationMarkersByKey.forEach((registeredMarkers, key) => {
        const remainingMarkers = registeredMarkers.filter((registeredMarker) => registeredMarker.marker !== marker);
        if (remainingMarkers.length === 0) {
            locationMarkersByKey.delete(key);
        } else {
            locationMarkersByKey.set(key, remainingMarkers);
        }
    });
}

function clearRegisteredLocationMarkers(): void {
    locationMarkersByKey.clear();
    selectedLocationKey = null;
}

function registeredMarkerLatLng(marker: LocationMarker): L.LatLng {
    return marker.getLatLng();
}

function applyMarkerSelectionStyles(
    registeredMarker: RegisteredLocationMarker,
    isSelected: boolean,
    hasSelection: boolean,
    isFilteredByLastKnown = false,
): void {
    const isDimmed = (hasSelection && !isSelected) || (isFilteredByLastKnown && !isSelected);
    const { marker, kind } = registeredMarker;

    if (marker instanceof L.CircleMarker) {
        marker.setRadius(isSelected ? 14 : 10);
        marker.setStyle({
            opacity: isDimmed ? 0.25 : 1,
            fillOpacity: isDimmed ? 0.2 : 0.9,
            weight: isSelected ? 4 : 2,
        });
    } else {
        marker.setOpacity(isDimmed ? 0.25 : 1);
    }

    const element = marker.getElement();
    element?.classList.toggle('location-marker-selected', isSelected);
    element?.classList.toggle('location-marker-dimmed', isDimmed);
    element?.classList.toggle('location-device-marker-selected', isSelected && kind === 'device');
}

function applyLocationSelection(): void {
    const hasSelection = selectedLocationKey !== null;
    const lastKnownLocationKeys = showLastKnownOnly ? getLastKnownLocationKeysByDevice() : null;
    document.querySelectorAll<HTMLElement>('.log-entry[data-location-key]').forEach((entry) => {
        const isSelected = entry.dataset.locationKey === selectedLocationKey;
        const isOlderThanLastKnown =
            lastKnownLocationKeys !== null && !lastKnownLocationKeys.has(entry.dataset.locationKey ?? '');
        entry.classList.toggle('log-entry-selected', isSelected);
        entry.classList.toggle('log-entry-dimmed', (hasSelection && !isSelected) || (isOlderThanLastKnown && !isSelected));
        entry.classList.toggle('log-entry-last-known-dimmed', isOlderThanLastKnown);
    });

    locationMarkersByKey.forEach((registeredMarkers, key) => {
        const isSelected = key === selectedLocationKey;
        const isOlderThanLastKnown = lastKnownLocationKeys !== null && !lastKnownLocationKeys.has(key);
        registeredMarkers.forEach((registeredMarker) => {
            applyMarkerSelectionStyles(registeredMarker, isSelected, hasSelection, isOlderThanLastKnown);
        });
    });
}

function focusLocationMarker(locationKey: string, openPopup: boolean): void {
    const registeredMarkers = locationMarkersByKey.get(locationKey);
    const registeredMarker = registeredMarkers?.[0];
    if (!registeredMarker || !map) {
        return;
    }

    const { marker } = registeredMarker;
    map.panTo(registeredMarkerLatLng(marker));
    if (openPopup) {
        marker.openPopup();
    }
}

function selectLocation(
    locationKey: string,
    options: { scrollRow?: boolean; focusMarker?: boolean; openPopup?: boolean } = {},
): void {
    if (selectedLocationKey === locationKey) {
        clearLocationSelection();
        return;
    }

    selectedLocationKey = locationKey;
    applyLocationSelection();

    if (options.scrollRow) {
        const row = document.querySelector<HTMLElement>(`.log-entry[data-location-key="${CSS.escape(locationKey)}"]`);
        row?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    if (options.focusMarker) {
        focusLocationMarker(locationKey, options.openPopup ?? true);
    }
}

/**
 * Clear the active location selection, restore default styles and close any
 * popup currently anchored to the previously-selected marker.
 */
function clearLocationSelection(): void {
    if (selectedLocationKey === null) {
        return;
    }
    selectedLocationKey = null;
    applyLocationSelection();
    map?.closePopup();
}

function attachLocationSelectionToEntry(entry: HTMLElement, location: TrackLocation): void {
    const locationKey = locationKeyFor(location);
    entry.dataset.locationKey = locationKey;
    entry.dataset.deviceName = location.device_name || selectedDevice || 'Unknown';
    entry.dataset.ts = String(locationTimestampUnix(location));
    entry.tabIndex = 0;
    entry.setAttribute('role', 'button');
    entry.setAttribute('aria-label', 'Toggle highlight for this location on the map');
    entry.addEventListener('click', () => {
        selectLocation(locationKey, { focusMarker: true, openPopup: true });
    });
    entry.addEventListener('keydown', (event: KeyboardEvent) => {
        if (event.key !== 'Enter' && event.key !== ' ') {
            return;
        }
        event.preventDefault();
        selectLocation(locationKey, { focusMarker: true, openPopup: true });
    });
}

function registerLocationMarker(location: TrackLocation, marker: LocationMarker, kind: RegisteredLocationMarker['kind']): void {
    unregisterLocationMarker(marker);
    const locationKey = locationKeyFor(location);
    const registeredMarkers = locationMarkersByKey.get(locationKey) ?? [];
    registeredMarkers.push({ marker, kind });
    locationMarkersByKey.set(locationKey, registeredMarkers);
    const selectableMarker = marker as SelectableLocationMarker;
    selectableMarker._myTracksLocationKey = locationKey;
    if (!selectableMarker._myTracksSelectionHandlerAttached) {
        marker.on('click', () => {
            const currentLocationKey = selectableMarker._myTracksLocationKey;
            if (currentLocationKey) {
                selectLocation(currentLocationKey, { scrollRow: true });
            }
        });
        selectableMarker._myTracksSelectionHandlerAttached = true;
    }
    applyLocationSelection();
}

function removeTrailElements(trail: TrailElements): void {
    if (trail.polyline) {
        trail.polyline.remove();
    }
    trail.markers.forEach((marker) => {
        unregisterLocationMarker(marker);
        marker.remove();
    });
}

function removeAllDeviceMarkers(): void {
    Object.values(deviceMarkers).forEach((marker) => {
        unregisterLocationMarker(marker);
        marker.remove();
    });
    deviceMarkers = {};
    updateDeviceLegendVisibility();
}

function removeAllTrails(): void {
    Object.values(deviceTrails).forEach(removeTrailElements);
    deviceTrails = {};
    updateDeviceLegendVisibility();
}

/**
 * Re-center and zoom the map so every device's last-known marker is visible
 * with a comfortable margin and street-level detail (capped by `maxZoom`).
 * Silently no-ops when the map or marker set is unavailable.
 */
function fitMapToLastKnownLocations(): void {
    if (!map) {
        return;
    }
    const keys = getLastKnownLocationKeysByDevice();
    if (keys.size === 0) {
        return;
    }
    const latLngs: L.LatLng[] = [];
    keys.forEach((key) => {
        const registered = locationMarkersByKey.get(key);
        if (!registered) {
            return;
        }
        registered.forEach((entry) => {
            latLngs.push(registeredMarkerLatLng(entry.marker));
        });
    });
    if (latLngs.length === 0) {
        return;
    }
    const bounds = L.latLngBounds(latLngs);
    map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
}

function getLastKnownLocationKeysByDevice(): Set<string> {
    const locationKeys = new Set<string>();
    const seenDevices = new Set<string>();
    const entries = [...document.querySelectorAll<HTMLElement>('.log-entry[data-location-key][data-device-name]')];

    entries
        .sort((a, b) => Number(b.dataset.ts ?? 0) - Number(a.dataset.ts ?? 0))
        .forEach((entry) => {
            const deviceName = entry.dataset.deviceName;
            const locationKey = entry.dataset.locationKey;
            if (!deviceName || !locationKey || seenDevices.has(deviceName)) {
                return;
            }
            seenDevices.add(deviceName);
            locationKeys.add(locationKey);
        });

    return locationKeys;
}

function updateLastKnownOnlyButton(): void {
    const button = document.getElementById('last-known-only-button');
    if (!button) {
        return;
    }
    button.classList.toggle('active', showLastKnownOnly);
    button.setAttribute('aria-pressed', String(showLastKnownOnly));
}

function toggleLastKnownOnly(): void {
    showLastKnownOnly = !showLastKnownOnly;
    updateLastKnownOnlyButton();
    applyLocationSelection();
    saveUIState();

    if (!showLastKnownOnly) {
        return;
    }
    if (isLiveMode) {
        // Live mode needs to fetch the last known location for any device not
        // already in the activity log; the fit happens once that resolves.
        void ensureLastKnownLocationsLoaded();
    } else {
        fitMapToLastKnownLocations();
    }
}

/**
 * Ensure every device visible to the logged-in user has its latest known
 * location present in the live activity log + map. The "Last Known Only"
 * toggle is a no-op when the dashboard has nothing to dim — this guarantees
 * there is always something to highlight when the user activates it.
 *
 * - Runs only in live mode (historic mode operates on a fixed trail).
 * - Honors the active device filter (selectedDevice) when set.
 * - Idempotent: skips devices that already have a row, and addLogEntry
 *   dedupes by location id when called concurrently.
 */
async function ensureLastKnownLocationsLoaded(): Promise<void> {
    if (!isLiveMode) {
        return;
    }

    const button = document.getElementById('last-known-only-button') as HTMLButtonElement | null;
    if (button) {
        button.disabled = true;
    }

    try {
        const devicesResp = await fetch('/api/devices/');
        if (!devicesResp.ok) {
            console.warn('Last Known Only: failed to fetch devices', devicesResp.status);
            return;
        }
        const devicesData = await devicesResp.json();
        const deviceList = extractResultsList<DeviceInfo>(devicesData);

        const targets = deviceList
            .map((d) => ({
                device_id: d.device_id,
                display_name: d.owner_username ? `${d.owner_username}/${d.device_id}` : d.device_id,
            }))
            .filter((d) => !selectedDevice || d.display_name === selectedDevice);

        const renderedDeviceNames = new Set<string>();
        document.querySelectorAll<HTMLElement>('.log-entry[data-device-name]').forEach((entry) => {
            const name = entry.dataset.deviceName;
            if (name) {
                renderedDeviceNames.add(name);
            }
        });

        const missing = targets.filter((d) => !renderedDeviceNames.has(d.display_name));
        if (missing.length === 0) {
            return;
        }

        const latestPerDevice = await Promise.all(
            missing.map(async (device) => {
                try {
                    const url = `/api/devices/${encodeURIComponent(device.device_id)}/locations/?limit=1`;
                    const resp = await fetch(url);
                    if (!resp.ok) {
                        return null;
                    }
                    const data = await resp.json();
                    return extractResultsList<TrackLocation>(data)[0] ?? null;
                } catch (error) {
                    console.error(`Last Known Only: failed to fetch latest location for ${device.display_name}`, error);
                    return null;
                }
            }),
        );

        latestPerDevice.forEach((location) => {
            if (location) {
                addLogEntry(location, /* skipScroll */ true);
            }
        });

        applyLocationSelection();
    } catch (error) {
        console.error('Last Known Only: unexpected error while fetching device locations', error);
    } finally {
        if (button) {
            button.disabled = false;
        }
        if (showLastKnownOnly) {
            fitMapToLastKnownLocations();
        }
    }
}

// ============================================================================
// UI State Persistence
// ============================================================================

/**
 * Save current UI state to localStorage.
 */
function saveUIState(): void {
    // Don't save while restoring state
    if (isRestoringState) return;

    const state: UIState = {
        isLiveMode: isLiveMode,
        selectedDevice: selectedDevice,
        timeRangeHours: timeRangeHours,
        trailResolution: trailResolution,
        showLastKnownOnly: showLastKnownOnly,
        historicDate: historicDate,
        historicStartMinutes: historicStartMinutes,
        historicEndMinutes: historicEndMinutes,
        mobileLayoutMode: mobileLayoutMode,
    };
    localStorage.setItem('mytracks-ui-state', JSON.stringify(state));
}

/**
 * Save map position separately (called on map move/zoom).
 */
function saveMapPosition(): void {
    if (!map || isRestoringState) return;
    const center = map.getCenter();
    const mapState: MapPosition = {
        lat: center.lat,
        lng: center.lng,
        zoom: map!.getZoom(),
    };
    localStorage.setItem('mytracks-map-position', JSON.stringify(mapState));
}

/**
 * Load saved map position from localStorage.
 * @returns Saved map position or null
 */
function loadMapPosition(): MapPosition | null {
    try {
        const saved = localStorage.getItem('mytracks-map-position');
        if (saved) {
            return JSON.parse(saved) as MapPosition;
        }
    } catch (e) {
        console.error('Error loading map position:', e);
    }
    return null;
}

/**
 * Load saved UI state from localStorage.
 * @returns Saved UI state or null
 */
function loadUIState(): UIState | null {
    try {
        const saved = localStorage.getItem('mytracks-ui-state');
        if (saved) {
            return JSON.parse(saved) as UIState;
        }
    } catch (e) {
        console.error('Error loading UI state:', e);
    }
    return null;
}

/**
 * Restore UI state from localStorage.
 */
function restoreUIState(): void {
    const state = loadUIState();
    if (!state) return;

    isRestoringState = true;

    // Restore time range (legacy, kept for backward compat)
    if (state.timeRangeHours) {
        timeRangeHours = state.timeRangeHours;
        const timeRangeSelector = document.getElementById('time-range-selector') as HTMLSelectElement;
        if (timeRangeSelector) {
            timeRangeSelector.value = String(timeRangeHours);
        }
    }

    // Restore historic date + time range
    if (state.historicDate) {
        historicDate = state.historicDate;
    }
    if (state.historicStartMinutes !== undefined) {
        historicStartMinutes = state.historicStartMinutes;
    }
    if (state.historicEndMinutes !== undefined) {
        historicEndMinutes = state.historicEndMinutes;
    }

    // Restore resolution (slider value 0-100)
    if (state.trailResolution !== undefined) {
        trailResolution = state.trailResolution;
        const precisionSlider = document.getElementById('precision-slider') as HTMLInputElement;
        const precisionValue = document.getElementById('precision-value');
        if (precisionSlider) {
            // Convert resolution (0-360) to slider percentage (100-0)
            // 0 (precise) -> 100%, 360 (coarse) -> 0%
            const sliderValue = Math.round((1 - trailResolution / 360) * 100);
            precisionSlider.value = String(sliderValue);
            if (precisionValue) {
                precisionValue.textContent = `${sliderValue}%`;
            }
        }
    }

    showLastKnownOnly = Boolean(state.showLastKnownOnly);
    updateLastKnownOnlyButton();

    if (state.mobileLayoutMode === 'map-only' || state.mobileLayoutMode === 'table-only' || state.mobileLayoutMode === 'split') {
        mobileLayoutMode = state.mobileLayoutMode;
    }
    applyMobileLayoutMode();

    // Restore mode
    if (state.isLiveMode === false) {
        // Store state for device restoration after devices load
        pendingRestoreState = state;
        switchToHistoricMode();
    }

    isRestoringState = false;
}

/**
 * Called after devices are populated to complete restoration.
 */
function completeStateRestore(): void {
    if (!pendingRestoreState || !pendingRestoreState.selectedDevice) return;

    const selector = document.getElementById('device-selector') as HTMLSelectElement;
    const deviceOption = selector?.querySelector(`option[value="${pendingRestoreState.selectedDevice}"]`);

    if (deviceOption) {
        isRestoringState = true;
        selectedDevice = pendingRestoreState.selectedDevice;
        selector.value = selectedDevice;
        // Don't fit bounds - we have a saved map position
        fetchAndDisplayTrail();
        isRestoringState = false;
    }

    pendingRestoreState = null;
}

// ============================================================================
// ============================================================================
// Map Functions
// ============================================================================

/**
 * Initialize the Leaflet map.
 */
function initMap(): void {
    map = L.map('map', {
        dragging: true,
        touchZoom: true,
        scrollWheelZoom: true,
        doubleClickZoom: true,
        boxZoom: true,
    });

    // Restore saved map position or use default
    const savedPosition = loadMapPosition();
    if (savedPosition) {
        map!.setView([savedPosition.lat, savedPosition.lng], savedPosition.zoom);
        // Don't fit bounds on restore since we have a saved position
        needsFitBounds = false;
    } else {
        map!.setView([37.7749, -122.4194], 17);
    }

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors',
        maxZoom: 19,
    }).addTo(map!);

    // Save map position on move/zoom
    map.on('moveend', saveMapPosition);
    map.on('zoomend', saveMapPosition);

    // Fix map rendering after initial load
    setTimeout(() => map!.invalidateSize(), 100);
}

/**
 * Get HTML content for a location popup.
 * @param location - Location data
 * @returns HTML string for popup
 */
function getPopupContent(location: TrackLocation): string {
    const device = location.device_name || 'Unknown';
    const time = formatTime(location.timestamp_unix || 0);
    const lat = formatLatLonCoordinate(location.latitude);
    const lon = formatLatLonCoordinate(location.longitude);
    const acc = location.accuracy || 'N/A';
    const batt = location.battery_level || 'N/A';
    const vel = location.velocity || 0;

    return `<div style="font-size: 12px;">
        <strong>${device}</strong><br>
        <em>${time}</em><br>
        <strong>Position:</strong> ${lat}, ${lon}<br>
        <strong>Accuracy:</strong> ${acc}m<br>
        <strong>Speed:</strong> ${vel} km/h<br>
        <strong>Battery:</strong> ${batt}%
    </div>`;
}

/**
 * Ensure a device name is present in the device selector dropdown.
 * Inserts in sorted (case-insensitive lexicographic) order after "All Devices".
 * Returns true if the device was newly added.
 * @param deviceName - The device name to ensure is in the selector
 */
function ensureDeviceInSelector(deviceName: string): boolean {
    if (devices.has(deviceName)) return false;

    devices.add(deviceName);
    const selector = document.getElementById('device-selector') as HTMLSelectElement;
    if (selector) {
        const option = document.createElement('option');
        option.value = deviceName;
        option.textContent = deviceName;

        // Insert in sorted position (skip index 0 = "All Devices")
        const nameLower = deviceName.toLowerCase();
        let inserted = false;
        for (let i = 1; i < selector.options.length; i++) {
            if (selector.options[i].textContent!.toLowerCase() > nameLower) {
                selector.insertBefore(option, selector.options[i]);
                inserted = true;
                break;
            }
        }
        if (!inserted) {
            selector.appendChild(option);
        }
    }

    // Try to complete state restoration if we just added the pending device
    if (pendingRestoreState && pendingRestoreState.selectedDevice === deviceName) {
        completeStateRestore();
    }

    return true;
}

/**
 * Refresh the device selector from the server.
 * Fetches the current device list and rebuilds the selector dropdown,
 * preserving the current selection. Removes devices that no longer exist.
 */
async function refreshDeviceSelector(): Promise<void> {
    try {
        const response = await fetch('/api/devices/');
        if (!response.ok) {
            console.error('Failed to fetch devices:', response.status);
            return;
        }

        const data = await response.json();
        const deviceList: DeviceInfo[] = extractResultsList<DeviceInfo>(data);
        const selector = document.getElementById('device-selector') as HTMLSelectElement;
        if (!selector) return;

        // Build display names: prefer owner/device_id combo; fall back to device_id
        const serverDeviceNames = deviceList.map(d =>
            d.owner_username ? `${d.owner_username}/${d.device_id}` : d.device_id,
        );

        // Sort case-insensitively
        serverDeviceNames.sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));

        // Remember current selection
        const previousSelection = selector.value;

        // Clear everything except "All Devices" (index 0)
        while (selector.options.length > 1) {
            selector.remove(1);
        }
        devices.clear();

        // Repopulate
        for (const name of serverDeviceNames) {
            devices.add(name);
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            selector.appendChild(option);
        }

        // Restore selection if the device still exists, otherwise reset to "All Devices"
        if (previousSelection && serverDeviceNames.includes(previousSelection)) {
            selector.value = previousSelection;
        } else if (previousSelection) {
            // Previously selected device no longer exists
            selector.value = '';
            selectedDevice = '';
            console.log(`Device '${previousSelection}' no longer exists, reset to All Devices`);
        }

        console.log(`Device selector refreshed: ${serverDeviceNames.length} device(s)`);
    } catch (error) {
        console.error('Error refreshing device selector:', error);
    }
}

/**
 * Update device marker on map.
 * @param location - Location data
 */
function updateDeviceMarker(location: TrackLocation): void {
    const deviceName = location.device_name || 'Unknown';
    const lat = parseFloat(String(location.latitude));
    const lon = parseFloat(String(location.longitude));

    if (isNaN(lat) || isNaN(lon)) return;

    ensureDeviceInSelector(deviceName);

    // In live mode, filter by selection if set; in historic mode, also filter
    if (selectedDevice && selectedDevice !== deviceName) {
        // Hide marker if it exists
        if (deviceMarkers[deviceName]) {
            unregisterLocationMarker(deviceMarkers[deviceName]);
            deviceMarkers[deviceName].remove();
            delete deviceMarkers[deviceName];
        }
        // Also hide trail if it exists
        if (deviceTrails[deviceName]) {
            removeTrailElements(deviceTrails[deviceName]);
            delete deviceTrails[deviceName];
        }
        return;
    }

    const latLng: [number, number] = [lat, lon];
    const deviceColor = getDeviceColor(deviceName);

    if (deviceMarkers[deviceName]) {
        // Update existing marker
        deviceMarkers[deviceName].setLatLng(latLng);
        deviceMarkers[deviceName].setPopupContent(getPopupContent(location));
    } else {
        // Create new colored marker using a circle marker for device-specific colors
        const marker = L.circleMarker(latLng, {
            radius: 10,
            fillColor: deviceColor,
            color: '#fff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.9,
        }).addTo(map!);
        marker.bindPopup(getPopupContent(location));
        // Add tooltip showing device name on hover
        marker.bindTooltip(deviceName, {
            permanent: false,
            direction: 'top',
            offset: [0, -10],
        });
        deviceMarkers[deviceName] = marker;
    }
    registerLocationMarker(location, deviceMarkers[deviceName], 'device');

    // Center map on the marker in live mode only (when a single device is selected or first marker)
    // Avoid re-centering when showing "All Devices" — that creates constant map motion/jank.
    if (isLiveMode && selectedDevice && selectedDevice === deviceName) {
        map!.setView(latLng, map!.getZoom());
    }

    // If we're in live mode with no filter, only center when the very first marker is created.
    if (isLiveMode && !selectedDevice && Object.keys(deviceMarkers).length === 1) {
        map!.setView(latLng, map!.getZoom());
    }
    updateDeviceLegendVisibility();
}

// ============================================================================
// Geocoding Functions
// ============================================================================

/**
 * Process geocoding queue one at a time.
 */
async function processGeocodingQueue(): Promise<void> {
    if (isProcessingQueue || geocodingQueue.length === 0) {
        return;
    }

    isProcessingQueue = true;

    while (geocodingQueue.length > 0) {
        const item = geocodingQueue.shift()!;
        const { lat, lon, resolve, reject } = item;

        try {
            const address = await fetchAddress(lat, lon);
            resolve(address);
        } catch (error) {
            reject(error as Error);
        }

        // Wait before processing next request
        if (geocodingQueue.length > 0) {
            await new Promise(r => setTimeout(r, GEOCODING_DELAY));
        }
    }

    isProcessingQueue = false;
}

/**
 * Fetch address from coordinates using Nominatim reverse geocoding.
 * @param lat - Latitude
 * @param lon - Longitude
 * @returns Address string
 */
async function fetchAddress(lat: number, lon: number): Promise<string> {
    try {
        const response = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=18&addressdetails=1`,
            {
                headers: {
                    'User-Agent': 'OwnTracks-Backend/1.0',
                },
            },
        );

        if (!response.ok) {
            console.error('Geocoding failed:', response.status);
            return formatLatLonPair(lat, lon);
        }

        const data = await response.json();
        return data.display_name || formatLatLonPair(lat, lon);
    } catch (error) {
        console.error('Geocoding error:', error);
        return formatLatLonPair(lat, lon);
    }
}

/**
 * Queue-based geocoding to prevent overwhelming the API.
 * @param lat - Latitude
 * @param lon - Longitude
 * @returns Promise resolving to address string
 */
async function getAddress(lat: number, lon: number): Promise<string> {
    const key = formatLatLonPair(lat, lon, ',');

    // Check cache first
    if (geocodeCache.has(key)) {
        return geocodeCache.get(key)!;
    }

    // Add to queue and return a promise
    return new Promise<string>((resolve, reject) => {
        geocodingQueue.push({ lat, lon, resolve, reject });
        processGeocodingQueue();
    }).then(address => {
        // Cache the result
        geocodeCache.set(key, address);
        return address;
    });
}

/**
 * Reverse geocode a location (alias for getAddress).
 * @param lat - Latitude
 * @param lon - Longitude
 * @returns Promise resolving to address string
 */
async function reverseGeocode(lat: number, lon: number): Promise<string> {
    return getAddress(lat, lon);
}

// ============================================================================
// Location Collapsing
// ============================================================================

/**
 * Collapse consecutive waypoints at the same location into a single point.
 * Uses the oldest timestamp for the collapsed point (first occurrence in chronological order).
 * Precision derived from database schema (decimal_places), capped at 5 (~1.1m).
 *
 * @param locations - Array of locations in chronological order
 * @returns Collapsed locations with _collapsedCount property
 */
function collapseLocations(locations: TrackLocation[]): TrackLocation[] {
    if (locations.length === 0) return [];

    // Precision from DB schema: config.collapsePrecision decimals
    // 5 decimals ≈ 1.1m, 4 decimals ≈ 11m, 6 decimals ≈ 0.1m
    const PRECISION = config.collapsePrecision;
    const collapsed: TrackLocation[] = [];
    let currentGroup: TrackLocation[] = [locations[0]];
    let currentKey = `${parseFloat(String(locations[0].latitude)).toFixed(PRECISION)},${parseFloat(String(locations[0].longitude)).toFixed(PRECISION)}`;

    for (let i = 1; i < locations.length; i++) {
        const loc = locations[i];
        const key = `${parseFloat(String(loc.latitude)).toFixed(PRECISION)},${parseFloat(String(loc.longitude)).toFixed(PRECISION)}`;

        if (key === currentKey) {
            // Same location - add to current group
            currentGroup.push(loc);
        } else {
            // New location - save current group and start new one
            // Use the OLDEST (first) location in the group as the representative
            const representative: TrackLocation = { ...currentGroup[0], _collapsedCount: currentGroup.length };
            collapsed.push(representative);
            currentGroup = [loc];
            currentKey = key;
        }
    }

    // Don't forget the last group
    if (currentGroup.length > 0) {
        const representative: TrackLocation = { ...currentGroup[0], _collapsedCount: currentGroup.length };
        collapsed.push(representative);
    }

    return collapsed;
}

// Track locations for incremental trail building (used after reset)
let incrementalLocations: Record<string, TrackLocation[]> = {};
// Lightweight live trail state: keep last key + bounded list of points per device
const liveTrailLastKeyByDevice = new Map<string, string>();
const liveTrailPointsByDevice: Record<string, [number, number][]> = {};

/**
 * Add a single location incrementally to the map trail.
 * Used after reset when skipHistoryFetch is true.
 * @param location - The new location to add
 */
function addLocationToTrail(location: TrackLocation): void {
    const deviceName = location.device_name || 'Unknown';
    const deviceColor = getDeviceColor(deviceName);

    // Check if we should display this location based on device filter
    if (selectedDevice && deviceName !== selectedDevice) {
        return;
    }

    if (!locationPassesAccuracyForTrail(location)) {
        return;
    }

    // Add to incremental locations for this device
    if (!incrementalLocations[deviceName]) {
        incrementalLocations[deviceName] = [];
    }
    incrementalLocations[deviceName].push(location);

    // Clear existing trail for this device
    if (deviceTrails[deviceName]) {
        if (deviceTrails[deviceName].polyline) {
            deviceTrails[deviceName].polyline!.remove();
        }
        if (deviceTrails[deviceName].markers) {
            deviceTrails[deviceName].markers.forEach((m) => m.remove());
        }
    }

    // Rebuild trail from all incremental locations for this device
    const locations = incrementalLocations[deviceName];
    const collapsedLocations = collapseLocations(locations);

    // Create path from collapsed location coordinates
    const path: [number, number][] = collapsedLocations
        .filter(loc => loc.latitude && loc.longitude)
        .map(loc => [parseFloat(String(loc.latitude)), parseFloat(String(loc.longitude))]);

    const trailElements: TrailElements = { polyline: null, markers: [] };

    if (path.length > 1) {
        const polyline = L.polyline(path, {
            color: deviceColor,
            weight: 3,
            opacity: 0.7,
        }).addTo(map!);
        trailElements.polyline = polyline;
    }

    // Add numbered waypoint markers (using collapsed locations)
    collapsedLocations.forEach((loc, index) => {
        const waypointNumber = index + 1;
        const latLng: [number, number] = [parseFloat(String(loc.latitude)), parseFloat(String(loc.longitude))];
        const collapsedCount = loc._collapsedCount || 1;

        // Create custom numbered icon with device-specific color
        const waypointIcon = L.divIcon({
            className: 'waypoint-marker',
            html: `<div style="
                background-color: ${deviceColor};
                color: white;
                border: 2px solid white;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: bold;
                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            ">${waypointNumber}</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });

        // Format timestamp for display
        const timestamp = loc.timestamp_unix
            ? new Date(loc.timestamp_unix * 1000).toLocaleString()
            : 'Unknown time';

        // Show count if multiple waypoints were collapsed at this location
        const countInfo = collapsedCount > 1 ? `<br><i>(${collapsedCount} waypoints)</i>` : '';

        const marker = L.marker(latLng, {
            icon: waypointIcon,
        }).addTo(map!);

        // Add tooltip with waypoint info (shown on hover)
        const deviceInfo = selectedDevice ? '' : ` ${deviceName}`;
        marker.bindTooltip(`<b>#${waypointNumber}</b>${deviceInfo}<br>${timestamp}${countInfo}`, {
            permanent: false,
            direction: 'top',
            offset: [0, -12],
            className: 'waypoint-tooltip',
        });

        registerLocationMarker(loc, marker, 'waypoint');
        trailElements.markers.push(marker);
    });

    deviceTrails[deviceName] = trailElements;

    // Update device marker
    updateDeviceMarker(location);

    // Fit bounds to show trail if this is initial load after reset
    if (needsFitBounds && path.length > 0) {
        const latLng = L.latLng(path[path.length - 1][0], path[path.length - 1][1]);
        map!.setView(latLng, 17);
        needsFitBounds = false;
    }
}

/**
 * Add a live location to the trail with minimal work.
 *
 * Unlike `addLocationToTrail()` (reset-mode), this does NOT rebuild the entire
 * trail/markers. It appends a point to the existing polyline, skipping points
 * that collapse to the same rounded coordinate.
 */
function addLiveLocationToTrail(location: TrackLocation): void {
    const deviceName = location.device_name || 'Unknown';

    // Respect device filter
    if (selectedDevice && deviceName !== selectedDevice) {
        return;
    }

    if (!locationPassesAccuracyForTrail(location)) {
        return;
    }

    const lat = parseFloat(String(location.latitude));
    const lon = parseFloat(String(location.longitude));
    if (isNaN(lat) || isNaN(lon)) return;

    const PRECISION = config.collapsePrecision;
    const key = `${lat.toFixed(PRECISION)},${lon.toFixed(PRECISION)}`;
    const prev = liveTrailLastKeyByDevice.get(deviceName);
    if (prev === key) {
        return;
    }
    liveTrailLastKeyByDevice.set(deviceName, key);

    const latLng: [number, number] = [lat, lon];
    if (!liveTrailPointsByDevice[deviceName]) {
        liveTrailPointsByDevice[deviceName] = [];
    }
    liveTrailPointsByDevice[deviceName].push(latLng);

    // Bound memory + render cost for very chatty devices
    const maxPoints = 600;
    if (liveTrailPointsByDevice[deviceName].length > maxPoints) {
        liveTrailPointsByDevice[deviceName] = liveTrailPointsByDevice[deviceName].slice(-maxPoints);
    }

    const points = liveTrailPointsByDevice[deviceName] as L.LatLngTuple[];
    const deviceColor = getDeviceColor(deviceName);

    if (!deviceTrails[deviceName] || !deviceTrails[deviceName].polyline) {
        const polyline = L.polyline(points, {
            color: deviceColor,
            weight: 3,
            opacity: 0.7,
        }).addTo(map!);
        deviceTrails[deviceName] = { polyline, markers: [] };
        updateDeviceLegendVisibility();
        return;
    }

    // Update existing polyline with the new bounded set of points
    deviceTrails[deviceName].polyline!.setLatLngs(points);
    updateDeviceLegendVisibility();
}

// ============================================================================
// Trail Drawing
// ============================================================================

/**
 * Draw trails for live mode - shows last hour of movement per device.
 * @param locationsByDevice - Locations grouped by device name
 */
function drawLiveTrails(locationsByDevice: Record<string, TrackLocation[]>): void {
    // Clear existing trails first
    removeAllTrails();

    // Draw trail for each device
    Object.entries(locationsByDevice).forEach(([deviceName, locations]) => {
        if (locations.length === 0) return;

        const deviceColor = getDeviceColor(deviceName);

        // Locations are newest-first, reverse for chronological trail
        const chronological = [...locations].reverse().filter(locationPassesAccuracyForTrail);

        // Collapse consecutive waypoints at same location
        const collapsedLocations = collapseLocations(chronological);

        // Create path from collapsed location coordinates
        const path: [number, number][] = collapsedLocations
            .filter(loc => loc.latitude && loc.longitude)
            .map(loc => [parseFloat(String(loc.latitude)), parseFloat(String(loc.longitude))]);

        const trailElements: TrailElements = { polyline: null, markers: [] };

        if (path.length > 1) {
            const polyline = L.polyline(path, {
                color: deviceColor,
                weight: 3,
                opacity: 0.7,
            }).addTo(map!);
            trailElements.polyline = polyline;
        }

        // Add numbered waypoint markers (using collapsed locations)
        collapsedLocations.forEach((loc, index) => {
            const waypointNumber = index + 1;
            const latLng: [number, number] = [parseFloat(String(loc.latitude)), parseFloat(String(loc.longitude))];
            const collapsedCount = loc._collapsedCount || 1;

            // Create custom numbered icon with device-specific color
            const waypointIcon = L.divIcon({
                className: 'waypoint-marker',
                html: `<div style="
                    background-color: ${deviceColor};
                    color: white;
                    border: 2px solid white;
                    border-radius: 50%;
                    width: 24px;
                    height: 24px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 12px;
                    font-weight: bold;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                ">${waypointNumber}</div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            });

            // Format timestamp for display
            const timestamp = loc.timestamp_unix
                ? new Date(loc.timestamp_unix * 1000).toLocaleString()
                : 'Unknown time';

            // Show count if multiple waypoints were collapsed at this location
            const countInfo = collapsedCount > 1 ? `<br><i>(${collapsedCount} waypoints)</i>` : '';

            const marker = L.marker(latLng, {
                icon: waypointIcon,
            }).addTo(map!);

            // Add tooltip with waypoint info (shown on hover)
            // Show device name only when "All Devices" is selected
            const deviceInfo = selectedDevice ? '' : ` ${deviceName}`;
            marker.bindTooltip(`<b>#${waypointNumber}</b>${deviceInfo}<br>${timestamp}${countInfo}`, {
                permanent: false,
                direction: 'top',
                offset: [0, -12],
                className: 'waypoint-tooltip',
            });

            registerLocationMarker(loc, marker, 'waypoint');
            trailElements.markers.push(marker);
        });

        deviceTrails[deviceName] = trailElements;
    });
    updateDeviceLegendVisibility();

    // Fit bounds to show all trails if this is initial load
    if (needsFitBounds) {
        const allPoints: L.LatLng[] = [];
        Object.values(deviceTrails).forEach(trail => {
            if (trail.polyline) {
                trail.polyline.getLatLngs().forEach((latlng) => allPoints.push(latlng as L.LatLng));
            }
        });
        if (allPoints.length > 0) {
            const bounds = L.latLngBounds(allPoints);
            if (allPoints.length === 1) {
                map!.setView(allPoints[0], 17);
            } else {
                map!.fitBounds(bounds, { padding: [50, 50], maxZoom: 17 });
            }
            needsFitBounds = false;
        }
    }
}

/**
 * Fetch and display location trail for selected device and time range.
 */
async function fetchAndDisplayTrail(): Promise<void> {
    const [startTime, endTime] = getHistoricTimestamps();

    // Clear existing trails
    removeAllTrails();
    selectedLocationKey = null;
    applyLocationSelection();

    if (!selectedDevice) {
        // "All Devices" selected - show trails and numbered waypoints for each device
        // Reset color assignments so colors are distributed optimally for visible devices
        resetDeviceColors();
        try {
            // Always include resolution to bypass pagination limit
            const url = `/api/locations/?start_time=${Math.floor(startTime)}&end_time=${Math.floor(endTime)}&ordering=-timestamp&resolution=${trailResolution}`;
            const response = await fetch(url);
            if (!response.ok) return;

            const data: LocationsApiResponse = await response.json();
            const locations = data.results || [];

            // Clear stale device markers before rendering new results
            removeAllDeviceMarkers();

            // Show summary in activity section (with device names)
            displayHistoricWaypoints(locations, true); // true = show device names

            // Group locations by device
            const locationsByDevice: Record<string, TrackLocation[]> = {};
            locations.forEach(loc => {
                const device = loc.device_name || 'Unknown';
                if (!locationsByDevice[device]) {
                    locationsByDevice[device] = [];
                }
                locationsByDevice[device].push(loc);
            });

            // Create trails and numbered waypoints for each device
            Object.entries(locationsByDevice).forEach(([deviceName, deviceLocations]) => {
                if (deviceLocations.length === 0) return;

                // Get locations in chronological order (oldest first)
                const chronologicalLocations = deviceLocations
                    .filter(loc => loc.latitude && loc.longitude)
                    .reverse()
                    .filter(locationPassesAccuracyForTrail);

                if (chronologicalLocations.length === 0) return;

                // Collapse consecutive waypoints at same location
                const collapsedLocations = collapseLocations(chronologicalLocations);

                // Create path from collapsed location coordinates
                const path: [number, number][] = collapsedLocations.map(loc => [
                    parseFloat(String(loc.latitude)),
                    parseFloat(String(loc.longitude)),
                ]);

                const trailElements: TrailElements = { polyline: null, markers: [] };
                const deviceColor = getDeviceColor(deviceName);

                if (path.length > 0) {
                    // Add numbered waypoint markers (using collapsed locations)
                    collapsedLocations.forEach((loc, index) => {
                        const waypointNumber = index + 1;
                        const latLng: [number, number] = [
                            parseFloat(String(loc.latitude)), parseFloat(String(loc.longitude))
                        ];
                        const collapsedCount = loc._collapsedCount || 1;

                        // Create custom numbered icon with device-specific color
                        const waypointIcon = L.divIcon({
                            className: 'waypoint-marker',
                            html: `<div style="
                                background-color: ${deviceColor};
                                color: white;
                                border: 2px solid white;
                                border-radius: 50%;
                                width: 24px;
                                height: 24px;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 12px;
                                font-weight: bold;
                                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                            ">${waypointNumber}</div>`,
                            iconSize: [24, 24],
                            iconAnchor: [12, 12],
                        });

                        // Format timestamp for display
                        const timestamp = loc.timestamp_unix
                            ? new Date(loc.timestamp_unix * 1000).toLocaleString()
                            : 'Unknown time';

                        // Show count if multiple waypoints were collapsed at this location
                        const countInfo = collapsedCount > 1 ? `<br><i>(${collapsedCount} waypoints)</i>` : '';

                        const marker = L.marker(latLng, {
                            icon: waypointIcon,
                        }).addTo(map!);

                        // Add tooltip with waypoint info (shown on hover)
                        // Show device name since multiple devices are displayed
                        marker.bindTooltip(`<b>${deviceName} #${waypointNumber}</b><br>${timestamp}${countInfo}`, {
                            permanent: false,
                            direction: 'top',
                            offset: [0, -12],
                            className: 'waypoint-tooltip',
                        });

                        // Create popup content
                        const collapsedInfo = collapsedCount > 1 ? `<i>(${collapsedCount} waypoints at this location)</i><br>` : '';
                        const popupContent = `
                            <div class="waypoint-popup">
                                <b>${deviceName} - Waypoint #${waypointNumber}</b><br>
                                ${timestamp}<br>
                                ${collapsedInfo}
                                <span class="loading-address">📍 Click to load address...</span>
                            </div>
                        `;
                        marker.bindPopup(popupContent);

                        // Lazy load address on click
                        marker.on('click', async function (this: L.Marker): Promise<void> {
                            const popup = this.getPopup();
                            if (!popup) return;
                            const content = popup.getContent();
                            if (typeof content !== 'string') return;

                            // Only geocode if not already loaded
                            if (content.includes('loading-address')) {
                                try {
                                    const address = await reverseGeocode(latLng[0], latLng[1]);
                                    const newContent = `
                                        <div class="waypoint-popup">
                                            <b>${deviceName} - Waypoint #${waypointNumber}</b><br>
                                            ${timestamp}<br>
                                            📍 ${address}
                                        </div>
                                    `;
                                    popup.setContent(newContent);
                                } catch (e) {
                                    console.error('Geocoding error:', e);
                                }
                            }
                        });

                        registerLocationMarker(loc, marker, 'waypoint');
                        trailElements.markers.push(marker);
                    });

                    // Draw polyline for trail (only if multiple points) with device-specific color
                    if (path.length > 1) {
                        const polyline = L.polyline(path, {
                            color: deviceColor,
                            weight: 3,
                            opacity: 0.7,
                        }).addTo(map!);

                        trailElements.polyline = polyline;
                    }

                    deviceTrails[deviceName] = trailElements;
                }

                // Update main marker to most recent location for this device
                updateDeviceMarker(deviceLocations[0]);
            });

            updateDeviceLegendVisibility();

            // Fit bounds to show all devices
            if (needsFitBounds && locations.length > 0) {
                const allPoints: [number, number][] = locations
                    .filter(loc => loc.latitude && loc.longitude)
                    .map(loc => [
                        parseFloat(String(loc.latitude)),
                        parseFloat(String(loc.longitude)),
                    ]);

                if (allPoints.length > 0) {
                    const bounds = L.latLngBounds(allPoints);
                    if (allPoints.length === 1) {
                        map!.setView(allPoints[0], 17);
                    } else {
                        map!.fitBounds(bounds, { padding: [50, 50], maxZoom: 17 });
                    }
                    needsFitBounds = false;
                }
            }
        } catch (error) {
            console.error('Error fetching all devices:', error);
        }
        return;
    }

    try {
        // Always include resolution to bypass pagination limit
        const url = `/api/locations/?device=${selectedDevice}&start_time=${Math.floor(startTime)}&end_time=${Math.floor(endTime)}&ordering=-timestamp&resolution=${trailResolution}`;
        const response = await fetch(url);
        if (!response.ok) return;

        const data: LocationsApiResponse = await response.json();
        const locations = data.results || [];

        updateDeviceLegendVisibility();

        // Clear stale marker for this device before rendering
        if (deviceMarkers[selectedDevice]) {
            deviceMarkers[selectedDevice].remove();
            delete deviceMarkers[selectedDevice];
        }

        // Update activity section with waypoints
        displayHistoricWaypoints(locations);

        if (locations.length === 0) return;

        // Clear old trail for this device
        if (deviceTrails[selectedDevice]) {
            if (deviceTrails[selectedDevice].polyline) {
                deviceTrails[selectedDevice].polyline!.remove();
            }
            if (deviceTrails[selectedDevice].markers) {
                deviceTrails[selectedDevice].markers.forEach((m) => m.remove());
            }
        }

        // Get locations in chronological order (oldest first)
        const chronologicalLocations = locations
            .filter(loc => loc.latitude && loc.longitude)
            .reverse()
            .filter(locationPassesAccuracyForTrail);

        // Collapse consecutive waypoints at same location (only shows movement)
        // Each collapsed point uses the oldest timestamp from the group
        const collapsedLocations = collapseLocations(chronologicalLocations);

        // Create path from collapsed location coordinates
        const path: [number, number][] = collapsedLocations.map(loc => [
            parseFloat(String(loc.latitude)),
            parseFloat(String(loc.longitude)),
        ]);

        const trailElements: TrailElements = { polyline: null, markers: [] };
        const deviceColor = getDeviceColor(selectedDevice);

        if (path.length > 0) {
            // Add numbered waypoint markers (using collapsed locations)
            collapsedLocations.forEach((loc, index) => {
                const waypointNumber = index + 1;
                const latLng: [number, number] = [parseFloat(String(loc.latitude)), parseFloat(String(loc.longitude))];
                const collapsedCount = loc._collapsedCount || 1;

                // Create custom numbered icon with device-specific color
                const waypointIcon = L.divIcon({
                    className: 'waypoint-marker',
                    html: `<div style="
                        background-color: ${deviceColor};
                        color: white;
                        border: 2px solid white;
                        border-radius: 50%;
                        width: 24px;
                        height: 24px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 12px;
                        font-weight: bold;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                    ">${waypointNumber}</div>`,
                    iconSize: [24, 24],
                    iconAnchor: [12, 12],
                });

                // Format timestamp for display
                const timestamp = loc.timestamp_unix
                    ? new Date(loc.timestamp_unix * 1000).toLocaleString()
                    : 'Unknown time';

                // Show count if multiple waypoints were collapsed at this location
                const countInfo = collapsedCount > 1 ? `<br><i>(${collapsedCount} waypoints)</i>` : '';

                const marker = L.marker(latLng, {
                    icon: waypointIcon,
                }).addTo(map!);

                // Add tooltip with waypoint info (shown on hover)
                // When a specific device is selected, don't show device name (it's already known)
                marker.bindTooltip(`<b>#${waypointNumber}</b><br>${timestamp}${countInfo}`, {
                    permanent: false,
                    direction: 'top',
                    offset: [0, -12],
                    className: 'waypoint-tooltip',
                });

                // Create popup content (will be updated with address on click)
                const collapsedInfo = collapsedCount > 1 ? `<i>(${collapsedCount} waypoints at this location)</i><br>` : '';
                const popupContent = `
                    <div class="waypoint-popup">
                        <b>Waypoint #${waypointNumber}</b><br>
                        ${timestamp}<br>
                        ${collapsedInfo}
                        <span class="loading-address">📍 Click to load address...</span>
                    </div>
                `;
                marker.bindPopup(popupContent);

                // Lazy load address on click
                marker.on('click', async function (this: L.Marker): Promise<void> {
                    const popup = this.getPopup();
                    if (!popup) return;
                    const content = popup.getContent();
                    if (typeof content !== 'string') return;

                    // Only geocode if not already loaded
                    if (content.includes('loading-address')) {
                        try {
                            const address = await reverseGeocode(latLng[0], latLng[1]);
                            const newContent = `
                                <div class="waypoint-popup">
                                    <b>Waypoint #${waypointNumber}</b><br>
                                    ${timestamp}<br>
                                    📍 ${address}
                                </div>
                            `;
                            popup.setContent(newContent);
                        } catch (e) {
                            console.error('Geocoding error:', e);
                        }
                    }
                });

                registerLocationMarker(loc, marker, 'waypoint');
                trailElements.markers.push(marker);
            });

            // Draw polyline for trail (only if multiple points) with device-specific color
            if (path.length > 1) {
                const polyline = L.polyline(path, {
                    color: deviceColor,
                    weight: 3,
                    opacity: 0.7,
                }).addTo(map!);

                trailElements.polyline = polyline;
            }

            deviceTrails[selectedDevice] = trailElements;

            // Fit map to show all waypoints only on initial load
            if (needsFitBounds) {
                if (path.length === 1) {
                    // Single location - center and zoom to street level
                    map!.setView(path[0], 17);
                } else {
                    // Multiple locations - fit to show all with appropriate padding
                    const bounds = L.latLngBounds(path);
                    map!.fitBounds(bounds, {
                        padding: [50, 50],
                        maxZoom: 17, // Don't zoom in too much even for close points
                    });
                }
                needsFitBounds = false;
            }
        }

        // Update main marker to most recent location
        if (locations.length > 0) {
            updateDeviceMarker(locations[0]);
        }
    } catch (error) {
        console.error('Error fetching trail:', error);
    }
}

// ============================================================================
// Activity Section
// ============================================================================

/**
 * Clear activity section and show a message.
 * @param message - Message to display
 */
function clearActivitySection(message: string): void {
    const container = document.getElementById('log-container');
    if (container) {
        container.innerHTML = `<p id="loading">${message}</p>`;
    }
    const logCount = document.getElementById('log-count');
    if (logCount) {
        logCount.textContent = '0 waypoints';
    }
}

/**
 * Display historic waypoints in activity section.
 * Shows collapsed waypoints (same location = single entry) with counts.
 * @param locations - Locations to display
 * @param showDeviceNames - Whether to show device names (for "All Devices" view)
 */
function displayHistoricWaypoints(locations: TrackLocation[], showDeviceNames = false): void {
    const container = document.getElementById('log-container');
    if (!container) return;

    container.innerHTML = ''; // Clear existing content

    if (locations.length === 0) {
        container.innerHTML = '<p id="loading">No waypoints found for selected time range</p>';
        const logCount = document.getElementById('log-count');
        if (logCount) {
            logCount.textContent = '0 waypoints';
        }
        return;
    }

    if (showDeviceNames) {
        // For "All Devices" view: group by device, collapse per device, show with device names
        const locationsByDevice: Record<string, TrackLocation[]> = {};
        locations.forEach(loc => {
            const device = loc.device_name || 'Unknown';
            if (!locationsByDevice[device]) {
                locationsByDevice[device] = [];
            }
            locationsByDevice[device].push(loc);
        });

        interface DisplayEntry {
            loc: TrackLocation;
            deviceName: string;
            deviceColor: string;
        }

        const displayEntries: DisplayEntry[] = [];

        Object.entries(locationsByDevice).forEach(([deviceName, deviceLocations]) => {
            const chronological = [...deviceLocations].reverse();
            const collapsedLocations = collapseLocations(chronological);

            collapsedLocations.forEach((loc) => {
                displayEntries.push({
                    loc,
                    deviceName,
                    deviceColor: getDeviceColor(deviceName),
                });
            });
        });

        // Sort all entries by timestamp (newest first for display)
        displayEntries.sort((a, b) => (b.loc.timestamp_unix || 0) - (a.loc.timestamp_unix || 0));

        // Display entries
        displayEntries.forEach(({ loc, deviceName, deviceColor }) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = formatTime(loc.timestamp_unix || 0, true);
            const ip = loc.received_via === 'mqtt' ? 'MQTT' : (loc.ip_address || 'N/A');
            const lat = formatLatLonCoordinate(loc.latitude);
            const lon = formatLatLonCoordinate(loc.longitude);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
            const collapsedCount = loc._collapsedCount || 1;

            const countBadge =
                collapsedCount > 1
                    ? `<span style="background:#6c757d;color:white;padding:1px 5px;border-radius:10px;font-size:10px;margin-left:8px;">×${collapsedCount}</span>`
                    : '';

            const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${deviceName}</span>`;

            entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>${countBadge}${deviceBadge}`;

            attachLocationSelectionToEntry(entry, loc);
            decorateActivityLogEntryForAccuracy(entry, loc);
            container.appendChild(entry);
        });

        // Show count summary
        const totalCollapsed = displayEntries.length;
        const deviceCount = Object.keys(locationsByDevice).length;
        const countText = `${totalCollapsed} location${totalCollapsed !== 1 ? 's' : ''} across ${deviceCount} device${deviceCount !== 1 ? 's' : ''} (${locations.length} waypoints)`;
        const logCount = document.getElementById('log-count');
        if (logCount) {
            logCount.textContent = countText;
        }
    } else {
        // Single device view: original behavior
        // Collapse consecutive waypoints at same location
        // API returns newest first, so we reverse to get chronological order for collapsing
        const chronological = [...locations].reverse();
        const collapsedLocations = collapseLocations(chronological);
        // Reverse back to show newest first in the list
        const displayLocations = [...collapsedLocations].reverse();

        // Display collapsed waypoints (newest first at top)
        displayLocations.forEach((loc) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = formatTime(loc.timestamp_unix || 0, true);
            const device = loc.device_name || selectedDevice || 'Unknown';
            const ip = loc.received_via === 'mqtt' ? 'MQTT' : (loc.ip_address || 'N/A');
            const lat = formatLatLonCoordinate(loc.latitude);
            const lon = formatLatLonCoordinate(loc.longitude);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
            const collapsedCount = loc._collapsedCount || 1;

            const countBadge =
                collapsedCount > 1
                    ? `<span style="background:#6c757d;color:white;padding:1px 5px;border-radius:10px;font-size:10px;margin-left:8px;">×${collapsedCount}</span>`
                    : '';

            const deviceColor = getDeviceColor(device);
            const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${device}</span>`;

            entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>${countBadge}${deviceBadge}`;

            attachLocationSelectionToEntry(entry, loc);
            decorateActivityLogEntryForAccuracy(entry, loc);
            container.appendChild(entry);
        });

        // Show both collapsed count and original count
        const collapsedCount = collapsedLocations.length;
        const originalCount = locations.length;
        const countText =
            collapsedCount < originalCount
                ? `${collapsedCount} location${collapsedCount !== 1 ? 's' : ''} (${originalCount} waypoints)`
                : `${originalCount} waypoint${originalCount !== 1 ? 's' : ''}`;
        const logCount = document.getElementById('log-count');
        if (logCount) {
            logCount.textContent = countText;
        }
    }
}

/**
 * Add a log entry for a new location.
 * @param location - Location data
 * @param skipScroll - Whether to skip auto-scrolling
 */
function addLogEntry(location: TrackLocation, skipScroll = false): void {
    const container = document.getElementById('log-container');
    if (!container) return;

    const loading = document.getElementById('loading');
    if (loading) loading.remove();

    console.log('Adding log entry:', location);

    if (location.id !== undefined && location.id !== null) {
        const existing = container.querySelector(`[data-location-id="${String(location.id)}"]`);
        if (existing) {
            return;
        }
    }

    const entry = document.createElement('div');
    entry.className = 'log-entry';
    if (location.id !== undefined && location.id !== null) {
        entry.setAttribute('data-location-id', String(location.id));
    }

    const time = formatTime(location.timestamp_unix || 0, true);
    const device = location.device_name || 'Unknown';
    const lat = formatLatLonCoordinate(location.latitude);
    const lon = formatLatLonCoordinate(location.longitude);
    const acc = location.accuracy || 'N/A';
    const alt = location.altitude || 0;
    const vel = location.velocity || 0;
    const batt = location.battery_level || 'N/A';
    const conn = location.connection_type === 'w' ? 'WiFi' : location.connection_type === 'm' ? 'Mobile' : 'N/A';
    // For MQTT locations the IP is the nginx proxy container address, not the device.
    // Show "MQTT" as the source label instead to avoid confusion.
    const ipDisplay = location.received_via === 'mqtt' ? 'MQTT' : (location.ip_address || 'N/A');

    const deviceColor = getDeviceColor(device);
    const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${device}</span>`;

    entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-ip">${ipDisplay}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>${deviceBadge}`;

    attachLocationSelectionToEntry(entry, location);
    decorateActivityLogEntryForAccuracy(entry, location);
    insertLiveLogEntryInTimestampOrder(container, entry, locationTimestampUnix(location));

    // Auto-scroll so newest entry is roughly in the middle of the view
    if (!skipScroll) {
        requestAnimationFrame(() => {
            entry.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
    }

    // Keep only last 100 entries (1 hour worth at typical update rates)
    while (container.children.length > 100) {
        container.removeChild(container.lastChild!);
    }

    eventCount++;
    const logCount = document.getElementById('log-count');
    if (logCount) {
        logCount.textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '') + ' (last hour)';
    }

    // Update map marker
    if (map) {
        updateDeviceMarker(location);
    }
}

/**
 * Reset events in the activity section and clear the map.
 * Clears all markers, trails, and activity log to start fresh from this point forward.
 */
function resetEvents(): void {
    // Clear the activity log
    const container = document.getElementById('log-container');
    if (container) {
        container.innerHTML = '<p id="loading">Waiting for location updates...</p>';
    }
    eventCount = 0;
    const logCount = document.getElementById('log-count');
    if (logCount) {
        logCount.textContent = '0 events';
    }

    // Clear device markers from the map
    removeAllDeviceMarkers();

    // Clear trails from the map
    removeAllTrails();
    clearRegisteredLocationMarkers();

    // Clear incremental locations used for building trails after reset
    incrementalLocations = {};

    // Reset timestamp so new updates start fresh (don't fetch history)
    lastTimestamp = Date.now() / 1000;

    // Skip history fetch - only show new incoming data after reset
    skipHistoryFetch = true;

    // Reset fit bounds flag so next location will center the map
    needsFitBounds = true;
}

/**
 * Load last 30 minutes of data and continue with live updates.
 * This disables skipHistoryFetch so normal live mode resumes after loading.
 */
async function loadLast30Minutes(): Promise<void> {
    console.log('📍 loadLast30Minutes() called');

    // Clear current state (like reset, but we'll load history)
    const container = document.getElementById('log-container');
    if (container) {
        container.innerHTML = '<p id="loading">Loading last 30 minutes...</p>';
    }
    eventCount = 0;

    // Clear device markers from the map
    removeAllDeviceMarkers();

    // Clear trails from the map
    removeAllTrails();
    selectedLocationKey = null;

    // Clear incremental locations
    incrementalLocations = {};

    // IMPORTANT: Disable skipHistoryFetch so we can load history and resume normal updates
    skipHistoryFetch = false;

    // Reset fit bounds flag so map will center on loaded data
    needsFitBounds = true;

    // Fetch last 30 minutes
    const now = Date.now() / 1000;
    const thirtyMinutesAgo = now - 1800; // 30 minutes in seconds

    // Always include resolution to bypass pagination limit
    let url = `/api/locations/?start_time=${Math.floor(thirtyMinutesAgo)}&ordering=-timestamp&resolution=${trailResolution}`;
    if (selectedDevice) {
        url += `&device=${selectedDevice}`;
    }

    console.log(`📍 loadLast30Minutes() fetching: ${url}`);

    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.log(`📍 loadLast30Minutes() failed: ${response.status}`);
            if (container) {
                container.innerHTML = '<p id="loading">Failed to load data. Waiting for updates...</p>';
            }
            return;
        }

        const data: LocationsApiResponse = await response.json();
        const locations = data.results || [];
        locations.sort(compareLocationsByTimestampDesc);

        console.log(`📍 loadLast30Minutes() got ${locations.length} locations`);

        if (locations.length === 0) {
            if (container) {
                container.innerHTML = '<p id="loading">No data in last 30 minutes. Waiting for updates...</p>';
            }
            const logCount = document.getElementById('log-count');
            if (logCount) {
                logCount.textContent = '0 events (last 30min)';
            }
            return;
        }

        if (!container) return;

        const loading = document.getElementById('loading');
        if (loading) loading.remove();

        // Clear existing entries
        container.innerHTML = '';

        // Group locations by device for trail drawing
        const locationsByDevice: Record<string, TrackLocation[]> = {};
        const markerUpdatedForDevice = new Set<string>();

        // Display locations (sorted newest-first)
        locations.forEach((loc) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.setAttribute('data-ts', String(locationTimestampUnix(loc)));
            if (loc.id !== undefined && loc.id !== null) {
                entry.setAttribute('data-location-id', String(loc.id));
            }

            const time = formatTime(loc.timestamp_unix || 0, true);
            const device = loc.device_name || 'Unknown';
            const lat = formatLatLonCoordinate(loc.latitude);
            const lon = formatLatLonCoordinate(loc.longitude);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
            // For MQTT locations the IP is often the proxy container address, not the device.
            // Show "MQTT" as the source label instead to avoid confusion.
            const ip = loc.received_via === 'mqtt' ? 'MQTT' : (loc.ip_address || 'N/A');

            // Group locations by device for trail drawing
            if (!locationsByDevice[device]) {
                locationsByDevice[device] = [];
            }
            locationsByDevice[device].push(loc);

            const deviceColor = getDeviceColor(device);
            const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${device}</span>`;

            entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>${deviceBadge}`;

            attachLocationSelectionToEntry(entry, loc);
            decorateActivityLogEntryForAccuracy(entry, loc);
            container.appendChild(entry);

            // Update device marker for the newest location per device.
            // The API is newest-first, so the first time we see a device is its latest.
            if (!markerUpdatedForDevice.has(device)) {
                updateDeviceMarker(loc);
                markerUpdatedForDevice.add(device);
            }
        });

        // Draw trails for each device
        drawLiveTrails(locationsByDevice);

        eventCount = locations.length;
        const logCount = document.getElementById('log-count');
        if (logCount) {
            logCount.textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '') + ' (last 30min)';
        }

        // Track the newest timestamp for incremental updates
        if (locations.length > 0) {
            lastTimestamp = locations[0].timestamp_unix || null;
        }
        liveActivityLoadKind = '30m';
    } catch (error) {
        console.error('Error loading last 30 minutes:', error);
        if (container) {
            container.innerHTML = '<p id="loading">Error loading data. Waiting for updates...</p>';
        }
    }
}

/**
 * Load the most recent locations (not limited to the last 30 minutes).
 * Uses the same resolution / device filter as other live bulk loads.
 */
async function loadLatestLocations(): Promise<void> {
    console.log('📍 loadLatestLocations() called');

    const container = document.getElementById('log-container');
    if (container) {
        container.innerHTML = '<p id="loading">Loading latest locations...</p>';
    }
    eventCount = 0;

    removeAllDeviceMarkers();
    removeAllTrails();
    selectedLocationKey = null;

    incrementalLocations = {};
    skipHistoryFetch = false;
    needsFitBounds = true;

    // Paginated fetch (do not pass resolution=0 — that would load the entire history into memory).
    let url = '/api/locations/?ordering=-timestamp&limit=200';
    if (selectedDevice) {
        url += `&device=${selectedDevice}`;
    }

    console.log(`📍 loadLatestLocations() fetching: ${url}`);

    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.log(`📍 loadLatestLocations() failed: ${response.status}`);
            if (container) {
                container.innerHTML = '<p id="loading">Failed to load data. Waiting for updates...</p>';
            }
            return;
        }

        const data: LocationsApiResponse = await response.json();
        const locations = data.results || [];
        locations.sort(compareLocationsByTimestampDesc);

        console.log(`📍 loadLatestLocations() got ${locations.length} locations`);

        if (locations.length === 0) {
            if (container) {
                container.innerHTML = '<p id="loading">No location data yet. Waiting for updates...</p>';
            }
            const logCount = document.getElementById('log-count');
            if (logCount) {
                logCount.textContent = '0 events (latest)';
            }
            return;
        }

        if (!container) return;

        const loading = document.getElementById('loading');
        if (loading) loading.remove();

        container.innerHTML = '';

        const locationsByDevice: Record<string, TrackLocation[]> = {};
        const markerUpdatedForDevice = new Set<string>();

        locations.forEach((loc) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.setAttribute('data-ts', String(locationTimestampUnix(loc)));
            if (loc.id !== undefined && loc.id !== null) {
                entry.setAttribute('data-location-id', String(loc.id));
            }

            const time = formatTime(loc.timestamp_unix || 0, true);
            const device = loc.device_name || 'Unknown';
            const lat = formatLatLonCoordinate(loc.latitude);
            const lon = formatLatLonCoordinate(loc.longitude);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
            const ip = loc.received_via === 'mqtt' ? 'MQTT' : (loc.ip_address || 'N/A');

            if (!locationsByDevice[device]) {
                locationsByDevice[device] = [];
            }
            locationsByDevice[device].push(loc);

            const deviceColor = getDeviceColor(device);
            const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${device}</span>`;

            entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>${deviceBadge}`;

            attachLocationSelectionToEntry(entry, loc);
            decorateActivityLogEntryForAccuracy(entry, loc);
            container.appendChild(entry);

            if (!markerUpdatedForDevice.has(device)) {
                updateDeviceMarker(loc);
                markerUpdatedForDevice.add(device);
            }
        });

        drawLiveTrails(locationsByDevice);

        eventCount = locations.length;
        const logCount = document.getElementById('log-count');
        if (logCount) {
            logCount.textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '') + ' (latest)';
        }

        if (locations.length > 0) {
            lastTimestamp = locations[0].timestamp_unix || null;
        }
        liveActivityLoadKind = 'latest';
    } catch (error) {
        console.error('Error loading latest locations:', error);
        if (container) {
            container.innerHTML = '<p id="loading">Error loading data. Waiting for updates...</p>';
        }
    }
}

// ============================================================================
// Live Activity
/**
 * Request all online MQTT devices to report their current location.
 * Fetches the device list, then sends a reportLocation command to each
 * device that has a known MQTT topic.
 */
async function requestDeviceLocations(): Promise<void> {
    const btn = document.getElementById('request-location-button') as HTMLButtonElement | null;
    if (btn) {
        btn.disabled = true;
        setIconLabelButton(btn, '⏳', 'Polling...');
    }

    try {
        const devicesResp = await fetch('/api/devices/');
        if (!devicesResp.ok) {
            console.warn('Failed to fetch devices:', devicesResp.status);
            showToast('Could not load device list to poll.', { type: 'error' });
            return;
        }

        interface DeviceInfo {
            device_id: string;
            mqtt_topic_id: string;
            is_online: boolean;
        }
        const data = await devicesResp.json();
        const devices: DeviceInfo[] = extractResultsList<DeviceInfo>(data);

        const mqttDevices = devices.filter(d => d.mqtt_topic_id && d.is_online);
        if (mqttDevices.length === 0) {
            console.log('No online MQTT devices to poll');
            showToast('No online MQTT devices to poll.', { type: 'warning' });
            return;
        }

        const csrfToken = document.querySelector<HTMLInputElement>('[name=csrfmiddlewaretoken]')?.value ?? '';

        const results = await Promise.allSettled(
            mqttDevices.map(d =>
                fetch('/api/commands/report-location/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                    },
                    body: JSON.stringify({ device_id: d.mqtt_topic_id }),
                })
            ),
        );

        const succeeded = results.filter(r => r.status === 'fulfilled' && (r as PromiseFulfilledResult<Response>).value.ok).length;
        console.log(`Polled ${succeeded}/${mqttDevices.length} MQTT devices`);
        if (succeeded === mqttDevices.length) {
            const deviceWord = succeeded === 1 ? 'device' : 'devices';
            showToast(`Location request sent to ${succeeded} ${deviceWord}.`, { type: 'success' });
        } else if (succeeded > 0) {
            showToast(
                `Location request sent to ${succeeded} of ${mqttDevices.length} devices; ${mqttDevices.length - succeeded} failed.`,
                { type: 'warning' },
            );
        } else {
            showToast('Failed to send location request to any device.', { type: 'error' });
        }
    } catch (err) {
        console.error('requestDeviceLocations error:', err);
        showToast('Failed to send location request.', { type: 'error' });
    } finally {
        if (btn) {
            btn.disabled = false;
            setIconLabelButton(btn, '📍', 'Poll Devices');
        }
    }
}

/**
 * Update an icon/label button while preserving the `.btn-icon` / `.btn-label`
 * span structure so the mobile responsive CSS can keep collapsing it to
 * icon-only. Falls back to setting textContent if the spans are not present.
 */
function setIconLabelButton(button: HTMLButtonElement, icon: string, label: string): void {
    const iconSpan = button.querySelector<HTMLElement>('.btn-icon');
    const labelSpan = button.querySelector<HTMLElement>('.btn-label');
    if (iconSpan && labelSpan) {
        iconSpan.textContent = icon;
        labelSpan.textContent = label;
        return;
    }
    button.textContent = `${icon} ${label}`;
}

// ============================================================================

/**
 * Load last hour of live activity data.
 */
async function loadLiveActivityHistory(): Promise<void> {
    // If skipHistoryFetch is set (after reset), don't fetch history
    // Just return and let WebSocket events add new locations incrementally
    if (skipHistoryFetch) {
        console.log('📍 loadLiveActivityHistory() skipped - skipHistoryFetch is true');
        return;
    }

    liveActivityLoadKind = 'hour';

    const now = Date.now() / 1000;
    const oneHourAgo = now - 3600; // 1 hour in seconds

    // Build URL with device filter if set
    // Always include resolution to bypass pagination limit
    let url = `/api/locations/?start_time=${Math.floor(oneHourAgo)}&ordering=-timestamp&resolution=${trailResolution}`;
    if (selectedDevice) {
        url += `&device=${selectedDevice}`;
    }

    console.log(`📍 loadLiveActivityHistory() fetching: ${url}`);

    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.log(`📍 loadLiveActivityHistory() failed: ${response.status}`);
            return;
        }

        const data: LocationsApiResponse = await response.json();
        const locations = data.results || [];
        locations.sort(compareLocationsByTimestampDesc);

        console.log(`📍 loadLiveActivityHistory() got ${locations.length} locations`);

        if (locations.length === 0) {
            return;
        }

        const container = document.getElementById('log-container');
        if (!container) return;

        const loading = document.getElementById('loading');
        if (loading) loading.remove();

        // Clear existing entries before repopulating
        container.innerHTML = '';

        // Group locations by device for trail drawing
        const locationsByDevice: Record<string, TrackLocation[]> = {};

        // Display locations (sorted newest-first)
        locations.forEach((loc, index) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.setAttribute('data-ts', String(locationTimestampUnix(loc)));
            if (loc.id !== undefined && loc.id !== null) {
                entry.setAttribute('data-location-id', String(loc.id));
            }

            const time = formatTime(loc.timestamp_unix || 0, true);
            const device = loc.device_name || 'Unknown';
            const lat = formatLatLonCoordinate(loc.latitude);
            const lon = formatLatLonCoordinate(loc.longitude);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
            const ip = loc.received_via === 'mqtt' ? 'MQTT' : (loc.ip_address || 'N/A');

            // Group locations by device for trail drawing
            if (!locationsByDevice[device]) {
                locationsByDevice[device] = [];
            }
            locationsByDevice[device].push(loc);

            const deviceColor = getDeviceColor(device);
            const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${device}</span>`;

            entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>${deviceBadge}`;

            attachLocationSelectionToEntry(entry, loc);
            decorateActivityLogEntryForAccuracy(entry, loc);
            container.appendChild(entry);

            // Update device marker (only for latest position of each device)
            if (index === 0 || !deviceMarkers[device]) {
                updateDeviceMarker(loc);
            }
        });

        // Draw trails for each device
        drawLiveTrails(locationsByDevice);

        eventCount = locations.length;
        const logCount = document.getElementById('log-count');
        if (logCount) {
            logCount.textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '') + ' (last hour)';
        }

        // Track the newest timestamp for incremental updates
        if (locations.length > 0) {
            lastTimestamp = locations[0].timestamp_unix || null;
        }
    } catch (error) {
        console.error('Error loading live activity history:', error);
    }
}

/**
 * Refresh live activity with updates since last known timestamp (for reconnect).
 */
async function refreshLiveActivitySinceLastUpdate(): Promise<void> {
    // If skipHistoryFetch is true (after reset), don't fetch any history
    if (skipHistoryFetch) {
        console.log('📍 refreshLiveActivitySinceLastUpdate() skipped - skipHistoryFetch is true');
        return;
    }

    if (!lastTimestamp) {
        // No previous data, do a full load
        loadLiveActivityHistory();
        return;
    }

    try {
        // Fetch only locations newer than our last known timestamp
        const response = await fetch(`/api/locations/?start_time=${lastTimestamp + 1}&ordering=timestamp&limit=100`);
        if (!response.ok) return;

        const data: LocationsApiResponse = await response.json();
        const locations = data.results || [];

        if (locations.length === 0) {
            console.log('No new locations since last update');
            return;
        }

        console.log(`Found ${locations.length} new location(s) since last update`);

        // Oldest first so insert-sorted log order stays correct
        locations.sort((a, b) => locationTimestampUnix(a) - locationTimestampUnix(b));
        locations.forEach(loc => {
            addLogEntry(loc);
            // Update lastTimestamp to track what we've seen
            if (loc.timestamp_unix && loc.timestamp_unix > (lastTimestamp || 0)) {
                lastTimestamp = loc.timestamp_unix;
            }
        });
    } catch (error) {
        console.error('Error refreshing live activity:', error);
    }
}

// ============================================================================
// Mode Switching
// ============================================================================

/**
 * Switch to live mode.
 */
function switchToLiveMode(): void {
    isLiveMode = true;
    needsFitBounds = true; // Fit bounds on mode switch
    liveActivityLoadKind = 'hour';

    // Update button states
    document.getElementById('live-mode-btn')?.classList.add('active');
    document.getElementById('historic-mode-btn')?.classList.remove('active');

    // Show live-mode-only buttons
    document.getElementById('load-history-button')?.classList.remove('hidden');
    document.getElementById('request-location-button')?.classList.remove('hidden');
    document.getElementById('reset-button')?.classList.remove('hidden');

    // Update title with today's date
    const todayText = formatDateForTitle(new Date());
    const activityTitle = document.getElementById('activity-title');
    if (activityTitle) {
        activityTitle.textContent = `📍 Live Activity - ${todayText}`;
    }
    const mapTitle = document.getElementById('map-title');
    if (mapTitle) {
        mapTitle.textContent = '🗺️ Live Map';
    }

    // Hide time range selector and historic controls but keep precision slider and device selector visible
    document.getElementById('time-range-selector')?.classList.add('hidden');
    document.getElementById('historic-controls')?.classList.add('hidden');
    document.getElementById('precision-slider-container')?.classList.remove('hidden');
    // Precision slider and device selectors stay visible in live mode

    // Clear activity section for live updates
    clearActivitySection('Loading last hour of activity...');
    eventCount = 0;
    lastTimestamp = null; // Reset to allow fresh load

    // Don't clear device selection - respect user's filter choice
    // Clear trails (will be redrawn by loadLiveActivityHistory)
    removeAllTrails();

    // Clear device markers for fresh load
    removeAllDeviceMarkers();
    selectedLocationKey = null;

    // Load last hour of activity data
    loadLiveActivityHistory();

    // Save UI state
    saveUIState();
}

/**
 * Switch to historic mode.
 */
function switchToHistoricMode(): void {
    isLiveMode = false;
    // Only fit bounds if not restoring state (user has saved map position)
    if (!isRestoringState) {
        needsFitBounds = true;
    }

    // Update button states
    document.getElementById('live-mode-btn')?.classList.remove('active');
    document.getElementById('historic-mode-btn')?.classList.add('active');

    // Hide live-mode-only buttons (they're not relevant in historic mode)
    document.getElementById('load-history-button')?.classList.add('hidden');
    document.getElementById('request-location-button')?.classList.add('hidden');
    document.getElementById('reset-button')?.classList.add('hidden');

    // Set date picker to current historic date (or today)
    if (!historicDate) {
        historicDate = getTodayDateString();
    }
    const dateInput = document.getElementById('historic-date') as HTMLInputElement;
    if (dateInput) {
        dateInput.value = historicDate;
        dateInput.max = getTodayDateString();
    }

    // Initialize or update time slider
    initTimeSlider();

    // Update title with date + time range
    const rangeText = getHistoricRangeText();
    const mapTitle = document.getElementById('map-title');
    if (mapTitle) {
        mapTitle.textContent = '🗺️ Historic Map';
    }
    const activityTitle = document.getElementById('activity-title');
    if (activityTitle) {
        activityTitle.textContent = `📅 Historic Trail - ${rangeText}`;
    }

    // Show historic controls
    document.getElementById('historic-controls')?.classList.remove('hidden');
    document.getElementById('precision-slider-container')?.classList.remove('hidden');
    document.getElementById('device-selector')?.classList.remove('hidden');

    // Clear markers (will be restored by fetchAndDisplayTrail)
    removeAllDeviceMarkers();
    selectedLocationKey = null;

    // Fetch and display trail (works for both All Devices and specific device)
    fetchAndDisplayTrail();

    // Save UI state
    saveUIState();
}

// ============================================================================
// Server Health & Network
// ============================================================================

/**
 * Check server health status.
 */
function checkServerHealth(): void {
    fetch('/health/')
        .then(response => {
            if (response.ok) {
                updateServerStatus(true);
            } else {
                updateServerStatus(false);
            }
        })
        .catch(() => {
            updateServerStatus(false);
        });
}

/**
 * Update server status display.
 * @param connected - Whether server is connected
 */
function updateServerStatus(connected: boolean): void {
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const mapEl = document.getElementById('map');
    if (connected) {
        if (statusDot) statusDot.className = 'status-dot connected';
        if (statusText) statusText.textContent = 'Connected';
        mapEl?.classList.remove('connection-disconnected');
        mapEl?.classList.add('connection-connected');
    } else {
        if (statusDot) statusDot.className = 'status-dot disconnected';
        if (statusText) statusText.textContent = 'Disconnected';
        mapEl?.classList.remove('connection-connected');
        mapEl?.classList.add('connection-disconnected');
    }
}

/**
 * Check for network info changes (IP address, hostname).
 */
async function checkNetworkInfo(): Promise<void> {
    try {
        const response = await fetch('/network-info/');
        if (response.ok) {
            const data: NetworkInfo = await response.json();
            const newIP = data.local_ip;
            const ips = data.local_ips || [newIP];

            // Update display elements
            const hostnameEl = document.getElementById('network-hostname');
            if (hostnameEl) hostnameEl.textContent = data.hostname;

            const ipsEl = document.getElementById('network-ips');
            if (ipsEl) {
                ipsEl.innerHTML = ips.map(ip => `<p><code>${ip}</code></p>`).join('');
            }

            const urlsEl = document.getElementById('network-urls');
            if (urlsEl) {
                urlsEl.innerHTML = ips.map(ip => `<p><code>http://${ip}:${data.port}/</code></p>`).join('');
            }

            // Update MQTT hosts
            const mqttHostsEl = document.getElementById('mqtt-hosts');
            if (mqttHostsEl) {
                mqttHostsEl.innerHTML = ips.map(ip => `<p><code>${ip}</code></p>`).join('');
            }

            // If IP changed, show a notification
            if (newIP !== lastKnownIP && lastKnownIP !== 'Unable to detect') {
                console.log(`Network IP changed: ${lastKnownIP} -> ${newIP}`);
                lastKnownIP = newIP;
            }
        }
    } catch {
        // Silently ignore network errors
    }
}

// ============================================================================
// WebSocket Connection
// ============================================================================

/**
 * Connect to WebSocket for real-time updates.
 */
function connectWebSocket(): void {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/locations/`;

    console.log('Connecting to WebSocket:', wsUrl);

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = (): void => {
            console.log('WebSocket connected');
            wsReconnectAttempts = 0;
            lastWebSocketMessageAtMs = Date.now();
        };

        ws.onmessage = (event: MessageEvent): void => {
            try {
                const message: WebSocketMessage = JSON.parse(event.data);
                console.log('WebSocket message received:', message);
                lastWebSocketMessageAtMs = Date.now();

                // Handle welcome message with server version
                if (message.type === 'welcome' && message.server_startup) {
                    if (serverStartupTimestamp === null) {
                        // First connection, store the version
                        serverStartupTimestamp = message.server_startup;
                        console.log('Server startup timestamp:', serverStartupTimestamp);
                        // Refresh device list and live data
                        refreshDeviceSelector();
                        if (isLiveMode) {
                            console.log('WebSocket first connection, refreshing live activity...');
                            refreshLiveActivitySinceLastUpdate();
                        }
                    } else if (serverStartupTimestamp !== message.server_startup) {
                        // Server has restarted, refresh the page
                        console.log(
                            'Server restarted (was:',
                            serverStartupTimestamp,
                            'now:',
                            message.server_startup,
                            '), refreshing page...',
                        );
                        window.location.reload();
                        return;
                    } else {
                        // Same server, but we reconnected - refresh device list and live data
                        console.log('WebSocket reconnected, refreshing device selector and live activity...');
                        refreshDeviceSelector();
                        if (isLiveMode) {
                            refreshLiveActivitySinceLastUpdate();
                        }
                    }
                }

                // Only process messages in live mode
                if (isLiveMode && message.type === 'location' && message.data) {
                    const location = message.data;
                    const deviceName = location.device_name || 'Unknown';
                    console.log(`📍 Live mode location received from ${deviceName}`, location);

                    // Check if we should display this location based on device filter
                    if (selectedDevice && deviceName !== selectedDevice) {
                        console.log(`Ignoring location from ${deviceName} (filter: ${selectedDevice})`);
                        return;
                    }

                    // If skipHistoryFetch is true (after reset), add locations incrementally
                    // instead of fetching history
                    if (skipHistoryFetch) {
                        console.log('📍 Adding location incrementally (skipHistoryFetch mode)');
                        addLogEntry(location);
                        addLocationToTrail(location);
                        return;
                    }

                    // Optimistically update the UI immediately so live updates feel responsive.
                    // We still do a debounced history reload below to reconcile trails and ensure
                    // state remains consistent even after reconnects.
                    addLogEntry(location, true);
                    if (location.timestamp_unix && location.timestamp_unix > (lastTimestamp || 0)) {
                        lastTimestamp = location.timestamp_unix;
                    }
                    addLiveLocationToTrail(location);

                    // Avoid re-fetching and re-rendering the full last-hour history on every
                    // incoming message; it clears/rebuilds the DOM and redraws all trails,
                    // which can make live updates feel laggy. We rely on:
                    // - `addLogEntry()` + `addLiveLocationToTrail()` for instant incremental updates
                    // - `refreshLiveActivitySinceLastUpdate()` on reconnect for reconciliation
                } else if (message.type === 'location' && message.data) {
                    // Not in live mode, but still update the device selector
                    // so new devices appear without needing to switch modes
                    const deviceName = message.data.device_name || 'Unknown';
                    if (ensureDeviceInSelector(deviceName)) {
                        console.log(`📍 New device '${deviceName}' added to selector (historic mode)`);
                    }
                }
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
            }
        };

        ws.onerror = (error: Event): void => {
            console.error('WebSocket error:', error);
        };

        ws.onclose = (): void => {
            console.log('WebSocket disconnected');
            ws = null;
            lastWebSocketMessageAtMs = null;

            // Try to reconnect with exponential backoff
            if (wsReconnectAttempts < maxReconnectAttempts) {
                wsReconnectAttempts++;
                const delay = reconnectDelay * Math.pow(2, wsReconnectAttempts - 1);
                console.log(`Reconnecting in ${delay}ms (attempt ${wsReconnectAttempts})...`);
                setTimeout(connectWebSocket, delay);
            } else {
                console.warn('Max reconnection attempts reached, falling back to polling');
                startPolling();
            }
        };
    } catch (error) {
        console.error('Failed to create WebSocket:', error);
        startPolling();
    }
}

// If a proxy blocks WS upgrades, the browser can appear "connected" but never
// receive location messages. Keep a lightweight watchdog so live mode still
// refreshes via HTTP.
function startWebSocketWatchdog(): void {
    const watchdogIntervalMs = 5000;
    const staleAfterMs = 15000;

    window.setInterval(() => {
        if (!isLiveMode) return;
        if (skipHistoryFetch) return;

        const now = Date.now();
        const last = lastWebSocketMessageAtMs;

        // If we have no WS, or it has gone silent, do an incremental HTTP refresh.
        if (!ws || ws.readyState !== WebSocket.OPEN || !last || (now - last) > staleAfterMs) {
            refreshLiveActivitySinceLastUpdate();
        }
    }, watchdogIntervalMs);
}

// ============================================================================
// Fallback Polling
// ============================================================================

/**
 * Fetch locations for polling fallback.
 */
async function fetchLocations(): Promise<void> {
    try {
        const url = '/api/locations/?ordering=-timestamp&limit=20';

        const response = await fetch(url);
        const data: LocationsApiResponse = await response.json();

        console.log('Fetched data:', data);

        if (data.results && data.results.length > 0) {
            console.log('Processing', data.results.length, 'locations');
            // Process all results (only in live mode)
            if (isLiveMode) {
                const isInitialLoad = lastTimestamp === null;
                const sorted = [...data.results].sort(compareLocationsByTimestampDesc);
                const locsToProcess = isInitialLoad
                    ? [...sorted].sort((a, b) => locationTimestampUnix(a) - locationTimestampUnix(b))
                    : sorted;

                let newestEntry: TrackLocation | null = null;
                for (const loc of locsToProcess) {
                    // Only add if we haven't seen this timestamp yet
                    if (!lastTimestamp || (loc.timestamp_unix && loc.timestamp_unix > lastTimestamp)) {
                        // Skip scrolling during batch load, we'll scroll once at the end
                        addLogEntry(loc, isInitialLoad);
                        if (
                            !newestEntry ||
                            locationTimestampUnix(loc) > locationTimestampUnix(newestEntry)
                        ) {
                            newestEntry = loc;
                        }
                    }
                }

                // After initial batch load, scroll to show the newest entry
                if (isInitialLoad && newestEntry) {
                    // Use setTimeout to ensure DOM is fully rendered before scrolling
                    setTimeout(() => {
                        const container = document.getElementById('log-container');
                        const row = container?.querySelector<HTMLElement>(
                            `[data-location-id="${String(newestEntry!.id)}"]`,
                        );
                        const target = row ?? (container?.firstChild as HTMLElement | null);
                        if (target) {
                            target.scrollIntoView({ behavior: 'instant', block: 'center' });
                        }
                    }, 100);
                }

                // Update last timestamp to the newest one
                if (sorted.length > 0) {
                    lastTimestamp = locationTimestampUnix(sorted[0]) || null;
                }
            }
        }
    } catch (error) {
        console.error('Error fetching locations:', error);
    }
}

/**
 * Start polling fallback for when WebSocket is not available.
 */
function startPolling(): void {
    if (!pollingInterval && isLiveMode) {
        console.log('Starting polling fallback');
        fetchLocations(); // Initial fetch
        pollingInterval = setInterval(fetchLocations, 2000);
    }
}

// ============================================================================
// Resize Handle
// ============================================================================

/**
 * Whether the viewport currently matches the mobile responsive media query.
 * Mirrors the `@media (max-width: 768px)` rule used by main.css.
 */
function isMobileViewport(): boolean {
    return window.matchMedia('(max-width: 768px)').matches;
}

/**
 * Apply the active mobile layout mode (full-screen map, full-screen activity
 * log, or restored split view) by toggling classes on the main container.
 * Only takes effect on phone-sized viewports because the supporting CSS lives
 * inside the mobile media query.
 */
function applyMobileLayoutMode(): void {
    const container = document.getElementById('main-container');
    if (container) {
        container.classList.toggle('mobile-layout-map-only', mobileLayoutMode === 'map-only');
        container.classList.toggle('mobile-layout-table-only', mobileLayoutMode === 'table-only');
    }

    const pressedById: Record<string, MobileLayoutMode> = {
        'resize-show-map-btn': 'map-only',
        'resize-show-split-btn': 'split',
        'resize-show-table-btn': 'table-only',
    };
    for (const [id, mode] of Object.entries(pressedById)) {
        document.getElementById(id)?.setAttribute('aria-pressed', String(mobileLayoutMode === mode));
    }

    if (map) {
        map.invalidateSize();
    }
}

/**
 * Set the active mobile layout mode and persist it so it survives reloads.
 */
function setMobileLayoutMode(mode: MobileLayoutMode): void {
    mobileLayoutMode = mode;
    applyMobileLayoutMode();
    saveUIState();
}

/**
 * Initialize resize handle functionality.
 */
function initResizeHandle(): void {
    const resizeHandle = document.getElementById('resize-handle');
    const mapSection = document.querySelector('.map-section') as HTMLElement | null;
    const activitySection = document.querySelector('.activity-section') as HTMLElement | null;

    if (!resizeHandle || !mapSection || !activitySection) return;

    document.getElementById('resize-show-map-btn')?.addEventListener('click', () => setMobileLayoutMode('map-only'));
    document.getElementById('resize-show-split-btn')?.addEventListener('click', () => setMobileLayoutMode('split'));
    document.getElementById('resize-show-table-btn')?.addEventListener('click', () => setMobileLayoutMode('table-only'));

    applyMobileLayoutMode();

    let isResizing = false;
    let startY = 0;
    let startMapHeight = 0;
    let startActivityHeight = 0;

    // Restore saved panel sizes
    const savedMapHeight = localStorage.getItem('mytracks-map-height');
    if (savedMapHeight) {
        const mapPercent = parseFloat(savedMapHeight);
        // Validate: must be between 10% and 90%
        if (mapPercent >= 10 && mapPercent <= 90) {
            mapSection.style.flex = `${mapPercent} 1 0px`;
            activitySection.style.flex = `${100 - mapPercent} 1 0px`;
        }
        // Otherwise keep CSS defaults (50/50)
    }

    resizeHandle.addEventListener('mousedown', (e: MouseEvent) => {
        // Mobile uses the icon buttons inside the handle; skip the drag flow
        // so taps on the buttons don't accidentally start a resize.
        if (isMobileViewport()) {
            return;
        }
        // Don't start a drag when the user clicks the mobile control buttons
        // (defensive — only reachable if the viewport flips between renders).
        if (e.target instanceof Element && e.target.closest('.resize-mobile-controls')) {
            return;
        }
        isResizing = true;
        startY = e.clientY;
        startMapHeight = mapSection.offsetHeight;
        startActivityHeight = activitySection.offsetHeight;

        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';

        e.preventDefault();
    });

    document.addEventListener('mousemove', (e: MouseEvent) => {
        if (!isResizing) return;

        const deltaY = e.clientY - startY;
        const totalHeight = startMapHeight + startActivityHeight;

        let newMapHeight = startMapHeight + deltaY;
        let newActivityHeight = startActivityHeight - deltaY;

        // Minimum heights (100px each)
        const minHeight = 100;
        if (newMapHeight < minHeight) {
            newMapHeight = minHeight;
            newActivityHeight = totalHeight - minHeight;
        }
        if (newActivityHeight < minHeight) {
            newMapHeight = totalHeight - minHeight;
        }

        const mapPercent = (newMapHeight / totalHeight) * 100;
        mapSection.style.flex = `${mapPercent} 1 0px`;
        activitySection.style.flex = `${100 - mapPercent} 1 0px`;

        // Invalidate map size during resize
        if (map) map!.invalidateSize();
    });

    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;

        document.body.style.cursor = '';
        document.body.style.userSelect = '';

        // Save panel sizes
        const totalHeight = mapSection.offsetHeight + activitySection.offsetHeight;
        const mapPercent = (mapSection.offsetHeight / totalHeight) * 100;
        localStorage.setItem('mytracks-map-height', mapPercent.toString());

        // Final map size invalidation
        if (map) map!.invalidateSize();
    });
}

// ============================================================================
// Event Listeners & Initialization
// ============================================================================

/**
 * Initialize the noUiSlider time range slider.
 * Creates the slider on first call, updates values on subsequent calls.
 */
function initTimeSlider(): void {
    const sliderEl = document.getElementById('time-slider');
    if (!sliderEl) return;

    if (timeSliderApi) {
        // Slider already exists, just update values
        timeSliderApi.set([historicStartMinutes, historicEndMinutes]);
        updateTimeSliderLabel();
        return;
    }

    // Create the slider
    timeSliderApi = noUiSlider.create(sliderEl, {
        start: [historicStartMinutes, historicEndMinutes],
        connect: true,
        range: {
            min: 0,
            max: 1439,
        },
        step: 15, // 15-minute increments
        behaviour: 'drag-tap',
    });

    // Update label on slide
    timeSliderApi.on('update', (values: (string | number)[]) => {
        historicStartMinutes = Math.round(Number(values[0]));
        historicEndMinutes = Math.round(Number(values[1]));
        updateTimeSliderLabel();
    });

    // Fetch trail on release
    timeSliderApi.on('change', () => {
        needsFitBounds = true;

        // Update activity title
        const activityTitle = document.getElementById('activity-title');
        if (activityTitle) {
            activityTitle.textContent = `📅 Historic Trail - ${getHistoricRangeText()}`;
        }

        if (!isLiveMode) {
            fetchAndDisplayTrail();
        }
        saveUIState();
    });
}

/**
 * Initialize all event listeners.
 */
function initEventListeners(): void {
    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }

    // Reset button
    const resetButton = document.getElementById('reset-button');
    if (resetButton) {
        resetButton.addEventListener('click', resetEvents);
    }

    // Load history button
    const loadHistoryButton = document.getElementById('load-history-button');
    if (loadHistoryButton) {
        loadHistoryButton.addEventListener('click', loadLast30Minutes);
    }

    const refreshLiveLatestButton = document.getElementById('refresh-live-latest-button');
    if (refreshLiveLatestButton) {
        refreshLiveLatestButton.addEventListener('click', () => {
            void loadLatestLocations();
        });
    }

    const lastKnownOnlyButton = document.getElementById('last-known-only-button');
    if (lastKnownOnlyButton) {
        lastKnownOnlyButton.addEventListener('click', toggleLastKnownOnly);
    }

    // Request location button
    const requestLocationButton = document.getElementById('request-location-button');
    if (requestLocationButton) {
        requestLocationButton.addEventListener('click', requestDeviceLocations);
    }

    // Device selector
    const deviceSelector = document.getElementById('device-selector') as HTMLSelectElement | null;
    if (deviceSelector) {
        deviceSelector.addEventListener('change', (e: Event) => {
            selectedDevice = (e.target as HTMLSelectElement).value;

            // Clear all markers and trails
            removeAllDeviceMarkers();
            removeAllTrails();
            selectedLocationKey = null;

            // Fit bounds when changing device selection
            needsFitBounds = true;

            // Refresh data based on current mode
            if (isLiveMode) {
                // Clear and reload live activity with filter
                clearActivitySection('Loading last hour of activity...');
                eventCount = 0;
                lastTimestamp = null;
                loadLiveActivityHistory();
            } else {
                fetchAndDisplayTrail();
            }

            // Save UI state
            saveUIState();
        });
    }

    // Time range selector (legacy, kept for backward compat)
    const timeRangeSelector = document.getElementById('time-range-selector') as HTMLSelectElement | null;
    if (timeRangeSelector) {
        timeRangeSelector.addEventListener('change', (e: Event) => {
            timeRangeHours = parseInt((e.target as HTMLSelectElement).value);

            // Update title with new date range
            const dateRangeText = getDateRangeText(timeRangeHours);
            const activityTitle = document.getElementById('activity-title');
            if (activityTitle) {
                activityTitle.textContent = `📅 Historic Trail - ${dateRangeText}`;
            }

            // Fit bounds when changing time range
            needsFitBounds = true;

            // Refresh trail with new time range (only in historic mode)
            if (!isLiveMode) {
                fetchAndDisplayTrail();
            }

            // Save UI state
            saveUIState();
        });
    }

    // Historic date picker
    const historicDateInput = document.getElementById('historic-date') as HTMLInputElement | null;
    if (historicDateInput) {
        historicDateInput.addEventListener('change', (e: Event) => {
            historicDate = (e.target as HTMLInputElement).value;
            needsFitBounds = true;

            // Update activity title
            const activityTitle = document.getElementById('activity-title');
            if (activityTitle) {
                activityTitle.textContent = `📅 Historic Trail - ${getHistoricRangeText()}`;
            }

            if (!isLiveMode) {
                fetchAndDisplayTrail();
            }
            saveUIState();
        });
    }

    // Precision slider (0% = coarse/360, 100% = precise/0)
    const precisionSlider = document.getElementById('precision-slider') as HTMLInputElement | null;
    const precisionValueDisplay = document.getElementById('precision-value');
    if (precisionSlider) {
        precisionSlider.addEventListener('input', (e: Event) => {
            const sliderValue = parseInt((e.target as HTMLInputElement).value);
            // Convert slider percentage (0-100) to resolution (360-0)
            // 0% = 360 (coarse), 100% = 0 (precise)
            trailResolution = Math.round((1 - sliderValue / 100) * 360);

            // Update display
            if (precisionValueDisplay) {
                precisionValueDisplay.textContent = `${sliderValue}%`;
            }
        });

        precisionSlider.addEventListener('change', () => {
            // Refresh trail with new resolution on release
            if (isLiveMode) {
                // Clear existing trails and reload
                removeAllTrails();
                selectedLocationKey = null;
                loadLiveActivityHistory();
            } else {
                fetchAndDisplayTrail();
            }

            // Save UI state
            saveUIState();
        });
    }

    // Mode toggle buttons. On phones the inactive button is hidden by CSS and
    // the visible (active) button acts as a single toggle: clicking it flips
    // the mode regardless of which underlying button received the event.
    const toggleMode = (preferred: 'live' | 'historic'): void => {
        if (isMobileViewport()) {
            if (isLiveMode) {
                switchToHistoricMode();
            } else {
                switchToLiveMode();
            }
            return;
        }
        if (preferred === 'live') {
            switchToLiveMode();
        } else {
            switchToHistoricMode();
        }
    };

    document.getElementById('live-mode-btn')?.addEventListener('click', () => toggleMode('live'));
    document.getElementById('historic-mode-btn')?.addEventListener('click', () => toggleMode('historic'));

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e: MediaQueryListEvent) => {
        if (!localStorage.getItem('theme')) {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible' || !isLiveMode) {
            return;
        }
        if (skipHistoryFetch) {
            void refreshLiveActivitySinceLastUpdate();
        } else if (liveActivityLoadKind === '30m') {
            void loadLast30Minutes();
        } else if (liveActivityLoadKind === 'latest') {
            void loadLatestLocations();
        } else {
            void loadLiveActivityHistory();
        }
        if (map) {
            map.invalidateSize();
        }
    });
}

/**
 * Main initialization function.
 */
function init(): void {
    // Initialize theme
    setTheme(getPreferredTheme());

    // Initialize event listeners
    initEventListeners();

    // Initialize resize handle
    initResizeHandle();

    // Restore UI state from localStorage
    restoreUIState();

    // Initial fetch for historical data (always needed to populate device list)
    fetchLocations();

    // Start WebSocket connection for real-time updates
    connectWebSocket();
    startWebSocketWatchdog();

    // Check health immediately and then every 5 seconds
    checkServerHealth();
    setInterval(checkServerHealth, 5000);

    // Check network info every 30 seconds
    setInterval(checkNetworkInfo, 30000);
}

// Initialize map after page load
window.addEventListener('load', initMap);

// Initialize the application when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
