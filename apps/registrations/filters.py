import django_filters as filters
from django.utils import timezone

from .constants import ACTIVE_STATUSES, RegistrationStatus
from .models import Registration


class RegistrationFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=RegistrationStatus.choices)
    event = filters.NumberFilter(field_name="event_id")
    when = filters.ChoiceFilter(
        choices=[("upcoming", "Upcoming"), ("past", "Past")],
        method="filter_when",
    )

    class Meta:
        model = Registration
        fields = []

    def filter_when(self, queryset, name, value):
        now = timezone.now()
        if value == "upcoming":
            return queryset.filter(status__in=ACTIVE_STATUSES, event__start_datetime__gte=now)
        if value == "past":
            return queryset.filter(event__start_datetime__lt=now)
        return queryset