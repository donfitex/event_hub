from rest_framework.permissions import SAFE_METHODS, BasePermission

from .validators import user_can_manage_event


class IsEventManager(BasePermission):
    """Object-level: admins manage any event, organizers only their own."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return user_can_manage_event(request.user, obj)