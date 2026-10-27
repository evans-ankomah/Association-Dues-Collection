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
from apps.workspace import services as svc
from apps.workspace.models import Committee, CommitteeMember, Meeting, Task
from apps.workspace.services import WorkspaceError

pytestmark = pytest.mark.django_db


# --- committees -------------------------------------------------------------------------------


def test_creating_a_committee_with_a_chair_seats_them(department, session, secretary, membership):
    committee = svc.create_committee(
        actor=secretary,
        department=department,
        academic_session=session,
        name="Finance Committee",
        chair=membership,
    )
    seat = committee.members.get(department_membership=membership)
    assert seat.role_title == "Chair"
    assert seat.membership_status == CommitteeMember.Status.ACTIVE


def test_a_person_sits_on_a_committee_once(committee, secretary, membership):
    svc.add_member(committee, actor=secretary, membership=membership)
    with pytest.raises(WorkspaceError, match="already on this committee"):
        svc.add_member(committee, actor=secretary, membership=membership)
    assert committee.members.count() == 1


def test_rejoining_reactivates_the_same_seat(committee, secretary, membership):
    seat = svc.add_member(committee, actor=secretary, membership=membership)
    svc.end_membership(seat, actor=secretary)
    again = svc.add_member(committee, actor=secretary, membership=membership, role_title="Secretary")
    assert again.pk == seat.pk
    assert again.membership_status == CommitteeMember.Status.ACTIVE
    assert again.left_at is None
    assert committee.members.count() == 1


def test_ending_a_seat_keeps_the_history(committee, secretary, membership):
    seat = svc.add_member(committee, actor=secretary, membership=membership)
    svc.end_membership(seat, actor=secretary)
    seat.refresh_from_db()
    assert seat.membership_status == CommitteeMember.Status.ENDED
    assert seat.left_at is not None
    assert CommitteeMember.objects.filter(pk=seat.pk).exists()


def test_archiving_a_committee_ends_every_seat(committee, secretary, membership, make_membership):
    svc.add_member(committee, actor=secretary, membership=membership)
    svc.add_member(committee, actor=secretary, membership=make_membership(user=UserFactory()))
    svc.set_committee_status(committee, actor=secretary, status=Committee.Status.ARCHIVED)
    assert not committee.members.filter(membership_status=CommitteeMember.Status.ACTIVE).exists()


def test_an_archived_committee_takes_no_new_members(committee, secretary, membership):
    svc.set_committee_status(committee, actor=secretary, status=Committee.Status.ARCHIVED)
    with pytest.raises(WorkspaceError, match="archived"):
        svc.add_member(committee, actor=secretary, membership=membership)


# --- meetings ---------------------------------------------------------------------------------


def test_scheduling_and_holding_a_meeting(department, secretary, committee):
    meeting = svc.schedule_meeting(
        actor=secretary,
        department=department,
        title="Welfare cases review",
        scheduled_at=timezone.now() + datetime.timedelta(days=3),
        committee=committee,
    )
    assert meeting.meeting_status == Meeting.Status.SCHEDULED
    svc.set_meeting_status(meeting, actor=secretary, status=Meeting.Status.HELD)
    meeting.refresh_from_db()
    assert meeting.meeting_status == Meeting.Status.HELD


