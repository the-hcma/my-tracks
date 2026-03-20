"""Tests for Phase 10 Step 2: TransitionAction model and email firing."""
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from app.models import (Device, SmtpConfig, Transition, TransitionAction,
                        Waypoint)
from app.mqtt.plugin import save_transition_to_db

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTransitionActionModel:

    def test_str_with_waypoint(self) -> None:
        user = User.objects.create_user(username='ta-str', password='pass')
        wp = Waypoint.objects.create(
            user=user, label='Home', latitude='51.5', longitude='-0.1', radius=100
        )
        action = TransitionAction.objects.create(
            user=user, waypoint=wp, event='enter', email_address='x@example.com'
        )
        s = str(action)
        assert 'Home' in s
        assert 'ta-str' in s

    def test_str_without_waypoint(self) -> None:
        user = User.objects.create_user(username='ta-any', password='pass')
        action = TransitionAction.objects.create(
            user=user, waypoint=None, event='any', email_address='y@example.com'
        )
        assert 'Any' in str(action)

    def test_default_is_active(self) -> None:
        user = User.objects.create_user(username='ta-active', password='pass')
        action = TransitionAction.objects.create(
            user=user, event='any', email_address='z@example.com'
        )
        assert action.is_active is True

    def test_default_action_type_is_email(self) -> None:
        user = User.objects.create_user(username='ta-type', password='pass')
        action = TransitionAction.objects.create(
            user=user, event='any', email_address='z@example.com'
        )
        assert action.action_type == TransitionAction.ACTION_EMAIL


# ---------------------------------------------------------------------------
# send_transition_email
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendTransitionEmail:

    @pytest.fixture
    def setup(self):
        user = User.objects.create_user(
            username='alice', password='pass', first_name='Alice', last_name='Smith'
        )
        device = Device.objects.create(
            device_id='iphone-alice', name="Alice's iPhone", owner=user
        )
        wp = Waypoint.objects.create(
            user=user, label='Home', latitude='51.5', longitude='-0.1', radius=100
        )
        transition = Transition.objects.create(
            device=device, waypoint=wp, event='enter',
            region_id=wp.rid, description='Home',
            timestamp=timezone.now(),
        )
        action = TransitionAction.objects.create(
            user=user, waypoint=wp, event='enter', email_address='notify@example.com'
        )
        SmtpConfig.objects.create(
            pk=1, host='smtp.example.com', port=587,
            from_address='noreply@example.com', use_tls=True,
        )
        return user, device, wp, transition, action

    def test_sends_email_with_correct_subject(self, setup) -> None:
        from app.notifications import send_transition_email
        _, _, _, transition, action = setup
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()):
            with patch('app.notifications.EmailMessage') as mock_msg_cls:
                mock_msg_cls.return_value = MagicMock()
                send_transition_email(transition, action)
        subject = mock_msg_cls.call_args[1]['subject']
        assert '[my-tracks]' in subject
        assert 'entered' in subject
        assert 'Home' in subject

    def test_sends_to_action_email_address(self, setup) -> None:
        from app.notifications import send_transition_email
        _, _, _, transition, action = setup
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()):
            with patch('app.notifications.EmailMessage') as mock_msg_cls:
                mock_msg_cls.return_value = MagicMock()
                send_transition_email(transition, action)
        assert mock_msg_cls.call_args[1]['to'] == ['notify@example.com']

    def test_skips_send_when_no_smtp_config(self, setup) -> None:
        from app.notifications import send_transition_email
        _, _, _, transition, action = setup
        SmtpConfig.objects.filter(pk=1).delete()
        with patch('app.notifications.EmailMessage') as mock_msg_cls:
            send_transition_email(transition, action)
        mock_msg_cls.assert_not_called()

    def test_leave_event_uses_left_verb(self, setup) -> None:
        from app.notifications import send_transition_email
        user, device, wp, _, action = setup
        leave_transition = Transition.objects.create(
            device=device, waypoint=wp, event='leave',
            region_id=wp.rid, description='Home', timestamp=timezone.now(),
        )
        action.event = 'leave'
        action.save()
        with patch('app.notifications.get_smtp_backend', return_value=MagicMock()):
            with patch('app.notifications.EmailMessage') as mock_msg_cls:
                mock_msg_cls.return_value = MagicMock()
                send_transition_email(leave_transition, action)
        subject = mock_msg_cls.call_args[1]['subject']
        assert 'left' in subject


# ---------------------------------------------------------------------------
# Rule matching inside save_transition_to_db
# ---------------------------------------------------------------------------

@pytest.fixture
def owner_device_wp(db):
    user = User.objects.create_user(username='match-user', password='pass')
    device = Device.objects.create(device_id='match-dev', name='Phone', owner=user)
    wp = Waypoint.objects.create(
        user=user, label='Office', latitude='40.7', longitude='-74.0',
        radius=100, rid='rid-match',
    )
    SmtpConfig.objects.create(
        pk=1, host='smtp.example.com', port=587,
        from_address='noreply@example.com', use_tls=True,
    )
    return user, device, wp


