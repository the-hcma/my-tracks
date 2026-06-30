/**
 * Tests for live activity HTTP refresh helpers.
 */
import { describe, it, expect } from 'vitest';
import {
    buildBulkLocationsUrl,
    buildIncrementalLocationsUrl,
    buildLocationDetailUrl,
    canRunIncrementalRefresh,
    createLiveActivityCursor,
    liveActivityCountLabel,
    mergeHintLocationIds,
    sortLocationsOldestFirst,
    updateCursorFromLocations,
} from './liveActivity';

describe('liveActivityCountLabel', () => {
    it('labels hour, 30m, and latest loads', () => {
        expect(liveActivityCountLabel('hour')).toBe('(last hour)');
        expect(liveActivityCountLabel('30m')).toBe('(last 30min)');
        expect(liveActivityCountLabel('latest')).toBe('(latest)');
    });
});

describe('buildIncrementalLocationsUrl', () => {
    it('returns null when cursor is empty', () => {
        expect(buildIncrementalLocationsUrl(createLiveActivityCursor())).toBeNull();
    });

    it('prefers since_id over start_time', () => {
        const url = buildIncrementalLocationsUrl({
            lastTimestamp: 1_700_000_000,
            lastSeenLocationId: 31370,
        });
        expect(url).toContain('since_id=31370');
        expect(url).toContain('ordering=id');
        expect(url).not.toContain('start_time=');
    });

    it('falls back to start_time when only timestamp is known', () => {
        const url = buildIncrementalLocationsUrl({
            lastTimestamp: 1_700_000_000,
            lastSeenLocationId: null,
        });
        expect(url).toContain('start_time=1700000000');
        expect(url).toContain('ordering=timestamp');
    });

    it('does not use start_time+1 (gte on last timestamp, dedupe by id in UI)', () => {
        const url = buildIncrementalLocationsUrl({
            lastTimestamp: 1_700_000_000,
            lastSeenLocationId: null,
        });
        expect(url).not.toContain('start_time=1700000001');
    });

    it('includes device filter when set', () => {
        const url = buildIncrementalLocationsUrl(
            { lastTimestamp: null, lastSeenLocationId: 42 },
            'kristen/pixel7',
        );
        expect(url).toContain('device=kristen%2Fpixel7');
    });
});

describe('buildBulkLocationsUrl', () => {
    it('builds hour window with resolution', () => {
        const url = buildBulkLocationsUrl('hour', 1_700_003_600, 0);
        expect(url).toContain('start_time=1700000000');
        expect(url).toContain('resolution=0');
    });
});

describe('updateCursorFromLocations', () => {
    it('tracks max timestamp and location id', () => {
        const cursor = updateCursorFromLocations(createLiveActivityCursor(), [
            { id: 10, timestamp_unix: 100 },
            { id: 12, timestamp_unix: 90 },
            { id: 11, timestamp_unix: 110 },
        ]);
        expect(cursor.lastTimestamp).toBe(110);
        expect(cursor.lastSeenLocationId).toBe(12);
    });

    it('picks up newer id even when timestamp is older (out-of-order devices)', () => {
        const cursor = updateCursorFromLocations(
            { lastTimestamp: 200, lastSeenLocationId: 50 },
            [{ id: 31371, timestamp_unix: 150 }],
        );
        expect(cursor.lastSeenLocationId).toBe(31371);
        expect(cursor.lastTimestamp).toBe(200);
    });
});

describe('canRunIncrementalRefresh', () => {
    it('is false for empty cursor', () => {
        expect(canRunIncrementalRefresh(createLiveActivityCursor())).toBe(false);
    });

    it('is true when lastSeenLocationId is set', () => {
        expect(
            canRunIncrementalRefresh({ lastTimestamp: null, lastSeenLocationId: 1 }),
        ).toBe(true);
    });
});

describe('sortLocationsOldestFirst', () => {
    it('orders by timestamp ascending', () => {
        const sorted = sortLocationsOldestFirst([
            { id: 2, timestamp_unix: 200 },
            { id: 1, timestamp_unix: 100 },
        ]);
        expect(sorted.map((l) => l.id)).toEqual([1, 2]);
    });
});

describe('mergeHintLocationIds', () => {
    it('appends unique hint ids', () => {
        expect(mergeHintLocationIds([1, 2], 3)).toEqual([1, 2, 3]);
        expect(mergeHintLocationIds([1, 2], 2)).toEqual([1, 2]);
    });
});

describe('buildLocationDetailUrl', () => {
    it('points at the location detail endpoint', () => {
        expect(buildLocationDetailUrl(31371)).toBe('/api/locations/31371/');
    });
});

describe('incremental refresh scenario', () => {
    it('fetches location 31371 after cursor 31370 even with older timestamp', () => {
        const cursor = { lastTimestamp: 1_748_000_000, lastSeenLocationId: 31370 };
        const url = buildIncrementalLocationsUrl(cursor);
        expect(url).toContain('since_id=31370');
        const next = updateCursorFromLocations(cursor, [{ id: 31371, timestamp_unix: 1_747_999_000 }]);
        expect(next.lastSeenLocationId).toBe(31371);
    });

    it('advances cursor lastTimestamp using reported_at_unix when present', () => {
        const cursor = { lastTimestamp: 1_748_000_000, lastSeenLocationId: 10 };
        const next = updateCursorFromLocations(cursor, [
            { id: 11, timestamp_unix: 1_747_000_000, reported_at_unix: 1_749_000_000 },
        ]);
        expect(next.lastTimestamp).toBe(1_749_000_000);
    });
});
