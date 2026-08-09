/**
 * Service worker fetch routing rules.
 *
 * Kept in sync with web_ui/static/web_ui/sw.js (inline copy). Vitest guards regressions
 * without requiring a browser deploy.
 */

export type ServiceWorkerFetchRoute = 'bypass' | 'main-bundle' | 'network-first' | 'cache-first';

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

/**
 * HTML shells that embed CSRF / session-bound markup must not be cache-first.
 * Mirror the path list inlined in sw.js.
 */
export function isShellHtmlPath(pathname: string): boolean {
    return (
        pathname === '/' ||
        pathname === '/login/' ||
        pathname === '/logout/' ||
        pathname === '/profile/' ||
        pathname === '/geofences/' ||
        pathname === '/admin-panel/' ||
        pathname === '/about/'
    );
}

export function resolveServiceWorkerFetchRoute(
    pathname: string,
    options: { navigate?: boolean } = {},
): ServiceWorkerFetchRoute {
    if (shouldBypassServiceWorker(pathname)) {
        return 'bypass';
    }
    if (options.navigate || isShellHtmlPath(pathname)) {
        return 'network-first';
    }
    if (isMainBundlePath(pathname)) {
        return 'main-bundle';
    }
    return 'cache-first';
}
