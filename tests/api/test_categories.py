import pytest

from apps.events.models import Category
from tests.factories import CategoryFactory, EventFactory, OrganizerFactory, UserFactory
from tests.helpers import data, error

pytestmark = pytest.mark.django_db
URL = "/api/v1/categories/"


def test_the_public_sees_only_active_categories(api_client):
    CategoryFactory(name="Visible")
    CategoryFactory(name="Hidden", is_active=False)
    assert [c["name"] for c in data(api_client.get(URL))] == ["Visible"]


def test_organizers_also_see_inactive_ones(auth_client, organizer):
    CategoryFactory(name="Visible")
    CategoryFactory(name="Hidden", is_active=False)
    assert len(data(auth_client(organizer).get(URL))) == 2


def test_retrieve_by_slug(api_client):
    CategoryFactory(name="Web & Mobile")
    assert data(api_client.get(f"{URL}web-mobile/"))["name"] == "Web & Mobile"


def test_who_may_create(api_client, auth_client, user, organizer):
    body = {"name": "Health", "description": "Wellness events"}
    assert api_client.post(URL, body, format="json").status_code == 401
    assert auth_client(user).post(URL, body, format="json").status_code == 403
    response = auth_client(organizer).post(URL, body, format="json")
    assert response.status_code == 201
    assert data(response)["slug"] == "health"


def test_duplicate_names_are_a_400(auth_client, organizer):
    CategoryFactory(name="Sports")
    response = auth_client(organizer).post(URL, {"name": "Sports"}, format="json")
    assert response.status_code == 400
    assert "name" in error(response)["details"]


def test_organizers_can_deactivate(auth_client, organizer):
    category = CategoryFactory(name="Seasonal")
    response = auth_client(organizer).patch(f"{URL}{category.slug}/", {"is_active": False}, format="json")
    assert response.status_code == 200
    assert Category.objects.get(pk=category.pk).is_active is False


def test_only_admins_delete(auth_client, organizer, admin_user):
    category = CategoryFactory(name="Temporary")
    assert auth_client(organizer).delete(f"{URL}{category.slug}/").status_code == 403
    assert auth_client(admin_user).delete(f"{URL}{category.slug}/").status_code == 204


def test_a_category_in_use_cannot_be_deleted(auth_client, admin_user):
    event = EventFactory()
    response = auth_client(admin_user).delete(f"{URL}{event.category.slug}/")
    assert response.status_code == 409
    assert error(response)["code"] == "CATEGORY_IN_USE"