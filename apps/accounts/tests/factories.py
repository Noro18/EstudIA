import factory
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    first_name = factory.LazyAttribute(lambda o: o.username)


class SuperUserFactory(UserFactory):
    username = factory.Sequence(lambda n: f"admin{n}")
    is_staff = True
    is_superuser = True
    password = factory.LazyFunction(lambda: make_password("admintestpw"))
