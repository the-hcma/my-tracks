import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    configureGoogleMapsLink,
    googleMapsPopupLinkHtml,
    googleMapsUrl,
    setPopupContentKeepingLinkFocus,
    OPEN_IN_GOOGLE_MAPS_LABEL,
    type ReplaceablePopup,
} from './googleMaps';

describe('googleMapsUrl', () => {
    it('builds the universal search URL with full-precision coordinates', () => {
        expect(googleMapsUrl(40.689247123, -74.044502456)).toBe(
            'https://www.google.com/maps/search/?api=1&query=40.689247123,-74.044502456',
        );
    });

    it('accepts string coordinates as returned by the API', () => {
        expect(googleMapsUrl('-33.8568', '151.2153')).toBe(
            'https://www.google.com/maps/search/?api=1&query=-33.8568,151.2153',
        );
    });

    it('keeps the digits of a string coordinate instead of rounding through a number', () => {
        expect(googleMapsUrl('0.1234567890123456789', '-122.12345678901234567')).toBe(
            'https://www.google.com/maps/search/?api=1&query=0.1234567890123456789,-122.12345678901234567',
        );
    });

    it('normalizes string forms that are not plain decimals', () => {
        expect(googleMapsUrl('+5.', '.5')).toBe('https://www.google.com/maps/search/?api=1&query=5,0.5');
    });

    it('never emits exponent notation for tiny numeric coordinates', () => {
        expect(googleMapsUrl(1e-7, 2)).toBe('https://www.google.com/maps/search/?api=1&query=0.0000001000,2');
    });

    it('accepts boundary coordinates', () => {
        expect(googleMapsUrl(-90, 180)).toBe('https://www.google.com/maps/search/?api=1&query=-90,180');
    });

    it.each([
        [Number.NaN, 0],
        [0, Number.POSITIVE_INFINITY],
        ['abc', '10'],
        ['', ''],
        [90.1, 0],
        [0, -180.5],
        ['40.5junk', '10'],
        ['10', '1e2x'],
        ['0x10', '5'],
    ])('returns null for unusable coordinates (%s, %s)', (lat, lon) => {
        expect(googleMapsUrl(lat, lon)).toBeNull();
    });
});

describe('configureGoogleMapsLink', () => {
    it('opens in a new tab without leaking the opener', () => {
        const link = document.createElement('a');
        configureGoogleMapsLink(link, 'https://www.google.com/maps/search/?api=1&query=1,2');
        expect(link.href).toBe('https://www.google.com/maps/search/?api=1&query=1,2');
        expect(link.target).toBe('_blank');
        expect(link.rel).toBe('noopener noreferrer');
    });
});

describe('googleMapsPopupLinkHtml', () => {
    it('renders a link for valid coordinates', () => {
        const html = googleMapsPopupLinkHtml(1.5, -2.5);
        expect(html).toContain('href="https://www.google.com/maps/search/?api=1&query=1.5,-2.5"');
        expect(html).toContain(OPEN_IN_GOOGLE_MAPS_LABEL);
        expect(html).toContain('rel="noopener noreferrer"');
    });

    it('renders nothing for unusable coordinates', () => {
        expect(googleMapsPopupLinkHtml('x', 'y')).toBe('');
    });
});

describe('setPopupContentKeepingLinkFocus', () => {
    afterEach(() => {
        document.body.innerHTML = '';
    });

    function makePopup(html: string): { element: HTMLElement; popup: ReplaceablePopup } {
        const element = document.createElement('div');
        element.innerHTML = html;
        document.body.appendChild(element);
        const popup: ReplaceablePopup = {
            getElement: () => element,
            setContent: (content: string) => {
                element.innerHTML = content;
            },
        };
        return { element, popup };
    }

    it('moves focus to the replacement link when the old link had focus', () => {
        const { element, popup } = makePopup(googleMapsPopupLinkHtml(1, 2));
        element.querySelector<HTMLElement>('a')!.focus();
        setPopupContentKeepingLinkFocus(popup, `address${googleMapsPopupLinkHtml(1, 2)}`);
        expect(document.activeElement).toBe(element.querySelector('a'));
    });

    it('leaves focus alone when the link did not have it', () => {
        const other = document.createElement('button');
        document.body.appendChild(other);
        const { element, popup } = makePopup(googleMapsPopupLinkHtml(1, 2));
        other.focus();
        setPopupContentKeepingLinkFocus(popup, `address${googleMapsPopupLinkHtml(1, 2)}`);
        expect(document.activeElement).toBe(other);
        expect(element.textContent).toContain('address');
    });

    it('still replaces the content when the popup has no element yet', () => {
        const setContent = vi.fn();
        setPopupContentKeepingLinkFocus({ getElement: () => undefined, setContent }, 'x');
        expect(setContent).toHaveBeenCalledWith('x');
    });
});
