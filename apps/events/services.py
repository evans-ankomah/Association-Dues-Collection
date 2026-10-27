"""Event lifecycle, registration and attendance.

Rules enforced here (never only in the template):
- Only `events.manage` holders create, publish or cancel an event.
- Members register themselves; an organiser may register or check in anyone in the department.
- Registration respects capacity: once full, further members are waitlisted rather than refused,
  and cancelling a seat promotes the longest-waiting person.
- Attendance is only recorded for a published or completed event, and only for members of the
  event's own department.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.access.services import has_perm, permission_codes
from apps.audit.services import record, snapshot
from apps.memberships.models import DepartmentMembership

from .models import Event, EventAttendance, EventRegistration

MANAGE = "events.manage"
REGISTER = "events.register"


class EventError(Exception):
    """A business-rule violation with a message safe to show to the user."""


def require_perm(actor, code, department):
    """Services re-check permissions so they're safe to call from views, the API or tasks."""
    if not has_perm(actor, code, department):
        raise PermissionDenied(f"Missing permission {code}.")


def visible_events(user, department):
    """Events in `department` the user may see: organisers see every state, members only published.

    A user with no role in `department` sees nothing: holding events.manage somewhere else
    must not reveal another department's calendar.
    """
    if not permission_codes(user, department):
        return Event.objects.none()
    qs = Event.objects.filter(department=department)
    return qs if has_perm(user, MANAGE, department) else qs.visible_to_members()


def can_view(user, event):
    return visible_events(user, event.department).filter(pk=event.pk).exists()


def _membership_for(user, event):
    """The user's own membership in the event's department, or None."""
    return DepartmentMembership.objects.filter(
        user=user, department=event.department, membership_status=DepartmentMembership.Status.ACTIVE
    ).first()


@transaction.atomic
def publish(event, *, actor):
    require_perm(actor, MANAGE, event.department)
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.event_status in (Event.Status.CANCELLED, Event.Status.COMPLETED):
        raise EventError("A cancelled or completed event can't be published.")
    before = snapshot(event)
    event.event_status = Event.Status.PUBLISHED
    event.published_at = event.published_at or timezone.now()
    event.approved_by = actor
    event.save()
    record(
        "event.published",
        event,
        actor=actor,
        department=event.department,
        before=before,
        after=snapshot(event),
    )
    return event


@transaction.atomic
def set_status(event, *, actor, status):
    """Cancel, complete or return an event to draft."""
    require_perm(actor, MANAGE, event.department)
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.event_status == status:
        raise EventError("The event is already in that state.")
    before = {"status": event.event_status}
    event.event_status = status
    event.save(update_fields=["event_status"])
    record(
        f"event.{status}",
        event,
        actor=actor,
        department=event.department,
        before=before,
        after={"status": status},
    )
    return event


@transaction.atomic
def register(event, *, actor, membership=None):
    """Register a member. `membership` is for organisers registering somebody else.

    Returns the registration; its status is `waitlisted` when the event is already full.
    """
    department = event.department
    if membership is None:
        require_perm(actor, REGISTER, department)
        membership = _membership_for(actor, event)
        if membership is None:
            raise EventError("You need an active membership of this department to register.")
    else:
        require_perm(actor, MANAGE, department)
        if membership.department_id != department.pk:
            raise EventError("That member belongs to another department.")

    event = Event.objects.select_for_update().get(pk=event.pk)
    if not event.registration_required:
        raise EventError("This event doesn't take registrations.")
    if event.event_status != Event.Status.PUBLISHED:
        raise EventError("Registration opens once the event is published.")
    if event.ends_at < timezone.now():
        raise EventError("This event has already finished.")

    existing = EventRegistration.objects.filter(event=event, department_membership=membership).first()
    if existing is not None and existing.registration_status != EventRegistration.Status.CANCELLED:
        raise EventError("That member is already registered.")

    status = EventRegistration.Status.WAITLISTED if event.is_full else EventRegistration.Status.REGISTERED
    now = timezone.now()
    if existing is not None:  # re-registering after a cancellation keeps one row per member
        existing.registration_status = status
        existing.registered_at = now
        existing.cancelled_at = None
        existing.save()
        registration = existing
    else:
        registration = EventRegistration.objects.create(
            event=event,
            department_membership=membership,
            registration_status=status,
            registered_at=now,
        )
    record(
        "event.registered" if status == EventRegistration.Status.REGISTERED else "event.waitlisted",
        registration,
        actor=actor,
        department=department,
        after=snapshot(registration),
    )
    return registration


