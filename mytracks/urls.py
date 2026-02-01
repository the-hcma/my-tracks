"""
URL configuration for mytracks project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse, JsonResponse
from typing import List
from django.urls.resolvers import URLPattern, URLResolver
import socket


def health(request):
    """Health check endpoint."""
    return JsonResponse({'status': 'ok'})


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
    <title>My Tracks - OwnTracks Backend</title>
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
        .status {{ color: var(--status-color); font-weight: bold; }}
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
        .theme-toggle {{
            position: fixed;
            top: 20px;
            left: 20px;
            background: var(--endpoint-bg);
            border: 2px solid var(--border-color);
            border-radius: 50px;
            padding: 8px 16px;
            cursor: pointer;
            font-size: 20px;
            transition: all 0.3s ease;
            z-index: 1000;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }}
        .theme-toggle:hover {{
            transform: scale(1.1);
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
        }}
        .device-selector {{
            background: var(--endpoint-bg);
            color: var(--text-main);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 12px;
            cursor: pointer;
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
        }}
    </style>
</head>
<body>
    <button class="theme-toggle" id="theme-toggle" aria-label="Toggle theme">🌙</button>
    <div class="container">
        <div class="left-column">
            <h1>🗺️ My Tracks - OwnTracks Backend</h1>
            <p class="status" id="server-status">🔄 Checking server status...</p>
            <p>A backend server for the OwnTracks Android/iOS app.</p>
            
            <h2>🌐 Network Access</h2>
    <div class="endpoint">
        <p><strong>Hostname:</strong> <code>{hostname}</code></p>
        <p><strong>Local IP:</strong> <code>{local_ip}</code></p>
        <p><strong>Port:</strong> <code>8080</code></p>
        <p style="margin-top: 10px;">Access from other devices on your LAN:</p>
        <p><code>http://{local_ip}:8080/</code></p>
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
        <li><a href="https://github.com/yourusername/my-tracks">GitHub Repository</a></li>
        <li>See <code>API.md</code> for complete API reference</li>
        <li>See <code>README.md</code> for setup instructions</li>
    </ul>
        </div>
        
        <div class="right-column">
            <div class="map-section">
                <div class="map-header">
                    <h2>🗺️ Live Map</h2>
                    <select class="device-selector" id="device-selector">
                        <option value="">All Devices</option>
                    </select>
                </div>
                <div id="map"></div>
            </div>
            <div class="activity-section">
                <div class="log-header">
                    <h2>📍 Live Activity</h2>
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
        let devices = new Set();
        let selectedDevice = '';
        
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
        
        // Initialize theme
        setTheme(getPreferredTheme());
        
        // Initialize map
        function initMap() {{
            map = L.map('map').setView([37.7749, -122.4194], 17);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 19
            }}).addTo(map);
            
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
            }}
            
            // Only show marker if no device selected or if it matches selected device
            if (selectedDevice && selectedDevice !== deviceName) {{
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
            
            // Center map on the marker if it's the selected device or no selection
            if (!selectedDevice || selectedDevice === deviceName) {{
                map.setView(latLng, map.getZoom());
            }}
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
        
        // Device selector change handler
        document.getElementById('device-selector').addEventListener('change', (e) => {{
            selectedDevice = e.target.value;
            
            // Clear all markers
            Object.values(deviceMarkers).forEach(marker => marker.remove());
            deviceMarkers = {{}};
            
            // Re-fetch and display locations for selected device
            fetchLocations();
        }});
        
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
            const statusEl = document.getElementById('server-status');
            if (connected) {{
                statusEl.innerHTML = '✅ Server is running!';
                statusEl.style.color = 'var(--status-color)';
            }} else {{
                statusEl.innerHTML = '❌ Server disconnected!';
                statusEl.style.color = '#dc3545';
            }}
        }}
        
        // Check health immediately and then every 5 seconds
        checkServerHealth();
        setInterval(checkServerHealth, 5000);
        
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
        
        function formatTime(timestamp) {{
            const date = new Date(timestamp * 1000);
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            const seconds = String(date.getSeconds()).padStart(2, '0');
            const ms = String(date.getMilliseconds()).padStart(3, '0');
            return `${{hours}}:${{minutes}}:${{seconds}}.${{ms}}`;
        }}
        
        function addLogEntry(location) {{
            const container = document.getElementById('log-container');
            const loading = document.getElementById('loading');
            if (loading) loading.remove();
            
            console.log('Adding log entry:', location);
            
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            
            const time = formatTime(location.timestamp_unix);
            const device = location.device_name || 'Unknown';
            const lat = parseFloat(location.latitude).toFixed(6);
            const lon = parseFloat(location.longitude).toFixed(6);
            const acc = location.accuracy || 'N/A';
            const alt = location.altitude || 0;
            const vel = location.velocity || 0;
            const batt = location.battery_level || 'N/A';
            const conn = location.connection_type === 'w' ? 'WiFi' : location.connection_type === 'm' ? 'Mobile' : 'N/A';
            const ip = location.ip_address || 'N/A';
            
            entry.innerHTML = `<span class="log-time">${{time}}</span> | <span class="log-device">${{device}}</span> | <span class="log-ip">${{ip}}</span> | <span class="log-coords">${{lat}}, ${{lon}}</span> | <span class="log-meta">acc:${{acc}}m alt:${{alt}}m vel:${{vel}}km/h batt:${{batt}}% ${{conn}}</span>`;
            
            container.insertBefore(entry, container.firstChild);
            
            // Auto-scroll to top (where new entries are added) after DOM update
            requestAnimationFrame(() => {{
                entry.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }});
            
            // Keep only last 50 entries
            while (container.children.length > 50) {{
                container.removeChild(container.lastChild);
            }}
            
            eventCount++;
            document.getElementById('log-count').textContent = eventCount + ' event' + (eventCount !== 1 ? 's' : '');
            
            // Update map marker
            if (map) {{
                updateDeviceMarker(location);
            }}
        }}
        
        // WebSocket connection for real-time updates
        let ws = null;
        let wsReconnectAttempts = 0;
        const maxReconnectAttempts = 5;
        const reconnectDelay = 3000;
        
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
                        
                        if (message.type === 'location' && message.data) {{
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
                    // Process all results, newest first
                    for (let i = 0; i < data.results.length; i++) {{
                        const loc = data.results[i];
                        // Only add if we haven't seen this timestamp yet
                        if (!lastTimestamp || loc.timestamp_unix > lastTimestamp) {{
                            addLogEntry(loc);
                        }}
                    }}
                    // Update last timestamp to the newest one
                    if (data.results.length > 0) {{
                        lastTimestamp = data.results[0].timestamp_unix;
                    }}
                }}
            }} catch (error) {{
                console.error('Error fetching locations:', error);
            }}
        }}
        
        function startPolling() {{
            if (!pollingInterval) {{
                console.log('Starting polling fallback');
                fetchLocations(); // Initial fetch
                pollingInterval = setInterval(fetchLocations, 2000);
            }}
        }}
        
        // Initial fetch for historical data
        fetchLocations();
        
        // Start WebSocket connection for real-time updates
        connectWebSocket();
    </script>
</body>
</html>
""".format(hostname=hostname, local_ip=local_ip)
    return HttpResponse(html)


urlpatterns: List[URLPattern | URLResolver] = [
    path('', home, name='home'),
    path('health/', health, name='health'),
    path('admin/', admin.site.urls),
    path('api/', include('tracker.urls')),
]
