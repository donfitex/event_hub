from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.events.constants import EventStatus
from apps.events.models import Category, Event
from apps.events.validators import MAX_CAPACITY
from tests.factories import (
    AdminFactory,
    CategoryFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def validation_errors(instance):
    """Run full_clean() and return the error dict (fails the test if nothing is raised)."""
    with pytest.raises(ValidationError) as exc_info:
        instance.full_clean()
    return exc_info.value.message_dict


class TestCategory:
    def test_slug_is_generated_from_the_name(self):
        assert Category.objects.create(name="Web & Mobile").slug == "web-mobile"

    def test_colliding_slugs_get_a_numeric_suffix(self):
        first = Category.objects.create(name="A B")
        second = Category.objects.create(name="A-B")  # slugifies to the same value
        assert (first.slug, second.slug) == ("a-b", "a-b-2")

    def test_names_are_unique(self):
        Category.objects.create(name="Sports")
        with pytest.raises(IntegrityError), transaction.atomic():
            Category.objects.create(name="Sports")

    def test_defaults_and_ordering(self):
        CategoryFactory(name="Zebra")
        CategoryFactory(name="Alpha")
        assert Category.objects.first().is_active
        assert [c.name for c in Category.objects.all()] == ["Alpha", "Zebra"]
        assert str(Category.objects.first()) == "Alpha"

    def test_a_category_with_events_cannot_be_deleted(self):
        event = EventFactory()
        with pytest.raises(ProtectedError):
            event.category.delete()


class TestEventBasics:
    def test_slug_is_generated_and_unique(self):
        slugs = [EventFactory(title="Django Workshop").slug for _ in range(3)]
        assert slugs == ["django-workshop", "django-workshop-2", "django-workshop-3"]

    def test_slug_stays_stable_when_the_title_changes(self):
        event = EventFactory(title="Original Title")
        event.title = "A Completely Different Title"
        event.save()
        assert event.slug == "original-title"

    def test_title_without_sluggable_characters_gets_a_fallback_slug(self):
        assert EventFactory(title="!!!").slug == "event"

    def test_str_and_default_status(self):
        event = EventFactory(title="Tech Summit", status=EventStatus.DRAFT)
        assert str(event) == "Tech Summit"
        assert Event._meta.get_field("status").default == EventStatus.DRAFT

    def test_events_are_ordered_by_start_date(self):
        now = timezone.now()
        later = EventFactory(start_datetime=now + timedelta(days=20))
        sooner = EventFactory(start_datetime=now + timedelta(days=5))
        assert list(Event.objects.all()) == [sooner, later]

    def test_registration_is_open_only_for_published_events_before_the_deadline(self):
        assert EventFactory().is_registration_open
        assert not EventFactory(draft=True).is_registration_open
        assert not EventFactory(cancelled=True).is_registration_open
        assert not EventFactory(closed=True).is_registration_open

    def test_an_organizer_with_events_cannot_be_deleted(self):
        event = EventFactory()
        with pytest.raises(ProtectedError):
            event.organizer.delete()

    def test_an_event_with_registrations_cannot_be_deleted(self):
        event = EventFactory()
        RegistrationFactory(event=event)
        with pytest.raises(ProtectedError):
            event.delete()


class TestEventDatabaseConstraints:
    """These must hold even when validation is bypassed (bulk writes, scripts, bugs)."""

    def test_end_must_be_after_start(self):
        start = timezone.now() + timedelta(days=10)
        with pytest.raises(IntegrityError), transaction.atomic():
            EventFactory(start_datetime=start, end_datetime=start - timedelta(hours=1))

    def test_deadline_cannot_be_after_start(self):
        start = timezone.now() + timedelta(days=10)
        with pytest.raises(IntegrityError), transaction.atomic():
            EventFactory(start_datetime=start, registration_deadline=start + timedelta(hours=1))

    def test_capacity_must_be_positive(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            EventFactory(capacity=0)


class TestEventValidation:
    def test_a_factory_event_is_valid(self):
        EventFactory().full_clean()

    @pytest.mark.parametrize("title", ["", "  ", "ab"])
    def test_title(self, title):
        event = EventFactory()
        event.title = title
        assert "title" in validation_errors(event)

    @pytest.mark.parametrize("description", ["", "too short"])
    def test_description(self, description):
        event = EventFactory()
        event.description = description
        assert "description" in validation_errors(event)

    @pytest.mark.parametrize("location", ["", "x", "12345"])
    def test_location(self, location):
        event = EventFactory()
        event.location = location
        assert "location" in validation_errors(event)

    @pytest.mark.parametrize("venue", ["", "?!", "9"])
    def test_venue(self, venue):
        event = EventFactory()
        event.venue = venue
        assert "venue" in validation_errors(event)

    @pytest.mark.parametrize("capacity", [0, MAX_CAPACITY + 1])
    def test_capacity_limits(self, capacity):
        event = EventFactory()
        event.capacity = capacity
        assert "capacity" in validation_errors(event)

    def test_end_must_be_after_start(self):
        event = EventFactory()
        event.end_datetime = event.start_datetime
        assert "end_datetime" in validation_errors(event)

    def test_deadline_must_not_be_after_start(self):
        event = EventFactory()
        event.registration_deadline = event.start_datetime + timedelta(hours=1)
        assert "registration_deadline" in validation_errors(event)

    def test_deadline_equal_to_start_is_allowed(self):
        event = EventFactory()
        event.registration_deadline = event.start_datetime
        event.full_clean()

    def test_a_new_event_cannot_start_in_the_past(self):
        past = timezone.now() - timedelta(days=2)
        event = EventFactory.build(
            organizer=OrganizerFactory(),
            category=CategoryFactory(),
            start_datetime=past,
            end_datetime=past + timedelta(hours=4),
            registration_deadline=past - timedelta(days=1),
        )
        assert "start_datetime" in validation_errors(event)

    def test_changing_the_start_to_the_past_is_rejected(self):
        event = EventFactory()
        event.start_datetime = timezone.now() - timedelta(days=1)
        assert "start_datetime" in validation_errors(event)

    def test_an_existing_past_event_can_still_be_edited(self):
        event = EventFactory(completed=True)  # started 5 days ago
        event.title = "Updated title for a finished event"
        event.full_clean()

    def test_the_organizer_must_have_an_organizer_role(self):
        event = EventFactory(organizer=UserFactory())  # factories skip validation
        assert "organizer" in validation_errors(event)

    def test_admins_may_organize_events(self):
        EventFactory(organizer=AdminFactory()).full_clean()


class TestPublishingRules:
    def test_a_valid_draft_can_be_published(self):
        event = EventFactory(draft=True)
        event.status = EventStatus.PUBLISHED
        event.full_clean()

    def test_publishing_requires_a_category(self):
        event = EventFactory(draft=True, category=None)
        event.status = EventStatus.PUBLISHED
        assert "category" in validation_errors(event)

    def test_an_event_that_already_started_cannot_be_published(self):
        event = EventFactory(draft=True)
        now = timezone.now()
        Event.objects.filter(pk=event.pk).update(
            start_datetime=now - timedelta(hours=2),
            end_datetime=now + timedelta(hours=2),
            registration_deadline=now - timedelta(days=1),
        )
        event.refresh_from_db()
        event.status = EventStatus.PUBLISHED
        errors = validation_errors(event)
        assert any("already started" in message for message in errors["status"])


class TestStatusTransitionsOnTheModel:
    @pytest.mark.parametrize(
        "old, new",
        [
            (EventStatus.DRAFT, EventStatus.PUBLISHED),
            (EventStatus.DRAFT, EventStatus.CANCELLED),
            (EventStatus.PUBLISHED, EventStatus.CANCELLED),
            (EventStatus.PUBLISHED, EventStatus.COMPLETED),
        ],
    )
    def test_allowed_transitions_validate(self, old, new):
        event = EventFactory(status=old)
        event.status = new
        event.full_clean()

    @pytest.mark.parametrize(
        "old, new",
        [
            (EventStatus.PUBLISHED, EventStatus.DRAFT),
            (EventStatus.DRAFT, EventStatus.COMPLETED),
            (EventStatus.CANCELLED, EventStatus.PUBLISHED),
            (EventStatus.CANCELLED, EventStatus.DRAFT),
            (EventStatus.COMPLETED, EventStatus.PUBLISHED),
            (EventStatus.COMPLETED, EventStatus.CANCELLED),
        ],
    )
    def test_forbidden_transitions_are_rejected(self, old, new):
        event = EventFactory(status=old)
        event.status = new
        assert "status" in validation_errors(event)


class TestCapacityAgainstRegistrations:
    def test_capacity_cannot_drop_below_the_registered_count(self):
        event = EventFactory(capacity=5)
        RegistrationFactory.create_batch(3, event=event)
        event.capacity = 2
        errors = validation_errors(event)
        assert "3" in errors["capacity"][0]

    def test_capacity_may_equal_the_registered_count(self):
        event = EventFactory(capacity=5)
        RegistrationFactory.create_batch(3, event=event)
        event.capacity = 3
        event.full_clean()

    def test_waitlisted_and_cancelled_registrations_do_not_hold_seats(self):
        event = EventFactory(capacity=5)
        RegistrationFactory.create_batch(2, event=event, waitlisted=True)
        RegistrationFactory(event=event, cancelled=True)
        event.capacity = 1
        event.full_clean()