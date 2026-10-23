from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.common.models import CurrencyField, MoneyField, TimeStampedModel
from apps.institutions.models import AcademicSession, Department
from apps.memberships.models import DepartmentMembership


class DuesType(TimeStampedModel):
    """A fee category for one department and academic session."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"
        CLOSED = "closed"
        CANCELLED = "cancelled"

    class Category(models.TextChoices):
        DEPARTMENTAL_DUES = "departmental_dues", "Departmental dues"
        SOUVENIR = "souvenir"
        EXCURSION = "excursion"
        DINNER = "dinner"
        ORIENTATION = "orientation"
        EVENT = "event"
        OTHER = "other"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="dues_types")
    academic_session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, related_name="dues_types")
    name = models.CharField(max_length=140)
    category = models.CharField(max_length=60, choices=Category, default=Category.DEPARTMENTAL_DUES)
    description = models.TextField(null=True, blank=True)
    default_amount = MoneyField()
    currency = CurrencyField()
    due_date = models.DateField(null=True, blank=True)
    is_mandatory = models.BooleanField(default=True)
    eligibility_description = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "dues_types"
        ordering = ["-academic_session__starts_on", "due_date", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(default_amount__gte=0), name="ck_dues_type_amount_nonneg"),
        ]

    def __str__(self):
        return self.name

    @property
    def can_assess(self):
        return self.status in (self.Status.DRAFT, self.Status.ACTIVE)


class DuesAssessment(TimeStampedModel):
    """What one member owes for one dues type. Balances are calculated, never stored."""

    class State(models.TextChoices):
        ACTIVE = "active"
        WAIVED = "waived"
        CANCELLED = "cancelled"

    dues_type = models.ForeignKey(DuesType, on_delete=models.PROTECT, related_name="assessments")
    department_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, related_name="assessments"
    )
    amount_assessed = MoneyField()
    amount_waived = MoneyField(default=0)
    due_date = models.DateField(null=True, blank=True)
    assessment_state = models.CharField(max_length=20, choices=State, default=State.ACTIVE)
    waiver_reason = models.TextField(null=True, blank=True)
    assessed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    assessed_at = models.DateTimeField(default=timezone.now)
    waived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    waived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dues_assessments"
        ordering = ["due_date", "dues_type__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["dues_type", "department_membership"],
                condition=~Q(assessment_state="cancelled"),
                name="uq_one_live_assessment_per_member_and_type",
            ),
            models.CheckConstraint(condition=Q(amount_assessed__gte=0), name="ck_assessment_amount_nonneg"),
            models.CheckConstraint(
                condition=Q(amount_waived__gte=0) & Q(amount_waived__lte=F("amount_assessed")),
                name="ck_waiver_within_assessed",
            ),
            models.CheckConstraint(
                condition=Q(amount_waived=0) | Q(waiver_reason__isnull=False),
                name="ck_waiver_has_reason",
            ),
        ]
        indexes = [models.Index(fields=["department_membership", "due_date"])]

    def __str__(self):
        return f"{self.dues_type} · {self.department_membership.user}"


class WaiverRequest(TimeStampedModel):
    """A proposed waiver awaiting a decision by someone holding dues.waiver.approve.

    Not in the workbook: it keeps the request separate from the approval so the person asking
    is never the person granting.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"

    dues_assessment = models.ForeignKey(
        DuesAssessment, on_delete=models.PROTECT, related_name="waiver_requests"
    )
    amount = MoneyField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "waiver_requests"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ck_waiver_request_positive"),
            models.UniqueConstraint(
                fields=["dues_assessment"],
                condition=Q(status="pending"),
                name="uq_one_pending_waiver_per_assessment",
            ),
        ]
