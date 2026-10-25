from datetime import timedelta

from django.db.models import Q
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.events.constants import EventStatus
from apps.events.models import Event
from apps.events.validators import user_can_manage_event

from . import notifications
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

def get_waitlist_position(registration):
    """1-based position in the FIFO queue, or None if not waitlisted."""
    if registration.status != RegistrationStatus.WAITLISTED:
        return None
    ahead = (
        Registration.objects.waitlisted()
        .filter(event_id=registration.event_id)
        .filter(
            Q(registered_at__lt=registration.registered_at)
            | Q(registered_at=registration.registered_at, id__lt=registration.id)
        )
        .count()
    )
    return ahead + 1

@transaction.atomic
def register_for_event(user, event):
    """Register user for event (or add to the waitlist if full), atomically."""
    # Lock the event row: concurrent registrations for this event now run one at a time.
    try:
        event = Event.objects.select_for_update().get(pk=event.pk)
    except Event.DoesNotExist:
        raise RegistrationError("EVENT_NOT_FOUND", "Event not found.", 404)

    # Everything below is checked against fresh data while holding the lock.
    ensure_event_open_for_registration(event)

    existing = Registration.objects.active().filter(user=user, event=event).first()
    if existing:
        if existing.status == RegistrationStatus.WAITLISTED:
            raise RegistrationError("ALREADY_WAITLISTED", "You are already on the waitlist for this event.", 409)
        raise RegistrationError("ALREADY_REGISTERED", "You are already registered for this event.", 409)

    # Nobody jumps the queue: fill any free seats from the waitlist first.
    promote_waitlisted(event)

    registered = Registration.objects.registered().filter(event=event).count()
    status = (
        RegistrationStatus.REGISTERED
        if registered < event.capacity
        else RegistrationStatus.WAITLISTED
    )

    try:
        with transaction.atomic():  # savepoint, so a constraint error doesn't poison the outer transaction
            registration = Registration.objects.create(user=user, event=event, status=status)
    except IntegrityError:
        raise RegistrationError("ALREADY_REGISTERED", "You are already registered for this event.", 409)

    if status == RegistrationStatus.WAITLISTED:
        transaction.on_commit(
            lambda: notifications.send_waitlist_joined(
                registration, get_waitlist_position(registration)
            )
        )
    else:
        transaction.on_commit(lambda: notifications.send_registration_confirmed(registration))
    return registration

def cancellation_deadline(event):
    """Last moment a registration for this event can still be cancelled."""
    return event.start_datetime - timedelta(
        hours=settings.REGISTRATION_CANCELLATION_CUTOFF_HOURS
    )


def promote_waitlisted(event):
    """Promote the earliest waitlisted registrations into any free seats (FIFO).

    Must be called inside a transaction that already holds the event row lock.
    Returns the list of promoted registrations.
    """
    if event.status != EventStatus.PUBLISHED:
        return []

    registered = Registration.objects.registered().filter(event=event).count()
    free_seats = event.capacity - registered
    if free_seats <= 0:
        return []

    queue = list(
        Registration.objects.waitlisted()
        .filter(event=event)
        .select_related("user")
        .order_by("registered_at", "id")[:free_seats]
    )
    for registration in queue:
        registration.status = RegistrationStatus.REGISTERED
        registration.save(update_fields=["status", "updated_at"])
    if queue:
        transaction.on_commit(lambda: notifications.send_waitlist_promoted(event, queue))
    return queue


@transaction.atomic
def cancel_registration(registration, cancelled_by):
    """Cancel a registration. Returns (registration, promoted_registrations)."""
    # Same lock order as register_for_event: event row first, then the registration row.
    event = Event.objects.select_for_update().get(pk=registration.event_id)
    registration = Registration.objects.select_for_update().get(pk=registration.pk)

    is_owner = registration.user_id == cancelled_by.id
    if not (is_owner or user_can_manage_event(cancelled_by, event)):
        raise RegistrationError("FORBIDDEN", "You cannot cancel this registration.", 403)

    if registration.status == RegistrationStatus.CANCELLED:
        raise RegistrationError("ALREADY_CANCELLED", "This registration is already cancelled.", 409)

    if timezone.now() >= cancellation_deadline(event):
        raise RegistrationError(
            "CANCELLATION_CLOSED",
            "This registration can no longer be cancelled.",
            409,
        )

    freed_seat = registration.status == RegistrationStatus.REGISTERED
    registration.status = RegistrationStatus.CANCELLED
    registration.cancelled_at = timezone.now()
    registration.save(update_fields=["status", "cancelled_at", "updated_at"])
    by_staff = registration.user_id != cancelled_by.id
    transaction.on_commit(
        lambda: notifications.send_registration_cancelled(registration, event, by_staff)
    )
    promoted = promote_waitlisted(event) if freed_seat else []
    return registration, promoted

def cancel_all_registrations(event):
    """Cancel every active registration of an event. Call while holding the event lock.

    Returns the registrations that were cancelled.
    """
    affected = list(Registration.objects.active().filter(event=event).select_related("user"))
    now = timezone.now()
    Registration.objects.filter(pk__in=[r.pk for r in affected]).update(
        status=RegistrationStatus.CANCELLED,
        cancelled_at=now,
        updated_at=now,
    )
    if affected:
        transaction.on_commit(lambda: notifications.send_event_cancelled(event, affected))
    return affected
