/**
 * Tests for My Tracks utility functions.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
    boundFetch,
    extractResultsList,
    formatLatLonCoordinate,
    formatLatLonPair,
    hashString,
    selectStablePaletteColor,
    formatTime,
    formatDateForTitle,
    collapseLocations,
    formatDwellDuration,
    formatDwellHoverHtml,
    haversineDistance,
    debounce,
    parseNumeric,
    formatMinutesAsTime,
    getTodayDateString,
    getYesterdayDateString,
    defaultHistoricDateRange,
    historicDatesAfterSameDayToggle,
    applyHistoricMobileDatePick,
    dateAndMinutesToTimestamps,
    historicPeriodToTimestamps,
    inclusiveDaySpan,
    clampHistoricToDate,
    tripSnapshotMaxPoints,
    thinTrailForTripSnapshot,
    prepareHistoricTripLocations,
    historicFetchResolutionSeconds,
    HISTORIC_MAX_SPAN_DAYS,
    restoredHistoricPeriodFromSavedState,
    sameOriginApiPath,
    LocationData,
} from './utils';

describe('boundFetch', () => {
    it('calls global fetch without Illegal invocation', async () => {
        const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
            ok: true,
            status: 200,
            text: async () => '[]',
        } as Response);

        await boundFetch('/api/locations/last-known/', { credentials: 'same-origin' });

        expect(spy).toHaveBeenCalledWith('/api/locations/last-known/', { credentials: 'same-origin' });
        spy.mockRestore();
    });
});

describe('formatLatLonCoordinate', () => {
    it('uses the shared six-decimal latitude/longitude precision by default', () => {
        expect(formatLatLonCoordinate(12.3456789)).toBe('12.345679');
        expect(formatLatLonCoordinate('-98.7654321')).toBe('-98.765432');
    });

    it('formats coordinate pairs with a configurable separator', () => {
        expect(formatLatLonPair(12.3, -98.7)).toBe('12.300000, -98.700000');
        expect(formatLatLonPair('12.3', '-98.7', ',')).toBe('12.300000,-98.700000');
    });
});

describe('hashString', () => {
    it('returns a consistent hash for the same input', () => {
        const hash1 = hashString('test');
        const hash2 = hashString('test');
        expect(hash1).toBe(hash2);
    });

    it('returns different hashes for different inputs', () => {
        const hash1 = hashString('test1');
        const hash2 = hashString('test2');
        expect(hash1).not.toBe(hash2);
    });

    it('returns a positive number', () => {
        expect(hashString('test')).toBeGreaterThanOrEqual(0);
        expect(hashString('')).toBeGreaterThanOrEqual(0);
        expect(hashString('negative')).toBeGreaterThanOrEqual(0);
    });

    it('handles empty string', () => {
        expect(hashString('')).toBe(0);
    });

    it('handles special characters', () => {
        const hash = hashString('device-123/user@home');
        expect(hash).toBeGreaterThanOrEqual(0);
        expect(hash).toBe(hashString('device-123/user@home'));
    });

    it('handles unicode characters', () => {
        const hash = hashString('日本語テスト');
        expect(hash).toBeGreaterThanOrEqual(0);
    });
});

describe('selectStablePaletteColor', () => {
    it('returns the same color for the same key and palette', () => {
        const palette = ['#111111', '#222222', '#333333'];
        expect(selectStablePaletteColor('kristen/pixel7', palette)).toBe(selectStablePaletteColor('kristen/pixel7', palette));
    });

    it('only returns values from the palette', () => {
        const palette = ['#111111', '#222222', '#333333', '#444444'];
        const color = selectStablePaletteColor('hcma/pixel7pro', palette);
        expect(palette).toContain(color);
    });

    it('throws for empty palette', () => {
        expect(() => selectStablePaletteColor('any', [])).toThrow('Palette must not be empty');
    });
});

describe('formatTime', () => {
    // Use a fixed timestamp to avoid timezone issues in tests
    const timestamp = 1704067200; // 2024-01-01 00:00:00 UTC

    it('formats time with hours, minutes, seconds, and timezone', () => {
        const result = formatTime(timestamp, true);
        // Should contain HH:MM:SS followed by a timezone abbreviation
        expect(result).toMatch(/\d{2}:\d{2}:\d{2} [A-Z]{2,5}/);
    });

    it('includes date when includeDate is true', () => {
        const result = formatTime(timestamp, true);
        // Should contain month abbreviation and day
        expect(result).toMatch(/[A-Z][a-z]{2} \d{1,2}/);
    });

    it('includes date for non-today timestamps', () => {
        // Use a timestamp far in the past (local timezone aware)
        const oldDate = new Date('2000-01-15T12:00:00'); // Use noon to avoid date boundary issues
        const oldTimestamp = Math.floor(oldDate.getTime() / 1000);
        const result = formatTime(oldTimestamp);
        // Should contain "Jan 15" in the output
        expect(result).toMatch(/Jan 15/);
    });

    it('shows time with timezone for today timestamps when includeDate is false', () => {
        // Create a timestamp for right now
        const now = Math.floor(Date.now() / 1000);
        const result = formatTime(now, false);
        // Format: HH:MM:SS TZ (e.g., "14:22:17 EST")
        expect(result).toMatch(/^\d{2}:\d{2}:\d{2} [A-Z]{2,5}$/);
    });
});

describe('formatDateForTitle', () => {
    it('formats date with weekday, month, and day', () => {
        const date = new Date('2024-01-15T12:00:00');
        const result = formatDateForTitle(date);
        // Should be like "Mon, Jan 15"
        expect(result).toMatch(/[A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}/);
    });

    it('handles different dates', () => {
        const christmas = new Date('2024-12-25T00:00:00');
        const result = formatDateForTitle(christmas);
        expect(result).toContain('Dec');
        expect(result).toContain('25');
    });
});

describe('collapseLocations', () => {
    it('returns empty array for empty input', () => {
        expect(collapseLocations([])).toEqual([]);
    });

    it('returns single location unchanged (with count)', () => {
        const locations: LocationData[] = [
            { latitude: 51.5074, longitude: -0.1278 },
        ];
        const result = collapseLocations(locations);
        expect(result).toHaveLength(1);
        expect(result[0]._collapsedCount).toBe(1);
    });

    it('collapses consecutive locations at same position', () => {
        const locations: LocationData[] = [
            { latitude: 51.5074, longitude: -0.1278, timestamp_unix: 1000 },
            { latitude: 51.5074, longitude: -0.1278, timestamp_unix: 2000 },
            { latitude: 51.5074, longitude: -0.1278, timestamp_unix: 3000 },
        ];
        const result = collapseLocations(locations);
        expect(result).toHaveLength(1);
        expect(result[0]._collapsedCount).toBe(3);
        expect(result[0].timestamp_unix).toBe(1000); // Should be oldest
        expect(result[0]._dwellSeconds).toBe(2000);
    });

    it('sets zero dwell when timestamps are missing', () => {
        const locations: LocationData[] = [
            { latitude: 51.5074, longitude: -0.1278 },
            { latitude: 51.5074, longitude: -0.1278 },
        ];
        const result = collapseLocations(locations);
        expect(result[0]._dwellSeconds).toBe(0);
    });

    it('keeps distinct locations separate', () => {
        const locations: LocationData[] = [
            { latitude: 51.5074, longitude: -0.1278 },
            { latitude: 48.8566, longitude: 2.3522 },
            { latitude: 40.7128, longitude: -74.006 },
        ];
        const result = collapseLocations(locations);
        expect(result).toHaveLength(3);
        result.forEach((loc) => {
            expect(loc._collapsedCount).toBe(1);
        });
    });

    it('groups consecutive same locations but separates different ones', () => {
        const locations: LocationData[] = [
            { latitude: 51.5074, longitude: -0.1278 }, // London
            { latitude: 51.5074, longitude: -0.1278 }, // London
            { latitude: 48.8566, longitude: 2.3522 }, // Paris
            { latitude: 48.8566, longitude: 2.3522 }, // Paris
            { latitude: 48.8566, longitude: 2.3522 }, // Paris
            { latitude: 51.5074, longitude: -0.1278 }, // London again
        ];
        const result = collapseLocations(locations);
        expect(result).toHaveLength(3);
        expect(result[0]._collapsedCount).toBe(2); // First London group
        expect(result[1]._collapsedCount).toBe(3); // Paris group
        expect(result[2]._collapsedCount).toBe(1); // Second London (new group)
    });

    it('respects precision parameter', () => {
        const locations: LocationData[] = [
            { latitude: 51.50741, longitude: -0.12781 },
            { latitude: 51.50742, longitude: -0.12782 }, // Very slightly different
        ];

        // With high precision (default 5), these should be different
        const result5 = collapseLocations(locations, 5);
        expect(result5).toHaveLength(2);

        // With low precision (2), these should be the same
        const result2 = collapseLocations(locations, 2);
        expect(result2).toHaveLength(1);
        expect(result2[0]._collapsedCount).toBe(2);
    });

    it('handles string coordinates', () => {
        const locations: LocationData[] = [
            { latitude: '51.5074', longitude: '-0.1278' },
            { latitude: '51.5074', longitude: '-0.1278' },
        ];
        const result = collapseLocations(locations);
        expect(result).toHaveLength(1);
        expect(result[0]._collapsedCount).toBe(2);
    });
});

describe('haversineDistance', () => {
    it('returns 0 for same coordinates', () => {
        const distance = haversineDistance(51.5074, -0.1278, 51.5074, -0.1278);
        expect(distance).toBe(0);
    });

    it('calculates distance between London and Paris correctly', () => {
        // London: 51.5074, -0.1278
        // Paris: 48.8566, 2.3522
        // Known distance: approximately 343 km
        const distance = haversineDistance(51.5074, -0.1278, 48.8566, 2.3522);
        expect(distance).toBeGreaterThan(340000);
        expect(distance).toBeLessThan(350000);
    });

    it('calculates distance between New York and Los Angeles correctly', () => {
        // New York: 40.7128, -74.0060
        // Los Angeles: 34.0522, -118.2437
        // Known distance: approximately 3,940 km
        const distance = haversineDistance(40.7128, -74.006, 34.0522, -118.2437);
        expect(distance).toBeGreaterThan(3930000);
        expect(distance).toBeLessThan(3950000);
    });

    it('handles antipodal points', () => {
        // Half the Earth's circumference
        const distance = haversineDistance(0, 0, 0, 180);
        // Should be approximately 20,000 km
        expect(distance).toBeGreaterThan(19900000);
        expect(distance).toBeLessThan(20100000);
    });

    it('is symmetric', () => {
        const d1 = haversineDistance(51.5074, -0.1278, 48.8566, 2.3522);
        const d2 = haversineDistance(48.8566, 2.3522, 51.5074, -0.1278);
        expect(d1).toBeCloseTo(d2, 5);
    });
});

describe('debounce', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('delays function execution', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn, 100);

        debouncedFn();
        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(99);
        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(1);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('resets timer on subsequent calls', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn, 100);

        debouncedFn();
        vi.advanceTimersByTime(50);

        debouncedFn(); // Reset timer
        vi.advanceTimersByTime(50);
        expect(fn).not.toHaveBeenCalled();

        vi.advanceTimersByTime(50);
        expect(fn).toHaveBeenCalledTimes(1);
    });

    it('passes arguments to the original function', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn, 100);

        debouncedFn('arg1', 'arg2');
        vi.advanceTimersByTime(100);

        expect(fn).toHaveBeenCalledWith('arg1', 'arg2');
    });

    it('uses the latest arguments when called multiple times', () => {
        const fn = vi.fn();
        const debouncedFn = debounce(fn, 100);

        debouncedFn('first');
        debouncedFn('second');
        debouncedFn('third');
        vi.advanceTimersByTime(100);

        expect(fn).toHaveBeenCalledTimes(1);
        expect(fn).toHaveBeenCalledWith('third');
    });
});

describe('parseNumeric', () => {
    it('returns numbers as-is', () => {
        expect(parseNumeric(42)).toBe(42);
        expect(parseNumeric(3.14)).toBe(3.14);
        expect(parseNumeric(-10)).toBe(-10);
        expect(parseNumeric(0)).toBe(0);
    });

    it('parses string numbers', () => {
        expect(parseNumeric('42')).toBe(42);
        expect(parseNumeric('3.14')).toBe(3.14);
        expect(parseNumeric('-10')).toBe(-10);
        expect(parseNumeric('0')).toBe(0);
    });

    it('handles scientific notation', () => {
        expect(parseNumeric('1e5')).toBe(100000);
        expect(parseNumeric('1.5e-3')).toBe(0.0015);
    });

    it('returns NaN for non-numeric strings', () => {
        expect(parseNumeric('not a number')).toBeNaN();
        expect(parseNumeric('')).toBeNaN();
    });
});

describe('formatMinutesAsTime', () => {
    it('formats midnight as 00:00', () => {
        expect(formatMinutesAsTime(0)).toBe('00:00');
    });

    it('formats end of day as 23:59', () => {
        expect(formatMinutesAsTime(1439)).toBe('23:59');
    });

    it('formats morning time', () => {
        expect(formatMinutesAsTime(510)).toBe('08:30');
    });

    it('formats afternoon time', () => {
        expect(formatMinutesAsTime(1050)).toBe('17:30');
    });

    it('pads single-digit hours and minutes', () => {
        expect(formatMinutesAsTime(65)).toBe('01:05');
    });

    it('handles 15-minute increments', () => {
        expect(formatMinutesAsTime(15)).toBe('00:15');
        expect(formatMinutesAsTime(45)).toBe('00:45');
        expect(formatMinutesAsTime(720)).toBe('12:00');
    });
});

describe('getTodayDateString', () => {
    it('returns a YYYY-MM-DD formatted string', () => {
        const result = getTodayDateString();
        expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });

    it('matches today\'s date', () => {
        const now = new Date();
        const expected = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        expect(getTodayDateString()).toBe(expected);
    });
});

describe('dateAndMinutesToTimestamps', () => {
    it('returns start and end timestamps for a full day', () => {
        const [start, end] = dateAndMinutesToTimestamps('2026-02-20', 0, 1439);
        // End should be 23:59:59 = 86399 seconds after start
        expect(end - start).toBe(86399);
    });

    it('returns correct timestamps for a time window', () => {
        const [start, end] = dateAndMinutesToTimestamps('2026-02-20', 480, 1020);
        // 480 min = 8:00, 1020 min = 17:00:59 -> 9 hours + 59 seconds = 32459 seconds
        expect(end - start).toBe(32459);
    });

    it('handles midnight to end of day', () => {
        const [start, end] = dateAndMinutesToTimestamps('2026-01-15', 0, 1439);
        const startDate = new Date(start * 1000);
        expect(startDate.getFullYear()).toBe(2026);
        expect(startDate.getMonth()).toBe(0); // January
        expect(startDate.getDate()).toBe(15);
        expect(startDate.getHours()).toBe(0);
        expect(startDate.getMinutes()).toBe(0);
        expect(end - start).toBe(86399);
    });

    it('returns same start with 59s offset when start equals end', () => {
        const [start, end] = dateAndMinutesToTimestamps('2026-02-20', 720, 720);
        // Both at minute 720 but end gets +59 seconds
        expect(end - start).toBe(59);
    });
});

describe('getYesterdayDateString', () => {
    it('returns the local calendar day before today', () => {
        const today = getTodayDateString();
        const [y, m, d] = today.split('-').map(Number);
        const expectedDate = new Date(y, m - 1, d);
        expectedDate.setDate(expectedDate.getDate() - 1);
        const expected = `${expectedDate.getFullYear()}-${String(expectedDate.getMonth() + 1).padStart(2, '0')}-${String(expectedDate.getDate()).padStart(2, '0')}`;
        expect(getYesterdayDateString()).toBe(expected);
    });
});

describe('defaultHistoricDateRange', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2026, 7, 9, 12, 0, 0));
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('defaults both ends to yesterday with same day on', () => {
        const range = defaultHistoricDateRange();
        expect(range.fromDate).toBe('2026-08-08');
        expect(range.toDate).toBe('2026-08-08');
        expect(range.sameDayOnly).toBe(true);
    });
});

describe('restoredHistoricPeriodFromSavedState', () => {
    const staleSaved = {
        historicEndMinutes: 1050,
        historicFromDate: '2020-01-01',
        historicSameDayOnly: true,
        historicStartMinutes: 480,
        historicToDate: '2020-01-01',
    };

    it('skips stale dates on compact UI but restores the time-slider window', () => {
        expect(restoredHistoricPeriodFromSavedState(true, staleSaved)).toEqual({
            endMinutes: 1050,
            startMinutes: 480,
        });
    });

    it('restores dates and minutes on desktop', () => {
        expect(restoredHistoricPeriodFromSavedState(false, staleSaved)).toEqual({
            endMinutes: 1050,
            fromDate: '2020-01-01',
            sameDayOnly: true,
            startMinutes: 480,
            toDate: '2020-01-01',
        });
    });

    it('migrates legacy historicDate on desktop', () => {
        expect(
            restoredHistoricPeriodFromSavedState(false, {
                historicDate: '2026-04-02',
            }),
        ).toEqual({
            fromDate: '2026-04-02',
            sameDayOnly: true,
            toDate: '2026-04-02',
        });
    });

    it('does not invent dates on compact when only a legacy historicDate is saved', () => {
        expect(
            restoredHistoricPeriodFromSavedState(true, {
                historicDate: '2026-04-02',
            }),
        ).toEqual({});
    });
});

describe('historicDatesAfterSameDayToggle', () => {
    it('keeps both ends on from when enabling same day', () => {
        expect(historicDatesAfterSameDayToggle(true, '2026-08-01', '2026-08-07')).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-01',
        });
    });

    it('uses the to date for both ends when disabling same day', () => {
        expect(historicDatesAfterSameDayToggle(false, '2026-08-01', '2026-08-07')).toEqual({
            fromDate: '2026-08-07',
            toDate: '2026-08-07',
        });
    });

    it('falls back to yesterday when both dates are empty on disable', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2026, 7, 9, 12, 0, 0));
        try {
            expect(historicDatesAfterSameDayToggle(false, '', '')).toEqual({
                fromDate: '2026-08-08',
                toDate: '2026-08-08',
            });
        } finally {
            vi.useRealTimers();
        }
    });
});

describe('applyHistoricMobileDatePick', () => {
    it('sets both ends on same-day picks and stays on from', () => {
        expect(applyHistoricMobileDatePick('from', '2026-08-05', true, '2026-08-01')).toEqual({
            fromDate: '2026-08-05',
            toDate: '2026-08-05',
            nextStep: 'from',
        });
    });

    it('uses first range pick as from and advances to to', () => {
        expect(applyHistoricMobileDatePick('from', '2026-08-01', false, '2026-07-20')).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-01',
            nextStep: 'to',
        });
    });

    it('uses second range pick as to and returns to from', () => {
        expect(applyHistoricMobileDatePick('to', '2026-08-07', false, '2026-08-01')).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-07',
            nextStep: 'from',
        });
    });

    it('clamps second range pick to from when earlier', () => {
        expect(applyHistoricMobileDatePick('to', '2026-07-15', false, '2026-08-01')).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-01',
            nextStep: 'from',
        });
    });
});

describe('historicPeriodToTimestamps', () => {
    it('uses minute window for same-day periods', () => {
        const [start, end] = historicPeriodToTimestamps('2026-02-20', '2026-02-20', true, 60, 120);
        const [expectedStart, expectedEnd] = dateAndMinutesToTimestamps('2026-02-20', 60, 120);
        expect(start).toBe(expectedStart);
        expect(end).toBe(expectedEnd);
    });

    it('uses full inclusive days when same-day is off even if from equals to', () => {
        const [start, end] = historicPeriodToTimestamps('2026-02-20', '2026-02-20', false, 60, 120);
        const [expectedStart, expectedEnd] = dateAndMinutesToTimestamps('2026-02-20', 0, 1439);
        expect(start).toBe(expectedStart);
        expect(end).toBe(expectedEnd);
    });

    it('uses full inclusive days for multi-day periods', () => {
        const [start, end] = historicPeriodToTimestamps('2026-02-20', '2026-02-22', false, 60, 120);
        const [expectedStart] = dateAndMinutesToTimestamps('2026-02-20', 0, 1439);
        const [, expectedEnd] = dateAndMinutesToTimestamps('2026-02-22', 0, 1439);
        expect(start).toBe(expectedStart);
        expect(end).toBe(expectedEnd);
    });
});

describe('inclusiveDaySpan and clampHistoricToDate', () => {
    it('counts inclusive calendar days', () => {
        expect(inclusiveDaySpan('2026-02-20', '2026-02-20')).toBe(1);
        expect(inclusiveDaySpan('2026-02-20', '2026-02-26')).toBe(7);
    });

    it('clamps to-date to the max span', () => {
        const clamped = clampHistoricToDate('2026-01-01', '2026-12-31', HISTORIC_MAX_SPAN_DAYS);
        expect(inclusiveDaySpan('2026-01-01', clamped)).toBe(HISTORIC_MAX_SPAN_DAYS);
    });

    it('orders inverted to-date up to from-date', () => {
        expect(clampHistoricToDate('2026-02-20', '2026-02-10')).toBe('2026-02-20');
    });
});

describe('formatDwellDuration', () => {
    it('formats seconds, minutes, and hours', () => {
        expect(formatDwellDuration(45)).toBe('45s');
        expect(formatDwellDuration(90)).toBe('1m');
        expect(formatDwellDuration(3660)).toBe('1h 1m');
        expect(formatDwellDuration(7200)).toBe('2h');
    });
});

describe('formatDwellHoverHtml', () => {
    it('prefers time spent when dwell is present', () => {
        expect(formatDwellHoverHtml(3600, 12)).toContain('Time spent: 1h');
    });

    it('falls back to waypoint count when dwell is zero', () => {
        expect(formatDwellHoverHtml(0, 4)).toContain('4 waypoints');
    });

    it('returns empty for a single non-dwell point', () => {
        expect(formatDwellHoverHtml(0, 1)).toBe('');
    });
});

describe('trip snapshot thinning', () => {
    it('shrinks max points as the span grows', () => {
        expect(tripSnapshotMaxPoints(1, 100)).toBeGreaterThan(tripSnapshotMaxPoints(10, 100));
        expect(tripSnapshotMaxPoints(10, 100)).toBeGreaterThan(tripSnapshotMaxPoints(40, 100));
    });

    it('raises historic fetch resolution for multi-day spans', () => {
        expect(historicFetchResolutionSeconds(1, 0)).toBe(0);
        expect(historicFetchResolutionSeconds(5, 0)).toBe(300);
        expect(historicFetchResolutionSeconds(20, 0)).toBe(600);
        expect(historicFetchResolutionSeconds(45, 0)).toBe(600);
    });

    it('keeps first and last points and reduces middle density', () => {
        const locations: LocationData[] = [];
        for (let i = 0; i < 100; i++) {
            locations.push({
                latitude: 40 + i * 0.01,
                longitude: -74 + (i % 2) * 0.001,
                timestamp_unix: 1_700_000_000 + i * 60,
            });
        }
        const thinned = thinTrailForTripSnapshot(locations, 20);
        expect(thinned.length).toBeLessThanOrEqual(20);
        expect(thinned[0]).toEqual(locations[0]);
        expect(thinned[thinned.length - 1]).toEqual(locations[locations.length - 1]);
    });

    it('collapses dwell then thins for trip preparation', () => {
        const locations: LocationData[] = [
            { latitude: 40, longitude: -74, timestamp_unix: 1000 },
            { latitude: 40, longitude: -74, timestamp_unix: 4000 },
            { latitude: 41, longitude: -74, timestamp_unix: 5000 },
            { latitude: 42, longitude: -74, timestamp_unix: 6000 },
        ];
        const prepared = prepareHistoricTripLocations(locations, 10);
        expect(prepared[0]._dwellSeconds).toBe(3000);
        expect(prepared.length).toBeLessThanOrEqual(3);
    });

    it('force-retains significant dwell points when thinning', () => {
        const locations: LocationData[] = [];
        locations.push({ latitude: 40, longitude: -74, timestamp_unix: 1_000_000 });
        // Long dwell (~20m) near the path — pure RDP would drop an on-line stop
        locations.push({ latitude: 40.05, longitude: -74, timestamp_unix: 1_003_600 });
        locations.push({ latitude: 40.05, longitude: -74, timestamp_unix: 1_004_800 });
        for (let i = 1; i <= 40; i++) {
            locations.push({
                latitude: 40 + i * 0.02,
                longitude: -74 + (i === 20 ? 0.5 : 0),
                timestamp_unix: 1_010_000 + i * 60,
            });
        }
        const prepared = prepareHistoricTripLocations(locations, 12, 5, 900);
        const dwellPoint = prepared.find((loc) => (loc._dwellSeconds ?? 0) >= 900);
        expect(dwellPoint).toBeTruthy();
        expect(prepared.length).toBeLessThanOrEqual(12);
    });

    it('caps retained dwells so the result never exceeds maxPoints', () => {
        const locations: LocationData[] = [];
        for (let stop = 0; stop < 30; stop++) {
            const base = 1_000_000 + stop * 10_000;
            locations.push({ latitude: 40 + stop, longitude: -74, timestamp_unix: base });
            locations.push({ latitude: 40 + stop, longitude: -74, timestamp_unix: base + 2_000 });
        }
        const prepared = prepareHistoricTripLocations(locations, 10, 5, 900);
        expect(prepared.length).toBeLessThanOrEqual(10);
        expect(prepared[0]).toEqual(expect.objectContaining({ latitude: 40 }));
        expect(prepared[prepared.length - 1]).toEqual(expect.objectContaining({ latitude: 69 }));
    });
});

describe('sameOriginApiPath', () => {
    it('returns relative paths unchanged', () => {
        expect(sameOriginApiPath('/api/devices/?offset=100', 'http://localhost')).toBe(
            '/api/devices/?offset=100',
        );
    });

    it('normalizes absolute same-origin pagination URLs', () => {
        expect(
            sameOriginApiPath('http://localhost/api/devices/?offset=100', 'http://localhost'),
        ).toBe('/api/devices/?offset=100');
    });

    it('rejects cross-origin pagination URLs', () => {
        expect(() =>
            sameOriginApiPath('https://evil.example/api/devices/', 'http://localhost'),
        ).toThrow(/cross-origin API URL/);
    });
});

describe('extractResultsList', () => {
    it('returns the array directly when data is already an array', () => {
        const data = [{ id: 1 }, { id: 2 }];
        expect(extractResultsList(data)).toEqual([{ id: 1 }, { id: 2 }]);
    });

    it('unwraps paginated response with results key', () => {
        const data = { count: 2, next: null, previous: null, results: [{ id: 1 }, { id: 2 }] };
        expect(extractResultsList(data)).toEqual([{ id: 1 }, { id: 2 }]);
    });

    it('returns empty array for paginated response with empty results', () => {
        const data = { count: 0, next: null, previous: null, results: [] };
        expect(extractResultsList(data)).toEqual([]);
    });

    it('returns empty array for null', () => {
        expect(extractResultsList(null)).toEqual([]);
    });

    it('returns empty array for undefined', () => {
        expect(extractResultsList(undefined)).toEqual([]);
    });

    it('returns empty array for a plain object without results key', () => {
        expect(extractResultsList({ count: 5 })).toEqual([]);
    });

    it('returns empty array when results is not an array', () => {
        expect(extractResultsList({ results: 'not-an-array' })).toEqual([]);
    });

    it('preserves generic type through extraction', () => {
        interface Device { device_id: string; is_online: boolean }
        const data = { count: 1, results: [{ device_id: 'phone', is_online: true }] };
        const devices: Device[] = extractResultsList<Device>(data);
        expect(devices).toHaveLength(1);
        expect(devices[0].device_id).toBe('phone');
        expect(devices[0].is_online).toBe(true);
    });
});
