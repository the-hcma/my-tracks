/**
 * Mobile historic range calendar: month-grid helpers and popover UI.
 *
 * Desktop continues to use native From/To date inputs; this module is for the
 * compact (max-width: 768px) toolbar where one calendar picks From/To with an
 * in-panel Same day checkbox.
 */

import { clampHistoricToDate, getYesterdayDateString, HISTORIC_MAX_SPAN_DAYS } from './utils';

export type HistoricRangePickStep = 'from' | 'to';

export type HistoricRangeSelection = {
    fromDate: string;
    toDate: string;
    sameDayOnly: boolean;
    pendingStep: HistoricRangePickStep;
};

export type MonthCell = {
    /** YYYY-MM-DD when inMonth, otherwise empty. */
    date: string;
    dayOfMonth: number;
    inMonth: boolean;
    /** True when date is after today (local). */
    disabled: boolean;
    inRange: boolean;
    isFrom: boolean;
    isTo: boolean;
};

const WEEKDAY_LABELS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'] as const;

export function formatYmd(year: number, monthIndex0: number, day: number): string {
    const month = String(monthIndex0 + 1).padStart(2, '0');
    const d = String(day).padStart(2, '0');
    return `${year}-${month}-${d}`;
}

export function parseYmd(dateStr: string): { year: number; monthIndex0: number; day: number } {
    const [year, month, day] = dateStr.split('-').map(Number);
    return { year, monthIndex0: month - 1, day };
}

