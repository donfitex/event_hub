import csv
import io

import pytest

from apps.events.models import Event
from apps.registrations.constants import RegistrationStatus as S
from apps.registrations.models import Registration
from tests.factories import (
    AdminFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)
from tests.helpers import data, error

pytestmark = pytest.mark.django_db
URL = "/api/v1/events/"


class TestRegister:
    def test_anonymous_gets_401(self, api_client):
        response = api_client.post(f"{URL}{EventFactory().pk}/register/")
        assert response.status_code == 401

    def test_a_user_registers(self, auth_client, user):
        event = EventFactory()
        response = auth_client(user).post(f"{URL}{event.pk}/register/")
        assert response.status_code == 201
        registration = data(response)
        assert registration["status"] == "REGISTERED"
        assert registration["event"]["id"] == event.pk
        assert registration["user"]["email"] == user.email
        assert registration["can_cancel"] is True
        assert registration["waitlist_position"] is None

    def test_registering_twice_is_a_409(self, auth_client, user):
        event = EventFactory()
        client = auth_client(user)
        client.post(f"{URL}{event.pk}/register/")
        response = client.post(f"{URL}{event.pk}/register/")
        assert response.status_code == 409
        assert error(response)["code"] == "ALREADY_REGISTERED"

    def test_a_full_event_puts_you_on_the_waitlist(self, auth_client, user):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        response = auth_client(user).post(f"{URL}{event.pk}/register/")
        assert response.status_code == 201
        assert data(response)["status"] == "WAITLISTED"
        assert data(response)["waitlist_position"] == 1

    @pytest.mark.parametrize(
        "traits, code",
        [({"closed": True}, "REGISTRATION_CLOSED"), ({"cancelled": True}, "EVENT_CANCELLED"),
         ({"completed": True}, "EVENT_COMPLETED")],
    )
    def test_closed_cancelled_and_completed_events(self, auth_client, user, traits, code):
        event = EventFactory(**traits)
        response = auth_client(user).post(f"{URL}{event.pk}/register/")
        assert response.status_code == 409
        assert error(response)["code"] == code

    def test_someone_elses_draft_is_a_404_but_the_owner_gets_a_clear_error(self, auth_client, user):
        draft = EventFactory(draft=True)
        assert auth_client(user).post(f"{URL}{draft.pk}/register/").status_code == 404
        response = auth_client(draft.organizer).post(f"{URL}{draft.pk}/register/")
        assert response.status_code == 409
        assert error(response)["code"] == "EVENT_NOT_PUBLISHED"

    def test_unknown_event(self, auth_client, user):
        assert auth_client(user).post(f"{URL}999999/register/").status_code == 404


