from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwnerOrReadOnly(BasePermission):
    """Object-level: only the owner may modify. Owner field set per view."""

    owner_field = "owner"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        owner_field = getattr(view, "owner_field", self.owner_field)
        return getattr(obj, owner_field) == request.user
    
class IsOrganizerRole(BasePermission):
    """Authenticated ORGANIZER or ADMIN."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_organizer)


class IsAdminRole(BasePermission):
    """Authenticated ADMIN only."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_admin_role)