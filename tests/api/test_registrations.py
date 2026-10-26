from datetime import timedelta

import pytest
from django.utils import timezone

from apps.registrations.constants import RegistrationStatus as S
from tests.factories import (
    AdminFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)
from tests.helpers import data, error

pytestmark = pytest.mark.django_db
URL = "/api/v1/registrations/"


class TestListAndDetail:
    def test_requires_authentication(self, api_client):
        response = api_client.get(URL)
        assert response.status_code == 401
        assert error(response)["code"] == "NOT_AUTHENTICATED"

    def test_users_only_see_their_own_registrations(self, auth_client, user):
        mine = RegistrationFactory(user=user)
        RegistrationFactory()  # someone else's
        response = auth_client(user).get(URL)
        assert [row["id"] for row in data(response)] == [mine.pk]
        assert "meta" in response.json()

    def test_the_list_is_the_full_history_newest_first(self, auth_client, user):
        old = RegistrationFactory(user=user, cancelled=True)
        new = RegistrationFactory(user=user)
        from apps.registrations.models import Registration
        Registration.objects.filter(pk=old.pk).update(registered_at=timezone.now() - timedelta(days=1))
        rows = data(auth_client(user).get(URL))
        assert [row["id"] for row in rows] == [new.pk, old.pk]
        assert rows[1]["status"] == "CANCELLED" and rows[1]["cancelled_at"]

    def test_organizers_list_is_still_personal(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        RegistrationFactory(event=event)  # an attendee of the organizer's event
        mine = RegistrationFactory(user=organizer)
        assert [row["id"] for row in data(auth_client(organizer).get(URL))] == [mine.pk]

    def test_detail_is_owner_only(self, auth_client):
        registration = RegistrationFactory()
        assert auth_client(registration.user).get(f"{URL}{registration.pk}/").status_code == 200
        assert auth_client(UserFactory()).get(f"{URL}{registration.pk}/").status_code == 404

    def test_organizers_and_admins_can_open_an_attendees_registration(self, auth_client):
        registration = RegistrationFactory()
        assert auth_client(registration.event.organizer).get(f"{URL}{registration.pk}/").status_code == 200
        assert auth_client(AdminFactory()).get(f"{URL}{registration.pk}/").status_code == 200
        assert auth_client(OrganizerFactory()).get(f"{URL}{registration.pk}/").status_code == 404

    def test_waitlist_position_is_shown(self, auth_client):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        waiting = RegistrationFactory(event=event, waitlisted=True)
        assert data(auth_client(waiting.user).get(f"{URL}{waiting.pk}/"))["waitlist_position"] == 1


class TestFilters:
    def test_status_event_when_and_search(self, auth_client, user):
        upcoming = RegistrationFactory(user=user, event=EventFactory(title="Django Day"))
        past = RegistrationFactory(user=user, event=EventFactory(completed=True, title="Old Gathering"))
        cancelled = RegistrationFactory(user=user, cancelled=True)
        client = auth_client(user)

        def ids(**params):
            return {row["id"] for row in data(client.get(URL, params))}

        assert ids(status="CANCELLED") == {cancelled.pk}
        assert ids(event=upcoming.event_id) == {upcoming.pk}
        assert ids(when="upcoming") == {upcoming.pk}
        assert ids(when="past") == {past.pk}
        assert ids(search="django") == {upcoming.pk}

    def test_sorting_by_event_date(self, auth_client, user):
        now = timezone.now()
        later = RegistrationFactory(user=user, event=EventFactory(start_datetime=now + timedelta(days=30)))
        sooner = RegistrationFactory(user=user, event=EventFactory(start_datetime=now + timedelta(days=5)))
        response = auth_client(user).get(URL, {"ordering": "event__start_datetime"})
        assert [row["id"] for row in data(response)] == [sooner.pk, later.pk]


class TestCancel:
    def test_the_owner_cancels(self, auth_client):
        registration = RegistrationFactory()
        response = auth_client(registration.user).post(f"{URL}{registration.pk}/cancel/")
        assert response.status_code == 200
        result = data(response)
        assert result["status"] == "CANCELLED"
        assert result["cancelled_at"] is not None
        assert result["can_cancel"] is False

    def test_cancelling_twice_is_a_409(self, auth_client):
        registration = RegistrationFactory()
        client = auth_client(registration.user)
        client.post(f"{URL}{registration.pk}/cancel/")
        response = client.post(f"{URL}{registration.pk}/cancel/")
        assert response.status_code == 409
        assert error(response)["code"] == "ALREADY_CANCELLED"

    def test_other_users_get_a_404(self, auth_client):
        registration = RegistrationFactory()
        assert auth_client(UserFactory()).post(f"{URL}{registration.pk}/cancel/").status_code == 404

    def test_anonymous_gets_401(self, api_client):
        assert api_client.post(f"{URL}{RegistrationFactory().pk}/cancel/").status_code == 401

    def test_the_organizer_and_an_admin_can_cancel_an_attendee(self, auth_client):
        first, second = RegistrationFactory(), RegistrationFactory()
        assert auth_client(first.event.organizer).post(f"{URL}{first.pk}/cancel/").status_code == 200
        assert auth_client(AdminFactory()).post(f"{URL}{second.pk}/cancel/").status_code == 200

    def test_another_organizer_cannot(self, auth_client):
        registration = RegistrationFactory()
        assert auth_client(OrganizerFactory()).post(f"{URL}{registration.pk}/cancel/").status_code == 404

    def test_cancelling_after_the_event_started_is_a_409(self, auth_client):
        now = timezone.now()
        event = EventFactory(
            start_datetime=now - timedelta(hours=1),
            end_datetime=now + timedelta(hours=3),
            registration_deadline=now - timedelta(days=1),
        )
        registration = RegistrationFactory(event=event)
        response = auth_client(registration.user).post(f"{URL}{registration.pk}/cancel/")
        assert response.status_code == 409
        assert error(response)["code"] == "CANCELLATION_CLOSED"

    def test_cancelling_promotes_the_next_person_on_the_waitlist(self, auth_client):
        event = EventFactory(capacity=1)
        holder = RegistrationFactory(event=event)
        waiting = RegistrationFactory(event=event, waitlisted=True)
        auth_client(holder.user).post(f"{URL}{holder.pk}/cancel/")
        waiting.refresh_from_db()
        assert waiting.status == S.REGISTERED