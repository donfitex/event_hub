from datetime import timedelta

import pytest
from django.utils import timezone

from tests.factories import (
    AdminFactory,
    CategoryFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)
from tests.helpers import data, error

pytestmark = pytest.mark.django_db
URL = "/api/v1/events/"

LIST_FIELDS = {
    "id", "title", "slug", "category", "organizer", "location", "venue",
    "start_datetime", "end_datetime", "capacity", "available_seats", "status", "image",
}
DETAIL_FIELDS = LIST_FIELDS | {
    "description", "registration_deadline", "registration_count", "waitlist_count",
    "is_registration_open", "registration_available", "waitlist_available",
    "created_at", "updated_at",
}


def ids(response):
    return [item["id"] for item in data(response)]


class TestEnvelopeAndPagination:
    def test_list_has_data_and_meta(self, api_client):
        EventFactory.create_batch(3)
        response = api_client.get(URL)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"data", "meta"}
        assert set(body["meta"]) == {"count", "page", "page_size", "total_pages", "next", "previous"}
        assert body["meta"]["count"] == 3
        assert set(body["data"][0]) == LIST_FIELDS

    def test_pagination(self, api_client):
        EventFactory.create_batch(5)
        first = api_client.get(URL, {"page_size": 2}).json()
        assert len(first["data"]) == 2
        assert first["meta"]["total_pages"] == 3
        assert first["meta"]["next"] and first["meta"]["previous"] is None

        last = api_client.get(URL, {"page_size": 2, "page": 3}).json()
        assert len(last["data"]) == 1
        assert last["meta"]["next"] is None and last["meta"]["previous"]

    def test_page_size_is_capped(self, api_client):
        EventFactory()
        assert api_client.get(URL, {"page_size": 1000}).json()["meta"]["page_size"] == 100

    def test_a_page_beyond_the_end_is_a_404(self, api_client):
        EventFactory()
        response = api_client.get(URL, {"page": 99})
        assert response.status_code == 404
        assert error(response)["code"] == "NOT_FOUND"

    def test_list_does_not_run_a_query_per_event(self, api_client, django_assert_max_num_queries):
        for event in EventFactory.create_batch(10):
            RegistrationFactory.create_batch(2, event=event)
        with django_assert_max_num_queries(6):
            assert api_client.get(URL).status_code == 200


class TestVisibility:
    def test_the_public_sees_everything_except_drafts(self, api_client):
        published, cancelled, completed = EventFactory(), EventFactory(cancelled=True), EventFactory(completed=True)
        draft = EventFactory(draft=True)
        assert set(ids(api_client.get(URL))) == {published.pk, cancelled.pk, completed.pk}
        assert api_client.get(f"{URL}{draft.pk}/").status_code == 404
        assert ids(api_client.get(URL, {"status": "DRAFT"})) == []

    def test_drafts_are_visible_only_to_their_owner_and_admins(self, auth_client):
        draft = EventFactory(draft=True)
        viewers = [
            (draft.organizer, True),
            (AdminFactory(), True),
            (OrganizerFactory(), False),
            (UserFactory(), False),
        ]
        for viewer, can_see in viewers:
            client = auth_client(viewer)
            assert (draft.pk in ids(client.get(URL))) is can_see
            assert client.get(f"{URL}{draft.pk}/").status_code == (200 if can_see else 404)


class TestDetail:
    def test_fields_and_counts(self, api_client):
        event = EventFactory(capacity=3)
        RegistrationFactory.create_batch(2, event=event)
        RegistrationFactory(event=event, waitlisted=True)
        RegistrationFactory(event=event, cancelled=True)

        detail = data(api_client.get(f"{URL}{event.pk}/"))

        assert set(detail) == DETAIL_FIELDS
        assert detail["registration_count"] == 2
        assert detail["available_seats"] == 1
        assert detail["waitlist_count"] == 1
        assert detail["is_registration_open"] is True
        assert detail["registration_available"] is True
        assert detail["waitlist_available"] is False

    def test_a_full_event_offers_the_waitlist(self, api_client):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        detail = data(api_client.get(f"{URL}{event.pk}/"))
        assert detail["available_seats"] == 0
        assert detail["registration_available"] is False
        assert detail["waitlist_available"] is True

    def test_a_closed_event_offers_neither(self, api_client):
        detail = data(api_client.get(f"{URL}{EventFactory(closed=True).pk}/"))
        assert detail["is_registration_open"] is False
        assert detail["registration_available"] is False
        assert detail["waitlist_available"] is False

    def test_only_safe_organizer_details_are_public(self, api_client):
        event = EventFactory()
        response = api_client.get(f"{URL}{event.pk}/")
        assert set(data(response)["organizer"]) == {"id", "full_name"}
        assert event.organizer.email not in response.content.decode()

    def test_unknown_event(self, api_client):
        response = api_client.get(f"{URL}999999/")
        assert response.status_code == 404
        assert error(response)["code"] == "NOT_FOUND"


