/**
 * Pure decision helpers for re-fitting the live map when the UI regains focus.
 * `visibilitychange` and window `focus` usually fire together on tab return, so
 * only one pass should run per focus gesture.
 */

/** Street-level zoom for a single point (OSM layer `maxZoom` is 19). Shared by every single-point fit. */
export const STREET_LEVEL_ZOOM = 17;

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

export interface MapView {
    center: [number, number];
    zoom: number;
}

/** Zoom in to street level, but never zoom out when the user is already closer. */
export function streetLevelZoom(currentZoom: number): number {
    return Math.max(currentZoom, STREET_LEVEL_ZOOM);
}

/**
 * Remember the view from before the first selection zoom. Selecting another point while still at
 * street level keeps the original view as the Escape target instead of nesting a stack of zooms.
 */
export function rememberPreSelectionView(existing: MapView | null, current: MapView): MapView {
    return existing ?? current;
}

export interface EscapeRestoreContext {
    key: string;
    defaultPrevented: boolean;
    hasRestoreView: boolean;
    /** Historic range calendar (or any other overlay that owns Escape) is open. */
    overlayOpen: boolean;
    /** Focus is in an input, textarea, select or contenteditable element. */
    targetEditable: boolean;
}

/** Escape restores the pre-selection view only when nothing else should consume the key first. */
export function shouldRestoreViewOnEscape(ctx: EscapeRestoreContext): boolean {
    return ctx.key === 'Escape' && !ctx.defaultPrevented && ctx.hasRestoreView && !ctx.overlayOpen && !ctx.targetEditable;
}
