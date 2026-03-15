# My Tracks

A self-hosted location tracking backend for the [OwnTracks](https://owntracks.org/) Android/iOS app. Receives, persists, and visualizes geolocation data via HTTP and MQTT, with a live map UI, real-time WebSocket updates, and a PKI-based certificate management system for secure MQTT TLS.

## 🚀 Quick Start

```bash
# One-command setup
bash setup

# Start server
./my-tracks-server

# Test API
curl -X POST http://localhost:8080/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"lat": 37.7749, "lon": -122.4194, "tst": 1705329600, "tid": "AB"}'
```

**See [QUICKSTART.md](QUICKSTART.md) for detailed 5-minute setup guide.**

## 📚 Documentation

- **[📖 Documentation Index](DOCS_INDEX.md)** - Complete guide to all docs
- **[🚀 QUICKSTART.md](QUICKSTART.md)** - Get running in 5 minutes
- **[📘 API.md](API.md)** - Complete API reference
- **[🚢 DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment guide
- **[⌨️ COMMANDS.md](COMMANDS.md)** - Command reference
- **[📊 PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Comprehensive project overview
- **[👥 AGENTS.md](AGENTS.md)** - Development agent workflow

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

## Requirements

- Python 3.14 or higher
- [uv](https://github.com/astral-sh/uv) package manager (fast, reliable Python package installer)
- PostgreSQL **14 or later** (required for production; Django 5.x enforces this minimum version) or SQLite (development only)

**Why uv?** This project uses `uv` exclusively for dependency management - it's significantly faster than pip and provides deterministic installs.

## Installation

### Automated Setup (Recommended)

```bash
# Clone repository
git clone <repository-url>
cd my-tracks

# Run setup script
bash setup
```

This will:
1. Install `uv` if needed
2. Set up virtual environment
3. Install all dependencies
4. Run database migrations

### Manual Setup

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd my-tracks
   ```

3. **Extract project files**:
   ```bash
   ./install
   ```

4. **Create virtual environment and install dependencies**:
   ```bash
   uv sync
   ```

   **Note**: With `uv run`, you don't need to manually activate the virtual environment.

5. **For development dependencies**:
   ```bash
   uv sync --all-extras
   ```

6. **Configure environment variables**:
   Create a `.env` file in the project root:
   ```
   SECRET_KEY=your-secret-key-here
   DEBUG=True
   ALLOWED_HOSTS=localhost,127.0.0.1
   DATABASE_URL=sqlite:///db.sqlite3
   ```

6. **Run migrations**:
   ```bash
   uv run python manage.py migrate
   ```

7. **Create a superuser** (optional, for admin access):
   ```bash
   uv run python manage.py createsuperuser
   ```

8. **Run the development server**:
   ```bash
   ./my-tracks-server
   ```

   Or with console logging (outputs to both console and file):
   ```bash
   ./my-tracks-server --console
   ```

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
├── my-tracks-server          # Server startup script
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
shellcheck my-tracks-server
```

## Production Deployment

For production deployment:

1. Set `DEBUG=False` in `.env`
2. Configure a proper database (PostgreSQL recommended)
3. Set strong `SECRET_KEY`
4. Configure `ALLOWED_HOSTS` with your domain
5. Use the production server script
6. Set up SSL/TLS certificates

Start production server:
```bash
./my-tracks-server --log-level warning
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete production setup guide.

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

See [COMMANDS.md](COMMANDS.md#version-control-graphite) for the complete Graphite workflow.
