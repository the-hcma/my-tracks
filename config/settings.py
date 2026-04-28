"""
Django settings for my-tracks project.

Generated for Django 5.0, using Python 3.12+.
For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""

from pathlib import Path
from typing import Any

import dj_database_url
from decouple import config
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR: Path = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG: bool = config('DEBUG', default=True, cast=bool)

# SECURITY WARNING: keep the secret key used in production secret!
_secret_key_default = 'django-insecure-change-me-in-production' if DEBUG else ''
SECRET_KEY: str = str(config('SECRET_KEY', default=_secret_key_default))
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in production (DEBUG=False). "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(50))\""
    )

# Allow URLs both with and without trailing slashes (OwnTracks POSTs without slash)
APPEND_SLASH = False

ALLOWED_HOSTS: list[str] = [
    host.strip()
    for host in str(config('ALLOWED_HOSTS', default='localhost,127.0.0.1')).split(',')
    if host.strip()
]

PUBLIC_DOMAIN: str = str(config('PUBLIC_DOMAIN', default=''))

if DEBUG:
    # Auto-discover and add all local network IPs to ALLOWED_HOSTS in development.
    # Only includes broadcast-capable interfaces (excludes VPN/tunnel adapters).
    # netifaces requires a C compiler to build, so it's optional and only loaded here.
    try:
        import netifaces

        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            for addr_info in addrs.get(netifaces.AF_INET, []):
                ip = addr_info.get('addr', '')
                has_broadcast = bool(addr_info.get('broadcast'))
                if ip and not ip.startswith('127.') and has_broadcast and ip not in ALLOWED_HOSTS:
                    ALLOWED_HOSTS.append(ip)
    except ImportError:
        pass


# Application definition

INSTALLED_APPS: list[str] = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'channels',
    'app.apps.MyTracksConfig',
    'web_ui.apps.WebUiConfig',
]

MIDDLEWARE: list[str] = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'app.middleware.RequestLoggingMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF: str = 'config.urls'

TEMPLATES: list[dict[str, Any]] = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION: str = 'config.wsgi.application'
ASGI_APPLICATION: str = 'config.asgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
# Set DATABASE_URL for PostgreSQL in production:
#   DATABASE_URL=postgresql://user:pass@host:5432/mytracks
# Defaults to SQLite for local development.

_SQLITE_DEFAULT = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

# Use decouple's config() so DATABASE_URL is read from the .env file as well as
# from the environment — dj_database_url.config() reads os.environ only and
# would miss DATABASE_URL values written to .env by on-deploy.
DATABASES: dict[str, Any] = {
    'default': dj_database_url.parse(
        str(config('DATABASE_URL', default=_SQLITE_DEFAULT)),
        conn_max_age=600,
        conn_health_checks=True,
    ),
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS: list[dict[str, Any]] = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE: str = 'en-us'

TIME_ZONE: str = 'UTC'

USE_I18N: bool = True

USE_TZ: bool = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL: str = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise configuration for serving static files
_staticfiles_backend = (
    "whitenoise.storage.CompressedStaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
STORAGES: dict[str, dict[str, str]] = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": _staticfiles_backend,
    },
}

if DEBUG:
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = True

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD: str = 'django.db.models.BigAutoField'


# REST Framework settings
REST_FRAMEWORK: dict[str, Any] = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 100,
}

# Authentication URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Session configuration: 7-day sliding window expiry
SESSION_COOKIE_AGE = 604800  # 7 days in seconds
SESSION_SAVE_EVERY_REQUEST = True  # Reset expiry on each request (sliding window)

# Logging configuration
import logging
import os
import time
from datetime import datetime, timedelta
from datetime import timezone as _tz
from zoneinfo import ZoneInfo


# Django sets os.environ['TZ'] = TIME_ZONE and calls time.tzset() after loading
# this module, which makes time.localtime() return UTC when TIME_ZONE='UTC'.
# Detect the real system timezone now, before Django overrides it.
def _detect_system_timezone() -> ZoneInfo | _tz:
    # 1. TZ env var (Docker, explicit config) — still original before Django overrides
    tz_env = os.environ.get('TZ')
    if tz_env and tz_env != 'UTC':
        try:
            return ZoneInfo(tz_env)
        except (KeyError, ValueError):
            pass
    # 2. /etc/localtime symlink (macOS, most Linux)
    try:
        link = os.readlink('/etc/localtime')
        idx = link.find('/zoneinfo/')
        if idx != -1:
            return ZoneInfo(link[idx + len('/zoneinfo/'):])
    except OSError:
        pass
    # 3. /etc/timezone plain-text file (Debian/Ubuntu)
    try:
        tz_name = Path('/etc/timezone').read_text().strip()
        if tz_name:
            return ZoneInfo(tz_name)
    except (OSError, KeyError, ValueError):
        pass
    # 4. Fallback: fixed offset from current localtime (no DST transitions)
    return _tz(timedelta(seconds=time.localtime().tm_gmtoff))

SYSTEM_TIMEZONE = _detect_system_timezone()
del _detect_system_timezone

# Add custom TRACE level (below DEBUG)
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, 'TRACE')

def trace(self: logging.Logger, message: str, *args: object, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)

logging.Logger.trace = trace  # type: ignore[attr-defined]

# Custom filter to set health check requests to TRACE level
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Check if this is a health check request
        if hasattr(record, 'msg') and '/health/' in str(record.msg):
            record.levelno = TRACE_LEVEL
            record.levelname = 'TRACE'
        return True


# Filter out confusing daphne "Configuring endpoint tcp:port=0" messages
class DaphnePortZeroFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Transform the confusing "Configuring endpoint tcp:port=0" message
        # to clarify that port 0 means OS-allocated ephemeral port
        msg = str(getattr(record, 'msg', ''))
        if 'Configuring endpoint tcp:port=0' in msg:
            record.msg = 'Requesting OS-allocated ephemeral port (port=0)...'
        return True


class AmqttConnectionFilter(logging.Filter):
    """Rewrite amqtt's ambiguous 'connections acquired' messages."""

    _prev_count: dict[str, int] = {}
    _LISTENER_TO_TRANSPORT = {"default": "mqtt", "mqtt-tls": "mqtt-tls"}

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(getattr(record, 'msg', ''))
        if 'connections acquired' not in msg:
            return True
        try:
            parts = msg.split("'")
            listener = parts[1]
            count_part = parts[2].split('/')[0].strip().rstrip(':').strip()
            count = int(count_part)
        except (IndexError, ValueError):
            return True
        prev = self._prev_count.get(listener, 0)
        self._prev_count[listener] = count
        tag = self._LISTENER_TO_TRANSPORT.get(listener, listener)
        if count > prev:
            record.msg = f"[{tag}] Client connected ({count} active)"
        else:
            record.msg = f"[{tag}] Client disconnected ({count} active)"
        return True


