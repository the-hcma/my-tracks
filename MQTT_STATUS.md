# MQTT Implementation Status

**Last Updated**: February 17, 2026

## Overview

Implementing embedded MQTT broker for OwnTracks bidirectional communication.

**Goals**:
- Battery life improvement (MQTT vs HTTP polling)
- Bidirectional communication (send commands to devices)
- Real-time location updates

## Completed Phases

### Phase 1: Basic Broker ✅
- **PR #100** - amqtt dependency (MERGED)
- Added `amqtt` from git (Python 3.14 compatible)
- Created `MQTTBroker` class wrapper

### Phase 2: Message Handlers ✅
- **PR #101** - Location processing (MERGED)
- `OwnTracksMessageHandler` for parsing messages
- Topic parsing: `owntracks/{user}/{device}`
- Extract location, LWT, transition data

### Phase 3: Authentication ✅
- **PR #102** - Django user integration (MERGED)
- `DjangoAuthPlugin` for amqtt
- Topic-based ACL (users can only access their own topics)
- Uses `sync_to_async` for Django ORM in async context

### Phase 4: Command API ✅
- **PR #103** - REST API for commands (MERGED)
- `Command` class with factory methods
- `CommandPublisher` for MQTT publishing
- REST endpoints:
  - `POST /api/commands/report-location/`
  - `POST /api/commands/set-waypoints/`
  - `POST /api/commands/clear-waypoints/`

### Phase 5.1: Server Integration ✅
- **PR #104** - MQTT broker startup (MERGED)
- `--mqtt-port` flag (default: 1883, 0 = OS allocates, -1 = disabled)
- `--http-port` flag (renamed from `--port`)
- Runtime config via JSON file (`config/.runtime-config.json`)
- OS-allocated port discovery via `actual_mqtt_port` property
- ASGI lifespan handler starts/stops broker

## Phase 5: Integration (IN PROGRESS)

### Tasks:
1. ~~**Server integration**~~ ✅ (PR #104)

2. **Admin UI MQTT endpoint display** ← NEXT
   - Show MQTT connection details in admin web UI
   - Display MQTT host and port for OwnTracks app configuration
   - Help users configure OwnTracks app with correct endpoint

3. **Traffic generator MQTT support**
   - Add `--mqtt` flag to traffic generator script
   - Send location data via MQTT in addition to existing HTTP mode
   - Use same OwnTracks message format as real devices

4. **Wire message handlers**
   - Connect `OwnTracksMessageHandler` to broker
   - Process incoming location messages → save to database
   - Broadcast to WebSocket clients

5. **LWT handling**
   - Detect device offline via Last Will messages
   - Update device status in database

6. **Transition events**
   - Handle region enter/exit events
   - Store transition history

7. **Waypoints sync**
   - Connect waypoint storage to command API
   - Allow UI to send waypoints to devices

## Key Files

```
my_tracks/mqtt/
├── __init__.py      # Module exports
├── broker.py        # MQTTBroker class
├── handlers.py      # OwnTracksMessageHandler
├── auth.py          # DjangoAuthPlugin
└── commands.py      # Command, CommandPublisher
```

## Test Coverage

- 175 tests passing
- 91.30% code coverage
- All pyright checks pass

## Technical Notes

- **Python 3.14 compatibility**: amqtt installed from git, not PyPI
- **Django ORM in async**: Use `sync_to_async` wrapper
- **SQLite async tests**: Use `@pytest.mark.django_db(transaction=True)`

## Next Steps

Phase 5 (Integration) is ready to begin. All prerequisite PRs are merged.

## Future Enhancements

- **MQTT over TLS** - Add `--mqtt-tls-port` (8883) for encrypted connections
