import logging

import pytest
from rest_framework.exceptions import Throttled

from apps.common.exceptions import api_exception_handler
from apps.events.views import EventViewSet
from tests.factories import EventFactory, RegistrationFactory
from tests.helpers import error

pytestmark = pytest.mark.django_db

CASES = [
    ("get", "/api/v1/", 200),
    ("get", "/api/v1/events/", 200),
    ("get", "/api/v1/categories/", 200),
    ("get", "/api/v1/users/profile/", 401),
    ("get", "/api/v1/nope/", 404),
    ("get", "/api/v1/events/999999/", 404),
    ("delete", "/api/v1/categories/", 405),
    ("post", "/api/v1/users/login/", 400),
    ("post", "/api/v1/users/register/", 400),
]


def assert_envelope(response):
    body = response.json()
    if response.status_code < 400:
        assert "data" in body and set(body) <= {"data", "meta"}
    else:
        assert set(body) == {"error"}
        err = body["error"]
        assert isinstance(err["code"], str) and err["code"] == err["code"].upper()
        assert isinstance(err["message"], str) and err["message"]


@pytest.mark.parametrize("method, url, expected", CASES)
def test_every_response_follows_the_envelope(api_client, method, url, expected):
    response = getattr(api_client, method)(url)
    assert response.status_code == expected
    assert_envelope(response)


def test_401_asks_for_a_token(api_client):
    response = api_client.get("/api/v1/users/profile/")
    assert error(response)["code"] == "NOT_AUTHENTICATED"
    assert response["WWW-Authenticate"].startswith("Token")


def test_a_bad_token_is_a_401(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")
    response = api_client.get("/api/v1/users/profile/")
    assert response.status_code == 401
    assert error(response)["code"] == "AUTHENTICATION_FAILED"


def test_403(auth_client, user):
    response = auth_client(user).post("/api/v1/events/", {}, format="json")
    assert (response.status_code, error(response)["code"]) == (403, "PERMISSION_DENIED")


def test_404_for_an_unknown_endpoint_is_json_not_html(api_client):
    response = api_client.get("/api/v1/definitely/not/here/")
    assert response["Content-Type"].startswith("application/json")
    assert error(response)["code"] == "NOT_FOUND"


def test_405(api_client):
    response = api_client.delete("/api/v1/categories/")
    assert error(response)["code"] == "METHOD_NOT_ALLOWED"


def test_malformed_json_is_a_400(api_client):
    response = api_client.post("/api/v1/users/login/", data="{bad json", content_type="application/json")
    assert response.status_code == 400
    assert error(response)["code"] == "PARSE_ERROR"


def test_validation_errors_list_the_failing_fields(api_client):
    response = api_client.post("/api/v1/users/register/", {"email": "nope"}, format="json")
    err = error(response)
    assert (response.status_code, err["code"]) == (400, "VALIDATION_ERROR")
    assert {"email", "first_name", "password"} <= set(err["details"])


def test_domain_errors_carry_their_own_code_and_message(auth_client, user):
    event = EventFactory(closed=True)
    response = auth_client(user).post(f"/api/v1/events/{event.pk}/register/")
    assert response.status_code == 409
    assert error(response) == {
        "code": "REGISTRATION_CLOSED",
        "message": "Registration for this event is closed.",
    }


def test_business_rule_violations_are_a_422(auth_client, organizer):
    event = EventFactory(organizer=organizer, capacity=5)
    RegistrationFactory.create_batch(3, event=event)
    response = auth_client(organizer).patch(f"/api/v1/events/{event.pk}/", {"capacity": 1}, format="json")
    assert (response.status_code, error(response)["code"]) == (422, "BUSINESS_RULE_VIOLATION")


def test_unexpected_failures_are_a_500_that_leaks_nothing(api_client, monkeypatch, caplog):
    def boom(self, request, *args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(EventViewSet, "list", boom)
    with caplog.at_level(logging.ERROR):
        response = api_client.get("/api/v1/events/")

    assert response.status_code == 500
    assert error(response) == {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}
    assert "secret internal detail" not in response.content.decode()
    assert "Unhandled API exception" in caplog.text  # ...but the log has the traceback


class TestHandlerDirectly:
    """Throttling is not switched on yet (Commit 31), so check the 429 shape at the handler."""

    def test_throttled_requests_become_a_429_with_retry_after(self):
        response = api_exception_handler(Throttled(wait=30), {})
        assert response.status_code == 429
        assert response.data["error"]["code"] == "RATE_LIMITED"
        assert response.data["error"]["retry_after"] == 30
        assert response["Retry-After"] == "30"

    def test_any_other_exception_is_a_500(self):
        response = api_exception_handler(ValueError("x"), {})
        assert response.status_code == 500
        assert response.data["error"]["code"] == "INTERNAL_ERROR"