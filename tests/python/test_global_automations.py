"""Tests for GlobalAutomationRule — model, state eval, plugin integration,
admin panel view, email and webhook notification helpers."""
# pyright: reportMissingParameterType=none
# pyright: reportUnknownParameterType=none
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from app.models import Device, GlobalAutomationRule, Location, SmtpConfig, Waypoint
from app.mqtt.plugin import _evaluate_global_automations_for_user, _get_user_geofence_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LAT_HOME = 51.5
_LON_HOME = -0.1
_RADIUS = 100  # metres


def _make_user(username: str, **kwargs) -> User:
    return User.objects.create_user(username=username, password='pass', **kwargs)


def _make_device(owner: User, device_id: str = 'dev1') -> Device:
    return Device.objects.create(device_id=device_id, name='Device', owner=owner)


def _make_waypoint(user: User, radius: int = _RADIUS) -> Waypoint:
    return Waypoint.objects.create(
        user=user, label='Home',
        latitude=str(_LAT_HOME), longitude=str(_LON_HOME),
        radius=radius,
    )


def _make_location(device: Device, lat: float, lon: float) -> Location:
    from django.utils import timezone
    return Location.objects.create(
        device=device,
        latitude=str(lat), longitude=str(lon),
        altitude='0', accuracy='5',
        timestamp=timezone.now(),
    )


def _make_rule(
    creator: User,
    waypoint: Waypoint,
    users: list[User],
    *,
    condition: str = GlobalAutomationRule.CONDITION_ALL_INSIDE,
    action_type: str = GlobalAutomationRule.ACTION_EMAIL,
    email_address: str = 'notify@example.com',
    webhook_url: str = '',
    is_active: bool = True,
) -> GlobalAutomationRule:
    rule = GlobalAutomationRule.objects.create(
        name='Test Rule',
        created_by=creator,
        waypoint=waypoint,
        condition=condition,
        action_type=action_type,
        email_address=email_address,
        webhook_url=webhook_url,
        is_active=is_active,
    )
    rule.users.set(users)
    return rule


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGlobalAutomationRuleModel:

    def test_str(self) -> None:
        user = _make_user('model-str')
        wp = _make_waypoint(user)
        rule = _make_rule(user, wp, [user])
        assert 'Test Rule' in str(rule)
        assert 'all_inside' in str(rule)

    def test_default_is_active(self) -> None:
        user = _make_user('model-active')
        wp = _make_waypoint(user)
        rule = _make_rule(user, wp, [user])
        assert rule.is_active is True

    def test_default_last_condition_met_is_none(self) -> None:
        user = _make_user('model-lcm')
        wp = _make_waypoint(user)
        rule = _make_rule(user, wp, [user])
        assert rule.last_condition_met is None

    def test_cascade_delete_with_waypoint(self) -> None:
        user = _make_user('model-cascade')
        wp = _make_waypoint(user)
        rule = _make_rule(user, wp, [user])
        rule_pk = rule.pk
        wp.delete()
        assert not GlobalAutomationRule.objects.filter(pk=rule_pk).exists()

    def test_condition_choices(self) -> None:
        user = _make_user('model-cond')
        wp = _make_waypoint(user)
        rule = _make_rule(user, wp, [user], condition=GlobalAutomationRule.CONDITION_ALL_OUTSIDE)
        assert rule.condition == 'all_outside'


