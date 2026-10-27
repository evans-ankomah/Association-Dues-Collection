"""Service requests: submission, triage, assignment, comments and resolution.

Privacy rules, enforced here and not only in the templates:

- A `department` request is visible to the requester and to any `requests.manage` holder.
- A `restricted` request is visible ONLY to its requester and the officer it is assigned to.
  It never appears in the general queue, however senior the viewer. The product plan is
  explicit that sensitive categories must not be placed in a general request queue without
  safeguards, so holding `requests.manage` is deliberately not enough.
- Sensitive request types (welfare, result queries, complaints) are forced to `restricted`
  when submitted, so a member cannot accidentally publish their own sensitive case.
- `staff_only` comments are never shown to the requester; a requester who is also an officer
  still cannot read staff-only notes on their own request.
- Assigning a restricted request hands over access, so only an officer who can already see it
  may reassign it, and reassignment is audited.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.access.services import has_perm
from apps.audit.services import record, snapshot
from apps.memberships.models import DepartmentMembership

from .models import SENSITIVE_TYPES, ServiceRequest, ServiceRequestComment

CREATE = "requests.create"
MANAGE = "requests.manage"


class ServiceRequestError(Exception):
    """A business-rule violation with a message safe to show to the user."""


def require_perm(actor, code, department):
    """Services re-check permissions so they're safe to call from views, the API or tasks."""
    if not has_perm(actor, code, department):
        raise PermissionDenied(f"Missing permission {code}.")


def visible_requests(user, department):
    """Requests in `department` that `user` may see.

    Officers see the department queue plus any restricted request assigned to them.
    Everyone sees their own requests, restricted or not.
    """
    qs = ServiceRequest.objects.filter(department=department)
    mine = Q(requester_membership__user=user)
    if has_perm(user, MANAGE, department):
        return qs.filter(
            mine | Q(visibility_level=ServiceRequest.Visibility.DEPARTMENT) | Q(assigned_to_user=user)
        ).distinct()
    return qs.filter(mine)


def can_view(user, service_request):
    return visible_requests(user, service_request.department).filter(pk=service_request.pk).exists()


def visible_comments(user, service_request):
    """Comments on a request. Staff-only notes are hidden from the requester."""
    qs = ServiceRequestComment.objects.filter(service_request=service_request)
    if is_handling_officer(user, service_request):
        return qs.select_related("author_user__profile")
    return qs.filter(visibility=ServiceRequestComment.Visibility.REQUESTER_VISIBLE).select_related(
        "author_user__profile"
    )


def is_handling_officer(user, service_request):
    """True when the user is acting as an officer on this request (not merely its requester).

    For a restricted request that means being the assignee: `requests.manage` alone never
    opens a restricted case.
    """
    department = service_request.department
    if not has_perm(user, MANAGE, department):
        return False
    if service_request.is_restricted:
        return service_request.assigned_to_user_id == user.pk
    return True


def _require_handling_officer(actor, service_request):
    if not is_handling_officer(actor, service_request):
        raise PermissionDenied("You can't act on this request.")


def _membership_for(user, department):
    return DepartmentMembership.objects.filter(
        user=user, department=department, membership_status=DepartmentMembership.Status.ACTIVE
    ).first()


@transaction.atomic
def submit(
    *,
    actor,
    department,
    request_type,
    title,
    description,
    priority=ServiceRequest.Priority.NORMAL,
    visibility=None,
    due_at=None,
):
    """A member raises a request. Sensitive types are always restricted."""
    require_perm(actor, CREATE, department)
    membership = _membership_for(actor, department)
    if membership is None:
        raise ServiceRequestError("You need an active membership of this department to submit a request.")
    if request_type in SENSITIVE_TYPES:
        visibility = ServiceRequest.Visibility.RESTRICTED
    service_request = ServiceRequest.objects.create(
        department=department,
        requester_membership=membership,
        request_type=request_type,
        title=title,
        description=description,
        priority=priority,
        visibility_level=visibility or ServiceRequest.Visibility.DEPARTMENT,
        due_at=due_at,
        submitted_at=timezone.now(),
    )
    record(
        "service_request.submitted",
        service_request,
        actor=actor,
        department=department,
        after=snapshot(service_request, fields=["request_type", "priority", "visibility_level"]),
    )
    return service_request


