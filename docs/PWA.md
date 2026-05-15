# Progressive Web App (PWA)

The My Tracks web dashboard can be installed on a phone or tablet home screen like
a native app. It opens in **standalone** mode (no browser chrome) and uses a
stylized globe launcher icon.

On eligible mobile browsers, a banner on the live map offers **Install** when
`beforeinstallprompt` is available, manual “Add to Home screen” instructions
otherwise, and **Dismiss** / **Do not ask again** controls.

## What works offline

The service worker precaches the app shell (HTML, CSS, manifest, icons, and the
compiled JS bundle). **Live map data, WebSockets, and API calls still require
network access** and a logged-in session — the PWA is for quick launch and
standalone display, not offline tracking.

## Install requirements

| Requirement | Details |
|-------------|---------|
| **HTTPS or loopback** | Service worker registration and the install prompt run only on `https://` URLs or `http://localhost` / `http://127.0.0.1`. Plain HTTP on a LAN IP shows manifest metadata in some browsers but not the full install flow. |
| **Logged in** | Open the live map at `/` after signing in. The install banner is mounted from the home dashboard JavaScript bundle. |
| **Mobile form factor** | Banner is shown on touch-first / compact layouts (not desktop browsers). |
| **Not already installed** | Hidden when running in standalone mode or iOS “Add to Home Screen” mode. |

### Production (HTTPS)

With nginx TLS termination ([DEPLOYMENT.md](DEPLOYMENT.md)), open
`https://your-host/` on the phone, log in, and use the install banner or the
browser’s **Install app** / **Add to Home screen** menu entry.

### Local systemd service

The default [systemd user service](SYSTEMD.md) listens on `http://localhost:8080`.
Install from the **same machine** works via loopback. To install from another
device on your LAN, put HTTPS in front of the app (production stack or local
reverse proxy) — do not expose an unauthenticated HTTP listener to the network.

## User flow

1. On a phone, open the My Tracks URL and log in.
2. On the live map, if eligible, an **Install My Tracks** banner appears at the
   top of the dashboard.
3. Tap **Install** when enabled, or use the browser menu (**Add to Home screen**
   / **Install app**).
4. The home-screen icon uses the globe artwork; launching it opens the dashboard
   in standalone mode.

Dismiss stores a per-session hide; **Do not ask again** stores a permanent hide
in `localStorage` (`my-tracks-pwa-install-dismiss-permanent`).

## Technical reference

| Asset | Location |
|-------|----------|
| Web app manifest | `web_ui/static/web_ui/manifest.webmanifest` → `/static/web_ui/manifest.webmanifest` |
| Service worker | `web_ui/static/web_ui/sw.js` → served at **`/sw.js`** (site root scope) |
| Icon source (SVG) | `web_ui/static/web_ui/icons/app-icon.svg` |
| Launcher PNGs | `icon-192.png`, `icon-512.png` (generated at build time) |
| Install UI | `web_ui/static/web_ui/ts/main.ts` — `initPwaInstallBanner()`, `registerServiceWorker()` |

Build icons and the JS bundle:

```bash
pnpm install --frozen-lockfile
pnpm run build   # runs rasterize-pwa-icons.mjs, then esbuild
```

`scripts/on-deploy` (used by `setup-service`) runs `pnpm run build` before
`collectstatic`, so the systemd service serves current PWA assets after each
deploy.

## Related docs

- [DEPLOYMENT.md](DEPLOYMENT.md) — production HTTPS stack
- [QUICKSTART.md](QUICKSTART.md) — first run and web dashboard
- [SYSTEMD.md](SYSTEMD.md) — persistent local server via user service
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — install banner / service worker issues
