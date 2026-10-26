import pytest
from rest_framework.test import APIClient

from tests.factories.users import DEFAULT_PASSWORD
from tests.factories import (
    AdminFactory, CategoryFactory, EventFactory, OrganizerFactory, UserFactory,
)


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Uploaded files go to a temporary folder, never into your real media/."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def organizer():
    return OrganizerFactory()


@pytest.fixture
def admin_user():
    return AdminFactory()


@pytest.fixture
def category():
    return CategoryFactory()


@pytest.fixture
def event(organizer, category):
    return EventFactory(organizer=organizer, category=category)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    """Usage: auth_client(user).get(...). Authenticates without going through login."""

    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make



@pytest.fixture
def token_client():
    """Logs in through the real endpoint and returns a client sending the real token."""

    def _make(user, password=DEFAULT_PASSWORD):
        login = APIClient().post(
            "/api/v1/users/login/", {"email": user.email, "password": password}, format="json"
        )
        assert login.status_code == 200, login.content
        client = APIClient()
        client.token = login.json()["data"]["token"]
        client.credentials(HTTP_AUTHORIZATION=f"Token {client.token}")
        return client

    return _make
