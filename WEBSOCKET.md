# WebSocket Real-Time Updates

## Overview

The My Tracks backend now supports WebSocket connections for real-time location updates. This eliminates polling delays and provides instant notifications when new location data arrives.

## Architecture

### Components

1. **Channels**: ASGI support for WebSocket protocol
2. **Daphne**: ASGI server for production
3. **LocationConsumer**: WebSocket consumer handling client connections
4. **Channel Layer**: In-memory message bus for broadcasting updates

### Flow

```
OwnTracks Client → HTTP POST → LocationViewSet
                                      ↓
                             Channel Layer Broadcast
                                      ↓
                       WebSocket Clients (via LocationConsumer)
                                      ↓
                              Live Activity UI Updates
```

## Connection

### WebSocket URL

```
ws://localhost:8080/ws/locations/
```

For production (HTTPS):
```
wss://your-domain.com/ws/locations/
```

### JavaScript Example

```javascript
const ws = new WebSocket('ws://localhost:8080/ws/locations/');

ws.onopen = () => {
    console.log('Connected to location updates');
};

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'location') {
        console.log('New location:', message.data);
        // message.data contains full location details
    }
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = () => {
    console.log('Disconnected');
};
```

## Message Format

### Outgoing (Server → Client)

When a new location is received, all connected clients receive:

```json
{
  "type": "location",
  "data": {
    "id": 123,
    "device": 1,
    "device_name": "housemeister",
    "latitude": "37.774900",
    "longitude": "-122.419400",
    "timestamp": "2024-01-15T10:30:00Z",
    "timestamp_unix": 1705329000,
    "accuracy": 10,
    "altitude": 50,
    "velocity": 5,
    "battery_level": 85,
    "connection_type": "w",
    "ip_address": "192.168.1.100"
  }
}
```

## Frontend Implementation

The home page automatically uses WebSocket for real-time updates with automatic fallback to polling if WebSocket connection fails.

### Features

- **Automatic connection**: Connects on page load
- **Reconnection**: Exponential backoff (up to 5 attempts)
- **Fallback**: Falls back to HTTP polling if WebSocket unavailable
- **Historical data**: Initial HTTP fetch for existing locations
- **Real-time**: Instant updates via WebSocket for new locations

## Testing

### Unit Tests

```bash
# Run all tests including WebSocket tests
uv run pytest test_websocket.py -v

# Test specific WebSocket functionality
uv run pytest test_websocket.py::TestLocationConsumer::test_websocket_connect -v
```

### Manual Testing

1. Start server: `./my-tracks-server`
2. Open browser to `http://localhost:8080/`
3. Run load generator: `./generate_load`
4. Watch Live Activity panel update in real-time

## Configuration

### settings.py

```python
# Add to INSTALLED_APPS (daphne must be first)
INSTALLED_APPS = [
    'daphne',
    ...
    'channels',
    ...
]

# ASGI application
ASGI_APPLICATION = 'config.asgi.application'

# Channel layers (in-memory for development)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}
```

### Production Considerations

For production, use Redis-backed channel layer:

```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('127.0.0.1', 6379)],
        },
    },
}
```

Install: `uv pip install channels-redis`

## Benefits

1. **Instant updates**: No 2-second polling delay
2. **Reduced load**: No unnecessary HTTP requests
3. **Better UX**: Smoother, more responsive interface
4. **Scalable**: Channel layers handle multiple clients efficiently
5. **Reliable**: Automatic fallback to polling if WebSocket unavailable

## Compatibility

- **Modern browsers**: Chrome, Firefox, Safari, Edge (all support WebSocket)
- **Mobile**: iOS Safari, Chrome Mobile
- **Legacy**: Falls back to HTTP polling automatically

## Debugging

### Check WebSocket connection in browser

```javascript
// In browser console
console.log('WebSocket ready state:', ws.readyState);
// 0 = CONNECTING, 1 = OPEN, 2 = CLOSING, 3 = CLOSED
```

### Server logs

Start with debug logging:

```bash
./my-tracks-server --log-level debug --console
```

Watch for:
- WebSocket connection established
- Channel layer broadcasts
- Client disconnections
