from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q

from apps.registrations.constants import RegistrationStatus
from apps.registrations.models import Registration
from apps.registrations.services import cancel_all_registrations, promote_waitlisted
from apps.users.models import Role

from .constants import EventStatus
from .models import Category, Event
from .services import change_event_status

User = get_user_model()


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "events_count"]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]
    ordering = ["name"]
    readonly_fields = ["slug", "created_at", "updated_at"]
    actions = ["activate", "deactivate"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_events=Count("events"))

    @admin.display(description="Events", ordering="_events")
    def events_count(self, obj):
        return obj._events

    @admin.action(description="Activate selected categories")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} category(ies) activated.")

    @admin.action(description="Deactivate selected categories")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} category(ies) deactivated.")


class EventRegistrationInline(admin.TabularInline):
    model = Registration
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ["user", "status", "registered_at", "cancelled_at"]
    readonly_fields = ["user", "status", "registered_at", "cancelled_at"]
    ordering = ["registered_at", "id"]
    verbose_name_plural = "registrations (oldest first)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        "title", "category", "organizer", "status", "start_datetime",
        "location", "capacity", "registered", "waitlisted",
    ]
    list_filter = ["status", "category", "organizer", "start_datetime"]
    search_fields = [
        "title", "description", "venue", "location", "category__name",
        "organizer__email", "organizer__first_name", "organizer__last_name",
    ]
    ordering = ["-start_datetime"]
    date_hierarchy = "start_datetime"
    list_select_related = ["category", "organizer"]
    autocomplete_fields = ["category"]
    readonly_fields = ["slug", "created_at", "updated_at"]
    inlines = [EventRegistrationInline]
    actions = ["publish_events", "cancel_events"]

    fieldsets = (
        ("Basics", {"fields": ("title", "slug", "description", "category", "organizer", "image")}),
        ("Schedule", {"fields": ("location", "venue", "start_datetime", "end_datetime", "registration_deadline")}),
        ("Capacity and status", {"fields": ("capacity", "status")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _registered=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.REGISTERED),
            ),
            _waitlisted=Count(
                "registrations",
                filter=Q(registrations__status=RegistrationStatus.WAITLISTED),
            ),
        )

    @admin.display(description="Registered", ordering="_registered")
    def registered(self, obj):
        return obj._registered

    @admin.display(description="Waitlisted", ordering="_waitlisted")
    def waitlisted(self, obj):
        return obj._waitlisted

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "organizer":
            kwargs["queryset"] = User.objects.filter(
                role__in=[Role.ORGANIZER, Role.ADMIN], is_active=True
            ).order_by("email")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """Keep registrations consistent when status or capacity changes in the form."""
        with transaction.atomic():
            previous_status = None
            if change:
                previous_status = Event.objects.select_for_update().get(pk=obj.pk).status
            super().save_model(request, obj, form, change)
            if change:
                if obj.status == EventStatus.CANCELLED and previous_status != EventStatus.CANCELLED:
                    cancel_all_registrations(obj)
                promote_waitlisted(obj)

    def _transition(self, request, queryset, new_status, done_label):
        done = 0
        for event in queryset:
            try:
                change_event_status(event, new_status, request.user)
                done += 1
            except PermissionDenied:
                self.message_user(request, f"'{event.title}': you cannot manage this event.", messages.ERROR)
            except ValidationError as exc:
                self.message_user(request, f"'{event.title}': {' '.join(exc.messages)}", messages.ERROR)
        if done:
            self.message_user(request, f"{done} event(s) {done_label}.", messages.SUCCESS)

    @admin.action(description="Publish selected events")
    def publish_events(self, request, queryset):
        self._transition(request, queryset, EventStatus.PUBLISHED, "published")

    @admin.action(description="Cancel selected events (cancels their registrations)")
    def cancel_events(self, request, queryset):
        self._transition(request, queryset, EventStatus.CANCELLED, "cancelled")