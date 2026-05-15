# My Tracks - Documentation Index

Complete guide to all project documentation.

**Package Manager**: This project uses [uv](https://github.com/astral-sh/uv) exclusively for all dependency management.

## 📖 Core Documentation

### [README.md](README.md)
Main project documentation with overview, features, and basic setup instructions.

### [QUICKSTART.md](QUICKSTART.md)
Get the project running in 5 minutes. Start here if you're new.

### [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)
Comprehensive overview of the project architecture, features, and status.

## 🚀 Setup & Installation

### [QUICKSTART.md](QUICKSTART.md)
Quick 5-minute setup guide with automated and manual options.

### [scripts/setup](../scripts/setup)
Automated setup script - run `bash scripts/setup` to set up everything.

### [scripts/verify-setup](../scripts/verify-setup)
Verification script to check if installation is complete and correct.

## 📚 API & Usage

### [API.md](API.md)
Complete API reference with all endpoints, parameters, examples, and response formats.

### [ANDROID_CERTS.md](ANDROID_CERTS.md)
How to install and remove the My Tracks CA and client certificate on Android for MQTT over TLS.

### [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
Common issues and solutions: OwnTracks commands, MQTT/TLS, PWA install banner, service worker registration.

### [COMMANDS.md](COMMANDS.md)
Quick reference for all commonly used commands (server management, testing, deployment, etc.).

## 🚢 Deployment

### [DEPLOYMENT.md](DEPLOYMENT.md)
Production deployment guide covering PostgreSQL, Nginx, SSL, and security (containerized stack).

### [PWA.md](PWA.md)
Install the web dashboard on a phone or tablet home screen (manifest, service worker, mobile install banner). Requires HTTPS or localhost for the full install flow.

### [SYSTEMD.md](SYSTEMD.md)
Run My Tracks as a persistent systemd user service on your local machine using `setup-service` from [repository-helpers](https://github.com/the-hcma/repository-helpers).

### Server
Uses Daphne ASGI server for WebSocket support. See [WEBSOCKET.md](WEBSOCKET.md).

## 🧪 Testing

### [tests/python/test_tracker.py](../tests/python/test_tracker.py)
Comprehensive pytest test suite for models, API, and OwnTracks compatibility.

### Running Tests
```bash
uv run pytest                      # Run all tests
uv run pytest --cov=app      # With coverage
```

## 👥 Development Workflow

### [AGENTS.md](AGENTS.md)
Development agent workflow and responsibilities for the project.

### [AGENT_MODELS.md](AGENT_MODELS.md)
Model assignments for different agent roles.

## 📦 Configuration Files

### [pyproject.toml](pyproject.toml)
Modern Python project configuration with dependencies (use `uv sync` to install).

### [examples/.env.example](../examples/.env.example)
Template for environment variables. Copy to `.env` and customize.

### [.gitignore](.gitignore)
Git ignore patterns for Python and development files.

## 🗂️ Source Code Structure

```
my-tracks/
├── manage.py                 # Management script
├── scripts/
│   └── my-tracks-server      # Server startup script
├── config/                   # Project configuration package
│   ├── __init__.py
│   ├── settings.py          # Project settings with type hints
│   ├── urls.py              # Main URL routing
│   ├── wsgi.py              # WSGI entry point
│   └── asgi.py              # ASGI entry point
├── app/                      # Location tracking app
│   ├── models.py            # Device & Location models
│   ├── serializers.py       # DRF serializers for OwnTracks
│   ├── views.py             # API viewsets
│   ├── urls.py              # App URL routing
│   ├── admin.py             # Admin configuration
│   └── migrations/          # Database migrations
└── web_ui/                   # Web interface app
    ├── static/web_ui/       # Static files (TS, JS, CSS, PWA manifest/sw/icons)
    └── templates/web_ui/    # HTML templates
```

## 📄 License & Contributing

### [LICENSE](LICENSE)
PolyForm Noncommercial 1.0.0 - Allows personal use, education, and research. Commercial use requires permission.

### Contributing
See [AGENTS.md](AGENTS.md) for the development workflow and agent responsibilities.

## 🔗 Quick Links by Task

### I want to...

**Get started quickly**
→ [QUICKSTART.md](QUICKSTART.md)

**Understand the API**
→ [API.md](API.md)

**Deploy to production**
→ [DEPLOYMENT.md](DEPLOYMENT.md)

**Run as a background service (local dev)**
→ [SYSTEMD.md](SYSTEMD.md)

**Install the web UI on a phone**
→ [PWA.md](PWA.md)

**Find a specific command**
→ [COMMANDS.md](COMMANDS.md)

**Understand the architecture**
→ [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)

**Run tests**
→ [tests/python/test_tracker.py](../tests/python/test_tracker.py) + `pytest`

**Configure OwnTracks app**
→ [QUICKSTART.md](QUICKSTART.md#configure-owntracks-app)

**Contribute to the project**
→ [AGENTS.md](AGENTS.md)

**Troubleshoot issues**
→ [COMMANDS.md](COMMANDS.md#troubleshooting)

**Set up environment variables**
→ [examples/.env.example](../examples/.env.example) + [README.md](README.md#installation)

## 📊 Project Files Overview

| File | Purpose | For Who |
|------|---------|---------|
| AGENTS.md | Development workflow | Contributors |
| API.md | API reference | Developers/Integrators |
| COMMANDS.md | Command reference | Developers |
| DEPLOYMENT.md | Production setup | DevOps/Admins |
| PROJECT_SUMMARY.md | Project overview | Everyone |
| PWA.md | Installable web dashboard | Users / mobile |
| QUICKSTART.md | 5-minute setup | New users |
| README.md | Main documentation | Everyone |
| SYSTEMD.md | Local systemd user service | Developers |
| pyproject.toml | Package config | Build tools |
| manage.py | CLI | Developers |
| scripts/setup | Auto setup | New users |
| scripts/verify-setup | Setup verification | Everyone |
| tests/python/test_tracker.py | Test suite | Developers/QA |

## 🎯 Getting Help

1. **Quick questions**: Check [COMMANDS.md](COMMANDS.md)
2. **API usage**: See [API.md](API.md)
3. **Setup issues**: Run `./scripts/verify-setup`
4. **Deployment questions**: Read [DEPLOYMENT.md](DEPLOYMENT.md)
5. **OwnTracks questions**: Visit https://owntracks.org/booklet/

## 📝 Documentation Standards

All documentation follows these principles:
- **Clear**: Easy to understand for target audience
- **Complete**: Covers all necessary information
- **Current**: Kept up-to-date with code changes
- **Practical**: Includes examples and real-world usage
- **Type-safe**: Code examples use type hints

## 🔄 Documentation Updates

When making changes:
1. Update relevant documentation files
2. Update this index if adding new docs
3. Run verification: `./scripts/verify-setup`
4. Test any code examples in docs
5. Update PROJECT_SUMMARY.md if architecture changes

---

**Last Updated**: 2026
**Project Version**: 0.1.0
**Python Version**: 3.14+
