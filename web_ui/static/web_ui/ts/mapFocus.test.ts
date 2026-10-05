import { describe, expect, it } from 'vitest';
import { FOCUS_FIT_COOLDOWN_MS, FOCUS_FIT_MAX_IN_FLIGHT_MS, shouldStartFocusFit } from './mapFocus';

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