# ---------------------------------------------------------------------------
# _get_user_geofence_state
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGetUserGeofenceState:

    def test_unknown_when_no_locations(self) -> None:
        user = _make_user('gug-unknown')
        wp = _make_waypoint(user)
        assert _get_user_geofence_state(user, wp) == 'unknown'

    def test_inside_when_within_radius(self) -> None:
        user = _make_user('gug-inside')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=1000)
        # Same coords → distance 0
        _make_location(device, _LAT_HOME, _LON_HOME)
        assert _get_user_geofence_state(user, wp) == 'inside'

    def test_outside_when_beyond_radius(self) -> None:
        user = _make_user('gug-outside')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10)  # very small radius
        # ~15 km away
        _make_location(device, _LAT_HOME + 0.14, _LON_HOME)
        assert _get_user_geofence_state(user, wp) == 'outside'

    def test_uses_latest_location(self) -> None:
        """The newest location wins even if an older one is inside."""
        import time
        from django.utils import timezone
        user = _make_user('gug-latest')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=1000)
        # Older location — inside
        loc1 = Location.objects.create(
            device=device,
            latitude=str(_LAT_HOME), longitude=str(_LON_HOME),
            altitude='0', accuracy='5',
            timestamp=timezone.now(),
        )
        # Ensure newer timestamp
        time.sleep(0.01)
        # Newer location — far outside
        Location.objects.create(
            device=device,
            latitude=str(_LAT_HOME + 5.0), longitude=str(_LON_HOME),
            altitude='0', accuracy='5',
            timestamp=timezone.now(),
        )
        del loc1
        assert _get_user_geofence_state(user, wp) == 'outside'


# ---------------------------------------------------------------------------
# _evaluate_global_automations_for_user
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEvaluateGlobalAutomations:

    def test_fires_email_when_condition_newly_met(self) -> None:
        user = _make_user('eval-fire')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10000)
        _make_location(device, _LAT_HOME, _LON_HOME)
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        rule = _make_rule(user, wp, [user], condition=GlobalAutomationRule.CONDITION_ALL_INSIDE)

        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage') as mock_msg_cls:
            mock_msg_cls.return_value = MagicMock()
            _evaluate_global_automations_for_user(user)

        mock_msg_cls.assert_called_once()
        rule.refresh_from_db()
        assert rule.last_condition_met is True

    def test_does_not_refire_when_already_met(self) -> None:
        user = _make_user('eval-nofire')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10000)
        _make_location(device, _LAT_HOME, _LON_HOME)
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        rule = _make_rule(user, wp, [user])
        GlobalAutomationRule.objects.filter(pk=rule.pk).update(last_condition_met=True)

        with patch('app.notifications.EmailMessage') as mock_msg_cls:
            _evaluate_global_automations_for_user(user)

        mock_msg_cls.assert_not_called()

    def test_resets_guard_when_condition_no_longer_met(self) -> None:
        user = _make_user('eval-reset')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10)  # small radius
        # User is outside
        _make_location(device, _LAT_HOME + 1.0, _LON_HOME)
        rule = _make_rule(user, wp, [user])
        GlobalAutomationRule.objects.filter(pk=rule.pk).update(last_condition_met=True)

        _evaluate_global_automations_for_user(user)

        rule.refresh_from_db()
        assert rule.last_condition_met is False

    def test_skips_inactive_rules(self) -> None:
        user = _make_user('eval-inactive')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10000)
        _make_location(device, _LAT_HOME, _LON_HOME)
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        _make_rule(user, wp, [user], is_active=False)

        with patch('app.notifications.EmailMessage') as mock_msg_cls:
            _evaluate_global_automations_for_user(user)

        mock_msg_cls.assert_not_called()

    def test_all_outside_condition_treats_unknown_as_outside(self) -> None:
        user1 = _make_user('eval-unk1')
        user2 = _make_user('eval-unk2')
        # user2 has no location — should count as outside
        device1 = _make_device(user1, 'dev-unk1')
        wp = _make_waypoint(user1, radius=10)
        # user1 is outside (far away)
        _make_location(device1, _LAT_HOME + 1.0, _LON_HOME)
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        rule = _make_rule(
            user1, wp, [user1, user2],
            condition=GlobalAutomationRule.CONDITION_ALL_OUTSIDE,
        )

        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage') as mock_msg_cls:
            mock_msg_cls.return_value = MagicMock()
            _evaluate_global_automations_for_user(user1)

        mock_msg_cls.assert_called_once()
        rule.refresh_from_db()
        assert rule.last_condition_met is True

    def test_fires_webhook_when_action_type_is_webhook(self) -> None:
        user = _make_user('eval-webhook')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10000)
        _make_location(device, _LAT_HOME, _LON_HOME)
        rule = _make_rule(
            user, wp, [user],
            action_type=GlobalAutomationRule.ACTION_WEBHOOK,
            webhook_url='https://hooks.example.com/notify',
            email_address='',
        )

        with patch('app.notifications.fire_global_automation_webhook') as mock_webhook:
            _evaluate_global_automations_for_user(user)

        mock_webhook.assert_called_once()

    def test_email_failure_does_not_prevent_state_update(self) -> None:
        user = _make_user('eval-emailfail')
        device = _make_device(user)
        wp = _make_waypoint(user, radius=10000)
        _make_location(device, _LAT_HOME, _LON_HOME)
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        rule = _make_rule(user, wp, [user])

        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage', side_effect=Exception('SMTP fail')):
            # Must not raise
            _evaluate_global_automations_for_user(user)

        rule.refresh_from_db()
        assert rule.last_condition_met is True


