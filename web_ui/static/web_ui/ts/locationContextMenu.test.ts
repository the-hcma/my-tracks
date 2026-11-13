import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    attachGoogleMapsActionsToEntry,
    attachLongPress,
    hideLocationContextMenu,
    isLocationContextMenuOpen,
    FIRED_RESET_DELAY_MS,
    LONG_PRESS_DELAY_MS,
    MENU_ARM_DELAY_MS,
    showLocationContextMenu,
    showLocationContextMenuForMarker,
} from './locationContextMenu';

const MENU = '.location-context-menu';

function touchEvent(type: string, x: number, y: number): Event {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'touches', { value: type === 'touchend' ? [] : [{ clientX: x, clientY: y }] });
    return event;
}

function touchPointerDown(pointerType: string): void {
    const event = new Event('pointerdown', { bubbles: true });
    Object.defineProperty(event, 'pointerType', { value: pointerType });
    document.body.dispatchEvent(event);
}

afterEach(() => {
    vi.useRealTimers();
    hideLocationContextMenu();
    document.body.innerHTML = '';
});

describe('showLocationContextMenu', () => {
    it('shows a Google Maps link for the location', () => {
        showLocationContextMenu(10, 20, 40.5, -74.25);
        const item = document.querySelector<HTMLAnchorElement>(`${MENU} a[role="menuitem"]`);
        expect(item?.href).toBe('https://www.google.com/maps/search/?api=1&query=40.5,-74.25');
        expect(item?.target).toBe('_blank');
        expect(document.activeElement).toBe(item);
    });

    it('places a touch menu above the finger, or below it when there is no room above', () => {
        const rectSpy = vi
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockReturnValue({ width: 200, height: 40 } as DOMRect);
        showLocationContextMenu(100, 300, 1, 2, 'above-touch');
        expect(document.querySelector<HTMLElement>(MENU)?.style.top).toBe('236px');
        showLocationContextMenu(100, 10, 1, 2, 'above-touch');
        expect(document.querySelector<HTMLElement>(MENU)?.style.top).toBe('58px');
        rectSpy.mockRestore();
    });

    it('places a pointer menu at the pointer', () => {
        const rectSpy = vi
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockReturnValue({ width: 200, height: 40 } as DOMRect);
        showLocationContextMenu(100, 300, 1, 2);
        expect(document.querySelector<HTMLElement>(MENU)?.style.top).toBe('300px');
        rectSpy.mockRestore();
    });

    it('replaces an already open menu', () => {
        showLocationContextMenu(0, 0, 1, 2);
        showLocationContextMenu(0, 0, 3, 4);
        expect(document.querySelectorAll(MENU)).toHaveLength(1);
        expect(document.querySelector<HTMLAnchorElement>(`${MENU} a`)?.href).toContain('query=3,4');
    });

    it('shows nothing for unusable coordinates', () => {
        showLocationContextMenu(0, 0, 'x', 'y');
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('closes on Escape', () => {
        showLocationContextMenu(0, 0, 1, 2);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('closes on Tab and hands focus back to the opener', () => {
        const opener = document.createElement('button');
        document.body.appendChild(opener);
        opener.focus();
        showLocationContextMenu(0, 0, 1, 2);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
        expect(document.querySelector(MENU)).toBeNull();
        expect(document.activeElement).toBe(opener);
    });

    it('closes on an outside pointerdown but not on one inside the menu', () => {
        showLocationContextMenu(0, 0, 1, 2);
        document.querySelector(MENU)!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        expect(document.querySelector(MENU)).not.toBeNull();
        document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('ignores programmatic scrolling but closes on wheel and resize', () => {
        showLocationContextMenu(0, 0, 1, 2);
        window.dispatchEvent(new Event('scroll'));
        expect(document.querySelector(MENU)).not.toBeNull();
        window.dispatchEvent(new Event('wheel'));
        expect(document.querySelector(MENU)).toBeNull();
        showLocationContextMenu(0, 0, 1, 2);
        window.dispatchEvent(new Event('resize'));
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('closes after the link is activated and returns focus to the opener', () => {
        vi.useFakeTimers();
        const opener = document.createElement('button');
        document.body.appendChild(opener);
        opener.focus();
        showLocationContextMenu(0, 0, 1, 2);
        vi.advanceTimersByTime(MENU_ARM_DELAY_MS);
        const item = document.querySelector<HTMLAnchorElement>(`${MENU} a`)!;
        item.addEventListener('click', (event) => event.preventDefault());
        item.click();
        expect(document.querySelector(MENU)).not.toBeNull();
        vi.advanceTimersByTime(0);
        expect(document.querySelector(MENU)).toBeNull();
        expect(document.activeElement).toBe(opener);
        vi.useRealTimers();
    });

    it('ignores a click on a touch-opened item right after opening (finger lifting from a long-press)', () => {
        vi.useFakeTimers();
        showLocationContextMenu(0, 0, 1, 2, 'above-touch');
        const item = document.querySelector<HTMLAnchorElement>(`${MENU} a`)!;
        const click = new MouseEvent('click', { bubbles: true, cancelable: true });
        item.dispatchEvent(click);
        expect(click.defaultPrevented).toBe(true);
        expect(document.querySelector(MENU)).not.toBeNull();
        vi.advanceTimersByTime(MENU_ARM_DELAY_MS);
        const laterClick = new MouseEvent('click', { bubbles: true, cancelable: true });
        item.dispatchEvent(laterClick);
        expect(laterClick.defaultPrevented).toBe(false);
        vi.advanceTimersByTime(0);
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('lets a mouse or keyboard activation through immediately', () => {
        vi.useFakeTimers();
        showLocationContextMenu(0, 0, 1, 2, 'at-point');
        const item = document.querySelector<HTMLAnchorElement>(`${MENU} a`)!;
        const click = new MouseEvent('click', { bubbles: true, cancelable: true });
        item.dispatchEvent(click);
        expect(click.defaultPrevented).toBe(false);
    });

    it('reports whether the menu is open', () => {
        expect(isLocationContextMenuOpen()).toBe(false);
        showLocationContextMenu(0, 0, 1, 2);
        expect(isLocationContextMenuOpen()).toBe(true);
        hideLocationContextMenu();
        expect(isLocationContextMenuOpen()).toBe(false);
    });

    it('returns focus to the opener on Escape', () => {
        const opener = document.createElement('button');
        document.body.appendChild(opener);
        opener.focus();
        showLocationContextMenu(0, 0, 1, 2);
        expect(document.activeElement).not.toBe(opener);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(document.activeElement).toBe(opener);
    });

    it('stops listening once closed', () => {
        showLocationContextMenu(0, 0, 1, 2);
        const closedMenu = document.querySelector(MENU)!;
        hideLocationContextMenu();
        // Re-attach the closed menu: a leaked Escape handler from it would remove it again.
        document.body.appendChild(closedMenu);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(closedMenu.isConnected).toBe(true);
    });
});

describe('attachLongPress', () => {
    let row: HTMLElement;
    let onLongPress: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.useFakeTimers();
        row = document.createElement('div');
        document.body.appendChild(row);
        onLongPress = vi.fn();
        attachLongPress(row, onLongPress);
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('fires after the delay with the touch position', () => {
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS - 1);
        expect(onLongPress).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(onLongPress).toHaveBeenCalledWith(30, 40);
    });

    it('does not fire when the finger lifts early', () => {
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS - 1);
        row.dispatchEvent(touchEvent('touchend', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(onLongPress).not.toHaveBeenCalled();
    });

    it('does not fire when the finger moves like a scroll', () => {
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        row.dispatchEvent(touchEvent('touchmove', 30, 80));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(onLongPress).not.toHaveBeenCalled();
    });

    it('dismisses the opened menu when the finger then moves like a scroll', () => {
        attachGoogleMapsActionsToEntry(row, 1, 2);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(document.querySelector(MENU)).not.toBeNull();
        row.dispatchEvent(touchEvent('touchmove', 30, 45));
        expect(document.querySelector(MENU)).not.toBeNull();
        row.dispatchEvent(touchEvent('touchmove', 30, 90));
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('does not dismiss the menu on touchcancel (Android fires one after its long-press menu)', () => {
        attachGoogleMapsActionsToEntry(row, 1, 2);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        row.dispatchEvent(touchEvent('touchcancel', 30, 40));
        expect(document.querySelector(MENU)).not.toBeNull();
    });

    it('still fires when the finger jitters within tolerance', () => {
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        row.dispatchEvent(touchEvent('touchmove', 33, 42));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(onLongPress).toHaveBeenCalledOnce();
    });

    it('ignores multi-touch', () => {
        const event = new Event('touchstart', { bubbles: true });
        Object.defineProperty(event, 'touches', { value: [{ clientX: 1, clientY: 1 }, { clientX: 2, clientY: 2 }] });
        row.dispatchEvent(event);
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(onLongPress).not.toHaveBeenCalled();
    });

    it('swallows the click that follows a long-press but not later clicks', () => {
        const onClick = vi.fn();
        row.addEventListener('click', onClick);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        row.dispatchEvent(touchEvent('touchend', 30, 40));
        row.click();
        expect(onClick).not.toHaveBeenCalled();
        row.click();
        expect(onClick).toHaveBeenCalledOnce();
    });

    it('stops swallowing clicks shortly after a long-press whose click never arrived', () => {
        const onClick = vi.fn();
        row.addEventListener('click', onClick);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        row.dispatchEvent(touchEvent('touchend', 30, 40));
        vi.advanceTimersByTime(FIRED_RESET_DELAY_MS);
        row.click();
        expect(onClick).toHaveBeenCalledOnce();
    });

    it('keeps an older reset timer from clearing a newer long-press', () => {
        const onClick = vi.fn();
        row.addEventListener('click', onClick);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        row.dispatchEvent(touchEvent('touchend', 30, 40));
        vi.advanceTimersByTime(FIRED_RESET_DELAY_MS - 100);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(onLongPress).toHaveBeenCalledTimes(2);
        vi.advanceTimersByTime(200);
        row.click();
        expect(onClick).not.toHaveBeenCalled();
    });

    it('stops swallowing clicks after a touchcancel that follows a long-press', () => {
        const onClick = vi.fn();
        row.addEventListener('click', onClick);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        row.dispatchEvent(touchEvent('touchcancel', 30, 40));
        vi.advanceTimersByTime(FIRED_RESET_DELAY_MS);
        row.click();
        expect(onClick).toHaveBeenCalledOnce();
    });

    it('does not swallow a normal tap', () => {
        const onClick = vi.fn();
        row.addEventListener('click', onClick);
        row.dispatchEvent(touchEvent('touchstart', 30, 40));
        row.dispatchEvent(touchEvent('touchend', 30, 40));
        row.click();
        expect(onClick).toHaveBeenCalledOnce();
    });
});

describe('attachGoogleMapsActionsToEntry', () => {
    function makeRow(): HTMLElement {
        const row = document.createElement('div');
        row.textContent = 'row text';
        document.body.appendChild(row);
        return row;
    }

    it('prepends a pin link to the location', () => {
        const row = makeRow();
        attachGoogleMapsActionsToEntry(row, '40.5', '-74.25');
        const link = row.firstElementChild as HTMLAnchorElement;
        expect(link.className).toBe('log-map-link');
        expect(link.href).toBe('https://www.google.com/maps/search/?api=1&query=40.5,-74.25');
        expect(link.getAttribute('aria-label')).toBe('Open in Google Maps');
    });

    it('does nothing for unusable coordinates', () => {
        const row = makeRow();
        attachGoogleMapsActionsToEntry(row, 'x', 'y');
        expect(row.querySelector('a')).toBeNull();
        row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
        expect(document.querySelector(MENU)).toBeNull();
    });

    it('keeps link clicks and keys from reaching the row selection handlers', () => {
        const row = makeRow();
        const onClick = vi.fn();
        const onKeydown = vi.fn();
        row.addEventListener('click', onClick);
        row.addEventListener('keydown', onKeydown);
        attachGoogleMapsActionsToEntry(row, 1, 2);
        const link = row.querySelector('a')!;
        link.addEventListener('click', (event) => event.preventDefault());
        link.click();
        link.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        link.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
        expect(onClick).not.toHaveBeenCalled();
        expect(onKeydown).not.toHaveBeenCalled();
    });

    it('lets Escape from the link reach document handlers', () => {
        const row = makeRow();
        attachGoogleMapsActionsToEntry(row, 1, 2);
        document.body.appendChild(row);
        const onKeydown = vi.fn();
        document.addEventListener('keydown', onKeydown);
        row.querySelector('a')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        document.removeEventListener('keydown', onKeydown);
        row.remove();
        expect(onKeydown).toHaveBeenCalledTimes(1);
    });

    it('opens the menu on right-click and suppresses the browser menu', () => {
        const row = makeRow();
        attachGoogleMapsActionsToEntry(row, 1, 2);
        const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 6 });
        row.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(true);
        expect(document.querySelector<HTMLAnchorElement>(`${MENU} a`)?.href).toContain('query=1,2');
    });

    it('places a contextmenu from a touch above the finger (Android native, Leaflet tap-hold)', () => {
        const rectSpy = vi
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockReturnValue({ width: 200, height: 40 } as DOMRect);
        const row = makeRow();
        attachGoogleMapsActionsToEntry(row, 3, 4);
        touchPointerDown('touch');
        row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 300 }));
        expect(document.querySelector<HTMLElement>(MENU)?.style.top).toBe('236px');
        touchPointerDown('mouse');
        row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 300 }));
        expect(document.querySelector<HTMLElement>(MENU)?.style.top).toBe('300px');
        rectSpy.mockRestore();
    });

    it('opens the menu on long-press', () => {
        vi.useFakeTimers();
        const row = makeRow();
        attachGoogleMapsActionsToEntry(row, 3, 4);
        row.dispatchEvent(touchEvent('touchstart', 10, 10));
        vi.advanceTimersByTime(LONG_PRESS_DELAY_MS);
        expect(document.querySelector<HTMLAnchorElement>(`${MENU} a`)?.href).toContain('query=3,4');
        vi.useRealTimers();
    });
});

describe('showLocationContextMenuForMarker', () => {
    it('shows the menu for the marker position and suppresses the browser menu', () => {
        const event = new MouseEvent('contextmenu', { cancelable: true, clientX: 7, clientY: 8 });
        showLocationContextMenuForMarker(event, { lat: -33.5, lng: 151.25 });
        expect(event.defaultPrevented).toBe(true);
        expect(document.querySelector<HTMLAnchorElement>(`${MENU} a`)?.href).toContain('query=-33.5,151.25');
    });
});
