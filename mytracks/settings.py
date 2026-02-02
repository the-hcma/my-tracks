"""
Django settings for mytracks project.

Generated for Django 5.0, using Python 3.12+.
For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""

from pathlib import Path

from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR: Path = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY: str = str(config('SECRET_KEY', default='django-insecure-change-me-in-production'))

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG: bool = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS: list[str] = ['*']


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
    'tracker.apps.TrackerConfig',
]

MIDDLEWARE: list[str] = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF: str = 'mytracks.urls'

TEMPLATES: list[dict] = [
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

WSGI_APPLICATION: str = 'mytracks.wsgi.application'
ASGI_APPLICATION: str = 'mytracks.asgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES: dict = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS: list[dict] = [
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

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD: str = 'django.db.models.BigAutoField'


# REST Framework settings
REST_FRAMEWORK: dict = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 100,
}

# Logging configuration
import logging
import time

# Add custom TRACE level (below DEBUG)
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, 'TRACE')

def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)

logging.Logger.trace = trace

# Custom filter to set health check requests to TRACE level
class HealthCheckFilter(logging.Filter):
    def filter(self, record):
        # Check if this is a health check request
        if hasattr(record, 'msg') and '/health/' in str(record.msg):
            record.levelno = TRACE_LEVEL
            record.levelname = 'TRACE'
        return True

# Custom formatter that uses local time instead of UTC
class LocalTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        """Override formatTime to use local time instead of UTC."""
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            s = time.strftime("%Y-%m-%d %H:%M:%S", ct)
            s = "%s,%03d" % (s, record.msecs)
        return s
    
    converter = time.localtime  # Use local time instead of gmtime

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'health_check_filter': {
            '()': 'mytracks.settings.HealthCheckFilter',
        },
    },
    'formatters': {
        'verbose': {
            '()': 'mytracks.settings.LocalTimeFormatter',
            'format': '%(asctime)s.%(msecs)03d %(levelname)-7s %(module)s %(message)s',
            'datefmt': '%Y%m%d-%H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['health_check_filter'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'tracker': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['console'],
            'level': TRACE_LEVEL,
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

# Channels configuration
CHANNEL_LAYERS: dict = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}
