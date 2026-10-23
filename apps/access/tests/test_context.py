import pytest

from apps.access.middleware import SESSION_DEPARTMENT_KEY
from apps.common.tests.factories import AcademicSessionFactory, DepartmentFactory, grant

pytestmark = pytest.mark.django_db


def test_request_gets_department_and_current_session(member, department, session, login):
    client = login(member)
    response = client.get("/")
    assert response.wsgi_request.department == department
    assert response.wsgi_request.academic_session == session


def test_switching_to_a_department_without_access_is_ignored(member, department, login):
    client = login(member)
    other = DepartmentFactory(institution=department.institution)
    client.post("/context/switch/", {"department": str(other.pk), "next": "/"})
    assert client.session[SESSION_DEPARTMENT_KEY] == str(department.pk)


def test_switching_between_accessible_departments(member, department, login):
    other = DepartmentFactory(institution=department.institution, name="Zoology")
    grant(member, "student_member", other)
    client = login(member)
    client.get("/")
    client.post("/context/switch/", {"department": str(other.pk), "next": "/"})
    assert client.get("/").wsgi_request.department == other


def test_switching_session_within_institution(member, department, session, login):
    older = AcademicSessionFactory(
        institution=department.institution, name="2025/2026", is_current=False, status="closed"
    )
    client = login(member)
    client.post("/context/switch/", {"academic_session": str(older.pk), "next": "/"})
    assert client.get("/").wsgi_request.academic_session == older


def test_switch_rejects_offsite_redirect(member, login):
    client = login(member)
    response = client.post("/context/switch/", {"next": "https://evil.example/"})
    assert response["Location"] == "/"
