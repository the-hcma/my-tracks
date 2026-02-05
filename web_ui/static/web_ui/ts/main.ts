/**
 * My Tracks - Main TypeScript application.
 *
 * Frontend for the OwnTracks backend server.
 */

import * as L from 'leaflet';

// Configuration passed from Django template
interface MyTracksConfig {
    hostname: string;
    localIp: string;
    collapsePrecision: number;
}

// Extend Window interface for our config
declare global {
    interface Window {
        MY_TRACKS_CONFIG: MyTracksConfig;
    }
}

const config = window.MY_TRACKS_CONFIG;

// ============================================================================
// Type Definitions
// ============================================================================

/** Location data from the API */
interface TrackLocation {
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

/** Saved UI state for persistence */
interface UIState {
    isLiveMode: boolean;
    selectedDevice: string;
    timeRangeHours: number;
    trailResolution: number;
}

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
    port: number;
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

let lastTimestamp: number | null = null;
let eventCount = 0;
let map: L.Map | null = null;
let deviceMarkers: Record<string, L.CircleMarker> = {};
let deviceTrails: Record<string, TrailElements> = {};
const devices = new Set<string>();
let selectedDevice = '';
let timeRangeHours = 2;
let trailResolution = 0; // 0 = precise (all points), 360 = coarse (~10/hour)
let isLiveMode = true; // Track current mode
let needsFitBounds = true; // Only fit bounds on initial trail load
let isRestoringState = false; // Flag to prevent saving during restore

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
let deviceColorMap: Record<string, string> = {}; // Maps device name to color
let deviceColorIndex = 0; // Sequential index for color assignment

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
let liveUpdateDebounceTimer: ReturnType<typeof setTimeout> | null = null;
const liveUpdateDebounceDelay = 500; // 500ms debounce for trail updates
const maxReconnectAttempts = 5;
const reconnectDelay = 3000;
let serverStartupTimestamp: string | null = null; // Track server version

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
    deviceColorIndex = 0;
}

/**
 * Show device color legend when viewing multiple devices (up to 5).
 * @param deviceNames - Array of device names to show in legend
 */
