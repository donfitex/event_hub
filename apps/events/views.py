import csv

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.utils import timezone

from apps.registrations.serializers import AttendeeSerializer, RegistrationSerializer

from .serializers import OrganizerEventSerializer  # add to the existing serializers import
from .services import change_event_status

from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action

from apps.common.permissions import IsAdminRole, IsOrganizerRole
from apps.registrations.constants import RegistrationStatus
from apps.registrations.exceptions import RegistrationError
from apps.registrations.serializers import RegistrationSerializer
from apps.registrations.services import register_for_event
from apps.registrations.models import Registration
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

def _csv_safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

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
            ),
            waitlisted_count=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.WAITLISTED),
            ),
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
        if self.action == "register":
            return [IsAuthenticated()]
        return [IsOrganizerRole(), IsEventManager()]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventWriteSerializer
        if self.action == "retrieve":
            return EventDetailSerializer
        if self.action == "register":
            return RegistrationSerializer
        return EventListSerializer

    def _detail(self, event):
        event = self.get_queryset().get(pk=event.pk)
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
    
    @action(detail=True, methods=["post"], url_path="register")
    def register(self, request, pk=None):
        event = self.get_object()  # drafts stay hidden from non-owners (404)
        try:
            registration = register_for_event(request.user, event)
        except RegistrationError as exc:
            return Response(
                {"error": {"code": exc.code, "message": exc.message}},
                status=exc.status_code,
            )
        data = RegistrationSerializer(
            registration, context=self.get_serializer_context()
        ).data
        return Response(data, status=status.HTTP_201_CREATED)
    
    def _attendees(self, request, event):
        qs = (
            Registration.objects.filter(event=event)
            .select_related("user")
            .order_by("registered_at", "id")
        )
        status_param = request.query_params.get("registration_status")
        if status_param:
            qs = qs.filter(status=status_param.upper())
        term = request.query_params.get("attendee", "").strip()
        if term:
            qs = qs.filter(
                Q(user__email__icontains=term)
                | Q(user__first_name__icontains=term)
                | Q(user__last_name__icontains=term)
                | Q(user__phone__icontains=term)
            )
        return qs

    @action(detail=True, methods=["get"], url_path="registrations")
    def registrations(self, request, pk=None):
        event = self.get_object()
        page = self.paginate_queryset(self._attendees(request, event))
        return self.get_paginated_response(AttendeeSerializer(page, many=True).data)

    @action(detail=True, methods=["get"], url_path="registrations/export")
    def export_registrations(self, request, pk=None):
        event = self.get_object()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{event.slug}-attendees.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["Registration ID", "Status", "Full name", "Email", "Phone", "Registered at", "Cancelled at"]
        )
        for r in self._attendees(request, event).iterator():
            row = [
                r.id, r.status, r.user.full_name, r.user.email, r.user.phone,
                r.registered_at.isoformat(),
                r.cancelled_at.isoformat() if r.cancelled_at else "",
            ]
            writer.writerow([_csv_safe(v) for v in row])
        return response

    def _transition(self, request, event, new_status):
        try:
            change_event_status(event, new_status, request.user)
        except DjangoValidationError as exc:
            return Response(
                {"error": {"code": "INVALID_EVENT_STATE", "message": " ".join(exc.messages)}},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self._detail(event))

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._transition(request, self.get_object(), EventStatus.PUBLISHED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_event(self, request, pk=None):
        return self._transition(request, self.get_object(), EventStatus.CANCELLED)

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        qs = self.get_queryset()
        if not request.user.is_admin_role:
            qs = qs.filter(organizer=request.user)
        page = self.paginate_queryset(self.filter_queryset(qs))
        data = OrganizerEventSerializer(
            page, many=True, context=self.get_serializer_context()
        ).data
        return self.get_paginated_response(data)

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        events = (
            Event.objects.all()
            if request.user.is_admin_role
            else Event.objects.filter(organizer=request.user)
        )
        now = timezone.now()
        stats = events.aggregate(
            total_events=Count("id"),
            upcoming_events=Count(
                "id", filter=Q(status=EventStatus.PUBLISHED, start_datetime__gte=now)
            ),
            published_events=Count("id", filter=Q(status=EventStatus.PUBLISHED)),
            completed_events=Count("id", filter=Q(status=EventStatus.COMPLETED)),
            draft_events=Count("id", filter=Q(status=EventStatus.DRAFT)),
            cancelled_events=Count("id", filter=Q(status=EventStatus.CANCELLED)),
        )
        registrations = Registration.objects.filter(event__in=events)
        stats["total_registrations"] = registrations.registered().count()
        stats["waitlisted_registrations"] = registrations.waitlisted().count()
        return Response(stats)