class TestPublishAndCancel:
    def test_the_owner_publishes_a_draft(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, draft=True)
        response = auth_client(organizer).post(f"{URL}{event.pk}/publish/")
        assert response.status_code == 200
        assert data(response)["status"] == "PUBLISHED"

    def test_publishing_without_a_category_is_a_409(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, draft=True, category=None)
        response = auth_client(organizer).post(f"{URL}{event.pk}/publish/")
        assert response.status_code == 409
        assert error(response)["code"] == "INVALID_EVENT_STATE"

    def test_other_users_cannot_publish(self, auth_client):
        event = EventFactory(draft=True)
        assert auth_client(UserFactory()).post(f"{URL}{event.pk}/publish/").status_code == 403
        assert auth_client(OrganizerFactory()).post(f"{URL}{event.pk}/publish/").status_code == 404

    def test_cancelling_an_event_cancels_its_registrations(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        registered = RegistrationFactory(event=event)
        waitlisted = RegistrationFactory(event=event, waitlisted=True)

        response = auth_client(organizer).post(f"{URL}{event.pk}/cancel/")

        assert response.status_code == 200
        assert data(response)["status"] == "CANCELLED"
        assert data(response)["registration_count"] == 0
        for registration in (registered, waitlisted):
            registration.refresh_from_db()
            assert registration.status == S.CANCELLED

    def test_a_completed_event_cannot_be_cancelled(self, auth_client, organizer):
        event = EventFactory(organizer=organizer, completed=True)
        response = auth_client(organizer).post(f"{URL}{event.pk}/cancel/")
        assert response.status_code == 409
        assert error(response)["code"] == "INVALID_EVENT_STATE"

    def test_a_stranger_cannot_cancel_an_event(self, auth_client):
        event = EventFactory()
        assert auth_client(OrganizerFactory()).post(f"{URL}{event.pk}/cancel/").status_code == 403
        assert Event.objects.get(pk=event.pk).status == "PUBLISHED"


class TestDashboard:
    def test_counts_for_an_organizer_ignore_other_organizers(self, auth_client, organizer):
        busy = EventFactory(organizer=organizer, capacity=2)
        RegistrationFactory.create_batch(2, event=busy)
        RegistrationFactory(event=busy, waitlisted=True)
        EventFactory(organizer=organizer)                      # published, no attendees
        EventFactory(organizer=organizer, draft=True)
        EventFactory(organizer=organizer, cancelled=True)
        EventFactory(organizer=organizer, completed=True)
        EventFactory()                                         # someone else's: must not count

        stats = data(auth_client(organizer).get(f"{URL}dashboard/"))

        assert stats == {
            "total_events": 5, "upcoming_events": 2, "published_events": 2,
            "completed_events": 1, "draft_events": 1, "cancelled_events": 1,
            "total_registrations": 2, "waitlisted_registrations": 1,
        }

    def test_an_admin_sees_the_whole_platform(self, auth_client, admin_user):
        EventFactory.create_batch(2)
        EventFactory(draft=True)
        assert data(auth_client(admin_user).get(f"{URL}dashboard/"))["total_events"] == 3

    def test_regular_users_and_anonymous_are_refused(self, auth_client, api_client, user):
        assert auth_client(user).get(f"{URL}dashboard/").status_code == 403
        assert api_client.get(f"{URL}dashboard/").status_code == 401


class TestMyEvents:
    def test_lists_only_own_events_including_drafts(self, auth_client, organizer):
        mine = EventFactory(organizer=organizer)
        my_draft = EventFactory(organizer=organizer, draft=True)
        EventFactory()  # someone else's
        RegistrationFactory(event=mine)
        RegistrationFactory(event=mine, waitlisted=True)

        response = auth_client(organizer).get(f"{URL}mine/")

        rows = {row["id"]: row for row in data(response)}
        assert set(rows) == {mine.pk, my_draft.pk}
        assert rows[mine.pk]["registration_count"] == 1
        assert rows[mine.pk]["waitlist_count"] == 1
        assert "registration_deadline" in rows[mine.pk]

    def test_filtering_by_status(self, auth_client, organizer):
        EventFactory(organizer=organizer)
        draft = EventFactory(organizer=organizer, draft=True)
        response = auth_client(organizer).get(f"{URL}mine/", {"status": "DRAFT"})
        assert [row["id"] for row in data(response)] == [draft.pk]

    def test_admins_see_every_event_and_users_are_refused(self, auth_client, admin_user, user):
        EventFactory.create_batch(2)
        assert len(data(auth_client(admin_user).get(f"{URL}mine/"))) == 2
        assert auth_client(user).get(f"{URL}mine/").status_code == 403


class TestAttendees:
    def test_the_organizer_sees_attendees_oldest_first(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        first, second = RegistrationFactory(event=event), RegistrationFactory(event=event)
        response = auth_client(organizer).get(f"{URL}{event.pk}/registrations/")
        assert response.status_code == 200
        assert [row["id"] for row in data(response)] == [first.pk, second.pk]
        assert set(data(response)[0]["user"]) == {"id", "full_name", "email", "phone"}
        assert "meta" in response.json()

    def test_filter_by_registration_status(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        RegistrationFactory(event=event)
        waiting = RegistrationFactory(event=event, waitlisted=True)
        response = auth_client(organizer).get(
            f"{URL}{event.pk}/registrations/", {"registration_status": "waitlisted"}
        )
        assert [row["id"] for row in data(response)] == [waiting.pk]

    def test_search_by_name_email_or_phone(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        ada = RegistrationFactory(
            event=event, user=UserFactory(first_name="Ada", last_name="Obi", email="ada@example.com", phone="+2348011111111")
        )
        RegistrationFactory(event=event, user=UserFactory(first_name="Ben", last_name="Eze", email="ben@example.com"))
        client = auth_client(organizer)
        for term in ("ada", "OBI", "ada@example", "8011111"):
            response = client.get(f"{URL}{event.pk}/registrations/", {"attendee": term})
            assert [row["id"] for row in data(response)] == [ada.pk], term

    def test_who_may_see_attendees(self, auth_client, api_client):
        event = EventFactory()
        url = f"{URL}{event.pk}/registrations/"
        assert api_client.get(url).status_code == 401
        assert auth_client(UserFactory()).get(url).status_code == 403
        assert auth_client(OrganizerFactory()).get(url).status_code == 403
        assert auth_client(AdminFactory()).get(url).status_code == 200


class TestExport:
    def test_csv_download(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        registration = RegistrationFactory(
            event=event, user=UserFactory(first_name="Ada", last_name="Obi", email="ada@example.com")
        )
        response = auth_client(organizer).get(f"{URL}{event.pk}/registrations/export/")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert f'{event.slug}-attendees.csv' in response["Content-Disposition"]
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        assert rows[0] == ["Registration ID", "Status", "Full name", "Email", "Phone", "Registered at", "Cancelled at"]
        assert rows[1][:4] == [str(registration.pk), "REGISTERED", "Ada Obi", "ada@example.com"]

    def test_spreadsheet_formulas_are_neutralised(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        RegistrationFactory(
            event=event, user=UserFactory(first_name="=SUM(1+1)", last_name="X", phone="+2348012345678")
        )
        response = auth_client(organizer).get(f"{URL}{event.pk}/registrations/export/")
        row = list(csv.reader(io.StringIO(response.content.decode())))[1]
        assert row[2] == "'=SUM(1+1) X"
        assert row[4] == "'+2348012345678"

    def test_export_follows_the_filters(self, auth_client, organizer):
        event = EventFactory(organizer=organizer)
        RegistrationFactory(event=event)
        RegistrationFactory(event=event, cancelled=True)
        response = auth_client(organizer).get(
            f"{URL}{event.pk}/registrations/export/", {"registration_status": "CANCELLED"}
        )
        assert len(list(csv.reader(io.StringIO(response.content.decode())))) == 2  # header + 1

    def test_only_managers_may_export(self, auth_client, api_client):
        event = EventFactory()
        url = f"{URL}{event.pk}/registrations/export/"
        assert api_client.get(url).status_code == 401
        assert auth_client(UserFactory()).get(url).status_code == 403
        assert auth_client(OrganizerFactory()).get(url).status_code == 403