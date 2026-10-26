import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from apps.registrations.services import cancel_all_registrations, promote_waitlisted
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
    waitlist_count = serializers.SerializerMethodField()

    def get_registration_count(self, obj):
        return getattr(obj, "registered_count", 0)

    def get_available_seats(self, obj):
        return max(obj.capacity - self.get_registration_count(obj), 0)

    def get_waitlist_count(self, obj):
        return getattr(obj, "waitlisted_count", 0)


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

class OrganizerEventSerializer(EventListSerializer):
    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + [
            "registration_deadline", "registration_count", "waitlist_count",
        ]

class EventDetailSerializer(_EventAvailabilityMixin, serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    organizer = OrganizerSerializer(read_only=True)
    is_registration_open = serializers.BooleanField(read_only=True)
    registration_available = serializers.SerializerMethodField()
    waitlist_available = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            "id", "title", "slug", "description", "category", "organizer",
            "location", "venue", "start_datetime", "end_datetime",
            "registration_deadline", "capacity", "registration_count",
            "available_seats", "is_registration_open", "registration_available",
            "status", "image", "waitlist_available", "waitlist_count", "created_at", "updated_at",
        ]
        
    def get_waitlist_available(self, obj):
        return obj.is_registration_open and self.get_available_seats(obj) == 0

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
                    "Cancelled or completed events cannot be edited.", code="business_rule"
                )
            candidate = copy.copy(self.instance)
        else:
            candidate = Event(organizer=request.user, status=EventStatus.DRAFT)

        for field, value in attrs.items():
            setattr(candidate, field, value)

        if self.instance is None and attrs.get("status", EventStatus.DRAFT) not in (
            EventStatus.DRAFT,
            EventStatus.PUBLISHED,
        ):
            raise serializers.ValidationError(
                {"status": "New events can only be created as draft or published."},
                code="business_rule",
            )
        # Reuse the model rules from Commit 08 (dates, transitions, publishing).
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict, code="business_rule")
        return attrs
    
    def update(self, instance, validated_data):
        with transaction.atomic():
            Event.objects.select_for_update().get(pk=instance.pk)
            previous_status = instance.status
            instance = super().update(instance, validated_data)
            if instance.status == EventStatus.CANCELLED and previous_status != EventStatus.CANCELLED:
                cancel_all_registrations(instance)
            promote_waitlisted(instance)
        return instance
    