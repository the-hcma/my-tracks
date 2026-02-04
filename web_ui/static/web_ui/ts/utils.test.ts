/**
 * Tests for My Tracks utility functions.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
    hashString,
    formatTime,
    formatDateForTitle,
    collapseLocations,
    haversineDistance,
    debounce,
    parseNumeric,
    LocationData,
} from './utils';

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

describe('formatTime', () => {
    // Use a fixed timestamp to avoid timezone issues in tests
    const timestamp = 1704067200; // 2024-01-01 00:00:00 UTC

    it('formats time with hours, minutes, and seconds', () => {
        const result = formatTime(timestamp, true);
        // The exact format depends on local timezone, but should contain time parts
        expect(result).toMatch(/\d{2}:\d{2}:\d{2}/);
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

    it('shows only time for today timestamps when includeDate is false', () => {
        // Create a timestamp for right now
        const now = Math.floor(Date.now() / 1000);
        const result = formatTime(now, false);
        // When it's today and includeDate is false, should just be time
        // Format: HH:MM:SS
        expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
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
