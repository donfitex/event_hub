from django.conf import settings
from django.db import models
from django.db.models import Q

from .constants import ACTIVE_STATUSES, RegistrationStatus


class RegistrationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=ACTIVE_STATUSES)

    def registered(self):
        return self.filter(status=RegistrationStatus.REGISTERED)

    def waitlisted(self):
        return self.filter(status=RegistrationStatus.WAITLISTED)


class Registration(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.REGISTERED,
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RegistrationQuerySet.as_manager()

    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-registered_at"]
        indexes = [
            models.Index(fields=["event", "status", "registered_at"]),
            models.Index(fields=["user", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event"],
                condition=Q(status__in=ACTIVE_STATUSES),
                name="unique_active_registration_per_user_event",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=RegistrationStatus.CANCELLED, cancelled_at__isnull=False)
                    | (~Q(status=RegistrationStatus.CANCELLED) & Q(cancelled_at__isnull=True))
                ),
                name="registration_cancelled_at_matches_status",
            ),
        ]

    def __str__(self):
        return f"{self.user} -> {self.event} ({self.status})"

    @property
    def is_active(self):
        return self.status in ACTIVE_STATUSES