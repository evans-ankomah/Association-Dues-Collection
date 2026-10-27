from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.institutions.models import Department
from apps.memberships.models import DepartmentMembership

# Event states a member may register for or be counted as attending.
OPEN_EVENT_STATES = ("published",)


class EventQuerySet(models.QuerySet):
    def visible_to_members(self):
        """Only published events are shown to ordinary members; drafts stay with the organisers."""
        return self.filter(event_status=Event.Status.PUBLISHED)

    def upcoming(self, at=None):
        return self.filter(ends_at__gte=at or timezone.now())


class Event(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        PUBLISHED = "published"
        CANCELLED = "cancelled"
        COMPLETED = "completed"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="events")
    title = models.CharField(max_length=180)
    description = models.TextField(null=True, blank=True)
    event_type = models.CharField(max_length=60)
    venue_text = models.CharField(max_length=240, null=True, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(null=True, blank=True)
    registration_required = models.BooleanField(default=False)
    event_status = models.CharField(max_length=24, choices=Status, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    related_budget = models.ForeignKey(
        "finance.Budget", on_delete=models.PROTECT, null=True, blank=True, related_name="events"
    )

    objects = EventQuerySet.as_manager()

    class Meta:
        db_table = "events"
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gte=F("starts_at")), name="ck_event_dates_ordered")
        ]
        indexes = [models.Index(fields=["department", "event_status", "starts_at"])]

    def __str__(self):
        return self.title

    @property
    def is_open_for_registration(self):
        return (
            self.registration_required
            and self.event_status == self.Status.PUBLISHED
            and self.starts_at > timezone.now()
        )

    @property
    def registered_count(self):
        return self.registrations.filter(
            registration_status__in=(
                EventRegistration.Status.REGISTERED,
                EventRegistration.Status.ATTENDED,
            )
        ).count()

    @property
    def seats_left(self):
        """None when the event has no capacity limit."""
        return None if self.capacity is None else max(self.capacity - self.registered_count, 0)

    @property
    def is_full(self):
        return self.seats_left == 0


class EventRegistration(TimeStampedModel):
    class Status(models.TextChoices):
        REGISTERED = "registered"
        WAITLISTED = "waitlisted"
        CANCELLED = "cancelled"
        ATTENDED = "attended"
        NO_SHOW = "no_show", "No show"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registrations")
    department_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, related_name="event_registrations"
    )
    registration_status = models.CharField(max_length=24, choices=Status, default=Status.REGISTERED)
    registered_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "event_registrations"
        ordering = ["registered_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "department_membership"], name="uq_registration_per_member"
            )
        ]
        indexes = [models.Index(fields=["event", "registration_status"])]

    def __str__(self):
        return f"{self.department_membership} · {self.event}"


class EventAttendance(TimeStampedModel):
    class Status(models.TextChoices):
        PRESENT = "present"
        ABSENT = "absent"
        EXCUSED = "excused"
        LATE = "late"

    class Method(models.TextChoices):
        QR = "qr", "QR code"
        MANUAL = "manual"
        IMPORT = "import"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attendance")
    department_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, related_name="event_attendance"
    )
    attendance_status = models.CharField(max_length=20, choices=Status, default=Status.PRESENT)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    checkin_method = models.CharField(max_length=20, choices=Method, null=True, blank=True)

    class Meta:
        db_table = "event_attendance"
        ordering = ["checked_in_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "department_membership"], name="uq_attendance_per_member"
            )
        ]
        indexes = [models.Index(fields=["event", "attendance_status"])]

    def __str__(self):
        return f"{self.department_membership} · {self.event}"
