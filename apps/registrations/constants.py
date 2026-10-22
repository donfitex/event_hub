from django.db import models


class RegistrationStatus(models.TextChoices):
    REGISTERED = "REGISTERED", "Registered"
    CANCELLED = "CANCELLED", "Cancelled"
    WAITLISTED = "WAITLISTED", "Waitlisted"


ACTIVE_STATUSES = (RegistrationStatus.REGISTERED, RegistrationStatus.WAITLISTED)