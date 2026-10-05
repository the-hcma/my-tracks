/**
 * Pure decision helpers for re-fitting the live map when the UI regains focus.
 * `visibilitychange` and window `focus` usually fire together on tab return, so
 * only one pass should run per focus gesture.
 */

/** Window in which a second focus signal is treated as part of the same gesture. */
export const FOCUS_FIT_COOLDOWN_MS = 1000;

export interface FocusFitGate {
    /** True while a previous focus-fit (refresh + fit) is still running. */
    inFlight: boolean;
    nowMs: number;
    /** When the previous focus-fit finished; 0 when none has run yet. */
    lastFinishedMs: number;
    cooldownMs?: number;
}

export function shouldStartFocusFit(gate: FocusFitGate): boolean {
    if (gate.inFlight) {
        return false;
    }
    const cooldownMs = gate.cooldownMs ?? FOCUS_FIT_COOLDOWN_MS;
    return gate.nowMs - gate.lastFinishedMs >= cooldownMs;
}
