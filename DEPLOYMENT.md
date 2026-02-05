# Deployment Guide

This guide covers deploying My Tracks to production.

**Package Manager**: This project uses [uv](https://github.com/astral-sh/uv) exclusively for fast, reliable dependency management.

## Prerequisites

- Python 3.14+
- PostgreSQL 14+ (recommended for production)
- Nginx (for reverse proxy)
- SSL certificate (Let's Encrypt recommended)
- Domain name

## Production Configuration

### 1. Environment Variables

Create a `.env` file with production settings:

```bash
# Security
SECRET_KEY=<generate-a-strong-random-key>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database
DATABASE_URL=postgresql://username:password@localhost:5432/owntracks

# CSRF
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

### 2. Generate Secret Key

```bash
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

### 3. PostgreSQL Setup

Install PostgreSQL:
```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql
```

Create database:
```bash
sudo -u postgres psql
CREATE DATABASE owntracks;
CREATE USER owntrackuser WITH PASSWORD 'your_password';
ALTER ROLE owntrackuser SET client_encoding TO 'utf8';
ALTER ROLE owntrackuser SET default_transaction_isolation TO 'read committed';
ALTER ROLE owntrackuser SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE owntracks TO owntrackuser;
\q
```

### 4. Install Dependencies

```bash
# Install all dependencies (uv run handles venv automatically)
uv sync --all-extras
```

### 5. Application Setup

```bash
# Collect static files
uv run python manage.py collectstatic --noinput

# Run migrations
uv run python manage.py migrate

# Create superuser
uv run python manage.py createsuperuser
```

### 6. Daphne ASGI Server Configuration

Daphne is used as the ASGI server to support WebSocket connections. The `./my-tracks-server` script handles this automatically for development.

For production, the systemd service (Step 7) runs Daphne directly.

### 7. Systemd Service

Create `/etc/systemd/system/my-tracks.service`:

```ini
[Unit]
Description=My Tracks OwnTracks Backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/path/to/my-tracks
Environment="PATH=/path/to/my-tracks/.venv/bin"
ExecStart=/path/to/my-tracks/.venv/bin/daphne \
    -b 127.0.0.1 \
    -p 8080 \
    config.asgi:application

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable my-tracks
sudo systemctl start my-tracks
sudo systemctl status my-tracks
```

### 8. Nginx Configuration

Create `/etc/nginx/sites-available/my-tracks`:

```nginx
upstream my_tracks_backend {
    server 127.0.0.1:8080;
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;
    
    # SSL configuration
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    client_max_body_size 4G;
    
    # Static files
    location /static/ {
        alias /path/to/my-tracks/staticfiles/;
        expires 30d;
    }
    
    # Django application
    location / {
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host $http_host;
        proxy_redirect off;
        proxy_pass http://my_tracks_backend;
    }
}
```

Enable site:
```bash
sudo ln -s /etc/nginx/sites-available/my-tracks /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 9. SSL Certificate (Let's Encrypt)

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

### 10. Firewall Configuration

```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

## Monitoring and Maintenance

### Log Locations

- Application logs: `logs/my-tracks.log` (with rotation)
- Nginx logs: `/var/log/nginx/`
- System logs: `journalctl -u my-tracks`

### Database Backups

Create daily backup script `/usr/local/bin/backup_owntracks`:

```bash
#!/usr/bin/env bash
BACKUP_DIR="/backups/owntracks"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR
pg_dump owntracks > $BACKUP_DIR/owntracks_$DATE.sql
gzip $BACKUP_DIR/owntracks_$DATE.sql

# Keep only last 30 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
```

Add to crontab:
```bash
0 2 * * * /usr/local/bin/backup_owntracks
```

Make executable:
```bash
chmod +x /usr/local/bin/backup_owntracks
```

### Health Checks

Create a health check endpoint or use Django's built-in admin health check.

### Updating the Application

```bash
# Sync with remote (using Graphite)
gt sync --force

# Update dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Collect static files
uv run python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart my-tracks
```

## Security Checklist

- [ ] DEBUG=False in production
- [ ] Strong SECRET_KEY
- [ ] PostgreSQL with strong password
- [ ] SSL/TLS enabled
- [ ] Firewall configured
- [ ] Regular security updates
- [ ] Database backups enabled
- [ ] Monitoring configured
- [ ] Rate limiting (consider django-ratelimit)
- [ ] ALLOWED_HOSTS configured correctly

## Performance Optimization

### Database Indexing

Already implemented in models:
- Device lookup by device_id
- Location queries by device and timestamp

### Caching

Add Redis caching for improved performance (add `django-redis` to pyproject.toml dependencies, then run `uv sync`):

Update settings.py:
```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}
```

### Database Connection Pooling

For PostgreSQL:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'owntracks',
        'USER': 'owntrackuser',
        'PASSWORD': 'password',
        'HOST': 'localhost',
        'PORT': '5432',
        'CONN_MAX_AGE': 600,
    }
}
```

## Troubleshooting

### Check Service Status
```bash
sudo systemctl status owntracks
journalctl -u owntracks -f
```

### Check Nginx
```bash
sudo nginx -t
sudo systemctl status nginx
tail -f /var/log/nginx/error.log
```

### Database Issues
```bash
sudo -u postgres psql owntracks
\dt  # List tables
\d+ my_tracks_location  # Describe table
```

### Permission Issues
```bash
sudo chown -R www-data:www-data /path/to/my-tracks
sudo chmod -R 755 /path/to/my-tracks
```

## Support

For issues, please create an issue on the GitHub repository.
