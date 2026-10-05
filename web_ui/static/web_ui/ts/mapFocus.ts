/**
 * Pure decision helpers for re-fitting the live map when the UI regains focus.
 * `visibilitychange` and window `focus` usually fire together on tab return, so
 * only one pass should run per focus gesture.
 */

/** Window in which a second focus signal is treated as part of the same gesture. */
export const FOCUS_FIT_COOLDOWN_MS = 1000;

/**
 * A focus-fit still "in flight" after this long is presumed dead (e.g. a stalled request), so one hung
 * pass cannot disable refit-on-focus for the rest of the session. Longer than the fetch deadline.
 */
export const FOCUS_FIT_MAX_IN_FLIGHT_MS = 60_000;

export interface FocusFitGate {
    /** When the running focus-fit (refresh + fit) started; null when none is running. */
    inFlightSinceMs: number | null;
    nowMs: number;
    /** When the previous focus-fit finished; 0 when none has run yet. */
    lastFinishedMs: number;
    cooldownMs?: number;
    maxInFlightMs?: number;
}

export function shouldStartFocusFit(gate: FocusFitGate): boolean {
    if (gate.inFlightSinceMs !== null) {
        const maxInFlightMs = gate.maxInFlightMs ?? FOCUS_FIT_MAX_IN_FLIGHT_MS;
        if (gate.nowMs - gate.inFlightSinceMs < maxInFlightMs) {
            return false;
        }
    }
    const cooldownMs = gate.cooldownMs ?? FOCUS_FIT_COOLDOWN_MS;
    return gate.nowMs - gate.lastFinishedMs >= cooldownMs;
}
