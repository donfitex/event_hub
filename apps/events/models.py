from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.common.models import TimeStampedModel


class EventStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"


class Event(TimeStampedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_events",
    )
    location = models.CharField(max_length=200, help_text="City or area, e.g. Lagos")
    venue = models.CharField(max_length=200)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    registration_deadline = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.DRAFT,
    )
    image = models.ImageField(upload_to="events/%Y/%m/", blank=True, null=True)

    class Meta:
        ordering = ["start_datetime"]
        indexes = [
            models.Index(fields=["status", "start_datetime"]),
            models.Index(fields=["organizer", "status"]),
            models.Index(fields=["location"]),
            models.Index(fields=["start_datetime"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_datetime__gt=F("start_datetime")),
                name="event_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(registration_deadline__lte=F("start_datetime")),
                name="event_deadline_not_after_start",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name="event_capacity_positive",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        if self.start_datetime and self.end_datetime and self.end_datetime <= self.start_datetime:
            errors["end_datetime"] = "End must be after start."
        if (
            self.start_datetime
            and self.registration_deadline
            and self.registration_deadline > self.start_datetime
        ):
            errors["registration_deadline"] = "Deadline cannot be after the event starts."
        if self.capacity is not None and self.capacity < 1:
            errors["capacity"] = "Capacity must be at least 1."
        if errors:
            raise ValidationError(errors)

    def _generate_unique_slug(self):
        base = slugify(self.title)[:200] or "event"
        slug, n = base, 2
        while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    @property
    def is_registration_open(self):
        return (
            self.status == EventStatus.PUBLISHED
            and timezone.now() <= self.registration_deadline
        )