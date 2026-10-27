import pytest

from apps.common.tests.factories import AcademicSessionFactory, DepartmentFactory, UserFactory
from apps.workspace import services as svc
from apps.workspace.models import Committee, Meeting, Task

pytestmark = pytest.mark.django_db


def test_member_sees_only_their_own_tasks(department, secretary, member, login, make_user):
    other = make_user("student_member")
    svc.create_task(actor=secretary, department=department, title="My job", assignee=member)
    svc.create_task(actor=secretary, department=department, title="Their job", assignee=other)
    body = login(member).get("/workspace/tasks/").content.decode()
    assert "My job" in body
    assert "Their job" not in body


def test_manager_sees_the_whole_board(department, secretary, member, login, make_user):
    other = make_user("student_member")
    svc.create_task(actor=secretary, department=department, title="My job", assignee=member)
    svc.create_task(actor=secretary, department=department, title="Their job", assignee=other)
    body = login(secretary).get("/workspace/tasks/").content.decode()
    assert "My job" in body
    assert "Their job" in body


def test_member_cannot_reach_committee_or_meeting_pages(committee, member, login, department, secretary):
    meeting = svc.schedule_meeting(
        actor=secretary, department=department, title="Exec", scheduled_at="2027-01-05T16:00:00Z"
    )
    client = login(member)
    assert client.get("/workspace/committees/").status_code == 403
    assert client.get(f"/workspace/committees/{committee.pk}/").status_code == 403
    assert client.get("/workspace/meetings/").status_code == 403
    assert client.get(f"/workspace/meetings/{meeting.pk}/").status_code == 403
    assert client.get("/workspace/tasks/new/").status_code == 403


def test_member_cannot_create_or_reassign_tasks_over_http(department, secretary, member, login):
    task = svc.create_task(actor=secretary, department=department, title="Mine", assignee=member)
    client = login(member)
    assert client.post("/workspace/tasks/new/", {"title": "Sneaky"}).status_code == 403
    response = client.post(
        f"/workspace/tasks/{task.pk}/action/", {"action": "assign", "assignee": str(secretary.pk)}
    )
    task.refresh_from_db()
    assert response.status_code == 302  # redirected with an error, not applied
    assert task.assigned_to_user == member


def test_assignee_can_mark_their_task_done_over_http(department, secretary, member, login):
    task = svc.create_task(actor=secretary, department=department, title="Mine", assignee=member)
    login(member).post(f"/workspace/tasks/{task.pk}/action/", {"action": "status", "status": "done"})
    task.refresh_from_db()
    assert task.task_status == Task.Status.DONE


def test_officer_cannot_reach_another_departments_workspace(secretary, login, department):
    other_dept = DepartmentFactory(institution=department.institution)
    other_session = AcademicSessionFactory(institution=department.institution, name="other")
    foreign_committee = Committee.objects.create(
        department=other_dept, academic_session=other_session, name="Theirs", created_by=UserFactory()
    )
    foreign_meeting = Meeting.objects.create(
        department=other_dept,
        title="Their meeting",
        scheduled_at="2027-01-05T16:00:00Z",
        created_by=UserFactory(),
    )
    foreign_task = Task.objects.create(department=other_dept, title="Their task", created_by=UserFactory())
    client = login(secretary)
    assert client.get(f"/workspace/committees/{foreign_committee.pk}/").status_code == 404
    assert client.get(f"/workspace/meetings/{foreign_meeting.pk}/").status_code == 404
    assert (
        client.post(
            f"/workspace/tasks/{foreign_task.pk}/action/", {"action": "status", "status": "done"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/workspace/committees/{foreign_committee.pk}/action/", {"action": "archived"}
        ).status_code
        == 404
    )


def test_committee_member_dropdown_only_lists_own_department(
    committee, secretary, login, department, make_membership
):
    mine = make_membership(user=UserFactory(with_profile__given_name="Yaa"))
    other_dept = DepartmentFactory(institution=department.institution)
    from apps.common.tests.factories import MembershipFactory

    MembershipFactory(department=other_dept, user=UserFactory(with_profile__given_name="Kofi"))
    body = login(secretary).get(f"/workspace/committees/{committee.pk}/").content.decode()
    assert str(mine.pk) in body
    assert "Kofi" not in body


def test_officer_adds_a_member_over_http(committee, secretary, login, membership):
    response = login(secretary).post(
        f"/workspace/committees/{committee.pk}/action/",
        {"action": "add_member", "membership": str(membership.pk), "role_title": "Secretary"},
    )
    assert response.status_code == 302
    assert committee.members.filter(department_membership=membership, role_title="Secretary").exists()


def test_anonymous_is_redirected_to_sign_in(client):
    assert client.get("/workspace/tasks/").status_code == 302
    assert client.get("/workspace/committees/").status_code == 302
