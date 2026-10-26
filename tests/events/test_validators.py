from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.events.constants import EventStatus
from apps.events.validators import (
    MAX_CAPACITY,
    user_can_manage_event,
    validate_capacity,
    validate_description,
    validate_event_dates,
    validate_location,
    validate_status_transition,
    validate_title,
    validate_venue,
)
from tests.factories import AdminFactory, EventFactory, OrganizerFactory, UserFactory


class TestFieldValidators:
    @pytest.mark.parametrize("value", ["abc", "  Lagos Tech Meetup  "])
    def test_valid_titles(self, value):
        validate_title(value)

    @pytest.mark.parametrize("value", ["", " ", "ab", "  a  "])
    def test_invalid_titles(self, value):
        with pytest.raises(ValidationError):
            validate_title(value)

    def test_description_needs_ten_characters(self):
        validate_description("0123456789")
        for value in ("", "   ", "too short"):
            with pytest.raises(ValidationError):
                validate_description(value)

    @pytest.mark.parametrize("validator", [validate_location, validate_venue])
    @pytest.mark.parametrize("value", ["Lagos", "Ota", "Yaba Tech Hub", "Hall 2"])
    def test_valid_places(self, validator, value):
        validator(value)

    @pytest.mark.parametrize("validator", [validate_location, validate_venue])
    @pytest.mark.parametrize("value", ["", "x", "12345", "---", "  "])
    def test_invalid_places(self, validator, value):
        with pytest.raises(ValidationError):
            validator(value)

    @pytest.mark.parametrize("value", [1, 50, MAX_CAPACITY])
    def test_valid_capacity(self, value):
        validate_capacity(value)

    @pytest.mark.parametrize("value", [0, -1, MAX_CAPACITY + 1])
    def test_invalid_capacity(self, value):
        with pytest.raises(ValidationError):
            validate_capacity(value)

    def test_none_is_left_to_the_required_field_checks(self):
        for validator in (validate_title, validate_description, validate_location,
                          validate_venue, validate_capacity):
            validator(None)


class TestEventDates:
    now = timezone.now()
    start = now + timedelta(days=10)
    end = start + timedelta(hours=4)
    deadline = start - timedelta(days=1)

    def test_valid_dates_have_no_errors(self):
        assert validate_event_dates(self.start, self.end, self.deadline, check_future=True) == {}

    def test_end_must_be_after_start(self):
        errors = validate_event_dates(self.start, self.start, self.deadline)
        assert list(errors) == ["end_datetime"]

    def test_deadline_cannot_be_after_start(self):
        errors = validate_event_dates(self.start, self.end, self.start + timedelta(minutes=1))
        assert list(errors) == ["registration_deadline"]

    def test_deadline_may_equal_start(self):
        assert validate_event_dates(self.start, self.end, self.start) == {}

    def test_future_rule_applies_only_when_requested(self):
        past = self.now - timedelta(days=2)
        args = (past, past + timedelta(hours=2), past - timedelta(days=1))
        assert validate_event_dates(*args) == {}
        assert "start_datetime" in validate_event_dates(*args, check_future=True)

    def test_several_problems_are_reported_together(self):
        errors = validate_event_dates(
            self.start, self.start - timedelta(hours=1), self.start + timedelta(hours=1)
        )
        assert set(errors) == {"end_datetime", "registration_deadline"}


class TestStatusTransitionValidator:
    @pytest.mark.parametrize(
        "old, new",
        [
            (EventStatus.DRAFT, EventStatus.PUBLISHED),
            (EventStatus.DRAFT, EventStatus.CANCELLED),
            (EventStatus.PUBLISHED, EventStatus.CANCELLED),
            (EventStatus.PUBLISHED, EventStatus.COMPLETED),
            (EventStatus.PUBLISHED, EventStatus.PUBLISHED),  # no change is always fine
        ],
    )
    def test_allowed(self, old, new):
        validate_status_transition(old, new)

    @pytest.mark.parametrize(
        "old, new",
        [
            (EventStatus.PUBLISHED, EventStatus.DRAFT),
            (EventStatus.DRAFT, EventStatus.COMPLETED),
            (EventStatus.CANCELLED, EventStatus.PUBLISHED),
            (EventStatus.CANCELLED, EventStatus.DRAFT),
            (EventStatus.CANCELLED, EventStatus.COMPLETED),
            (EventStatus.COMPLETED, EventStatus.PUBLISHED),
            (EventStatus.COMPLETED, EventStatus.CANCELLED),
            (EventStatus.COMPLETED, EventStatus.DRAFT),
        ],
    )
    def test_not_allowed(self, old, new):
        with pytest.raises(ValidationError):
            validate_status_transition(old, new)


@pytest.mark.django_db
class TestUserCanManageEvent:
    def test_owning_organizer_can_manage(self):
        event = EventFactory()
        assert user_can_manage_event(event.organizer, event)

    def test_other_organizer_cannot(self):
        assert not user_can_manage_event(OrganizerFactory(), EventFactory())

    def test_admin_can_manage_any_event(self):
        assert user_can_manage_event(AdminFactory(), EventFactory())

    def test_regular_user_cannot_even_if_listed_as_organizer(self):
        # e.g. an organizer who was later demoted
        demoted = UserFactory()
        event = EventFactory(organizer=demoted)
        assert not user_can_manage_event(demoted, event)

    def test_anonymous_and_missing_users_cannot(self):
        event = EventFactory()
        assert not user_can_manage_event(AnonymousUser(), event)
        assert not user_can_manage_event(None, event)