from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_future_datetime(value):
    if value <= timezone.now():
        raise ValidationError("Date and time must be in the future.")


def validate_positive_capacity(value):
    if value is None or value < 1:
        raise ValidationError("Capacity must be at least 1.")