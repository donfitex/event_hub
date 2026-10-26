import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.registrations.constants import RegistrationStatus
from apps.registrations.models import Registration

from .events import EventFactory
from .users import UserFactory


class RegistrationFactory(DjangoModelFactory):
    class Meta:
        model = Registration

    user = factory.SubFactory(UserFactory)
    event = factory.SubFactory(EventFactory)
    status = RegistrationStatus.REGISTERED

    class Params:
        waitlisted = factory.Trait(status=RegistrationStatus.WAITLISTED)
        cancelled = factory.Trait(
            status=RegistrationStatus.CANCELLED,
            cancelled_at=factory.LazyFunction(timezone.now),
        )