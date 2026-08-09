import { describe, expect, it } from 'vitest';
import {
    isDisplayStandalone,
    isMobileFormFactor,
    nextPwaInstallUiMode,
    pwaInstallCopyForMode,
    resolvePwaInstallCopyVariant,
    resolvePwaInstallEligibility,
} from './pwaInstall';

function media(matchesFor: Record<string, boolean>): (query: string) => { matches: boolean } {
    return (query: string) => ({ matches: Boolean(matchesFor[query]) });
}

const ANDROID_CHROME_UA =
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36';
const ANDROID_TABLET_CHROME_UA =
    'Mozilla/5.0 (Linux; Android 14; Pixel Tablet) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36';
const ANDROID_WEBVIEW_UA =
    'Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/128.0.0.0 Mobile Safari/537.36';
const ANDROID_BRAVE_UA =
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 Brave/1.68';
const DESKTOP_CHROME_UA =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36';

describe('resolvePwaInstallEligibility', () => {
    it('hides in standalone', () => {
        expect(
            resolvePwaInstallEligibility({
                matchMedia: media({ '(display-mode: standalone)': true }),
                permanentDismissed: false,
                sessionDismissed: false,
                userAgentDataMobile: true,
                userAgent: ANDROID_CHROME_UA,
            }).reason,
        ).toBe('standalone');
    });

    it('hides when permanently dismissed', () => {
        expect(
            resolvePwaInstallEligibility({
                matchMedia: media({ '(display-mode: standalone)': false, '(max-width: 768px)': true }),
                permanentDismissed: true,
                sessionDismissed: false,
                userAgentDataMobile: true,
                userAgent: ANDROID_CHROME_UA,
            }).reason,
        ).toBe('dismissed-permanent');
    });

    it('shows on mobile when not dismissed', () => {
        expect(
            resolvePwaInstallEligibility({
                matchMedia: media({ '(display-mode: standalone)': false }),
                permanentDismissed: false,
                sessionDismissed: false,
                userAgentDataMobile: true,
                userAgent: ANDROID_CHROME_UA,
            }),
        ).toEqual({ showBanner: true, reason: 'ok' });
    });
});

describe('isMobileFormFactor', () => {
    it('uses UA mobile when present', () => {
        expect(
            isMobileFormFactor({
                userAgentDataMobile: true,
                userAgent: ANDROID_CHROME_UA,
                matchMedia: media({}),
            }),
        ).toBe(true);
    });

    it('allows Android tablets with UA-CH mobile=false via compact fallback', () => {
        expect(
            isMobileFormFactor({
                userAgentDataMobile: false,
                userAgent: ANDROID_TABLET_CHROME_UA,
                matchMedia: media({ '(max-width: 768px)': true }),
            }),
        ).toBe(true);
    });

    it('excludes desktop touch laptops with UA-CH mobile=false', () => {
        expect(
            isMobileFormFactor({
                userAgentDataMobile: false,
                userAgent: DESKTOP_CHROME_UA,
                matchMedia: media({
                    '(any-pointer: coarse)': true,
                    '(max-width: 768px)': true,
                }),
            }),
        ).toBe(false);
    });

    it('excludes desktop Firefox/Safari without UA-CH', () => {
        const firefoxDesktopUa =
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0';
        expect(
            isMobileFormFactor({
                userAgent: firefoxDesktopUa,
                matchMedia: media({
                    '(any-pointer: coarse)': true,
                    '(max-width: 768px)': true,
                }),
            }),
        ).toBe(false);
    });

    it('allows iPadOS desktop-class Safari UA with a coarse pointer', () => {
        const ipadDesktopSafariUa =
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15';
        expect(
            isMobileFormFactor({
                userAgent: ipadDesktopSafariUa,
                matchMedia: media({ '(any-pointer: coarse)': true }),
            }),
        ).toBe(true);
    });

    it('excludes macOS Safari narrow windows without a coarse pointer', () => {
        const macSafariUa =
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15';
        expect(
            isMobileFormFactor({
                userAgent: macSafariUa,
                matchMedia: media({ '(max-width: 768px)': true }),
            }),
        ).toBe(false);
    });
});

describe('resolvePwaInstallCopyVariant', () => {
    it('detects Chrome on Android', () => {
        expect(resolvePwaInstallCopyVariant(ANDROID_CHROME_UA)).toBe('android-chrome');
    });

    it('defaults WebView and Brave to generic', () => {
        expect(resolvePwaInstallCopyVariant(ANDROID_WEBVIEW_UA)).toBe('generic-mobile');
        expect(resolvePwaInstallCopyVariant(ANDROID_BRAVE_UA)).toBe('generic-mobile');
    });

    it('defaults desktop, iOS Safari, Samsung, and Edge Android to generic', () => {
        expect(resolvePwaInstallCopyVariant(DESKTOP_CHROME_UA)).toBe('generic-mobile');
        expect(
            resolvePwaInstallCopyVariant(
                'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
            ),
        ).toBe('generic-mobile');
        expect(
            resolvePwaInstallCopyVariant(
                'Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/28.0 Chrome/125.0.0.0 Safari/537.36',
            ),
        ).toBe('generic-mobile');
        expect(
            resolvePwaInstallCopyVariant(
                'Mozilla/5.0 (Linux; Android 14; Pixel Tablet) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36 EdgA/125.0.0.0',
            ),
        ).toBe('generic-mobile');
    });
});

describe('isDisplayStandalone', () => {
    it('detects iOS navigator.standalone', () => {
        expect(isDisplayStandalone(media({ '(display-mode: standalone)': false }), true)).toBe(true);
    });
});

describe('nextPwaInstallUiMode', () => {
    it('promotes to deferred when prompt arrives', () => {
        expect(nextPwaInstallUiMode('waiting-for-prompt', 'prompt-available')).toBe('deferred-prompt');
        expect(nextPwaInstallUiMode('manual-only', 'prompt-available')).toBe('deferred-prompt');
    });

    it('falls back to manual after wait without prompt', () => {
        expect(nextPwaInstallUiMode('waiting-for-prompt', 'wait-elapsed')).toBe('manual-only');
        expect(nextPwaInstallUiMode('deferred-prompt', 'wait-elapsed')).toBe('deferred-prompt');
    });
});

describe('pwaInstallCopyForMode', () => {
    it('mentions Android uninstall cleanup for android-chrome manual mode', () => {
        expect(pwaInstallCopyForMode('manual-only', 'android-chrome')).toContain('Settings → Apps');
        expect(pwaInstallCopyForMode('manual-only', 'android-chrome')).toContain('Uninstall');
    });

    it('uses generic manual copy outside Android Chrome', () => {
        expect(pwaInstallCopyForMode('manual-only', 'generic-mobile')).toContain('browser menu');
        expect(pwaInstallCopyForMode('manual-only', 'generic-mobile')).toContain('share sheet');
        expect(pwaInstallCopyForMode('manual-only', 'generic-mobile')).not.toContain('Settings → Apps');
        expect(pwaInstallCopyForMode('waiting-for-prompt', 'generic-mobile')).not.toContain(
            'Chrome menu',
        );
    });
});
