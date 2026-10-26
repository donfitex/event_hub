import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError

from apps.events.constants import EventStatus
from apps.events.services import change_event_status
from apps.registrations.constants import RegistrationStatus as S
from apps.registrations.services import register_for_event
from tests.factories import (
    AdminFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)
from tests.helpers import expect_error

pytestmark = pytest.mark.django_db


class TestChangeEventStatus:
    def test_the_owner_can_publish_a_draft(self):
        event = EventFactory(draft=True)
        updated = change_event_status(event, EventStatus.PUBLISHED, event.organizer)
        updated.refresh_from_db()
        assert updated.status == EventStatus.PUBLISHED

    def test_an_admin_can_publish_any_draft(self):
        event = EventFactory(draft=True)
        assert change_event_status(event, EventStatus.PUBLISHED, AdminFactory()).status == EventStatus.PUBLISHED

    def test_publishing_without_a_category_fails_and_changes_nothing(self):
        event = EventFactory(draft=True, category=None)
        with pytest.raises(ValidationError):
            change_event_status(event, EventStatus.PUBLISHED, event.organizer)
        event.refresh_from_db()
        assert event.status == EventStatus.DRAFT

    def test_forbidden_transition_is_rejected(self):
        event = EventFactory()  # published
        with pytest.raises(ValidationError):
            change_event_status(event, EventStatus.DRAFT, event.organizer)

    def test_another_organizer_is_denied(self):
        event = EventFactory(draft=True)
        with pytest.raises(PermissionDenied):
            change_event_status(event, EventStatus.PUBLISHED, OrganizerFactory())

    def test_a_regular_user_is_denied(self):
        event = EventFactory(draft=True)
        with pytest.raises(PermissionDenied):
            change_event_status(event, EventStatus.PUBLISHED, UserFactory())

    def test_cancelling_a_draft_works_without_registrations(self):
        event = EventFactory(draft=True)
        assert change_event_status(event, EventStatus.CANCELLED, event.organizer).status == EventStatus.CANCELLED

    def test_a_completed_event_cannot_be_cancelled(self):
        event = EventFactory(completed=True)
        with pytest.raises(ValidationError):
            change_event_status(event, EventStatus.CANCELLED, event.organizer)


class TestCancellingAnEvent:
    def test_all_active_registrations_are_cancelled(self):
        event = EventFactory(capacity=1)
        registered = RegistrationFactory(event=event)
        waitlisted = RegistrationFactory(event=event, waitlisted=True)

        change_event_status(event, EventStatus.CANCELLED, event.organizer)

        for registration in (registered, waitlisted):
            registration.refresh_from_db()
            assert registration.status == S.CANCELLED
            assert registration.cancelled_at is not None

    def test_waitlisted_people_are_not_promoted_by_a_cancelled_event(self, django_capture_on_commit_callbacks):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        RegistrationFactory(event=event, waitlisted=True)

        with django_capture_on_commit_callbacks(execute=True):
            change_event_status(event, EventStatus.CANCELLED, event.organizer)

        assert not any("You're in" in m.subject for m in mail.outbox)

    def test_nobody_can_register_for_a_cancelled_event(self):
        event = EventFactory()
        change_event_status(event, EventStatus.CANCELLED, event.organizer)
        with expect_error("EVENT_CANCELLED"):
            register_for_event(UserFactory(), event)