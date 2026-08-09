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
    /** Seconds from first to last fix in a collapsed dwell group. */
    _dwellSeconds?: number;
}

/** Hard cap on historic calendar span (inclusive day count). */
export const HISTORIC_MAX_SPAN_DAYS = 90;

/** Soft-warn threshold for long historic ranges. */
export const HISTORIC_WARN_SPAN_DAYS = 30;

export const LAT_LON_DECIMAL_PLACES = 6;

/** Window.fetch throws "Illegal invocation" when passed unbound as a callback. */
export const boundFetch: typeof fetch = (...args: Parameters<typeof fetch>) => globalThis.fetch(...args);

export function formatLatLonCoordinate(
    coordinate: string | number,
    precision = LAT_LON_DECIMAL_PLACES,
): string {
    return parseFloat(String(coordinate)).toFixed(precision);
}

export function formatLatLonPair(
    latitude: string | number,
    longitude: string | number,
    separator = ', ',
    precision = LAT_LON_DECIMAL_PLACES,
): string {
    return `${formatLatLonCoordinate(latitude, precision)}${separator}${formatLatLonCoordinate(longitude, precision)}`;
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
 * Select a stable color from a palette based on a string key.
 * The returned color is deterministic for a given key and palette.
 *
 * @param key - Identifier used to pick a color (e.g. "kristen/pixel7")
 * @param palette - Non-empty list of colors
 * @returns A color string from the palette
 */
export function selectStablePaletteColor(key: string, palette: readonly string[]): string {
    if (palette.length === 0) {
        throw new Error('Palette must not be empty');
    }
    const index = hashString(key) % palette.length;
    return palette[index];
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
 * @returns Formatted date string like "Wed, Jan 15"
 */
export function formatDateForTitle(date: Date): string {
    const options: Intl.DateTimeFormatOptions = { weekday: 'short', month: 'short', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

/**
 * Seconds spent in a consecutive same-position group (first → last fix).
 */
export function dwellSecondsForGroup<T extends LocationData>(group: T[]): number {
    if (group.length === 0) {
        return 0;
    }
    const first = group[0].timestamp_unix;
    const last = group[group.length - 1].timestamp_unix;
    if (first === undefined || last === undefined) {
        return 0;
    }
    return Math.max(0, last - first);
}

/**
 * Collapse consecutive locations at the same position.
 * Useful for reducing trail complexity when device stays stationary.
 *
 * @param locations - Array of locations in chronological order
 * @param precision - Decimal places for coordinate comparison (default: 5 ≈ 1.1m)
 * @returns Collapsed locations with _collapsedCount and _dwellSeconds
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
            const representative = {
                ...currentGroup[0],
                _collapsedCount: currentGroup.length,
                _dwellSeconds: dwellSecondsForGroup(currentGroup),
            };
            collapsed.push(representative);
            currentGroup = [loc];
            currentKey = key;
        }
    }

    // Don't forget the last group
    if (currentGroup.length > 0) {
        const representative = {
            ...currentGroup[0],
            _collapsedCount: currentGroup.length,
            _dwellSeconds: dwellSecondsForGroup(currentGroup),
        };
        collapsed.push(representative);
    }

    return collapsed;
}

/**
 * Format a dwell duration for tooltips (e.g. "45m", "2h 15m").
 */
export function formatDwellDuration(totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    if (seconds < 60) {
        return `${seconds}s`;
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours === 0) {
        return `${minutes}m`;
    }
    if (minutes === 0) {
        return `${hours}h`;
    }
    return `${hours}h ${minutes}m`;
}

/**
 * HTML fragment describing time spent at a collapsed location (empty if none).
 */
export function formatDwellHoverHtml(dwellSeconds: number | undefined, collapsedCount: number | undefined): string {
    const dwell = dwellSeconds ?? 0;
    const count = collapsedCount ?? 1;
    if (dwell <= 0 && count <= 1) {
        return '';
    }
    if (dwell > 0) {
        return `<br><i>Time spent: ${formatDwellDuration(dwell)}</i>`;
    }
    return `<br><i>(${count} waypoints)</i>`;
}

/**
 * Inclusive calendar-day span between YYYY-MM-DD strings (local interpretation).
 */
export function inclusiveDaySpan(fromDate: string, toDate: string): number {
    const [fy, fm, fd] = fromDate.split('-').map(Number);
    const [ty, tm, td] = toDate.split('-').map(Number);
    const from = Date.UTC(fy, fm - 1, fd);
    const to = Date.UTC(ty, tm - 1, td);
    if (Number.isNaN(from) || Number.isNaN(to) || to < from) {
        return 1;
    }
    return Math.floor((to - from) / 86_400_000) + 1;
}

/**
 * Aggressive per-device point budget for historic trip snapshots.
 * Longer spans keep fewer points; precisionPercent (0–100) scales within the band.
 */
export function tripSnapshotMaxPoints(daySpan: number, precisionPercent: number): number {
    const span = Math.max(1, daySpan);
    const base =
        span <= 1 ? 350 :
        span <= 7 ? 200 :
        span <= 30 ? 120 :
        80;
    const scale = 0.25 + 0.75 * Math.min(100, Math.max(0, precisionPercent)) / 100;
    return Math.max(20, Math.round(base * scale));
}

/**
 * Minimum server `resolution` (seconds) for historic fetches so long ranges stay small.
 */
export function historicFetchResolutionSeconds(daySpan: number, trailResolution: number): number {
    // Keep floor ≤ significant-dwell threshold so client dwell collapse still sees
    // multiple fixes for mid-length stays on long vacation ranges.
    const spanFloor =
        daySpan <= 1 ? 0 :
        daySpan <= 7 ? 300 :
        daySpan <= 30 ? 600 :
        600;
    return Math.max(trailResolution, spanFloor);
}

/**
 * Ramer–Douglas–Peucker simplification keeping first/last and high-deviation points.
 */
export function thinTrailForTripSnapshot<T extends LocationData>(
    locations: T[],
    maxPoints: number,
): T[] {
    if (locations.length <= maxPoints || maxPoints < 2) {
        if (locations.length <= maxPoints) {
            return locations;
        }
        return [locations[0], locations[locations.length - 1]];
    }

    const points = locations.map((loc) => ({
        lat: parseFloat(String(loc.latitude)),
        lon: parseFloat(String(loc.longitude)),
    }));

    // Binary-search epsilon (meters) until kept count fits the budget.
    let low = 0;
    let high = 50_000;
    let bestKeep = new Set<number>([0, locations.length - 1]);

    for (let iter = 0; iter < 24; iter++) {
        const epsilon = (low + high) / 2;
        const keep = rdpKeepIndices(points, epsilon);
        if (keep.size > maxPoints) {
            low = epsilon;
        } else {
            bestKeep = keep;
            high = epsilon;
        }
    }

    // If still over budget (very noisy path), keep evenly spaced indices among RDP survivors.
    let indices = [...bestKeep].sort((a, b) => a - b);
    if (indices.length > maxPoints) {
        const thinned = [indices[0]];
        const step = (indices.length - 1) / (maxPoints - 1);
        for (let i = 1; i < maxPoints - 1; i++) {
            thinned.push(indices[Math.round(i * step)]);
        }
        thinned.push(indices[indices.length - 1]);
        indices = [...new Set(thinned)].sort((a, b) => a - b);
    }

    return indices.map((i) => locations[i]);
}

function rdpKeepIndices(
    points: { lat: number; lon: number }[],
    epsilonMeters: number,
): Set<number> {
    const keep = new Set<number>();
    if (points.length === 0) {
        return keep;
    }
    keep.add(0);
    keep.add(points.length - 1);

    const stack: [number, number][] = [[0, points.length - 1]];
    while (stack.length > 0) {
        const [start, end] = stack.pop()!;
        if (end <= start + 1) {
            continue;
        }
        let maxDist = 0;
        let maxIdx = start;
        const a = points[start];
        const b = points[end];
        for (let i = start + 1; i < end; i++) {
            const dist = perpendicularDistanceMeters(points[i], a, b);
            if (dist > maxDist) {
                maxDist = dist;
                maxIdx = i;
            }
        }
        if (maxDist > epsilonMeters) {
            keep.add(maxIdx);
            stack.push([start, maxIdx], [maxIdx, end]);
        }
    }
    return keep;
}

function perpendicularDistanceMeters(
    point: { lat: number; lon: number },
    lineStart: { lat: number; lon: number },
    lineEnd: { lat: number; lon: number },
): number {
    if (lineStart.lat === lineEnd.lat && lineStart.lon === lineEnd.lon) {
        return haversineDistance(point.lat, point.lon, lineStart.lat, lineStart.lon);
    }
    // Equirectangular projection around the segment midpoint for local meters.
    const midLat = ((lineStart.lat + lineEnd.lat) / 2) * Math.PI / 180;
    const toXY = (p: { lat: number; lon: number }): [number, number] => {
        const x = (p.lon * Math.PI / 180) * Math.cos(midLat) * 6_371_000;
        const y = (p.lat * Math.PI / 180) * 6_371_000;
        return [x, y];
    };
    const [px, py] = toXY(point);
    const [ax, ay] = toXY(lineStart);
    const [bx, by] = toXY(lineEnd);
    const dx = bx - ax;
    const dy = by - ay;
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
    const qx = ax + t * dx;
    const qy = ay + t * dy;
    return Math.hypot(px - qx, py - qy);
}

/**
 * Collapse dwells then thin to a trip-snapshot budget (per device).
 * Significant dwell points are preferentially retained (longest first),
 * but the result never exceeds maxPoints.
 */
export function prepareHistoricTripLocations<T extends LocationData>(
    locations: T[],
    maxPoints: number,
    precision: number = 5,
    minDwellSeconds: number = 900,
): T[] {
    const collapsed = collapseLocations(locations, precision);
    if (collapsed.length <= maxPoints) {
        return collapsed;
    }

    const budget = Math.max(2, maxPoints);
    const endpoints = new Set<T>([collapsed[0], collapsed[collapsed.length - 1]]);
    const dwellSlots = Math.max(0, budget - endpoints.size);
    const significantDwells = collapsed
        .filter((loc) => (loc._dwellSeconds ?? 0) >= minDwellSeconds && !endpoints.has(loc))
        .sort((a, b) => (b._dwellSeconds ?? 0) - (a._dwellSeconds ?? 0))
        .slice(0, dwellSlots);
    const forced = new Set<T>([...endpoints, ...significantDwells]);
    const remainingBudget = Math.max(0, budget - forced.size);
    if (remainingBudget === 0) {
        return collapsed.filter((loc) => forced.has(loc));
    }

    const optional = collapsed.filter((loc) => !forced.has(loc));
    const keptOptional = thinTrailForTripSnapshot(
        [collapsed[0], ...optional, collapsed[collapsed.length - 1]],
        Math.max(2, remainingBudget + 2),
    ).filter((loc) => optional.includes(loc));
    // Prefer longest optional geometry keepers within remaining budget.
    const optionalKeep = keptOptional.slice(0, remainingBudget);
    const finalKeep = new Set<T>([...forced, ...optionalKeep]);
    return collapsed.filter((loc) => finalKeep.has(loc));
}

/**
 * Clamp `toDate` so the inclusive span from `fromDate` does not exceed maxDays.
 * Always returns a valid to-date that is >= fromDate.
 */
export function clampHistoricToDate(fromDate: string, toDate: string, maxDays = HISTORIC_MAX_SPAN_DAYS): string {
    const orderedTo = toDate < fromDate ? fromDate : toDate;
    const span = inclusiveDaySpan(fromDate, orderedTo);
    if (span <= maxDays) {
        return orderedTo;
    }
    const [fy, fm, fd] = fromDate.split('-').map(Number);
    const capped = new Date(fy, fm - 1, fd);
    capped.setDate(capped.getDate() + maxDays - 1);
    const year = capped.getFullYear();
    const month = String(capped.getMonth() + 1).padStart(2, '0');
    const day = String(capped.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
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

/**
 * Format minutes since midnight as HH:MM.
 * @param minutes - Minutes since midnight (0-1439)
 * @returns Formatted time string like "08:30"
 */
export function formatMinutesAsTime(minutes: number): string {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * Get today's date as YYYY-MM-DD string.
 * @returns Date string
 */
export function getTodayDateString(): string {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

/**
 * Get yesterday's local date as YYYY-MM-DD.
 */
export function getYesterdayDateString(): string {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

/** Default Historic period: yesterday for both ends, Same day on. */
export type HistoricDateRangeState = {
    fromDate: string;
    toDate: string;
    sameDayOnly: boolean;
};

/**
 * Fresh Historic defaults when no saved period exists.
 */
export function defaultHistoricDateRange(): HistoricDateRangeState {
    const yesterday = getYesterdayDateString();
    return {
        fromDate: yesterday,
        toDate: yesterday,
        sameDayOnly: true,
    };
}

/**
 * Update from/to after the Same day checkbox changes.
 *
 * When enabling Same day, To tracks From.
 * When disabling Same day, both ends start at the current To day (falls back to
 * From, then yesterday) so the range opens on the single-day selection.
 */
export function historicDatesAfterSameDayToggle(
    sameDayOnly: boolean,
    fromDate: string,
    toDate: string,
): Pick<HistoricDateRangeState, 'fromDate' | 'toDate'> {
    if (sameDayOnly) {
        const day = fromDate || toDate || getYesterdayDateString();
        return { fromDate: day, toDate: day };
    }
    const day = toDate || fromDate || getYesterdayDateString();
    return { fromDate: day, toDate: day };
}

/** Which end the compact (mobile) historic calendar is editing next. */
export type HistoricMobilePickStep = 'from' | 'to';

/**
 * Apply a date picked from the compact historic calendar.
 *
 * Same day: both ends follow the pick and the next step stays From.
 * Range mode: first pick sets From (and To to match); second pick sets To,
 * then the next step returns to From.
 */
export function applyHistoricMobileDatePick(
    step: HistoricMobilePickStep,
    pickedDate: string,
    sameDayOnly: boolean,
    fromDate: string,
): { fromDate: string; toDate: string; nextStep: HistoricMobilePickStep } {
    if (sameDayOnly || step === 'from') {
        return {
            fromDate: pickedDate,
            toDate: pickedDate,
            nextStep: sameDayOnly ? 'from' : 'to',
        };
    }
    let nextTo = pickedDate;
    const nextFrom = fromDate;
    if (nextTo < nextFrom) {
        nextTo = nextFrom;
    }
    return { fromDate: nextFrom, toDate: nextTo, nextStep: 'from' };
}

/**
 * Compute start and end Unix timestamps from a date string and minute offsets.
 * @param dateStr - Date string in YYYY-MM-DD format
 * @param startMinutes - Start time as minutes from midnight (0-1439)
 * @param endMinutes - End time as minutes from midnight (0-1439)
 * @returns [startTimestamp, endTimestamp] in seconds
 */
export function dateAndMinutesToTimestamps(
    dateStr: string,
    startMinutes: number,
    endMinutes: number,
): [number, number] {
    const [year, month, day] = dateStr.split('-').map(Number);
    const dayStart = new Date(year, month - 1, day);
    const startTimestamp = dayStart.getTime() / 1000 + startMinutes * 60;
    // Add 59 seconds to include the full last minute (e.g., 23:59 → 23:59:59)
    const endTimestamp = dayStart.getTime() / 1000 + endMinutes * 60 + 59;
    return [startTimestamp, endTimestamp];
}

/**
 * Historic period timestamps: same-day checkbox uses minute window; otherwise full inclusive days.
 */
export function historicPeriodToTimestamps(
    fromDate: string,
    toDate: string,
    sameDayOnly: boolean,
    startMinutes: number,
    endMinutes: number,
): [number, number] {
    if (sameDayOnly) {
        return dateAndMinutesToTimestamps(fromDate, startMinutes, endMinutes);
    }
    const [start] = dateAndMinutesToTimestamps(fromDate, 0, 1439);
    const [, end] = dateAndMinutesToTimestamps(toDate, 0, 1439);
    return [start, end];
}

/**
 * Extract an array from a potentially paginated API response.
 *
 * DRF's LimitOffsetPagination wraps results as `{count, results: [...]}`.
 * This helper normalises both paginated and plain-array responses into a
 * flat array so callers don't need to know the response shape.
 */
/**
 * Normalize a DRF pagination URL to a same-origin path for browser fetch().
 * Throws when the URL targets a different origin (would fail from the browser).
 */
export function sameOriginApiPath(
    url: string,
    origin = typeof globalThis.location !== 'undefined' ? globalThis.location.origin : 'http://localhost',
): string {
    if (url.startsWith('/')) {
        return url;
    }
    const parsed = new URL(url, origin);
    if (parsed.origin !== origin) {
        throw new Error(`cross-origin API URL: ${url}`);
    }
    return `${parsed.pathname}${parsed.search}`;
}

export function extractResultsList<T>(data: unknown): T[] {
    if (Array.isArray(data)) {
        return data as T[];
    }
    if (data !== null && typeof data === 'object' && 'results' in data) {
        const results = (data as Record<string, unknown>).results;
        if (Array.isArray(results)) {
            return results as T[];
        }
    }
    return [];
}
