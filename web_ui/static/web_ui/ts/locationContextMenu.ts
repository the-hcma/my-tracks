/**
 * Context menu offering "Open in Google Maps" for a location, opened by right-click or
 * touch hold on activity log rows and map markers. Rows also run their own long-press timer
 * because iOS Safari does not reliably fire `contextmenu` on a touch hold; markers rely on
 * Leaflet's `contextmenu` (including its tap-hold) plus the Google Maps link in their popup.
 */
import { configureGoogleMapsLink, googleMapsUrl, OPEN_IN_GOOGLE_MAPS_LABEL } from './googleMaps';

type Coordinate = string | number;

/** How long after the finger lifts a long-press still swallows the click that follows it. */
export const FIRED_RESET_DELAY_MS = 600;

export const LONG_PRESS_DELAY_MS = 500;
/** Finger travel (px) beyond which a touch is a scroll or drag, not a long-press. */
export const LONG_PRESS_MOVE_TOLERANCE_PX = 10;

/**
 * Ignore taps on a touch-opened menu item this soon after it opens: the click that follows
 * the finger lifting from a long-press can land on the item now under the finger.
 */
export const MENU_ARM_DELAY_MS = 400;

/** Gap between a touch point and a menu placed above it, so the finger does not cover the item. */
const ABOVE_TOUCH_GAP_PX = 24;
/** Gap below a touch point when there is no room above it. */
const BELOW_TOUCH_GAP_PX = 48;
const MENU_CLASS = 'location-context-menu';
const VIEWPORT_MARGIN_PX = 4;

/** Holder for the single open menu and its dismissal listeners. */
class MenuState {
    dismissAbort: AbortController | null = null;
    /** `pointerType` of the most recent pointerdown ("touch", "mouse", "pen"), or "" before any. */
    lastPointerType = '';
    menu: HTMLElement | null = null;
    /** Element focused when the menu opened, so Escape can hand focus back to it. */
    opener: HTMLElement | null = null;
}

const state = new MenuState();

document.addEventListener(
    'pointerdown',
    (event) => {
        state.lastPointerType = event.pointerType;
    },
    { capture: true, passive: true },
);

type MenuPlacement = 'at-point' | 'above-touch';

/** Touch menus go above the finger so releasing it cannot land on the item. */
function defaultPlacement(): MenuPlacement {
    return state.lastPointerType === 'touch' ? 'above-touch' : 'at-point';
}

export function hideLocationContextMenu(): void {
    state.dismissAbort?.abort();
    state.dismissAbort = null;
    state.menu?.remove();
    state.menu = null;
    state.opener = null;
}

export function isLocationContextMenuOpen(): boolean {
    return state.menu !== null;
}

/**
 * Show the menu at viewport coordinates (x, y) for a location.
 * Replaces any open menu. Does nothing when the coordinates are unusable.
 */
export function showLocationContextMenu(
    x: number,
    y: number,
    latitude: Coordinate,
    longitude: Coordinate,
    placement: MenuPlacement = defaultPlacement(),
): void {
    const url = googleMapsUrl(latitude, longitude);
    hideLocationContextMenu();
    if (url === null) {
        return;
    }

    const menu = document.createElement('div');
    menu.className = MENU_CLASS;
    menu.setAttribute('role', 'menu');
    const item = document.createElement('a');
    item.className = 'location-context-menu-item';
    item.setAttribute('role', 'menuitem');
    item.textContent = `📍 ${OPEN_IN_GOOGLE_MAPS_LABEL}`;
    configureGoogleMapsLink(item, url);
    // A real link tap is a user-initiated navigation, which lets mobile OSes open the app.
    const openedAtMs = Date.now();
    // Only a touch-opened menu can receive the release click of its own long-press.
    const guardEarlyTaps = placement === 'above-touch';
    item.addEventListener('click', (event) => {
        if (guardEarlyTaps && Date.now() - openedAtMs < MENU_ARM_DELAY_MS) {
            event.preventDefault();
            return;
        }
        // Defer so the link's default navigation runs before the menu is removed.
        const opener = state.opener;
        setTimeout(() => {
            hideLocationContextMenu();
            if (opener?.isConnected) {
                opener.focus();
            }
        }, 0);
    });
    menu.appendChild(item);
    menu.addEventListener('contextmenu', (event) => event.preventDefault());
    const previouslyFocused = document.activeElement;
    document.body.appendChild(menu);

    const rect = menu.getBoundingClientRect();
    const left = Math.max(VIEWPORT_MARGIN_PX, Math.min(x, window.innerWidth - rect.width - VIEWPORT_MARGIN_PX));
    let preferredTop = y;
    if (placement === 'above-touch') {
        preferredTop = y - rect.height - ABOVE_TOUCH_GAP_PX;
        if (preferredTop < VIEWPORT_MARGIN_PX) {
            preferredTop = y + BELOW_TOUCH_GAP_PX;
        }
    }
    const maxTop = window.innerHeight - rect.height - VIEWPORT_MARGIN_PX;
    const top = Math.max(VIEWPORT_MARGIN_PX, Math.min(preferredTop, maxTop));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    item.focus();

    const abort = new AbortController();
    const { signal } = abort;
    document.addEventListener(
        'pointerdown',
        (event) => {
            if (!menu.contains(event.target as Node)) {
                hideLocationContextMenu();
            }
        },
        { signal, capture: true },
    );
    document.addEventListener(
        'keydown',
        (event) => {
            // Tab closes the menu too, handing focus back so it moves on from the opener (menu pattern).
            if (event.key === 'Escape' || event.key === 'Tab') {
                const opener = state.opener;
                hideLocationContextMenu();
                if (opener?.isConnected) {
                    opener.focus();
                }
            }
        },
        { signal },
    );
    // User-initiated scrolling only: the live log also scrolls programmatically (scrollIntoView).
    window.addEventListener('wheel', hideLocationContextMenu, { signal, passive: true });
    window.addEventListener('resize', hideLocationContextMenu, { signal });
    state.menu = menu;
    state.dismissAbort = abort;
    state.opener =
        previouslyFocused instanceof HTMLElement && previouslyFocused !== document.body ? previouslyFocused : null;
}

