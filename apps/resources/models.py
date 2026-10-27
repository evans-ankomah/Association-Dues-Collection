from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q

from apps.common.models import CurrencyField, MoneyField, TimeStampedModel
from apps.institutions.models import Department

# A booking in one of these states holds the asset, so no other booking may overlap it.
# Requested, rejected, returned and cancelled bookings never block anything.
BLOCKING_STATES = ("approved", "checked_out")


class TsTzRange(Func):
    """The Postgres tstzrange(starts_at, ends_at, '[)') used by the no-overlap constraint.

    '[)' means the end is exclusive, so a booking ending at 10:00 and one starting at 10:00
    are back-to-back rather than overlapping.
    """

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Asset(TimeStampedModel):
    class Type(models.TextChoices):
        EQUIPMENT = "equipment"
        FACILITY = "facility"
        VENUE = "venue"
        OTHER = "other"

    class Condition(models.TextChoices):
        EXCELLENT = "excellent"
        GOOD = "good"
        FAIR = "fair"
        NEEDS_REPAIR = "needs_repair", "Needs repair"
        RETIRED = "retired"

    class Availability(models.TextChoices):
        AVAILABLE = "available"
        RESERVED = "reserved"
        MAINTENANCE = "maintenance"
        RETIRED = "retired"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="assets")
    asset_tag = models.CharField(max_length=100)
    name = models.CharField(max_length=180)
    asset_type = models.CharField(max_length=30, choices=Type, default=Type.EQUIPMENT)
    description = models.TextField(null=True, blank=True)
    location = models.CharField(max_length=200, null=True, blank=True)
    condition_status = models.CharField(max_length=24, choices=Condition, default=Condition.GOOD)
    availability_status = models.CharField(
        max_length=24, choices=Availability, default=Availability.AVAILABLE
    )
    custodian_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    acquired_on = models.DateField(null=True, blank=True)
    replacement_cost = MoneyField(null=True, blank=True)
    currency = CurrencyField(null=True, blank=True)

    class Meta:
        db_table = "assets"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["department", "asset_tag"], name="uq_asset_tag_per_department")
        ]
        indexes = [models.Index(fields=["department", "asset_type", "availability_status"])]

    def __str__(self):
        return f"{self.asset_tag} · {self.name}"

    @property
    def is_bookable(self):
        return self.availability_status == self.Availability.AVAILABLE


class ResourceBooking(TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested"
        APPROVED = "approved"
        REJECTED = "rejected"
        CHECKED_OUT = "checked_out", "Checked out"
        RETURNED = "returned"
        CANCELLED = "cancelled"

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="bookings")
    requested_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="resource_bookings"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    purpose = models.TextField()
    booking_status = models.CharField(max_length=24, choices=Status, default=Status.REQUESTED)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "resource_bookings"
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="ck_booking_ends_after_start"
            ),
            # The database itself refuses two holding bookings on one asset at the same time,
            # so a race between two approvals can't double-book it.
            ExclusionConstraint(
                name="ex_booking_no_overlap",
                expressions=[
                    (TsTzRange("starts_at", "ends_at", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("asset", RangeOperators.EQUAL),
                ],
                condition=Q(booking_status__in=BLOCKING_STATES),
            ),
        ]
        indexes = [models.Index(fields=["asset", "booking_status", "starts_at"])]

    def __str__(self):
        return f"{self.asset} · {self.starts_at:%d %b %H:%M}"

    @property
    def holds_the_asset(self):
        return self.booking_status in BLOCKING_STATES
