from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.registrations.constants import RegistrationStatus as S
from apps.registrations.models import Registration
from tests.factories import EventFactory, RegistrationFactory, UserFactory

pytestmark = pytest.mark.django_db


def make(user, event, status):
    """Create a registration in any status (cancelled ones need their timestamp)."""
    if status == S.CANCELLED:
        return RegistrationFactory(user=user, event=event, cancelled=True)
    return RegistrationFactory(user=user, event=event, status=status)


class TestRegistrationBasics:
    def test_defaults(self):
        registration = RegistrationFactory()
        assert registration.status == S.REGISTERED
        assert registration.registered_at is not None
        assert registration.cancelled_at is None
        assert registration.reminder_sent_at is None

    @pytest.mark.parametrize(
        "status, active",
        [(S.REGISTERED, True), (S.WAITLISTED, True), (S.CANCELLED, False)],
    )
    def test_is_active(self, status, active):
        registration = make(UserFactory(), EventFactory(), status)
        assert registration.is_active is active

    def test_str_mentions_user_event_and_status(self):
        registration = RegistrationFactory()
        text = str(registration)
        assert registration.user.email in text
        assert registration.event.title in text
        assert S.REGISTERED in text

    def test_queryset_helpers(self):
        event = EventFactory()
        registered = RegistrationFactory(event=event)
        waitlisted = RegistrationFactory(event=event, waitlisted=True)
        RegistrationFactory(event=event, cancelled=True)
        assert set(Registration.objects.active()) == {registered, waitlisted}
        assert list(Registration.objects.registered()) == [registered]
        assert list(Registration.objects.waitlisted()) == [waitlisted]

    def test_newest_registrations_come_first(self):
        older = RegistrationFactory()
        newer = RegistrationFactory()
        Registration.objects.filter(pk=older.pk).update(
            registered_at=timezone.now() - timedelta(hours=1)
        )
        assert list(Registration.objects.all()) == [newer, older]

    def test_related_names(self):
        registration = RegistrationFactory()
        assert registration in registration.user.registrations.all()
        assert registration in registration.event.registrations.all()


class TestRelationships:
    def test_an_event_with_registrations_cannot_be_deleted(self):
        registration = RegistrationFactory()
        with pytest.raises(ProtectedError):
            registration.event.delete()

    def test_deleting_a_user_removes_their_registrations(self):
        registration = RegistrationFactory()
        user_id = registration.user_id
        registration.user.delete()
        assert not Registration.objects.filter(user_id=user_id).exists()


class TestDuplicateActiveRegistrations:
    @pytest.mark.parametrize("existing", [S.REGISTERED, S.WAITLISTED])
    @pytest.mark.parametrize("new", [S.REGISTERED, S.WAITLISTED])
    def test_one_active_registration_per_user_and_event(self, existing, new):
        user, event = UserFactory(), EventFactory()
        make(user, event, existing)
        with pytest.raises(IntegrityError), transaction.atomic():
            make(user, event, new)

    @pytest.mark.parametrize("new", [S.REGISTERED, S.WAITLISTED, S.CANCELLED])
    def test_a_cancelled_registration_does_not_block_a_new_one(self, new):
        user, event = UserFactory(), EventFactory()
        make(user, event, S.CANCELLED)
        make(user, event, new)
        assert Registration.objects.filter(user=user, event=event).count() == 2

    def test_history_can_hold_many_cancelled_rows(self):
        user, event = UserFactory(), EventFactory()
        for _ in range(3):
            make(user, event, S.CANCELLED)
        assert Registration.objects.filter(user=user, event=event).count() == 3

    def test_different_users_can_register_for_the_same_event(self):
        event = EventFactory()
        RegistrationFactory(event=event)
        RegistrationFactory(event=event)
        assert event.registrations.count() == 2

    def test_one_user_can_register_for_different_events(self):
        user = UserFactory()
        RegistrationFactory(user=user)
        RegistrationFactory(user=user)
        assert user.registrations.count() == 2


class TestStatusAndCancellationTimestamp:
    def test_cancelled_requires_a_timestamp(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            RegistrationFactory(status=S.CANCELLED)  # cancelled_at missing

    @pytest.mark.parametrize("status", [S.REGISTERED, S.WAITLISTED])
    def test_only_cancelled_rows_may_have_a_timestamp(self, status):
        with pytest.raises(IntegrityError), transaction.atomic():
            RegistrationFactory(status=status, cancelled_at=timezone.now())

    def test_cancelling_properly_works(self):
        registration = RegistrationFactory()
        registration.status = S.CANCELLED
        registration.cancelled_at = timezone.now()
        registration.save()
        registration.refresh_from_db()
        assert registration.status == S.CANCELLED

    def test_reactivating_without_clearing_the_timestamp_is_blocked(self):
        registration = RegistrationFactory(cancelled=True)
        registration.status = S.REGISTERED
        with pytest.raises(IntegrityError), transaction.atomic():
            registration.save()

    def test_reactivating_with_a_cleared_timestamp_is_allowed(self):
        registration = RegistrationFactory(cancelled=True)
        registration.status = S.REGISTERED
        registration.cancelled_at = None
        registration.save()

    def test_waitlisted_to_registered_promotion_keeps_the_original_join_time(self):
        registration = RegistrationFactory(waitlisted=True)
        joined = registration.registered_at
        registration.status = S.REGISTERED
        registration.save()
        registration.refresh_from_db()
        assert registration.registered_at == joined