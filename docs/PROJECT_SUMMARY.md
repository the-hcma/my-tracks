# My Tracks - Project Summary

## Overview

A self-hosted location tracking backend for the [OwnTracks](https://owntracks.org/) Android/iOS app. Receives, persists, and visualizes geolocation data via HTTP and MQTT, with a live map UI, real-time WebSocket updates, and a PKI-based certificate management system for secure MQTT TLS. Built with Python 3.14+, comprehensive type hints, and RESTful API design.

**Package Management**: Uses [uv](https://github.com/astral-sh/uv) exclusively for fast, deterministic dependency management.

**License**: PolyForm Noncommercial 1.0.0

## Project Status

✅ **Complete Implementation** - Ready for development and production use

## Architecture

### Technology Stack

- **Framework**: Django + Django REST Framework
- **Language**: Python 3.14+ with full type hints
- **Package Manager**: `uv` for fast, reliable dependency management
- **Database**: SQLite (development) / PostgreSQL (production)
- **Server**: Daphne (ASGI) with WebSocket support
- **Frontend**: TypeScript with esbuild, ESLint, Vitest
- **Testing**: pytest (Python), Vitest (TypeScript)

### Key Components

1. **Device Management** (`my_tracks.models.Device`)
   - Unique device identification
   - Automatic device registration
   - Last seen tracking

2. **Location Tracking** (`my_tracks.models.Location`)
   - Comprehensive location metadata
   - Timestamp indexing for efficient queries
   - Support for all OwnTracks fields

3. **REST API** (`my_tracks.views`)
   - OwnTracks HTTP protocol compatibility
   - Location submission endpoint
   - Query endpoints with filtering
   - Pagination support

4. **Data Validation** (`my_tracks.serializers`)
   - OwnTracks format transformation
   - Coordinate validation (-90/+90 lat, -180/+180 lon)
   - Battery level validation (0-100)
   - Informative error messages

5. **Web Interface** (`web_ui`)
   - Live location map with Leaflet
   - Historic trail visualization
   - WebSocket real-time updates
   - TypeScript with strict ESLint rules

## Project Structure

```
my-tracks/
├── README.md                   # Main documentation
├── QUICKSTART.md              # 5-minute setup guide
├── API.md                     # Complete API reference
├── DEPLOYMENT.md              # Production deployment guide
├── TESTING.md                 # Testing guide
├── AGENTS.md                  # Agent workflow definitions
├── AGENT_MODELS.md            # Agent model assignments
├── pyproject.toml             # Python dependencies (uv)
├── package.json               # Frontend dependencies (npm)
├── manage.py                  # Management script
├── my-tracks-server           # Server startup script
├── setup                      # Automated setup script
├── test_tracker.py            # Python test suite
├── .env.example               # Environment template
├── config/                    # Project configuration
│   ├── __init__.py
│   ├── settings.py           # Application settings with type hints
│   ├── urls.py               # URL routing
│   ├── wsgi.py               # WSGI entry point
│   └── asgi.py               # ASGI entry point
├── my_tracks/                 # Location tracking app
│   ├── models.py             # Device & Location models
│   ├── serializers.py        # DRF serializers
│   ├── views.py              # API viewsets
│   ├── urls.py               # App routing
│   ├── admin.py              # Admin config
│   └── migrations/           # Database migrations
└── web_ui/                    # Web interface app
    ├── static/web_ui/
    │   ├── ts/               # TypeScript source
    │   ├── js/               # Compiled JavaScript
    │   └── css/              # Stylesheets
    └── templates/web_ui/     # HTML templates
```

## Features

### ✅ Implemented

- **OwnTracks HTTP Protocol Support**
  - Full compatibility with OwnTracks JSON format
  - Automatic field mapping (lat→latitude, lon→longitude, etc.)
  - Support for all optional fields

- **Device Management**
  - Automatic device registration on first location
  - Unique device identification via tracker ID
  - Last seen timestamp tracking

- **Location Persistence**
  - Complete location metadata storage
  - Timestamp-indexed queries
  - Device-specific location history

- **REST API**
  - `POST /api/locations/` - Submit location data
  - `GET /api/locations/` - Query location history
  - `GET /api/devices/` - List devices
  - `GET /api/devices/{id}/` - Device details
  - `GET /api/devices/{id}/locations/` - Device-specific locations

- **Filtering & Pagination**
  - Filter by device ID
  - Filter by date range (start_date, end_date)
  - Configurable page size (default: 100)
  - Offset-based pagination

- **Data Validation**
  - Latitude range validation (-90 to +90)
  - Longitude range validation (-180 to +180)
  - Battery level validation (0 to 100)
  - Informative error messages with expected vs actual values

- **Type Safety**
  - Full type hints throughout codebase
  - Python 3.14+ features (dataclasses where appropriate)
  - Type annotations on models, views, serializers

- **Admin Interface**
  - Web-based admin for device management
  - Location browsing and filtering
  - Search by device ID or name

- **Testing**
  - Comprehensive pytest test suite
  - Model tests
  - API endpoint tests
  - Validation tests
  - OwnTracks format tests

- **Documentation**
  - Complete API documentation
  - Quick start guide
  - Production deployment guide
  - Agent workflow definitions

- **Development Tools**
  - Automated setup script
  - Environment template
  - Type checking with pyright
  - Import sorting with isort
  - ESLint for TypeScript
  - Vitest for TypeScript tests

### 🔮 Future Enhancements

- Authentication (API keys, OAuth2, JWT)
- Rate limiting per device/IP
- Geofencing support
- Waypoints and regions (OwnTracks features)
- Location sharing between devices
- Data export (GPX, KML formats)
- Statistics and analytics dashboard
- Battery optimization suggestions
- Offline queue support

## Getting Started

### Quick Start (5 minutes)

```bash
# Run automated setup
./scripts/setup

# Start server
./scripts/my-tracks-server

# Test API
curl -X POST http://localhost:8080/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"lat": 37.7749, "lon": -122.4194, "tst": 1705329600, "tid": "AB"}'
```

See [QUICKSTART.md](QUICKSTART.md) for detailed instructions.

### Manual Setup

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Setup environment and install dependencies
uv sync --all-extras

# 3. Install frontend dependencies
npm install
npm run build

# 4. Initialize database
cp .env.example .env
uv run python manage.py migrate

# 5. Run server
./scripts/my-tracks-server
```

## API Examples

### Submit Location (OwnTracks Format)

```bash
curl -X POST http://localhost:8080/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{
    "_type": "location",
    "lat": 37.7749,
    "lon": -122.4194,
    "tst": 1705329600,
    "acc": 10,
    "alt": 50,
    "vel": 5,
    "batt": 85,
    "tid": "AB",
    "conn": "w"
  }'
```

### Query Locations

```bash
# All locations
curl http://localhost:8080/api/locations/

# Filter by device
curl "http://localhost:8080/api/locations/?device=AB"

# Filter by date range
curl "http://localhost:8080/api/locations/?start_date=2024-01-01T00:00:00Z&end_date=2024-01-31T23:59:59Z"

# Combine filters with pagination
curl "http://localhost:8080/api/locations/?device=AB&limit=50&offset=100"
```

See [API.md](API.md) for complete API documentation.

## Testing

```bash
# Install dev dependencies
uv sync --all-extras

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=my_tracks --cov-report=html

# Run specific test file
uv run pytest test_tracker.py

# Run specific test
uv run pytest test_tracker.py::TestLocationAPI::test_create_location_owntracks_format
```

## Code Quality

### Type Checking

```bash
uv run pyright
```

### Import Sorting

```bash
uv run isort my_tracks config web_ui
```

### Check All

```bash
uv run isort --check-only my_tracks config web_ui
uv run pyright
uv run pytest --cov=my_tracks --cov-fail-under=90
```

## Production Deployment

### Requirements

- Python 3.14+
- PostgreSQL 14+
- Nginx/Apache
- SSL certificate
- Domain name

### Quick Deploy

```bash
# 1. Setup PostgreSQL
sudo -u postgres psql
CREATE DATABASE owntracks;
CREATE USER owntrackuser WITH PASSWORD 'password';
GRANT ALL PRIVILEGES ON DATABASE owntracks TO owntrackuser;

# 2. Configure environment
cp .env.example .env
# Edit .env with production settings

# 3. Install dependencies
uv sync

# 4. Run migrations
uv run python manage.py migrate

# 5. Collect static files
uv run python manage.py collectstatic

# 6. Start with Daphne ASGI server
daphne -b 0.0.0.0 -p 8080 config.asgi:application
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete production setup.

## OwnTracks App Configuration

1. Install OwnTracks from Play Store or App Store
2. Settings → Connection → Mode: **HTTP**
3. URL: `http://your-server:8080/api/locations/`
4. Settings → Identification → Tracker ID: **AB** (2 chars)
5. Save and test connection

## Agent Workflow

This project uses a structured agent workflow defined in [AGENTS.md](AGENTS.md):

1. **Implementation Agent** - Core development
2. **Primary Critique Agent (Claude)** - Code review
3. **Secondary Critique Agent (GPT-5)** - Independent review
4. **Testing Agent** - Comprehensive testing

See [AGENTS.md](AGENTS.md) and [AGENT_MODELS.md](AGENT_MODELS.md) for details.

## Contributing

Contributions welcome! Please:

1. Follow PEP 8 style guidelines
2. Add type hints to all new code
3. Write tests for new features
4. Update documentation
5. Ensure all agents approve changes before PR

## License

PolyForm Noncommercial License 1.0.0 - See [LICENSE](LICENSE) file for details

## Support

- **API Docs**: [API.md](API.md)
- **Quick Start**: [QUICKSTART.md](QUICKSTART.md)
- **Deployment**: [DEPLOYMENT.md](DEPLOYMENT.md)
- **OwnTracks**: https://owntracks.org/booklet/

## Acknowledgments

- [OwnTracks](https://owntracks.org/) for the excellent location tracking app
- [Django](https://www.djangoproject.com/) and [Django REST Framework](https://www.django-rest-framework.org/)
- [amqtt](https://github.com/Yakifo/amqtt) for the embedded MQTT broker

---

**Status**: ✅ Production Ready
**Version**: 0.1.0
**Last Updated**: 2026
**Python**: 3.14+
