import pytest

from apps.common.tests.factories import MembershipFactory

from .factories import AssessmentFactory, DuesTypeFactory


@pytest.fixture
def finsec(make_user, session):
    return make_user("financial_secretary", session=session)


@pytest.fixture
def hod(make_user):
    return make_user("hod_faculty_adviser")


@pytest.fixture
def dues_type(department, session, finsec):
    return DuesTypeFactory(department=department, academic_session=session, created_by=finsec)


@pytest.fixture
def membership(member, department, session):
    return member.memberships.get(department=department, academic_session=session)


@pytest.fixture
def assessment(dues_type, membership, finsec):
    return AssessmentFactory(dues_type=dues_type, department_membership=membership, assessed_by=finsec)


@pytest.fixture
def make_membership(department, session):
    def _make(**kwargs):
        return MembershipFactory(department=department, academic_session=session, **kwargs)

    return _make