# URL prefixes that are WebSocket-only (no HTTP handler registered).
# HTTP requests to these paths always 404 — that is expected, not a problem.
_WS_PREFIXES = ('/ws/',)


class WebSocketNotFoundFilter(logging.Filter):
    """Downgrade django.request 404s for WebSocket-only paths to INFO.

    When a browser (or any HTTP client) sends a plain HTTP request to a
    WebSocket-only endpoint like /ws/locations/, Django's HTTP handler returns
    404 and logs it at WARNING via log_response().  That WARNING is misleading
    because the 404 is expected — the path only exists in the WebSocket URL
    router, not in the HTTP URL conf.

    This filter intercepts those records, improves the message so the cause
    is immediately clear, and downgrades the level to INFO so it is visible
    but does not look like a server-side error.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, 'status_code', None) != 404:
            return True
        # django.request formats 404s as msg="%s: %s", args=("Not Found", path)
        args = getattr(record, 'args', ())
        path = args[1] if isinstance(args, tuple) and len(args) >= 2 else ''
        if not str(path).startswith(_WS_PREFIXES):
            return True
        record.levelno = logging.INFO
        record.levelname = 'INFO'
        record.msg = 'HTTP request to WebSocket-only endpoint (no Upgrade header): %s'
        record.args = (path,)
        return True


# Custom formatter that uses the real system timezone for log timestamps.
# We cannot rely on time.localtime() because Django overrides TZ to UTC.
class LocalTimeFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        tz = _tz.utc if os.environ.get('LOG_UTC') else SYSTEM_TIMEZONE
        dt = datetime.fromtimestamp(record.created, tz=tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S") + ",%03d" % record.msecs

# Optional file logging: set LOG_FILE env var to enable (e.g., /app/logs/my-tracks.log)
LOG_FILE: str = str(config('LOG_FILE', default=''))

_handlers: dict[str, dict[str, Any]] = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
        'filters': ['health_check_filter'],
    },
}

_all_handlers = ['console']

if LOG_FILE:
    log_dir = Path(LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    _handlers['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': LOG_FILE,
        'maxBytes': 10 * 1024 * 1024,  # 10 MB
        'backupCount': 5,
        'formatter': 'verbose',
        'filters': ['health_check_filter'],
    }
    _all_handlers.append('file')

# Honour the log level exported by my-tracks-server (or docker-entrypoint).
# Falls back to INFO so that plain `manage.py runserver` is unaffected.
_app_log_level: str = config('DJANGO_LOG_LEVEL', default='INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'health_check_filter': {
            '()': 'config.settings.HealthCheckFilter',
        },
        'daphne_port_zero_filter': {
            '()': 'config.settings.DaphnePortZeroFilter',
        },
        'amqtt_connection_filter': {
            '()': 'config.settings.AmqttConnectionFilter',
        },
        'ws_not_found_filter': {
            '()': 'config.settings.WebSocketNotFoundFilter',
        },
    },
    'formatters': {
        'verbose': {
            '()': 'config.settings.LocalTimeFormatter',
            'format': '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(module)-12s | %(message)s',
            'datefmt': '%Y%m%d-%H:%M:%S',
        },
    },
    'handlers': _handlers,
    'root': {
        'handlers': _all_handlers,
        'level': _app_log_level,
    },
    'loggers': {
        'app': {
            'handlers': _all_handlers,
            'level': _app_log_level,
            'propagate': False,
        },
        'django.server': {
            'handlers': _all_handlers,
            'level': TRACE_LEVEL,
            'propagate': False,
        },
        'daphne.server': {
            'handlers': _all_handlers,
            'level': 'INFO',
            'filters': ['daphne_port_zero_filter'],
            'propagate': False,
        },
        'amqtt.broker': {
            'handlers': _all_handlers,
            'level': 'INFO',
            'filters': ['amqtt_connection_filter'],
            'propagate': False,
        },
        'transitions.core': {
            'handlers': _all_handlers,
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': _all_handlers,
            'level': 'INFO',
            'filters': ['ws_not_found_filter'],
            'propagate': False,
        },
    },
}

# CSRF exemption for OwnTracks endpoints (they use device authentication)
def _parse_csrf_origins(value: str) -> list[str]:
    """Parse comma-separated CSRF origins from environment."""
    return [s.strip() for s in value.split(',') if s.strip()]

CSRF_TRUSTED_ORIGINS: list[str] = _parse_csrf_origins(
    str(config('CSRF_TRUSTED_ORIGINS', default=''))
)

# Allow cross-origin requests (e.g. OpenStreetMap tile servers) to receive the
# origin as Referer. Django's SecurityMiddleware defaults to "same-origin" which
# strips the Referer entirely for cross-origin requests, causing OSM 403s.
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Production security settings (only active when DEBUG=False)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER: tuple[str, str] = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Channels configuration
CHANNEL_LAYERS: dict[str, Any] = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}
