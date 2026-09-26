# My Tracks

[![CI](https://github.com/the-hcma/my-tracks/actions/workflows/ci.yml/badge.svg)](https://github.com/the-hcma/my-tracks/actions/workflows/ci.yml)
[![CVE Check](https://github.com/the-hcma/my-tracks/actions/workflows/cve-check.yml/badge.svg)](https://github.com/the-hcma/my-tracks/actions/workflows/cve-check.yml)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-6.x-0C4B33.svg)](https://www.djangoproject.com/)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange.svg)](https://github.com/the-hcma/my-tracks/blob/main/LICENSE)

A self-hosted location tracking server for the [OwnTracks](https://owntracks.org/) [Android](https://play.google.com/store/apps/details?id=org.owntracks.android) and [iOS](https://apps.apple.com/app/owntracks/id692424691) apps. Your phone reports where it is; My Tracks stores it on hardware you control and shows it on a live map. Your location history stays in your own database, with no account on anyone else's service. (The browser does fetch map tiles and address lookups from OpenStreetMap; see [Maps and geodata](#maps-and-geodata).)

It speaks both OwnTracks transports (HTTP and MQTT), ships with its own MQTT broker and certificate authority, and can fire actions when someone arrives at or leaves a place.

## How it relates to OwnTracks

[OwnTracks](https://owntracks.org/) is an open-source **client**: an app that publishes your location and can receive commands. The app itself does not include a server: you point it at a backend, such as OwnTracks' own optional Recorder or, here, My Tracks.

| | OwnTracks app | My Tracks |
|---|---|---|
| Runs on | Your phone | Your server, NAS, or home lab |
| Job | Collect and publish location, geofence events, and waypoints | Receive, store, visualize, and act on them |
| Talks to the other via | HTTP `POST` or MQTT | HTTP endpoint and embedded MQTT broker |

My Tracks is an independent project. It is not affiliated with or endorsed by the OwnTracks project; it implements the [documented OwnTracks protocol](https://owntracks.org/booklet/tech/json/).

## What it does

- **Receives locations over HTTP or MQTT.** Point the app at `/api/locations/`, or connect it to the built-in [MQTT](https://mqtt.org/) v3.1.1 broker for typically lower battery use and two-way communication.
- **Live map.** A [Leaflet](https://leafletjs.com/) dashboard with live and historic trails, updated over [WebSockets](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API) as points arrive. Installable as a [Progressive Web App](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps) on a phone or tablet ([docs/PWA.md](docs/PWA.md)).
- **Full location context.** Latitude, longitude, timestamp, accuracy, altitude, velocity, battery, and connection type, stored per device with filtering by device and date range.
- **Geofences and transitions.** Define places, record enter/leave events, and attach email rules to them ("tell me when the kids get to school"). An optional accuracy gate ignores noisy GPS fixes.
- **Commands to devices.** Ask a phone to report its location now, or push, fetch, and clear its waypoints, over MQTT.
- **Built-in PKI for secure MQTT.** Create a certificate authority, a server certificate, and per-user client certificates from the admin panel. MQTT over TLS uses mutual authentication, where the client certificate's common name maps to a user, and topic access control restricts users to their own `owntracks/<user>/...` topics by default (admins have wider access, and any authenticated user can publish commands to another user's device `/cmd` topic). A certificate revocation list is included. See [docs/ANDROID_CERTS.md](docs/ANDROID_CERTS.md).
- **Multiple users, friends, and sharing.** Per-user accounts, an admin panel, and friend requests so people can choose which devices to share with each other.
- **Companion to domesti-bot.** Pair with [domesti-bot](https://github.com/the-hcma/domesti-bot) to relay location updates into home automations (see [docs/DOMESTI_BOT_INTEGRATION_PLAN.md](docs/DOMESTI_BOT_INTEGRATION_PLAN.md)).
- **Production deployment out of the box.** A single script brings up [nginx](https://nginx.org/) (TLS), the app, and [PostgreSQL](https://www.postgresql.org/) in containers, with [Docker](https://www.docker.com/) or [Podman](https://podman.io/).

> **Scope note:** My Tracks is built for a person, family, or small group running their own server. It is not a multi-tenant SaaS, and the license does not permit commercial use (see [License](#license)).

## Quick start (container, recommended)

```bash
git clone https://github.com/the-hcma/my-tracks.git
cd my-tracks
./production/scripts/my-tracks-production-container-manager --start
```

On first run this will:

1. Check for [Docker](https://www.docker.com/) or [Podman](https://podman.io/) (with platform-specific install hints if missing)
2. Generate `.env.production` with a random secret key
3. Generate self-signed TLS certificates
4. Build the container image from source
5. Start the full stack: **nginx** (TLS termination), **my-tracks** (app and MQTT broker), and **PostgreSQL**
6. Wait for the health check and print access URLs

Once healthy, visit `https://localhost:8443` and create an admin user by running the `createsuperuser` command printed in the startup banner (it already includes the right compose files). It has the form:

```bash
<compose command> exec my-tracks python manage.py createsuperuser
```

Common operations:

| Command | Description |
|---|---|
| `--start` | Start (or restart) the stack; reuses existing config |
| `--start --freshen-up` | Wipe config and start fresh |
| `--start --import-sqlite [path]` | Import a local SQLite DB into PostgreSQL |
| `--stop` | Tear down the stack and volumes |
| `--security-check` | Run pre-launch security checks (CVE audit, Django hardening) |

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the complete production guide, including [Let's Encrypt](https://letsencrypt.org/), external PostgreSQL, backups, firewall ports, and bare-metal (non-container) instructions.

## Architecture

```text
  OwnTracks app (Android / iOS)
        │                  │
   HTTP POST          MQTT / MQTTS
        │                  │
        ▼                  ▼
  ┌───────────────────────────────────────────┐
  │  My Tracks  (Django + Daphne ASGI)        │
  │   REST API · embedded MQTT broker · PKI   │
  │   geofence engine · email actions         │
  └───────┬───────────────────────┬───────────┘
          │                       │ WebSocket
     PostgreSQL / SQLite          ▼
                            Live map (browser / PWA)
```

- **Backend:** Python 3.14+, [Django](https://www.djangoproject.com/), [Django REST Framework](https://www.django-rest-framework.org/), [Channels](https://channels.readthedocs.io/)/[Daphne](https://github.com/django/daphne), [amqtt](https://github.com/Yakifo/amqtt) for the broker
- **Frontend:** [TypeScript](https://www.typescriptlang.org/) ([esbuild](https://esbuild.github.io/), [Vitest](https://vitest.dev/), [ESLint](https://eslint.org/)) and [Leaflet](https://leafletjs.com/)
- **Storage:** [SQLite](https://www.sqlite.org/) for development, [PostgreSQL](https://www.postgresql.org/) for production
- **Quality:** full type hints checked by [Pyright](https://github.com/microsoft/pyright), [Ruff](https://docs.astral.sh/ruff/), [pytest](https://docs.pytest.org/) with a 90% coverage gate, and CVE scanning in CI

## Maps and geodata

My Tracks stands on open-source mapping projects and open data:

- **[Leaflet](https://leafletjs.com/)** renders the interactive maps on the dashboard, geofence editor, and profile pages.
- **[OpenStreetMap](https://www.openstreetmap.org/)** provides the base map tiles, © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) and available under the [ODbL](https://opendatacommons.org/licenses/odbl/).
- **[Nominatim](https://nominatim.org/)**, OpenStreetMap's geocoder, turns coordinates into street addresses in the web UI.

Tiles and address lookups are requested by your browser directly from OpenStreetMap's public servers, so those requests carry the coordinates being viewed. Please respect the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/) and [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/); for heavy use, point the code at your own tile or geocoding server. Geofence distance calculations (haversine) are implemented in this repository and need no external service.

## Connecting the OwnTracks app

### HTTP mode

- **Mode**: HTTP
- **URL**: `http://your-server:8080/api/locations/`
- **Authentication**: Use device ID in the payload

### MQTT mode (recommended)

MQTT provides real-time location updates, lower battery usage, and bidirectional
communication (for example, sending commands to devices).

**Important**: My Tracks uses **MQTT v3.1.1** (protocol level 4). OwnTracks on
Android defaults to MQTT v3.1, which is **not supported** by the embedded broker.

#### OwnTracks app settings

1. **Mode**: MQTT
2. **Host**: Your server's IP or hostname
3. **Port**: `8883` for MQTT over TLS (recommended for anything beyond a trusted local network), or `1883` for plain MQTT (or the port shown in the web UI)
4. **Client ID**: Leave default or set a unique ID
5. **Username / Password**: Your My Tracks username and password for plain MQTT (anonymous connections are rejected). Plain MQTT sends them unencrypted, so use it only on a trusted network. For TLS, authenticate with a client certificate instead ([docs/ANDROID_CERTS.md](docs/ANDROID_CERTS.md)).

#### Setting the MQTT protocol level to v3.1.1

OwnTracks on Android defaults to MQTT v3.1 (`MQIsdp`, protocol level 3).
You must reconfigure it to use v3.1.1 (protocol level 4):

1. Create a file on your phone (for example, `config.otrc`) with:
   ```json
   {"_type": "configuration", "mqttProtocolLevel": 4}
   ```
2. Open the file with OwnTracks (tap it in a file manager, share it to OwnTracks,
   or use the import feature in the app)
3. The app will apply the configuration and reconnect using v3.1.1

> **Tip**: If connections are being rejected, look for the server log warning
> *"MQTT v3.1 connection detected"*. It confirms the protocol level needs to be
> updated on the device.

## API

The REST API follows the OwnTracks payload format. The essentials:

| Endpoint | Purpose |
|---|---|
| `POST /api/locations/` | Submit a location from an OwnTracks client (`200 OK` with an empty `[]` body, as the app expects) |
| `GET /api/locations/` | Location history; filter with `device`, `start_date`, `end_date`, `limit` |
| `GET /api/devices/` | List registered devices |

Example body for `POST /api/locations/`:

```json
{
  "_type": "location",
  "lat": 37.7749,
  "lon": -122.4194,
  "tst": 1234567890,
  "acc": 10,
  "alt": 50,
  "vel": 5,
  "batt": 85,
  "tid": "AB",
  "conn": "w"
}
```

There is more: device commands, friends and sharing, and admin endpoints for users and PKI. See [docs/API.md](docs/API.md) for the complete reference.

## Documentation

- **[📘 docs/API.md](docs/API.md)**: complete API reference
- **[🚢 docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**: production deployment guide
- **[🚀 docs/QUICKSTART.md](docs/QUICKSTART.md)**: get running in 5 minutes
- **[📱 docs/ANDROID_CERTS.md](docs/ANDROID_CERTS.md)**: client certificates for MQTT over TLS
- **[📱 docs/PWA.md](docs/PWA.md)**: install the dashboard on a phone or tablet
- **[🔌 docs/MQTT_IMPLEMENTATION.md](docs/MQTT_IMPLEMENTATION.md)**: how the embedded broker works
- **[🛠️ docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**: common problems and fixes
- **[⌨️ docs/COMMANDS.md](docs/COMMANDS.md)**: command reference
- **[⚙️ docs/SYSTEMD.md](docs/SYSTEMD.md)**: local systemd user service
- **[📊 docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)**: project overview
- **[📖 Documentation Index](docs/DOCS_INDEX.md)**: guide to all docs

## Local development

For contributing or running locally without containers.

**Requirements**: Python 3.14+, [uv](https://github.com/astral-sh/uv); [pnpm](https://pnpm.io/) for the frontend

```bash
git clone https://github.com/the-hcma/my-tracks.git
cd my-tracks

# Install dependencies and run migrations
bash scripts/setup

# Start the dev server (one-off)
./scripts/my-tracks-server

# Or install a persistent systemd user service (recommended for daily use).
# Requires a local clone of repository-helpers; see docs/SYSTEMD.md.
~/work/ai/repository-helpers/scripts/setup-service
```

For manual setup, the web UI, PWA install, and the systemd service, see
[docs/QUICKSTART.md](docs/QUICKSTART.md), [docs/PWA.md](docs/PWA.md), and
[docs/SYSTEMD.md](docs/SYSTEMD.md).

### Running tests and checks

```bash
uv run pytest --cov=app --cov-fail-under=90   # Python tests (90% coverage minimum)
shellcheck scripts/my-tracks-server            # shell script linting
pnpm run test                                  # TypeScript tests
pnpm run lint                                  # TypeScript linting
uv run pyright                                 # type checking
uv run ruff check app config web_ui            # lint and import order
uv run ruff format --check app config web_ui   # formatting
```

### Project structure

```
my-tracks/
├── app/          # Models, REST API, MQTT broker, PKI, geofence logic
├── config/       # Django settings, URLs, ASGI/WSGI
├── web_ui/       # Dashboard, geofence, profile, and admin pages (TypeScript + templates)
├── production/   # Container manager, docker compose files, nginx config
├── scripts/      # Dev server and setup scripts
├── docs/         # Guides and references
└── tests/        # Python test suite
```

## Contributing

Contributions are welcome. This project uses GitHub Stacked PRs (`gh stack`) and the GitHub merge queue:

```bash
~/work/ai/repository-helpers/scripts/dev/start-development --worktree <stack-name> --no-interactive
cd .worktrees/<stack-name>-wt
gh stack init <stack>/<topic>
# … commit changes …
~/work/ai/repository-helpers/scripts/dev/submit-stack
```

See [`AGENTS.md`](AGENTS.md) for the full workflow and quality gates,
[`.agents/rules/stacking-tool.md`](.agents/rules/stacking-tool.md),
[docs/GH-STACK.md](docs/GH-STACK.md), and
[docs/COMMANDS.md](docs/COMMANDS.md#version-control-gh-stack).

## License

Copyright © 2026 Henrique Andrade ([GitHub's thehcma](https://github.com/thehcma)).

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) ([license text on polyformproject.org](https://polyformproject.org/licenses/noncommercial/1.0.0)): free to use, modify, and share for any noncommercial purpose, provided the license terms and notices are kept. Commercial use requires separate permission from the copyright holder.

OwnTracks is a trademark of its respective owners and is referenced here only to describe compatibility.
