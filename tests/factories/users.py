import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from apps.users.models import Role

User = get_user_model()
DEFAULT_PASSWORD = "Pass#12345"


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    role = Role.USER

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Go through the manager so the password is hashed properly.
        email = kwargs.pop("email")
        password = kwargs.pop("password", DEFAULT_PASSWORD)
        return model_class.objects.create_user(email, password, **kwargs)


class OrganizerFactory(UserFactory):
    role = Role.ORGANIZER


class AdminFactory(UserFactory):
    role = Role.ADMIN
    is_staff = True
    is_superuser = True