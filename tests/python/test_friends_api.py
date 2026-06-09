"""Tests for the Friends API: FriendRequestViewSet, FriendViewSet, DeviceShareViewSet."""

from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from hamcrest import assert_that, equal_to, has_length
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Device, DeviceShare, FriendRequest


@pytest.fixture
def alice(db: Any) -> User:
    return User.objects.create_user(username="alice", password="pass")


@pytest.fixture
def bob(db: Any) -> User:
    return User.objects.create_user(username="bob", password="pass")


@pytest.fixture
def charlie(db: Any) -> User:
    return User.objects.create_user(username="charlie", password="pass")


@pytest.fixture
def alice_client(alice: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=alice)
    return c


@pytest.fixture
def bob_client(bob: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=bob)
    return c


@pytest.fixture
def alice_device(alice: User) -> Device:
    return Device.objects.create(device_id="alice-phone", name="Alice Phone", owner=alice)


@pytest.fixture
def accepted_request(alice: User, bob: User) -> FriendRequest:
    return FriendRequest.objects.create(from_user=alice, to_user=bob, status=FriendRequest.ACCEPTED)


class TestFriendRequestAPI:
    def test_send_request_success(self, alice_client: APIClient, bob: User) -> None:
        response = alice_client.post("/api/friends/requests/", {"username": "bob"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data["status"], equal_to("pending"))

    def test_send_request_to_self_returns_400(self, alice_client: APIClient, alice: User) -> None:
        response = alice_client.post("/api/friends/requests/", {"username": "alice"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

    def test_send_request_to_unknown_user_returns_404(self, alice_client: APIClient) -> None:
        response = alice_client.post("/api/friends/requests/", {"username": "nobody"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_send_duplicate_pending_returns_409(self, alice_client: APIClient, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = alice_client.post("/api/friends/requests/", {"username": "bob"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))

    def test_send_request_when_already_friends_returns_409(
        self, alice_client: APIClient, accepted_request: FriendRequest
    ) -> None:
        response = alice_client.post("/api/friends/requests/", {"username": "bob"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))

    def test_rerequest_after_decline_is_allowed(self, alice_client: APIClient, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob, status=FriendRequest.DECLINED)
        response = alice_client.post("/api/friends/requests/", {"username": "bob"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))

    def test_list_pending_received_requests(self, bob_client: APIClient, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = bob_client.get("/api/friends/requests/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["received"], has_length(1))
        assert_that(response.data["received"][0]["from_user"], equal_to("alice"))
        assert_that(response.data["sent"], has_length(0))

    def test_list_pending_sent_requests(self, alice_client: APIClient, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = alice_client.get("/api/friends/requests/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["sent"], has_length(1))
        assert_that(response.data["sent"][0]["to_user"], equal_to("bob"))
        assert_that(response.data["received"], has_length(0))

    def test_list_does_not_include_accepted(self, bob_client: APIClient, accepted_request: FriendRequest) -> None:
        response = bob_client.get("/api/friends/requests/")
        assert_that(response.data["received"], has_length(0))
        assert_that(response.data["sent"], has_length(0))

    def test_accept_request_success(self, bob_client: APIClient, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = bob_client.post(f"/api/friends/requests/{req.id}/accept/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["status"], equal_to("accepted"))

    def test_accept_with_reciprocal_request(self, bob_client: APIClient, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = bob_client.post(
            f"/api/friends/requests/{req.id}/accept/",
            {"auto_accept_reciprocal": True},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        reciprocal = FriendRequest.objects.get(from_user=bob, to_user=alice)
        assert_that(reciprocal.status, equal_to(FriendRequest.ACCEPTED))
        assert_that(reciprocal.auto_accept_reciprocal, equal_to(True))

    def test_send_request_emails_recipient(self, alice_client: APIClient, bob: User) -> None:
        bob.email = "bob@example.com"
        bob.save()
        with patch("app.notifications.send_friend_request_email") as mock_send:
            response = alice_client.post("/api/friends/requests/", {"username": "bob"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        mock_send.assert_called_once()

    def test_accept_request_by_sender_returns_404(self, alice_client: APIClient, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = alice_client.post(f"/api/friends/requests/{req.id}/accept/")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_decline_request_success(self, bob_client: APIClient, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = bob_client.post(f"/api/friends/requests/{req.id}/decline/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["status"], equal_to("declined"))

    def test_cancel_sent_request_success(self, alice_client: APIClient, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = alice_client.delete(f"/api/friends/requests/{req.id}/")
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(FriendRequest.objects.count(), equal_to(0))

    def test_cancel_others_request_returns_404(self, bob_client: APIClient, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        response = bob_client.delete(f"/api/friends/requests/{req.id}/")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_unauthenticated_returns_401(self) -> None:
        client = APIClient()
        response = client.get("/api/friends/requests/")
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_send_with_auto_accept_accepts_incoming_pending(
        self, alice_client: APIClient, alice: User, bob: User
    ) -> None:
        incoming = FriendRequest.objects.create(from_user=bob, to_user=alice)
        response = alice_client.post(
            "/api/friends/requests/",
            {"username": "bob", "auto_accept_reciprocal": True},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["status"], equal_to("accepted"))
        incoming.refresh_from_db()
        assert_that(incoming.status, equal_to(FriendRequest.ACCEPTED))

    def test_send_with_reciprocal_preauth_stored_on_outgoing(self, alice_client: APIClient, bob: User) -> None:
        response = alice_client.post(
            "/api/friends/requests/",
            {"username": "bob", "auto_accept_reciprocal": True},
            format="json",
        )
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        req = FriendRequest.objects.get(from_user__username="alice", to_user=bob)
        assert_that(req.auto_accept_reciprocal, equal_to(True))

    def test_reciprocal_preauth_accepts_when_other_user_sends_later(
        self, alice_client: APIClient, bob_client: APIClient, alice: User, bob: User
    ) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob, auto_accept_reciprocal=True)
        response = bob_client.post("/api/friends/requests/", {"username": "alice"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data["status"], equal_to("accepted"))


class TestFriendViewSet:
    def test_list_friends_empty(self, alice_client: APIClient) -> None:
        response = alice_client.get("/api/friends/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(0))

    def test_list_friends_from_sent_request(self, alice_client: APIClient, accepted_request: FriendRequest) -> None:
        response = alice_client.get("/api/friends/")
        assert_that(response.data, has_length(1))
        assert_that(response.data[0]["username"], equal_to("bob"))

    def test_list_friends_from_received_request(self, bob_client: APIClient, accepted_request: FriendRequest) -> None:
        response = bob_client.get("/api/friends/")
        assert_that(response.data, has_length(1))
        assert_that(response.data[0]["username"], equal_to("alice"))

    def test_list_friends_both_directions(
        self,
        alice_client: APIClient,
        alice: User,
        bob: User,
        charlie: User,
    ) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob, status=FriendRequest.ACCEPTED)
        FriendRequest.objects.create(from_user=charlie, to_user=alice, status=FriendRequest.ACCEPTED)
        response = alice_client.get("/api/friends/")
        usernames = {f["username"] for f in response.data}
        assert_that(usernames, equal_to({"bob", "charlie"}))

    def test_remove_friend_success(
        self,
        alice_client: APIClient,
        alice: User,
        bob: User,
        accepted_request: FriendRequest,
    ) -> None:
        response = alice_client.delete(f"/api/friends/{bob.id}/")
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(FriendRequest.objects.count(), equal_to(0))

    def test_remove_friend_cascades_device_shares(
        self,
        alice_client: APIClient,
        alice: User,
        bob: User,
        alice_device: Device,
        accepted_request: FriendRequest,
    ) -> None:
        DeviceShare.objects.create(device=alice_device, shared_with=bob)
        alice_client.delete(f"/api/friends/{bob.id}/")
        assert_that(DeviceShare.objects.count(), equal_to(0))

    def test_remove_non_friend_returns_404(self, alice_client: APIClient, bob: User) -> None:
        response = alice_client.delete(f"/api/friends/{bob.id}/")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

    def test_user_search_returns_prefix_matches(self, alice_client: APIClient, bob: User, charlie: User) -> None:
        response = alice_client.get("/api/friends/user-search/?q=bo")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(1))
        assert_that(response.data[0]["username"], equal_to("bob"))

    def test_user_search_excludes_self_and_existing_friends(
        self, alice_client: APIClient, accepted_request: FriendRequest, charlie: User
    ) -> None:
        response = alice_client.get("/api/friends/user-search/?q=c")
        usernames = {row["username"] for row in response.data}
        assert_that(usernames, equal_to({"charlie"}))


class TestDeviceShareAPI:
    def test_list_shares_empty(
        self,
        alice_client: APIClient,
        bob: User,
        accepted_request: FriendRequest,
    ) -> None:
        response = alice_client.get(f"/api/friends/{bob.id}/shares/")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.data, has_length(0))

    def test_create_share_success(
        self,
        alice_client: APIClient,
        alice_device: Device,
        bob: User,
        accepted_request: FriendRequest,
    ) -> None:
        response = alice_client.post(f"/api/friends/{bob.id}/shares/", {"device_id": "alice-phone"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.data["device_id"], equal_to("alice-phone"))
        assert_that(DeviceShare.objects.count(), equal_to(1))

    def test_create_share_unowned_device_returns_403(
        self,
        alice_client: APIClient,
        bob: User,
        accepted_request: FriendRequest,
    ) -> None:
        Device.objects.create(device_id="bob-phone", name="Bob Phone", owner=bob)
        response = alice_client.post(f"/api/friends/{bob.id}/shares/", {"device_id": "bob-phone"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_create_share_non_friend_returns_403(
        self,
        alice_client: APIClient,
        alice_device: Device,
        bob: User,
    ) -> None:
        response = alice_client.post(f"/api/friends/{bob.id}/shares/", {"device_id": "alice-phone"}, format="json")
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

    def test_delete_share_success(
        self,
        alice_client: APIClient,
        alice_device: Device,
        bob: User,
        accepted_request: FriendRequest,
    ) -> None:
        DeviceShare.objects.create(device=alice_device, shared_with=bob)
        response = alice_client.delete(f"/api/friends/{bob.id}/shares/alice-phone/")
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(DeviceShare.objects.count(), equal_to(0))

    def test_delete_nonexistent_share_returns_404(
        self,
        alice_client: APIClient,
        alice_device: Device,
        bob: User,
        accepted_request: FriendRequest,
    ) -> None:
        response = alice_client.delete(f"/api/friends/{bob.id}/shares/alice-phone/")
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