function showDeviceLegend(deviceNames: string[]): void {
    const legend = document.getElementById('device-legend');
    if (!legend) return;

    // Filter out empty/undefined names
    const validNames = deviceNames.filter(name => name && name.trim() !== '');

    // Only show legend for 2-5 devices
    if (validNames.length < 2 || validNames.length > 5) {
        legend.classList.add('hidden');
        return;
    }

    // Build legend HTML
    let html = '<div class="device-legend-title">Devices</div>';
    console.log('Building legend with names:', validNames);
    validNames.forEach(name => {
        const color = getDeviceColor(name);
        console.log('Adding legend item:', name, 'with color:', color);
        html += `
            <div class="device-legend-item">
                <div class="device-legend-color" style="background-color: ${color};"></div>
                <span class="device-legend-name">${name}</span>
            </div>
        `;
    });
    console.log('Legend HTML:', html);

    legend.innerHTML = html;
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

/**
 * Get color for a device - assigns colors sequentially for maximum visual difference.
 * Colors are assigned in order of first appearance, using a palette ordered for maximum contrast.
 * @param deviceName - Name of the device
 * @returns Hex color string
 */
function getDeviceColor(deviceName: string): string {
    if (!deviceColorMap[deviceName]) {
        // Assign next color in sequence (palette is ordered for max difference)
        deviceColorMap[deviceName] = deviceColors[deviceColorIndex % deviceColors.length];
        deviceColorIndex++;
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
    const timeStr = `${hours}:${minutes}:${seconds}`;

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

    // Restore time range
    if (state.timeRangeHours) {
        timeRangeHours = state.timeRangeHours;
        const timeRangeSelector = document.getElementById('time-range-selector') as HTMLSelectElement;
        if (timeRangeSelector) {
            timeRangeSelector.value = String(timeRangeHours);
        }
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
// Theme Management
// ============================================================================

/**
 * Get the user's preferred theme.
 * @returns 'dark' or 'light'
 */
function getPreferredTheme(): string {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        return savedTheme;
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * Set the application theme.
 * @param theme - 'dark' or 'light'
 */
function setTheme(theme: string): void {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
        toggle.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
}

/**
 * Toggle between dark and light themes.
 */
function toggleTheme(): void {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
}

// ============================================================================
// Sidebar Management
// ============================================================================

/**
 * Get the sidebar collapsed state.
 * @returns true if sidebar should be collapsed
 */
function getSidebarState(): boolean {
    // Default to collapsed, but respect user preference if set
    const saved = localStorage.getItem('sidebar-collapsed');
    if (saved === null) {
        return true; // Default: collapsed
    }
    return saved === 'true';
}

/**
 * Set the sidebar collapsed state.
 * @param collapsed - Whether sidebar should be collapsed
 */
function setSidebarState(collapsed: boolean): void {
    const container = document.getElementById('main-container');
    const toggle = document.getElementById('sidebar-toggle');
    if (collapsed) {
        container?.classList.add('sidebar-collapsed');
        if (toggle) toggle.textContent = '◀'; // Point left to expand (show sidebar)
    } else {
        container?.classList.remove('sidebar-collapsed');
        if (toggle) toggle.textContent = '▶'; // Point right to collapse (hide sidebar)
    }
    localStorage.setItem('sidebar-collapsed', String(collapsed));
    // Invalidate map size after transition
    setTimeout(() => {
        if (map) map!.invalidateSize();
    }, 350);
}

/**
 * Toggle the sidebar collapsed state.
 */
function toggleSidebar(): void {
    const container = document.getElementById('main-container');
    const isCollapsed = container?.classList.contains('sidebar-collapsed');
    setSidebarState(!isCollapsed);
}

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
    const lat = parseFloat(String(location.latitude)).toFixed(6);
    const lon = parseFloat(String(location.longitude)).toFixed(6);
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
 * Update device marker on map.
 * @param location - Location data
 */
function updateDeviceMarker(location: TrackLocation): void {
    const deviceName = location.device_name || 'Unknown';
    const lat = parseFloat(String(location.latitude));
    const lon = parseFloat(String(location.longitude));

    if (isNaN(lat) || isNaN(lon)) return;

    // Add device to set and update selector
    if (!devices.has(deviceName)) {
        devices.add(deviceName);
        const selector = document.getElementById('device-selector') as HTMLSelectElement;
        if (selector) {
            const option = document.createElement('option');
            option.value = deviceName;
            option.textContent = deviceName;
            selector.appendChild(option);
        }

        // Try to complete state restoration if we just added the pending device
        if (pendingRestoreState && pendingRestoreState.selectedDevice === deviceName) {
            completeStateRestore();
        }
    }

    // In live mode, filter by selection if set; in historic mode, also filter
    if (selectedDevice && selectedDevice !== deviceName) {
        // Hide marker if it exists
        if (deviceMarkers[deviceName]) {
            deviceMarkers[deviceName].remove();
            delete deviceMarkers[deviceName];
        }
        // Also hide trail if it exists
        if (deviceTrails[deviceName]) {
            if (deviceTrails[deviceName].polyline) deviceTrails[deviceName].polyline.remove();
            if (deviceTrails[deviceName].markers) deviceTrails[deviceName].markers.forEach((m) => m.remove());
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

    // Center map on the marker in live mode only (when a single device is selected or first marker)
    if (isLiveMode && (selectedDevice === deviceName || !selectedDevice)) {
        map!.setView(latLng, map!.getZoom());
    }
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
            return `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
        }

        const data = await response.json();
        return data.display_name || `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
    } catch (error) {
        console.error('Geocoding error:', error);
        return `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
    }
}

/**
 * Queue-based geocoding to prevent overwhelming the API.
 * @param lat - Latitude
 * @param lon - Longitude
 * @returns Promise resolving to address string
 */
async function getAddress(lat: number, lon: number): Promise<string> {
    const key = `${lat.toFixed(6)},${lon.toFixed(6)}`;

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

// ============================================================================
// Trail Drawing
// ============================================================================

/**
 * Draw trails for live mode - shows last hour of movement per device.
 * @param locationsByDevice - Locations grouped by device name
 */
function drawLiveTrails(locationsByDevice: Record<string, TrackLocation[]>): void {
    // Clear existing trails first
    Object.values(deviceTrails).forEach(trail => {
        if (trail.polyline) trail.polyline.remove();
        if (trail.markers) trail.markers.forEach((m) => m.remove());
    });
    deviceTrails = {};

    // Draw trail for each device
    Object.entries(locationsByDevice).forEach(([deviceName, locations]) => {
        if (locations.length === 0) return;

        const deviceColor = getDeviceColor(deviceName);

        // Locations are newest-first, reverse for chronological trail
        const chronological = [...locations].reverse();

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

            trailElements.markers.push(marker);
        });

        deviceTrails[deviceName] = trailElements;
    });

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
    const now = Date.now() / 1000;
    const startTime = now - timeRangeHours * 3600;

    // Clear existing trails
    Object.values(deviceTrails).forEach(trail => {
        if (trail.polyline) trail.polyline.remove();
        if (trail.markers) trail.markers.forEach((m) => m.remove());
    });
    deviceTrails = {};

    if (!selectedDevice) {
        // "All Devices" selected - show trails and numbered waypoints for each device
        // Reset color assignments so colors are distributed optimally for visible devices
        resetDeviceColors();
        try {
            let url = `/api/locations/?start_time=${Math.floor(startTime)}&ordering=-timestamp&limit=1000`;
            if (trailResolution > 0) {
                url += `&resolution=${trailResolution}`;
            }
            const response = await fetch(url);
            if (!response.ok) return;

            const data: LocationsApiResponse = await response.json();
            const locations = data.results || [];

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

            // Show legend if 2-5 devices (after colors are assigned below)
            const deviceNames = Object.keys(locationsByDevice);

            // Create trails and numbered waypoints for each device
            Object.entries(locationsByDevice).forEach(([deviceName, deviceLocations]) => {
                if (deviceLocations.length === 0) return;

                // Get locations in chronological order (oldest first)
                const chronologicalLocations = deviceLocations
                    .filter(loc => loc.latitude && loc.longitude)
                    .reverse();

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

            // Show legend for 2-5 devices (colors have now been assigned)
            showDeviceLegend(deviceNames);

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
        let url = `/api/locations/?device=${selectedDevice}&start_time=${Math.floor(startTime)}&ordering=-timestamp&limit=1000`;
        if (trailResolution > 0) {
            url += `&resolution=${trailResolution}`;
        }
        const response = await fetch(url);
        if (!response.ok) return;

        const data: LocationsApiResponse = await response.json();
        const locations = data.results || [];

        // Hide legend when viewing single device
        hideDeviceLegend();

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
        const chronologicalLocations = locations.filter(loc => loc.latitude && loc.longitude).reverse();

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

        // Build display entries with device info and per-device waypoint numbers
        interface DisplayEntry {
            loc: TrackLocation;
            deviceName: string;
            waypointNumber: number;
            deviceColor: string;
        }

        const displayEntries: DisplayEntry[] = [];

        Object.entries(locationsByDevice).forEach(([deviceName, deviceLocations]) => {
            // Collapse per device (API returns newest first, reverse for chronological)
            const chronological = [...deviceLocations].reverse();
            const collapsedLocations = collapseLocations(chronological);

            // Create entries with waypoint numbers (oldest = #1)
            collapsedLocations.forEach((loc, index) => {
                displayEntries.push({
                    loc,
                    deviceName,
                    waypointNumber: index + 1,
                    deviceColor: getDeviceColor(deviceName),
                });
            });
        });

        // Sort all entries by timestamp (newest first for display)
        displayEntries.sort((a, b) => (b.loc.timestamp_unix || 0) - (a.loc.timestamp_unix || 0));

        // Display entries
        displayEntries.forEach(({ loc, deviceName, waypointNumber, deviceColor }) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = formatTime(loc.timestamp_unix || 0, true);
            const lat = parseFloat(String(loc.latitude)).toFixed(6);
            const lon = parseFloat(String(loc.longitude)).toFixed(6);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const collapsedCount = loc._collapsedCount || 1;

            const countBadge =
                collapsedCount > 1
                    ? `<span style="background:#6c757d;color:white;padding:1px 5px;border-radius:10px;font-size:10px;margin-left:8px;">×${collapsedCount}</span>`
                    : '';

            // Show device name with color indicator (at end of line)
            const deviceBadge = `<span style="background:${deviceColor};color:white;padding:1px 6px;border-radius:10px;font-size:11px;margin-left:8px;">${deviceName}</span>`;

            entry.innerHTML = `<span class="log-time"><b>#${waypointNumber}</b> ${time}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}%</span>${countBadge}${deviceBadge}`;

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
        displayLocations.forEach((loc, index) => {
            const waypointNumber = collapsedLocations.length - index; // Oldest = #1, newest = #N
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = formatTime(loc.timestamp_unix || 0, true); // Always show date in historic view
            const lat = parseFloat(String(loc.latitude)).toFixed(6);
            const lon = parseFloat(String(loc.longitude)).toFixed(6);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const collapsedCount = loc._collapsedCount || 1;

            // Show count badge at end of line if multiple waypoints were collapsed
            const countBadge =
                collapsedCount > 1
                    ? `<span style="background:#6c757d;color:white;padding:1px 5px;border-radius:10px;font-size:10px;margin-left:8px;">×${collapsedCount}</span>`
                    : '';

            entry.innerHTML = `<span class="log-time"><b>#${waypointNumber}</b> ${time}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}%</span>${countBadge}`;

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

    const entry = document.createElement('div');
    entry.className = 'log-entry';

    const time = formatTime(location.timestamp_unix || 0, true); // Show date for context
    const device = location.device_name || 'Unknown';
    const deviceId = location.device_id_display || 'N/A';
    const trackerId = location.tid_display || '';
    const lat = parseFloat(String(location.latitude)).toFixed(6);
    const lon = parseFloat(String(location.longitude)).toFixed(6);
    const acc = location.accuracy || 'N/A';
    const alt = location.altitude || 0;
    const vel = location.velocity || 0;
    const batt = location.battery_level || 'N/A';
    const conn = location.connection_type === 'w' ? 'WiFi' : location.connection_type === 'm' ? 'Mobile' : 'N/A';
    const ip = location.ip_address || 'N/A';

    // Show device with tracker ID if available
    let deviceDisplay = device;
    if (trackerId) {
        deviceDisplay = `${device} (${trackerId})`;
    } else if (device !== deviceId) {
        deviceDisplay = `${device} (${deviceId})`;
    }

    entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-device">${deviceDisplay}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>`;

    container.insertBefore(entry, container.firstChild);

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
 * Reset events in the activity section.
 */
function resetEvents(): void {
    const container = document.getElementById('log-container');
    if (container) {
        container.innerHTML = '<p id="loading">Waiting for location updates...</p>';
    }
    eventCount = 0;
    const logCount = document.getElementById('log-count');
    if (logCount) {
        logCount.textContent = '0 events';
    }
}

// ============================================================================
// Live Activity
// ============================================================================

/**
 * Load last hour of live activity data.
 */
async function loadLiveActivityHistory(): Promise<void> {
    const now = Date.now() / 1000;
    const oneHourAgo = now - 3600; // 1 hour in seconds

    // Build URL with device filter if set
    let url = `/api/locations/?start_time=${Math.floor(oneHourAgo)}&ordering=-timestamp&limit=500`;
    if (selectedDevice) {
        url += `&device=${selectedDevice}`;
    }
    // Apply resolution filtering (same as historic mode)
    if (trailResolution > 0) {
        url += `&resolution=${trailResolution}`;
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

        // Display locations (already newest first from API)
        locations.forEach((loc, index) => {
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = formatTime(loc.timestamp_unix || 0, true); // Show date for context
            const device = loc.device_name || 'Unknown';
            const deviceId = loc.device_id_display || 'N/A';
            const trackerId = loc.tid_display || '';
            const lat = parseFloat(String(loc.latitude)).toFixed(6);
            const lon = parseFloat(String(loc.longitude)).toFixed(6);
            const acc = loc.accuracy || 'N/A';
            const alt = loc.altitude || 0;
            const vel = loc.velocity || 0;
            const batt = loc.battery_level || 'N/A';
            const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
            const ip = loc.ip_address || 'N/A';

            // Group locations by device for trail drawing
            if (!locationsByDevice[device]) {
                locationsByDevice[device] = [];
            }
            locationsByDevice[device].push(loc);

            let deviceDisplay = device;
            if (trackerId) {
                deviceDisplay = `${device} (${trackerId})`;
            } else if (device !== deviceId) {
                deviceDisplay = `${device} (${deviceId})`;
            }

            // Add color indicator for device
            const deviceColor = getDeviceColor(device);
            entry.innerHTML = `<span class="log-time">${time}</span> | <span class="log-device" style="color:${deviceColor}">${deviceDisplay}</span> | <span class="log-ip">${ip}</span> | <span class="log-coords">${lat}, ${lon}</span> | <span class="log-meta">acc:${acc}m alt:${alt}m vel:${vel}km/h batt:${batt}% ${conn}</span>`;

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

        // Add each new location (already in chronological order)
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

    // Update button states
    document.getElementById('live-mode-btn')?.classList.add('active');
    document.getElementById('historic-mode-btn')?.classList.remove('active');

    // Hide device legend in live mode
    hideDeviceLegend();

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

    // Hide time range selector but keep precision slider and device selector visible
    document.getElementById('time-range-selector')?.classList.add('hidden');
    document.getElementById('precision-slider-container')?.classList.remove('hidden');
    // Precision slider and device selectors stay visible in live mode

    // Clear activity section for live updates
    clearActivitySection('Loading last hour of activity...');
    eventCount = 0;
    lastTimestamp = null; // Reset to allow fresh load

    // Don't clear device selection - respect user's filter choice
    // Clear trails (will be redrawn by loadLiveActivityHistory)
    Object.values(deviceTrails).forEach(trail => {
        if (trail.polyline) trail.polyline.remove();
        if (trail.markers) trail.markers.forEach((m) => m.remove());
    });
    deviceTrails = {};

    // Clear device markers for fresh load
    Object.values(deviceMarkers).forEach((marker) => marker.remove());
    deviceMarkers = {};

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

    // Update title with date range
    const dateRangeText = getDateRangeText(timeRangeHours);
    const mapTitle = document.getElementById('map-title');
    if (mapTitle) {
        mapTitle.textContent = '🗺️ Historic Map';
    }
    const activityTitle = document.getElementById('activity-title');
    if (activityTitle) {
        activityTitle.textContent = `📅 Historic Trail - ${dateRangeText}`;
    }

    // Show historic controls
    document.getElementById('time-range-selector')?.classList.remove('hidden');
    document.getElementById('precision-slider-container')?.classList.remove('hidden');
    document.getElementById('device-selector')?.classList.remove('hidden');

    // Clear markers (will be restored by fetchAndDisplayTrail)
    Object.values(deviceMarkers).forEach((marker) => marker.remove());
    deviceMarkers = {};

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
    if (connected) {
        if (statusDot) statusDot.className = 'status-dot connected';
        if (statusText) statusText.textContent = 'Connected';
    } else {
        if (statusDot) statusDot.className = 'status-dot disconnected';
        if (statusText) statusText.textContent = 'Disconnected';
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

            // Update display elements
            const hostnameEl = document.getElementById('network-hostname');
            if (hostnameEl) hostnameEl.textContent = data.hostname;

            const ipEl = document.getElementById('network-ip');
            if (ipEl) ipEl.textContent = newIP;

            const urlEl = document.getElementById('network-url');
            if (urlEl) urlEl.textContent = `http://${newIP}:${data.port}/`;

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
        };

        ws.onmessage = (event: MessageEvent): void => {
            try {
                const message: WebSocketMessage = JSON.parse(event.data);
                console.log('WebSocket message received:', message);

                // Handle welcome message with server version
                if (message.type === 'welcome' && message.server_startup) {
                    if (serverStartupTimestamp === null) {
                        // First connection, store the version
                        serverStartupTimestamp = message.server_startup;
                        console.log('Server startup timestamp:', serverStartupTimestamp);
                        // Refresh live data in case we missed anything during initial connection
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
                        // Same server, but we reconnected - refresh live data to catch up on missed updates
                        console.log('WebSocket reconnected, refreshing live activity...');
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

                    console.log(`📍 Scheduling live activity refresh (debounced ${liveUpdateDebounceDelay}ms)`);
                    // Debounce trail reload to prevent rapid consecutive API calls
                    // loadLiveActivityHistory() clears and repopulates the log, so we
                    // don't need to call addLogEntry() here - it would just be overwritten
                    if (liveUpdateDebounceTimer) {
                        clearTimeout(liveUpdateDebounceTimer);
                        console.log('📍 Cleared existing debounce timer');
                    }
                    liveUpdateDebounceTimer = setTimeout(() => {
                        console.log('📍 Debounce fired, calling loadLiveActivityHistory()');
                        loadLiveActivityHistory();
                        liveUpdateDebounceTimer = null;
                    }, liveUpdateDebounceDelay);
                } else if (message.type === 'location') {
                    console.log(`📍 Location received but not in live mode (isLiveMode=${isLiveMode})`);
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
                // On initial load, show recent history in chronological order
                // Results come in newest-first, so reverse for initial display
                const isInitialLoad = lastTimestamp === null;
                const locsToProcess = isInitialLoad ? [...data.results].reverse() : data.results;

                let newestEntry: TrackLocation | null = null;
                for (const loc of locsToProcess) {
                    // Only add if we haven't seen this timestamp yet
                    if (!lastTimestamp || (loc.timestamp_unix && loc.timestamp_unix > lastTimestamp)) {
                        // Skip scrolling during batch load, we'll scroll once at the end
                        addLogEntry(loc, isInitialLoad);
                        newestEntry = loc;
                    }
                }

                // After initial batch load, scroll to show the newest entry
                if (isInitialLoad && newestEntry) {
                    // Use setTimeout to ensure DOM is fully rendered before scrolling
                    setTimeout(() => {
                        const container = document.getElementById('log-container');
                        if (container?.firstChild) {
                            (container.firstChild as HTMLElement).scrollIntoView({ behavior: 'instant', block: 'center' });
                        }
                    }, 100);
                }

                // Update last timestamp to the newest one
                if (data.results.length > 0) {
                    lastTimestamp = data.results[0].timestamp_unix || null;
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
 * Initialize resize handle functionality.
 */
function initResizeHandle(): void {
    const resizeHandle = document.getElementById('resize-handle');
    const mapSection = document.querySelector('.map-section') as HTMLElement | null;
    const activitySection = document.querySelector('.activity-section') as HTMLElement | null;

    if (!resizeHandle || !mapSection || !activitySection) return;

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
            mapSection.style.flex = `0 0 ${mapPercent}%`;
            activitySection.style.flex = `0 0 ${100 - mapPercent}%`;
        }
        // Otherwise keep CSS defaults (50/50)
    }

    resizeHandle.addEventListener('mousedown', (e: MouseEvent) => {
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
            newActivityHeight = minHeight;
            newMapHeight = totalHeight - minHeight;
        }

        const mapPercent = (newMapHeight / totalHeight) * 100;
        mapSection.style.flex = `0 0 ${mapPercent}%`;
        activitySection.style.flex = `0 0 ${100 - mapPercent}%`;

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
 * Initialize all event listeners.
 */
function initEventListeners(): void {
    // Sidebar toggle
    const sidebarToggle = document.getElementById('sidebar-toggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', toggleSidebar);
    }

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

    // Device selector
    const deviceSelector = document.getElementById('device-selector') as HTMLSelectElement | null;
    if (deviceSelector) {
        deviceSelector.addEventListener('change', (e: Event) => {
            selectedDevice = (e.target as HTMLSelectElement).value;

            // Clear all markers and trails
            Object.values(deviceMarkers).forEach((marker) => marker.remove());
            deviceMarkers = {};
            Object.values(deviceTrails).forEach(trail => {
                if (trail.polyline) trail.polyline.remove();
                if (trail.markers) trail.markers.forEach((m) => m.remove());
            });
            deviceTrails = {};

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

    // Time range selector
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
                Object.values(deviceTrails).forEach(trail => {
                    if (trail.polyline) trail.polyline.remove();
                    if (trail.markers) trail.markers.forEach((m) => m.remove());
                });
                deviceTrails = {};
                loadLiveActivityHistory();
            } else {
                fetchAndDisplayTrail();
            }

            // Save UI state
            saveUIState();
        });
    }

    // Mode toggle buttons
    const liveModeBtn = document.getElementById('live-mode-btn');
    if (liveModeBtn) {
        liveModeBtn.addEventListener('click', switchToLiveMode);
    }

    const historicModeBtn = document.getElementById('historic-mode-btn');
    if (historicModeBtn) {
        historicModeBtn.addEventListener('click', switchToHistoricMode);
    }

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e: MediaQueryListEvent) => {
        if (!localStorage.getItem('theme')) {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });
}

/**
 * Main initialization function.
 */
function init(): void {
    // Initialize sidebar state
    setSidebarState(getSidebarState());

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
