import pytest

pytestmark = pytest.mark.django_db


def test_api_root_uses_the_success_envelope(api_client):
    response = api_client.get("/api/v1/")
    assert response.status_code == 200
    assert response.json() == {"data": {"name": "EventHub API", "version": "v1"}}


def test_unknown_endpoint_uses_the_error_envelope(api_client):
    response = api_client.get("/api/v1/nope/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_auth_client_fixture_authenticates(auth_client, user):
    response = auth_client(user).get("/api/v1/users/profile/")
    assert response.status_code == 200
    assert response.json()["data"]["email"] == user.email