# ---------------------------------------------------------------------------
# send_global_automation_email
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendGlobalAutomationEmail:

    @pytest.fixture
    def setup(self):
        user = _make_user('email-u1')
        wp = _make_waypoint(user)
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        rule = _make_rule(user, wp, [user])
        states = {user.username: 'inside'}
        return user, rule, states

    def test_subject_has_my_tracks_prefix(self, setup) -> None:
        from app.notifications import send_global_automation_email
        user, rule, states = setup
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage') as mock_cls:
            mock_cls.return_value = MagicMock()
            send_global_automation_email(rule, user, states)
        subject = mock_cls.call_args[1]['subject']
        assert subject.startswith('[my-tracks]')

    def test_body_contains_sent_at(self, setup) -> None:
        from app.notifications import send_global_automation_email
        user, rule, states = setup
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage') as mock_cls:
            mock_cls.return_value = MagicMock()
            send_global_automation_email(rule, user, states)
        body = mock_cls.call_args[1]['body']
        assert 'Sent at:' in body

    def test_body_contains_sent_by(self, setup) -> None:
        from app.notifications import send_global_automation_email
        user, rule, states = setup
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage') as mock_cls:
            mock_cls.return_value = MagicMock()
            send_global_automation_email(rule, user, states)
        body = mock_cls.call_args[1]['body']
        assert 'Sent by:' in body

    def test_sends_to_rule_email_address(self, setup) -> None:
        from app.notifications import send_global_automation_email
        user, rule, states = setup
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()), \
             patch('app.notifications.EmailMessage') as mock_cls:
            mock_cls.return_value = MagicMock()
            send_global_automation_email(rule, user, states)
        assert mock_cls.call_args[1]['to'] == ['notify@example.com']

    def test_skips_when_no_smtp_config(self, setup) -> None:
        from app.notifications import send_global_automation_email
        user, rule, states = setup
        SmtpConfig.objects.all().delete()
        with patch('app.notifications.EmailMessage') as mock_cls:
            send_global_automation_email(rule, user, states)
        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# fire_global_automation_webhook
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFireGlobalAutomationWebhook:

    def test_posts_json_with_correct_fields(self) -> None:
        from app.notifications import fire_global_automation_webhook
        user = _make_user('wh-u1')
        wp = _make_waypoint(user)
        rule = _make_rule(
            user, wp, [user],
            action_type=GlobalAutomationRule.ACTION_WEBHOOK,
            webhook_url='https://hooks.example.com/notify',
            email_address='',
        )
        states = {user.username: 'inside'}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            fire_global_automation_webhook(rule, user, {str(k): v for k, v in states.items()})

        mock_open.assert_called_once()
        import json
        req = mock_open.call_args[0][0]
        payload = json.loads(req.data)
        assert payload['rule_name'] == 'Test Rule'
        assert payload['condition'] == GlobalAutomationRule.CONDITION_ALL_INSIDE
        assert 'users_state' in payload
        assert payload['triggered_by'] == user.username
        assert 'timestamp' in payload
        assert 'waypoint' in payload

    def test_uses_5s_timeout(self) -> None:
        from app.notifications import fire_global_automation_webhook
        user = _make_user('wh-timeout')
        wp = _make_waypoint(user)
        rule = _make_rule(
            user, wp, [user],
            action_type=GlobalAutomationRule.ACTION_WEBHOOK,
            webhook_url='https://hooks.example.com/notify',
            email_address='',
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_resp) as mock_open:
            fire_global_automation_webhook(rule, user, {str(user.username): 'inside'})

        _, call_kwargs = mock_open.call_args
        assert call_kwargs.get('timeout') == 5


