import pytest
from django.core.exceptions import PermissionDenied

from apps.common.tests.factories import UserFactory
from apps.service_requests import services as svc
from apps.service_requests.models import ServiceRequest, ServiceRequestComment
from apps.service_requests.services import ServiceRequestError

pytestmark = pytest.mark.django_db


def test_member_submits_and_officer_resolves(department, member, officer, membership):
    req = svc.submit(
        actor=member,
        department=department,
        request_type="introductory_letter",
        title="Letter for attachment",
        description="Needed for industrial attachment.",
    )
    assert req.requester_membership == membership
    assert req.request_status == ServiceRequest.Status.SUBMITTED
    assert req.visibility_level == ServiceRequest.Visibility.DEPARTMENT

    svc.assign(req, actor=officer, assignee=officer)
    req.refresh_from_db()
    assert req.request_status == ServiceRequest.Status.TRIAGED

    svc.set_status(req, actor=officer, status=ServiceRequest.Status.RESOLVED, summary="Ready for collection.")
    req.refresh_from_db()
    assert req.resolved_at is not None
    assert req.resolution_summary == "Ready for collection."

    svc.close(req, actor=member)
    req.refresh_from_db()
    assert req.request_status == ServiceRequest.Status.CLOSED


def test_resolving_requires_a_summary_for_the_requester(make_request, officer):
    req = make_request(assigned_to_user=officer)
    with pytest.raises(ServiceRequestError, match="how it was resolved"):
        svc.set_status(req, actor=officer, status=ServiceRequest.Status.RESOLVED)


def test_only_a_resolved_request_can_be_closed(make_request, officer, member):
    req = make_request()
    with pytest.raises(ServiceRequestError, match="resolved or rejected"):
        svc.close(req, actor=member)


def test_a_user_without_a_membership_cannot_submit(department, make_user):
    outsider = make_user("student_member")
    with pytest.raises(ServiceRequestError, match="active membership"):
        svc.submit(
            actor=outsider,
            department=department,
            request_type="admin_question",
            title="x",
            description="y",
        )


def test_assignee_must_be_able_to_handle_requests(make_request, officer, member):
    req = make_request()
    with pytest.raises(ServiceRequestError, match="can't be assigned"):
        svc.assign(req, actor=officer, assignee=member)


# --- restricted visibility -------------------------------------------------------------------


def test_sensitive_types_are_forced_private(department, member):
    """A member can't accidentally publish their own welfare case."""
    for request_type in ("welfare", "result_query"):
        req = svc.submit(
            actor=member,
            department=department,
            request_type=request_type,
            title="Private matter",
            description="Details.",
            visibility=ServiceRequest.Visibility.DEPARTMENT,  # asked for the open queue...
        )
        assert req.visibility_level == ServiceRequest.Visibility.RESTRICTED  # ...overridden


def test_restricted_request_is_hidden_from_the_general_queue(make_request, member, officer):
    """requests.manage alone is deliberately not enough to open a restricted case."""
    restricted = make_request(
        request_type="welfare",
        title="Welfare concern",
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
    )
    assert restricted not in svc.visible_requests(officer, restricted.department)
    assert not svc.can_view(officer, restricted)
    assert not svc.is_handling_officer(officer, restricted)
    # The requester always sees their own.
    assert svc.can_view(member, restricted)


def test_restricted_request_is_visible_to_its_assignee(make_request, officer, other_officer):
    restricted = make_request(
        request_type="welfare",
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
        assigned_to_user=officer,
    )
    assert svc.can_view(officer, restricted)
    assert svc.is_handling_officer(officer, restricted)
    # A different officer still can't see it.
    assert not svc.can_view(other_officer, restricted)


def test_unassigned_officer_cannot_act_on_a_restricted_request(make_request, officer, other_officer):
    restricted = make_request(
        request_type="welfare",
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
        assigned_to_user=officer,
    )
    with pytest.raises(PermissionDenied):
        svc.set_status(restricted, actor=other_officer, status=ServiceRequest.Status.RESOLVED, summary="x")
    with pytest.raises(PermissionDenied):
        svc.assign(restricted, actor=other_officer, assignee=other_officer)
    with pytest.raises(PermissionDenied):
        svc.comment(restricted, actor=other_officer, body="Let me see this.")


