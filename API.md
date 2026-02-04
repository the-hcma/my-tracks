# API Documentation

Complete API reference for the OwnTracks Backend.

## Base URL

Development: `http://localhost:8080/api/`
Production: `https://yourdomain.com/api/`

## Authentication

Currently, the API uses device identification via the `tid` (tracker ID) field in OwnTracks payloads. Each device is automatically created when it first sends location data.

For production, consider adding:
- API key authentication
- OAuth2
- JWT tokens

## Endpoints

### 1. Submit Location Data

**Endpoint:** `POST /api/locations/`

Submit location data from an OwnTracks client.

#### OwnTracks Format Request

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

#### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_type` | string | No | Message type (usually "location") |
| `lat` | float | Yes | Latitude in decimal degrees (-90 to +90) |
| `lon` | float | Yes | Longitude in decimal degrees (-180 to +180) |
| `tst` | integer | Yes | Unix timestamp (seconds since epoch) |
| `acc` | integer | No | Accuracy in meters |
| `alt` | integer | No | Altitude in meters |
| `vel` | integer | No | Velocity/speed in km/h |
| `batt` | integer | No | Battery level (0-100) |
| `tid` | string | Yes | Tracker ID (device identifier, 2 chars) |
| `conn` | string | No | Connection type: 'w'=WiFi, 'm'=Mobile, 'o'=Offline |

#### Response

**Success (201 Created):**
```json
{
  "status": "ok",
  "message": "Location received"
}
```

**Error (400 Bad Request):**
```json
{
  "lat": [
    "Expected latitude between -90 and +90 degrees, got 91.0"
  ]
}
```

#### Example with cURL

```bash
curl -X POST http://localhost:8080/api/locations/ \
  -H "Content-Type: application/json" \
  -d '{
    "_type": "location",
    "lat": 37.7749,
    "lon": -122.4194,
    "tst": 1234567890,
    "tid": "AB"
  }'
```

---

### 2. List Location History

**Endpoint:** `GET /api/locations/`

Retrieve location history with optional filtering.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `device` | string | Filter by device ID (e.g., "AB") |
| `start_date` | ISO 8601 | Filter locations after this date |
| `end_date` | ISO 8601 | Filter locations before this date |
| `limit` | integer | Results per page (default: 100) |
| `offset` | integer | Pagination offset |

#### Response

```json
{
  "count": 150,
  "next": "http://localhost:8080/api/locations/?limit=100&offset=100",
  "previous": null,
  "results": [
    {
      "id": 1,
      "device": 1,
      "latitude": "37.774900",
      "longitude": "-122.419400",
      "timestamp": "2024-01-15T10:30:00Z",
      "accuracy": 10,
      "altitude": 50,
      "velocity": 5,
      "battery_level": 85,
      "connection_type": "w",
      "received_at": "2024-01-15T10:30:05Z"
    }
  ]
}
```

#### Examples

**Filter by device:**
```bash
curl "http://localhost:8080/api/locations/?device=AB"
```

**Filter by date range:**
```bash
curl "http://localhost:8080/api/locations/?start_date=2024-01-01T00:00:00Z&end_date=2024-01-31T23:59:59Z"
```

**Combine filters:**
```bash
curl "http://localhost:8080/api/locations/?device=AB&start_date=2024-01-01T00:00:00Z&limit=50"
```

---

### 3. List Devices

**Endpoint:** `GET /api/devices/`

Retrieve list of all registered devices.

