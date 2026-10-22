from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.events.constants import EventStatus

from .exceptions import RegistrationError
from .models import Registration


def register_for_event(user, event):
    """Register `user` for `event` or raise RegistrationError."""
    if event.status == EventStatus.CANCELLED:
        raise RegistrationError("EVENT_CANCELLED", "This event has been cancelled.", 409)
    if event.status == EventStatus.COMPLETED:
        raise RegistrationError("EVENT_COMPLETED", "This event has already taken place.", 409)
    if event.status != EventStatus.PUBLISHED:
        raise RegistrationError("EVENT_NOT_PUBLISHED", "This event is not open for registration.", 409)

    if timezone.now() > event.registration_deadline:
        raise RegistrationError("REGISTRATION_CLOSED", "Registration for this event is closed.", 409)

    if Registration.objects.active().filter(user=user, event=event).exists():
        raise RegistrationError("ALREADY_REGISTERED", "You are already registered for this event.", 409)

    registered = Registration.objects.registered().filter(event=event).count()
    if registered >= event.capacity:
        raise RegistrationError("EVENT_FULL", "This event is full.", 409)

    try:
        with transaction.atomic():
            return Registration.objects.create(user=user, event=event)
    except IntegrityError:
        # The database constraint caught a duplicate that slipped past the check above.
        raise RegistrationError("ALREADY_REGISTERED", "You are already registered for this event.", 409)