import pytest

from .factories import EventFactory


@pytest.fixture
def organiser(make_user, session):
    """Holds events.manage (the President role also carries it)."""
    return make_user("department_president", session=session)


@pytest.fixture
def event(department, organiser):
    return EventFactory(department=department, created_by=organiser)
