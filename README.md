# My Tracks

A self-hosted location tracking backend for the [OwnTracks](https://owntracks.org/) Android/iOS app. Receives, persists, and visualizes geolocation data via HTTP and MQTT, with a live map UI, real-time WebSocket updates, and a PKI-based certificate management system for secure MQTT TLS.

## 🚀 Quick Start (Container — Recommended)

```bash
git clone https://github.com/the-hcma/my-tracks.git
cd my-tracks
./production/scripts/my-tracks-production-container-manager --start
```

On first run this will:
1. Check for Docker or Podman (with platform-specific install hints if missing)
2. Generate `.env.production` with a random secret key
3. Generate self-signed TLS certificates
4. Build the container image from source
5. Start the full stack: **nginx** (TLS termination) + **my-tracks** (app) + **PostgreSQL**
6. Wait for the health check and print access URLs

Once healthy, visit `https://localhost:8443` and create an admin user:

```bash
# Create admin user (shown in the startup banner)
docker compose exec my-tracks python manage.py createsuperuser
```

Common operations:

| Command | Description |
|---|---|
| `--start` | Start (or restart) the stack; reuses existing config |
| `--start --freshen-up` | Wipe config and start fresh |
| `--start --import-sqlite [path]` | Import a local SQLite DB into PostgreSQL |
| `--stop` | Tear down the stack and volumes |
| `--security-check` | Run pre-launch security checks (CVE audit, Django hardening) |

**See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the complete production deployment guide.**

## 📚 Documentation

- **[📖 Documentation Index](docs/DOCS_INDEX.md)** - Complete guide to all docs
- **[🚀 docs/QUICKSTART.md](docs/QUICKSTART.md)** - Get running in 5 minutes
- **[📘 docs/API.md](docs/API.md)** - Complete API reference
- **[🚢 docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** - Production deployment guide
- **[⌨️ docs/COMMANDS.md](docs/COMMANDS.md)** - Command reference
- **[📊 docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)** - Comprehensive project overview
- **[👥 docs/AGENTS.md](docs/AGENTS.md)** - Development agent workflow

## Features

- **OwnTracks HTTP Protocol Support**: Full compatibility with OwnTracks JSON format
- **Location Data Persistence**: Store location data with full context (latitude, longitude, timestamp, accuracy, altitude, velocity, battery, connection type)
- **RESTful API**: Clean API endpoints for location data with filtering and pagination
- **Device Management**: Support for multiple devices with unique identification
- **Type Safety**: Full type hints using Python 3.14+ features
- **Modern Python**: Uses dataclasses and modern Python idioms
- **Admin Interface**: Web-based admin for data management
- **Comprehensive Testing**: Full pytest test suite included
- **Production Ready**: Includes deployment guide with Daphne ASGI server for WebSocket support

## Local Development Setup

For contributing or running locally without Docker:

**Requirements**: Python 3.14+, [uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/the-hcma/my-tracks.git
cd my-tracks

# Install dependencies and run migrations
bash scripts/setup

# Start the dev server
./scripts/my-tracks-server
```

For manual setup or more options, see [docs/QUICKSTART.md](docs/QUICKSTART.md).

## OwnTracks Configuration

### HTTP Mode

Configure your OwnTracks app with the following settings:

- **Mode**: HTTP
- **URL**: `http://your-server:8080/api/locations/`
- **Authentication**: Use device ID in the payload

### MQTT Mode (Recommended)

MQTT provides real-time location updates, lower battery usage, and bidirectional
communication (e.g., sending commands to devices).

**Important**: my-tracks uses **MQTT v3.1.1** (protocol level 4). OwnTracks on
Android defaults to MQTT v3.1, which is **not supported** by the embedded broker.

#### OwnTracks App Settings

1. **Mode**: MQTT
2. **Host**: Your server's IP or hostname
3. **Port**: `1883` (or the port shown in the web UI)
4. **Client ID**: Leave default or set a unique ID
5. **Username / Password**: Leave blank (anonymous access)

#### Setting MQTT Protocol Level to v3.1.1

OwnTracks on Android defaults to MQTT v3.1 (`MQIsdp`, protocol level 3).
You must reconfigure it to use v3.1.1 (protocol level 4):

1. Create a file on your phone (e.g., `config.otrc`) with:
   ```json
   {"_type": "configuration", "mqttProtocolLevel": 4}
   ```
2. Open the file with OwnTracks (tap it in a file manager, share to OwnTracks,
   or use the import feature in the app)
3. The app will apply the configuration and reconnect using v3.1.1

> **Tip**: If you see connections being rejected in the server logs, check for
> the warning message: *"MQTT v3.1 connection detected"* — this confirms the
> protocol level needs to be updated on the device.

## API Endpoints

### POST /api/locations/

Submit location data from OwnTracks client.

**Request Body** (JSON):
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

**Response**: 201 Created

### GET /api/locations/

Retrieve location history.

**Query Parameters**:
- `device`: Filter by device ID
- `start_date`: Filter locations after this date (ISO 8601)
- `end_date`: Filter locations before this date (ISO 8601)
- `limit`: Maximum number of results (default: 100)

### GET /api/devices/

List all registered devices.

## Project Structure

```
my-tracks/
├── manage.py                 # Management script
├── pyproject.toml            # Python dependencies (uv)
├── package.json              # Frontend dependencies (npm)
├── scripts/
│   └── my-tracks-server      # Server startup script
├── config/                   # Project configuration directory
│   ├── __init__.py
│   ├── settings.py          # Project settings
│   ├── urls.py              # URL routing
│   ├── asgi.py              # ASGI configuration
│   └── wsgi.py              # WSGI configuration
├── my_tracks/                # Location tracking app
│   ├── __init__.py
│   ├── admin.py             # Admin configuration
│   ├── apps.py              # App configuration
│   ├── models.py            # Database models
│   ├── serializers.py       # DRF serializers
│   ├── views.py             # API views
│   ├── urls.py              # App URL routing
│   └── migrations/          # Database migrations
└── web_ui/                   # Web interface app
    ├── static/web_ui/
    │   ├── ts/              # TypeScript source
    │   ├── js/              # Compiled JavaScript
    │   └── css/             # Stylesheets
    └── templates/web_ui/    # HTML templates
```

## Development

### Running Tests

```bash
# Python tests
uv run pytest

# With coverage (90% minimum required)
uv run pytest --cov=my_tracks --cov-fail-under=90

# TypeScript tests
npm run test

# TypeScript linting
npm run lint
```

### Code Style

This project follows PEP 8 guidelines with additional tooling:

```bash
# Type checking
uv run pyright

# Import sorting
uv run isort my_tracks config web_ui

# Shell script linting
shellcheck scripts/my-tracks-server
```

## Production Deployment

The recommended deployment path is the container manager script described in Quick Start above. It builds and runs the full stack (nginx + my-tracks + PostgreSQL) with a single command, handles first-time setup automatically, and works on macOS, Linux (Debian/Ubuntu, CentOS/RHEL), and anywhere Docker or Podman is available.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the complete guide, including TLS configuration, environment variables, and bare-metal (non-container) instructions.

## License

PolyForm Noncommercial License 1.0.0 - See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! This project uses [Graphite](https://graphite.dev) for PR management:

```bash
# Create a feature branch
gt create --all --message "feat: your feature"

# Submit PR
gt submit --no-interactive --publish
```

See [docs/COMMANDS.md](docs/COMMANDS.md#version-control-graphite) for the complete Graphite workflow.
