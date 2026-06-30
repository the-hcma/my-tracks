import { describe, expect, it } from 'vitest';

import {
    compareLocationsByReportTimeDesc,
    formatDurationShort,
    formatFixAgeNote,
    formatFixObservedLogLine,
    formatTriggerLabel,
    locationReportedAtUnix,
} from './locationReport';

describe('locationReportedAtUnix', () => {
    it('prefers reported_at_unix over timestamp_unix', () => {
        expect(
            locationReportedAtUnix({ reported_at_unix: 2000, timestamp_unix: 1000 }),
        ).toBe(2000);
    });

    it('falls back to timestamp_unix', () => {
        expect(locationReportedAtUnix({ timestamp_unix: 1000 })).toBe(1000);
    });
});

describe('formatTriggerLabel', () => {
    it('maps ping trigger', () => {
        expect(formatTriggerLabel('p')).toBe('ping');
    });
});

describe('formatDurationShort', () => {
    it('formats hours and minutes', () => {
        expect(formatDurationShort(6720)).toBe('1h 52m');
    });
});

describe('formatFixAgeNote', () => {
    it('returns null below threshold', () => {
        expect(formatFixAgeNote(30, '12:09 PM')).toBeNull();
    });

    it('describes stale fix relative to report', () => {
        expect(formatFixAgeNote(6720, '12:09 PM')).toBe(
            'Position from 12:09 PM (1h 52m before this report)',
        );
    });
});

describe('formatFixObservedLogLine', () => {
    it('shows fix time when report and fix are close', () => {
        expect(formatFixObservedLogLine('12:09 PM', 5)).toBe('Fix observed: 12:09 PM');
    });

    it('shows stale note when fix predates report', () => {
        expect(formatFixObservedLogLine('12:09 PM', 6720)).toBe(
            'Position from 12:09 PM (1h 52m before this report)',
        );
    });
});

describe('compareLocationsByReportTimeDesc', () => {
    it('sorts newest report first (sort comparator)', () => {
        const newer = { reported_at_unix: 2000, timestamp_unix: 1000 };
        const older = { reported_at_unix: 1500, timestamp_unix: 1500 };
        expect(compareLocationsByReportTimeDesc(newer, older)).toBeLessThan(0);
        expect(compareLocationsByReportTimeDesc(older, newer)).toBeGreaterThan(0);
    });
});
