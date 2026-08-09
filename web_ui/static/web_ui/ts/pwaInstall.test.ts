import { describe, expect, it } from 'vitest';
import {
    isDisplayStandalone,
    isMobileFormFactor,
    nextPwaInstallUiMode,
    pwaInstallCopyForMode,
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
        expect(pwaInstallCopyForMode('manual-only')).toContain('Settings → Apps');
        expect(pwaInstallCopyForMode('manual-only')).toContain('Uninstall');
    });
});
