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

describe('resolvePwaInstallEligibility', () => {
    it('hides in standalone', () => {
        expect(
            resolvePwaInstallEligibility({
                matchMedia: media({ '(display-mode: standalone)': true }),
                permanentDismissed: false,
                sessionDismissed: false,
                userAgentDataMobile: true,
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
            }),
        ).toEqual({ showBanner: true, reason: 'ok' });
    });
});

describe('isMobileFormFactor', () => {
    it('uses UA mobile when present', () => {
        expect(
            isMobileFormFactor({
                userAgentDataMobile: true,
                matchMedia: media({}),
            }),
        ).toBe(true);
        expect(
            isMobileFormFactor({
                userAgentDataMobile: false,
                matchMedia: media({ '(max-width: 768px)': true }),
            }),
        ).toBe(true);
        expect(
            isMobileFormFactor({
                userAgentDataMobile: false,
                matchMedia: media({}),
            }),
        ).toBe(false);
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
    it('mentions Android uninstall cleanup in manual mode', () => {
        expect(pwaInstallCopyForMode('manual-only', 'android-chrome')).toContain('Settings → Apps');
        expect(pwaInstallCopyForMode('manual-only', 'android-chrome')).toContain('Uninstall');
    });

    it('uses generic manual copy outside Android Chrome', () => {
        expect(pwaInstallCopyForMode('manual-only', 'generic-mobile')).not.toContain('Settings → Apps');
        expect(pwaInstallCopyForMode('manual-only', 'generic-mobile')).toContain('share sheet');
        expect(pwaInstallCopyForMode('waiting-for-prompt', 'generic-mobile')).not.toContain(
            'Chrome menu',
        );
    });
});

describe('resolvePwaInstallCopyVariant', () => {
    it('keeps Android Chrome-specific guidance scoped to Chrome on Android', () => {
        expect(
            resolvePwaInstallCopyVariant(
                'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
            ),
        ).toBe('android-chrome');
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
