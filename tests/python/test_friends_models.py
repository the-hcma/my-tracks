"""Tests for FriendRequest and DeviceShare models."""
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError
from hamcrest import assert_that, equal_to

from app.models import Device, DeviceShare, FriendRequest


@pytest.fixture
def alice(db: Any) -> User:
    return User.objects.create_user(username="alice", password="pass")


@pytest.fixture
def bob(db: Any) -> User:
    return User.objects.create_user(username="bob", password="pass")


@pytest.fixture
def alice_device(alice: User) -> Device:
    return Device.objects.create(device_id="alice-phone", name="Alice Phone", owner=alice)


class TestFriendRequestModel:
    def test_create_friend_request(self, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        assert_that(req.status, equal_to(FriendRequest.PENDING))
        assert_that(req.from_user, equal_to(alice))
        assert_that(req.to_user, equal_to(bob))

    def test_unique_together_enforced(self, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        with pytest.raises(IntegrityError):
            FriendRequest.objects.create(from_user=alice, to_user=bob)

    def test_reverse_direction_is_separate(self, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        req2 = FriendRequest.objects.create(from_user=bob, to_user=alice)
        assert_that(req2.pk is not None, equal_to(True))

    def test_status_transitions(self, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        req.status = FriendRequest.ACCEPTED
        req.save()
        req.refresh_from_db()
        assert_that(req.status, equal_to(FriendRequest.ACCEPTED))

    def test_str(self, alice: User, bob: User) -> None:
        req = FriendRequest.objects.create(from_user=alice, to_user=bob)
        assert_that("alice" in str(req), equal_to(True))
        assert_that("bob" in str(req), equal_to(True))

    def test_ordering_newest_first(self, alice: User, bob: User) -> None:
        charlie = User.objects.create_user(username="charlie", password="pass")
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        FriendRequest.objects.create(from_user=alice, to_user=charlie)
        requests = list(FriendRequest.objects.filter(from_user=alice))
        assert_that(requests[0].to_user, equal_to(charlie))

    def test_cascade_delete_when_user_deleted(self, alice: User, bob: User) -> None:
        FriendRequest.objects.create(from_user=alice, to_user=bob)
        alice.delete()
        assert_that(FriendRequest.objects.count(), equal_to(0))


class TestDeviceShareModel:
    def test_create_device_share(self, alice_device: Device, bob: User) -> None:
        share = DeviceShare.objects.create(device=alice_device, shared_with=bob)
        assert_that(share.device, equal_to(alice_device))
        assert_that(share.shared_with, equal_to(bob))

    def test_unique_together_enforced(self, alice_device: Device, bob: User) -> None:
        DeviceShare.objects.create(device=alice_device, shared_with=bob)
        with pytest.raises(IntegrityError):
            DeviceShare.objects.create(device=alice_device, shared_with=bob)

    def test_cascade_delete_when_device_deleted(self, alice_device: Device, bob: User) -> None:
        DeviceShare.objects.create(device=alice_device, shared_with=bob)
        alice_device.delete()
        assert_that(DeviceShare.objects.count(), equal_to(0))

    def test_cascade_delete_when_user_deleted(self, alice_device: Device, bob: User) -> None:
        DeviceShare.objects.create(device=alice_device, shared_with=bob)
        bob.delete()
        assert_that(DeviceShare.objects.count(), equal_to(0))

    def test_str(self, alice_device: Device, bob: User) -> None:
        share = DeviceShare.objects.create(device=alice_device, shared_with=bob)
        assert_that("alice-phone" in str(share), equal_to(True))
        assert_that("bob" in str(share), equal_to(True))
