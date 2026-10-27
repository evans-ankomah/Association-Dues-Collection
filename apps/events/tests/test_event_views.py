import pytest

from apps.common.tests.factories import DepartmentFactory, MembershipFactory, UserFactory
from apps.events.models import Event, EventAttendance, EventRegistration

from .factories import EventFactory

pytestmark = pytest.mark.django_db


def test_member_sees_published_events_but_not_drafts(department, organiser, member, login):
    published = EventFactory(department=department, created_by=organiser, title="Career Talk")
    draft = EventFactory(
        department=department, created_by=organiser, title="Secret Planning", event_status=Event.Status.DRAFT
    )
    page = login(member).get("/events/?show=all")
    assert page.status_code == 200
    body = page.content.decode()
    assert "Career Talk" in body
    assert "Secret Planning" not in body
    assert login(member).get(f"/events/{published.pk}/").status_code == 200
    assert login(member).get(f"/events/{draft.pk}/").status_code == 403


def test_member_cannot_reach_organiser_pages(event, member, login):
    client = login(member)
    assert client.get("/events/new/").status_code == 403
    assert client.get(f"/events/{event.pk}/edit/").status_code == 403
    assert client.get(f"/events/{event.pk}/attendance/").status_code == 403
    assert client.get(f"/events/{event.pk}/attendance/search/?q=ama").status_code == 403
    assert client.post(f"/events/{event.pk}/action/", {"action": "publish"}).status_code == 403


def test_member_cannot_check_anyone_in_over_http(event, member, membership, login):
    response = login(member).post(
        f"/events/{event.pk}/attendance/check-in/", {"membership": str(membership.pk)}
    )
    assert response.status_code == 403
    assert not EventAttendance.objects.exists()


def test_organiser_cannot_reach_another_departments_event(organiser, login, department):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = EventFactory(department=other_dept, created_by=UserFactory())
    client = login(organiser)
    assert client.get(f"/events/{foreign.pk}/").status_code == 404
    assert client.get(f"/events/{foreign.pk}/edit/").status_code == 404
    assert client.get(f"/events/{foreign.pk}/attendance/").status_code == 404
    assert client.post(f"/events/{foreign.pk}/action/", {"action": "publish"}).status_code == 404


def test_organiser_cannot_cancel_a_foreign_registration(organiser, login, department):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = EventFactory(department=other_dept, created_by=UserFactory())
    registration = EventRegistration.objects.create(
        event=foreign, department_membership=MembershipFactory(department=other_dept)
    )
    assert login(organiser).post(f"/events/registrations/{registration.pk}/cancel/").status_code == 404


def test_organiser_cannot_check_in_a_foreign_member(event, organiser, login, department):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = MembershipFactory(department=other_dept)
    response = login(organiser).post(
        f"/events/{event.pk}/attendance/check-in/", {"membership": str(foreign.pk)}
    )
    assert response.status_code == 404
    assert not EventAttendance.objects.exists()


def test_member_search_only_returns_own_department(event, organiser, login, department, make_membership):
    mine = make_membership(user=UserFactory(with_profile__given_name="Akosua"))
    other_dept = DepartmentFactory(institution=department.institution)
    MembershipFactory(department=other_dept, user=UserFactory(with_profile__given_name="Akosua"))
    body = login(organiser).get(f"/events/{event.pk}/attendance/search/?q=Akosua").content.decode()
    assert str(mine.pk) in body
    assert body.count('name="membership"') == 1


def test_organiser_creates_and_publishes_an_event(organiser, login, department):
    response = login(organiser).post(
        "/events/new/",
        {
            "title": "CSE Week 2027",
            "event_type": "departmental_week",
            "description": "A week of activities.",
            "venue_text": "UMaT Auditorium",
            "starts_at": "2027-03-22T08:00",
            "ends_at": "2027-03-27T22:00",
            "capacity": "",
            "registration_required": "on",
            "publish": "1",
        },
    )
    event = Event.objects.get(title="CSE Week 2027")
    assert response.status_code == 302
    assert event.department == department
    assert event.created_by == organiser
    assert event.event_status == Event.Status.PUBLISHED


def test_member_registers_over_http(event, member, login, membership):
    response = login(member).post(f"/events/{event.pk}/register/")
    assert response.status_code == 302
    assert EventRegistration.objects.get(event=event, department_membership=membership)


def test_anonymous_is_redirected_to_sign_in(event, client):
    assert client.get("/events/").status_code == 302
    assert client.get(f"/events/{event.pk}/").status_code == 302
