from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "organizer", "status", "start_datetime", "capacity"]
    list_filter = ["status"]
    search_fields = ["title", "venue", "location"]
    readonly_fields = ["slug", "created_at", "updated_at"]