from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.events.constants import EventStatus
from apps.events.models import Category, Event

from .users import OrganizerFactory


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Category {n}")


class EventFactory(DjangoModelFactory):
    """A valid, published event starting in 10 days. Use traits for other states."""

    class Meta:
        model = Event

    title = factory.Sequence(lambda n: f"Test Event {n}")
    description = "A test event used in automated tests."
    organizer = factory.SubFactory(OrganizerFactory)
    category = factory.SubFactory(CategoryFactory)
    location = "Lagos"
    venue = "Main Hall"
    start_datetime = factory.LazyFunction(lambda: timezone.now() + timedelta(days=10))
    end_datetime = factory.LazyAttribute(lambda o: o.start_datetime + timedelta(hours=4))
    registration_deadline = factory.LazyAttribute(lambda o: o.start_datetime - timedelta(days=1))
    capacity = 10
    status = EventStatus.PUBLISHED

    class Params:
        draft = factory.Trait(status=EventStatus.DRAFT)
        cancelled = factory.Trait(status=EventStatus.CANCELLED)
        completed = factory.Trait(
            status=EventStatus.COMPLETED,
            start_datetime=factory.LazyFunction(lambda: timezone.now() - timedelta(days=5)),
        )
        closed = factory.Trait(
            registration_deadline=factory.LazyFunction(lambda: timezone.now() - timedelta(hours=1)),
        )