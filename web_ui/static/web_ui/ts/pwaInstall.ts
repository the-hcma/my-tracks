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

export const PWA_MANUAL_INSTALL_STEPS_GENERIC =
    'Use your browser menu or share sheet to Add to Home screen or Install this app. If the app was previously installed, uninstall it, clear site data for this site, reload, then try again.';

export type PwaInstallEligibility = {
    showBanner: boolean;
    reason:
        | 'ok'
        | 'standalone'
        | 'dismissed-permanent'
        | 'dismissed-session'
        | 'not-mobile';
};

export type PwaInstallCopyVariant = 'android-chrome' | 'generic-mobile';

export function isDisplayStandalone(
    matchMedia: (query: string) => { matches: boolean },
    navigatorStandalone: boolean | undefined,
): boolean {
    return matchMedia('(display-mode: standalone)').matches || navigatorStandalone === true;
}

function isAndroidOrAppleMobileUa(userAgent: string): boolean {
    return /Android|iPhone|iPad|iPod/i.test(userAgent);
}

/**
 * Classify install-help copy. Prefer an explicit Chrome-on-Android signal;
 * WebView / Brave / other Chromium forks fall back to generic steps.
 */
export function resolvePwaInstallCopyVariant(userAgent: string): PwaInstallCopyVariant {
    if (!/Android/i.test(userAgent)) {
        return 'generic-mobile';
    }
    if (/\bwv\b|; wv\)/i.test(userAgent)) {
        return 'generic-mobile';
    }
    if (/Brave|EdgA|OPR\/|SamsungBrowser|YaBrowser|DuckDuckGo|Firefox/i.test(userAgent)) {
        return 'generic-mobile';
    }
    // Chrome for Android typically includes both Chrome/ and Mobile Safari tokens.
    if (/Chrome\/\d+/i.test(userAgent) && /Mobile Safari/i.test(userAgent)) {
        return 'android-chrome';
    }
    return 'generic-mobile';
}

export function isMobileFormFactor(options: {
    userAgentDataMobile?: boolean;
    userAgent?: string;
    matchMedia: (query: string) => { matches: boolean };
}): boolean {
    if (options.userAgentDataMobile === true) {
        return true;
    }
    const ua = options.userAgent ?? '';
    const phoneOrTabletUa = isAndroidOrAppleMobileUa(ua);
    // Desktop UA-CH reports mobile=false. Do not treat touch laptops / narrow
    // desktop windows as install-eligible unless the UA is Android/iOS.
    if (options.userAgentDataMobile === false && !phoneOrTabletUa) {
        return false;
    }
    // Android tablets often report UA-CH mobile=false; allow coarse/compact
    // fallback when the UA is a phone/tablet platform (or UA-CH is absent).
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
    userAgent?: string;
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
            userAgent: options.userAgent,
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

function assertNever(value: never): never {
    throw new Error(`Unhandled PWA install UI mode: ${String(value)}`);
}

export function pwaInstallCopyForMode(
    mode: PwaInstallUiMode,
    variant: PwaInstallCopyVariant = 'generic-mobile',
): string {
    if (mode === 'deferred-prompt') {
        return 'Tap Install to add My Tracks to your home screen.';
    }
    if (mode === 'manual-only') {
        const steps =
            variant === 'android-chrome'
                ? PWA_MANUAL_INSTALL_STEPS_ANDROID
                : PWA_MANUAL_INSTALL_STEPS_GENERIC;
        return `Your browser did not offer a one-tap Install button. ${steps}`;
    }
    if (mode === 'waiting-for-prompt') {
        if (variant === 'generic-mobile') {
            return 'Checking whether this browser can show a one-tap Install button… If it does not appear, use your browser menu or share sheet to Add to Home screen or Install this app.';
        }
        return 'Checking whether this browser can show a one-tap Install button… If it does not appear, use Chrome menu (⋮) → Install app or Add to Home screen.';
    }
    return assertNever(mode);
}
