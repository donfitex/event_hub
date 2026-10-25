from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.events.constants import EventStatus
from apps.events.models import Event

from .constants import RegistrationStatus
from .exceptions import RegistrationError
from .models import Registration


def ensure_event_open_for_registration(event):
    """Raise RegistrationError unless the event accepts registrations right now."""
    if event.status == EventStatus.CANCELLED:
        raise RegistrationError("EVENT_CANCELLED", "This event has been cancelled.", 409)
    if event.status == EventStatus.COMPLETED:
        raise RegistrationError("EVENT_COMPLETED", "This event has already taken place.", 409)
    if event.status != EventStatus.PUBLISHED:
        raise RegistrationError("EVENT_NOT_PUBLISHED", "This event is not open for registration.", 409)
    if timezone.now() > event.registration_deadline:
        raise RegistrationError("REGISTRATION_CLOSED", "Registration for this event is closed.", 409)


@transaction.atomic
def register_for_event(user, event):
    """Atomically register `user` for `event`, or raise RegistrationError."""
    # Lock the event row: concurrent registrations for this event now run one at a time.
    try:
        event = Event.objects.select_for_update().get(pk=event.pk)
    except Event.DoesNotExist:
        raise RegistrationError("EVENT_NOT_FOUND", "Event not found.", 404)

    # Everything below is checked against fresh data while holding the lock.
    ensure_event_open_for_registration(event)

    if Registration.objects.active().filter(user=user, event=event).exists():
        raise RegistrationError("ALREADY_REGISTERED", "You are already registered for this event.", 409)

    registered = Registration.objects.registered().filter(event=event).count()
    if registered >= event.capacity:
        raise RegistrationError("EVENT_FULL", "This event is full.", 409)

    try:
        with transaction.atomic():  # savepoint, so a constraint error doesn't poison the outer transaction
            return Registration.objects.create(user=user, event=event)
    except IntegrityError:
        # Last line of defence: the partial unique constraint from Commit 11.
        raise RegistrationError("ALREADY_REGISTERED", "You are already registered for this event.", 409)

@transaction.atomic
def cancel_registration(registration):
    """Cancel a registration. Extended with full rules in Commit 15."""
    # Lock the row so two simultaneous cancel requests can't both succeed.
    registration = Registration.objects.select_for_update().get(pk=registration.pk)

    if registration.status == RegistrationStatus.CANCELLED:
        raise RegistrationError("ALREADY_CANCELLED", "This registration is already cancelled.", 409)

    registration.status = RegistrationStatus.CANCELLED
    registration.cancelled_at = timezone.now()
    registration.save(update_fields=["status", "cancelled_at", "updated_at"])
    return registration
