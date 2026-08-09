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

/**
 * Reload once when a new service worker takes control so the next page load
 * uses the updated fetch handlers (network-first HTML, new VERSION cache).
 * Skip the first controllerchange when there was no prior controller (fresh
 * install / claim) so first visits do not get an unannounced reload.
 */
function reloadOnceOnControllerChange(): void {
    if (!('serviceWorker' in navigator)) {
        return;
    }
    const hadController = navigator.serviceWorker.controller != null;
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (!hadController || refreshing) {
            return;
        }
        refreshing = true;
        window.location.reload();
    });
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

    reloadOnceOnControllerChange();

    const registration = await navigator.serviceWorker.register('/sw.js', {
        scope: '/',
        updateViaCache: 'none',
    });

    registration.addEventListener('updatefound', () => {
        const installing = registration.installing;
        if (!installing) {
            return;
        }
        installing.addEventListener('statechange', () => {
            if (installing.state === 'installed' && navigator.serviceWorker.controller) {
                installing.postMessage({ type: 'SKIP_WAITING' });
            }
        });
    });

    await registration.update();
    // Activate a worker that was already waiting before this page load;
    // updatefound only covers installs that start after we attach the listener.
    await activateWaitingServiceWorker();
}
