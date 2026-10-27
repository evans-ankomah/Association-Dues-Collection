import datetime

import pytest
from django.utils import timezone

from apps.common.tests.factories import DepartmentFactory, UserFactory
from apps.resources import services as svc
from apps.resources.models import Asset, ResourceBooking

pytestmark = pytest.mark.django_db


def _form_time(when):
    return when.strftime("%Y-%m-%dT%H:%M")


def test_member_books_over_http(asset, member, login, slot):
    starts, ends = slot()
    response = login(member).post(
        f"/resources/{asset.pk}/book/",
        {
            "starts_at": _form_time(starts),
            "ends_at": _form_time(ends),
            "purpose": "Final-year project demo",
        },
    )
    assert response.status_code == 302
    booking = ResourceBooking.objects.get(asset=asset)
    assert booking.requested_by_user == member
    assert booking.booking_status == ResourceBooking.Status.REQUESTED


def test_overlapping_approval_is_refused_over_http(asset, member, custodian, login, make_user, slot):
    starts, ends = slot()
    first = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="A")
    second = svc.request_booking(
        asset,
        actor=make_user("student_member"),
        starts_at=starts + datetime.timedelta(minutes=30),
        ends_at=ends,
        purpose="B",
    )
    client = login(custodian)
    client.post(f"/resources/bookings/{first.pk}/action/", {"action": "approve"})
    client.post(f"/resources/bookings/{second.pk}/action/", {"action": "approve"})
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.booking_status == ResourceBooking.Status.APPROVED
    assert second.booking_status == ResourceBooking.Status.REQUESTED


def test_member_cannot_approve_or_edit_assets(asset, member, custodian, login, slot):
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="A")
    client = login(member)
    assert client.get("/resources/new/").status_code == 403
    assert client.get(f"/resources/{asset.pk}/edit/").status_code == 403
    client.post(f"/resources/bookings/{booking.pk}/action/", {"action": "approve"})
    booking.refresh_from_db()
    assert booking.booking_status == ResourceBooking.Status.REQUESTED


def test_member_sees_only_their_own_bookings(asset, member, login, make_user, slot):
    starts, ends = slot()
    svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Mine only")
    other = make_user("student_member")
    svc.request_booking(
        asset,
        actor=other,
        starts_at=starts + datetime.timedelta(days=2),
        ends_at=ends + datetime.timedelta(days=2),
        purpose="Theirs only",
    )
    body = login(member).get("/resources/bookings/").content.decode()
    mine = ResourceBooking.objects.get(requested_by_user=member)
    theirs = ResourceBooking.objects.get(requested_by_user=other)
    assert str(mine.pk) in body
    assert str(theirs.pk) not in body


def test_custodian_cannot_reach_another_departments_asset(custodian, login, department, slot):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = Asset.objects.create(department=other_dept, asset_tag="X-1", name="Theirs")
    booking = ResourceBooking.objects.create(
        asset=foreign,
        requested_by_user=UserFactory(),
        starts_at=slot()[0],
        ends_at=slot()[1],
        purpose="Theirs",
    )
    client = login(custodian)
    assert client.get(f"/resources/{foreign.pk}/").status_code == 404
    assert client.get(f"/resources/{foreign.pk}/edit/").status_code == 404
    assert client.post(f"/resources/{foreign.pk}/book/", {}).status_code == 404
    assert client.post(f"/resources/bookings/{booking.pk}/action/", {"action": "approve"}).status_code == 404


def test_retired_assets_are_hidden_from_members(department, custodian, member, login):
    svc.create_asset(
        actor=custodian,
        department=department,
        asset_tag="OLD-1",
        name="Retired laptop",
        availability_status=Asset.Availability.RETIRED,
    )
    svc.create_asset(actor=custodian, department=department, asset_tag="NEW-1", name="Working laptop")
    member_body = login(member).get("/resources/").content.decode()
    custodian_body = login(custodian).get("/resources/").content.decode()
    assert "Retired laptop" not in member_body
    assert "Working laptop" in member_body
    assert "Retired laptop" in custodian_body


def test_past_booking_is_rejected_over_http(asset, member, login):
    past = timezone.now() - datetime.timedelta(days=1)
    login(member).post(
        f"/resources/{asset.pk}/book/",
        {
            "starts_at": _form_time(past),
            "ends_at": _form_time(past + datetime.timedelta(hours=2)),
            "purpose": "Backdated",
        },
    )
    assert not ResourceBooking.objects.exists()


def test_anonymous_is_redirected_to_sign_in(asset, client):
    assert client.get("/resources/").status_code == 302
    assert client.get(f"/resources/{asset.pk}/").status_code == 302