@pytest.fixture
def catalogue():
    tech, sports = CategoryFactory(name="Technology"), CategoryFactory(name="Sports")
    now = timezone.now()
    return {
        "python": EventFactory(
            title="Python Meetup", description="Learn Python together", category=tech,
            location="Lagos", start_datetime=now + timedelta(days=5), capacity=30,
        ),
        "football": EventFactory(
            title="Football Fiesta", description="Friendly matches", category=sports,
            location="Abuja", start_datetime=now + timedelta(days=20), capacity=100,
        ),
        "workshop": EventFactory(
            title="Design Workshop", description="Hands-on design", category=tech,
            location="Lagos Island", start_datetime=now + timedelta(days=40), capacity=10,
        ),
        "old": EventFactory(
            title="Old Conference", description="Already happened", category=tech,
            location="Ibadan", completed=True, capacity=50,
        ),
    }


class TestFilteringSearchAndSorting:
    def test_filter_by_category_slug(self, api_client, catalogue):
        assert ids(api_client.get(URL, {"category": "sports"})) == [catalogue["football"].pk]

    def test_filter_by_location_is_case_insensitive_and_partial(self, api_client, catalogue):
        found = set(ids(api_client.get(URL, {"location": "lagos"})))
        assert found == {catalogue["python"].pk, catalogue["workshop"].pk}

    def test_filter_by_status(self, api_client, catalogue):
        assert ids(api_client.get(URL, {"status": "COMPLETED"})) == [catalogue["old"].pk]

    def test_filter_by_date_range(self, api_client, catalogue):
        now = timezone.now()
        response = api_client.get(URL, {
            "start_date_after": (now + timedelta(days=15)).date().isoformat(),
            "start_date_before": (now + timedelta(days=30)).date().isoformat(),
        })
        assert ids(response) == [catalogue["football"].pk]

    def test_upcoming_flag(self, api_client, catalogue):
        upcoming = set(ids(api_client.get(URL, {"upcoming": "true"})))
        assert catalogue["old"].pk not in upcoming and len(upcoming) == 3
        assert ids(api_client.get(URL, {"upcoming": "false"})) == [catalogue["old"].pk]

    @pytest.mark.parametrize(
        "term, expected",
        [("python", ["python"]), ("PYTHON", ["python"]), ("design", ["workshop"]), ("sports", ["football"])],
    )
    def test_search_covers_title_description_and_category(self, api_client, catalogue, term, expected):
        assert ids(api_client.get(URL, {"search": term})) == [catalogue[k].pk for k in expected]

    def test_sorting(self, api_client, catalogue):
        c = catalogue
        assert ids(api_client.get(URL)) == [c["old"].pk, c["python"].pk, c["football"].pk, c["workshop"].pk]
        assert ids(api_client.get(URL, {"ordering": "-capacity"})) == [
            c["football"].pk, c["old"].pk, c["python"].pk, c["workshop"].pk,
        ]
        assert ids(api_client.get(URL, {"ordering": "title"})) == [
            c["workshop"].pk, c["football"].pk, c["old"].pk, c["python"].pk,
        ]

    def test_filters_combine(self, api_client, catalogue):
        response = api_client.get(URL, {"category": "technology", "location": "lagos", "upcoming": "true"})
        assert set(ids(response)) == {catalogue["python"].pk, catalogue["workshop"].pk}

    def test_an_invalid_filter_value_is_a_validation_error(self, api_client):
        response = api_client.get(URL, {"status": "NOT_A_STATUS"})
        assert response.status_code == 400
        assert error(response)["code"] == "VALIDATION_ERROR"