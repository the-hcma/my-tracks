/**
 * Service worker fetch routing rules.
 *
 * Kept in sync with web_ui/static/web_ui/sw.js (inline copy). Vitest guards regressions
 * without requiring a browser deploy.
 */

export type ServiceWorkerFetchRoute = 'bypass' | 'main-bundle' | 'cache-first';

/** Live API and WebSocket traffic must not use cache-first handling. */
export function shouldBypassServiceWorker(pathname: string): boolean {
    return pathname.startsWith('/api/') || pathname.startsWith('/ws/');
}

export function isMainBundlePath(pathname: string): boolean {
    return (
        pathname.endsWith('/main.js') ||
        /\/static\/web_ui\/js\/main\.[a-f0-9]+\.js$/.test(pathname)
    );
}

export function resolveServiceWorkerFetchRoute(pathname: string): ServiceWorkerFetchRoute {
    if (shouldBypassServiceWorker(pathname)) {
        return 'bypass';
    }
    if (isMainBundlePath(pathname)) {
        return 'main-bundle';
    }
    return 'cache-first';
}
