import pytest

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
def assessment(dues_type, membership, finsec):
    return AssessmentFactory(dues_type=dues_type, department_membership=membership, assessed_by=finsec)
