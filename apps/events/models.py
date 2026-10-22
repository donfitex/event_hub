from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.common.models import TimeStampedModel

from .constants import EventStatus
from .validators import (
    validate_capacity,
    validate_description,
    validate_event_dates,
    validate_location,
    validate_organizer_role,
    validate_status_transition,
    validate_title,
    validate_venue,
)

class Category(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:110] or "category"
            slug, n = base, 2
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

def _check(errors, field, func, *args):
    try:
        func(*args)
    except ValidationError as exc:
        errors.setdefault(field, []).extend(exc.messages)
        
class Event(TimeStampedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField()
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_events",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="events",
        null=True,
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
            models.Index(fields=["category", "start_datetime"]),
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
        original = None
        if self.pk:
            original = (
                Event.objects.filter(pk=self.pk).only("status", "start_datetime").first()
            )

        _check(errors, "title", validate_title, self.title)
        _check(errors, "description", validate_description, self.description)
        _check(errors, "location", validate_location, self.location)
        _check(errors, "venue", validate_venue, self.venue)
        _check(errors, "capacity", validate_capacity, self.capacity)

        # Future-start rule applies to new events and when the start date changes.
        start_changed = original is None or original.start_datetime != self.start_datetime
        for field, message in validate_event_dates(
            self.start_datetime,
            self.end_datetime,
            self.registration_deadline,
            check_future=start_changed,
        ).items():
            errors.setdefault(field, []).append(message)

        if self.organizer_id:
            _check(errors, "organizer", validate_organizer_role, self.organizer)

        if original and original.status != self.status:
            _check(errors, "status", validate_status_transition, original.status, self.status)

        publishing = self.status == EventStatus.PUBLISHED and (
            original is None or original.status != EventStatus.PUBLISHED
        )
        if publishing:
            if not self.category_id:
                errors.setdefault("category", []).append("A category is required to publish.")
            if self.start_datetime and self.start_datetime <= timezone.now():
                errors.setdefault("status", []).append("Cannot publish an event that has already started.")

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