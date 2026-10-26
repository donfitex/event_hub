import pytest
from django.core import mail

from apps.registrations.constants import RegistrationStatus
from apps.registrations.services import register_for_event
from tests.factories import EventFactory, RegistrationFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_registration_factory_traits():
    assert RegistrationFactory().status == RegistrationStatus.REGISTERED
    assert RegistrationFactory(waitlisted=True).status == RegistrationStatus.WAITLISTED
    cancelled = RegistrationFactory(cancelled=True)
    assert cancelled.status == RegistrationStatus.CANCELLED
    assert cancelled.cancelled_at is not None


def test_registering_sends_a_confirmation_email(django_capture_on_commit_callbacks):
    user, event = UserFactory(), EventFactory()

    # Emails are sent on commit; this fixture runs those callbacks inside the test transaction.
    with django_capture_on_commit_callbacks(execute=True):
        registration = register_for_event(user, event)

    assert registration.status == RegistrationStatus.REGISTERED
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert event.title in mail.outbox[0].subject