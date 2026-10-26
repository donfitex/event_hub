from datetime import timedelta

import pytest
from django.utils import timezone

from apps.events.models import Event
from apps.registrations.constants import RegistrationStatus as S
from apps.registrations.models import Registration
from tests.factories import (
    AdminFactory,
    CategoryFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)
from tests.helpers import data, error, event_payload

pytestmark = pytest.mark.django_db
URL = "/api/v1/events/"


class TestCreate:
    def test_anonymous_gets_401(self, api_client, category):
        response = api_client.post(URL, event_payload(category), format="json")
        assert response.status_code == 401
        assert error(response)["code"] == "NOT_AUTHENTICATED"

    def test_a_regular_user_gets_403(self, auth_client, user, category):
        response = auth_client(user).post(URL, event_payload(category), format="json")
        assert response.status_code == 403
        assert error(response)["code"] == "PERMISSION_DENIED"

    def test_an_organizer_creates_a_draft_they_own(self, auth_client, organizer, category):
        someone_else = OrganizerFactory()
        response = auth_client(organizer).post(
            URL, event_payload(category, organizer=someone_else.pk), format="json"
        )
        assert response.status_code == 201
        created = data(response)
        assert created["status"] == "DRAFT"
        assert created["slug"] == "django-workshop-2026"
        assert created["organizer"]["id"] == organizer.pk  # the payload's organizer is ignored
        assert (created["registration_count"], created["available_seats"]) == (0, 50)
        assert Event.objects.get(pk=created["id"]).organizer == organizer

    def test_an_admin_can_create(self, auth_client, admin_user, category):
        response = auth_client(admin_user).post(URL, event_payload(category), format="json")
        assert response.status_code == 201

    def test_an_event_can_be_created_already_published(self, auth_client, organizer, category):
        response = auth_client(organizer).post(
            URL, event_payload(category, status="PUBLISHED"), format="json"
        )
        assert response.status_code == 201
        assert data(response)["status"] == "PUBLISHED"

    @pytest.mark.parametrize("status", ["CANCELLED", "COMPLETED"])
    def test_an_event_cannot_be_created_cancelled_or_completed(self, auth_client, organizer, category, status):
        response = auth_client(organizer).post(
            URL, event_payload(category, status=status), format="json"
        )
        assert response.status_code == 422
        assert "status" in error(response)["details"]

    def test_missing_fields_are_a_400(self, auth_client, organizer):
        response = auth_client(organizer).post(URL, {}, format="json")
        assert response.status_code == 400
        assert error(response)["code"] == "VALIDATION_ERROR"
        assert {"title", "description", "category", "start_datetime", "capacity"} <= set(
            error(response)["details"]
        )

    def test_unknown_inactive_and_negative_values_are_a_400(self, auth_client, organizer, category):
        client = auth_client(organizer)
        inactive = CategoryFactory(is_active=False)
        for field, override in [
            ("category", {"category": 999999}),
            ("category", {"category": inactive.pk}),
            ("capacity", {"capacity": -5}),
        ]:
            response = client.post(URL, event_payload(category, **override), format="json")
            assert response.status_code == 400, override
            assert field in error(response)["details"]

    def test_business_rules_are_a_422(self, auth_client, organizer, category):
        client = auth_client(organizer)
        start = timezone.now() + timedelta(days=30)
        past = timezone.now() - timedelta(days=3)
        cases = [
            ("end_datetime", {"start_datetime": start.isoformat(),
                              "end_datetime": (start - timedelta(hours=1)).isoformat()}),
            ("registration_deadline", {"start_datetime": start.isoformat(),
                                       "end_datetime": (start + timedelta(hours=4)).isoformat(),
                                       "registration_deadline": (start + timedelta(hours=1)).isoformat()}),
            ("start_datetime", {"start_datetime": past.isoformat(),
                                "end_datetime": (past + timedelta(hours=4)).isoformat(),
                                "registration_deadline": (past - timedelta(days=1)).isoformat()}),
            ("title", {"title": "ab"}),
            ("capacity", {"capacity": 0}),
        ]
        for field, overrides in cases:
            response = client.post(URL, event_payload(category, **overrides), format="json")
            assert response.status_code == 422, field
            assert error(response)["code"] == "BUSINESS_RULE_VIOLATION", field
            assert field in error(response)["details"], field


