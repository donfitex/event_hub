import pytest

from apps.events.constants import EventStatus
from tests.factories import EventFactory

pytestmark = pytest.mark.django_db


def test_event_factory_builds_a_valid_published_event():
    event = EventFactory()
    event.full_clean()  # passes all the validation rules from Commit 08
    assert event.status == EventStatus.PUBLISHED
    assert event.slug


def test_event_factory_traits():
    assert EventFactory(draft=True).status == EventStatus.DRAFT
    assert EventFactory(cancelled=True).status == EventStatus.CANCELLED
    assert EventFactory(completed=True).status == EventStatus.COMPLETED
    assert not EventFactory(closed=True).is_registration_open