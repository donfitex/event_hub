import re

import pytest
from django.core import mail
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from tests.factories import AdminFactory, OrganizerFactory, UserFactory
from tests.factories.users import DEFAULT_PASSWORD
from tests.helpers import data, error

pytestmark = pytest.mark.django_db
USERS = "/api/v1/users/"
STRONG = "Brand#New2026pass"


def register_payload(**overrides):
    payload = {
        "email": "ada@example.com", "first_name": "Ada", "last_name": "Obi",
        "password": STRONG, "password_confirm": STRONG,
    }
    payload.update(overrides)
    return payload


class TestRegister:
    def test_creates_a_regular_user_and_ignores_a_requested_role(self, api_client):
        response = api_client.post(USERS + "register/", register_payload(role="ADMIN"), format="json")
        assert response.status_code == 201
        assert data(response)["role"] == "USER"
        assert "password" not in response.content.decode()

    @pytest.mark.parametrize(
        "overrides, field",
        [
            ({"email": "not-an-email"}, "email"),
            ({"password": "short", "password_confirm": "short"}, "non_field_errors"),
            ({"password_confirm": "Different#2026pw"}, "password_confirm"),
        ],
    )
    def test_invalid_input_is_a_400(self, api_client, overrides, field):
        response = api_client.post(USERS + "register/", register_payload(**overrides), format="json")
        assert response.status_code == 400
        assert error(response)["code"] == "VALIDATION_ERROR"
        assert field in error(response)["details"] or "password" in error(response)["details"]

    def test_duplicate_emails_are_rejected_case_insensitively(self, api_client):
        UserFactory(email="ada@example.com")
        response = api_client.post(USERS + "register/", register_payload(email="ADA@example.com"), format="json")
        assert response.status_code == 400
        assert "email" in error(response)["details"]


class TestLoginAndLogout:
    def test_login_returns_a_token_and_the_user(self, api_client, user):
        response = api_client.post(USERS + "login/", {"email": user.email, "password": DEFAULT_PASSWORD}, format="json")
        assert response.status_code == 200
        assert data(response)["token"] == Token.objects.get(user=user).key
        assert data(response)["user"]["email"] == user.email

    def test_login_is_case_insensitive_on_the_email(self, api_client, user):
        response = api_client.post(
            USERS + "login/", {"email": user.email.upper(), "password": DEFAULT_PASSWORD}, format="json"
        )
        assert response.status_code == 200

    def test_wrong_password_and_unknown_email_look_identical(self, api_client, user):
        wrong = api_client.post(USERS + "login/", {"email": user.email, "password": "nope"}, format="json")
        unknown = api_client.post(USERS + "login/", {"email": "ghost@example.com", "password": "nope"}, format="json")
        assert wrong.status_code == unknown.status_code == 400
        assert wrong.json() == unknown.json()

    def test_inactive_users_cannot_log_in(self, api_client):
        user = UserFactory(is_active=False)
        response = api_client.post(USERS + "login/", {"email": user.email, "password": DEFAULT_PASSWORD}, format="json")
        assert response.status_code == 400

    def test_the_token_authenticates_requests(self, token_client, user):
        assert token_client(user).get(USERS + "profile/").status_code == 200

    def test_logout_invalidates_the_token(self, token_client, user):
        client = token_client(user)
        assert client.post(USERS + "logout/").status_code == 204
        response = client.get(USERS + "profile/")
        assert response.status_code == 401
        assert error(response)["code"] == "AUTHENTICATION_FAILED"

    def test_logout_requires_authentication(self, api_client):
        assert api_client.post(USERS + "logout/").status_code == 401


