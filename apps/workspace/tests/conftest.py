import pytest

from apps.workspace import services as svc


@pytest.fixture
def secretary(make_user, session):
    """Holds committees.manage."""
    return make_user("department_secretary", session=session)


@pytest.fixture
def committee(department, session, secretary):
    return svc.create_committee(
        actor=secretary,
        department=department,
        academic_session=session,
        name="Welfare Committee",
        description="Supports members in hardship.",
    )
