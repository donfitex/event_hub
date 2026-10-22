from django.core.exceptions import ValidationError
from django.utils import timezone

from .constants import EventStatus

MAX_CAPACITY = 100_000

ALLOWED_STATUS_TRANSITIONS = {
    EventStatus.DRAFT: {EventStatus.PUBLISHED, EventStatus.CANCELLED},
    EventStatus.PUBLISHED: {EventStatus.CANCELLED, EventStatus.COMPLETED},
    EventStatus.CANCELLED: set(),
    EventStatus.COMPLETED: set(),
}


def validate_title(value):
    if value is not None and len(value.strip()) < 3:
        raise ValidationError("Title must be at least 3 characters.")


def validate_description(value):
    if value is not None and len(value.strip()) < 10:
        raise ValidationError("Description must be at least 10 characters.")


def _validate_place(value, label):
    if value is None:
        return
    value = value.strip()
    if len(value) < 2 or not any(ch.isalpha() for ch in value):
        raise ValidationError(f"Enter a valid {label}.")


def validate_location(value):
    _validate_place(value, "location")


def validate_venue(value):
    _validate_place(value, "venue")


def validate_capacity(value):
    if value is None:
        return
    if value < 1:
        raise ValidationError("Capacity must be at least 1.")
    if value > MAX_CAPACITY:
        raise ValidationError(f"Capacity cannot exceed {MAX_CAPACITY:,}.")


def validate_event_dates(start, end, deadline, check_future=False):
    """Returns a dict of {field: message} for any date rule that fails."""
    errors = {}
    if start and end and end <= start:
        errors["end_datetime"] = "End date must be after the start date."
    if start and deadline and deadline > start:
        errors["registration_deadline"] = "Registration deadline must be before the event starts."
    if check_future and start and start <= timezone.now():
        errors["start_datetime"] = "Start date must be in the future."
    return errors


def validate_status_transition(old_status, new_status):
    if old_status == new_status:
        return
    if new_status not in ALLOWED_STATUS_TRANSITIONS.get(old_status, set()):
        raise ValidationError(
            f"Cannot change status from {old_status} to {new_status}."
        )


def validate_organizer_role(user):
    if user is None or not user.is_organizer:
        raise ValidationError("Only organizers or admins can own events.")


def user_can_manage_event(user, event):
    """Admins manage any event; organizers manage only their own."""
    if not user or not user.is_authenticated:
        return False
    if user.is_admin_role:
        return True
    return user.is_organizer and event.organizer_id == user.id