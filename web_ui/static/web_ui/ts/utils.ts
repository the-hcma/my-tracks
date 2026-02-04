/**
 * My Tracks - Utility Functions.
 *
 * Pure utility functions that can be tested independently.
 */

/**
 * Location data interface (subset for utils).
 */
export interface LocationData {
    latitude: string | number;
    longitude: string | number;
    timestamp_unix?: number;
    _collapsedCount?: number;
}

/**
 * Hash function for consistent color assignment based on string identifier.
 * Uses a simple djb2-like hash function.
 * @param str - String to hash
 * @returns Positive integer hash value
 */
export function hashString(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
    }
    return Math.abs(hash);
}

/**
 * Format a Unix timestamp for display.
 * @param timestamp - Unix timestamp in seconds
 * @param includeDate - Whether to always include the date
 * @returns Formatted time string
 */
export function formatTime(timestamp: number, includeDate = false): string {
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
 * @returns Formatted date string like "Wed, Jan 15"
 */
export function formatDateForTitle(date: Date): string {
    const options: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

/**
 * Collapse consecutive locations at the same position.
 * Useful for reducing trail complexity when device stays stationary.
 *
 * @param locations - Array of locations in chronological order
 * @param precision - Decimal places for coordinate comparison (default: 5 ≈ 1.1m)
 * @returns Collapsed locations with _collapsedCount property
 */
export function collapseLocations<T extends LocationData>(
    locations: T[],
    precision: number = 5,
): T[] {
    if (locations.length === 0) return [];

    const collapsed: T[] = [];
    let currentGroup: T[] = [locations[0]];
    let currentKey = getLocationKey(locations[0], precision);

    for (let i = 1; i < locations.length; i++) {
        const loc = locations[i];
        const key = getLocationKey(loc, precision);

        if (key === currentKey) {
            // Same location - add to current group
            currentGroup.push(loc);
        } else {
            // New location - save current group and start new one
            // Use the OLDEST (first) location in the group as the representative
            const representative = { ...currentGroup[0], _collapsedCount: currentGroup.length };
            collapsed.push(representative);
            currentGroup = [loc];
            currentKey = key;
        }
    }

    // Don't forget the last group
    if (currentGroup.length > 0) {
        const representative = { ...currentGroup[0], _collapsedCount: currentGroup.length };
        collapsed.push(representative);
    }

    return collapsed;
}

/**
 * Get a string key for a location based on rounded coordinates.
 */
function getLocationKey(location: LocationData, precision: number): string {
    const lat = parseFloat(String(location.latitude)).toFixed(precision);
    const lon = parseFloat(String(location.longitude)).toFixed(precision);
    return `${lat},${lon}`;
}

/**
 * Calculate distance between two coordinates using Haversine formula.
 * @param lat1 - Latitude of first point
 * @param lon1 - Longitude of first point
 * @param lat2 - Latitude of second point
 * @param lon2 - Longitude of second point
 * @returns Distance in meters
 */
export function haversineDistance(
    lat1: number,
    lon1: number,
    lat2: number,
    lon2: number,
): number {
    const R = 6371000; // Earth's radius in meters
    const φ1 = (lat1 * Math.PI) / 180;
    const φ2 = (lat2 * Math.PI) / 180;
    const Δφ = ((lat2 - lat1) * Math.PI) / 180;
    const Δλ = ((lon2 - lon1) * Math.PI) / 180;

    const a =
        Math.sin(Δφ / 2) * Math.sin(Δφ / 2) +
        Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) * Math.sin(Δλ / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

    return R * c;
}

/**
 * Debounce a function - delays execution until after wait milliseconds.
 * @param fn - Function to debounce
 * @param wait - Milliseconds to wait
 * @returns Debounced function
 */
export function debounce<T extends (...args: Parameters<T>) => void>(
    fn: T,
    wait: number,
): (...args: Parameters<T>) => void {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    return (...args: Parameters<T>): void => {
        if (timeoutId !== null) {
            clearTimeout(timeoutId);
        }
        timeoutId = setTimeout(() => {
            fn(...args);
            timeoutId = null;
        }, wait);
    };
}

/**
 * Parse a numeric value from string or number.
 * @param value - String or number value
 * @returns Parsed number
 */
export function parseNumeric(value: string | number): number {
    return typeof value === 'number' ? value : parseFloat(value);
}
