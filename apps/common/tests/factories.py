"""Shared factory_boy factories for tests across apps."""

import datetime

import factory
from django.utils import timezone

from apps.access.models import Role, RoleAssignment
from apps.accounts.models import User, UserProfile
from apps.institutions.models import AcademicSession, Department, Institution
from apps.memberships.models import DepartmentMembership

TEST_PASSWORD = "correct-horse-battery-staple"


class InstitutionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Institution

    name = factory.Sequence(lambda n: f"University {n}")
    country_code = "GH"


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department

    institution = factory.SubFactory(InstitutionFactory)
    code = factory.Sequence(lambda n: f"D{n}")
    name = factory.Sequence(lambda n: f"Department {n}")


class AcademicSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AcademicSession

    institution = factory.SubFactory(InstitutionFactory)
    name = factory.Sequence(lambda n: f"{2020 + n}/{2021 + n}")
    starts_on = datetime.date(2026, 8, 24)
    ends_on = datetime.date(2027, 7, 30)
    is_current = True
    status = AcademicSession.Status.ACTIVE


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.test")
    password = factory.PostGenerationMethodCall("set_password", TEST_PASSWORD)

    @factory.post_generation
    def with_profile(obj, create, extracted, **kwargs):
        if extracted is False:
            return
        institution = kwargs.get("institution") or InstitutionFactory()
        UserProfile.objects.create(
            user=obj,
            institution=institution,
            given_name=kwargs.get("given_name", "Ama"),
            family_name=kwargs.get("family_name", "Mensah"),
        )
        obj.save()


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DepartmentMembership

    department = factory.SubFactory(DepartmentFactory)
    user = factory.SubFactory(UserFactory)
    academic_session = factory.LazyAttribute(
        lambda o: AcademicSessionFactory(institution=o.department.institution)
    )
    programme_name = "BSc Computer Science and Engineering"
    level_code = "Level 200"


def grant(user, role_code, department=None, session=None, **extra):
    """Give `user` a current role assignment."""
    role = Role.objects.get(role_code=role_code)
    return RoleAssignment.objects.create(
        user=user,
        role=role,
        department=department if role.scope_type == Role.Scope.DEPARTMENT else None,
        institution=extra.pop("institution", None),
        academic_session=session,
        starts_at=extra.pop("starts_at", timezone.now() - datetime.timedelta(days=1)),
        **extra,
    )
