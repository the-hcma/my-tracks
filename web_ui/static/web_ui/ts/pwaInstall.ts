/**
 * PWA install-banner helpers (Chrome deferred install prompt + manual fallback).
 */

export const PWA_INSTALL_DISMISS_PERMANENT_KEY = 'my-tracks-pwa-install-dismiss-permanent';
export const PWA_INSTALL_DISMISS_SESSION_KEY = 'my-tracks-pwa-install-dismiss-session';
/** Legacy session key from earlier builds. */
export const PWA_INSTALL_DISMISS_LEGACY_SESSION_KEY = 'my-tracks-pwa-install-dismissed';

/** How long to wait for beforeinstallprompt before emphasizing manual install steps. */
export const PWA_INSTALL_PROMPT_WAIT_MS = 2500;

export const PWA_MANUAL_INSTALL_STEPS_ANDROID =
    'Chrome menu (⋮) → Install app or Add to Home screen. If that is missing: Settings → Apps → See all apps → My Tracks → Uninstall (or long-press the home-screen icon → Uninstall), clear site data for this site, reload, then try again.';

export type PwaInstallEligibility = {
    showBanner: boolean;
    reason:
        | 'ok'
        | 'standalone'
        | 'dismissed-permanent'
        | 'dismissed-session'
        | 'not-mobile';
};

export function isDisplayStandalone(
    matchMedia: (query: string) => { matches: boolean },
    navigatorStandalone: boolean | undefined,
): boolean {
    return matchMedia('(display-mode: standalone)').matches || navigatorStandalone === true;
}

export function isMobileFormFactor(options: {
    userAgentDataMobile?: boolean;
    matchMedia: (query: string) => { matches: boolean };
}): boolean {
    if (options.userAgentDataMobile === true) {
        return true;
    }
    // Android tablets often report userAgentData.mobile === false; still treat
    // coarse/compact layouts as install-eligible.
    const { matchMedia } = options;
    return (
        matchMedia('(any-pointer: coarse)').matches ||
        matchMedia('(pointer: coarse)').matches ||
        matchMedia('(max-width: 768px)').matches
    );
}

export function resolvePwaInstallEligibility(options: {
    matchMedia: (query: string) => { matches: boolean };
    navigatorStandalone?: boolean;
    userAgentDataMobile?: boolean;
    permanentDismissed: boolean;
    sessionDismissed: boolean;
}): PwaInstallEligibility {
    if (isDisplayStandalone(options.matchMedia, options.navigatorStandalone)) {
        return { showBanner: false, reason: 'standalone' };
    }
    if (options.permanentDismissed) {
        return { showBanner: false, reason: 'dismissed-permanent' };
    }
    if (options.sessionDismissed) {
        return { showBanner: false, reason: 'dismissed-session' };
    }
    if (
        !isMobileFormFactor({
            userAgentDataMobile: options.userAgentDataMobile,
            matchMedia: options.matchMedia,
        })
    ) {
        return { showBanner: false, reason: 'not-mobile' };
    }
    return { showBanner: true, reason: 'ok' };
}

export type PwaInstallUiMode = 'waiting-for-prompt' | 'deferred-prompt' | 'manual-only';

/**
 * After beforeinstallprompt: deferred-prompt.
 * After wait with no event: manual-only (Chrome often withholds Install when a
 * prior install remnant exists).
 */
export function nextPwaInstallUiMode(
    current: PwaInstallUiMode,
    event: 'prompt-available' | 'wait-elapsed',
): PwaInstallUiMode {
    if (event === 'prompt-available') {
        return 'deferred-prompt';
    }
    if (current === 'deferred-prompt') {
        return current;
    }
    return 'manual-only';
}

export function pwaInstallCopyForMode(mode: PwaInstallUiMode): string {
    if (mode === 'deferred-prompt') {
        return 'Tap Install to add My Tracks to your home screen.';
    }
    if (mode === 'manual-only') {
        return `Your browser did not offer a one-tap Install button. ${PWA_MANUAL_INSTALL_STEPS_ANDROID}`;
    }
    return 'Checking whether this browser can show a one-tap Install button… If it does not appear, use Chrome menu (⋮) → Install app or Add to Home screen.';
}
