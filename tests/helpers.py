from contextlib import contextmanager

from datetime import timedelta

from django.utils import timezone

import pytest

from apps.registrations.exceptions import RegistrationError


@contextmanager
def expect_error(code, status=409):
    """Assert that the block raises RegistrationError with this code and HTTP status."""
    with pytest.raises(RegistrationError) as exc_info:
        yield
    assert exc_info.value.code == code
    assert exc_info.value.status_code == status


def data(response):
    return response.json()["data"]


def error(response):
    return response.json()["error"]


def event_payload(category, **overrides):
    """A valid JSON body for creating or fully replacing an event."""
    start = timezone.now() + timedelta(days=30)
    payload = {
        "title": "Django Workshop 2026",
        "description": "A hands-on workshop for beginners.",
        "category": category.pk,
        "location": "Lagos",
        "venue": "Yaba Tech Hub",
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(hours=4)).isoformat(),
        "registration_deadline": (start - timedelta(days=1)).isoformat(),
        "capacity": 50,
    }
    payload.update(overrides)
    return payload