# Testing Guide

This document provides guidelines for testing the OwnTracks backend server.

## Test Port Configuration

**For automated tests**: Use port **0** to let the OS allocate an ephemeral port. This prevents port conflicts when running multiple tests.

**For manual testing**: Use port **18080** to avoid conflicts with production servers on port 8080.

### Starting the Test Server

```bash
# Start test server on port 18080
./my-tracks-server --port 18080

# With dual logging (console + file) for debugging
./my-tracks-server --port 18080 --console

# With debug log level
./my-tracks-server --port 18080 --log-level debug --console
```

### Test URLs

When testing, use these URLs:

- **Web Interface**: http://localhost:18080/
- **API Endpoint**: http://localhost:18080/api/locations/
- **WebSocket**: ws://localhost:18080/ws/locations/

## Running Unit Tests

```bash
# Run all tests with coverage
uv run pytest --cov=my_tracks --cov-fail-under=90

# Run specific test file
uv run pytest test_tracker.py -v

# Run specific test
uv run pytest test_tracker.py::TestLocationAPI::test_create_location -v
```

## Running Frontend Tests

```bash
# Run TypeScript tests
npm run test

# Run with watch mode
npm run test:watch

# Run ESLint
npm run lint
```

## Manual Testing

### Testing Location Submission

```bash
# Submit a location (replace TEST_DEVICE with your device ID)
curl -X POST http://localhost:18080/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{
    "_type": "location",
    "tid": "hc",
    "lat": 37.7749,
    "lon": -122.4194,
    "tst": '$(date +%s)',
    "topic": "owntracks/user/TEST_DEVICE"
  }'
```

### Testing Trail Visualization

1. Start test server on port 18080
2. Create test trail data:

```bash
# Create multiple locations over time for a device
for i in {1..10}; do
  curl -X POST http://localhost:18080/api/locations/ \
    -H "Content-Type: application/json" \
    -d '{
      "_type": "location",
      "tid": "hc",
      "lat": '$(echo "37.7749 + $i * 0.001" | bc)',
      "lon": '$(echo "-122.4194 + $i * 0.001" | bc)',
      "tst": '$(echo "$(date +%s) - (10 - $i) * 300" | bc)',
      "topic": "owntracks/user/TEST_DEVICE"
    }'
  sleep 0.5
done
```

3. Open http://localhost:18080/ in browser
4. Select device from dropdown
5. Adjust time range slider
6. Verify trail appears on map

### Testing WebSocket Updates

1. Start test server on port 18080
2. Open http://localhost:18080/ in browser
3. Open browser console
4. Submit a location via curl (see above)
5. Verify live marker appears on map
6. Check console for WebSocket messages

## Coverage Requirements

- **Minimum coverage**: 90%
- Run coverage check: `uv run pytest --cov=my_tracks --cov-fail-under=90`

## Pre-PR Checklist

Before creating a pull request:

- [ ] All Python tests pass: `uv run pytest`
- [ ] Coverage ≥ 90%: `uv run pytest --cov=my_tracks --cov-fail-under=90`
- [ ] Type checking passes: `uv run pyright`
- [ ] Imports sorted: `uv run isort --check-only my_tracks config web_ui`
- [ ] All TypeScript tests pass: `npm run test`
- [ ] ESLint passes: `npm run lint`
- [ ] No pytest warnings
- [ ] VS Code Problems panel is clear
- [ ] Shell scripts pass shellcheck
- [ ] Manual testing on port 18080 successful
- [ ] CI/CD pipeline passes

## Port Reference

| Port  | Purpose                          |
|-------|----------------------------------|
| 8080  | Production server (default)      |
| 18080 | Testing server (use for testing) |

## Common Test Scenarios

### Test Case: Device ID Extraction

Verify device ID is correctly extracted from OwnTracks topic:

- Input topic: `owntracks/user/hcma`
- Expected device_id: `hcma`
- Expected tracker_id: `hc` (from tid field)

### Test Case: Time Range Filtering

1. Create locations spanning 6 hours
2. Filter with 2-hour time range
3. Verify only recent locations returned

### Test Case: Live Updates

1. Open map in browser
2. Submit location via API
3. Verify marker appears without page refresh
4. Verify activity log updates

## Troubleshooting

### Port Already in Use

If port 18080 is already in use:

```bash
# Find process using port 18080
lsof -i :18080

# Kill process if needed
kill -9 <PID>
```

### Database Issues

Reset test database:

```bash
# Remove database
rm db.sqlite3

# Run migrations
uv run python manage.py migrate
```

### WebSocket Connection Failed

1. Verify server is running on correct port
2. Check browser console for errors
3. Ensure no firewall blocking WebSocket connections
4. Try with `--console` flag to see server logs
