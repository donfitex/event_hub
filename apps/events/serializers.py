import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .constants import EventStatus
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
    
class EventWriteSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.filter(is_active=True)
    )
    status = serializers.ChoiceField(choices=EventStatus.choices, required=False)

    class Meta:
        model = Event
        fields = [
            "title", "description", "category", "location", "venue",
            "start_datetime", "end_datetime", "registration_deadline",
            "capacity", "status", "image",
        ]
        extra_kwargs = {"image": {"required": False, "allow_null": True}}

    def validate(self, attrs):
        request = self.context["request"]

        if self.instance is not None:
            if self.instance.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
                raise serializers.ValidationError(
                    "Cancelled or completed events cannot be edited."
                )
            candidate = copy.copy(self.instance)
        else:
            candidate = Event(organizer=request.user, status=EventStatus.DRAFT)

        for field, value in attrs.items():
            setattr(candidate, field, value)

        # Reuse the model rules from Commit 08 (dates, transitions, publishing).
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs