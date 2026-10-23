import pytest

from apps.common.tests.factories import (
    AcademicSessionFactory,
    DepartmentFactory,
    MembershipFactory,
    UserFactory,
)
from apps.finance.models import DuesAssessment, DuesType

from .factories import AssessmentFactory, DuesTypeFactory

pytestmark = pytest.mark.django_db


def test_member_sees_own_dues_only(assessment, member, login, department, session):
    stranger_membership = MembershipFactory(department=department, academic_session=session)
    AssessmentFactory(dues_type=assessment.dues_type, department_membership=stranger_membership)
    client = login(member)
    response = client.get("/finance/my-dues/")
    assert response.status_code == 200
    assert response.context["outstanding"] == assessment.amount_assessed


def test_member_cannot_open_department_dues_or_others_assessments(
    assessment, member, login, department, session
):
    client = login(member)
    assert client.get("/finance/dues/").status_code == 403
    other = AssessmentFactory(
        dues_type=assessment.dues_type,
        department_membership=MembershipFactory(department=department, academic_session=session),
    )
    assert client.get(f"/finance/assessments/{other.pk}/").status_code == 403
    assert client.get(f"/finance/assessments/{assessment.pk}/").status_code == 200


def test_officer_cannot_reach_another_departments_records(finsec, login, department):
    other_dept = DepartmentFactory(institution=department.institution)
    other_session = AcademicSessionFactory(institution=department.institution, is_current=False, name="x")
    foreign = DuesTypeFactory(department=other_dept, academic_session=other_session, created_by=UserFactory())
    client = login(finsec)
    assert client.get(f"/finance/dues/{foreign.pk}/").status_code == 404


def test_create_dues_type_then_assess_with_preview(finsec, login, make_membership):
    make_membership(level_code="Level 100")
    make_membership(level_code="Level 200")
    client = login(finsec)
    response = client.post(
        "/finance/dues/new/",
        {"name": "Departmental Dues", "category": "departmental_dues", "default_amount": "150.00"},
    )
    dues_type = DuesType.objects.get()
    assert response["Location"] == f"/finance/dues/{dues_type.pk}/assess/"

    preview = client.post(
        f"/finance/dues/{dues_type.pk}/assess/", {"levels": ["Level 100"], "amount": "150.00", "preview": "1"}
    )
    assert preview.context["preview"]["count"] == 1
    assert DuesAssessment.objects.count() == 0

    client.post(
        f"/finance/dues/{dues_type.pk}/assess/", {"levels": ["Level 100"], "amount": "150.00", "confirm": "1"}
    )
    assert DuesAssessment.objects.count() == 1


def test_treasurer_can_view_but_not_create(make_user, login, dues_type):
    client = login(make_user("treasurer"))
    assert client.get("/finance/dues/").status_code == 200
    assert client.get(f"/finance/dues/{dues_type.pk}/").status_code == 200
    assert client.get("/finance/dues/new/").status_code == 403


def test_waiver_request_and_approval_through_views(assessment, member, hod, login):
    client = login(member)
    client.post(
        f"/finance/assessments/{assessment.pk}/waiver/", {"amount": "150.00", "reason": "Medical leave"}
    )
    waiver = assessment.waiver_requests.get()

    client = login(hod)
    assert client.get("/finance/waivers/").status_code == 200
    client.post(f"/finance/waivers/{waiver.pk}/decide/", {"decision": "approve"})
    assessment.refresh_from_db()
    assert assessment.assessment_state == DuesAssessment.State.WAIVED


def test_roster_shows_outstanding(finsec, login, assessment):
    client = login(finsec)
    response = client.get("/members/?owing=1")
    assert response.status_code == 200
    rows = list(response.context["page"])
    assert len(rows) == 1 and rows[0].outstanding == assessment.amount_assessed
    detail = client.get(f"/members/{rows[0].pk}/")
    assert detail.status_code == 200
