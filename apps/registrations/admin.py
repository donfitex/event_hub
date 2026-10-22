from django.contrib import admin

from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "status", "registered_at", "cancelled_at"]
    list_filter = ["status"]
    search_fields = ["user__email", "event__title"]
    raw_id_fields = ["user", "event"]
    readonly_fields = ["registered_at", "updated_at"]