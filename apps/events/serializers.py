from rest_framework import serializers

from .models import Category, Event

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "is_active"]
        read_only_fields = ["id", "slug"]
        
        
class OrganizerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()


class _EventAvailabilityMixin(serializers.Serializer):
    registration_count = serializers.SerializerMethodField()
    available_seats = serializers.SerializerMethodField()

    def get_registration_count(self, obj):
        # Annotated by the queryset once the registrations app exists (Commit 11).
        return getattr(obj, "registered_count", 0)

    def get_available_seats(self, obj):
        return max(obj.capacity - self.get_registration_count(obj), 0)


class EventListSerializer(_EventAvailabilityMixin, serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    organizer = OrganizerSerializer(read_only=True)

    class Meta:
        model = Event
        fields = [
            "id", "title", "slug", "category", "organizer", "location", "venue",
            "start_datetime", "end_datetime", "capacity", "available_seats",
            "status", "image",
        ]


class EventDetailSerializer(_EventAvailabilityMixin, serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    organizer = OrganizerSerializer(read_only=True)
    is_registration_open = serializers.BooleanField(read_only=True)
    registration_available = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id", "title", "slug", "description", "category", "organizer",
            "location", "venue", "start_datetime", "end_datetime",
            "registration_deadline", "capacity", "registration_count",
            "available_seats", "is_registration_open", "registration_available",
            "status", "image", "created_at", "updated_at",
        ]

    def get_registration_available(self, obj):
        return obj.is_registration_open and self.get_available_seats(obj) > 0