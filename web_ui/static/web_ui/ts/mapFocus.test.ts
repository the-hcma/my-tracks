import { describe, expect, it } from 'vitest';
import { FOCUS_FIT_COOLDOWN_MS, shouldStartFocusFit } from './mapFocus';

describe('shouldStartFocusFit', () => {
    it('starts when nothing has run yet', () => {
        expect(shouldStartFocusFit({ inFlight: false, nowMs: 5000, lastFinishedMs: 0 })).toBe(true);
    });

    it('does not start while a previous focus fit is still in flight', () => {
        expect(shouldStartFocusFit({ inFlight: true, nowMs: 99999, lastFinishedMs: 0 })).toBe(false);
    });

    it('skips a second focus signal inside the cooldown window', () => {
        const finished = 10_000;
        const nowMs = finished + FOCUS_FIT_COOLDOWN_MS - 1;
        expect(shouldStartFocusFit({ inFlight: false, nowMs, lastFinishedMs: finished })).toBe(false);
    });

    it('starts again once the cooldown has elapsed', () => {
        const finished = 10_000;
        const nowMs = finished + FOCUS_FIT_COOLDOWN_MS;
        expect(shouldStartFocusFit({ inFlight: false, nowMs, lastFinishedMs: finished })).toBe(true);
    });

    it('honors a custom cooldown', () => {
        expect(shouldStartFocusFit({ inFlight: false, nowMs: 1200, lastFinishedMs: 1000, cooldownMs: 100 })).toBe(true);
    });
});
