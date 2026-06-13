/** Unregister all service workers for this origin (clears stale SW fetch handlers). */
export async function unregisterAllServiceWorkers(): Promise<number> {
    if (!('serviceWorker' in navigator)) {
        return 0;
    }
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
    return registrations.length;
}

/** Ask a waiting service worker to activate immediately. */
export async function activateWaitingServiceWorker(): Promise<void> {
    if (!('serviceWorker' in navigator)) {
        return;
    }
    const registration = await navigator.serviceWorker.getRegistration('/');
    registration?.waiting?.postMessage({ type: 'SKIP_WAITING' });
}

/** Register /sw.js and force the browser to check for updates on every load. */
export async function registerAndUpdateServiceWorker(): Promise<void> {
    if (!('serviceWorker' in navigator)) {
        return;
    }
    const { protocol, hostname } = window.location;
    const allowed =
        protocol === 'https:' || hostname === 'localhost' || hostname === '127.0.0.1';
    if (!allowed) {
        return;
    }

    const registration = await navigator.serviceWorker.register('/sw.js', {
        scope: '/',
        updateViaCache: 'none',
    });
    await registration.update();
    await activateWaitingServiceWorker();
}