@pytest.mark.django_db
class TestTransitionActionRuleMatching:

    def test_enter_rule_fires_on_enter(self, owner_device_wp) -> None:
        user, _, wp = owner_device_wp
        TransitionAction.objects.create(
            user=user, waypoint=wp, event='enter', email_address='e@example.com'
        )
        with patch('app.notifications.send_transition_email') as mock_send:
            save_transition_to_db({
                'device': 'match-dev', 'event': 'enter', 'region_id': 'rid-match',
                'description': 'Office', 'timestamp': timezone.now(),
            })
        assert mock_send.call_count == 1

    def test_enter_rule_does_not_fire_on_leave(self, owner_device_wp) -> None:
        user, _, wp = owner_device_wp
        TransitionAction.objects.create(
            user=user, waypoint=wp, event='enter', email_address='e@example.com'
        )
        with patch('app.notifications.send_transition_email') as mock_send:
            save_transition_to_db({
                'device': 'match-dev', 'event': 'leave', 'region_id': 'rid-match',
                'description': 'Office', 'timestamp': timezone.now(),
            })
        assert mock_send.call_count == 0

    def test_any_waypoint_rule_fires_for_unknown_geofence(self, owner_device_wp) -> None:
        user, _, _ = owner_device_wp
        TransitionAction.objects.create(
            user=user, waypoint=None, event='any', email_address='e@example.com'
        )
        with patch('app.notifications.send_transition_email') as mock_send:
            save_transition_to_db({
                'device': 'match-dev', 'event': 'enter', 'region_id': 'other-rid',
                'description': 'Unknown', 'timestamp': timezone.now(),
            })
        assert mock_send.call_count == 1

    def test_specific_waypoint_rule_skips_different_geofence(self, owner_device_wp) -> None:
        user, _, wp = owner_device_wp
        other_wp = Waypoint.objects.create(
            user=user, label='Home', latitude='51.5', longitude='-0.1', radius=100
        )
        TransitionAction.objects.create(
            user=user, waypoint=other_wp, event='any', email_address='e@example.com'
        )
        with patch('app.notifications.send_transition_email') as mock_send:
            save_transition_to_db({
                'device': 'match-dev', 'event': 'enter', 'region_id': 'rid-match',
                'description': 'Office', 'timestamp': timezone.now(),
            })
        assert mock_send.call_count == 0

    def test_inactive_rule_does_not_fire(self, owner_device_wp) -> None:
        user, _, wp = owner_device_wp
        TransitionAction.objects.create(
            user=user, waypoint=wp, event='any', email_address='e@example.com',
            is_active=False,
        )
        with patch('app.notifications.send_transition_email') as mock_send:
            save_transition_to_db({
                'device': 'match-dev', 'event': 'enter', 'region_id': 'rid-match',
                'description': 'Office', 'timestamp': timezone.now(),
            })
        assert mock_send.call_count == 0

    def test_email_failure_does_not_propagate(self, owner_device_wp) -> None:
        user, _, wp = owner_device_wp
        TransitionAction.objects.create(
            user=user, waypoint=wp, event='any', email_address='e@example.com'
        )
        with patch('app.notifications.send_transition_email', side_effect=Exception('SMTP down')):
            result = save_transition_to_db({
                'device': 'match-dev', 'event': 'enter', 'region_id': 'rid-match',
                'description': 'Office', 'timestamp': timezone.now(),
            })
        assert result is not None
        assert result['event'] == 'enter'


# ---------------------------------------------------------------------------
# View: geofences POST — add/delete action
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGeofencesActionPosts:

    def test_add_action_creates_rule(self, logged_in_client: Client, user: User) -> None:
        wp = Waypoint.objects.create(
            user=user, label='Home', latitude='51.5', longitude='-0.1', radius=100
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'add_action',
            'waypoint_id': wp.pk,
            'event': 'enter',
            'email_address': 'notify@example.com',
        })
        assert response.status_code == 302
        assert TransitionAction.objects.filter(
            user=user, waypoint=wp, email_address='notify@example.com'
        ).exists()

    def test_add_action_null_waypoint(self, logged_in_client: Client, user: User) -> None:
        response = logged_in_client.post('/geofences/', {
            'form_type': 'add_action',
            'waypoint_id': '',
            'event': 'any',
            'email_address': 'all@example.com',
        })
        assert response.status_code == 302
        action = TransitionAction.objects.filter(user=user, email_address='all@example.com').first()
        assert action is not None
        assert action.waypoint is None

    def test_add_action_rejects_other_users_waypoint(self, logged_in_client: Client) -> None:
        other = User.objects.create_user(username='other-ga', password='pass')
        wp = Waypoint.objects.create(
            user=other, label='Other', latitude='51.5', longitude='-0.1', radius=100
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'add_action',
            'waypoint_id': wp.pk,
            'event': 'enter',
            'email_address': 'hack@example.com',
        })
        assert response.status_code == 404

    def test_delete_action_removes_rule(self, logged_in_client: Client, user: User) -> None:
        action = TransitionAction.objects.create(
            user=user, waypoint=None, event='any', email_address='del@example.com'
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'delete_action',
            'action_id': action.pk,
        })
        assert response.status_code == 302
        assert not TransitionAction.objects.filter(pk=action.pk).exists()

    def test_delete_action_returns_404_for_other_user(self, logged_in_client: Client) -> None:
        other = User.objects.create_user(username='other-del', password='pass')
        action = TransitionAction.objects.create(
            user=other, waypoint=None, event='any', email_address='theirs@example.com'
        )
        response = logged_in_client.post('/geofences/', {
            'form_type': 'delete_action',
            'action_id': action.pk,
        })
        assert response.status_code == 404

    def test_get_includes_actions_in_context(self, logged_in_client: Client, user: User) -> None:
        TransitionAction.objects.create(
            user=user, waypoint=None, event='any', email_address='ctx@example.com'
        )
        response = logged_in_client.get('/geofences/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'ctx@example.com' in content
        assert 'Automations' in content
