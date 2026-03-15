# MQTT Implementation Plan

## Overview

Add MQTT broker support to my-tracks for OwnTracks app connectivity, enabling:
- **Battery efficiency**: Persistent connection instead of repeated HTTP handshakes
- **Bidirectional communication**: Server can send commands to devices

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      my-tracks-server                            │
│                                                                  │
│  ┌──────────────┐         ┌──────────────────────────────────┐  │
│  │   Daphne     │         │          amqtt Broker            │  │
│  │  (HTTP/WS)   │         │                                  │  │
│  │  Port 8080   │         │  Port 1883 (MQTT)               │  │
│  └──────┬───────┘         │  Port 8083 (MQTT over WebSocket) │  │
│         │                 └──────────────┬───────────────────┘  │
│         │                                │                       │
│         │    ┌───────────────────────────┘                      │
│         │    │                                                   │
│         ▼    ▼                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Django ORM / Location Model                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                     SQLite DB                             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                    ┌─────────┴─────────┐
                    │   OwnTracks App   │
                    │   (MQTT Mode)     │
                    └───────────────────┘
```

## OwnTracks MQTT Topics

### Device Publishes To:
| Topic | Type | Description |
|-------|------|-------------|
| `owntracks/{user}/{device}` | location | Location updates |
| `owntracks/{user}/{device}` | lwt | Last Will & Testament (offline) |
| `owntracks/{user}/{device}/event` | transition | Enter/leave region events |
| `owntracks/{user}/{device}/waypoint` | waypoint | Single waypoint created |
| `owntracks/{user}/{device}/waypoints` | waypoints | Exported waypoint list |
| `owntracks/{user}/{device}/status` | status | Device status |

### Server Publishes To (commands):
| Topic | Action | Description |
|-------|--------|-------------|
| `owntracks/{user}/{device}/cmd` | reportLocation | Request immediate location |
| `owntracks/{user}/{device}/cmd` | setWaypoints | Push waypoints to device |
| `owntracks/{user}/{device}/cmd` | setConfiguration | Push config to device |
| `owntracks/{user}/{device}/cmd` | clearWaypoints | Delete all waypoints |
| `owntracks/{user}/{device}/cmd` | dump | Request config dump |
| `owntracks/{user}/{device}/cmd` | status | Request status message |

## Implementation Phases

### Phase 1: Basic MQTT Broker (PR #1)
- [ ] Add `amqtt` dependency to pyproject.toml
- [ ] Create `my_tracks/mqtt/broker.py` - broker configuration
- [ ] Create `my_tracks/mqtt/plugin.py` - message handler plugin
- [ ] Update `my-tracks-server` to start both HTTP and MQTT
- [ ] Basic tests for broker startup/shutdown

### Phase 2: Location Processing (PR #2)
- [ ] Handle `_type=location` messages
- [ ] Parse OwnTracks JSON format
- [ ] Save to existing Location model
- [ ] Broadcast to WebSocket (existing functionality)
- [ ] Tests for location message handling

### Phase 3: Authentication (PR #3)
- [ ] Implement Django user authentication for MQTT
- [ ] Username/password validation against Django users
- [ ] Topic ACL (users can only publish to their topics)
- [ ] Tests for auth scenarios

### Phase 4: Command API (PR #4)
- [ ] REST API endpoint: `POST /api/devices/{device}/cmd/`
- [ ] Support for `reportLocation` command
- [ ] Support for `setWaypoints` command
- [ ] Web UI button to request location update
- [ ] Tests for command delivery

### Phase 5: Additional Message Types (PR #5)
- [ ] Handle `_type=lwt` (device offline detection)
- [ ] Handle `_type=transition` (region enter/leave)
- [ ] Handle `_type=waypoint` / `_type=waypoints`
- [ ] Store/display transitions in activity log

## File Structure

```
my_tracks/
├── mqtt/
│   ├── __init__.py
│   ├── broker.py          # amqtt broker configuration
│   ├── handlers.py        # Message type handlers
│   ├── auth.py            # Django user authentication plugin
│   └── commands.py        # Command publishing utilities
├── ...
```

## Configuration

### Server Ports
| Service | Port | Protocol |
|---------|------|----------|
| HTTP/WebSocket | 8080 | HTTP/WS |
| MQTT | 1883 | TCP |
| MQTT over WS | 8083 | WebSocket |

### Environment Variables
```bash
MQTT_PORT=1883              # MQTT TCP port
MQTT_WS_PORT=8083           # MQTT WebSocket port
MQTT_ANONYMOUS=false        # Allow anonymous connections
```

### OwnTracks App Configuration
```json
{
    "_type": "configuration",
    "mode": 0,
    "host": "your-server.com",
    "port": 1883,
    "tls": false,
    "auth": true,
    "username": "your-username",
    "password": "your-password",
    "deviceId": "phone",
    "pubTopicBase": "owntracks/%u/%d"
}
```

## amqtt Broker Configuration

```python
MQTT_CONFIG = {
    "listeners": {
        "default": {
            "type": "tcp",
            "bind": "0.0.0.0:1883",
        },
        "ws-mqtt": {
            "type": "ws",
            "bind": "0.0.0.0:8083",
        },
    },
    "plugins": {
        # Custom auth plugin using Django users
        "my_tracks.mqtt.auth.DjangoAuthPlugin": {},
        # Custom handler plugin for OwnTracks messages
        "my_tracks.mqtt.handlers.OwnTracksHandlerPlugin": {},
    },
    "topic-check": {
        "enabled": True,
        # Users can only publish/subscribe to their own topics
        "plugins": ["my_tracks.mqtt.auth.DjangoTopicACL"],
    },
}
```

## Testing Strategy

### Unit Tests
- Broker startup/shutdown
- Message parsing (all OwnTracks types)
- Authentication validation
- Topic ACL enforcement

### Integration Tests
- MQTT client publishes location → saved to DB
- MQTT client publishes location → broadcast to WebSocket
- REST API sends command → device receives via MQTT
- Device reconnection handling

### Manual Testing
- Configure OwnTracks app in MQTT mode
- Verify location updates appear in web UI
- Test "Request Location" button
- Test region enter/leave notifications

## Dependencies

```toml
# pyproject.toml additions
dependencies = [
    # ... existing deps ...
    "amqtt>=0.11.3",
]
```

## Migration Notes

- HTTP mode continues to work unchanged
- Users can choose HTTP or MQTT in OwnTracks app
- Both protocols save to the same Location model
- WebSocket broadcasts work for both HTTP and MQTT sources

## Security Considerations

1. **Authentication**: All MQTT connections require valid user credentials
2. **Topic ACL**: Users can only access `owntracks/{their-user}/*`
3. **TLS**: Phase 6 will add TLS support on port 8883
4. **Rate limiting**: Consider adding publish rate limits

## Future Enhancements (Post-MVP)

- [ ] TLS/SSL support (port 8883)
- [ ] QoS 2 support for guaranteed delivery
- [ ] Retained messages for last known location
- [ ] Friends feature (see other users' locations)
- [ ] Card support (user avatars/names)
- [ ] Encrypted payloads support
