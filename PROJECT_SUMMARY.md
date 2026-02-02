# My Tracks - Project Summary

## Overview

A production-ready Django backend server for the OwnTracks Android/iOS app, designed to receive, persist, and serve geolocation data with modern Python 3.12+ features, comprehensive type hints, and RESTful API design.

**Package Management**: Uses [uv](https://github.com/astral-sh/uv) exclusively for fast, deterministic dependency management.

## Project Status

✅ **Complete Implementation** - Ready for development and production use

## Architecture

### Technology Stack

- **Framework**: Django 5.0+ with Django REST Framework
- **Language**: Python 3.12+ with full type hints
- **Package Manager**: `uv` for fast, reliable dependency management
- **Database**: SQLite (development) / PostgreSQL (production)
- **Server**: Gunicorn (production)
- **Testing**: pytest with pytest-django

### Key Components

1. **Device Management** (`tracker.models.Device`)
   - Unique device identification
   - Automatic device registration
   - Last seen tracking

2. **Location Tracking** (`tracker.models.Location`)
   - Comprehensive location metadata
   - Timestamp indexing for efficient queries
   - Support for all OwnTracks fields

3. **REST API** (`tracker.views`)
   - OwnTracks HTTP protocol compatibility
   - Location submission endpoint
   - Query endpoints with filtering
   - Pagination support

4. **Data Validation** (`tracker.serializers`)
   - OwnTracks format transformation
   - Coordinate validation (-90/+90 lat, -180/+180 lon)
   - Battery level validation (0-100)
   - Informative error messages

## Project Structure

```
my-tracks/
├── README.md                   # Main documentation
├── QUICKSTART.md              # 5-minute setup guide
├── API.md                     # Complete API reference
├── DEPLOYMENT.md              # Production deployment guide
├── AGENTS.md                  # Agent workflow definitions
├── AGENT_MODELS.md            # Agent model assignments
├── pyproject.toml             # Project configuration (uv)
├── manage.py                  # Django management script
├── setup                      # Automated setup script (no .sh extension)
├── install.py                 # File extraction script
├── PROJECT_FILES.txt          # All source files (for setup)
├── test_tracker.py            # Comprehensive test suite
├── .env.example               # Environment template
├── .gitignore                 # Git exclusions
├── mytracks/                  # Django project
│   ├── __init__.py
│   ├── settings.py           # Django settings with type hints
│   ├── urls.py               # URL routing
│   ├── wsgi.py               # WSGI entry point
│   └── asgi.py               # ASGI entry point
└── tracker/                   # Location tracking app
    ├── __init__.py
    ├── models.py             # Device & Location models
    ├── serializers.py        # DRF serializers
    ├── views.py              # API viewsets
    ├── urls.py               # App routing
    ├── admin.py              # Django admin config
    ├── apps.py               # App configuration
    └── migrations/           # Database migrations
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
  - Python 3.12+ features (dataclasses where appropriate)
  - Type annotations on models, views, serializers

- **Admin Interface**
  - Django admin for device management
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
  - Type checking with mypy
  - Code formatting with black
  - Linting with flake8

### 🔮 Future Enhancements

- **Server Management**
  - `start_server` script with smart restart and status checking (no .sh extension)
  - Automatic process detection and graceful shutdown
  - Support for both development and production servers
  
- Authentication (API keys, OAuth2, JWT)
- Rate limiting per device/IP
- Geofencing support
- Waypoints and regions (OwnTracks features)
- WebSocket for real-time updates
- Location sharing between devices
- Data export (GPX, KML formats)
- Statistics and analytics dashboard
- Battery optimization suggestions
- Offline queue support

## Getting Started

### Quick Start (5 minutes)

```bash
# Run automated setup
./setup


# Start server
python manage.py runserver

# Test API
curl -X POST http://localhost:8000/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"lat": 37.7749, "lon": -122.4194, "tst": 1705329600, "tid": "AB"}'
```

See [QUICKSTART.md](QUICKSTART.md) for detailed instructions.

### Manual Setup

```bash
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Extract project files
python3 install.py

# 3. Setup environment
uv venv && source .venv/bin/activate
uv pip install -e .

# 4. Initialize database
cp .env.example .env
python manage.py migrate

# 5. Run server
python manage.py runserver
```

## API Examples

### Submit Location (OwnTracks Format)

```bash
curl -X POST http://localhost:8000/api/locations/ \
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
curl http://localhost:8000/api/locations/

# Filter by device
curl "http://localhost:8000/api/locations/?device=AB"

# Filter by date range
curl "http://localhost:8000/api/locations/?start_date=2024-01-01T00:00:00Z&end_date=2024-01-31T23:59:59Z"

# Combine filters with pagination
curl "http://localhost:8000/api/locations/?device=AB&limit=50&offset=100"
```

See [API.md](API.md) for complete API documentation.

## Testing

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=tracker --cov-report=html

# Run specific test file
pytest test_tracker.py

# Run specific test
pytest test_tracker.py::TestLocationAPI::test_create_location_owntracks_format
```

## Code Quality

### Type Checking

```bash
mypy tracker/
```

### Code Formatting

```bash
black .
```

### Linting

```bash
flake8 .
```

## Production Deployment

### Requirements

- Python 3.12+
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
uv pip install -e .

# 4. Run migrations
python manage.py migrate

# 5. Collect static files
python manage.py collectstatic

# 6. Start with Gunicorn
gunicorn mytracks.wsgi:application --bind 0.0.0.0:8000
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete production setup.

## OwnTracks App Configuration

1. Install OwnTracks from Play Store or App Store
2. Settings → Connection → Mode: **HTTP**
3. URL: `http://your-server:8000/api/locations/`
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

MIT License - See LICENSE file for details

## Support

- **API Docs**: [API.md](API.md)
- **Quick Start**: [QUICKSTART.md](QUICKSTART.md)
- **Deployment**: [DEPLOYMENT.md](DEPLOYMENT.md)
- **OwnTracks**: https://owntracks.org/booklet/
- **Django**: https://docs.djangoproject.com/

## Acknowledgments

- OwnTracks project for the excellent location tracking app
- Django and Django REST Framework communities
- Python type hints and modern Python features

---

**Status**: ✅ Production Ready
**Version**: 0.1.0
**Last Updated**: 2024
**Python**: 3.12+
**Django**: 5.0+