class TestSessionsAndCsrf:
    def test_session_login_still_works(self, user):
        client = APIClient()
        assert client.login(username=user.email, password=DEFAULT_PASSWORD)
        assert client.get(USERS + "profile/").status_code == 200

    def test_session_requests_need_a_csrf_token(self, user):
        client = APIClient(enforce_csrf_checks=True)
        client.login(username=user.email, password=DEFAULT_PASSWORD)
        response = client.post(USERS + "logout/")
        assert response.status_code == 403
        assert "CSRF" in error(response)["message"]

    def test_token_requests_are_exempt_from_csrf(self, token_client, user):
        client = token_client(user)
        client.handler.enforce_csrf_checks = True
        assert client.post(USERS + "logout/").status_code == 204

    def test_the_state_endpoint_reports_the_login_and_sets_the_csrf_cookie(self, api_client, auth_client, user):
        anonymous = api_client.get(USERS + "state/")
        assert data(anonymous) == {"authenticated": False, "user": None}
        assert "csrftoken" in anonymous.cookies
        logged_in = data(auth_client(user).get(USERS + "state/"))
        assert logged_in["authenticated"] is True and logged_in["user"]["email"] == user.email


class TestProfile:
    def test_requires_authentication(self, api_client):
        assert api_client.get(USERS + "profile/").status_code == 401

    def test_update_changes_only_allowed_fields(self, auth_client, user):
        response = auth_client(user).patch(
            USERS + "profile/",
            {"first_name": "Renamed", "phone": "08012345678", "email": "hijack@example.com", "role": "ADMIN"},
            format="json",
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert (user.first_name, user.phone) == ("Renamed", "08012345678")
        assert user.email != "hijack@example.com"
        assert user.role == "USER"


class TestChangePassword:
    def test_success_rotates_the_token(self, token_client, user):
        client = token_client(user)
        old_token = client.token
        response = client.post(
            USERS + "change-password/", {"old_password": DEFAULT_PASSWORD, "new_password": STRONG}, format="json"
        )
        assert response.status_code == 200
        new_token = data(response)["token"]
        assert new_token != old_token

        client.credentials(HTTP_AUTHORIZATION=f"Token {old_token}")
        assert client.get(USERS + "profile/").status_code == 401
        client.credentials(HTTP_AUTHORIZATION=f"Token {new_token}")
        assert client.get(USERS + "profile/").status_code == 200
        user.refresh_from_db()
        assert user.check_password(STRONG)

    def test_the_old_password_must_be_right(self, auth_client, user):
        response = auth_client(user).post(
            USERS + "change-password/", {"old_password": "wrong", "new_password": STRONG}, format="json"
        )
        assert response.status_code == 400
        assert "old_password" in error(response)["details"]

    def test_weak_passwords_are_rejected(self, auth_client, user):
        response = auth_client(user).post(
            USERS + "change-password/", {"old_password": DEFAULT_PASSWORD, "new_password": "12345678"}, format="json"
        )
        assert response.status_code == 400
        assert "new_password" in error(response)["details"]


class TestPasswordReset:
    def request_link(self, api_client, email):
        api_client.post(USERS + "password-reset/", {"email": email}, format="json")
        match = re.search(r"uid=([^&\s]+)&token=([^\s]+)", mail.outbox[-1].body)
        return match.group(1), match.group(2)

    def test_the_response_does_not_reveal_whether_an_email_exists(self, api_client, user):
        known = api_client.post(USERS + "password-reset/", {"email": user.email}, format="json")
        unknown = api_client.post(USERS + "password-reset/", {"email": "ghost@example.com"}, format="json")
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert len(mail.outbox) == 1  # only the real account got an email
        assert mail.outbox[0].to == [user.email]

    def test_full_reset_flow(self, api_client, user):
        uid, token = self.request_link(api_client, user.email)
        response = api_client.post(
            USERS + "password-reset/confirm/", {"uid": uid, "token": token, "new_password": STRONG}, format="json"
        )
        assert response.status_code == 200
        login = api_client.post(USERS + "login/", {"email": user.email, "password": STRONG}, format="json")
        assert login.status_code == 200

    def test_a_link_works_only_once(self, api_client, user):
        uid, token = self.request_link(api_client, user.email)
        body = {"uid": uid, "token": token, "new_password": STRONG}
        api_client.post(USERS + "password-reset/confirm/", body, format="json")
        again = api_client.post(USERS + "password-reset/confirm/", {**body, "new_password": "Another#2026pass"}, format="json")
        assert again.status_code == 400
        assert error(again)["code"] == "INVALID_RESET_TOKEN"

    def test_bad_links_and_weak_passwords(self, api_client, user):
        uid, token = self.request_link(api_client, user.email)
        bad_uid = api_client.post(
            USERS + "password-reset/confirm/", {"uid": "!!", "token": token, "new_password": STRONG}, format="json"
        )
        assert error(bad_uid)["code"] == "INVALID_RESET_LINK"
        weak = api_client.post(
            USERS + "password-reset/confirm/", {"uid": uid, "token": token, "new_password": "12345678"}, format="json"
        )
        assert weak.status_code == 400
        assert "new_password" in error(weak)["details"]

    def test_a_reset_logs_out_existing_tokens(self, api_client, token_client, user):
        client = token_client(user)
        uid, token = self.request_link(api_client, user.email)
        api_client.post(
            USERS + "password-reset/confirm/", {"uid": uid, "token": token, "new_password": STRONG}, format="json"
        )
        assert client.get(USERS + "profile/").status_code == 401


class TestUserManagement:
    URL = USERS + "manage/"

    def test_admin_only(self, api_client, auth_client, user, organizer, admin_user):
        assert api_client.get(self.URL).status_code == 401
        assert auth_client(user).get(self.URL).status_code == 403
        assert auth_client(organizer).get(self.URL).status_code == 403
        assert auth_client(admin_user).get(self.URL).status_code == 200

    def test_filter_and_search(self, auth_client, admin_user):
        ada = OrganizerFactory(first_name="Ada", last_name="Obi")
        UserFactory(first_name="Ben")
        client = auth_client(admin_user)
        organizers = data(client.get(self.URL, {"role": "ORGANIZER"}))
        assert [u["id"] for u in organizers] == [ada.pk]
        assert [u["id"] for u in data(client.get(self.URL, {"search": "obi"}))] == [ada.pk]

    def test_an_admin_can_promote_a_user(self, auth_client, admin_user, user):
        response = auth_client(admin_user).patch(f"{self.URL}{user.pk}/", {"role": "ORGANIZER"}, format="json")
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.role == "ORGANIZER"

    def test_only_role_and_active_flag_are_writable(self, auth_client, admin_user, user):
        auth_client(admin_user).patch(
            f"{self.URL}{user.pk}/", {"email": "changed@example.com", "first_name": "Changed"}, format="json"
        )
        user.refresh_from_db()
        assert user.email != "changed@example.com" and user.first_name != "Changed"

    def test_admins_cannot_lock_themselves_out(self, auth_client, admin_user):
        client = auth_client(admin_user)
        assert client.patch(f"{self.URL}{admin_user.pk}/", {"role": "USER"}, format="json").status_code == 400
        assert client.patch(f"{self.URL}{admin_user.pk}/", {"is_active": False}, format="json").status_code == 400

    def test_deactivating_a_user_ends_their_access(self, auth_client, token_client, admin_user, user):
        client = token_client(user)
        auth_client(admin_user).patch(f"{self.URL}{user.pk}/", {"is_active": False}, format="json")
        assert not Token.objects.filter(user=user).exists()
        assert client.get(USERS + "profile/").status_code == 401

    def test_only_get_and_patch_are_allowed(self, auth_client, admin_user, user):
        client = auth_client(admin_user)
        assert client.post(self.URL, {}, format="json").status_code == 405
        assert client.put(f"{self.URL}{user.pk}/", {}, format="json").status_code == 405
        assert client.delete(f"{self.URL}{user.pk}/").status_code == 405