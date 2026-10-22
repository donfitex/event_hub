from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import Event
from .validators import user_can_manage_event, validate_status_transition


@transaction.atomic
def change_event_status(event, new_status, user):
    """Change an event's status with ownership and transition checks."""
    if not user_can_manage_event(user, event):
        raise PermissionDenied("You do not have permission to manage this event.")

    event = Event.objects.select_for_update().get(pk=event.pk)
    validate_status_transition(event.status, new_status)

    event.status = new_status
    event.full_clean()
    event.save(update_fields=["status", "updated_at"])
    return event