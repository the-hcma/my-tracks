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
 * Remember the view from before the first selection zoom. Selecting another point while a selection
 * is still active keeps the original view as the Escape target instead of nesting a stack of zooms.
 * With no active selection any remembered view is stale, so the current view replaces it.
 */
export function rememberPreSelectionView(
    existing: MapView | null,
    current: MapView,
    hasActiveSelection: boolean,
): MapView {
    return hasActiveSelection && existing ? existing : current;
}

export interface EscapeRestoreContext {
    key: string;
    defaultPrevented: boolean;
    /** A location is currently selected/highlighted. */
    hasSelection: boolean;
    /** Historic range calendar (or any other overlay that owns Escape) is open. */
    overlayOpen: boolean;
    /** Focus is in an input, textarea, select or contenteditable element. */
    targetEditable: boolean;
}

/** Escape clears the selection (and restores the view) only when nothing else should take the key. */
export function shouldRestoreViewOnEscape(ctx: EscapeRestoreContext): boolean {
    if (ctx.key !== 'Escape' || ctx.defaultPrevented) {
        return false;
    }
    return ctx.hasSelection && !ctx.overlayOpen && !ctx.targetEditable;
}

/** Focus is in an element that owns Escape itself (input, textarea, select, contenteditable). */
export function isEditableTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
        return false;
    }
    return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

export interface EscapeRestoreDeps {
    hasSelection: () => boolean;
    overlayOpen: () => boolean;
    restore: () => void;
}

/** Keydown handler for the document-level Escape restore; only consumes the key when it acts. */
export function createEscapeRestoreHandler(deps: EscapeRestoreDeps): (event: KeyboardEvent) => void {
    return (event: KeyboardEvent): void => {
        const shouldRestore = shouldRestoreViewOnEscape({
            key: event.key,
            defaultPrevented: event.defaultPrevented,
            hasSelection: deps.hasSelection(),
            overlayOpen: deps.overlayOpen(),
            targetEditable: isEditableTarget(event.target),
        });
        if (!shouldRestore) {
            return;
        }
        event.preventDefault();
        deps.restore();
    };
}

/**
 * A live fix re-keys a device marker. When the selected key belonged only to the marker being
 * replaced, the highlight would dangle on a key with no marker, so it follows the marker instead.
 */
export function selectedKeyAfterMarkerRekey(options: {
    selectedKey: string | null;
    previousKey: string | undefined;
    newKey: string;
    previousKeyStillRegistered: boolean;
}): string | null {
    const { selectedKey, previousKey, newKey, previousKeyStillRegistered } = options;
    if (selectedKey !== null && selectedKey === previousKey && newKey !== previousKey && !previousKeyStillRegistered) {
        return newKey;
    }
    return selectedKey;
}

/** Window in which a second click on the same marker counts as part of a double-click. */
export const RAPID_RECLICK_WINDOW_MS = 300;

/**
 * Second click of a double-click on the marker that was just selected. Without this guard the toggle-off
 * would undo the street-level zoom the first click just made (the marker is under the cursor again).
 */
export function isRapidReclick(options: {
    nowMs: number;
    lastClickMs: number;
    lastKey: string | null;
    key: string;
    windowMs?: number;
}): boolean {
    const windowMs = options.windowMs ?? RAPID_RECLICK_WINDOW_MS;
    return options.lastKey === options.key && options.nowMs - options.lastClickMs < windowMs;
}
