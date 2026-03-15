# My Tracks — Implementation Plan

**Last Updated**: March 11, 2026

## Overview

Evolution plan for My Tracks, a self-hosted location tracking backend for the OwnTracks Android/iOS app.

**Core Goals**:
- Persist and visualize geolocation data
- Battery-efficient real-time updates via embedded MQTT broker
- Bidirectional device communication (send commands to devices)
- User authentication and TLS certificate management

## Completed Phases

### Phase 1: Basic MQTT Broker ✅
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

### Phase 5: Integration ✅

1. **Server integration** ✅ (PR #104)
   - `--mqtt-port` flag (default: 1883, 0 = OS allocates, -1 = disabled)
   - `--http-port` flag (renamed from `--port`)
   - Runtime config via JSON file (`config/.runtime-config.json`)
   - OS-allocated port discovery via `actual_mqtt_port` property
   - ASGI lifespan handler starts/stops broker

2. **Admin UI MQTT endpoint display** ✅ (PR #105)
   - Show HTTP/MQTT status in web UI with consistent format
   - Display MQTT host and port for OwnTracks app configuration
   - Updated OwnTracks setup instructions for both MQTT and HTTP modes

3. **Wire message handlers** ✅
   - Connect `OwnTracksMessageHandler` to broker via amqtt plugin
   - Process incoming location messages → save to database
   - Broadcast to WebSocket clients via channel layer
   - Created `OwnTracksPlugin` with `on_broker_message_received` hook

4. **Graceful process termination** ✅
   - `graceful_kill()` function: SIGTERM first, configurable wait, SIGKILL fallback
   - Uses signal names (TERM, KILL) instead of numbers
   - Applied to server PID, orphaned HTTP, and orphaned MQTT processes

5. **Traffic generator MQTT support** ✅ (PR #126)
   - Added `--mqtt` flag to `generate-tail` traffic generator
   - `MQTTTransport` class wrapping `amqtt.client.MQTTClient`
   - Auto-detects MQTT port from server's runtime config
   - `--mqtt-host`, `--mqtt-port`, `--mqtt-user`, `--mqtt-password` options
   - 38 new tests in `test_generate_tail.py`

6. **LWT handling** ✅ (PR #128)
   - Added `is_online` field to Device model
   - `save_lwt_to_db()` marks device offline, stores LWT payload
   - `save_location_to_db()` marks device online when location received
   - Real-time WebSocket broadcast of device status changes
   - Admin UI shows online/offline status with filtering

7. **Historic view date & time picker** ✅ (PR #130)
   - Replaced time range `<select>` with date picker + dual-handle time slider
   - Date picker (`<input type="date">`) to select any past day (default: today)
   - noUiSlider dual-handle range (00:00–23:59) to select time window within day
   - Live time labels update as handles are dragged, +59s end offset for full minute
   - Added `end_time` Unix timestamp parameter to API
   - Shared utility functions in `utils.ts` with 12 new TypeScript tests

### Phase 6: Account Management ✅ (Step 1)

1. **User Authentication & Account Management API** ✅ (PR #193)
   - Enforce authentication on all API endpoints (reject unauthenticated requests)
   - Web UI login/logout:
     - Login page using Django's `LoginView` (session-based auth)
     - Logout via Django's `LogoutView` (POST-based, CSRF-protected)
     - All web UI views require login (redirect unauthenticated users to login page)
     - Username display and logout button in header ✅ (PR #195)
   - REST endpoints for account self-service:
     - `GET /api/account/` — retrieve current user profile
     - `PATCH /api/account/` — update profile fields
     - `POST /api/account/change-password/` — change password
   - Admin endpoints for user lifecycle:
     - `POST /api/admin/users/` — create user
     - `DELETE /api/admin/users/{id}/` — deactivate user
     - `GET /api/admin/users/` — list users
   - `UserProfile` model (extends Django User) for per-user settings
   - Auth strategy: session auth for web UI, API key/token auth for REST clients
   - Skip MQTT broker during management commands, handle port-in-use gracefully ✅ (PR #194)
   - Tests for authenticated/unauthenticated access, login/logout flows, permissions, CRUD

2. **User Profile Page, Admin Badge & Session Management** ✅ (PR #247)
   - Admin vs regular user differentiation:
     - Admin badge in header for staff users (pink "admin" pill)
     - Role badge on profile page (Administrator / User)
   - Web UI profile page (`/profile/`):
     - Display and edit user's full name (first name, last name)
     - Display and edit email address
     - Change password form with Django password validators
     - Session preserved after password change (`update_session_auth_hash`)
     - Username in header links to profile page
   - Session management:
     - 7-day sliding window expiry (`SESSION_COOKIE_AGE = 604800`)
     - `SESSION_SAVE_EVERY_REQUEST = True` to reset expiry on each request
   - 18 new tests for admin badge, profile CRUD, password flows, session config

3. **Admin Dashboard & Navigation** ✅ (PR #251, #253, #254)
   - Admin-only route (`/admin-panel/`), guarded by `@login_required` + `@user_passes_test(is_staff)`
   - User list: table of all users showing username, email, role, status, last login
   - Create user form: username, email, first name, last name, password, admin toggle
   - Deactivate/reactivate users (soft delete via `is_active` flag)
   - Toggle admin/regular role (with self-toggle protection)
   - API endpoints: `POST /api/admin/users/{id}/reactivate/`, `POST /api/admin/users/{id}/toggle-admin/`
   - Hamburger navigation menu with Profile, Admin Panel (admin-only), About & Setup, Logout
   - Documentation sidebar moved to dedicated `/about/` page
   - 20+ new tests for admin access, user CRUD, hamburger menu, about page

4. **PKI — CA Certificate Management** ✅ (PR #261, #262)
   - `CertificateAuthority` model with encrypted private key storage (Fernet + SECRET_KEY)
   - CA generation: self-signed X.509, configurable CN and validity (1–36500 days), 4096-bit RSA
   - Admin REST API: list, create, deactivate, download, get active CA
   - Admin panel UI: active CA details (fingerprint, validity, download), generate form, CA history table
   - Expunge action for permanently deleting inactive CAs
   - Confirmation dialog shows active CA name and expiry before replacement
   - 31+ tests for crypto utilities, model, API, permissions, admin panel

5. **Enhanced User Management** ✅ (PR #268)
   - Permanent user deletion (`DELETE /api/admin/users/{id}/hard-delete/`)
   - Admin password reset (`POST /api/admin/users/{id}/set-password/`) with modal UI
   - Self-deletion and self-password-reset blocked
   - 12 new API + UI tests

6. **Password Visibility Toggles** ✅ (PR #265, #267, #273)
   - Eye icon toggle on login page, admin panel create-user form, and profile change-password form
   - Inline SVG icons (eye/eye-off), `aria-label` for accessibility, per-field independent toggles

7. **PKI — Configurable Key Size & Server Certificate** ✅ (PR #276, #278, #279)
   - Configurable RSA key size (2048, 3072, 4096) for CA, server, and client certs
   - `ServerCertificate` model with encrypted private key, SANs, fingerprint
   - `generate_server_certificate()` with auto-detected local IPs + hostname for SANs
   - Admin REST API: generate, list, download, deactivate, expunge server certs
   - Admin panel UI: "Server Certificate (MQTT TLS)" section with generate form and history

8. **PKI — Client Certificate Management** ✅ (PR #289, #290, #291, #292, #293)
   - `ClientCertificate` model (FK → User, FK → CA) with encrypted private key
   - Certificate generation, revocation, and CRL generation (`generate_crl()`)
   - 5-year default validity with configurable presets (1–5 years)
   - Subject metadata display (CN, O, OU) in admin panel and profile page
   - Admin REST API: issue, list, revoke, expunge client certs; download CRL
   - Admin panel UI: issue cert for user, view all certs, revoke/expunge actions
   - Profile page: certificate status, download cert + key bundle, CA cert download
   - TLS handshake validation tests (server presents cert, client authenticates)

9. **PKI — CRL Enforcement Tests** ✅ (PR #295)
   - `TestTLSHandshake` integration tests simulating real TLS with `ssl` module
   - Revoked client cert rejected (server raises `SSLError: certificate revoked`)
   - Non-revoked client passes when CRL checking is enabled
   - Handles TLS 1.3 deferred client verification (test verifies data exchange fails)

10. **Admin Panel Restructure** ✅ (PR #307, #308)
    - Tabbed interface: "Users" tab (create user + users table) and "PKI" tab (all cert operations)
    - Users table shows client cert status with hover tooltip (CN, key size, expiry, serial)
    - One-click cert issuance from users table for users without a cert
    - CRL section: revoked certs table, revocation count, CRL download button
    - Prominent section titles across all pages (admin panel, profile, about)
    - Auto-build frontend assets (`npm run build`) on server startup
    - `WHITENOISE_USE_FINDERS = True` in DEBUG mode for direct static file serving

11. **Server Script Fix** ✅ (PR #309)
    - Declining restart prompt no longer triggers cleanup of running processes

12. **Test Coverage & Reliability** ✅ (PR #317)
    - Fixed Python 3.14 test failures (`dict.get` read-only, `None` payload handling)
    - Added tests for `CommandApiKeyAuthentication`, MQTT broker error paths, ASGI lifecycle
    - Coverage improved from 85.5% to 98.27% (818 Python tests)

13. **CI/CD Improvements** ✅ (PR #319, #323)
    - Parallel test execution with accurate coverage (`coverage-enable-subprocess` + pytest-xdist)
    - Split single backend CI job into 3 parallel jobs: Backend Lint (16s), Backend Tests (1m37s), Shell Script Tests (1m25s)
    - CI wall-clock time reduced from ~3m30s to ~1m37s (55% faster)

14. **Fatal Port Conflicts** ✅ (PR #320)
    - MQTT broker bind failure now calls `os._exit(1)` instead of logging a warning
    - Reusable `check_port_conflict` shell function covers HTTP and MQTT ports
    - Prevents half-running server state (HTTP up, MQTT down)

### Phase 6, Step 4: MQTT Broker TLS Integration ✅

Full TLS integration: server certificate presentation + client certificate authentication + CRL enforcement.

- **Server-side TLS** ✅ (PR #325, #326)
  - MQTT broker reads active server cert from database at startup
  - `--mqtt-tls-port` flag (default: 8883, -1 = disabled)
  - Broker presents server certificate for TLS connections
  - Write cert/key to temporary files for amqtt TLS configuration
  - Display TLS status and port in web UI (About & Setup page)
  - OwnTracks setup instructions updated for TLS mode

- **Client certificate authentication** ✅
  - MQTT broker requires client certificate for TLS connections (`CERT_REQUIRED`)
  - Validate client cert is signed by active CA
  - TLS 1.2 cap ensures `CERT_REQUIRED` is enforced during initial handshake

- **Certificate validation & CRL enforcement** ✅
  - Untrusted, expired, and revoked client certs rejected at TLS handshake
  - CRL loaded into the broker's TLS context via `VERIFY_CRL_CHECK_LEAF`
  - Empty CRL (no revocations) does not block valid clients

- **End-to-end TLS tests** ✅ (PR #327)
  - Valid client cert → MQTT connection accepted + publish/receive works
  - Untrusted cert (not signed by CA) → connection refused
  - Expired client cert → connection refused
  - Revoked client cert (on CRL) → connection refused
  - No client cert → connection refused
  - Revoked cert accepted when CRL checking is disabled

15. **PKCS#12 Client Certificate Download** ✅ (PR #331)
    - Replaced PEM download with password-protected `.p12` bundle (cert + private key + CA)
    - Profile page: POST form with password field and eye icon reveal toggle
    - Admin panel: JavaScript prompt + fetch for `.p12` download
    - Required for importing client certs onto mobile devices (Android/iOS)

16. **Mobile-Friendly Web UI** ✅ (PR #332)
    - Added `<meta name="viewport">` tag (root cause of tiny fonts on mobile)
    - Responsive CSS with `@media` queries for all pages (home, profile, admin, about)
    - Tables wrapped in scroll containers, forms stack vertically on small screens

17. **TLS Client Identification & Handshake Logging** ✅ (PR #333)
    - MQTT connections logged with TLS status: `TLS (CN=username [AA:BB:CC:DD])` or `(non-TLS)`
    - Extract peer certificate CN and SHA-256 fingerprint from SSL transport
    - Location and transition messages annotated with TLS identity in logs
    - HTTP location endpoint explicitly marked `(non-TLS)` in logs
    - Failed TLS handshakes now logged at WARNING level (previously silently dropped by asyncio)
    - Suppressed noisy `transitions.core` INFO logs and `sys_interval` deprecation warning

18. **Interactive SAN Tag Editor** ✅ (PR #334)
    - Replaced comma-separated text input with tag-style add/remove editor
    - Auto-detects local IPs, hostname, AND request hostname (e.g., `mytracks.hcma.info`)
    - Users can add/remove individual SAN entries before generating server certificate

19. **Single Reveal Button for Change Password** ✅ (PR #336)
    - Consolidated multiple password reveal toggles into a single button on profile change-password form

20. **SAN Hostname Auto-Include & Frontend Warning** ✅ (PR #337)
    - Backend auto-includes request hostname in server certificate SANs during generation
    - Frontend warning if the access hostname is removed from the SAN list
    - Prevents `SSLPeerUnverifiedException` from clients connecting via a hostname not in SANs

21. **TLS Disconnect Diagnostic Logging** ✅ (PR #338)
    - Log WARNING when TLS client disconnects immediately after handshake (before MQTT data)
    - Includes client IP and server certificate SANs for diagnosing client-side cert rejections
    - Surfaces issues like hostname mismatch or untrusted CA that are invisible at server level

22. **Widen Desktop Layout** ✅ (PR #339)
    - Admin panel: 900px → 1200px, About page: 700px → 960px, Profile: 560px → 720px
    - Better use of screen real estate on desktop browsers

23. **Consistent Transport Labels in Logs** ✅ (PR #340)
    - All client-activity log messages now begin with a lowercase transport tag: `[mqtt]`, `[mqtt-tls]`, `[http]`, `[ws]`
    - TLS identity info follows the action, not the tag
    - Custom `AmqttConnectionFilter` rewrites ambiguous amqtt "connections acquired" messages
    - Added transport labeling guideline to AGENTS.md

24. **MQTT TLS Info on About & Setup Page** ✅ (PR #341)
    - New "MQTT TLS" section showing status, port, server cert details (CN, fingerprint, SANs, expiry), and CA details
    - OwnTracks configuration instructions updated to prioritize TLS mode when enabled

25. **Fix Device Polling (Paginated Response Bug)** ✅ (PR #342)
    - "Poll Devices" button was silently failing: frontend treated paginated `/api/devices/` response as flat array
    - Extracted `extractResultsList<T>()` utility for consistent pagination handling
    - Added `[http]` transport-tagged logging to command endpoint
    - 8 new TypeScript tests for paginated response extraction

26. **CI Shell Test Fix** ✅ (PR #343)
    - Changed `test_valid_log_levels` from "wait for success" to "fast negative check" (2s timeout)
    - Prevents CI timeout caused by `npm build` / `collectstatic` consuming the 5s window

## Upcoming Work

### Phase 7: Production Containerization

Package the application as a production-ready container image deployable on a CentOS 8+ host, with proper database, TLS termination, and a one-command deployment script.

**Step 1: PostgreSQL Support** ✅ (PR #355)
- `DATABASE_URL` env var wired into `config/settings.py` using `dj-database-url`
- Default: SQLite for development, PostgreSQL for production
- Connection pooling (`conn_max_age=600`, `conn_health_checks=True`)

**Step 2: Production Settings Hardening** ✅ (PR #356)
- `SECRET_KEY` raises `ImproperlyConfigured` if unset when `DEBUG=False`
- `ALLOWED_HOSTS` requires explicit setting in production (`netifaces` auto-detect only when `DEBUG=True`)
- `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` set in production

**Step 3: Dockerfile & Image Build** ✅ (PR #357)
- Multi-stage build: Node → Python (uv) → slim runtime
- Health check endpoint: `GET /api/health/` (no auth, returns version)
- Non-root `app` user, `libpq5` for PostgreSQL, ports 8080 + 8883
- `docker-entrypoint` script with configurable ports, log level, `--skip-migrate`
- `.dockerignore` excludes dev artifacts

**Step 4: Docker Compose Stack** ✅ (PR #358)
- Three services: nginx (TLS termination), my-tracks (app), postgres (database)
- Optional certbot service for Let's Encrypt (`--profile certbot`)
- Nginx: HTTPS reverse proxy, HTTP→HTTPS redirect, MQTT TLS TCP passthrough
- Security headers (HSTS, X-Frame-Options), login rate limiting, static file caching
- `.env.production.example` template with all configuration variables

**Step 5: Deployment Script** ✅ (PR #359)
- `./scripts/deploy` interactive first-time setup (secret generation, TLS certs, admin user)
- `./scripts/deploy --update` pulls latest image, migrates, restarts
- `./scripts/deploy --backup` timestamped gzipped `pg_dump`
- `./scripts/deploy --status`, `--stop`, `--logs` convenience commands

**Step 6: Semantic Versioning** ✅ (PR #354)
- `pyproject.toml` is single source of truth for version
- `get_version()` utility in `my_tracks/utils.py` via `importlib.metadata`
- Version displayed on About page and `/api/health/` endpoint
- `./scripts/release patch|minor|major` script (Typer CLI): bumps version, commits, tags, pushes
- Supports `--dry-run` and `--skip-push`

**Step 7: Container Registry & CI/CD Publish** ← NEXT
- Publish image to GitHub Container Registry (`ghcr.io/the-hcma/my-tracks`)
- GitHub Actions workflow triggered on version tags (`v*`):
  - Builds the multi-stage Docker image
  - Tags as `latest` and `vX.Y.Z`
  - Pushes to `ghcr.io`
- Multi-arch build (amd64 + arm64) for broad host compatibility
- Workflow also runs on PRs (build-only, no push) to catch Dockerfile regressions early

**Step 8: Network Hardening** ✅ (baked into Steps 4-5)
- Only exposed host ports: 443 (HTTPS), 80 (redirect), 8883 (MQTT TLS)
- HTTP 8080 and plain MQTT 1883 internal to Docker network only
- Nginx rate limiting on login endpoint
- Firewall guidance in DEPLOYMENT.md (firewalld + ufw)

**Step 9: Documentation** ✅ (PR #351, #362)
- Comprehensive DEPLOYMENT.md rewrite for containerized deployment
- Architecture diagram, configuration reference, TLS certificate options
- Day-to-day operations, semver release workflow, troubleshooting
- Clarified HTTPS vs MQTT TLS certificate distinction

27. **Replace venv activation with uv run** ✅ (PR #363)
    - Replaced `_activate_venv()` pattern with `_ensure_uv()` in `release`, `generate-tail`, `verify-setup`
    - Updated AGENTS.md Python CLI convention to use `uv run` instead of virtualenv

28. **Local Production Container Manager** ✅ (PR #365)
    - `production-testing/my-tracks-production-container-manager` script for macOS local testing
    - `--start` builds and launches the full Docker Compose stack (nginx + app + postgres)
    - `--stop` tears down all containers
    - `--freshen-up` regenerates `.env.production` and self-signed TLS certs
    - `--import-sqlite` imports a local SQLite database into PostgreSQL (preserves `SECRET_KEY` for PKI, `ALLOWED_HOSTS` for domain)
    - Transient database warning with `psql` connect command
    - Support for external PostgreSQL (skips containerized postgres)
    - Prerequisite checks for `docker`, `docker compose`, `curl`, `openssl`, `python3`, `uv`

29. **Fix uv Docker Image Tag** ✅ (PR #366)
    - Updated Dockerfile from `ghcr.io/astral-sh/uv:0.7-python3.14-bookworm-slim` to working tag
    - Previous tag was removed from the registry

30. **Container-Aware About Page** ✅ (PR #367)
    - `get_server_info()` helper derives hostname, port, scheme from `HttpRequest` instead of `socket.gethostname()`
    - Reads `HTTPS_PORT` / `HTTP_PORT` env vars for correct external port display behind Docker/Nginx
    - Filters loopback addresses from "Also accessible via" when a real domain is primary
    - Splits `docker-compose.yml` into base + optional `docker-compose.postgres.yml`
    - Renamed script from `my-tracks-production-container-tester` to `my-tracks-production-container-manager`

31. **Fix Pyright Type Errors & Hide Non-TLS MQTT in Production** ✅ (PR #368)
    - Resolved 8 pre-existing pyright type errors in `web_ui/views.py`
    - Wrapped `QueryDict.get()` calls with `str()`, `ValidationError.messages` with `str()` generator
    - `_is_staff()` returns `bool(user.is_staff)` instead of BooleanField descriptor
    - Non-TLS MQTT section hidden on About page when running behind proxy (`HTTPS_PORT` env var)

32. **Local Testing Docs & Bare Metal Guide** ✅ (PR #369)
    - New "Local Testing (macOS)" section in DEPLOYMENT.md recommending Colima
    - Container manager usage, default ports, SQLite import, database modes, cleanup
    - Expanded "Bare Metal (Alternative)" with distro-specific instructions for CentOS/RHEL and Ubuntu/Debian
    - Includes `uv` installation, PostgreSQL setup, Nginx config, systemd service

33. **Log User Creation Events** ✅ (PR #370)
    - Webservice logs new user creation events
    - Separate stack (independent of production containerization work)

### Phase 8: TLS Hot-Reload ✅

34. **TLS Hot-Reload** ✅ (PR #376)
    - `MQTTBroker.reload_tls()` method restarts the inner amqtt broker with new certificate material
    - `trigger_tls_reload()` in `apps.py` — thread-safe, fire-and-forget scheduler for the broker's event loop
    - Django `post_save` signals on `ServerCertificate` (when activated) and `ClientCertificate` (when revoked)
    - Reason propagated through entire reload chain for clear logging (cert CN, fingerprint, serial)
    - Server cert serial number included in `_log_cert_info()` to disambiguate rotations with same CN
    - `asyncio.Lock` prevents concurrent reloads
    - Fresh install flow: broker starts without TLS → admin creates cert → TLS listener starts automatically
    - Cert rotation: new server cert → broker reloads with updated cert (no server restart)
    - Client revocation: CRL rebuilt and loaded → revoked clients rejected immediately
    - 19 new tests (11 broker reload + 4 signal + 4 trigger function)

### Phase 8b: MQTT TLS Hardening

35. **MQTT TLS Hardening (nginx + logging)** ✅ (PR #380)
    - Nginx stream `limit_conn_zone` + `limit_conn mqtt 10` per IP on port 8883
    - MQTT auth failure logs elevated from DEBUG to WARNING for security monitoring
    - `_CRLBroker` docstring updated to reference cpython#83375 (TLS 1.3 bug)
    - New tests: SSL context configuration (mTLS + TLS 1.2 cap), auth failure log levels, nginx rate limiting

36. **Cert-Based MQTT Auth — CN Identity, Topic ACLs, Django Auth** ✅ (PR #383)
    - `DjangoAuthPlugin` now enforces username/password and topic ACLs on the TLS listener
    - MQTT username must match client certificate's Common Name (prevents cert-based impersonation)
    - `use_django_auth=True`, `allow_anonymous=False` on TLS listener config
    - TLS peer CN extracted and validated against authenticated MQTT username
    - Tests for CN mismatch rejection, topic ACL enforcement, anonymous rejection

37. **Cross-Platform Install Hints in Container Manager** ✅ (PR #387)
    - `install_hint()` helper provides OS-appropriate package install commands (brew on macOS, apt/dnf on Linux)
    - Prerequisite error messages now include platform-specific install instructions

**Remaining hardening (future PRs)**:
- **TLS 1.3 support** — Blocked by [cpython#83375](https://github.com/python/cpython/issues/83375) (open since Jan 2020, unassigned). When `asyncio.start_server` uses TLS 1.3 with `ssl.CERT_REQUIRED`, client certificate verification happens post-handshake; asyncio does not propagate the rejection, so invalid/expired/revoked certs silently get a dead connection instead of a handshake error. The workaround is `ctx.maximum_version = ssl.TLSVersion.TLSv1_2`. TLS 1.2 remains secure and is standard for MQTT/IoT. Monitor the CPython issue for a fix; when resolved, remove the `maximum_version` cap in `_CRLBroker._create_ssl_context()` and update the `test_caps_at_tls_1_2` test.

### Phase 7b: Production Hardening (In Progress)

38. **Squash 15 Migrations into Single Initial** (PR #389)
    - Consolidate migration history into clean `0001_initial` for fresh production deploys
    - Reduces `migrate` runtime and simplifies deployment

39. **Re-encrypt PKI Keys with Production SECRET_KEY During SQLite Import** (PR #390)
    - Container manager extracts source `SECRET_KEY` (Django-resolved, not raw `.env`)
    - `reencrypt_pki` management command re-encrypts CA, server, and client certificate private keys
    - Ensures PKI keys remain decryptable after migrating from dev SQLite to production PostgreSQL

40. **Container Log Volume for Tailable Logs** (PR #391)
    - Named `app-logs` Docker volume for persistent application logs
    - `RotatingFileHandler` writes to `/app/logs/my-tracks.log` inside container

41. **Improve Docker Daemon Error Detection with Actionable Recovery Hints** (PR #392)
    - `check_prerequisites()` in `deploy` script runs `docker info` and detects connectivity failures
    - Catches Docker 29+ `"failed to connect"` error pattern
    - Platform-specific recovery hints: Colima/Docker Desktop on macOS, systemctl on Linux

42. **Host-Accessible .run/ Directory for Container Manager Staging and Logs** (PR #393)
    - Staging directory moved from `/tmp/` to `production-testing/.run/` (inside repo, gitignored)
    - Fixes Colima bind mount failures (macOS `/tmp` → `/private/tmp` outside virtiofs share)
    - `APP_LOGS_DIR` env var parameterizes log volume: bind mount for local testing, named volume for production
    - Banner shows host-accessible paths for nginx config, TLS certs, and app logs
    - `tail -f .run/logs/my-tracks.log` replaces long `docker-compose exec` command

43. **Catch PKI Re-encryption Key Mismatch with Actionable Error Message** (PR #394)
    - `_probe_key()` test-decrypts a single PKI key before bulk re-encryption
    - On mismatch: `CommandError` with common causes (placeholder .env key, Django default, key rotation)
    - Container manager tries Django's default insecure key as fallback

44. ✅ **Reorganize Test Scripts Under Top-Level `tests/`**
    - Move all test scripts into a top-level `tests/` directory
    - Organize test scripts by language using subdirectories (for example, `tests/python/`, `tests/bash/`, `tests/typescript/`)
    - Update test discovery/configuration paths so existing CI and local workflows continue to work
    - Update project documentation to reflect the new testing layout and commands

45. ✅ **Reorganize Bash Scripts Under Top-Level `scripts/`**
    - Move Bash scripts into a top-level `scripts/` directory
    - Keep script naming and executable conventions intact while updating all references
    - Update documentation and operational examples to use the new script paths
    - Update configuration/workflow references that point to legacy script locations

46. **Let's Encrypt Certificate Support in Production Container Manager**

    **Problem**: The container manager currently generates self-signed certs for every `--start`, which means every browser session shows a TLS warning. Users who already hold Let's Encrypt (or other CA-issued) certs for their domain can't use them cleanly — the manager ignores them and overwrites with self-signed.

    **Goal**: When real certs are present the stack starts with a fully browser-trusted HTTPS endpoint. When no certs exist, the manager guides the user through supplying them before starting.

    ---

    **Domain detection** (happens early in `cmd_start`, before env is written):

    1. If `production/var/certs/fullchain.pem` exists, extract the domain automatically:
       ```bash
       # Prefer SAN (RFC-correct); fall back to CN
       domain=$(openssl x509 -noout -ext subjectAltName \
                   -in "$CERTS_DIR/fullchain.pem" 2>/dev/null \
               | grep -oE 'DNS:[^,]+' | head -1 | sed 's/DNS://')
       [ -z "$domain" ] && domain=$(openssl x509 -noout -subject \
                   -in "$CERTS_DIR/fullchain.pem" \
               | sed -n 's/.*CN\s*=\s*//p' | xargs)
       ```
    2. Validate the cert/key pair match (compare public-key fingerprints of cert and key).
    3. Check expiry: error if already expired; warn (but continue) if expiring within 30 days.
    4. Print the detected domain so the user can confirm: `info "Detected domain from cert: $domain"`.

    **No-cert flow** (certs absent and `--freshen-up` not passed):

    Present a choice instead of silently self-signing:
    ```
    ── TLS Certificate Setup ──
      No certificates found in production/var/certs/

      a) Import Let's Encrypt certs  — copy from certbot or a custom path (browser-trusted)
      b) Generate self-signed cert   — fast start; browser will show a security warning
    ```
    - **Option a — import**:
      1. Probe the certbot default path: `/etc/letsencrypt/live/<domain>/` (if the user already
         has a domain in mind, or skip probing and ask first).
      2. Prompt: `Domain name (e.g. mytracks.example.com):` — used to find
         `/etc/letsencrypt/live/<domain>/{fullchain,privkey}.pem`.
      3. If certbot path not found, prompt: `Path to fullchain.pem:` / `Path to privkey.pem:`.
      4. Validate the pair, then copy to `production/var/certs/`.
      5. Domain is now known from the imported cert (step 1 of detection above).
    - **Option b — self-signed**: existing `create_self_signed_certs` behaviour; domain stays
      `localhost`, self-signed for `localhost` (unchanged behaviour).

    **`--freshen-up` behaviour change**:
    - Currently always regenerates self-signed. After this change:
      - If `production/var/certs/` already has a real CA cert, `--freshen-up` preserves it
        and only wipes env/db/logs (not certs). Add `--freshen-up --reset-certs` to explicitly
        replace certs as well.
      - If certs are absent, runs the no-cert flow above (import or self-sign).

    **New `--update-certs` command**:
    ```
    ./production/scripts/my-tracks-production-container-manager --update-certs
    ```
    - Prompts for the new cert source (certbot path or custom paths).
    - Validates the new cert/key pair.
    - Copies to `production/var/certs/`, replacing existing files.
    - Re-stages bind-mount files (`stage_bind_mounts`) and sends `nginx -s reload` to the
      running nginx container so the new cert takes effect without a full restart.
    - Displays new expiry date on completion.

    **Django environment (`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`)**:
    - When domain is a real hostname (not `localhost`/`127.0.0.1`):
      - `ALLOWED_HOSTS=<domain>` (no localhost in production mode; add 127.0.0.1 only if
        POSTGRES_MODE=transient so health-checks still work)
      - `CSRF_TRUSTED_ORIGINS=https://<domain>`
    - When domain is `localhost` (self-signed path):
      - Current defaults unchanged: `ALLOWED_HOSTS=localhost,127.0.0.1`
      - `CSRF_TRUSTED_ORIGINS=https://localhost:<HTTPS_PORT>`

    **nginx `server_name` patch**:
    - After staging nginx config to `production/run/nginx/nginx.conf`, apply a `sed` substitution:
      `server_name _;` → `server_name <domain>;`
    - This enables proper SNI matching and is required for correct ACME renewal probes.
    - The source file `production/nginx/nginx.conf` keeps `server_name _;` as the generic
      default; the patch is applied only to the staged copy.

    **Port defaults when a real domain is used**:
    - Currently the manager uses non-standard ports (8443/8080/8883) to avoid local conflicts.
    - When a real Let's Encrypt domain is detected, default to standard ports (443/80/8883)
      and note in the banner that standard ports are in use.
    - Allow override with `--https-port`, `--http-port`, `--mqtt-tls-port` as before.

    **Start banner addition**:
    ```
    TLS:   Let's Encrypt  (expires 2025-09-14, 87 days)   [or: Self-signed (localhost)]
    ```

    **Cert expiry reminder on every `--start`**:
    - If a real cert is present and expires within 30 days, print a prominent warning:
      ```
      ⚠  TLS cert expires in 23 days (2025-04-07). Run --update-certs to renew.
      ```

    **Automated nginx cert reload (nightly cron)**:
    - nginx is the TLS termination layer; Django/Daphne sit behind it over plain HTTP and
      never touch certs directly. Only nginx needs to reload when certs change on disk.
    - `nginx -s reload` performs a graceful in-place reload (zero downtime, drains existing
      connections before workers restart with the new cert).
    - Assume an external process (any renewal tool — certbot, acme.sh, manual copy, etc.)
      places new `fullchain.pem` / `privkey.pem` into `production/var/certs/` on the host.
    - The container manager's `--start` banner prints the host cron line to add:
      ```
      ── Automated cert reload ──
        Add this cron entry to pick up renewed certs within 24 hours (zero downtime):
          0 3 * * * cd /path/to/repo && docker compose -f production/docker/docker-compose.yml exec nginx nginx -s reload
      ```
    - The 24-hour maximum lag is acceptable: renewals typically happen 30+ days before
      expiry, so the window between cert-on-disk and nginx-picks-it-up is inconsequential.
    - `--update-certs` continues to reload nginx immediately after copying new certs, for
      cases where the operator wants instant pickup without waiting for the nightly cron.

    **Cert expiry email notification (Django management command)**:
    - A new management command `check_cert_expiry` checks `fullchain.pem` expiry using
      Python's `ssl` module and sends an email warning if ≤ 10 days remain.
    - Django needs read access to the cert: mount `production/var/certs/` read-only into
      the Django container (in addition to the existing nginx mount):
      ```yaml
      # in docker-compose.yml my-tracks service
      volumes:
        - ${CERTS_DIR}/fullchain.pem:/app/certs/fullchain.pem:ro
      ```
    - The cert path is exposed via `TLS_CERT_PATH=/app/certs/fullchain.pem` in the
      container environment (set from `CERTS_DIR` in the compose file).
    - The management command reads `TLS_CERT_PATH`, skips gracefully if unset or file absent
      (so dev environments without certs are unaffected).
    - Email is sent via Django's standard mail backend to all addresses in `ADMINS`.
    - Run daily from a host cron (printed in the `--start` banner alongside the nginx cron):
      ```
      30 3 * * * cd /path/to/repo && docker compose -f production/docker/docker-compose.yml exec my-tracks python manage.py check_cert_expiry
      ```

    **SMTP configuration**:
    - New Django settings (read from environment):
      `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
      `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`, `ADMINS`
    - Added to `examples/.env.production.example` with commented-out placeholders and a
      note that `check_cert_expiry` and any future alert emails require these to be set.
    - The container manager prompts for SMTP settings during `--start` setup (optional,
      skippable — if left blank the command logs to stdout and skips sending).

    **Files changed**:
    - `production/scripts/my-tracks-production-container-manager`:
      - New functions: `detect_domain_from_cert`, `validate_cert_key_pair`, `check_cert_expiry`,
        `import_letsencrypt_certs`, `patch_nginx_server_name`, `cmd_update_certs`
      - Modified: `cmd_start` (domain detection before env write, port defaults, banner,
        cron hint lines), `cmd_freshen_up` (preserve real certs unless `--reset-certs`),
        `env_spec` (add SMTP vars as optional)
    - `production/docker/docker-compose.yml`: mount cert read-only into Django container;
      pass `TLS_CERT_PATH` env var
    - `my_tracks/management/commands/check_cert_expiry.py`: new management command
    - `config/settings.py`: add `EMAIL_*` and `ADMINS` settings from environment
    - `examples/.env.production.example`: add commented SMTP block
    - `docs/DEPLOYMENT.md`: document `--update-certs`, cert import flow, nightly cron
      setup, SMTP configuration, and `check_cert_expiry`

47. **Pre-Internet Security Scan**

    **Problem**: Before opening port 443 to the internet, there should be a documented
    checklist and an automated scan to catch obvious vulnerabilities in the codebase and
    container configuration.

    **Goal**: A single command (or short sequence) that any operator can run to get a
    confidence signal that the stack is reasonably hardened before going public.

    ---

    **Scan categories**:

    1. **Python dependency audit** — `uv run pip-audit` (or `safety check`) flags packages
       with known CVEs. Add `pip-audit` as a dev dependency.

    2. **Container image scan** — `docker scout cves ghcr.io/the-hcma/my-tracks:latest`
       (Docker Scout is bundled with Docker Desktop and Docker Engine ≥ 24). Reports CVEs
       in the base image and installed packages. Run after `compose build` but before
       going live.

    3. **Django deployment checklist** — `python manage.py check --deploy` is Django's
       built-in hardening check. Verifies `DEBUG=False`, `ALLOWED_HOSTS` set, `SECRET_KEY`
       strength, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
       `HSTS` headers, etc. Fails non-zero on any finding — can be run inside the container
       via `docker compose exec my-tracks python manage.py check --deploy`.

    4. **Shell script static analysis** — `shellcheck` on all scripts under `scripts/` and
       `production/scripts/` (already run in CI; ensure it covers new scripts added in
       step 46).

    5. **Secret / credential leak scan** — `trufflehog filesystem .` or `gitleaks detect`
       to confirm no secrets are accidentally committed. Add as a one-time pre-launch step.

    **Container manager integration**:
    - New `--security-check` command that runs items 1–3 (pip-audit, docker scout, manage.py
      check --deploy) in sequence and prints a summary. Exits non-zero if any scan finds
      high/critical issues, so it can gate a deployment script.
    - Printed in the `--start` banner as a recommended pre-launch step:
      ```
      ── Before opening port 443 ──
        Run: ./production/scripts/my-tracks-production-container-manager --security-check
      ```

    **CI integration**:
    - Add `pip-audit` to the `backend-lint` job in `pr-validation.yml` so dependency CVEs
      are caught per-PR, not just at deploy time.
    - `manage.py check --deploy` runs in the `backend-test` job (already has a running
      Django process) with a production-like env (`DEBUG=False`, dummy `SECRET_KEY`, etc.).

    **Files changed**:
    - `production/scripts/my-tracks-production-container-manager`: add `cmd_security_check`
    - `.github/workflows/pr-validation.yml`: add `pip-audit` step to `backend-lint` job;
      add `manage.py check --deploy` step to `backend-test` job
    - `pyproject.toml`: add `pip-audit` to dev dependencies
    - `docs/DEPLOYMENT.md`: pre-launch security checklist section

### Phase 9: Advanced Integration
1. **Transition events** — Handle region enter/exit events, store transition history
2. **Waypoints sync** — Connect waypoint storage to command API, allow UI to send waypoints to devices
3. **Friends feature** — Refine as a phased, backward-compatible sharing model:
   - Add explicit ownership and sharing entities (`Device.owner`, `FriendRequest`, `FriendConnection` with per-direction share toggles)
   - Keep OwnTracks ingestion (`POST /api/locations/`) behavior unchanged, but enforce visibility on read paths (`/api/locations/`, `/api/devices/`, device locations)
   - Add friend APIs (send/list/accept/decline/remove requests + share preference updates)
   - Extend MQTT ACL rules so subscribe access supports approved friend visibility while preserving own-topic publish constraints
   - Replace global WebSocket fan-out with visibility-aware delivery (only owner + authorized friends receive updates)
   - Cover with dedicated tests for model constraints, API filtering, MQTT ACL, and WebSocket visibility behavior

## Key Files

```
my_tracks/mqtt/
├── __init__.py      # Module exports
├── broker.py        # MQTTBroker class
├── handlers.py      # OwnTracksMessageHandler
├── auth.py          # DjangoAuthPlugin
├── commands.py      # Command, CommandPublisher
└── plugin.py        # OwnTracksPlugin (amqtt broker plugin)
```

## Test Coverage

- 1120+ Python tests + 87 TypeScript tests passing
- 97%+ code coverage (target: 90%)
- Tests run in parallel via pytest-xdist with accurate coverage merging
- All pyright checks pass (0 errors, 0 warnings)
- All imports sorted (isort clean)
- All shell scripts pass shellcheck
- CI pipeline: 4 parallel jobs (Frontend, Backend Lint, Backend Tests, Shell Script Tests)

## Technical Notes

- **Python 3.14 compatibility**: amqtt installed from git, not PyPI
- **MQTT v3.1.1 required**: amqtt only supports protocol level 4 (v3.1.1). OwnTracks Android defaults to v3.1 — reconfigure with `{"_type": "configuration", "mqttProtocolLevel": 4}`. The broker logs a warning when a v3.1 client connects.
- **Django ORM in async**: Use `sync_to_async` wrapper
- **SQLite async tests**: Use `@pytest.mark.django_db(transaction=True)`

## Future Enhancements

- **ACME / Let's Encrypt** — Optional integration for publicly trusted server certificates instead of self-signed CA
- **TLS 1.3 for MQTT** — Waiting on [cpython#83375](https://github.com/python/cpython/issues/83375) fix (see Phase 8b notes)