#### Response

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "device_id": "AB",
      "name": "Device AB",
      "created_at": "2024-01-01T10:00:00Z",
      "last_seen": "2024-01-15T14:30:00Z",
      "location_count": 1250
    },
    {
      "id": 2,
      "device_id": "CD",
      "name": "Device CD",
      "created_at": "2024-01-05T08:00:00Z",
      "last_seen": "2024-01-15T14:25:00Z",
      "location_count": 850
    }
  ]
}
```

#### Example

```bash
curl "http://localhost:8080/api/devices/"
```

---

### 4. Get Device Details

**Endpoint:** `GET /api/devices/{device_id}/`

Retrieve details for a specific device.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `device_id` | string | Device identifier (e.g., "AB") |

#### Response

```json
{
  "id": 1,
  "device_id": "AB",
  "name": "Device AB",
  "created_at": "2024-01-01T10:00:00Z",
  "last_seen": "2024-01-15T14:30:00Z",
  "location_count": 1250
}
```

#### Example

```bash
curl "http://localhost:8080/api/devices/AB/"
```

---

### 5. Get Device Locations

**Endpoint:** `GET /api/devices/{device_id}/locations/`

Retrieve all locations for a specific device.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `device_id` | string | Device identifier (e.g., "AB") |

Supports same query parameters as `/api/locations/` for date filtering and pagination.

#### Response

Same format as `/api/locations/` but filtered to the specified device.

#### Example

```bash
curl "http://localhost:8080/api/devices/AB/locations/?limit=50"
```

---

## Error Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request - Invalid input data |
| 404 | Not Found - Resource doesn't exist |
| 500 | Internal Server Error |

## Error Response Format

All errors return a JSON response with details:

```json
{
  "error": "Expected valid device ID, got 'XYZ' which does not exist"
}
```

Or for validation errors:

```json
{
  "field_name": [
    "Error message describing what was expected vs what was received"
  ]
}
```

## Rate Limiting

Currently no rate limiting is implemented. For production, consider adding:

- Per-device rate limits
- IP-based rate limits
- Django middleware like `django-ratelimit`

## Data Types

### Device Object

```typescript
{
  id: number;
  device_id: string;
  name: string;
  created_at: string;  // ISO 8601
  last_seen: string;   // ISO 8601
  location_count: number;
}
```

### Location Object

```typescript
{
  id: number;
  device: number;
  latitude: string;          // Decimal string
  longitude: string;         // Decimal string
  timestamp: string;         // ISO 8601
  accuracy: number | null;
  altitude: number | null;
  velocity: number | null;
  battery_level: number | null;
  connection_type: string;   // 'w', 'm', 'o', or ''
  received_at: string;       // ISO 8601
}
```

## Integration Examples

### Python

```python
import requests
from datetime import datetime

# Submit location
location_data = {
    "_type": "location",
    "lat": 37.7749,
    "lon": -122.4194,
    "tst": int(datetime.now().timestamp()),
    "tid": "PY",
    "acc": 10,
    "batt": 85
}

response = requests.post(
    "http://localhost:8080/api/locations/",
    json=location_data
)
print(response.json())

# Get location history
response = requests.get(
    "http://localhost:8080/api/locations/",
    params={"device": "PY", "limit": 10}
)
locations = response.json()["results"]
```

### JavaScript

```javascript
// Submit location
const locationData = {
  _type: "location",
  lat: 37.7749,
  lon: -122.4194,
  tst: Math.floor(Date.now() / 1000),
  tid: "JS",
  acc: 10,
  batt: 85
};

fetch("http://localhost:8080/api/locations/", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(locationData)
})
  .then(response => response.json())
  .then(data => console.log(data));

// Get location history
fetch("http://localhost:8080/api/locations/?device=JS&limit=10")
  .then(response => response.json())
  .then(data => console.log(data.results));
```

### OwnTracks App Configuration

1. Open OwnTracks app
2. Go to Settings → Connection
3. Set Mode to "HTTP"
4. Set URL to: `http://your-server:8080/api/locations/`
5. Leave authentication empty (or add if implemented)
6. Save and test connection

## Best Practices

1. **Timestamps**: Always use UTC timezone
2. **Coordinates**: Use 6 decimal places for ~10cm precision
3. **Device IDs**: Use short, unique identifiers (2-10 chars)
4. **Batch Uploads**: Consider batching for efficiency
5. **Error Handling**: Always check response status codes

## Future Enhancements

Planned features for future versions:

- [ ] Authentication (API keys, OAuth2)
- [ ] Geofencing support
- [ ] Location sharing between devices
- [ ] Waypoints and regions
- [x] WebSocket support for real-time updates (implemented - see [WEBSOCKET.md](WEBSOCKET.md))
- [ ] Data export (GPX, KML formats)
- [ ] Location statistics and analytics
