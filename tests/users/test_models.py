import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

from apps.users.models import Role
from tests.factories import UserFactory
from tests.factories.users import DEFAULT_PASSWORD

pytestmark = pytest.mark.django_db
User = get_user_model()


class TestUserManager:
    def test_create_user_applies_safe_defaults(self):
        user = User.objects.create_user(
            "Ada@EXAMPLE.com", "Pass#12345", first_name="Ada", last_name="Obi"
        )
        assert user.email == "Ada@example.com"  # Django lowercases the domain part
        assert user.check_password("Pass#12345")
        assert user.password != "Pass#12345"  # stored hashed, never as plain text
        assert user.role == Role.USER
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser

    def test_create_user_requires_an_email(self):
        with pytest.raises(ValueError):
            User.objects.create_user("", "Pass#12345")

    def test_create_user_accepts_an_explicit_role(self):
        user = User.objects.create_user("org@example.com", "Pass#12345", role=Role.ORGANIZER)
        assert user.role == Role.ORGANIZER
        assert not user.is_staff

    def test_create_user_without_password_is_unusable(self):
        user = User.objects.create_user("nopass@example.com", None)
        assert not user.has_usable_password()

    def test_create_superuser_is_an_admin_with_staff_access(self):
        admin = User.objects.create_superuser("root@example.com", "Pass#12345")
        assert admin.role == Role.ADMIN
        assert admin.is_staff
        assert admin.is_superuser


class TestUserModel:
    def test_email_is_unique(self):
        UserFactory(email="same@example.com")
        with pytest.raises(IntegrityError), transaction.atomic():
            UserFactory(email="same@example.com")

    @pytest.mark.parametrize(
        "role, is_organizer, is_admin",
        [
            (Role.USER, False, False),
            (Role.ORGANIZER, True, False),
            (Role.ADMIN, True, True),
        ],
    )
    def test_role_properties(self, role, is_organizer, is_admin):
        user = UserFactory(role=role)
        assert user.is_organizer is is_organizer
        assert user.is_admin_role is is_admin

    def test_full_name_and_str(self):
        user = UserFactory(first_name="Ada", last_name="Obi", email="ada@example.com")
        assert user.full_name == "Ada Obi"
        assert str(user) == "ada@example.com"

    def test_full_name_without_last_name_has_no_trailing_space(self):
        assert UserFactory(first_name="Ada", last_name="").full_name == "Ada"

    def test_timestamps_are_set(self):
        user = UserFactory()
        assert user.created_at is not None
        user.first_name = "Changed"
        user.save()
        assert user.updated_at >= user.created_at


class TestAuthentication:
    def test_login_with_email_and_password(self):
        user = UserFactory()
        assert authenticate(username=user.email, password=DEFAULT_PASSWORD) == user

    def test_wrong_password_is_rejected(self):
        user = UserFactory()
        assert authenticate(username=user.email, password="wrong") is None

    def test_inactive_users_cannot_authenticate(self):
        user = UserFactory(is_active=False)
        assert authenticate(username=user.email, password=DEFAULT_PASSWORD) is None