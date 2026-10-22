from rest_framework import serializers

from apps.events.models import Event

from .models import Registration


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

    class Meta:
        model = Registration
        fields = ["id", "event", "user", "status", "registered_at"]
        read_only_fields = fields