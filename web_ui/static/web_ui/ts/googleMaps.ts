/**
 * Google Maps deep links for a reported location.
 *
 * The universal `https://www.google.com/maps/search/?api=1` URL opens the
 * Google Maps app on iOS and Android when it is installed, and Google Maps in
 * the browser otherwise. Coordinates keep full precision (not the 6-decimal
 * display value).
 */

const DECIMAL_NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)$/;
const GOOGLE_MAPS_SEARCH_URL = 'https://www.google.com/maps/search/?api=1&query=';

const POPUP_LINK_CLASS = 'popup-google-maps-link';
const PLAIN_DECIMAL = /^-?\d+(\.\d+)?$/;

export const OPEN_IN_GOOGLE_MAPS_LABEL = 'Open in Google Maps';

interface ParsedCoordinate {
    /** Text to put in the URL: the supplied decimal string as-is, so no precision is lost. */
    text: string;
    value: number;
}

/**
 * Parse a coordinate. A string must be entirely a decimal number (no trailing text); a plain
 * decimal string keeps its own digits, since a JavaScript number would round long ones.
 */
function parseCoordinate(input: string | number): ParsedCoordinate {
    if (typeof input === 'number') {
        // Tiny magnitudes stringify in exponent form, which is not a decimal coordinate.
        return { text: /e/i.test(String(input)) ? input.toFixed(10) : String(input), value: input };
    }
    const trimmed = input.trim();
    if (!DECIMAL_NUMBER.test(trimmed)) {
        return { text: '', value: Number.NaN };
    }
    const value = Number(trimmed);
    return { text: PLAIN_DECIMAL.test(trimmed) ? trimmed : String(value), value };
}

/** Point a link at Google Maps; opens in a new tab without exposing the opener. */
export function configureGoogleMapsLink(link: HTMLAnchorElement, url: string): void {
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
}

/** Popup HTML for the link, or an empty string when the coordinates are unusable. */
export function googleMapsPopupLinkHtml(latitude: string | number, longitude: string | number): string {
    const url = googleMapsUrl(latitude, longitude);
    if (url === null) {
        return '';
    }
    return `<br><a class="${POPUP_LINK_CLASS}" href="${url}" target="_blank" rel="noopener noreferrer">📍 ${OPEN_IN_GOOGLE_MAPS_LABEL}</a>`;
}

/**
 * Build the Google Maps URL for a coordinate pair.
 * @returns the URL, or null when either coordinate is not a finite number in range
 */
export function googleMapsUrl(latitude: string | number, longitude: string | number): string | null {
    const lat = parseCoordinate(latitude);
    const lon = parseCoordinate(longitude);
    const finite = Number.isFinite(lat.value) && Number.isFinite(lon.value);
    if (!finite || Math.abs(lat.value) > 90 || Math.abs(lon.value) > 180) {
        return null;
    }
    return `${GOOGLE_MAPS_SEARCH_URL}${lat.text},${lon.text}`;
}

/** The part of a Leaflet popup that {@link setPopupContentKeepingLinkFocus} needs. */
export interface ReplaceablePopup {
    getElement(): HTMLElement | undefined;
    setContent(content: string): unknown;
}

/**
 * Replace a popup's content (for example when a looked-up address arrives). If the popup's
 * Google Maps link had keyboard focus, move focus to the replacement link so it is not lost.
 */
export function setPopupContentKeepingLinkFocus(popup: ReplaceablePopup, content: string): void {
    const popupElement = popup.getElement();
    const linkHadFocus =
        popupElement !== undefined &&
        document.activeElement instanceof HTMLElement &&
        document.activeElement.classList.contains(POPUP_LINK_CLASS) &&
        popupElement.contains(document.activeElement);
    popup.setContent(content);
    if (linkHadFocus) {
        popup.getElement()?.querySelector<HTMLElement>(`.${POPUP_LINK_CLASS}`)?.focus();
    }
}
