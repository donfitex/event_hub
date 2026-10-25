import math

from django.utils import timezone

from apps.registrations.constants import RegistrationStatus

from .constants import EventStatus


def availability_state(event, registered_count, user_status=None):
    """Return (code, label) describing what a visitor can do with this event."""
    now = timezone.now()
    if event.status == EventStatus.CANCELLED:
        return "cancelled", "Cancelled"
    if event.status == EventStatus.COMPLETED or event.end_datetime <= now:
        return "completed", "Completed"
    if user_status == RegistrationStatus.REGISTERED:
        return "registered", "Already registered"
    if user_status == RegistrationStatus.WAITLISTED:
        return "waitlisted", "On the waitlist"
    if now > event.registration_deadline:
        return "closed", "Registration closed"
    seats = event.capacity - registered_count
    if seats <= 0:
        return "full", "Full"
    if seats <= max(1, math.ceil(event.capacity * 0.2)):
        return "almost", "Almost full"
    return "available", "Available"