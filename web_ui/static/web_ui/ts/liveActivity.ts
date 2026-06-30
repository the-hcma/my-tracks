/**
 * Live activity refresh helpers (HTTP is the single source for the activity log).
 */

import { locationReportedAtUnix } from './locationReport';

export type LiveActivityLoadKind = 'hour' | '30m' | 'latest';
export type LiveActivityRefreshRequest = LiveActivityLoadKind | 'incremental';

export interface TrackLocationRow {
    id?: number;
    timestamp_unix?: number;
    reported_at_unix?: number;
}

export interface LiveActivityCursor {
    lastTimestamp: number | null;
    lastSeenLocationId: number | null;
}

export function createLiveActivityCursor(): LiveActivityCursor {
    return {
        lastTimestamp: null,
        lastSeenLocationId: null,
    };
}

export function liveActivityCountLabel(kind: LiveActivityLoadKind): string {
    switch (kind) {
        case '30m':
            return '(last 30min)';
        case 'latest':
            return '(latest)';
        default:
            return '(last hour)';
    }
}

/** True when incremental HTTP refresh can run (full load required otherwise). */
export function canRunIncrementalRefresh(cursor: LiveActivityCursor): boolean {
    return cursor.lastSeenLocationId !== null || cursor.lastTimestamp !== null;
}

/**
 * Build the incremental locations API URL.
 * Prefer since_id (monotonic) over start_time so out-of-order device timestamps are not missed.
 */
export function buildIncrementalLocationsUrl(
    cursor: LiveActivityCursor,
    selectedDevice?: string,
): string | null {
    if (!canRunIncrementalRefresh(cursor)) {
        return null;
    }

    const params = new URLSearchParams();
    if (cursor.lastSeenLocationId !== null) {
        params.set('since_id', String(cursor.lastSeenLocationId));
        params.set('ordering', 'id');
    } else if (cursor.lastTimestamp !== null) {
        params.set('start_time', String(cursor.lastTimestamp));
        params.set('ordering', 'timestamp');
    }
    params.set('limit', '100');
    if (selectedDevice) {
        params.set('device', selectedDevice);
    }
    return `/api/locations/?${params.toString()}`;
}

export function buildBulkLocationsUrl(
    kind: LiveActivityLoadKind,
    nowUnix: number,
    trailResolution: number,
    selectedDevice?: string,
): string {
    let url: string;
    if (kind === '30m') {
        const thirtyMinutesAgo = Math.floor(nowUnix) - 1800;
        url = `/api/locations/?start_time=${thirtyMinutesAgo}&ordering=-timestamp&resolution=${trailResolution}`;
    } else if (kind === 'latest') {
        url = '/api/locations/?ordering=-timestamp&limit=200';
    } else {
        const oneHourAgo = Math.floor(nowUnix) - 3600;
        url = `/api/locations/?start_time=${oneHourAgo}&ordering=-timestamp&resolution=${trailResolution}`;
    }
    if (selectedDevice) {
        url += `&device=${encodeURIComponent(selectedDevice)}`;
    }
    return url;
}

export function buildLocationDetailUrl(locationId: number): string {
    return `/api/locations/${locationId}/`;
}

export function updateCursorFromLocations(
    cursor: LiveActivityCursor,
    locations: TrackLocationRow[],
): LiveActivityCursor {
    let lastTimestamp = cursor.lastTimestamp;
    let lastSeenLocationId = cursor.lastSeenLocationId;

    for (const loc of locations) {
        const ts = locationReportedAtUnix(loc);
        if (lastTimestamp === null || ts > lastTimestamp) {
            lastTimestamp = ts;
        }
        if (loc.id !== undefined && loc.id !== null) {
            if (lastSeenLocationId === null || loc.id > lastSeenLocationId) {
                lastSeenLocationId = loc.id;
            }
        }
    }

    return { lastTimestamp, lastSeenLocationId };
}

/** Sort oldest-first for stable incremental append order (by report time, then id). */
export function sortLocationsOldestFirst<T extends TrackLocationRow>(locations: T[]): T[] {
    return [...locations].sort((a, b) => {
        const aReport = locationReportedAtUnix(a);
        const bReport = locationReportedAtUnix(b);
        if (aReport !== bReport) {
            return aReport - bReport;
        }
        return (a.id ?? 0) - (b.id ?? 0);
    });
}

export function mergeHintLocationIds(queue: number[], hintLocationId?: number): number[] {
    if (hintLocationId === undefined || hintLocationId === null) {
        return queue;
    }
    if (queue.includes(hintLocationId)) {
        return queue;
    }
    return [...queue, hintLocationId];
}