def test_officer_can_act_on_an_ordinary_request(make_request, officer):
    req = make_request()
    assert svc.is_handling_officer(officer, req)
    svc.set_status(req, actor=officer, status=ServiceRequest.Status.IN_PROGRESS)
    req.refresh_from_db()
    assert req.request_status == ServiceRequest.Status.IN_PROGRESS


# --- staff-only comments ----------------------------------------------------------------------


def test_staff_only_comments_are_hidden_from_the_requester(make_request, member, officer):
    req = make_request(assigned_to_user=officer)
    svc.comment(req, actor=officer, body="We are looking into this.")
    svc.comment(req, actor=officer, body="Chase the works department.", staff_only=True)

    requester_view = svc.visible_comments(member, req)
    assert requester_view.count() == 1
    assert "works department" not in requester_view.first().body
    assert svc.visible_comments(officer, req).count() == 2


def test_requester_cannot_write_a_staff_only_note(make_request, member):
    req = make_request()
    with pytest.raises(PermissionDenied, match="staff-only"):
        svc.comment(req, actor=member, body="hidden", staff_only=True)


def test_an_officer_who_is_also_the_requester_sees_no_staff_notes_on_their_own_case(
    department, officer, make_membership, make_request
):
    """Being an officer doesn't let you read staff notes about yourself."""
    own_membership = make_membership(user=officer)
    req = make_request(
        requester_membership=own_membership,
        visibility_level=ServiceRequest.Visibility.RESTRICTED,
        request_type="welfare",
    )
    other_officer_user = UserFactory()
    ServiceRequestComment.objects.create(
        service_request=req,
        author_user=other_officer_user,
        body="Escalate to the HoD.",
        visibility=ServiceRequestComment.Visibility.STAFF_ONLY,
    )
    # Restricted and not assigned to them, so they are the requester here, not the handler.
    assert not svc.is_handling_officer(officer, req)
    assert svc.visible_comments(officer, req).count() == 0


def test_a_stranger_cannot_comment(make_request, make_user):
    req = make_request()
    stranger = make_user("student_member")
    with pytest.raises(PermissionDenied):
        svc.comment(req, actor=stranger, body="hello")


def test_empty_comments_are_refused(make_request, member):
    req = make_request()
    with pytest.raises(ServiceRequestError, match="Write something"):
        svc.comment(req, actor=member, body="   ")


# --- cross-department leaks --------------------------------------------------------------------


def test_requests_do_not_leak_across_departments(
    officer, department, other_department, make_other_membership
):
    foreign = ServiceRequest.objects.create(
        department=other_department,
        requester_membership=make_other_membership(),
        request_type="admin_question",
        title="Their business",
        description="Not yours.",
    )
    assert foreign not in svc.visible_requests(officer, department)
    assert not svc.can_view(officer, foreign)
    assert not svc.is_handling_officer(officer, foreign)
    with pytest.raises(PermissionDenied):
        svc.set_status(foreign, actor=officer, status=ServiceRequest.Status.RESOLVED, summary="x")


def test_member_sees_only_their_own_requests(department, member, make_membership, make_request):
    mine = make_request()
    theirs = make_request(requester_membership=make_membership(user=UserFactory()))
    visible = svc.visible_requests(member, department)
    assert mine in visible
    assert theirs not in visible


def test_stats_count_open_and_resolved(make_request, officer, department):
    make_request()
    resolved = make_request(assigned_to_user=officer)
    svc.set_status(resolved, actor=officer, status=ServiceRequest.Status.RESOLVED, summary="done")
    stats = svc.resolution_stats(department)
    assert stats["total"] == 2
    assert stats["open"] == 1
    assert stats["resolved"] == 1
    assert stats["average_days"] is not None