# ---------------------------------------------------------------------------
# Admin panel view — GET
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminPanelGlobalRules:

    def test_admin_sees_global_rules_tab(
        self, admin_user: User, admin_logged_in_client: Client
    ) -> None:
        wp = _make_waypoint(admin_user)
        _make_rule(admin_user, wp, [admin_user])
        response = admin_logged_in_client.get('/admin-panel/')
        assert response.status_code == 200
        assert b'Automations' in response.content

    def test_non_staff_cannot_access_admin_panel(
        self, user: User, logged_in_client: Client
    ) -> None:
        response = logged_in_client.get('/admin-panel/')
        assert response.status_code in (302, 403)

    def test_add_global_rule_post(
        self, admin_user: User, admin_logged_in_client: Client
    ) -> None:
        user2 = _make_user('rule-target')
        wp = _make_waypoint(admin_user)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'add_global_rule',
            'rule_name': 'Test Auto',
            'rule_waypoint_id': str(wp.pk),
            'rule_condition': 'all_inside',
            'rule_user_ids': [str(admin_user.pk), str(user2.pk)],
            'rule_action_type': 'email',
            'rule_email_address': 'out@example.com',
        })
        assert response.status_code in (200, 302)
        assert GlobalAutomationRule.objects.filter(name='Test Auto').exists()

    def test_toggle_global_rule_post(
        self, admin_user: User, admin_logged_in_client: Client
    ) -> None:
        wp = _make_waypoint(admin_user)
        rule = _make_rule(admin_user, wp, [admin_user], is_active=True)
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'toggle_global_rule',
            'rule_id': str(rule.pk),
        })
        rule.refresh_from_db()
        assert rule.is_active is False

    def test_delete_global_rule_post(
        self, admin_user: User, admin_logged_in_client: Client
    ) -> None:
        wp = _make_waypoint(admin_user)
        rule = _make_rule(admin_user, wp, [admin_user])
        rule_pk = rule.pk
        admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'delete_global_rule',
            'rule_id': str(rule_pk),
        })
        assert not GlobalAutomationRule.objects.filter(pk=rule_pk).exists()

    def test_add_rule_requires_name(
        self, admin_user: User, admin_logged_in_client: Client
    ) -> None:
        wp = _make_waypoint(admin_user)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'add_global_rule',
            'rule_name': '',
            'rule_waypoint_id': str(wp.pk),
            'rule_condition': 'all_inside',
            'rule_action_type': 'email',
            'rule_email_address': 'out@example.com',
        })
        assert response.status_code == 200
        assert not GlobalAutomationRule.objects.exists()

    def test_add_rule_requires_email_for_email_action(
        self, admin_user: User, admin_logged_in_client: Client
    ) -> None:
        wp = _make_waypoint(admin_user)
        response = admin_logged_in_client.post('/admin-panel/', {
            'form_type': 'add_global_rule',
            'rule_name': 'No Email',
            'rule_waypoint_id': str(wp.pk),
            'rule_condition': 'all_inside',
            'rule_action_type': 'email',
            'rule_email_address': '',
        })
        assert response.status_code == 200
        assert not GlobalAutomationRule.objects.filter(name='No Email').exists()
