from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import CurrencyField, MoneyField, TimeStampedModel
from apps.institutions.models import Department
from apps.memberships.models import DepartmentMembership

from .dues import DuesAssessment


class Payment(TimeStampedModel):
    """A payment attempt or confirmed receipt of money. Only confirmed payments count as income."""

    class Method(models.TextChoices):
        CASH = "cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        CARD = "card"
        PROVIDER = "provider", "Online (Paystack)"
        OTHER = "other"

    class Status(models.TextChoices):
        PENDING = "pending"
        CONFIRMED = "confirmed"
        FAILED = "failed"
        CANCELLED = "cancelled"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        REFUNDED = "refunded"

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="payments")
    payer_membership = models.ForeignKey(
        DepartmentMembership, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    amount = MoneyField()
    currency = CurrencyField()
    payment_method = models.CharField(max_length=30, choices=Method)
    payment_status = models.CharField(max_length=24, choices=Status, default=Status.PENDING)
    provider_name = models.CharField(max_length=80, null=True, blank=True)
    provider_reference = models.CharField(max_length=180, null=True, blank=True)
    idempotency_key = models.CharField(max_length=180, null=True, blank=True, unique=True)
    external_reference = models.CharField(max_length=180, null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    initiated_at = models.DateTimeField(null=True, blank=True, default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "payments"
        ordering = ["-initiated_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="ck_payment_amount_positive"),
            models.UniqueConstraint(
                fields=["provider_name", "provider_reference"],
                condition=Q(provider_reference__isnull=False),
                name="uq_provider_reference",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        payment_status__in=["confirmed", "partially_refunded", "refunded"],
                        confirmed_at__isnull=False,
                    )
                    | (
                        ~Q(payment_status__in=["confirmed", "partially_refunded", "refunded"])
                        & Q(confirmed_at__isnull=True)
                    )
                ),
                name="ck_confirmed_at_matches_status",
            ),
        ]
        indexes = [models.Index(fields=["department", "payment_status", "confirmed_at"])]

    def __str__(self):
        return f"{self.currency} {self.amount} · {self.get_payment_method_display()} · {self.payment_status}"

    @property
    def is_confirmed(self):
        return self.payment_status in CONFIRMED_PAYMENT_STATES

    @property
    def method_label(self):
        if self.provider_name and self.payment_method != self.Method.CASH:
            return self.provider_name
        return self.get_payment_method_display()


# Statuses where the money was received. Refunds are tracked separately as adjustments.
CONFIRMED_PAYMENT_STATES = (
    Payment.Status.CONFIRMED,
    Payment.Status.PARTIALLY_REFUNDED,
    Payment.Status.REFUNDED,
)


class PaymentAllocation(TimeStampedModel):
    """How much of a payment settles one assessment."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    dues_assessment = models.ForeignKey(DuesAssessment, on_delete=models.PROTECT, related_name="allocations")
    amount_allocated = MoneyField()
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    allocated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payment_allocations"
        constraints = [
            models.UniqueConstraint(fields=["payment", "dues_assessment"], name="uq_allocation_pair"),
            models.CheckConstraint(condition=Q(amount_allocated__gt=0), name="ck_allocation_positive"),
        ]


class Receipt(TimeStampedModel):
    class Status(models.TextChoices):
        ISSUED = "issued"
        VOIDED = "voided"
        REPLACED = "replaced"

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    receipt_number = models.CharField(max_length=80, unique=True)
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    receipt_status = models.CharField(max_length=20, choices=Status, default=Status.ISSUED)
    storage_key = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "receipts"
        ordering = ["-issued_at"]

    def __str__(self):
        return self.receipt_number


class ReceiptCounter(models.Model):
    """Last receipt sequence number per department and year. Locked while a receipt is issued."""

    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "receipt_counters"
        constraints = [models.UniqueConstraint(fields=["department", "year"], name="uq_receipt_counter")]

    def __str__(self):
        return f"{self.department_id} {self.year}: {self.last_number}"


class PaymentAdjustment(TimeStampedModel):
    """A refund, reversal or correction against an original payment."""

    class Type(models.TextChoices):
        REFUND = "refund"
        REVERSAL = "reversal"
        CORRECTION = "correction"

    class Status(models.TextChoices):
        REQUESTED = "requested"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPROVED = "approved"
        PROCESSED = "processed"
        REJECTED = "rejected"
        FAILED = "failed"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="adjustments")
    adjustment_type = models.CharField(max_length=20, choices=Type)
    amount = MoneyField()
    reason = models.TextField()
    adjustment_status = models.CharField(max_length=24, choices=Status, default=Status.REQUESTED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=180, null=True, blank=True)

    class Meta:
        db_table = "payment_adjustments"
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="ck_adjustment_positive")]


class PaymentAllocationAdjustment(TimeStampedModel):
    """Which allocation a processed refund or reversal reduces, so balances stay correct."""

    payment_adjustment = models.ForeignKey(
        PaymentAdjustment, on_delete=models.PROTECT, related_name="allocation_adjustments"
    )
    payment_allocation = models.ForeignKey(
        PaymentAllocation, on_delete=models.PROTECT, related_name="adjustments"
    )
    amount_reversed = MoneyField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "payment_allocation_adjustments"
        constraints = [
            models.UniqueConstraint(
                fields=["payment_adjustment", "payment_allocation"], name="uq_allocation_adjustment_pair"
            ),
            models.CheckConstraint(condition=Q(amount_reversed__gt=0), name="ck_reversal_positive"),
        ]
