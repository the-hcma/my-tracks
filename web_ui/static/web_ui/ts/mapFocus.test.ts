import { describe, expect, it } from 'vitest';
import {
    FOCUS_FIT_COOLDOWN_MS,
    FOCUS_FIT_MAX_IN_FLIGHT_MS,
    type MapView,
    rememberPreSelectionView,
    shouldRestoreViewOnEscape,
    shouldStartFocusFit,
    STREET_LEVEL_ZOOM,
    streetLevelZoom,
} from './mapFocus';

describe('shouldStartFocusFit', () => {
    it('starts when nothing has run yet', () => {
        expect(shouldStartFocusFit({ inFlightSinceMs: null, nowMs: 5000, lastFinishedMs: 0 })).toBe(true);
    });

    it('does not start while a previous focus fit is still in flight', () => {
        expect(shouldStartFocusFit({ inFlightSinceMs: 1000, nowMs: 2000, lastFinishedMs: 0 })).toBe(false);
    });

    it('treats a focus fit stuck past the max in-flight time as dead and starts again', () => {
        const startedMs = 1000;
        const nowMs = startedMs + FOCUS_FIT_MAX_IN_FLIGHT_MS;
        expect(shouldStartFocusFit({ inFlightSinceMs: startedMs, nowMs, lastFinishedMs: 0 })).toBe(true);
    });

    it('still blocks just before the max in-flight time', () => {
        const startedMs = 1000;
        const nowMs = startedMs + FOCUS_FIT_MAX_IN_FLIGHT_MS - 1;
        expect(shouldStartFocusFit({ inFlightSinceMs: startedMs, nowMs, lastFinishedMs: 0 })).toBe(false);
    });

    it('skips a second focus signal inside the cooldown window', () => {
        const finished = 10_000;
        const nowMs = finished + FOCUS_FIT_COOLDOWN_MS - 1;
        expect(shouldStartFocusFit({ inFlightSinceMs: null, nowMs, lastFinishedMs: finished })).toBe(false);
    });

    it('starts again once the cooldown has elapsed', () => {
        const finished = 10_000;
        const nowMs = finished + FOCUS_FIT_COOLDOWN_MS;
        expect(shouldStartFocusFit({ inFlightSinceMs: null, nowMs, lastFinishedMs: finished })).toBe(true);
    });

    it('honors a custom cooldown', () => {
        const gate = { inFlightSinceMs: null, nowMs: 1200, lastFinishedMs: 1000, cooldownMs: 100 };
        expect(shouldStartFocusFit(gate)).toBe(true);
    });
});

describe('selection zoom helpers', () => {
    it('zooms in to street level from a wide view', () => {
        expect(streetLevelZoom(9)).toBe(STREET_LEVEL_ZOOM);
    });

    it('does not zoom out when already closer than street level', () => {
        expect(streetLevelZoom(19)).toBe(19);
    });

    it('remembers the current view for the first selection', () => {
        const original: MapView = { center: [1, 2], zoom: 10 };
        expect(rememberPreSelectionView(null, original, false)).toBe(original);
    });

    it('keeps the first remembered view when selecting another point while a selection is active', () => {
        const original: MapView = { center: [1, 2], zoom: 10 };
        const streetLevel: MapView = { center: [3, 4], zoom: STREET_LEVEL_ZOOM };
        expect(rememberPreSelectionView(original, streetLevel, true)).toBe(original);
    });

    it('replaces a stale remembered view when no selection is active any more', () => {
        const stale: MapView = { center: [1, 2], zoom: 10 };
        const current: MapView = { center: [5, 6], zoom: 12 };
        expect(rememberPreSelectionView(stale, current, false)).toBe(current);
    });
});

describe('shouldRestoreViewOnEscape', () => {
    const base = {
        key: 'Escape',
        defaultPrevented: false,
        hasSelection: true,
        overlayOpen: false,
        targetEditable: false,
    };

    it('clears the selection on a plain Escape when something is selected', () => {
        expect(shouldRestoreViewOnEscape(base)).toBe(true);
    });

    it('ignores other keys', () => {
        expect(shouldRestoreViewOnEscape({ ...base, key: 'Enter' })).toBe(false);
    });

    it('does nothing when nothing is selected', () => {
        expect(shouldRestoreViewOnEscape({ ...base, hasSelection: false })).toBe(false);
    });

    it('leaves Escape to an open overlay such as the historic calendar', () => {
        expect(shouldRestoreViewOnEscape({ ...base, overlayOpen: true })).toBe(false);
    });

    it('leaves Escape to inputs such as the friends search box', () => {
        expect(shouldRestoreViewOnEscape({ ...base, targetEditable: true })).toBe(false);
    });

    it('leaves Escape that another handler already consumed', () => {
        expect(shouldRestoreViewOnEscape({ ...base, defaultPrevented: true })).toBe(false);
    });
});