@transaction.atomic
def assign(service_request, *, actor, assignee):
    """Hand the request to an officer. Only someone who can already see it may reassign it."""
    department = service_request.department
    _require_handling_officer(actor, service_request)
    if assignee is not None and not has_perm(assignee, MANAGE, department):
        raise ServiceRequestError("That person can't be assigned requests in this department.")
    service_request = ServiceRequest.objects.select_for_update().get(pk=service_request.pk)
    before = snapshot(service_request, fields=["assigned_to_user", "request_status"])
    service_request.assigned_to_user = assignee
    if service_request.request_status == ServiceRequest.Status.SUBMITTED and assignee is not None:
        service_request.request_status = ServiceRequest.Status.TRIAGED
    service_request.save()
    record(
        "service_request.assigned",
        service_request,
        actor=actor,
        department=department,
        before=before,
        after=snapshot(service_request, fields=["assigned_to_user", "request_status"]),
    )
    return service_request


@transaction.atomic
def set_status(service_request, *, actor, status, summary=""):
    """Move the request along. Resolving or rejecting needs a summary the requester can read."""
    department = service_request.department
    _require_handling_officer(actor, service_request)
    service_request = ServiceRequest.objects.select_for_update().get(pk=service_request.pk)
    if service_request.request_status == ServiceRequest.Status.CLOSED:
        raise ServiceRequestError("This request is closed.")
    closing = status in (ServiceRequest.Status.RESOLVED, ServiceRequest.Status.REJECTED)
    if closing and not (summary or service_request.resolution_summary):
        raise ServiceRequestError("Say how it was resolved so the requester knows what happened.")

    before = snapshot(service_request, fields=["request_status", "resolved_at"])
    service_request.request_status = status
    if closing:
        service_request.resolved_at = timezone.now()
        service_request.resolution_summary = summary or service_request.resolution_summary
    service_request.save()
    record(
        f"service_request.{status}",
        service_request,
        actor=actor,
        department=department,
        before=before,
        after=snapshot(service_request, fields=["request_status", "resolved_at"]),
    )
    return service_request


@transaction.atomic
def close(service_request, *, actor):
    """The requester accepts the outcome, or an officer closes a resolved request."""
    department = service_request.department
    is_requester = service_request.requester_user_id == actor.pk
    if not is_requester:
        _require_handling_officer(actor, service_request)
    service_request = ServiceRequest.objects.select_for_update().get(pk=service_request.pk)
    if service_request.request_status not in (
        ServiceRequest.Status.RESOLVED,
        ServiceRequest.Status.REJECTED,
    ):
        raise ServiceRequestError("Only a resolved or rejected request can be closed.")
    before = {"status": service_request.request_status}
    service_request.request_status = ServiceRequest.Status.CLOSED
    service_request.save(update_fields=["request_status"])
    record(
        "service_request.closed",
        service_request,
        actor=actor,
        department=department,
        before=before,
        after={"status": service_request.request_status},
    )
    return service_request


@transaction.atomic
def comment(service_request, *, actor, body, staff_only=False):
    """Add a note. Only a handling officer may write a staff-only one."""
    department = service_request.department
    is_requester = service_request.requester_user_id == actor.pk
    is_officer = is_handling_officer(actor, service_request)
    if not is_requester and not is_officer:
        raise PermissionDenied("You can't comment on this request.")
    if staff_only and not is_officer:
        raise PermissionDenied("Only an officer handling this request can leave a staff-only note.")
    if not body.strip():
        raise ServiceRequestError("Write something first.")

    note = ServiceRequestComment.objects.create(
        service_request=service_request,
        author_user=actor,
        body=body.strip(),
        visibility=(
            ServiceRequestComment.Visibility.STAFF_ONLY
            if staff_only
            else ServiceRequestComment.Visibility.REQUESTER_VISIBLE
        ),
    )
    record(
        "service_request.commented",
        note,
        actor=actor,
        department=department,
        after={"visibility": note.visibility, "request": str(service_request.pk)},
    )
    return note


def queue_for(user, department, *, status=None, mine_only=False):
    """The officer queue, honouring restricted visibility."""
    qs = visible_requests(user, department).select_related(
        "requester_membership__user__profile", "assigned_to_user__profile"
    )
    if status:
        qs = qs.filter(request_status=status)
    if mine_only:
        qs = qs.filter(assigned_to_user=user)
    return qs


def resolution_stats(department, *, since=None):
    """Volume and resolution time for the operational report."""
    qs = ServiceRequest.objects.filter(department=department)
    if since is not None:
        qs = qs.filter(submitted_at__gte=since)
    resolved = qs.filter(resolved_at__isnull=False)
    durations = [
        (r.resolved_at - r.submitted_at).total_seconds() / 86400
        for r in resolved.only("resolved_at", "submitted_at")
    ]
    return {
        "total": qs.count(),
        "open": qs.open().count(),
        "resolved": resolved.count(),
        "overdue": sum(1 for r in qs.open().only("due_at", "request_status") if r.is_overdue),
        "average_days": (sum(durations) / len(durations)) if durations else None,
    }
