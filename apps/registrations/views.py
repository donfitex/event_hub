from django.db.models import Q

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .exceptions import RegistrationError
from .filters import RegistrationFilter
from .models import Registration
from .serializers import RegistrationSerializer
from .services import cancel_registration


class RegistrationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = RegistrationSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = RegistrationFilter
    search_fields = ["event__title"]
    ordering_fields = ["registered_at", "event__start_datetime"]
    ordering = ["-registered_at"]

    def get_queryset(self):
        user = self.request.user
        qs = Registration.objects.select_related("event", "user")
        if self.action == "list":
            return qs.filter(user=user)  # "my registrations" stays personal
        if user.is_admin_role:
            return qs
        if user.is_organizer:
            return qs.filter(Q(user=user) | Q(event__organizer=user))
        return qs.filter(user=user)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        registration = self.get_object()
        try:
            registration, _promoted = cancel_registration(registration, request.user)
        except RegistrationError:
            registration = self.get_queryset().get(pk=registration.pk)
            return Response(self.get_serializer(registration).data)