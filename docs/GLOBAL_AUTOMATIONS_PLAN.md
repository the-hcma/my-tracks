# Global Automations — Implementation Plan

**Status**: Planning  
**Last Updated**: April 28, 2026

---

## Goal

Allow admins to define server-evaluated automation rules that fire when a
**combination of users** are simultaneously inside or outside a geofence.
Examples:
- Send an email (or hit a webhook) when both Henrique and Kristen are inside
  the home geofence.
- Turn off the house lights when both users are outside the home geofence.

---

## Scope boundaries

| In scope | Out of scope |
|---|---|
| Admin-only rule management | Per-user global rules |
| Email and webhook actions | Other action types |
| Server-side evaluation via latest known location | Phone-reported transition messages as the trigger |
| State change fire-once (no spam) | Rate-limiting / debounce |
| Re-evaluation on every new location from watched users | Push/WS notifications for rule firings |

---

## Design decisions

### 1. Admin only
Only staff users can create, edit, or delete global automation rules.
Regular users cannot define rules that apply to other users.

### 2. State from latest known location
For each watched user, "inside or outside the geofence?" is determined
server-side using:
- The most-recent `Location` row for any device owned by that user
- Haversine distance from that location to the waypoint centre
- If distance ≤ waypoint.radius → **inside**
- If distance > waypoint.radius → **outside**
- No location on record → **unknown** (treated as **outside** for both
  `all_inside` and `all_outside` conditions)

This is entirely server-computed and does not rely on OwnTracks reporting a
`_type: transition` message.

### 3. Trigger
Global automation rules are re-evaluated **only when a new location update
(`_type: location`) is saved** for a device whose owner is in the rule's
watched user list.

`_type: transition` messages and waypoint syncs do **not** trigger evaluation —
only a fresh location fix does. This ensures the state check always uses a
GPS position reported by the device, not a phone-side geofence event.

### 4. Fire-once per state transition
A rule fires once when the condition changes from _not met_ to _met_.
It will not fire again until the condition resets (goes back to _not met_) and
then becomes _met_ again.

`GlobalAutomationRule.last_condition_met` (nullable bool) tracks this:
- `None` — never evaluated
- `False` — last evaluation: condition not met
- `True` — last evaluation: condition was met (rule fired); won't fire again
  until this resets to `False`

### 5. Independent actions
Email and webhook actions are independent. A webhook failure does not prevent
the email from being sent and vice versa.

---

## New model: `GlobalAutomationRule`

```python
class GlobalAutomationRule(models.Model):
    CONDITION_ALL_INSIDE  = 'all_inside'
    CONDITION_ALL_OUTSIDE = 'all_outside'
    CONDITION_CHOICES = [
        ('all_inside',  'All users inside'),
        ('all_outside', 'All users outside'),
    ]

    ACTION_EMAIL   = 'email'
    ACTION_WEBHOOK = 'webhook'
    ACTION_CHOICES = [
        ('email',   'Email'),
        ('webhook', 'Webhook'),
    ]

    name          = CharField(max_length=200)
    created_by    = FK(User, related_name='global_automation_rules_created')
    waypoint      = FK(Waypoint, on_delete=CASCADE)
    condition     = CharField(choices=CONDITION_CHOICES)
    users         = ManyToManyField(User, related_name='global_automation_rules')
    action_type   = CharField(choices=ACTION_CHOICES)
    email_address = EmailField(blank=True)
    webhook_url   = URLField(blank=True)
    is_active     = BooleanField(default=True)
    last_condition_met = BooleanField(null=True, default=None)
    created_at    = DateTimeField(auto_now_add=True)
    updated_at    = DateTimeField(auto_now=True)
```

One migration (`0007_add_global_automation_rule.py`).

---

## State evaluation logic

### `_get_user_geofence_state(user, waypoint) → str`

```
latest_loc = Location.objects
    .filter(device__owner=user)
    .order_by('-timestamp')
    .first()

if latest_loc is None:
    return 'unknown'

dist = haversine_m(latest_loc.lat, latest_loc.lon,
                   waypoint.lat, waypoint.lon)
return 'inside' if dist <= waypoint.radius else 'outside'
```

### `_evaluate_global_automations_for_user(user)`

```
rules = GlobalAutomationRule.objects
    .filter(is_active=True, users=user)
    .prefetch_related('users')
    .select_related('waypoint')

for rule in rules:
    states = [_get_user_geofence_state(u, rule.waypoint)
              for u in rule.users.all()]

    if rule.condition == 'all_inside':
        condition_met = all(s == 'inside' for s in states)
    else:  # all_outside
        condition_met = all(s in ('outside', 'unknown') for s in states)

    if condition_met and not rule.last_condition_met:
        # Fire
        if rule.action_type == 'email' and rule.email_address:
            try: send_global_automation_email(rule, user, states_dict)
            except: logger.exception(...)
        if rule.action_type == 'webhook' and rule.webhook_url:
            try: fire_global_automation_webhook(rule, user, states_dict)
            except: logger.exception(...)
        GlobalAutomationRule.objects.filter(pk=rule.pk)
            .update(last_condition_met=True)

    elif not condition_met and rule.last_condition_met:
        # Reset so rule can fire again next time condition is met
        GlobalAutomationRule.objects.filter(pk=rule.pk)
            .update(last_condition_met=False)
```

