import pytest

from apps.common.tests.factories import DepartmentFactory, MembershipFactory, UserFactory
from apps.service_requests.models import ServiceRequest, ServiceRequestComment

pytestmark = pytest.mark.django_db


def test_member_submits_a_request_over_http(member, login, department, membership):
    response = login(member).post(
        "/requests/new/",
        {
            "request_type": "introductory_letter",
            "title": "Letter for attachment",
            "description": "Needed for industrial attachment.",
            "priority": "normal",
            "visibility_level": "department",
        },
    )
    assert response.status_code == 302
    req = ServiceRequest.objects.get(title="Letter for attachment")
    assert req.department == department
    assert req.requester_membership == membership


def test_welfare_requests_are_private_even_if_the_form_says_otherwise(member, login):
    """A tampered form field must not be able to publish a sensitive case."""
    login(member).post(
        "/requests/new/",
        {
            "request_type": "welfare",
            "title": "Private matter",
            "description": "Details.",
            "priority": "normal",
            "visibility_level": "department",
        },
    )
    assert ServiceRequest.objects.get(title="Private matter").is_restricted


def test_restricted_request_is_404_for_an_unassigned_officer(make_request, officer, other_officer, login):
    """Not 403 — an officer shouldn't even learn that a welfare case exists."""
    restricted = make_request(
        request_type="welfare",
        title="Welfare concern",
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
        assigned_to_user=officer,
    )
    assert login(other_officer).get(f"/requests/{restricted.pk}/").status_code == 403
    body = login(other_officer).get("/requests/").content.decode()
    assert "Welfare concern" not in body


def test_assigned_officer_can_open_a_restricted_request(make_request, officer, login):
    restricted = make_request(
        request_type="welfare",
        title="Welfare concern",
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
        assigned_to_user=officer,
    )
    assert login(officer).get(f"/requests/{restricted.pk}/").status_code == 200


def test_requester_never_sees_staff_only_notes(make_request, member, officer, login):
    req = make_request(assigned_to_user=officer)
    ServiceRequestComment.objects.create(
        service_request=req,
        author_user=officer,
        body="Visible reply.",
    )
    ServiceRequestComment.objects.create(
        service_request=req,
        author_user=officer,
        body="Internal chase-up note.",
        visibility=ServiceRequestComment.Visibility.STAFF_ONLY,
    )
    body = login(member).get(f"/requests/{req.pk}/").content.decode()
    assert "Visible reply." in body
    assert "Internal chase-up note." not in body


def test_requester_cannot_post_a_staff_only_note(make_request, member, login):
    req = make_request()
    response = login(member).post(
        f"/requests/{req.pk}/action/", {"action": "comment", "body": "sneaky", "staff_only": "on"}
    )
    assert response.status_code == 403
    assert not ServiceRequestComment.objects.exists()


def test_member_cannot_see_another_members_request(make_request, member, login, make_membership):
    theirs = make_request(requester_membership=make_membership(user=UserFactory()), title="Someone else's")
    assert login(member).get(f"/requests/{theirs.pk}/").status_code == 403
    assert "Someone else's" not in login(member).get("/requests/").content.decode()


def test_member_cannot_change_status_or_assign(make_request, member, login, officer):
    req = make_request()
    client = login(member)
    assert (
        client.post(
            f"/requests/{req.pk}/action/",
            {"action": "status", "status": "resolved", "summary": "done"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/requests/{req.pk}/action/", {"action": "assign", "assignee": str(officer.pk)}
        ).status_code
        == 403
    )
    req.refresh_from_db()
    assert req.request_status == ServiceRequest.Status.SUBMITTED
    assert req.assigned_to_user_id is None


def test_officer_cannot_reach_another_departments_request(officer, login, department):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = ServiceRequest.objects.create(
        department=other_dept,
        requester_membership=MembershipFactory(department=other_dept),
        request_type="admin_question",
        title="Their business",
        description="Not yours.",
    )
    client = login(officer)
    assert client.get(f"/requests/{foreign.pk}/").status_code == 404
    assert client.post(f"/requests/{foreign.pk}/action/", {"action": "close"}).status_code == 404


def test_officer_queue_excludes_restricted_requests(make_request, officer, login):
    make_request(title="Ordinary letter")
    make_request(
        request_type="welfare",
        title="Welfare concern",
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
    )
    body = login(officer).get("/requests/").content.decode()
    assert "Ordinary letter" in body
    assert "Welfare concern" not in body


def test_anonymous_is_redirected_to_sign_in(make_request, client):
    req = make_request()
    assert client.get("/requests/").status_code == 302
    assert client.get(f"/requests/{req.pk}/").status_code == 302