/** Shift a YYYY-MM-DD (or YYYY-MM) by `delta` months; returns YYYY-MM for the month view. */
export function shiftMonth(anchorDate: string, delta: number): string {
    const { year, monthIndex0 } = parseYmd(
        anchorDate.length === 7 ? `${anchorDate}-01` : anchorDate,
    );
    const d = new Date(year, monthIndex0 + delta, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function monthTitle(yearMonth: string): string {
    const { year, monthIndex0 } = parseYmd(`${yearMonth}-01`);
    return new Date(year, monthIndex0, 1).toLocaleDateString('en-US', {
        month: 'long',
        year: 'numeric',
    });
}

/**
 * Build a 6×7 (or shorter) calendar grid for one month.
 * Leading/trailing padding cells have inMonth=false.
 */
export function buildMonthCells(
    yearMonth: string,
    selection: Pick<HistoricRangeSelection, 'fromDate' | 'toDate'>,
    today: string,
): MonthCell[] {
    const { year, monthIndex0 } = parseYmd(`${yearMonth}-01`);
    const firstDow = new Date(year, monthIndex0, 1).getDay();
    const daysInMonth = new Date(year, monthIndex0 + 1, 0).getDate();
    const from = selection.fromDate;
    const to = selection.toDate >= selection.fromDate ? selection.toDate : selection.fromDate;

    const cells: MonthCell[] = [];
    for (let i = 0; i < firstDow; i += 1) {
        cells.push({
            date: '',
            dayOfMonth: 0,
            inMonth: false,
            disabled: true,
            inRange: false,
            isFrom: false,
            isTo: false,
        });
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
        const date = formatYmd(year, monthIndex0, day);
        cells.push({
            date,
            dayOfMonth: day,
            inMonth: true,
            disabled: date > today,
            inRange: Boolean(from && to && date >= from && date <= to),
            isFrom: date === from,
            isTo: date === to,
        });
    }
    return cells;
}

/**
 * Apply a day tap inside the range calendar.
 * Same day: both ends = picked. Range: first tap From, second tap To (clamped).
 */
export function applyRangeDayClick(
    selection: HistoricRangeSelection,
    pickedDate: string,
    maxSpanDays = HISTORIC_MAX_SPAN_DAYS,
): HistoricRangeSelection {
    if (selection.sameDayOnly) {
        return {
            fromDate: pickedDate,
            toDate: pickedDate,
            sameDayOnly: true,
            pendingStep: 'from',
        };
    }
    if (selection.pendingStep === 'from') {
        return {
            fromDate: pickedDate,
            toDate: pickedDate,
            sameDayOnly: false,
            pendingStep: 'to',
        };
    }
    let fromDate = selection.fromDate;
    let toDate = pickedDate;
    if (toDate < fromDate) {
        fromDate = pickedDate;
        toDate = selection.fromDate;
    }
    toDate = clampHistoricToDate(fromDate, toDate, maxSpanDays);
    return {
        fromDate,
        toDate,
        sameDayOnly: false,
        pendingStep: 'from',
    };
}

export function applyCalendarSameDayToggle(
    sameDayOnly: boolean,
    fromDate: string,
    toDate: string,
): HistoricRangeSelection {
    if (sameDayOnly) {
        const day = fromDate || toDate || getYesterdayDateString();
        return {
            fromDate: day,
            toDate: day,
            sameDayOnly: true,
            pendingStep: 'from',
        };
    }
    const from = fromDate || toDate || getYesterdayDateString();
    return {
        fromDate: from,
        toDate: toDate || from,
        sameDayOnly: false,
        pendingStep: 'from',
    };
}

export function rangeStatusText(selection: HistoricRangeSelection): string {
    if (selection.sameDayOnly) {
        return selection.fromDate ? `Day: ${selection.fromDate}` : 'Pick a day';
    }
    if (selection.pendingStep === 'from') {
        return selection.fromDate && selection.toDate && selection.fromDate !== selection.toDate
            ? `${selection.fromDate} → ${selection.toDate}`
            : 'Pick start date';
    }
    return `From ${selection.fromDate} — pick end date`;
}

export type HistoricRangeCalendarCallbacks = {
    getState: () => {
        fromDate: string;
        toDate: string;
        sameDayOnly: boolean;
    };
    onApply: (state: {
        fromDate: string;
        toDate: string;
        sameDayOnly: boolean;
    }) => void;
    getToday: () => string;
    maxSpanDays?: number;
};

export type HistoricRangeCalendarApi = {
    open: () => void;
    close: () => void;
    isOpen: () => boolean;
    destroy: () => void;
};

/**
 * Mount a mobile range-calendar popover. Caller supplies an anchor (toolbar control).
 */
export function createHistoricRangeCalendar(
    anchor: HTMLElement,
    callbacks: HistoricRangeCalendarCallbacks,
): HistoricRangeCalendarApi {
    const maxSpanDays = callbacks.maxSpanDays ?? HISTORIC_MAX_SPAN_DAYS;
    let draft: HistoricRangeSelection = {
        fromDate: '',
        toDate: '',
        sameDayOnly: true,
        pendingStep: 'from',
    };
    let viewMonth = '';
    let open = false;

    const backdrop = document.createElement('div');
    backdrop.className = 'historic-range-backdrop';
    backdrop.hidden = true;

    const panel = document.createElement('div');
    panel.className = 'historic-range-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', 'Historic date range');
    panel.tabIndex = -1;
    panel.hidden = true;

    const header = document.createElement('div');
    header.className = 'historic-range-header';

    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'historic-range-nav';
    prevBtn.setAttribute('aria-label', 'Previous month');
    prevBtn.textContent = '‹';

    const titleEl = document.createElement('h3');
    titleEl.className = 'historic-range-title';

    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'historic-range-nav';
    nextBtn.setAttribute('aria-label', 'Next month');
    nextBtn.textContent = '›';

    header.append(prevBtn, titleEl, nextBtn);

    const weekdays = document.createElement('div');
    weekdays.className = 'historic-range-weekdays';
    for (const label of WEEKDAY_LABELS) {
        const el = document.createElement('span');
        el.textContent = label;
        weekdays.append(el);
    }

    const grid = document.createElement('div');
    grid.className = 'historic-range-grid';

    const status = document.createElement('p');
    status.className = 'historic-range-status';
    status.setAttribute('aria-live', 'polite');

    const sameDayRow = document.createElement('label');
    sameDayRow.className = 'historic-range-same-day';
    const sameDayCb = document.createElement('input');
    sameDayCb.type = 'checkbox';
    sameDayCb.className = 'historic-range-same-day-cb';
    const sameDayText = document.createElement('span');
    sameDayText.textContent = 'Same day';
    sameDayRow.append(sameDayCb, sameDayText);

    const actions = document.createElement('div');
    actions.className = 'historic-range-actions';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn historic-range-cancel';
    cancelBtn.textContent = 'Cancel';
    const doneBtn = document.createElement('button');
    doneBtn.type = 'button';
    doneBtn.className = 'btn historic-range-done';
    doneBtn.textContent = 'Done';
    actions.append(cancelBtn, doneBtn);

    panel.append(header, weekdays, grid, status, sameDayRow, actions);
    document.body.append(backdrop, panel);

    const renderGrid = (): void => {
        const today = callbacks.getToday();
        titleEl.textContent = monthTitle(viewMonth);
        status.textContent = rangeStatusText(draft);
        sameDayCb.checked = draft.sameDayOnly;
        grid.replaceChildren();
        for (const cell of buildMonthCells(viewMonth, draft, today)) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'historic-range-day';
            if (!cell.inMonth) {
                btn.classList.add('historic-range-day-outside');
                btn.disabled = true;
                btn.textContent = '';
                grid.append(btn);
                continue;
            }
            btn.textContent = String(cell.dayOfMonth);
            btn.dataset.date = cell.date;
            if (cell.disabled) {
                btn.disabled = true;
            }
            if (cell.inRange) {
                btn.classList.add('historic-range-day-in-range');
            }
            if (cell.isFrom) {
                btn.classList.add('historic-range-day-from');
            }
            if (cell.isTo) {
                btn.classList.add('historic-range-day-to');
            }
            btn.addEventListener('click', () => {
                if (!cell.date || cell.disabled) {
                    return;
                }
                draft = applyRangeDayClick(draft, cell.date, maxSpanDays);
                renderGrid();
            });
            grid.append(btn);
        }
    };

    const positionPanel = (): void => {
        const rect = anchor.getBoundingClientRect();
        const margin = 8;
        const panelWidth = Math.min(320, window.innerWidth - margin * 2);
        let left = rect.left;
        if (left + panelWidth > window.innerWidth - margin) {
            left = window.innerWidth - margin - panelWidth;
        }
        if (left < margin) {
            left = margin;
        }
        const top = rect.bottom + margin;
        panel.style.width = `${panelWidth}px`;
        panel.style.left = `${left}px`;
        panel.style.top = `${top}px`;
        // After layout, flip above if overflowing bottom; otherwise clamp into
        // the viewport so Done/Cancel stay reachable on short (landscape) screens.
        requestAnimationFrame(() => {
            const height = panel.offsetHeight;
            const maxBottom = window.innerHeight - margin;
            if (top + height > maxBottom && rect.top - height - margin > margin) {
                panel.style.top = `${rect.top - height - margin}px`;
                return;
            }
            if (top + height > maxBottom) {
                panel.style.top = `${Math.max(margin, maxBottom - height)}px`;
            }
        });
    };

    const focusableInPanel = (): HTMLElement[] => {
        const nodes = panel.querySelectorAll<HTMLElement>(
            'button:not([disabled]), input:not([disabled])',
        );
        return Array.from(nodes);
    };

    const close = (): void => {
        if (!open) {
            return;
        }
        open = false;
        panel.hidden = true;
        backdrop.hidden = true;
        const restoreTarget =
            (anchor.querySelector('input, button') as HTMLElement | null) ?? anchor;
        if (typeof restoreTarget.focus === 'function') {
            restoreTarget.focus();
        }
    };

    const openCalendar = (): void => {
        const state = callbacks.getState();
        draft = {
            fromDate: state.fromDate,
            toDate: state.toDate,
            sameDayOnly: state.sameDayOnly,
            pendingStep: 'from',
        };
        viewMonth = state.fromDate
            ? state.fromDate.slice(0, 7)
            : callbacks.getToday().slice(0, 7);
        open = true;
        backdrop.hidden = false;
        panel.hidden = false;
        renderGrid();
        positionPanel();
        requestAnimationFrame(() => {
            const first = focusableInPanel()[0] ?? panel;
            first.focus();
        });
    };

    prevBtn.addEventListener('click', () => {
        viewMonth = shiftMonth(`${viewMonth}-01`, -1);
        renderGrid();
    });
    nextBtn.addEventListener('click', () => {
        viewMonth = shiftMonth(`${viewMonth}-01`, 1);
        renderGrid();
    });
    sameDayCb.addEventListener('change', () => {
        draft = applyCalendarSameDayToggle(sameDayCb.checked, draft.fromDate, draft.toDate);
        renderGrid();
    });
    cancelBtn.addEventListener('click', () => {
        close();
    });
    doneBtn.addEventListener('click', () => {
        if (!draft.fromDate) {
            close();
            return;
        }
        callbacks.onApply({
            fromDate: draft.fromDate,
            toDate: draft.sameDayOnly ? draft.fromDate : draft.toDate || draft.fromDate,
            sameDayOnly: draft.sameDayOnly,
        });
        close();
    });
    backdrop.addEventListener('click', () => {
        close();
    });

    const onKey = (e: KeyboardEvent): void => {
        if (!open) {
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            close();
            return;
        }
        if (e.key !== 'Tab') {
            return;
        }
        const items = focusableInPanel();
        if (items.length === 0) {
            e.preventDefault();
            panel.focus();
            return;
        }
        const first = items[0]!;
        const last = items[items.length - 1]!;
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    };
    window.addEventListener('keydown', onKey);

    return {
        open: openCalendar,
        close,
        isOpen: () => open,
        destroy: () => {
            window.removeEventListener('keydown', onKey);
            backdrop.remove();
            panel.remove();
        },
    };
}
