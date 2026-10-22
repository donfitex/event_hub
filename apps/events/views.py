from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.permissions import IsAdminRole, IsOrganizerRole
from apps.registrations.constants import RegistrationStatus
from django.db.models import Count, Q

from .constants import EventStatus
from .filters import EventFilter
from .models import Category, Event

from .permissions import IsEventManager
from .serializers import (
    CategorySerializer,
    EventDetailSerializer,
    EventListSerializer,
    EventWriteSerializer,
)

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

class EventViewSet(viewsets.ModelViewSet):
    filterset_class = EventFilter
    search_fields = ["title", "description", "venue", "location", "category__name"]
    ordering_fields = ["start_datetime", "created_at", "title", "capacity"]
    ordering = ["start_datetime"]

    def get_queryset(self):
        qs = Event.objects.select_related("category", "organizer").annotate(
            registered_count=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.REGISTERED),
            )
        )
        user = self.request.user
        if user.is_authenticated and user.is_admin_role:
            return qs
        visible = ~Q(status=EventStatus.DRAFT)
        if user.is_authenticated and user.is_organizer:
            visible |= Q(organizer=user)
        return qs.filter(visible)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsOrganizerRole()]
        return [IsOrganizerRole(), IsEventManager()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventWriteSerializer
        if self.action == "retrieve":
            return EventDetailSerializer
        return EventListSerializer

    def _detail(self, event):
        return EventDetailSerializer(event, context=self.get_serializer_context()).data

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save(organizer=request.user)
        return Response(self._detail(event), status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        event = serializer.save()
        return Response(self._detail(event))

    def destroy(self, request, *args, **kwargs):
        event = self.get_object()
        if event.status != EventStatus.DRAFT:
            return Response(
                {"detail": "Only draft events can be deleted. Cancel the event instead."},
                status=status.HTTP_409_CONFLICT,
            )
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)