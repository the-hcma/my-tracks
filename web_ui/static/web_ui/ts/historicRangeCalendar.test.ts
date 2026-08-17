import { describe, expect, it, vi } from 'vitest';
import {
    applyCalendarSameDayToggle,
    applyRangeDayClick,
    buildMonthCells,
    formatYmd,
    monthTitle,
    rangeStatusText,
    shiftMonth,
} from './historicRangeCalendar';

describe('formatYmd and shiftMonth', () => {
    it('formats local Y-M-D', () => {
        expect(formatYmd(2026, 7, 9)).toBe('2026-08-09');
    });

    it('shifts months across year boundaries', () => {
        expect(shiftMonth('2026-01-15', -1)).toBe('2025-12');
        expect(shiftMonth('2026-12-01', 1)).toBe('2027-01');
    });
});

describe('buildMonthCells', () => {
    it('marks range endpoints and in-range days', () => {
        const cells = buildMonthCells(
            '2026-08',
            { fromDate: '2026-08-01', toDate: '2026-08-03' },
            '2026-08-20',
        );
        const inMonth = cells.filter((c) => c.inMonth);
        expect(inMonth[0]?.isFrom).toBe(true);
        expect(inMonth[2]?.isTo).toBe(true);
        expect(inMonth[1]?.inRange).toBe(true);
        expect(inMonth.find((c) => c.date === '2026-08-21')?.disabled).toBe(true);
    });
});

describe('applyRangeDayClick', () => {
    it('sets both ends when same day is on', () => {
        expect(
            applyRangeDayClick(
                {
                    fromDate: '2026-08-01',
                    toDate: '2026-08-01',
                    sameDayOnly: true,
                    pendingStep: 'from',
                },
                '2026-08-05',
            ),
        ).toEqual({
            fromDate: '2026-08-05',
            toDate: '2026-08-05',
            sameDayOnly: true,
            pendingStep: 'from',
        });
    });

    it('uses first range tap as from and advances to to', () => {
        expect(
            applyRangeDayClick(
                {
                    fromDate: '2026-07-01',
                    toDate: '2026-07-10',
                    sameDayOnly: false,
                    pendingStep: 'from',
                },
                '2026-08-01',
            ),
        ).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-01',
            sameDayOnly: false,
            pendingStep: 'to',
        });
    });

    it('uses second range tap as to and returns to from', () => {
        expect(
            applyRangeDayClick(
                {
                    fromDate: '2026-08-01',
                    toDate: '2026-08-01',
                    sameDayOnly: false,
                    pendingStep: 'to',
                },
                '2026-08-07',
            ),
        ).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-07',
            sameDayOnly: false,
            pendingStep: 'from',
        });
    });

    it('orders inverted second tap', () => {
        expect(
            applyRangeDayClick(
                {
                    fromDate: '2026-08-10',
                    toDate: '2026-08-10',
                    sameDayOnly: false,
                    pendingStep: 'to',
                },
                '2026-08-01',
            ),
        ).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-10',
            sameDayOnly: false,
            pendingStep: 'from',
        });
    });
});

describe('applyCalendarSameDayToggle', () => {
    it('collapses to from when enabling same day', () => {
        expect(applyCalendarSameDayToggle(true, '2026-08-01', '2026-08-07')).toEqual({
            fromDate: '2026-08-01',
            toDate: '2026-08-01',
            sameDayOnly: true,
            pendingStep: 'from',
        });
    });

    it('falls back to yesterday when both dates are empty', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2026, 7, 9, 12, 0, 0));
        try {
            expect(applyCalendarSameDayToggle(true, '', '')).toEqual({
                fromDate: '2026-08-08',
                toDate: '2026-08-08',
                sameDayOnly: true,
                pendingStep: 'from',
            });
        } finally {
            vi.useRealTimers();
        }
    });
});

describe('rangeStatusText and monthTitle', () => {
    it('describes same-day and range prompts', () => {
        expect(
            rangeStatusText({
                fromDate: '2026-08-08',
                toDate: '2026-08-08',
                sameDayOnly: true,
                pendingStep: 'from',
            }),
        ).toContain('2026-08-08');
        expect(
            rangeStatusText({
                fromDate: '2026-08-01',
                toDate: '2026-08-01',
                sameDayOnly: false,
                pendingStep: 'to',
            }),
        ).toContain('pick end');
    });

    it('titles a month in en-US', () => {
        expect(monthTitle('2026-08')).toContain('2026');
        expect(monthTitle('2026-08').toLowerCase()).toContain('august');
    });
});
