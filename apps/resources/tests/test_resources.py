import datetime

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.tests.factories import DepartmentFactory, UserFactory
from apps.resources import services as svc
from apps.resources.models import Asset, ResourceBooking
from apps.resources.services import ResourceError

pytestmark = pytest.mark.django_db


def test_member_requests_and_custodian_approves(asset, member, custodian, slot):
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Project demo")
    assert booking.booking_status == ResourceBooking.Status.REQUESTED

    svc.decide_booking(booking, actor=custodian, approve=True)
    booking.refresh_from_db()
    assert booking.booking_status == ResourceBooking.Status.APPROVED
    assert booking.approved_by == custodian
    assert booking.approved_at is not None


def test_full_checkout_and_return_cycle(asset, member, custodian, slot):
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Lecture")
    svc.decide_booking(booking, actor=custodian, approve=True)
    svc.check_out(booking, actor=custodian)
    booking.refresh_from_db()
    assert booking.booking_status == ResourceBooking.Status.CHECKED_OUT

    svc.check_in(booking, actor=custodian, condition=Asset.Condition.NEEDS_REPAIR)
    booking.refresh_from_db()
    asset.refresh_from_db()
    assert booking.booking_status == ResourceBooking.Status.RETURNED
    assert booking.returned_at is not None
    # Returning a broken asset takes it out of service.
    assert asset.condition_status == Asset.Condition.NEEDS_REPAIR
    assert asset.availability_status == Asset.Availability.MAINTENANCE


# --- the overlap rule ---------------------------------------------------------------------------


def test_overlapping_approval_is_refused(asset, member, custodian, make_user, slot):
    """Two people may ask for the same slot, but only one can be approved."""
    starts, ends = slot()
    first = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Demo")
    other = make_user("student_member")
    second = svc.request_booking(
        asset,
        actor=other,
        starts_at=starts + datetime.timedelta(minutes=30),
        ends_at=ends + datetime.timedelta(minutes=30),
        purpose="Clashing demo",
    )
    svc.decide_booking(first, actor=custodian, approve=True)
    with pytest.raises(ResourceError, match="already booked"):
        svc.decide_booking(second, actor=custodian, approve=True)
    second.refresh_from_db()
    assert second.booking_status == ResourceBooking.Status.REQUESTED


@pytest.mark.parametrize(
    ("offset", "length", "overlaps"),
    [
        (0, 2, True),  # identical slot
        (1, 2, True),  # starts inside
        (-1, 2, True),  # ends inside
        (-1, 4, True),  # spans it entirely
        (0.5, 1, True),  # entirely inside
        (2, 2, False),  # starts exactly when the other ends
        (-2, 2, False),  # ends exactly when the other starts
        (5, 2, False),  # well clear
    ],
    ids=[
        "identical",
        "starts-inside",
        "ends-inside",
        "spans",
        "inside",
        "back-to-back-after",
        "back-to-back-before",
        "clear",
    ],
)
def test_overlap_boundaries(asset, member, custodian, make_user, slot, offset, length, overlaps):
    """Back-to-back bookings are fine; any real overlap is not."""
    starts, ends = slot()
    held = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Held")
    svc.decide_booking(held, actor=custodian, approve=True)

    other_start = starts + datetime.timedelta(hours=offset)
    candidate = svc.request_booking(
        asset,
        actor=make_user("student_member"),
        starts_at=other_start,
        ends_at=other_start + datetime.timedelta(hours=length),
        purpose="Candidate",
    )
    if overlaps:
        with pytest.raises(ResourceError, match="already booked"):
            svc.decide_booking(candidate, actor=custodian, approve=True)
    else:
        svc.decide_booking(candidate, actor=custodian, approve=True)
        candidate.refresh_from_db()
        assert candidate.booking_status == ResourceBooking.Status.APPROVED


def test_the_database_itself_refuses_an_overlap(asset, member, custodian, slot):
    """Last line of defence: even a direct write can't double-book."""
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Held")
    svc.decide_booking(booking, actor=custodian, approve=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        ResourceBooking.objects.create(
            asset=asset,
            requested_by_user=member,
            starts_at=starts + datetime.timedelta(minutes=15),
            ends_at=ends,
            purpose="Sneaked past the service",
            booking_status=ResourceBooking.Status.APPROVED,
        )


def test_cancelling_frees_the_slot(asset, member, custodian, make_user, slot):
    starts, ends = slot()
    first = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Demo")
    svc.decide_booking(first, actor=custodian, approve=True)
    svc.cancel_booking(first, actor=member)

    second = svc.request_booking(
        asset,
        actor=make_user("student_member"),
        starts_at=starts,
        ends_at=ends,
        purpose="Now free",
    )
    svc.decide_booking(second, actor=custodian, approve=True)
    second.refresh_from_db()
    assert second.booking_status == ResourceBooking.Status.APPROVED


def test_rejected_and_returned_bookings_do_not_block(asset, member, custodian, make_user, slot):
    starts, ends = slot()
    rejected = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="No")
    svc.decide_booking(rejected, actor=custodian, approve=False)
    replacement = svc.request_booking(
        asset, actor=make_user("student_member"), starts_at=starts, ends_at=ends, purpose="Yes"
    )
    svc.decide_booking(replacement, actor=custodian, approve=True)
    replacement.refresh_from_db()
    assert replacement.booking_status == ResourceBooking.Status.APPROVED


