"""
URL configuration for mytracks project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
"""
import logging
import socket

from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver

logger = logging.getLogger(__name__)

# Track last known IP to detect changes
_last_known_ip: str | None = None


def health(request):
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


def network_info(request):
    """Return current network information for dynamic UI updates."""
    global _last_known_ip

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "Unable to detect"

    hostname = socket.gethostname()

    # Log if IP changed
    if _last_known_ip is not None and _last_known_ip != local_ip:
        logger.info(f"Network IP changed: {_last_known_ip} -> {local_ip}")
    _last_known_ip = local_ip

    return JsonResponse({
        'hostname': hostname,
        'local_ip': local_ip,
        'port': 8080
    })


def home(request):
    """Home page with API information."""
    # Get local IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "Unable to detect"

    hostname = socket.gethostname()

    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>My Tracks - OwnTracks Backend</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🗺️</text></svg>">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <style>
        :root {{
            --bg-main: #ffffff;
            --bg-left: #1e1e1e;
            --text-main: #2c3e50;
            --text-secondary: #34495e;
            --text-left: #d4d4d4;
            --border-color: #333;
            --endpoint-bg: #f8f9fa;
            --endpoint-border: #007bff;
            --code-bg: #e9ecef;
            --log-entry-bg: #2d2d2d;
            --log-entry-border: #4CAF50;
            --log-time-color: #858585;
            --link-color: #007bff;
            --status-color: #28a745;
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-main: #1e1e1e;
                --text-main: #e0e0e0;
                --text-secondary: #b0b0b0;
                --endpoint-bg: #2d2d2d;
                --code-bg: #3d3d3d;
                --link-color: #4a9eff;
            }}
        }}

        [data-theme="light"] {{
            --bg-main: #ffffff;
            --bg-left: #f5f5f5;
            --text-main: #2c3e50;
            --text-secondary: #34495e;
            --text-left: #2c3e50;
            --border-color: #ddd;
            --endpoint-bg: #f8f9fa;
            --endpoint-border: #007bff;
            --code-bg: #e9ecef;
            --log-entry-bg: #ffffff;
            --log-entry-border: #28a745;
            --log-time-color: #666666;
            --link-color: #007bff;
            --status-color: #28a745;
            --log-device-color: #0c7c59;
            --log-coords-color: #b8530d;
            --right-header-color: #2c3e50;
        }}

        [data-theme="dark"] {{
            --bg-main: #1e1e1e;
            --bg-left: #0d0d0d;
            --text-main: #e0e0e0;
            --text-secondary: #b0b0b0;
            --text-left: #d4d4d4;
            --border-color: #3a3a3a;
            --endpoint-bg: #2d2d2d;
            --endpoint-border: #4a9eff;
            --code-bg: #3d3d3d;
            --log-entry-bg: #2d2d2d;
            --log-entry-border: #4CAF50;
            --log-time-color: #858585;
            --link-color: #4a9eff;
            --status-color: #4CAF50;
            --log-device-color: #4ec9b0;
            --log-coords-color: #ce9178;
            --right-header-color: #ffffff;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 0;
            line-height: 1.6;
            background: var(--bg-main);
            color: var(--text-main);
            transition: background-color 0.3s ease, color 0.3s ease;
        }}
        .container {{
            display: grid;
            grid-template-columns: 1fr 3fr;
            height: 100vh;
            gap: 0;
        }}
        .left-column {{
            padding: 20px 40px;
            overflow-y: auto;
            background: var(--bg-main);
            color: var(--text-main);
        }}
        .right-column {{
            background: var(--bg-left);
            color: var(--text-left);
            padding: 20px;
            overflow-y: hidden;
            border-left: 1px solid var(--border-color);
            display: grid;
            grid-template-rows: 1fr 1fr;
            gap: 20px;
        }}
        h1 {{ color: var(--text-main); margin-top: 0; }}
        h2 {{ color: var(--text-secondary); margin-top: 30px; }}
        .right-column h2 {{ color: var(--right-header-color); margin-top: 0; }}
        .endpoint {{
            background: var(--endpoint-bg);
            border-left: 4px solid var(--endpoint-border);
            padding: 15px;
            margin: 15px 0;
            transition: background-color 0.3s ease;
        }}
        .method {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 12px;
            margin-right: 10px;
        }}
        .get {{ background: #28a745; color: white; }}
        .post {{ background: #007bff; color: white; }}
        code {{
            background: var(--code-bg);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Monaco', 'Courier New', monospace;
            color: var(--text-main);
            transition: background-color 0.3s ease;
        }}
        a {{ color: var(--link-color); text-decoration: none; transition: color 0.3s ease; }}
        a:hover {{ text-decoration: underline; }}
        .log-entry {{
            background: var(--log-entry-bg);
            border-left: 3px solid var(--log-entry-border);
            padding: 8px 12px;
            margin: 5px 0;
            border-radius: 4px;
            font-size: 12px;
            font-family: 'Monaco', 'Courier New', monospace;
            white-space: nowrap;
            overflow-x: auto;
        }}
        .log-time {{
            color: var(--log-time-color);
            display: inline;
        }}
        .log-device {{
            color: var(--log-device-color);
            font-weight: bold;
            display: inline;
            margin: 0 8px;
        }}
        .log-ip {{
            color: #7c7cff;
            display: inline;
            margin-right: 8px;
            font-family: 'Monaco', 'Courier New', monospace;
        }}
        .log-coords {{
            color: var(--log-coords-color);
            display: inline;
            margin-right: 8px;
        }}
        .log-meta {{
            color: var(--text-secondary);
            display: inline;
            font-size: 11px;
        }}
        .log-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        .log-controls {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .log-count {{
            background: #007bff;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
        }}
        .reset-button {{
            background: #dc3545;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .reset-button:hover {{
            background: #c82333;
            transform: scale(1.05);
        }}
        #log-container {{
            background: var(--code-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 15px;
            height: calc(100vh - 150px);
            overflow-y: auto;
            scroll-behavior: smooth;
        }}
        #loading {{
            color: var(--log-time-color);
            font-style: italic;
        }}
        .header-toggle {{
            background: var(--endpoint-bg);
            border: 2px solid var(--border-color);
            border-radius: 50px;
            padding: 6px 14px;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s ease;
        }}
        .header-toggle:hover {{
            transform: scale(1.1);
        }}
        .status-indicator {{
            background: var(--endpoint-bg);
            border: 2px solid var(--border-color);
            border-radius: 50px;
            padding: 6px 14px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .status-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #ffc107;
            transition: background 0.3s ease;
        }}
        .status-dot.connected {{
            background: #28a745;
        }}
        .status-dot.disconnected {{
            background: #dc3545;
        }}
        .container.sidebar-collapsed {{
            grid-template-columns: 0fr 1fr;
        }}
        .container.sidebar-collapsed .left-column {{
            padding: 0;
            overflow: hidden;
            opacity: 0;
            pointer-events: none;
        }}
        .left-column {{
            transition: padding 0.3s ease, opacity 0.3s ease;
        }}
        .map-section {{
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        .map-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            gap: 10px;
        }}
        .map-controls {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .device-selector,
        .time-range-selector,
        .resolution-selector {{
            background: var(--endpoint-bg);
            color: var(--text-main);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 12px;
            cursor: pointer;
        }}
        .mode-toggle {{
            display: flex;
            background: var(--endpoint-bg);
            border: 2px solid var(--border-color);
            border-radius: 20px;
            overflow: hidden;
        }}
        .mode-toggle button {{
            background: transparent;
            border: none;
            padding: 6px 16px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            color: var(--text-main);
        }}
        .mode-toggle button.active {{
            background: #007bff;
            color: white;
        }}
        .mode-toggle button:hover:not(.active) {{
            background: var(--code-bg);
        }}
        #map {{
            flex: 1;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            min-height: 0;
        }}
        .activity-section {{
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transition: opacity 0.3s ease, filter 0.3s ease;
        }}
        .activity-section.inactive {{
            opacity: 0.4;
            filter: grayscale(50%);
            pointer-events: none;
        }}
        .hidden {{
            display: none !important;
        }}
        /* Leaflet tooltip styling for waypoints - prevent wrapping */
        .waypoint-tooltip.leaflet-tooltip {{
            max-width: none !important;
            white-space: nowrap !important;
        }}
    </style>
</head>
<body>
    <div class="container" id="main-container">
        <div class="left-column">
            <h1>🗺️ My Tracks - OwnTracks Backend</h1>
            <p>A backend server for the OwnTracks Android/iOS app.</p>

            <h2>🌐 Network Access</h2>
    <div class="endpoint" id="network-info">
        <p><strong>Hostname:</strong> <code id="network-hostname">{hostname}</code></p>
        <p><strong>Local IP:</strong> <code id="network-ip">{local_ip}</code></p>
        <p><strong>Port:</strong> <code>8080</code></p>
        <p style="margin-top: 10px;">Access from other devices on your LAN:</p>
        <p><code id="network-url">http://{local_ip}:8080/</code></p>
    </div>

    <h2>📍 API Endpoints</h2>

    <div class="endpoint">
        <span class="method get">GET</span>
        <a href="/api/">/api/</a>
        <p>API root - Browse all available endpoints</p>
    </div>

    <div class="endpoint">
        <span class="method post">POST</span>
        <span class="method get">GET</span>
        <a href="/api/locations/">/api/locations/</a>
        <p>Submit and query location data</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <a href="/api/devices/">/api/devices/</a>
        <p>View registered devices</p>
    </div>

    <div class="endpoint">
        <span class="method get">GET</span>
        <a href="/admin/">/admin/</a>
        <p>Admin interface (requires superuser)</p>
    </div>

    <h2>🧪 Test the API</h2>
    <p>Submit a test location:</p>
    <pre><code>curl -X POST http://{local_ip}:8080/api/locations/ \\
  -H "Content-Type: application/json" \\
  -d '{{"lat": 37.7749, "lon": -122.4194, "tst": 1705329600, "tid": "AB"}}'</code></pre>

    <h2>📚 Documentation</h2>
    <ul>
        <li><a href="https://github.com/thehcma/my-tracks">GitHub Repository</a></li>
        <li>See <code>API.md</code> for complete API reference</li>
        <li>See <code>README.md</code> for setup instructions</li>
    </ul>
        </div>

        <div class="right-column">
            <div class="map-section">
                <div class="map-header">
                    <h2 id="map-title">🗺️ Live Map</h2>
                    <div class="map-controls">
                        <div class="mode-toggle">
                            <button id="live-mode-btn" class="active">📡 Live</button>
                            <button id="historic-mode-btn">📅 Historic</button>
                        </div>
                        <select class="time-range-selector hidden" id="time-range-selector">
                            <option value="1">Last 1 hour</option>
                            <option value="2" selected>Last 2 hours</option>
                            <option value="6">Last 6 hours</option>
                            <option value="12">Last 12 hours</option>
                            <option value="24">Last 24 hours</option>
                        </select>
                        <select class="resolution-selector hidden" id="resolution-selector" title="Trail precision: Coarse ~10 pts/hr, Medium ~20 pts/hr, Precise all">
                            <option value="360">🔍 Coarse</option>
                            <option value="180">📍 Medium</option>
                            <option value="0" selected>🎯 Precise</option>
                        </select>
                        <select class="device-selector hidden" id="device-selector">
                            <option value="">All Devices</option>
                        </select>
                        <div class="status-indicator" id="server-status-indicator" title="Server status">
                            <span class="status-dot" id="status-dot"></span>
                            <span id="status-text">Checking...</span>
                        </div>
                        <button class="header-toggle" id="sidebar-toggle" aria-label="Toggle sidebar">◀</button>
                        <button class="header-toggle" id="theme-toggle" aria-label="Toggle theme">🌙</button>
                    </div>
                </div>
                <div id="map"></div>
            </div>
            <div class="activity-section">
                <div class="log-header">
                    <h2 id="activity-title">📍 Live Activity</h2>
                    <div class="log-controls">
                        <span class="log-count" id="log-count">0 events</span>
                        <button class="reset-button" id="reset-button" title="Clear all events">🗑️ Reset</button>
                    </div>
                </div>
                <div id="log-container">
                    <p id="loading">Waiting for location updates...</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        let lastTimestamp = null;
        let eventCount = 0;
        let isServerConnected = false;
        let map = null;
        let deviceMarkers = {{}};
        let deviceTrails = {{}};
        let devices = new Set();
        let selectedDevice = '';
        let timeRangeHours = 2;
        let trailResolution = 0; // 0 = precise (all points), 360 = coarse (~10/hour)
        let isLiveMode = true; // Track current mode
        let needsFitBounds = true; // Only fit bounds on initial trail load
        let isRestoringState = false; // Flag to prevent saving during restore

        // UI State persistence
        function saveUIState() {{
            // Don't save while restoring state
            if (isRestoringState) return;

            const state = {{
                isLiveMode: isLiveMode,
                selectedDevice: selectedDevice,
                timeRangeHours: timeRangeHours,
                trailResolution: trailResolution
            }};
            localStorage.setItem('mytracks-ui-state', JSON.stringify(state));
        }}

        // Save map position separately (called on map move/zoom)
        function saveMapPosition() {{
            if (!map || isRestoringState) return;
            const center = map.getCenter();
            const mapState = {{
                lat: center.lat,
                lng: center.lng,
                zoom: map.getZoom()
            }};
            localStorage.setItem('mytracks-map-position', JSON.stringify(mapState));
        }}

        function loadMapPosition() {{
            try {{
                const saved = localStorage.getItem('mytracks-map-position');
                if (saved) {{
                    return JSON.parse(saved);
                }}
            }} catch (e) {{
                console.error('Error loading map position:', e);
            }}
            return null;
        }}

        function loadUIState() {{
            try {{
                const saved = localStorage.getItem('mytracks-ui-state');
                if (saved) {{
                    return JSON.parse(saved);
                }}
            }} catch (e) {{
                console.error('Error loading UI state:', e);
            }}
            return null;
        }}

        // Store pending restore state for after devices are loaded
        let pendingRestoreState = null;

        function restoreUIState() {{
            const state = loadUIState();
            if (!state) return;

            isRestoringState = true;

            // Restore time range
            if (state.timeRangeHours) {{
                timeRangeHours = state.timeRangeHours;
                document.getElementById('time-range-selector').value = timeRangeHours;
            }}

            // Restore resolution
            if (state.trailResolution !== undefined) {{
                trailResolution = state.trailResolution;
                document.getElementById('resolution-selector').value = trailResolution;
            }}

            // Restore mode
            if (state.isLiveMode === false) {{
                // Store state for device restoration after devices load
                pendingRestoreState = state;
                switchToHistoricMode();
            }}

            isRestoringState = false;
        }}

        // Called after devices are populated to complete restoration
        function completeStateRestore() {{
            if (!pendingRestoreState || !pendingRestoreState.selectedDevice) return;

            const selector = document.getElementById('device-selector');
            const deviceOption = selector.querySelector(`option[value="${{pendingRestoreState.selectedDevice}}"]`);

            if (deviceOption) {{
                isRestoringState = true;
                selectedDevice = pendingRestoreState.selectedDevice;
                selector.value = selectedDevice;
                // Don't fit bounds - we have a saved map position
                fetchAndDisplayTrail();
                isRestoringState = false;
            }}

            pendingRestoreState = null;
        }}

        // Date formatting helper
        function formatDateForTitle(date) {{
            const options = {{ weekday: 'short', month: 'short', day: 'numeric' }};
            return date.toLocaleDateString('en-US', options);
        }}

        function getDateRangeText(hours) {{
            const now = new Date();
            const startDate = new Date(now.getTime() - hours * 60 * 60 * 1000);

            // If same day, just show one date
            if (startDate.toDateString() === now.toDateString()) {{
                return formatDateForTitle(now);
            }}
            // Otherwise show range
            return `${{formatDateForTitle(startDate)}} - ${{formatDateForTitle(now)}}`;
        }}

        // Theme management
        function getPreferredTheme() {{
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme) {{
                return savedTheme;
            }}
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }}

        function setTheme(theme) {{
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            const toggle = document.getElementById('theme-toggle');
            toggle.textContent = theme === 'dark' ? '☀️' : '🌙';
        }}

        function toggleTheme() {{
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        }}

        // Sidebar collapse management
        function getSidebarState() {{
            // Default to collapsed, but respect user preference if set
            const saved = localStorage.getItem('sidebar-collapsed');
            if (saved === null) {{
                return true;  // Default: collapsed
            }}
            return saved === 'true';
        }}

        function setSidebarState(collapsed) {{
            const container = document.getElementById('main-container');
            const toggle = document.getElementById('sidebar-toggle');
            if (collapsed) {{
                container.classList.add('sidebar-collapsed');
                toggle.textContent = '▶';
            }} else {{
                container.classList.remove('sidebar-collapsed');
                toggle.textContent = '◀';
            }}
            localStorage.setItem('sidebar-collapsed', collapsed);
            // Invalidate map size after transition
            setTimeout(() => {{
                if (map) map.invalidateSize();
            }}, 350);
        }}

        function toggleSidebar() {{
            const container = document.getElementById('main-container');
            const isCollapsed = container.classList.contains('sidebar-collapsed');
            setSidebarState(!isCollapsed);
        }}

        // Initialize sidebar state
        setSidebarState(getSidebarState());
        document.getElementById('sidebar-toggle').addEventListener('click', toggleSidebar);

        // Initialize theme
        setTheme(getPreferredTheme());

        // Initialize map
        function initMap() {{
            map = L.map('map', {{
                dragging: true,
                touchZoom: true,
                scrollWheelZoom: true,
                doubleClickZoom: true,
                boxZoom: true
            }});

            // Restore saved map position or use default
            const savedPosition = loadMapPosition();
            if (savedPosition) {{
                map.setView([savedPosition.lat, savedPosition.lng], savedPosition.zoom);
                // Don't fit bounds on restore since we have a saved position
                needsFitBounds = false;
            }} else {{
                map.setView([37.7749, -122.4194], 17);
            }}

            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 19
            }}).addTo(map);

            // Save map position on move/zoom
            map.on('moveend', saveMapPosition);
            map.on('zoomend', saveMapPosition);

            // Fix map rendering after initial load
            setTimeout(() => map.invalidateSize(), 100);
        }}

        // Initialize map after page load
        window.addEventListener('load', initMap);

        // Update device marker on map
        function updateDeviceMarker(location) {{
            const deviceName = location.device_name || 'Unknown';
            const lat = parseFloat(location.latitude);
            const lon = parseFloat(location.longitude);

            if (isNaN(lat) || isNaN(lon)) return;

            // Add device to set and update selector
            if (!devices.has(deviceName)) {{
                devices.add(deviceName);
                const selector = document.getElementById('device-selector');
                const option = document.createElement('option');
                option.value = deviceName;
                option.textContent = deviceName;
                selector.appendChild(option);

                // Try to complete state restoration if we just added the pending device
                if (pendingRestoreState && pendingRestoreState.selectedDevice === deviceName) {{
                    completeStateRestore();
                }}
            }}

            // In live mode, show all devices; in historic mode, filter by selection
            if (!isLiveMode && selectedDevice && selectedDevice !== deviceName) {{
                // Hide marker if it exists
                if (deviceMarkers[deviceName]) {{
                    deviceMarkers[deviceName].remove();
                    delete deviceMarkers[deviceName];
                }}
                return;
            }}

            const latLng = [lat, lon];

            if (deviceMarkers[deviceName]) {{
                // Update existing marker
                deviceMarkers[deviceName].setLatLng(latLng);
                deviceMarkers[deviceName].setPopupContent(getPopupContent(location));
            }} else {{
                // Create new marker
                const marker = L.marker(latLng).addTo(map);
                marker.bindPopup(getPopupContent(location));
                deviceMarkers[deviceName] = marker;
            }}

            // Center map on the marker in live mode only
            if (isLiveMode) {{
                map.setView(latLng, map.getZoom());
            }}
            // In historic mode, don't auto-refresh trail on every location update
        }}

        function getPopupContent(location) {{
            const device = location.device_name || 'Unknown';
            const time = formatTime(location.timestamp_unix);
            const lat = parseFloat(location.latitude).toFixed(6);
            const lon = parseFloat(location.longitude).toFixed(6);
            const acc = location.accuracy || 'N/A';
            const batt = location.battery_level || 'N/A';
            const vel = location.velocity || 0;

            return `<div style="font-size: 12px;">
                <strong>${{device}}</strong><br>
                <em>${{time}}</em><br>
                <strong>Position:</strong> ${{lat}}, ${{lon}}<br>
                <strong>Accuracy:</strong> ${{acc}}m<br>
                <strong>Speed:</strong> ${{vel}} km/h<br>
                <strong>Battery:</strong> ${{batt}}%
            </div>`;
        }}

        // Cache for reverse geocoding results
        const geocodeCache = new Map();
        const geocodingQueue = [];
        let isProcessingQueue = false;
        const GEOCODING_DELAY = 1000; // 1 second delay between requests

        // Process geocoding queue one at a time
        async function processGeocodingQueue() {{
            if (isProcessingQueue || geocodingQueue.length === 0) {{
                return;
            }}

            isProcessingQueue = true;

            while (geocodingQueue.length > 0) {{
                const {{ lat, lon, resolve, reject }} = geocodingQueue.shift();

                try {{
                    const address = await fetchAddress(lat, lon);
                    resolve(address);
                }} catch (error) {{
                    reject(error);
                }}

                // Wait before processing next request
                if (geocodingQueue.length > 0) {{
                    await new Promise(resolve => setTimeout(resolve, GEOCODING_DELAY));
                }}
            }}

            isProcessingQueue = false;
        }}

        // Fetch address from coordinates using Nominatim reverse geocoding
        async function fetchAddress(lat, lon) {{
            try {{
                const response = await fetch(
                    `https://nominatim.openstreetmap.org/reverse?format=json&lat=${{lat}}&lon=${{lon}}&zoom=18&addressdetails=1`,
                    {{
                        headers: {{
                            'User-Agent': 'OwnTracks-Backend/1.0'
                        }}
                    }}
                );

                if (!response.ok) {{
                    console.error('Geocoding failed:', response.status);
                    return `${{lat.toFixed(3)}}, ${{lon.toFixed(3)}}`;
                }}

                const data = await response.json();
                return data.display_name || `${{lat.toFixed(3)}}, ${{lon.toFixed(3)}}`;
            }} catch (error) {{
                console.error('Geocoding error:', error);
                return `${{lat.toFixed(3)}}, ${{lon.toFixed(3)}}`;
            }}
        }}

        // Queue-based geocoding to prevent overwhelming the API
        async function getAddress(lat, lon) {{
            const key = `${{lat.toFixed(6)}},${{lon.toFixed(6)}}`;

            // Check cache first
            if (geocodeCache.has(key)) {{
                return geocodeCache.get(key);
            }}

            // Add to queue and return a promise
            return new Promise((resolve, reject) => {{
                geocodingQueue.push({{ lat, lon, resolve, reject }});
                processGeocodingQueue();
            }}).then(address => {{
                // Cache the result
                geocodeCache.set(key, address);
                return address;
            }});
        }}

        // Collapse consecutive waypoints at the same location into a single point
        // Uses the oldest timestamp for the collapsed point (first occurrence in chronological order)
        // Threshold: locations within ~10 meters are considered "same location"
        function collapseLocations(locations) {{
            if (locations.length === 0) return [];

            const PRECISION = 4;  // ~11 meters precision at equator
            const collapsed = [];
            let currentGroup = [locations[0]];
            let currentKey = `${{parseFloat(locations[0].latitude).toFixed(PRECISION)}},${{parseFloat(locations[0].longitude).toFixed(PRECISION)}}`;

            for (let i = 1; i < locations.length; i++) {{
                const loc = locations[i];
                const key = `${{parseFloat(loc.latitude).toFixed(PRECISION)}},${{parseFloat(loc.longitude).toFixed(PRECISION)}}`;

                if (key === currentKey) {{
                    // Same location - add to current group
                    currentGroup.push(loc);
                }} else {{
                    // New location - save current group and start new one
                    // Use the OLDEST (first) location in the group as the representative
                    const representative = {{ ...currentGroup[0], _collapsedCount: currentGroup.length }};
                    collapsed.push(representative);
                    currentGroup = [loc];
                    currentKey = key;
                }}
            }}

            // Don't forget the last group
            if (currentGroup.length > 0) {{
                const representative = {{ ...currentGroup[0], _collapsedCount: currentGroup.length }};
                collapsed.push(representative);
            }}

            return collapsed;
        }}

        // Fetch and display location trail for selected device and time range
        async function fetchAndDisplayTrail() {{
            const now = Date.now() / 1000;
            const startTime = now - (timeRangeHours * 3600);

            // Clear existing trails
            Object.values(deviceTrails).forEach(trail => {{
                if (trail.polyline) trail.polyline.remove();
                if (trail.markers) trail.markers.forEach(m => m.remove());
            }});
            deviceTrails = {{}};

            if (!selectedDevice) {{
                // "All Devices" selected - show all device markers
                try {{
                    let url = `/api/locations/?start_time=${{Math.floor(startTime)}}&ordering=-timestamp&limit=1000`;
                    if (trailResolution > 0) {{
                        url += `&resolution=${{trailResolution}}`;
                    }}
                    const response = await fetch(url);
                    if (!response.ok) return;

                    const data = await response.json();
                    const locations = data.results || [];

                    // Show summary in activity section
                    displayHistoricWaypoints(locations);

                    // Group locations by device and show latest marker for each
                    const latestByDevice = {{}};
                    locations.forEach(loc => {{
                        const device = loc.device_name || 'Unknown';
                        if (!latestByDevice[device]) {{
                            latestByDevice[device] = loc;
                        }}
                    }});

                    // Create markers for each device's latest position
                    Object.values(latestByDevice).forEach(loc => {{
                        updateDeviceMarker(loc);
                    }});

                    // Fit bounds to show all devices
                    if (needsFitBounds && Object.keys(latestByDevice).length > 0) {{
                        const bounds = L.latLngBounds(
                            Object.values(latestByDevice).map(loc => 
                                [parseFloat(loc.latitude), parseFloat(loc.longitude)]
                            )
                        );
                        if (Object.keys(latestByDevice).length === 1) {{
                            map.setView(bounds.getCenter(), 17);
                        }} else {{
                            map.fitBounds(bounds, {{ padding: [50, 50], maxZoom: 17 }});
                        }}
                        needsFitBounds = false;
                    }}
                }} catch (error) {{
                    console.error('Error fetching all devices:', error);
                }}
                return;
            }}

            try {{
                let url = `/api/locations/?device=${{selectedDevice}}&start_time=${{Math.floor(startTime)}}&ordering=-timestamp&limit=1000`;
                if (trailResolution > 0) {{
                    url += `&resolution=${{trailResolution}}`;
                }}
                const response = await fetch(url);
                if (!response.ok) return;

                const data = await response.json();
                const locations = data.results || [];

                // Update activity section with waypoints
                displayHistoricWaypoints(locations);

                if (locations.length === 0) return;

                // Clear old trail for this device
                if (deviceTrails[selectedDevice]) {{
                    if (deviceTrails[selectedDevice].polyline) {{
                        deviceTrails[selectedDevice].polyline.remove();
                    }}
                    if (deviceTrails[selectedDevice].markers) {{
                        deviceTrails[selectedDevice].markers.forEach(m => m.remove());
                    }}
                }}

                // Get locations in chronological order (oldest first)
                const chronologicalLocations = locations
                    .filter(loc => loc.latitude && loc.longitude)
                    .reverse();

                // Collapse consecutive waypoints at same location (only shows movement)
                // Each collapsed point uses the oldest timestamp from the group
                const collapsedLocations = collapseLocations(chronologicalLocations);

                // Create path from collapsed location coordinates
                const path = collapsedLocations.map(loc => 
                    [parseFloat(loc.latitude), parseFloat(loc.longitude)]
                );

                const trailElements = {{ polyline: null, markers: [] }};

                if (path.length > 0) {{
                    // Add numbered waypoint markers (using collapsed locations)
                    collapsedLocations.forEach((loc, index) => {{
                        const waypointNumber = index + 1;
                        const latLng = [parseFloat(loc.latitude), parseFloat(loc.longitude)];
                        const collapsedCount = loc._collapsedCount || 1;

                        // Create custom numbered icon
                        const waypointIcon = L.divIcon({{
                            className: 'waypoint-marker',
                            html: `<div style="
                                background-color: #007bff;
                                color: white;
                                border: 2px solid white;
                                border-radius: 50%;
                                width: 24px;
                                height: 24px;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 12px;
                                font-weight: bold;
                                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                            ">${{waypointNumber}}</div>`,
                            iconSize: [24, 24],
                            iconAnchor: [12, 12]
                        }});

                        // Format timestamp for display
                        const timestamp = loc.timestamp_unix ? 
                            new Date(loc.timestamp_unix * 1000).toLocaleString() : 
                            'Unknown time';

                        // Show count if multiple waypoints were collapsed at this location
                        const countInfo = collapsedCount > 1 ? 
                            `<br><i>(${{collapsedCount}} waypoints)</i>` : '';

                        const marker = L.marker(latLng, {{ 
                            icon: waypointIcon
                        }}).addTo(map);

                        // Add tooltip with waypoint info (shown on hover)
                        marker.bindTooltip(
                            `<b>#${{waypointNumber}}</b><br>${{timestamp}}${{countInfo}}`,
                            {{ 
                                permanent: false, 
                                direction: 'top',
                                offset: [0, -12],
                                className: 'waypoint-tooltip'
                            }}
                        );

                        // Create popup content (will be updated with address on click)
                        const collapsedInfo = collapsedCount > 1 ? 
                            `<i>(${{collapsedCount}} waypoints at this location)</i><br>` : '';
                        const popupContent = `
                            <div class="waypoint-popup">
                                <b>Waypoint #${{waypointNumber}}</b><br>
                                ${{timestamp}}<br>
                                ${{collapsedInfo}}
                                <span class="loading-address">📍 Click to load address...</span>
                            </div>
                        `;
                        marker.bindPopup(popupContent);

                        // Lazy load address on click
                        marker.on('click', async function() {{
                            const popup = this.getPopup();
                            const content = popup.getContent();

                            // Only geocode if not already loaded
                            if (content.includes('loading-address')) {{
                                try {{
                                    const address = await reverseGeocode(latLng[0], latLng[1]);
                                    const newContent = `
                                        <div class="waypoint-popup">
                                            <b>Waypoint #${{waypointNumber}}</b><br>
                                            ${{timestamp}}<br>
                                            📍 ${{address}}
                                        </div>
                                    `;
                                    popup.setContent(newContent);
                                }} catch (e) {{
                                    console.error('Geocoding error:', e);
                                }}
                            }}
                        }});

                        trailElements.markers.push(marker);
                    }});

                    // Draw polyline for trail (only if multiple points)
                    if (path.length > 1) {{
                        const polyline = L.polyline(path, {{
                            color: '#007bff',
                            weight: 3,
                            opacity: 0.7
                        }}).addTo(map);

                        trailElements.polyline = polyline;
                    }}

                    deviceTrails[selectedDevice] = trailElements;

                    // Fit map to show all waypoints only on initial load
                    if (needsFitBounds) {{
                        if (path.length === 1) {{
                            // Single location - center and zoom to street level
                            map.setView(path[0], 17);
                        }} else {{
                            // Multiple locations - fit to show all with appropriate padding
                            const bounds = L.latLngBounds(path);
                            map.fitBounds(bounds, {{ 
                                padding: [50, 50],
                                maxZoom: 17  // Don't zoom in too much even for close points
                            }});
                        }}
                        needsFitBounds = false;
                    }}
                }}

                // Update main marker to most recent location
                if (locations.length > 0) {{
                    updateDeviceMarker(locations[0]);
                }}
            }} catch (error) {{
                console.error('Error fetching trail:', error);
            }}
        }}

        // Device selector change handler
        document.getElementById('device-selector').addEventListener('change', (e) => {{
            selectedDevice = e.target.value;

            // Clear all markers and trails
            Object.values(deviceMarkers).forEach(marker => marker.remove());
            deviceMarkers = {{}};
            Object.values(deviceTrails).forEach(trail => {{
                if (trail.polyline) trail.polyline.remove();
                if (trail.markers) trail.markers.forEach(m => m.remove());
            }});
            deviceTrails = {{}};

            // Fit bounds when changing device selection
            needsFitBounds = true;

            // Fetch and display trail for selected device (only in historic mode)
            if (!isLiveMode) {{
                fetchAndDisplayTrail();
            }}

            // Save UI state
            saveUIState();
        }});

        // Time range selector change handler
        document.getElementById('time-range-selector').addEventListener('change', (e) => {{
            timeRangeHours = parseInt(e.target.value);

            // Update title with new date range
            const dateRangeText = getDateRangeText(timeRangeHours);
            document.getElementById('activity-title').textContent = `📅 Historic Trail - ${{dateRangeText}}`;

            // Fit bounds when changing time range
            needsFitBounds = true;

            // Refresh trail with new time range (only in historic mode)
            if (!isLiveMode) {{
                fetchAndDisplayTrail();
            }}

            // Save UI state
            saveUIState();
        }});

        // Resolution selector change handler
        document.getElementById('resolution-selector').addEventListener('change', (e) => {{
            trailResolution = parseInt(e.target.value);

            // Refresh trail with new resolution (only in historic mode)
            if (!isLiveMode) {{
                fetchAndDisplayTrail();
            }}

            // Save UI state
            saveUIState();
        }});

        // Mode toggle handlers
        function switchToLiveMode() {{
            isLiveMode = true;

            // Update button states
            document.getElementById('live-mode-btn').classList.add('active');
            document.getElementById('historic-mode-btn').classList.remove('active');

            // Update title with today's date
            const todayText = formatDateForTitle(new Date());
            document.getElementById('activity-title').textContent = `📍 Live Activity - ${{todayText}}`;
            document.getElementById('map-title').textContent = '🗺️ Live Map';

            // Hide historic controls
            document.getElementById('time-range-selector').classList.add('hidden');
            document.getElementById('resolution-selector').classList.add('hidden');
            document.getElementById('device-selector').classList.add('hidden');

            // Clear activity section for live updates
            clearActivitySection('Loading last hour of activity...');
            eventCount = 0;
            lastTimestamp = null;  // Reset to allow fresh load

            // Clear selection and trails
            selectedDevice = '';
            document.getElementById('device-selector').value = '';
            Object.values(deviceTrails).forEach(trail => {{
                if (trail.polyline) trail.polyline.remove();
                if (trail.markers) trail.markers.forEach(m => m.remove());
            }});
            deviceTrails = {{}};

            // Clear device markers for fresh load
            Object.values(deviceMarkers).forEach(marker => marker.remove());
            deviceMarkers = {{}};

            // Load last hour of activity data
            loadLiveActivityHistory();

            // Save UI state
            saveUIState();
        }}

        function switchToHistoricMode() {{
            isLiveMode = false;
            // Only fit bounds if not restoring state (user has saved map position)
            if (!isRestoringState) {{
                needsFitBounds = true;
            }}

            // Update button states
            document.getElementById('live-mode-btn').classList.remove('active');
            document.getElementById('historic-mode-btn').classList.add('active');

            // Update title with date range
            const dateRangeText = getDateRangeText(timeRangeHours);
            document.getElementById('map-title').textContent = '🗺️ Historic Map';
            document.getElementById('activity-title').textContent = `📅 Historic Trail - ${{dateRangeText}}`;

            // Show historic controls
            document.getElementById('time-range-selector').classList.remove('hidden');
            document.getElementById('resolution-selector').classList.remove('hidden');
            document.getElementById('device-selector').classList.remove('hidden');

            // Clear markers (will be restored by fetchAndDisplayTrail)
            Object.values(deviceMarkers).forEach(marker => marker.remove());
            deviceMarkers = {{}};

            // Fetch and display trail (works for both All Devices and specific device)
            fetchAndDisplayTrail();

            // Save UI state
            saveUIState();
        }}

        document.getElementById('live-mode-btn').addEventListener('click', switchToLiveMode);
        document.getElementById('historic-mode-btn').addEventListener('click', switchToHistoricMode);

        // Server health check
        function checkServerHealth() {{
            fetch('/health/')
                .then(response => {{
                    if (response.ok) {{
                        isServerConnected = true;
                        updateServerStatus(true);
                    }} else {{
                        isServerConnected = false;
                        updateServerStatus(false);
                    }}
                }})
                .catch(() => {{
                    isServerConnected = false;
                    updateServerStatus(false);
                }});
        }}

        function updateServerStatus(connected) {{
            const statusDot = document.getElementById('status-dot');
            const statusText = document.getElementById('status-text');
            if (connected) {{
                statusDot.className = 'status-dot connected';
                statusText.textContent = 'Connected';
            }} else {{
                statusDot.className = 'status-dot disconnected';
                statusText.textContent = 'Disconnected';
            }}
        }}

        // Check health immediately and then every 5 seconds
        checkServerHealth();
        setInterval(checkServerHealth, 5000);

        // Track last known IP to detect changes
        let lastKnownIP = '{local_ip}';

        // Check for network info changes (IP address, hostname)
        async function checkNetworkInfo() {{
            try {{
                const response = await fetch('/network-info/');
                if (response.ok) {{
                    const data = await response.json();
                    const newIP = data.local_ip;

                    // Update display elements
                    document.getElementById('network-hostname').textContent = data.hostname;
                    document.getElementById('network-ip').textContent = newIP;
                    document.getElementById('network-url').textContent = `http://${{newIP}}:${{data.port}}/`;

                    // If IP changed, show a notification
                    if (newIP !== lastKnownIP && lastKnownIP !== 'Unable to detect') {{
                        console.log(`Network IP changed: ${{lastKnownIP}} -> ${{newIP}}`);
                        lastKnownIP = newIP;
                    }}
                }}
            }} catch (e) {{
                // Silently ignore network errors
            }}
        }}

        // Check network info every 30 seconds
        setInterval(checkNetworkInfo, 30000);

        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {{
            if (!localStorage.getItem('theme')) {{
                setTheme(e.matches ? 'dark' : 'light');
            }}
        }});

        // Theme toggle click handler
        document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

        // Reset button handler
        function resetEvents() {{
            const container = document.getElementById('log-container');
            container.innerHTML = '<p id="loading">Waiting for location updates...</p>';
            eventCount = 0;
            document.getElementById('log-count').textContent = '0 events';
        }}

        document.getElementById('reset-button').addEventListener('click', resetEvents);

        function formatTime(timestamp, includeDate = false) {{
            const date = new Date(timestamp * 1000);
            const today = new Date();
            const isToday = date.toDateString() === today.toDateString();

            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            const seconds = String(date.getSeconds()).padStart(2, '0');
            const timeStr = `${{hours}}:${{minutes}}:${{seconds}}`;

            // Include date if requested or if not today
            if (includeDate || !isToday) {{
                const month = date.toLocaleDateString('en-US', {{ month: 'short' }});
                const day = date.getDate();
                return `${{month}} ${{day}} ${{timeStr}}`;
            }}
            return timeStr;
        }}

        // Clear activity section and show a message
        function clearActivitySection(message) {{
            const container = document.getElementById('log-container');
            container.innerHTML = `<p id="loading">${{message}}</p>`;
            document.getElementById('log-count').textContent = '0 waypoints';
        }}

        // Display historic waypoints in activity section
        // Shows collapsed waypoints (same location = single entry) with counts
        function displayHistoricWaypoints(locations) {{
            const container = document.getElementById('log-container');
            container.innerHTML = ''; // Clear existing content

            if (locations.length === 0) {{
                container.innerHTML = '<p id="loading">No waypoints found for selected time range</p>';
                document.getElementById('log-count').textContent = '0 waypoints';
                return;
            }}

            // Collapse consecutive waypoints at same location
            // API returns newest first, so we reverse to get chronological order for collapsing
            const chronological = [...locations].reverse();
            const collapsedLocations = collapseLocations(chronological);
            // Reverse back to show newest first in the list
            const displayLocations = [...collapsedLocations].reverse();

            // Display collapsed waypoints (newest first at top)
            displayLocations.forEach((loc, index) => {{
                const waypointNumber = collapsedLocations.length - index;  // Oldest = #1, newest = #N
                const entry = document.createElement('div');
                entry.className = 'log-entry';

                const time = formatTime(loc.timestamp_unix, true);  // Always show date in historic view
                const lat = parseFloat(loc.latitude).toFixed(6);
                const lon = parseFloat(loc.longitude).toFixed(6);
                const acc = loc.accuracy || 'N/A';
                const alt = loc.altitude || 0;
                const vel = loc.velocity || 0;
                const batt = loc.battery_level || 'N/A';
                const collapsedCount = loc._collapsedCount || 1;

                // Show count badge at end of line if multiple waypoints were collapsed
                const countBadge = collapsedCount > 1 ? 
                    `<span style="background:#6c757d;color:white;padding:1px 5px;border-radius:10px;font-size:10px;margin-left:8px;">×${{collapsedCount}}</span>` : '';

                entry.innerHTML = `<span class="log-time"><b>#${{waypointNumber}}</b> ${{time}}</span> | <span class="log-coords">${{lat}}, ${{lon}}</span> | <span class="log-meta">acc:${{acc}}m alt:${{alt}}m vel:${{vel}}km/h batt:${{batt}}%</span>${{countBadge}}`;

                container.appendChild(entry);
            }});

            // Show both collapsed count and original count
            const collapsedCount = collapsedLocations.length;
            const originalCount = locations.length;
            const countText = collapsedCount < originalCount ?
                `${{collapsedCount}} location${{collapsedCount !== 1 ? 's' : ''}} (${{originalCount}} waypoints)` :
                `${{originalCount}} waypoint${{originalCount !== 1 ? 's' : ''}}`;
            document.getElementById('log-count').textContent = countText;
        }}

        function addLogEntry(location, skipScroll = false) {{
            const container = document.getElementById('log-container');
            const loading = document.getElementById('loading');
            if (loading) loading.remove();

            console.log('Adding log entry:', location);

            const entry = document.createElement('div');
            entry.className = 'log-entry';

            const time = formatTime(location.timestamp_unix, true);  // Show date for context
            const device = location.device_name || 'Unknown';
            const deviceId = location.device_id_display || 'N/A';
            const trackerId = location.tid_display || '';
            const lat = parseFloat(location.latitude).toFixed(6);
            const lon = parseFloat(location.longitude).toFixed(6);
            const acc = location.accuracy || 'N/A';
            const alt = location.altitude || 0;
            const vel = location.velocity || 0;
            const batt = location.battery_level || 'N/A';
            const conn = location.connection_type === 'w' ? 'WiFi' : location.connection_type === 'm' ? 'Mobile' : 'N/A';
            const ip = location.ip_address || 'N/A';

            // Show device with tracker ID if available
            let deviceDisplay = device;
            if (trackerId) {{
                deviceDisplay = `${{device}} (${{trackerId}})`;
            }} else if (device !== deviceId) {{
                deviceDisplay = `${{device}} (${{deviceId}})`;
            }}

            entry.innerHTML = `<span class="log-time">${{time}}</span> | <span class="log-device">${{deviceDisplay}}</span> | <span class="log-ip">${{ip}}</span> | <span class="log-coords">${{lat}}, ${{lon}}</span> | <span class="log-meta">acc:${{acc}}m alt:${{alt}}m vel:${{vel}}km/h batt:${{batt}}% ${{conn}}</span>`;

            container.insertBefore(entry, container.firstChild);

            // Auto-scroll so newest entry is roughly in the middle of the view
            if (!skipScroll) {{
                requestAnimationFrame(() => {{
                    entry.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                }});
            }}

            // Keep only last 100 entries (1 hour worth at typical update rates)
            while (container.children.length > 100) {{
                container.removeChild(container.lastChild);
            }}

            eventCount++;
            document.getElementById('log-count').textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '') + ' (last hour)';

            // Update map marker
            if (map) {{
                updateDeviceMarker(location);
            }}
        }}

        // Load last hour of live activity data
        async function loadLiveActivityHistory() {{
            const now = Date.now() / 1000;
            const oneHourAgo = now - 3600;  // 1 hour in seconds

            try {{
                const response = await fetch(`/api/locations/?start_time=${{Math.floor(oneHourAgo)}}&ordering=-timestamp&limit=100`);
                if (!response.ok) return;

                const data = await response.json();
                const locations = data.results || [];

                if (locations.length === 0) {{
                    return;
                }}

                const container = document.getElementById('log-container');
                const loading = document.getElementById('loading');
                if (loading) loading.remove();

                // Display locations (already newest first from API)
                locations.forEach((loc, index) => {{
                    const entry = document.createElement('div');
                    entry.className = 'log-entry';

                    const time = formatTime(loc.timestamp_unix, true);  // Show date for context
                    const device = loc.device_name || 'Unknown';
                    const deviceId = loc.device_id_display || 'N/A';
                    const trackerId = loc.tid_display || '';
                    const lat = parseFloat(loc.latitude).toFixed(6);
                    const lon = parseFloat(loc.longitude).toFixed(6);
                    const acc = loc.accuracy || 'N/A';
                    const alt = loc.altitude || 0;
                    const vel = loc.velocity || 0;
                    const batt = loc.battery_level || 'N/A';
                    const conn = loc.connection_type === 'w' ? 'WiFi' : loc.connection_type === 'm' ? 'Mobile' : 'N/A';
                    const ip = loc.ip_address || 'N/A';

                    let deviceDisplay = device;
                    if (trackerId) {{
                        deviceDisplay = `${{device}} (${{trackerId}})`;
                    }} else if (device !== deviceId) {{
                        deviceDisplay = `${{device}} (${{deviceId}})`;
                    }}

                    entry.innerHTML = `<span class="log-time">${{time}}</span> | <span class="log-device">${{deviceDisplay}}</span> | <span class="log-ip">${{ip}}</span> | <span class="log-coords">${{lat}}, ${{lon}}</span> | <span class="log-meta">acc:${{acc}}m alt:${{alt}}m vel:${{vel}}km/h batt:${{batt}}% ${{conn}}</span>`;

                    container.appendChild(entry);

                    // Update device marker (only for latest position of each device)
                    if (index === 0 || !deviceMarkers[device]) {{
                        updateDeviceMarker(loc);
                    }}
                }});

                eventCount = locations.length;
                document.getElementById('log-count').textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '') + ' (last hour)';

                // Track the newest timestamp for incremental updates
                if (locations.length > 0) {{
                    lastTimestamp = locations[0].timestamp_unix;
                }}
            }} catch (error) {{
                console.error('Error loading live activity history:', error);
            }}
        }}

        // Refresh live activity with updates since last known timestamp (for reconnect)
        async function refreshLiveActivitySinceLastUpdate() {{
            if (!lastTimestamp) {{
                // No previous data, do a full load
                loadLiveActivityHistory();
                return;
            }}

            try {{
                // Fetch only locations newer than our last known timestamp
                const response = await fetch(`/api/locations/?start_time=${{lastTimestamp + 1}}&ordering=timestamp&limit=100`);
                if (!response.ok) return;

                const data = await response.json();
                const locations = data.results || [];

                if (locations.length === 0) {{
                    console.log('No new locations since last update');
                    return;
                }}

                console.log(`Found ${{locations.length}} new location(s) since last update`);

                // Add each new location (already in chronological order)
                locations.forEach(loc => {{
                    addLogEntry(loc);
                }});
            }} catch (error) {{
                console.error('Error refreshing live activity:', error);
            }}
        }}

        // WebSocket connection for real-time updates
        let ws = null;
        let wsReconnectAttempts = 0;
        const maxReconnectAttempts = 5;
        const reconnectDelay = 3000;
        let serverStartupTimestamp = null;  // Track server version

        function connectWebSocket() {{
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${{protocol}}//${{window.location.host}}/ws/locations/`;

            console.log('Connecting to WebSocket:', wsUrl);

            try {{
                ws = new WebSocket(wsUrl);

                ws.onopen = () => {{
                    console.log('WebSocket connected');
                    wsReconnectAttempts = 0;
                }};

                ws.onmessage = (event) => {{
                    try {{
                        const message = JSON.parse(event.data);
                        console.log('WebSocket message received:', message);

                        // Handle welcome message with server version
                        if (message.type === 'welcome' && message.server_startup) {{
                            if (serverStartupTimestamp === null) {{
                                // First connection, store the version
                                serverStartupTimestamp = message.server_startup;
                                console.log('Server startup timestamp:', serverStartupTimestamp);
                            }} else if (serverStartupTimestamp !== message.server_startup) {{
                                // Server has restarted, refresh the page
                                console.log('Server restarted (was:', serverStartupTimestamp, 'now:', message.server_startup, '), refreshing page...');
                                window.location.reload();
                                return;
                            }} else {{
                                // Same server, but we reconnected - refresh live data to catch up on missed updates
                                console.log('WebSocket reconnected, refreshing live activity...');
                                if (isLiveMode) {{
                                    refreshLiveActivitySinceLastUpdate();
                                }}
                            }}
                        }}

                        // Only process messages in live mode
                        if (isLiveMode && message.type === 'location' && message.data) {{
                            addLogEntry(message.data);
                        }}
                    }} catch (error) {{
                        console.error('Error parsing WebSocket message:', error);
                    }}
                }};

                ws.onerror = (error) => {{
                    console.error('WebSocket error:', error);
                }};

                ws.onclose = () => {{
                    console.log('WebSocket disconnected');
                    ws = null;

                    // Try to reconnect with exponential backoff
                    if (wsReconnectAttempts < maxReconnectAttempts) {{
                        wsReconnectAttempts++;
                        const delay = reconnectDelay * Math.pow(2, wsReconnectAttempts - 1);
                        console.log(`Reconnecting in ${{delay}}ms (attempt ${{wsReconnectAttempts}})...`);
                        setTimeout(connectWebSocket, delay);
                    }} else {{
                        console.warn('Max reconnection attempts reached, falling back to polling');
                        startPolling();
                    }}
                }};
            }} catch (error) {{
                console.error('Failed to create WebSocket:', error);
                startPolling();
            }}
        }}

        // Fallback polling for when WebSocket is not available
        let pollingInterval = null;

        async function fetchLocations() {{
            try {{
                let url = '/api/locations/?ordering=-timestamp&limit=20';

                const response = await fetch(url);
                const data = await response.json();

                console.log('Fetched data:', data);

                if (data.results && data.results.length > 0) {{
                    console.log('Processing', data.results.length, 'locations');
                    // Process all results (only in live mode)
                    if (isLiveMode) {{
                        // On initial load, show recent history in chronological order
                        // Results come in newest-first, so reverse for initial display
                        const isInitialLoad = lastTimestamp === null;
                        const locsToProcess = isInitialLoad ? [...data.results].reverse() : data.results;

                        let newestEntry = null;
                        for (const loc of locsToProcess) {{
                            // Only add if we haven't seen this timestamp yet
                            if (!lastTimestamp || loc.timestamp_unix > lastTimestamp) {{
                                // Skip scrolling during batch load, we'll scroll once at the end
                                addLogEntry(loc, isInitialLoad);
                                newestEntry = loc;
                            }}
                        }}

                        // After initial batch load, scroll to show the newest entry
                        if (isInitialLoad && newestEntry) {{
                            // Use setTimeout to ensure DOM is fully rendered before scrolling
                            setTimeout(() => {{
                                const container = document.getElementById('log-container');
                                if (container.firstChild) {{
                                    container.firstChild.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                                }}
                            }}, 100);
                        }}

                        // Update last timestamp to the newest one
                        if (data.results.length > 0) {{
                            lastTimestamp = data.results[0].timestamp_unix;
                        }}
                    }}
                }}
            }} catch (error) {{
                console.error('Error fetching locations:', error);
            }}
        }}

        function startPolling() {{
            if (!pollingInterval && isLiveMode) {{
                console.log('Starting polling fallback');
                fetchLocations(); // Initial fetch
                pollingInterval = setInterval(fetchLocations, 2000);
            }}
        }}

        // Restore UI state from localStorage
        restoreUIState();

        // Initial fetch for historical data (always needed to populate device list)
        fetchLocations();

        // Start WebSocket connection for real-time updates
        connectWebSocket();
    </script>
</body>
</html>
""".format(hostname=hostname, local_ip=local_ip)
    response = HttpResponse(content=html, content_type='text/html; charset=utf-8')  # type: ignore[arg-type]
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


urlpatterns: list[URLPattern | URLResolver] = [
    path('', home, name='home'),
    path('health/', health, name='health'),
    path('network-info/', network_info, name='network_info'),
    path('admin/', admin.site.urls),
    path('api/', include('tracker.urls')),
]
