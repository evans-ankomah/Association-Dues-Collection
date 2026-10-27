import pytest

from apps.common.tests.factories import (
    TEST_PASSWORD,
    AcademicSessionFactory,
    DepartmentFactory,
    MembershipFactory,
    UserFactory,
    grant,
)


@pytest.fixture
def department(db):
    return DepartmentFactory(code="CSE", name="Computer Science and Engineering")


@pytest.fixture
def session(department):
    return AcademicSessionFactory(institution=department.institution, name="2026/2027")


@pytest.fixture
def make_user(department):
    def _make(role_code=None, *, session=None, email=None, **kwargs):
        user = UserFactory(
            **({"email": email} if email else {}),
            with_profile__institution=department.institution,
            **kwargs,
        )
        if role_code:
            grant(user, role_code, department, session)
        return user

    return _make


@pytest.fixture
def member(make_user, department, session):
    user = make_user("student_member", session=session)
    MembershipFactory(user=user, department=department, academic_session=session)
    return user


@pytest.fixture
def membership(member, department, session):
    return member.memberships.get(department=department, academic_session=session)


@pytest.fixture
def make_membership(department, session):
    def _make(**kwargs):
        return MembershipFactory(department=department, academic_session=session, **kwargs)

    return _make


@pytest.fixture
def other_department(department):
    """A second department in the same institution, for cross-department leak tests.

    Same institution on purpose, so a passing test proves department scoping rather than
    institution isolation.
    """
    return DepartmentFactory(institution=department.institution)


@pytest.fixture
def other_session(department):
    """A second academic session. Never current: only one session per institution may be."""
    return AcademicSessionFactory(institution=department.institution, is_current=False, name="2024/2025")


@pytest.fixture
def make_other_membership(other_department, other_session):
    """A membership in the *other* department, with an explicit session.

    MembershipFactory would otherwise build its own current session and collide with
    uq_one_current_session_per_institution.
    """

    def _make(**kwargs):
        return MembershipFactory(department=other_department, academic_session=other_session, **kwargs)

    return _make


@pytest.fixture
def login(client):
    def _login(user):
        assert client.login(email=user.email, password=TEST_PASSWORD)
        return client

    return _login