@transaction.atomic
def cancel_registration(registration, *, actor):
    """Give up a seat. Members may cancel their own; organisers may cancel anyone's."""
    department = registration.event.department
    is_own = registration.department_membership.user_id == actor.pk
    if not is_own:
        require_perm(actor, MANAGE, department)
    elif not has_perm(actor, REGISTER, department):
        raise PermissionDenied(f"Missing permission {REGISTER}.")

    registration = EventRegistration.objects.select_for_update().get(pk=registration.pk)
    if registration.registration_status == EventRegistration.Status.CANCELLED:
        raise EventError("That registration is already cancelled.")
    if registration.registration_status == EventRegistration.Status.ATTENDED:
        raise EventError("Attendance has already been recorded for this member.")
    before = snapshot(registration)
    registration.registration_status = EventRegistration.Status.CANCELLED
    registration.cancelled_at = timezone.now()
    registration.save()
    record(
        "event.registration_cancelled",
        registration,
        actor=actor,
        department=department,
        before=before,
        after=snapshot(registration),
    )
    _promote_from_waitlist(registration.event, actor=actor)
    return registration


def _promote_from_waitlist(event, *, actor):
    """Move the longest-waiting member into a seat freed by a cancellation."""
    if event.capacity is None or event.is_full:
        return None
    nxt = (
        EventRegistration.objects.select_for_update()
        .filter(event=event, registration_status=EventRegistration.Status.WAITLISTED)
        .order_by("registered_at")
        .first()
    )
    if nxt is None:
        return None
    nxt.registration_status = EventRegistration.Status.REGISTERED
    nxt.save(update_fields=["registration_status"])
    record("event.promoted_from_waitlist", nxt, actor=actor, department=event.department)
    return nxt


@transaction.atomic
def check_in(event, *, actor, membership, status=EventAttendance.Status.PRESENT, method=None):
    """Record attendance. Organisers only — attendance is evidence, not self-asserted."""
    department = event.department
    require_perm(actor, MANAGE, department)
    if membership.department_id != department.pk:
        raise EventError("That member belongs to another department.")
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.event_status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED):
        raise EventError("Attendance is recorded for published or completed events.")

    now = timezone.now()
    attendance, created = EventAttendance.objects.update_or_create(
        event=event,
        department_membership=membership,
        defaults={
            "attendance_status": status,
            "checked_in_at": now,
            "checked_in_by": actor,
            "checkin_method": method or EventAttendance.Method.MANUAL,
        },
    )
    # A registered member who turns up has attended.
    EventRegistration.objects.filter(
        event=event,
        department_membership=membership,
        registration_status__in=(
            EventRegistration.Status.REGISTERED,
            EventRegistration.Status.WAITLISTED,
        ),
    ).update(registration_status=EventRegistration.Status.ATTENDED, updated_at=now)
    record(
        "event.checked_in" if created else "event.attendance_updated",
        attendance,
        actor=actor,
        department=department,
        after=snapshot(attendance),
    )
    return attendance


@transaction.atomic
def close_registrations(event, *, actor):
    """Mark an event completed and flag registered members who never showed up."""
    require_perm(actor, MANAGE, event.department)
    event = Event.objects.select_for_update().get(pk=event.pk)
    if event.ends_at > timezone.now():
        raise EventError("This event hasn't finished yet.")
    no_shows = EventRegistration.objects.filter(
        event=event,
        registration_status__in=(
            EventRegistration.Status.REGISTERED,
            EventRegistration.Status.WAITLISTED,
        ),
    ).update(registration_status=EventRegistration.Status.NO_SHOW, updated_at=timezone.now())
    event.event_status = Event.Status.COMPLETED
    event.save(update_fields=["event_status"])
    record(
        "event.completed",
        event,
        actor=actor,
        department=event.department,
        after={"status": event.event_status, "no_shows": no_shows},
    )
    return event


def attendance_summary(event):
    """Registration and attendance counts for the event report."""
    registrations = EventRegistration.objects.filter(event=event)
    attendance = EventAttendance.objects.filter(event=event)
    present = attendance.filter(
        attendance_status__in=(EventAttendance.Status.PRESENT, EventAttendance.Status.LATE)
    ).count()
    registered = registrations.exclude(registration_status=EventRegistration.Status.CANCELLED).count()
    return {
        "registered": registered,
        "waitlisted": registrations.filter(registration_status=EventRegistration.Status.WAITLISTED).count(),
        "cancelled": registrations.filter(registration_status=EventRegistration.Status.CANCELLED).count(),
        "no_shows": registrations.filter(registration_status=EventRegistration.Status.NO_SHOW).count(),
        "present": present,
        "attendance_rate": (present / registered * 100) if registered else None,
    }