export interface LongPressOptions {
    delayMs?: number;
    moveTolerancePx?: number;
}

/**
 * Call `onLongPress(x, y)` when a single touch is held in place. The click that
 * follows the lifted finger is swallowed so the press does not also select the row.
 * iOS Safari does not reliably fire `contextmenu` on long-press, hence the manual timer.
 */
export function attachLongPress(
    element: HTMLElement,
    onLongPress: (x: number, y: number) => void,
    options: LongPressOptions = {},
): void {
    const delayMs = options.delayMs ?? LONG_PRESS_DELAY_MS;
    const tolerance = options.moveTolerancePx ?? LONG_PRESS_MOVE_TOLERANCE_PX;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let startX = 0;
    let startY = 0;
    let fired = false;
    let firedResetTimer: ReturnType<typeof setTimeout> | null = null;

    const cancel = (): void => {
        if (timer !== null) {
            clearTimeout(timer);
            timer = null;
        }
    };

    element.addEventListener(
        'touchstart',
        (event: TouchEvent) => {
            cancel();
            if (firedResetTimer !== null) {
                clearTimeout(firedResetTimer);
                firedResetTimer = null;
            }
            fired = false;
            if (event.touches.length !== 1) {
                return;
            }
            startX = event.touches[0].clientX;
            startY = event.touches[0].clientY;
            timer = setTimeout(() => {
                timer = null;
                fired = true;
                onLongPress(startX, startY);
            }, delayMs);
        },
        { passive: true },
    );
    element.addEventListener(
        'touchmove',
        (event: TouchEvent) => {
            const touch = event.touches[0];
            if (touch && Math.hypot(touch.clientX - startX, touch.clientY - startY) > tolerance) {
                cancel();
                // The finger is now scrolling or dragging: do not leave the menu over other rows.
                // (Not done on touchcancel: Android Chrome sends one right after its own long-press menu.)
                if (fired) {
                    hideLocationContextMenu();
                }
            }
        },
        { passive: true },
    );
    // A cancelled touch need not be followed by touchend, so both end the gesture the same way.
    // The follow-up click may never reach this element (it can land on the menu, or the
    // browser may suppress it), so do not let `fired` swallow a later, unrelated click.
    const endGesture = (): void => {
        cancel();
        if (fired) {
            firedResetTimer = setTimeout(() => {
                firedResetTimer = null;
                fired = false;
            }, FIRED_RESET_DELAY_MS);
        }
    };
    element.addEventListener('touchend', endGesture);
    element.addEventListener('touchcancel', endGesture);
    element.addEventListener(
        'click',
        (event) => {
            if (fired) {
                fired = false;
                event.preventDefault();
                event.stopImmediatePropagation();
            }
        },
        { capture: true },
    );
}

/**
 * Add a map-pin link at the start of an activity log row, plus right-click and long-press
 * handlers that open the context menu. The link does not trigger the row's own
 * click / Enter-Space selection. Does nothing when the coordinates are unusable.
 */
export function attachGoogleMapsActionsToEntry(entry: HTMLElement, latitude: Coordinate, longitude: Coordinate): void {
    const url = googleMapsUrl(latitude, longitude);
    if (url === null) {
        return;
    }
    const link = document.createElement('a');
    link.className = 'log-map-link';
    link.textContent = '📍';
    link.title = OPEN_IN_GOOGLE_MAPS_LABEL;
    link.setAttribute('aria-label', OPEN_IN_GOOGLE_MAPS_LABEL);
    configureGoogleMapsLink(link, url);
    link.addEventListener('click', (event) => event.stopPropagation());
    link.addEventListener('keydown', (event) => {
        // Only Enter and Space activate the row; let Escape and other keys reach the document handler.
        if (event.key === 'Enter' || event.key === ' ') {
            event.stopPropagation();
        }
    });
    entry.prepend(link);

    entry.addEventListener('contextmenu', (event: MouseEvent) => {
        event.preventDefault();
        showLocationContextMenu(event.clientX, event.clientY, latitude, longitude);
    });
    attachLongPress(entry, (x, y) => showLocationContextMenu(x, y, latitude, longitude, 'above-touch'));
}

/** Handle a map marker's right-click: show the menu at the pointer for the marker's position. */
export function showLocationContextMenuForMarker(
    pointerEvent: MouseEvent,
    position: { lat: number; lng: number },
): void {
    pointerEvent.preventDefault();
    showLocationContextMenu(pointerEvent.clientX, pointerEvent.clientY, position.lat, position.lng);
}
