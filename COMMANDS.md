# My Tracks - Command Reference

Quick reference for all commonly used commands.

**Package Manager**: This project uses [uv](https://github.com/astral-sh/uv) exclusively for all dependency management.

## Setup Commands

### Initial Setup

```bash
# Automated setup (recommended)
bash setup

# Manual setup
./install
uv sync
```

### Verification

```bash
# Verify setup
./verify-setup

# Check Python version
uv run python --version

# Check Django installation
uv run python -c "import django; print(django.get_version())"
```

## Virtual Environment

**Note**: With `uv run`, you don't need to manually activate the virtual environment.
The `uv run` prefix automatically uses the project's virtual environment.

```bash
# Create virtual environment (uv venv creates .venv by default)
uv venv

# Run any command in the virtual environment
uv run <command>

# Example: run Python
uv run python

# Example: run Django management command
uv run python manage.py migrate
```

## Package Management (uv)

```bash
# Install production dependencies
uv sync

# Install with dev dependencies
uv sync --all-extras

# Update all packages (after editing pyproject.toml)
uv sync

# List installed packages
uv pip list

# Show package info
uv pip show django
```

## Installing uv

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify installation
uv --version
```

## Server Management

### Database

```bash
# Run migrations
uv run python manage.py migrate

# Create new migrations after model changes
uv run python manage.py makemigrations

# Show migrations
uv run python manage.py showmigrations

# Check for migration issues
uv run python manage.py makemigrations --check --dry-run

# Rollback migration
uv run python manage.py migrate my_tracks 0001  # Rollback to migration 0001

# Reset database (SQLite only)
rm db.sqlite3
uv run python manage.py migrate
```

### Server

```bash
# Start development server (default port 8080)
./my-tracks-server

# Start on different port
./my-tracks-server --port 18080

# Start with console logging (dual mode: console + file)
./my-tracks-server --console

# Start with debug log level
./my-tracks-server --log-level debug --console

# Let OS allocate ephemeral port (useful for testing)
./my-tracks-server --port 0
```

### Server Script Options

| Option | Description |
|--------|-------------|
| `--port PORT` | Set server port (default: 8080, use 0 for OS-allocated) |
| `--log-level LEVEL` | Set log level (debug, info, warning, error, critical) |
| `--console` | Enable dual logging: logs go to both console AND file |

### Admin

```bash
# Create superuser
uv run python manage.py createsuperuser

# Change user password
uv run python manage.py changepassword username

# Create superuser non-interactively
uv run python manage.py createsuperuser --username admin --email admin@example.com --noinput
```

### Shell

```bash
# Interactive shell
uv run python manage.py shell

# Shell with IPython
uv run python manage.py shell -i ipython

# Run Python file in app context
uv run python manage.py shell < script.py
```

### Static Files

```bash
# Collect static files
uv run python manage.py collectstatic

# Collect without prompts
uv run python manage.py collectstatic --noinput

# Clear existing and collect
uv run python manage.py collectstatic --clear --noinput
```

### Other Commands

```bash
# Check for common issues
uv run python manage.py check

# Check deployment settings
uv run python manage.py check --deploy

# Show version
uv run python manage.py version

# Clear expired sessions
uv run python manage.py clearsessions

# Show SQL for migration
uv run python manage.py sqlmigrate my_tracks 0001
```

## Testing

### Run Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest test_tracker.py

# Run specific test class
uv run pytest test_tracker.py::TestLocationAPI

# Run specific test
uv run pytest test_tracker.py::TestLocationAPI::test_create_location_owntracks_format

# Run with verbose output
uv run pytest -v

# Run with output capture disabled
uv run pytest -s

# Stop on first failure
uv run pytest -x

# Run last failed tests
uv run pytest --lf
```

### Coverage

```bash
# Run tests with coverage
uv run pytest --cov=my_tracks

# Generate HTML coverage report
uv run pytest --cov=my_tracks --cov-report=html

# Show coverage for specific module
uv run pytest --cov=my_tracks.models --cov-report=term-missing

# Coverage threshold (fail if below 90%)
uv run pytest --cov=my_tracks --cov-fail-under=90
```

### Frontend Tests

```bash
# Run TypeScript tests
npm run test

# Run tests in watch mode
npm run test:watch

# Run ESLint
npm run lint

# Build TypeScript
npm run build
```

### Backend Tests

```bash
# Run backend tests
uv run python manage.py test

# Run specific app tests
uv run python manage.py test my_tracks

# Run with verbose output
uv run python manage.py test --verbosity=2

# Keep test database
uv run python manage.py test --keepdb
```

## Code Quality

### Import Sorting (isort)

```bash
# Sort all imports
uv run isort my_tracks config web_ui

# Sort specific file
uv run isort my_tracks/models.py

# Check without modifying
uv run isort --check-only my_tracks config web_ui

# Show diff
uv run isort --diff my_tracks config web_ui
```

### Combined Quality Checks

```bash
# Run all quality checks
uv run isort --check-only my_tracks config web_ui
uv run pyright
uv run pytest --cov=my_tracks --cov-fail-under=90
```

### Type Checking

```bash
# Run pyright
uv run pyright

# Check specific file
uv run pyright my_tracks/models.py

# Run isort to sort imports
uv run isort my_tracks config web_ui

# Check imports without modifying
uv run isort --check-only my_tracks config web_ui
```

## API Testing

### cURL Examples

```bash
# Submit location
curl -X POST http://localhost:8080/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{"lat": 37.7749, "lon": -122.4194, "tst": 1705329600, "tid": "AB"}'

# Get all locations
curl http://localhost:8080/api/locations/

# Get locations for device
curl "http://localhost:8080/api/locations/?device=AB"

# Get locations with date filter
curl "http://localhost:8080/api/locations/?start_date=2024-01-01T00:00:00Z"

# Get with pagination
curl "http://localhost:8080/api/locations/?limit=10&offset=20"

# Get all devices
curl http://localhost:8080/api/devices/

# Get device details
curl http://localhost:8080/api/devices/AB/

# Get device locations
curl http://localhost:8080/api/devices/AB/locations/
```

### HTTPie Examples (if installed)

```bash
# Submit location
http POST localhost:8080/api/locations/ \
  lat=37.7749 lon=-122.4194 tst=1705329600 tid=AB

# Get locations
http GET localhost:8080/api/locations/ device==AB

# Pretty JSON
http --pretty=format GET localhost:8080/api/locations/
```

## Version Control (Graphite)

This project uses [Graphite](https://graphite.dev) for all version control operations. The `gt` command is a **passthrough for git** - all git commands work through `gt`, so always use `gt` instead of `git`.

### Why Graphite?

- **Git Passthrough**: All git commands work via `gt` (e.g., `gt status`, `gt diff`, `gt log`)
- **PR Stacking**: Create dependent PRs that automatically rebase
- **Automatic Cleanup**: Merged branches are auto-deleted
- **Better Workflow**: Single commands replace multi-step git operations
- **Force Push Safety**: Built-in protection against overwriting remote changes

### Common Commands

```bash
# Create a new branch with staged changes
gt create --all --message "feat: add new feature"

# Amend current branch commit
gt modify --all --message "feat: updated implementation"

# Submit PR(s) to GitHub
gt submit --no-interactive --publish

# View current stack
gt log short

# Sync with remote (fetch + rebase)
gt sync --force

# Switch branches
gt checkout <branch-name>

# Move up/down the stack
gt up
gt down

# Delete a branch
gt delete <branch-name>
```

### Git Passthrough Commands

Many git commands work through `gt`:

```bash
# Check status
gt status

# View changes
gt diff

# Fetch and prune
gt fetch --prune

# Other passthroughs
gt add, gt reset, gt restore, gt rebase, gt cherry-pick
```

### Commands Requiring Native Git

Some commands have different behavior in gt, so use native git:

```bash
# View commit history (gt log shows stack instead)
git log --oneline -10

# List all branches (gt branch is a subcommand)
git branch -a
```

### Initial Repository Setup

For new repositories only:

```bash
# Initialize repository
gt init  # Select trunk branch (main)

# Create .gitignore
cat > .gitignore << 'EOF'
__pycache__/
*.pyc
.venv/
db.sqlite3
.env
.DS_Store
node_modules/
dist/
EOF

# Initial commit
gt create --all --message "chore: initial commit"
gt submit --no-interactive --publish
```

## Production Commands

### Daphne ASGI Server

```bash
# Start Daphne (ASGI for WebSocket support)
daphne -b 0.0.0.0 -p 8080 config.asgi:application

# Development mode with my-tracks-server
./my-tracks-server

# With console logging
./my-tracks-server --console

# With debug level
./my-tracks-server --log-level debug
```

### Systemd

```bash
# Enable service
sudo systemctl enable my-tracks

# Start service
sudo systemctl start my-tracks

# Stop service
sudo systemctl stop my-tracks

# Restart service
sudo systemctl restart my-tracks

# Check status
sudo systemctl status my-tracks

# View logs
journalctl -u my-tracks -f
```

### Database Backup (PostgreSQL)

```bash
# Backup database
pg_dump owntracks > backup.sql

# Backup with compression
pg_dump owntracks | gzip > backup.sql.gz

# Restore database
psql owntracks < backup.sql

# Restore compressed
gunzip -c backup.sql.gz | psql owntracks
```

## Monitoring

```bash
# Watch location updates
watch -n 2 'curl -s http://localhost:8080/api/locations/?limit=1'

# Monitor logs
tail -f logs/my-tracks.log

# Monitor with console logging
./my-tracks-server --console

# Check disk usage
du -sh db.sqlite3

# Count locations in database
echo "SELECT COUNT(*) FROM my_tracks_location;" | uv run python manage.py dbshell
```

## Debugging

```bash
# Interactive shell with models loaded
uv run python manage.py shell
>>> from my_tracks.models import Device, Location
>>> Device.objects.all()
>>> Location.objects.count()

# Run with Python debugger
uv run python -m pdb manage.py runserver

# Enable SQL query logging (settings.py)
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}

# Test email (if configured)
uv run python manage.py sendtestemail admin@example.com
```

## Environment Variables

```bash
# Set environment variable (Unix/macOS)
export SECRET_KEY='your-secret-key'
export DEBUG=False

# Set environment variable (Windows)
set SECRET_KEY=your-secret-key
set DEBUG=False

# Load from .env file (with python-decouple)
# Automatically loaded by Django settings

# Check environment variable
echo $SECRET_KEY
printenv | grep DJANGO
```

## Troubleshooting

```bash
# Clear Python cache
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# Reinstall dependencies
uv sync --reinstall

# Check for port conflicts
lsof -i :8080  # Unix/macOS
netstat -ano | findstr :8080  # Windows

# Kill process on port
kill $(lsof -t -i:8080)  # Unix/macOS

# Reset migrations (careful!)
find . -path "*/migrations/*.py" -not -name "__init__.py" -delete
find . -path "*/migrations/*.pyc" -delete
uv run python manage.py makemigrations
uv run python manage.py migrate
```

## Quick Workflows

### Complete Fresh Start

```bash
rm -rf .venv db.sqlite3
uv sync --all-extras
uv run python manage.py migrate
uv run python manage.py createsuperuser
./my-tracks-server
```

### Deploy Update

```bash
gt sync --force
uv sync
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
sudo systemctl restart my-tracks
```

### Run Full Test Suite

```bash
uv run isort --check-only my_tracks config web_ui
uv run pyright
uv run pytest --cov=my_tracks --cov-report=html
uv run python manage.py check --deploy
```

## Help

```bash
# Management help
uv run python manage.py help

# Help for specific command
uv run python manage.py help migrate

# List all commands
uv run python manage.py help --commands

# uv help
uv --help

# pytest help
uv run pytest --help
```
