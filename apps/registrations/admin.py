from django.contrib import admin, messages

from .exceptions import RegistrationError
from .models import Registration
from .services import cancel_registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    """Registrations are managed through actions so capacity and waitlist rules always apply."""

    list_display = ["id", "user", "event", "status", "registered_at", "cancelled_at"]
    list_filter = ["status", "event__category", "registered_at"]
    search_fields = [
        "user__email", "user__first_name", "user__last_name", "event__title",
    ]
    ordering = ["-registered_at"]
    date_hierarchy = "registered_at"
    list_select_related = ["user", "event"]
    readonly_fields = ["user", "event", "status", "registered_at", "cancelled_at", "updated_at"]
    actions = ["cancel_selected"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Cancel selected registrations (frees seats, promotes waitlist)")
    def cancel_selected(self, request, queryset):
        done = 0
        for registration in queryset:
            try:
                cancel_registration(registration, request.user)
                done += 1
            except RegistrationError as exc:
                self.message_user(request, f"#{registration.pk}: {exc.message}", messages.ERROR)
        if done:
            self.message_user(request, f"{done} registration(s) cancelled.", messages.SUCCESS)