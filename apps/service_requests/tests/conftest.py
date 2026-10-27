import pytest

from apps.service_requests.models import ServiceRequest


@pytest.fixture
def officer(make_user, session):
    """Holds requests.manage (the President role carries it)."""
    return make_user("department_president", session=session)


@pytest.fixture
def other_officer(make_user, session):
    """A second requests.manage holder, for the restricted-visibility tests."""
    return make_user("hod_faculty_adviser", session=session)


@pytest.fixture
def make_request(department, membership):
    def _make(**kwargs):
        kwargs.setdefault("department", department)
        kwargs.setdefault("requester_membership", membership)
        kwargs.setdefault("request_type", "introductory_letter")
        kwargs.setdefault("title", "Introductory letter")
        kwargs.setdefault("description", "Please issue a letter for industrial attachment.")
        return ServiceRequest.objects.create(**kwargs)

    return _make
