# my-tracks Email Guidelines

All emails sent by my-tracks **must** follow these rules so recipients can always
identify which server sent a message and when.

## Required fields in every email body

| Field | Rule |
|-------|------|
| **Public domain** | If `settings.PUBLIC_DOMAIN` is non-empty, include it so the recipient knows which deployment sent the email. |
| **Timestamp** | Include both the local server time (`settings.SYSTEM_TIMEZONE`) **and** the UTC time, formatted as `YYYY-MM-DD HH:MM:SS TZ (YYYY-MM-DD HH:MM:SS UTC)`. |

## Implementation pattern

```python
from datetime import datetime, timezone as _utc
from django.conf import settings

now = datetime.now(tz=_utc.utc)
local_ts = now.astimezone(settings.SYSTEM_TIMEZONE)
utc_ts = now.astimezone(_utc.utc)
ts_str = (
    f"{local_ts.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    f" ({utc_ts.strftime('%Y-%m-%d %H:%M:%S UTC')})"
)

public_domain = getattr(settings, 'PUBLIC_DOMAIN', '')
# ... include ts_str and public_domain in the email body ...
```

## Applies to

- `send_transition_email` — geofence transition notifications (`app/notifications.py`)
- `send_test_email_via_backend` — SMTP configuration test (`app/notifications.py`)
- `action_test` — automation rule test email (`web_ui/views.py`)
- Any future email sending code added to my-tracks

## Checklist for new email functions

- [ ] Subject prefixed with `[my-tracks]`
- [ ] Body includes `Sent at: <local> (<utc>)` line
- [ ] Body includes `Sent by: <public_domain or smtp_host>` line
