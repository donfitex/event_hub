from django.contrib import admin

from .models import Category, Event


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    readonly_fields = ["slug", "created_at", "updated_at"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "organizer", "status", "start_datetime", "capacity"]
    list_filter = ["status", "category"]
    search_fields = ["title", "venue", "location"]
    readonly_fields = ["slug", "created_at", "updated_at"]