def test_attaching_minutes_marks_the_meeting_held(department, secretary, tmp_path, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "documents": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.documents import services as docs

    document = docs.upload(
        actor=secretary,
        department=department,
        upload_file=SimpleUploadedFile("m.pdf", b"%PDF-1.4", content_type="application/pdf"),
        title="Minutes",
        category="minutes",
    )
    meeting = svc.schedule_meeting(
        actor=secretary,
        department=department,
        title="Executive meeting",
        scheduled_at=timezone.now() - datetime.timedelta(days=1),
    )
    svc.attach_minutes(meeting, actor=secretary, document=document)
    meeting.refresh_from_db()
    assert meeting.minutes_document == document
    assert meeting.meeting_status == Meeting.Status.HELD


# --- tasks ------------------------------------------------------------------------------------


def test_assignee_can_move_their_own_task(department, secretary, member):
    task = svc.create_task(actor=secretary, department=department, title="Book the venue", assignee=member)
    assert svc.can_update_task(member, task)
    svc.set_task_status(task, actor=member, status=Task.Status.DONE)
    task.refresh_from_db()
    assert task.task_status == Task.Status.DONE
    assert task.completed_at is not None


def test_a_member_cannot_move_somebody_elses_task(department, secretary, member, make_user):
    other = make_user("student_member")
    task = svc.create_task(actor=secretary, department=department, title="Design flyers", assignee=other)
    assert not svc.can_update_task(member, task)
    with pytest.raises(PermissionDenied):
        svc.set_task_status(task, actor=member, status=Task.Status.DONE)


def test_only_a_manager_reassigns(department, secretary, member, make_user):
    """An assignee may finish their task but not hand it to someone else."""
    other = make_user("student_member")
    task = svc.create_task(actor=secretary, department=department, title="Confirm caterer", assignee=member)
    with pytest.raises(PermissionDenied):
        svc.assign_task(task, actor=member, assignee=other)
    svc.assign_task(task, actor=secretary, assignee=other)
    task.refresh_from_db()
    assert task.assigned_to_user == other


def test_a_member_cannot_create_a_task(department, member):
    with pytest.raises(PermissionDenied):
        svc.create_task(actor=member, department=department, title="Nope")


def test_overdue_tasks_are_counted(department, secretary, member):
    svc.create_task(
        actor=secretary,
        department=department,
        title="Late job",
        assignee=member,
        due_at=timezone.now() - datetime.timedelta(days=2),
    )
    svc.create_task(actor=secretary, department=department, title="Unassigned job")
    summary = svc.workspace_summary(department)
    assert summary["tasks_open"] == 2
    assert summary["tasks_overdue"] == 1
    assert summary["tasks_unassigned"] == 1


# --- cross-department leaks --------------------------------------------------------------------


def test_committees_management_does_not_leak_across_departments(secretary, department, session):
    other_dept = DepartmentFactory(institution=department.institution)
    other_session = AcademicSessionFactory(institution=department.institution, name="other")
    with pytest.raises(PermissionDenied):
        svc.create_committee(
            actor=secretary,
            department=other_dept,
            academic_session=other_session,
            name="Theirs",
        )
    foreign = Committee.objects.create(
        department=other_dept,
        academic_session=other_session,
        name="Theirs",
        created_by=UserFactory(),
    )
    with pytest.raises(PermissionDenied):
        svc.set_committee_status(foreign, actor=secretary, status=Committee.Status.ARCHIVED)
    with pytest.raises(PermissionDenied):
        svc.add_member(foreign, actor=secretary, membership=MembershipFactory(department=other_dept))


def test_a_committee_cannot_seat_a_member_of_another_department(committee, secretary, department):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = MembershipFactory(department=other_dept)
    with pytest.raises(WorkspaceError, match="another department"):
        svc.add_member(committee, actor=secretary, membership=foreign)


def test_a_task_cannot_be_linked_to_another_departments_committee(department, secretary):
    other_dept = DepartmentFactory(institution=department.institution)
    other_session = AcademicSessionFactory(institution=department.institution, name="x")
    foreign = Committee.objects.create(
        department=other_dept,
        academic_session=other_session,
        name="Theirs",
        created_by=UserFactory(),
    )
    with pytest.raises(WorkspaceError, match="committee belongs to another department"):
        svc.create_task(actor=secretary, department=department, title="Cross link", committee=foreign)


def test_minutes_must_belong_to_the_same_department(department, secretary):
    from apps.documents.models import Document

    other_dept = DepartmentFactory(institution=department.institution)
    foreign = Document.objects.create(
        department=other_dept,
        uploaded_by=secretary,
        title="Their minutes",
        category="minutes",
        original_filename="x.pdf",
        storage_key="k",
        mime_type="application/pdf",
        file_size_bytes=1,
        checksum_sha256="0" * 64,
    )
    meeting = svc.schedule_meeting(
        actor=secretary,
        department=department,
        title="Executive meeting",
        scheduled_at=timezone.now(),
    )
    with pytest.raises(WorkspaceError, match="another department"):
        svc.attach_minutes(meeting, actor=secretary, document=foreign)
