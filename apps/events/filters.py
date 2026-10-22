import django_filters as filters
from django.utils import timezone

from .models import Event


class EventFilter(filters.FilterSet):
    category = filters.CharFilter(field_name="category__slug")
    location = filters.CharFilter(field_name="location", lookup_expr="icontains")
    start_date_after = filters.DateFilter(field_name="start_datetime", lookup_expr="date__gte")
    start_date_before = filters.DateFilter(field_name="start_datetime", lookup_expr="date__lte")
    upcoming = filters.BooleanFilter(method="filter_upcoming")

    class Meta:
        model = Event
        fields = ["status"]

    def filter_upcoming(self, queryset, name, value):
        now = timezone.now()
        if value:
            return queryset.filter(start_datetime__gte=now)
        return queryset.filter(start_datetime__lt=now)