"""Committees, meetings and tasks — the departmental workspace.

Rules enforced here:
- `committees.manage` governs creating committees, meetings and tasks.
- Committee membership is drawn from the owning department only, and a person sits on a
  committee once: re-adding someone who left reactivates their seat instead of duplicating it.
- A meeting's minutes must be a document of the same department.
- Anyone may move a task that is assigned to them; everything else needs committees.manage.
  That lets an executive work their own list without being able to rewrite everyone else's.
- Committees are tied to an academic session, so handover is a new committee, not an edit.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.access.services import has_perm
from apps.audit.services import record, snapshot

from .models import Committee, CommitteeMember, Meeting, Task

MANAGE = "committees.manage"


class WorkspaceError(Exception):
    """A business-rule violation with a message safe to show to the user."""


def require_perm(actor, code, department):
    """Services re-check permissions so they're safe to call from views, the API or tasks."""
    if not has_perm(actor, code, department):
        raise PermissionDenied(f"Missing permission {code}.")


# --- committees -------------------------------------------------------------------------------


@transaction.atomic
def create_committee(*, actor, department, academic_session, name, description="", chair=None):
    require_perm(actor, MANAGE, department)
    if chair is not None and chair.department_id != department.pk:
        raise WorkspaceError("The chair must be a member of this department.")
    committee = Committee.objects.create(
        department=department,
        academic_session=academic_session,
        name=name,
        description=description or None,
        chair_membership=chair,
        created_by=actor,
    )
    record(
        "committee.created",
        committee,
        actor=actor,
        department=department,
        after=snapshot(committee, fields=["name", "committee_status"]),
    )
    if chair is not None:
        add_member(committee, actor=actor, membership=chair, role_title="Chair")
    return committee


@transaction.atomic
def add_member(committee, *, actor, membership, role_title=None):
    """Put someone on a committee. Re-adding a past member reactivates their seat."""
    department = committee.department
    require_perm(actor, MANAGE, department)
    if membership.department_id != department.pk:
        raise WorkspaceError("That member belongs to another department.")
    if committee.committee_status == Committee.Status.ARCHIVED:
        raise WorkspaceError("This committee is archived.")

    seat = CommitteeMember.objects.filter(committee=committee, department_membership=membership).first()
    if seat is not None:
        if seat.membership_status == CommitteeMember.Status.ACTIVE:
            raise WorkspaceError("They are already on this committee.")
        seat.membership_status = CommitteeMember.Status.ACTIVE
        seat.joined_at = timezone.now()
        seat.left_at = None
        seat.role_title = role_title or seat.role_title
        seat.save()
    else:
        seat = CommitteeMember.objects.create(
            committee=committee,
            department_membership=membership,
            role_title=role_title,
            joined_at=timezone.now(),
        )
    record(
        "committee.member_added",
        seat,
        actor=actor,
        department=department,
        after={"committee": str(committee.pk), "role_title": seat.role_title},
    )
    return seat


@transaction.atomic
def end_membership(seat, *, actor):
    """End someone's seat. History is kept — the row is never deleted."""
    department = seat.committee.department
    require_perm(actor, MANAGE, department)
    seat = CommitteeMember.objects.select_for_update().get(pk=seat.pk)
    if seat.membership_status == CommitteeMember.Status.ENDED:
        raise WorkspaceError("That seat has already ended.")
    before = snapshot(seat, fields=["membership_status", "left_at"])
    seat.membership_status = CommitteeMember.Status.ENDED
    seat.left_at = timezone.now()
    seat.save()
    record(
        "committee.member_ended",
        seat,
        actor=actor,
        department=department,
        before=before,
        after=snapshot(seat, fields=["membership_status", "left_at"]),
    )
    return seat


@transaction.atomic
def set_committee_status(committee, *, actor, status):
    require_perm(actor, MANAGE, committee.department)
    committee = Committee.objects.select_for_update().get(pk=committee.pk)
    before = {"status": committee.committee_status}
    committee.committee_status = status
    committee.save(update_fields=["committee_status"])
    if status == Committee.Status.ARCHIVED:
        committee.members.filter(membership_status=CommitteeMember.Status.ACTIVE).update(
            membership_status=CommitteeMember.Status.ENDED, left_at=timezone.now()
        )
    record(
        f"committee.{status}",
        committee,
        actor=actor,
        department=committee.department,
        before=before,
        after={"status": status},
    )
    return committee


# --- meetings ---------------------------------------------------------------------------------


@transaction.atomic
def schedule_meeting(*, actor, department, title, scheduled_at, committee=None, location_text=None):
    require_perm(actor, MANAGE, department)
    if committee is not None and committee.department_id != department.pk:
        raise WorkspaceError("That committee belongs to another department.")
    meeting = Meeting.objects.create(
        department=department,
        committee=committee,
        title=title,
        scheduled_at=scheduled_at,
        location_text=location_text or None,
        created_by=actor,
    )
    record(
        "meeting.scheduled",
        meeting,
        actor=actor,
        department=department,
        after=snapshot(meeting, fields=["title", "scheduled_at", "meeting_status"]),
    )
    return meeting