### Integration point in `app/mqtt/plugin.py`

After the location row is committed in `save_location_to_db` (and **only**
there — not in `save_transition_to_db`):

```python
owner = device.owner
if owner is not None:
    _evaluate_global_automations_for_user(owner)
```

---

## New notification functions (`app/notifications.py`)

### `send_global_automation_email(rule, triggered_by_user, states_dict)`

- Subject: `[my-tracks] {rule.name} — {condition_label}`
- Body:
  ```
  Global automation rule "{rule.name}" fired.

    Condition:   All users {inside|outside} {waypoint.label}
    Triggered by: {triggered_by_user.username}

    User states:
      {username}: inside / outside / unknown
      ...

    Sent at:  LOCAL (UTC)
    Sent by:  {public_domain | smtp_host}
  ```
- Follows `docs/EMAIL_GUIDELINES.md` (subject prefix, `Sent at:`, `Sent by:`).

### `fire_global_automation_webhook(rule, triggered_by_user, states_dict)`

- HTTP POST via `urllib.request` (no new dependency)
- Timeout: 5 seconds
- JSON body:
  ```json
  {
    "rule_name": "...",
    "condition": "all_inside" | "all_outside",
    "waypoint": {"label": "...", "lat": 0, "lon": 0, "radius": 100},
    "users_state": {"username": "inside" | "outside" | "unknown"},
    "triggered_by": "username",
    "timestamp": "ISO8601 UTC"
  }
  ```

---

## Admin UI additions (`/admin-panel/`)

Three new collapsible sections appended after existing content:

### Section A: All Geofences (read-only)
Table: Owner | Name | Lat | Lon | Radius | Active | Created

### Section B: All Transitions (read-only, newest 50)
Table: Owner | Device | Event | Geofence | Time

### Section C: Global Automation Rules
- Table listing all rules with: Name | Geofence | Condition | Users | Action | Active | Delete
- "Add Rule" form:
  - Name (text)
  - Geofence (select — all waypoints from all users, labelled `owner / name`)
  - Condition (radio: All inside / All outside)
  - Users (multi-select — all active users)
  - Action type (toggle: Email / Webhook)
  - Email address (shown when action=email)
  - Webhook URL (shown when action=webhook)
- Per-rule: Delete button + Active toggle

### POST handlers (`form_type` pattern, same as existing admin panel)
- `add_global_rule` — validate + create
- `delete_global_rule` — get_object_or_404 + delete
- `toggle_global_rule` — flip is_active

---

## File change summary

| File | Change |
|---|---|
| `app/models.py` | Add `GlobalAutomationRule` model |
| `app/migrations/0007_add_global_automation_rule.py` | New migration |
| `app/mqtt/plugin.py` | Add `_get_user_geofence_state`, `_evaluate_global_automations_for_user`; call from `save_location_to_db` |
| `app/notifications.py` | Add `send_global_automation_email`, `fire_global_automation_webhook` |
| `web_ui/views.py` | Extend `admin_panel`: 3 new GET context items + 3 POST form_type handlers |
| `web_ui/templates/web_ui/admin_panel.html` | 3 new sections |
| `docs/EMAIL_GUIDELINES.md` | Add 4th sender: `send_global_automation_email` |
| `tests/python/test_web_ui.py` | Admin panel section tests |
| `tests/python/test_plugin.py` | State eval + fire logic tests |

---

## Test cases

### State evaluation
- `_get_user_geofence_state` with no location → `'unknown'`
- `_get_user_geofence_state` with location inside radius → `'inside'`
- `_get_user_geofence_state` with location outside radius → `'outside'`
- Uses most-recent location when user has multiple devices

### Rule evaluation
- `all_inside`: all users inside → fires; one user outside → doesn't fire
- `all_outside`: all users outside → fires; one user inside → doesn't fire
- `unknown` treated as outside for both conditions
- Already-met condition (`last_condition_met=True`) → does not re-fire
- Condition resets to `False` when no longer met → fires again next time

### Admin panel
- GET: all-geofences table shows rows from all users
- GET: all-transitions shows newest 50
- GET: global rules table renders
- POST `add_global_rule`: staff succeeds; non-staff gets 403
- POST `delete_global_rule`: staff succeeds
- POST `toggle_global_rule`: flips is_active

### Email / webhook
- `send_global_automation_email`: subject prefix, Sent at, Sent by
- `fire_global_automation_webhook`: correct JSON payload
- Webhook failure does not prevent email being sent

---

## Quality gate order

1. `uv run pyright`
2. `uv run ruff check app config web_ui`
3. `uv run ruff format --check app config web_ui`
4. `uv run manage.py makemigrations --check --dry-run`
5. `uv run pytest` (≥ 90% coverage)