class TestUpdate:
    def test_the_owner_can_patch(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, title="Original Title")
        RegistrationFactory.create_batch(2, event=event)
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"title": "New Title Here"}, format="json")
        assert response.status_code == 200
        updated = data(response)
        assert updated["title"] == "New Title Here"
        assert updated["slug"] == event.slug  # URLs stay stable
        assert updated["registration_count"] == 2  # counts are real in write responses

    def test_put_needs_the_full_payload(self, auth_client, organizer, category):
        event = EventFactory(organizer=organizer)
        client = auth_client(organizer)
        assert client.put(f"{URL}{event.pk}/", {"title": "Only a title"}, format="json").status_code == 400
        response = client.put(f"{URL}{event.pk}/", event_payload(category), format="json")
        assert response.status_code == 200
        assert data(response)["capacity"] == 50

    def test_the_organizer_cannot_be_reassigned(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        other = OrganizerFactory()
        auth_client(organizer).patch(f"{URL}{event.pk}/", {"organizer": other.pk}, format="json")
        event.refresh_from_db()
        assert event.organizer == organizer

    def test_who_may_edit(self, auth_client):
        event = EventFactory()
        payload = {"title": "Edited by someone"}
        assert auth_client(OrganizerFactory()).patch(f"{URL}{event.pk}/", payload, format="json").status_code == 403
        assert auth_client(UserFactory()).patch(f"{URL}{event.pk}/", payload, format="json").status_code == 403
        assert auth_client(AdminFactory()).patch(f"{URL}{event.pk}/", payload, format="json").status_code == 200
        assert auth_client(event.organizer).patch(f"{URL}{event.pk}/", payload, format="json").status_code == 200

    def test_anonymous_gets_401(self, api_client):
        event = EventFactory()
        assert api_client.patch(f"{URL}{event.pk}/", {"title": "Nope nope"}, format="json").status_code == 401

    def test_someone_elses_draft_does_not_exist_for_you(self, auth_client):
        draft = EventFactory(draft=True)
        response = auth_client(OrganizerFactory()).patch(f"{URL}{draft.pk}/", {"title": "Sneaky edit"}, format="json")
        assert response.status_code == 404

    def test_forbidden_status_transition_is_a_422(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)  # published
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"status": "DRAFT"}, format="json")
        assert response.status_code == 422
        assert "status" in error(response)["details"]

    def test_a_draft_can_be_published(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, draft=True)
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"status": "PUBLISHED"}, format="json")
        assert response.status_code == 200
        assert data(response)["status"] == "PUBLISHED"

    def test_cancelled_events_cannot_be_edited(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, cancelled=True)
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"title": "Too late now"}, format="json")
        assert response.status_code == 422
        assert error(response)["code"] == "BUSINESS_RULE_VIOLATION"

    def test_capacity_cannot_drop_below_the_registered_count(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, capacity=5)
        RegistrationFactory.create_batch(3, event=event)
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"capacity": 2}, format="json")
        assert response.status_code == 422
        assert "3" in error(response)["details"]["capacity"][0]

    def test_raising_capacity_promotes_the_waitlist(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, capacity=1)
        RegistrationFactory(event=event)
        waiting = RegistrationFactory(event=event, waitlisted=True)
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"capacity": 2}, format="json")
        assert response.status_code == 200
        waiting.refresh_from_db()
        assert waiting.status == S.REGISTERED

    def test_cancelling_through_patch_cancels_the_registrations(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        registered = RegistrationFactory(event=event)
        waitlisted = RegistrationFactory(event=event, waitlisted=True)
        response = auth_client(organizer).patch(f"{URL}{event.pk}/", {"status": "CANCELLED"}, format="json")
        assert response.status_code == 200
        for registration in (registered, waitlisted):
            registration.refresh_from_db()
            assert registration.status == S.CANCELLED


class TestDelete:
    def test_the_owner_can_delete_a_draft(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, draft=True)
        assert auth_client(organizer).delete(f"{URL}{event.pk}/").status_code == 204
        assert not Event.objects.filter(pk=event.pk).exists()

    def test_published_events_must_be_cancelled_instead(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        response = auth_client(organizer).delete(f"{URL}{event.pk}/")
        assert response.status_code == 409
        assert error(response)["code"] == "EVENT_NOT_DELETABLE"
        assert Event.objects.filter(pk=event.pk).exists()

    def test_who_may_delete(self, auth_client, api_client):
        draft = EventFactory(draft=True)
        assert api_client.delete(f"{URL}{draft.pk}/").status_code == 401
        assert auth_client(UserFactory()).delete(f"{URL}{draft.pk}/").status_code == 403
        assert auth_client(OrganizerFactory()).delete(f"{URL}{draft.pk}/").status_code == 404  # hidden draft
        assert auth_client(AdminFactory()).delete(f"{URL}{draft.pk}/").status_code == 204