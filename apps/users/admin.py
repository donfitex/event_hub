from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.registrations.models import Registration

from .models import Organizer, Role, User


class UserRegistrationInline(admin.TabularInline):
    model = Registration
    fk_name = "user"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ["event", "status", "registered_at", "cancelled_at"]
    readonly_fields = ["event", "status", "registered_at", "cancelled_at"]
    ordering = ["-registered_at"]
    verbose_name_plural = "registrations"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = [
        "email", "first_name", "last_name", "role", "is_active", "is_staff",
        "events_count", "registrations_count", "created_at",
    ]
    list_filter = ["role", "is_active", "is_staff", "created_at"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at", "last_login"]
    inlines = [UserRegistrationInline]
    actions = ["make_organizer", "make_regular_user"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "phone", "bio")}),
        ("Access", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _events=Count("organized_events", distinct=True),
            _registrations=Count("registrations", distinct=True),
        )

    @admin.display(description="Events", ordering="_events")
    def events_count(self, obj):
        return obj._events

    @admin.display(description="Registrations", ordering="_registrations")
    def registrations_count(self, obj):
        return obj._registrations

    @admin.action(description="Make selected users organizers")
    def make_organizer(self, request, queryset):
        updated = (
            queryset.exclude(pk=request.user.pk)
            .filter(role=Role.USER)
            .update(role=Role.ORGANIZER, updated_at=timezone.now())
        )
        self.message_user(request, f"{updated} user(s) are now organizers.")

    @admin.action(description="Set selected organizers back to regular users")
    def make_regular_user(self, request, queryset):
        updated = (
            queryset.exclude(pk=request.user.pk)
            .filter(role=Role.ORGANIZER)
            .update(role=Role.USER, updated_at=timezone.now())
        )
        self.message_user(request, f"{updated} organizer(s) are now regular users.")


@admin.register(Organizer)
class OrganizerAdmin(admin.ModelAdmin):
    """Read-only overview of organizers; edit accounts under Users."""

    list_display = ["email", "first_name", "last_name", "events_link", "published", "attendees"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=Role.ORGANIZER).annotate(
            _events=Count("organized_events", distinct=True),
            _published=Count(
                "organized_events", filter=Q(organized_events__status="PUBLISHED"), distinct=True
            ),
            _attendees=Count(
                "organized_events__registrations",
                filter=Q(organized_events__registrations__status="REGISTERED"),
                distinct=True,
            ),
        )

    @admin.display(description="Events", ordering="_events")
    def events_link(self, obj):
        url = reverse("admin:events_event_changelist")
        return format_html('<a href="{}?organizer__id__exact={}">{}</a>', url, obj.pk, obj._events)

    @admin.display(description="Published", ordering="_published")
    def published(self, obj):
        return obj._published

    @admin.display(description="Registered attendees", ordering="_attendees")
    def attendees(self, obj):
        return obj._attendees

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False