# --- validation and permissions -----------------------------------------------------------------


def test_bookings_cannot_start_in_the_past(asset, member):
    now = timezone.now()
    with pytest.raises(ResourceError, match="in the past"):
        svc.request_booking(
            asset,
            actor=member,
            starts_at=now - datetime.timedelta(hours=2),
            ends_at=now + datetime.timedelta(hours=1),
            purpose="Backdated",
        )


def test_the_end_must_be_after_the_start(asset, member, slot):
    starts, _ = slot()
    with pytest.raises(ResourceError, match="end must be after"):
        svc.request_booking(asset, actor=member, starts_at=starts, ends_at=starts, purpose="Zero length")


def test_an_unavailable_asset_cannot_be_booked(asset, member, custodian, slot):
    svc.update_asset(asset, actor=custodian, availability_status=Asset.Availability.MAINTENANCE)
    starts, ends = slot()
    with pytest.raises(ResourceError, match="maintenance"):
        svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Broken")


def test_nobody_approves_their_own_booking(asset, custodian, slot):
    """A custodian may request an asset, but someone else signs it off."""
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=custodian, starts_at=starts, ends_at=ends, purpose="Mine")
    with pytest.raises(ResourceError, match="booking you requested"):
        svc.decide_booking(booking, actor=custodian, approve=True)


def test_a_member_cannot_approve_or_manage(asset, member, custodian, slot):
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Demo")
    with pytest.raises(PermissionDenied):
        svc.decide_booking(booking, actor=member, approve=True)
    with pytest.raises(PermissionDenied):
        svc.check_out(booking, actor=member)
    with pytest.raises(PermissionDenied):
        svc.update_asset(asset, actor=member, location="Elsewhere")


def test_a_member_cannot_create_an_asset(department, member):
    with pytest.raises(PermissionDenied):
        svc.create_asset(actor=member, department=department, asset_tag="X-1", name="Sneaky")


def test_the_requester_may_cancel_their_own(asset, member, custodian, slot):
    starts, ends = slot()
    booking = svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Demo")
    svc.cancel_booking(booking, actor=member)
    booking.refresh_from_db()
    assert booking.booking_status == ResourceBooking.Status.CANCELLED


def test_a_member_cannot_cancel_somebody_elses(asset, member, make_user, slot):
    starts, ends = slot()
    booking = svc.request_booking(
        asset, actor=make_user("student_member"), starts_at=starts, ends_at=ends, purpose="Theirs"
    )
    with pytest.raises(PermissionDenied):
        svc.cancel_booking(booking, actor=member)


# --- cross-department leaks ----------------------------------------------------------------------


def test_assets_do_not_leak_across_departments(custodian, department, slot):
    other_dept = DepartmentFactory(institution=department.institution)
    foreign = Asset.objects.create(department=other_dept, asset_tag="X-1", name="Their projector")
    with pytest.raises(PermissionDenied):
        svc.update_asset(foreign, actor=custodian, location="Mine now")
    with pytest.raises(PermissionDenied):
        svc.create_asset(actor=custodian, department=other_dept, asset_tag="X-2", name="Sneaky")
    booking = ResourceBooking.objects.create(
        asset=foreign,
        requested_by_user=UserFactory(),
        starts_at=slot()[0],
        ends_at=slot()[1],
        purpose="Theirs",
    )
    with pytest.raises(PermissionDenied):
        svc.decide_booking(booking, actor=custodian, approve=True)


def test_an_asset_tag_is_unique_only_within_a_department(custodian, department):
    """Two departments may both have a CSE-PRJ-001."""
    other_dept = DepartmentFactory(institution=department.institution)
    svc.create_asset(actor=custodian, department=department, asset_tag="SHARED-1", name="Mine")
    Asset.objects.create(department=other_dept, asset_tag="SHARED-1", name="Theirs")
    assert Asset.objects.filter(asset_tag="SHARED-1").count() == 2
    with pytest.raises(IntegrityError), transaction.atomic():
        Asset.objects.create(department=department, asset_tag="SHARED-1", name="Duplicate")


def test_utilisation_counts(asset, member, custodian, slot):
    starts, ends = slot()
    svc.request_booking(asset, actor=member, starts_at=starts, ends_at=ends, purpose="Demo")
    stats = svc.utilisation(asset.department)
    assert stats["assets"] == 1
    assert stats["available"] == 1
    assert stats["bookings"] == 1
    assert stats["awaiting_decision"] == 1
