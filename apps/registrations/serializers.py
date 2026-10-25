from rest_framework import serializers

from django.utils import timezone

from apps.events.models import Event

from .models import Registration
from .services import cancellation_deadline
from .services import get_waitlist_position as waitlist_position_for
class RegistrationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "slug", "location", "venue", "start_datetime"]


class RegistrationUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    full_name = serializers.CharField()


class RegistrationSerializer(serializers.ModelSerializer):
    event = RegistrationEventSerializer(read_only=True)
    user = RegistrationUserSerializer(read_only=True)
    can_cancel = serializers.SerializerMethodField()
    waitlist_position = serializers.SerializerMethodField()

    class Meta:
        model = Registration
        fields = [
            "id", "event", "user", "status", "registered_at",
            "cancelled_at", "can_cancel", "waitlist_position",
        ]
        read_only_fields = fields

    def get_can_cancel(self, obj):
        return obj.is_active and timezone.now() < cancellation_deadline(obj.event)

    def get_waitlist_position(self, obj):
        return waitlist_position_for(obj)
    
    
class AttendeeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()


class AttendeeSerializer(serializers.ModelSerializer):
    user = AttendeeUserSerializer(read_only=True)

    class Meta:
        model = Registration
        fields = ["id", "status", "registered_at", "cancelled_at", "user"]
        read_only_fields = fields