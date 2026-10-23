"""Dues balances, calculated from records rather than stored (workbook view v_dues_balances).

    paid    = allocations on received payments - amounts reversed by processed adjustments
    balance = assessed - waived - paid           (cancelled assessments owe nothing)

A payment counts as received when its status is confirmed, partially_refunded or refunded;
refunds reduce `paid` only through processed allocation adjustments.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import (
    Case,
    CharField,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.common.models import ZERO

from ..models import (
    CONFIRMED_PAYMENT_STATES,
    DuesAssessment,
    PaymentAdjustment,
    PaymentAllocation,
    PaymentAllocationAdjustment,
)

MONEY = DecimalField(max_digits=14, decimal_places=2)


class DerivedStatus:
    PAID = "paid"
    PARTIAL = "partial"
    OUTSTANDING = "outstanding"
    OVERDUE = "overdue"
    WAIVED = "waived"
    CANCELLED = "cancelled"

    LABELS = {
        PAID: "Paid",
        PARTIAL: "Part paid",
        OUTSTANDING: "Outstanding",
        OVERDUE: "Overdue",
        WAIVED: "Waived",
        CANCELLED: "Cancelled",
    }


def allocated_subquery():
    rows = (
        PaymentAllocation.objects.filter(
            dues_assessment=OuterRef("pk"), payment__payment_status__in=CONFIRMED_PAYMENT_STATES
        )
        .order_by()
        .values("dues_assessment")
        .annotate(total=Sum("amount_allocated"))
        .values("total")
    )
    return Coalesce(Subquery(rows, output_field=MONEY), Value(ZERO), output_field=MONEY)


def reversed_subquery():
    rows = (
        PaymentAllocationAdjustment.objects.filter(
            payment_allocation__dues_assessment=OuterRef("pk"),
            payment_allocation__payment__payment_status__in=CONFIRMED_PAYMENT_STATES,
            payment_adjustment__adjustment_status=PaymentAdjustment.Status.PROCESSED,
        )
        .order_by()
        .values("payment_allocation__dues_assessment")
        .annotate(total=Sum("amount_reversed"))
        .values("total")
    )
    return Coalesce(Subquery(rows, output_field=MONEY), Value(ZERO), output_field=MONEY)


def with_balances(queryset=None, today=None):
    """Annotate assessments with amount_paid, balance and derived_status."""
    today = today or timezone.localdate()
    qs = queryset if queryset is not None else DuesAssessment.objects.all()
    qs = qs.annotate(
        amount_paid=ExpressionWrapper(allocated_subquery() - reversed_subquery(), output_field=MONEY)
    )
    qs = qs.annotate(
        balance=Case(
            When(assessment_state=DuesAssessment.State.CANCELLED, then=Value(ZERO)),
            default=ExpressionWrapper(
                F("amount_assessed") - F("amount_waived") - F("amount_paid"), output_field=MONEY
            ),
            output_field=MONEY,
        )
    )
    return qs.annotate(
        derived_status=Case(
            When(assessment_state=DuesAssessment.State.CANCELLED, then=Value(DerivedStatus.CANCELLED)),
            When(
                Q(amount_waived__gt=0) & Q(amount_waived=F("amount_assessed")),
                then=Value(DerivedStatus.WAIVED),
            ),
            When(balance__lte=0, then=Value(DerivedStatus.PAID)),
            When(Q(due_date__lt=today), then=Value(DerivedStatus.OVERDUE)),
            When(amount_paid__gt=0, then=Value(DerivedStatus.PARTIAL)),
            default=Value(DerivedStatus.OUTSTANDING),
            output_field=CharField(),
        )
    )


@dataclass(frozen=True)
class BalanceTotals:
    assessed: Decimal
    waived: Decimal
    paid: Decimal
    outstanding: Decimal
    count: int

    @property
    def collection_rate(self):
        due = self.assessed - self.waived
        return (self.paid / due * 100) if due > 0 else None


def totals(queryset):
    """Totals over assessments (cancelled assessments excluded)."""
    qs = with_balances(queryset.exclude(assessment_state=DuesAssessment.State.CANCELLED))
    rows = list(qs.values_list("amount_assessed", "amount_waived", "amount_paid", "balance"))
    assessed = sum((r[0] for r in rows), ZERO)
    waived = sum((r[1] for r in rows), ZERO)
    paid = sum((r[2] for r in rows), ZERO)
    outstanding = sum((max(r[3], ZERO) for r in rows), ZERO)
    return BalanceTotals(assessed, waived, paid, outstanding, len(rows))


def assessment_balance(assessment):
    """Fresh balance for one assessment."""
    return with_balances(DuesAssessment.objects.filter(pk=assessment.pk)).values_list("balance", flat=True)[0]
