import datetime

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.common.tests.factories import (
    AcademicSessionFactory,
    DepartmentFactory,
    MembershipFactory,
    UserFactory,
)
from apps.events import services as svc
from apps.events.models import Event, EventAttendance, EventRegistration
from apps.events.services import EventError

from .factories import EventFactory

pytestmark = pytest.mark.django_db


def test_member_registers_and_cancels(event, member, membership):
    registration = svc.register(event, actor=member)
    assert registration.registration_status == EventRegistration.Status.REGISTERED
    assert registration.department_membership == membership

    svc.cancel_registration(registration, actor=member)
    registration.refresh_from_db()
    assert registration.registration_status == EventRegistration.Status.CANCELLED
    assert registration.cancelled_at is not None


def test_registering_twice_is_refused(event, member, membership):
    svc.register(event, actor=member)
    with pytest.raises(EventError, match="already registered"):
        svc.register(event, actor=member)


def test_cancelling_frees_the_seat_for_a_new_registration(event, member, membership):
    registration = svc.register(event, actor=member)
    svc.cancel_registration(registration, actor=member)
    again = svc.register(event, actor=member)
    assert again.pk == registration.pk  # one row per member, reused
    assert again.registration_status == EventRegistration.Status.REGISTERED


def test_full_event_waitlists_then_promotes(department, organiser, make_user, make_membership, session):
    event = EventFactory(department=department, created_by=organiser, capacity=1)
    first = make_user("student_member", session=session)
    MembershipFactory(user=first, department=department, academic_session=session)
    second = make_user("student_member", session=session)
    MembershipFactory(user=second, department=department, academic_session=session)

    seated = svc.register(event, actor=first)
    waiting = svc.register(event, actor=second)
    assert seated.registration_status == EventRegistration.Status.REGISTERED
    assert waiting.registration_status == EventRegistration.Status.WAITLISTED

    svc.cancel_registration(seated, actor=first)
    waiting.refresh_from_db()
    assert waiting.registration_status == EventRegistration.Status.REGISTERED


def test_registration_needs_a_published_event(department, organiser, member):
    draft = EventFactory(department=department, created_by=organiser, event_status=Event.Status.DRAFT)
    with pytest.raises(EventError, match="published"):
        svc.register(draft, actor=member)


def test_registration_refused_for_a_finished_event(department, organiser, member):
    past = EventFactory(
        department=department,
        created_by=organiser,
        starts_at=timezone.now() - datetime.timedelta(days=3),
        ends_at=timezone.now() - datetime.timedelta(days=3, hours=-2),
    )
    with pytest.raises(EventError, match="already finished"):
        svc.register(past, actor=member)


def test_registration_refused_when_the_event_takes_none(department, organiser, member):
    walk_in = EventFactory(department=department, created_by=organiser, registration_required=False)
    with pytest.raises(EventError, match="doesn't take registrations"):
        svc.register(walk_in, actor=member)


def test_check_in_marks_the_registration_attended(event, organiser, member, membership):
    svc.register(event, actor=member)
    attendance = svc.check_in(event, actor=organiser, membership=membership)
    assert attendance.attendance_status == EventAttendance.Status.PRESENT
    assert attendance.checked_in_by == organiser
    assert (
        EventRegistration.objects.get(event=event, department_membership=membership).registration_status
        == EventRegistration.Status.ATTENDED
    )


def test_completing_an_event_marks_no_shows(department, organiser, member, membership):
    event = EventFactory(
        department=department,
        created_by=organiser,
        starts_at=timezone.now() - datetime.timedelta(hours=5),
        ends_at=timezone.now() - datetime.timedelta(hours=2),
    )
    registration = EventRegistration.objects.create(event=event, department_membership=membership)
    svc.close_registrations(event, actor=organiser)
    registration.refresh_from_db()
    event.refresh_from_db()
    assert registration.registration_status == EventRegistration.Status.NO_SHOW
    assert event.event_status == Event.Status.COMPLETED


def test_an_unfinished_event_cannot_be_completed(event, organiser):
    with pytest.raises(EventError, match="hasn't finished"):
        svc.close_registrations(event, actor=organiser)


def test_attendance_summary_counts(event, organiser, member, membership):
    svc.register(event, actor=member)
    svc.check_in(event, actor=organiser, membership=membership)
    summary = svc.attendance_summary(event)
    assert summary["registered"] == 1
    assert summary["present"] == 1
    assert summary["attendance_rate"] == 100


# --- permissions and leaks ------------------------------------------------------------------


def test_member_cannot_manage_events(event, member):
    with pytest.raises(PermissionDenied):
        svc.publish(event, actor=member)
    with pytest.raises(PermissionDenied):
        svc.set_status(event, actor=member, status=Event.Status.CANCELLED)
    with pytest.raises(PermissionDenied):
        svc.close_registrations(event, actor=member)


def test_member_cannot_check_anyone_in(event, member, membership):
    """Attendance is evidence an organiser records, never self-asserted."""
    with pytest.raises(PermissionDenied):
        svc.check_in(event, actor=member, membership=membership)


def test_member_cannot_register_somebody_else(event, member, make_membership):
    other = make_membership(user=UserFactory())
    with pytest.raises(PermissionDenied):
        svc.register(event, actor=member, membership=other)


def test_member_cannot_cancel_another_members_registration(event, member, make_membership, make_user):
    other_user = make_user("student_member")
    other = make_membership(user=other_user)
    registration = EventRegistration.objects.create(event=event, department_membership=other)
    with pytest.raises(PermissionDenied):
        svc.cancel_registration(registration, actor=member)


def test_organiser_cannot_register_a_member_of_another_department(event, organiser, department):
    other_dept = DepartmentFactory(institution=department.institution)
    other_session = AcademicSessionFactory(institution=department.institution, is_current=False, name="x")
    foreign = MembershipFactory(department=other_dept, academic_session=other_session)
    with pytest.raises(EventError, match="another department"):
        svc.register(event, actor=organiser, membership=foreign)


def test_organiser_cannot_check_in_a_member_of_another_department(event, organiser, department):
    other_dept = DepartmentFactory(institution=department.institution)
    other_session = AcademicSessionFactory(institution=department.institution, is_current=False, name="y")
    foreign = MembershipFactory(department=other_dept, academic_session=other_session)
    with pytest.raises(EventError, match="another department"):
        svc.check_in(event, actor=organiser, membership=foreign)


def test_permissions_do_not_leak_to_other_departments(organiser, department):
    """events.manage in one department grants nothing in another."""
    other = DepartmentFactory(institution=department.institution)
    foreign_event = EventFactory(department=other, created_by=UserFactory())
    with pytest.raises(PermissionDenied):
        svc.publish(foreign_event, actor=organiser)
    with pytest.raises(PermissionDenied):
        svc.check_in(foreign_event, actor=organiser, membership=MembershipFactory(department=other))
    assert not svc.can_view(organiser, foreign_event)


def test_drafts_are_hidden_from_members(department, organiser, member):
    draft = EventFactory(department=department, created_by=organiser, event_status=Event.Status.DRAFT)
    published = EventFactory(department=department, created_by=organiser)
    visible = svc.visible_events(member, department)
    assert published in visible
    assert draft not in visible
    assert not svc.can_view(member, draft)
    assert draft in svc.visible_events(organiser, department)


def test_a_user_without_a_membership_cannot_register(event, make_user):
    """A role in the department is not the same as being a member of it."""
    outsider = make_user("student_member")
    with pytest.raises(EventError, match="active membership"):
        svc.register(event, actor=outsider)
