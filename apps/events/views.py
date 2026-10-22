from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsOrganizerRole

from django.db.models import Q

from .constants import EventStatus
from .filters import EventFilter
from .models import Category, Event
from .serializers import CategorySerializer, EventDetailSerializer, EventListSerializer

class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    lookup_field = "slug"

    def get_queryset(self):
        qs = Category.objects.all()
        user = self.request.user
        if user.is_authenticated and user.is_organizer:
            return qs
        return qs.filter(is_active=True)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "destroy":
            return [IsAdminRole()]
        return [IsOrganizerRole()]

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        try:
            category.delete()
        except ProtectedError:
            return Response(
                {"detail": "This category has events and cannot be deleted. Deactivate it instead."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

class EventViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    filterset_class = EventFilter
    search_fields = ["title", "description", "venue", "location", "category__name"]
    ordering_fields = ["start_datetime", "created_at", "title", "capacity"]
    ordering = ["start_datetime"]

    def get_queryset(self):
        qs = Event.objects.select_related("category", "organizer")
        user = self.request.user
        if user.is_authenticated and user.is_admin_role:
            return qs
        visible = ~Q(status=EventStatus.DRAFT)
        if user.is_authenticated and user.is_organizer:
            visible |= Q(organizer=user)
        return qs.filter(visible)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return EventDetailSerializer
        return EventListSerializer