@transaction.atomic
def set_meeting_status(meeting, *, actor, status):
    require_perm(actor, MANAGE, meeting.department)
    meeting = Meeting.objects.select_for_update().get(pk=meeting.pk)
    before = {"status": meeting.meeting_status}
    meeting.meeting_status = status
    meeting.save(update_fields=["meeting_status"])
    record(
        f"meeting.{status}",
        meeting,
        actor=actor,
        department=meeting.department,
        before=before,
        after={"status": status},
    )
    return meeting


@transaction.atomic
def attach_minutes(meeting, *, actor, document):
    """Link an uploaded document as the minutes. It must belong to the same department."""
    department = meeting.department
    require_perm(actor, MANAGE, department)
    if document.department_id != department.pk:
        raise WorkspaceError("That document belongs to another department.")
    meeting = Meeting.objects.select_for_update().get(pk=meeting.pk)
    before = {"minutes_document": str(meeting.minutes_document_id or "")}
    meeting.minutes_document = document
    if meeting.meeting_status == Meeting.Status.SCHEDULED:
        meeting.meeting_status = Meeting.Status.HELD
    meeting.save()
    record(
        "meeting.minutes_attached",
        meeting,
        actor=actor,
        department=department,
        before=before,
        after={"minutes_document": str(document.pk)},
    )
    return meeting


# --- tasks ------------------------------------------------------------------------------------


@transaction.atomic
def create_task(
    *,
    actor,
    department,
    title,
    description="",
    priority=Task.Priority.NORMAL,
    assignee=None,
    assigned_membership=None,
    committee=None,
    event=None,
    meeting=None,
    due_at=None,
):
    require_perm(actor, MANAGE, department)
    for related, label in ((committee, "committee"), (event, "event"), (meeting, "meeting")):
        if related is not None and related.department_id != department.pk:
            raise WorkspaceError(f"That {label} belongs to another department.")
    if assigned_membership is not None and assigned_membership.department_id != department.pk:
        raise WorkspaceError("That member belongs to another department.")
    task = Task.objects.create(
        department=department,
        title=title,
        description=description or None,
        priority=priority,
        assigned_to_user=assignee,
        assigned_membership=assigned_membership,
        committee=committee,
        event=event,
        meeting=meeting,
        created_by=actor,
        due_at=due_at,
    )
    record(
        "task.created",
        task,
        actor=actor,
        department=department,
        after=snapshot(task, fields=["title", "task_status", "priority", "due_at"]),
    )
    return task


def can_update_task(user, task):
    """The assignee may move their own task; otherwise committees.manage is needed."""
    if task.assigned_to_user_id == user.pk:
        return True
    return has_perm(user, MANAGE, task.department)


@transaction.atomic
def set_task_status(task, *, actor, status):
    if not can_update_task(actor, task):
        raise PermissionDenied("You can't update this task.")
    task = Task.objects.select_for_update().get(pk=task.pk)
    before = snapshot(task, fields=["task_status", "completed_at"])
    task.task_status = status
    task.completed_at = timezone.now() if status == Task.Status.DONE else None
    task.save()
    record(
        f"task.{status}",
        task,
        actor=actor,
        department=task.department,
        before=before,
        after=snapshot(task, fields=["task_status", "completed_at"]),
    )
    return task


@transaction.atomic
def assign_task(task, *, actor, assignee, assigned_membership=None):
    """Reassignment is an organising decision, so it always needs committees.manage."""
    require_perm(actor, MANAGE, task.department)
    if assigned_membership is not None and assigned_membership.department_id != task.department_id:
        raise WorkspaceError("That member belongs to another department.")
    task = Task.objects.select_for_update().get(pk=task.pk)
    before = {"assigned_to_user": str(task.assigned_to_user_id or "")}
    task.assigned_to_user = assignee
    task.assigned_membership = assigned_membership
    task.save()
    record(
        "task.assigned",
        task,
        actor=actor,
        department=task.department,
        before=before,
        after={"assigned_to_user": str(assignee.pk) if assignee else ""},
    )
    return task


def my_tasks(user, department):
    return Task.objects.filter(department=department, assigned_to_user=user)


def task_board(department, *, committee=None, event=None, assignee=None, status=None):
    qs = Task.objects.filter(department=department).select_related(
        "assigned_to_user__profile", "committee", "event", "meeting"
    )
    if committee is not None:
        qs = qs.filter(committee=committee)
    if event is not None:
        qs = qs.filter(event=event)
    if assignee is not None:
        qs = qs.filter(assigned_to_user=assignee)
    if status:
        qs = qs.filter(task_status=status)
    return qs


def workspace_summary(department, *, session=None):
    """Counts for the operations dashboard."""
    committees = Committee.objects.filter(department=department)
    meetings = Meeting.objects.filter(department=department)
    tasks = Task.objects.filter(department=department)
    if session is not None:
        committees = committees.filter(academic_session=session)
    now = timezone.now()
    return {
        "committees": committees.filter(committee_status=Committee.Status.ACTIVE).count(),
        "meetings_upcoming": meetings.filter(
            meeting_status=Meeting.Status.SCHEDULED, scheduled_at__gte=now
        ).count(),
        "tasks_open": tasks.open().count(),
        "tasks_overdue": tasks.overdue(now).count(),
        "tasks_unassigned": tasks.open().filter(Q(assigned_to_user__isnull=True)).count(),
    }
