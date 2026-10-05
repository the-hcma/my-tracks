import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    FOCUS_FIT_COOLDOWN_MS,
    createEscapeRestoreHandler,
    FOCUS_FIT_MAX_IN_FLIGHT_MS,
    isEditableTarget,
    isRapidReclick,
    RAPID_RECLICK_WINDOW_MS,
    type MapView,
    rememberPreSelectionView,
    selectedKeyAfterMarkerRekey,
    shouldApplyFocusFit,
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

describe('isEditableTarget', () => {
    it.each(['input', 'textarea', 'select'])('treats a focused <%s> as editable', (tag) => {
        expect(isEditableTarget(document.createElement(tag))).toBe(true);
    });

    it('treats a contenteditable element as editable', () => {
        const div = document.createElement('div');
        Object.defineProperty(div, 'isContentEditable', { value: true });
        expect(isEditableTarget(div)).toBe(true);
    });

    it('does not treat buttons, plain elements, document or null as editable', () => {
        expect(isEditableTarget(document.createElement('button'))).toBe(false);
        expect(isEditableTarget(document.createElement('div'))).toBe(false);
        expect(isEditableTarget(document)).toBe(false);
        expect(isEditableTarget(null)).toBe(false);
    });
});

describe('createEscapeRestoreHandler', () => {
    afterEach(() => {
        document.body.innerHTML = '';
    });

    function setup(deps: { hasSelection?: boolean; overlayOpen?: boolean } = {}): {
        restore: ReturnType<typeof vi.fn>;
        teardown: () => void;
    } {
        const restore = vi.fn();
        const handler = createEscapeRestoreHandler({
            hasSelection: () => deps.hasSelection ?? true,
            overlayOpen: () => deps.overlayOpen ?? false,
            restore,
        });
        document.addEventListener('keydown', handler);
        return { restore, teardown: () => document.removeEventListener('keydown', handler) };
    }

    function press(target: EventTarget, key = 'Escape'): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
        target.dispatchEvent(event);
        return event;
    }

    it('restores once and consumes the key when a selection is active', () => {
        const { restore, teardown } = setup();
        const event = press(document.body);
        expect(restore).toHaveBeenCalledTimes(1);
        expect(event.defaultPrevented).toBe(true);
        teardown();
    });

    it('leaves Escape alone when nothing is selected', () => {
        const { restore, teardown } = setup({ hasSelection: false });
        const event = press(document.body);
        expect(restore).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(false);
        teardown();
    });

    it('leaves Escape to an open overlay such as the historic calendar', () => {
        const { restore, teardown } = setup({ overlayOpen: true });
        press(document.body);
        expect(restore).not.toHaveBeenCalled();
        teardown();
    });

    it('leaves Escape to a focused input', () => {
        const { restore, teardown } = setup();
        const input = document.createElement('input');
        document.body.appendChild(input);
        const event = press(input);
        expect(restore).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(false);
        teardown();
    });

    it('ignores other keys', () => {
        const { restore, teardown } = setup();
        press(document.body, 'Enter');
        expect(restore).not.toHaveBeenCalled();
        teardown();
    });
});

describe('selectedKeyAfterMarkerRekey', () => {
    it('moves the selection to the new key when the old key lost its only marker', () => {
        const result = selectedKeyAfterMarkerRekey({
            selectedKey: 'a',
            previousKey: 'a',
            newKey: 'b',
            previousKeyStillRegistered: false,
        });
        expect(result).toBe('b');
    });

    it('keeps the selection when another marker still holds the old key', () => {
        const result = selectedKeyAfterMarkerRekey({
            selectedKey: 'a',
            previousKey: 'a',
            newKey: 'b',
            previousKeyStillRegistered: true,
        });
        expect(result).toBe('a');
    });

    it('keeps an unrelated selection and a null selection', () => {
        const base = { previousKey: 'a', newKey: 'b', previousKeyStillRegistered: false };
        expect(selectedKeyAfterMarkerRekey({ ...base, selectedKey: 'z' })).toBe('z');
        expect(selectedKeyAfterMarkerRekey({ ...base, selectedKey: null })).toBeNull();
    });

    it('keeps the selection when the marker did not change key', () => {
        const result = selectedKeyAfterMarkerRekey({
            selectedKey: 'a',
            previousKey: 'a',
            newKey: 'a',
            previousKeyStillRegistered: false,
        });
        expect(result).toBe('a');
    });
});

describe('isRapidReclick', () => {
    const base = { nowMs: 1000, lastClickMs: 900, lastKey: 'a', key: 'a' };

    it('flags a second click on the same marker inside the window', () => {
        expect(isRapidReclick(base)).toBe(true);
    });

    it('does not flag a click once the window has elapsed', () => {
        expect(isRapidReclick({ ...base, nowMs: base.lastClickMs + RAPID_RECLICK_WINDOW_MS })).toBe(false);
    });

    it('does not flag a click on a different marker', () => {
        expect(isRapidReclick({ ...base, key: 'b' })).toBe(false);
    });

    it('does not flag the first click', () => {
        expect(isRapidReclick({ ...base, lastKey: null })).toBe(false);
    });
});

describe('shouldApplyFocusFit', () => {
    const base = { isLiveMode: true, hasSelection: false, lastInteractionMs: 100, startedMs: 200 };

    it('applies when live, nothing is selected and the user has not interacted since the pass started', () => {
        expect(shouldApplyFocusFit(base)).toBe(true);
    });

    it('does not apply outside live mode', () => {
        expect(shouldApplyFocusFit({ ...base, isLiveMode: false })).toBe(false);
    });

    it('does not apply while a point is selected, so its Escape restore target survives', () => {
        expect(shouldApplyFocusFit({ ...base, hasSelection: true })).toBe(false);
    });

    it('does not apply when the user interacted during the pass, even in the same millisecond', () => {
        expect(shouldApplyFocusFit({ ...base, lastInteractionMs: 200 })).toBe(false);
        expect(shouldApplyFocusFit({ ...base, lastInteractionMs: 250 })).toBe(false);
    });
});
