"""Assets and resource bookings.

Overlap rule: an asset can only be held by one booking at a time. That is enforced twice —
a friendly check here, and a Postgres exclusion constraint on the table, so two approvals
racing each other still can't double-book. `requested` bookings may overlap freely (several
people may ask for the same slot); only approving one is refused while another holds it.

Permissions:
- `assets.manage` maintains the inventory and decides bookings.
- `requests.create` lets any member ask for an asset.
- Nobody approves their own booking request: approving is a custodian decision.
"""

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.access.services import has_any_perm, has_perm
from apps.audit.services import record, snapshot

from .models import BLOCKING_STATES, Asset, ResourceBooking

MANAGE = "assets.manage"
REQUEST = "requests.create"


class ResourceError(Exception):
    """A business-rule violation with a message safe to show to the user."""


def require_perm(actor, code, department):
    """Services re-check permissions so they're safe to call from views, the API or tasks."""
    if not has_perm(actor, code, department):
        raise PermissionDenied(f"Missing permission {code}.")


def clashing_bookings(asset, starts_at, ends_at, *, exclude_pk=None):
    """Bookings that already hold `asset` over any part of [starts_at, ends_at)."""
    qs = ResourceBooking.objects.filter(
        asset=asset,
        booking_status__in=BLOCKING_STATES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    return qs.exclude(pk=exclude_pk) if exclude_pk else qs


def is_free(asset, starts_at, ends_at, *, exclude_pk=None):
    return not clashing_bookings(asset, starts_at, ends_at, exclude_pk=exclude_pk).exists()


@transaction.atomic
def create_asset(*, actor, department, asset_tag, name, **fields):
    require_perm(actor, MANAGE, department)
    asset = Asset.objects.create(department=department, asset_tag=asset_tag, name=name, **fields)
    record(
        "asset.created",
        asset,
        actor=actor,
        department=department,
        after=snapshot(asset, fields=["asset_tag", "name", "asset_type", "availability_status"]),
    )
    return asset


@transaction.atomic
def update_asset(asset, *, actor, **fields):
    require_perm(actor, MANAGE, asset.department)
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    before = snapshot(asset, fields=["condition_status", "availability_status", "location"])
    for key, value in fields.items():
        setattr(asset, key, value)
    asset.save()
    record(
        "asset.updated",
        asset,
        actor=actor,
        department=asset.department,
        before=before,
        after=snapshot(asset, fields=["condition_status", "availability_status", "location"]),
    )
    return asset


@transaction.atomic
def request_booking(asset, *, actor, starts_at, ends_at, purpose):
    """Ask for an asset. Overlapping requests are allowed; only one can be approved."""
    department = asset.department
    # A custodian holds assets.manage but not requests.create, and still needs to be able
    # to book an asset — they just can't be the one who approves it.
    if not has_any_perm(actor, (REQUEST, MANAGE), department):
        raise PermissionDenied(f"Missing permission {REQUEST}.")
    if ends_at <= starts_at:
        raise ResourceError("The end must be after the start.")
    if starts_at < timezone.now():
        raise ResourceError("Bookings can't start in the past.")
    # Re-read under a lock: the caller's copy may predate the asset going out of service.
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    if not asset.is_bookable:
        raise ResourceError(f"This asset is {asset.get_availability_status_display().lower()}.")

    booking = ResourceBooking.objects.create(
        asset=asset,
        requested_by_user=actor,
        starts_at=starts_at,
        ends_at=ends_at,
        purpose=purpose,
    )
    record(
        "booking.requested",
        booking,
        actor=actor,
        department=department,
        after=snapshot(booking, fields=["starts_at", "ends_at", "booking_status"]),
    )
    return booking


@transaction.atomic
def decide_booking(booking, *, actor, approve, note=""):
    """Approve or reject a booking. The requester never decides their own."""
    department = booking.asset.department
    require_perm(actor, MANAGE, department)
    booking = ResourceBooking.objects.select_for_update().select_related("asset").get(pk=booking.pk)
    if booking.booking_status != ResourceBooking.Status.REQUESTED:
        raise ResourceError("This booking isn't waiting for a decision.")
    if booking.requested_by_user_id == actor.pk:
        raise ResourceError("You can't approve a booking you requested.")

    before = snapshot(booking, fields=["booking_status", "approved_at"])
    if approve:
        clash = clashing_bookings(
            booking.asset, booking.starts_at, booking.ends_at, exclude_pk=booking.pk
        ).first()
        if clash is not None:
            raise ResourceError(
                f"{booking.asset.name} is already booked from "
                f"{clash.starts_at:%d %b %H:%M} to {clash.ends_at:%d %b %H:%M}."
            )
        booking.booking_status = ResourceBooking.Status.APPROVED
        booking.approved_by = actor
        booking.approved_at = timezone.now()
    else:
        booking.booking_status = ResourceBooking.Status.REJECTED
        booking.notes = note or booking.notes

    try:
        booking.save()
    except IntegrityError as exc:
        # The exclusion constraint caught a race the check above missed.
        raise ResourceError("That slot was taken while you were deciding. Try again.") from exc

    record(
        "booking.approved" if approve else "booking.rejected",
        booking,
        actor=actor,
        department=department,
        before=before,
        after={**snapshot(booking, fields=["booking_status", "approved_at"]), "note": note},
    )
    return booking


@transaction.atomic
def check_out(booking, *, actor):
    department = booking.asset.department
    require_perm(actor, MANAGE, department)
    booking = ResourceBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.booking_status != ResourceBooking.Status.APPROVED:
        raise ResourceError("Only an approved booking can be checked out.")
    booking.booking_status = ResourceBooking.Status.CHECKED_OUT
    booking.save(update_fields=["booking_status"])
    record("booking.checked_out", booking, actor=actor, department=department)
    return booking


@transaction.atomic
def check_in(booking, *, actor, condition=None, notes=""):
    """Return the asset, optionally recording its condition."""
    department = booking.asset.department
    require_perm(actor, MANAGE, department)
    booking = ResourceBooking.objects.select_for_update().select_related("asset").get(pk=booking.pk)
    if booking.booking_status not in (
        ResourceBooking.Status.CHECKED_OUT,
        ResourceBooking.Status.APPROVED,
    ):
        raise ResourceError("This booking isn't out.")
    booking.booking_status = ResourceBooking.Status.RETURNED
    booking.returned_at = timezone.now()
    booking.notes = notes or booking.notes
    booking.save()
    if condition:
        asset = booking.asset
        asset.condition_status = condition
        if condition == Asset.Condition.NEEDS_REPAIR:
            asset.availability_status = Asset.Availability.MAINTENANCE
        asset.save(update_fields=["condition_status", "availability_status"])
    record(
        "booking.returned",
        booking,
        actor=actor,
        department=department,
        after={"returned_at": str(booking.returned_at), "condition": condition or ""},
    )
    return booking


@transaction.atomic
def cancel_booking(booking, *, actor):
    """The requester withdraws, or a custodian cancels."""
    department = booking.asset.department
    is_requester = booking.requested_by_user_id == actor.pk
    if not is_requester:
        require_perm(actor, MANAGE, department)
    elif not has_any_perm(actor, (REQUEST, MANAGE), department):
        raise PermissionDenied(f"Missing permission {REQUEST}.")

    booking = ResourceBooking.objects.select_for_update().get(pk=booking.pk)
    if booking.booking_status in (
        ResourceBooking.Status.RETURNED,
        ResourceBooking.Status.CANCELLED,
        ResourceBooking.Status.REJECTED,
    ):
        raise ResourceError("This booking is already finished.")
    before = {"status": booking.booking_status}
    booking.booking_status = ResourceBooking.Status.CANCELLED
    booking.save(update_fields=["booking_status"])
    record(
        "booking.cancelled",
        booking,
        actor=actor,
        department=department,
        before=before,
        after={"status": booking.booking_status},
    )
    return booking


def bookings_for(department, *, status=None, asset=None, user=None, upcoming_only=False):
    qs = ResourceBooking.objects.filter(asset__department=department).select_related(
        "asset", "requested_by_user__profile"
    )
    if status:
        qs = qs.filter(booking_status=status)
    if asset is not None:
        qs = qs.filter(asset=asset)
    if user is not None:
        qs = qs.filter(requested_by_user=user)
    if upcoming_only:
        qs = qs.filter(ends_at__gte=timezone.now())
    return qs


def utilisation(department, *, since=None, until=None):
    """Booking counts for the operations report."""
    qs = ResourceBooking.objects.filter(asset__department=department)
    if since is not None:
        qs = qs.filter(starts_at__gte=since)
    if until is not None:
        qs = qs.filter(starts_at__lt=until)
    assets = Asset.objects.filter(department=department)
    return {
        "assets": assets.count(),
        "available": assets.filter(availability_status=Asset.Availability.AVAILABLE).count(),
        "needing_repair": assets.filter(
            Q(condition_status=Asset.Condition.NEEDS_REPAIR)
            | Q(availability_status=Asset.Availability.MAINTENANCE)
        ).count(),
        "bookings": qs.count(),
        "awaiting_decision": qs.filter(booking_status=ResourceBooking.Status.REQUESTED).count(),
        "out_now": qs.filter(booking_status=ResourceBooking.Status.CHECKED_OUT).count(),
    }
