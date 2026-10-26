import pytest

from apps.users.models import Role
from tests.factories import AdminFactory, OrganizerFactory, UserFactory
from tests.factories.users import DEFAULT_PASSWORD

pytestmark = pytest.mark.django_db


def test_user_factory_creates_regular_user_with_working_password():
    user = UserFactory()
    assert user.role == Role.USER
    assert user.check_password(DEFAULT_PASSWORD)


def test_organizer_and_admin_roles():
    assert OrganizerFactory().is_organizer
    admin = AdminFactory()
    assert admin.is_admin_role and admin.is_staff and admin.is_superuser