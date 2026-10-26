"""Finance figures for dashboards and reports (workbook view v_finance_summary).

Definitions:
- Assessed / waived / collected / outstanding come from v_dues_balances (cancelled excluded).
  Collected = allocations on received payments net of processed reversals.
- Income = received payments by confirmation date; refunds = processed refund/reversal
  adjustments by processing date. A payment attempt is never income.
- Collection rate = collected / (assessed - waived).
Every figure is for one department and one currency (GHS); currencies are never mixed.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.common.models import ZERO
from apps.finance.models import (
    CONFIRMED_PAYMENT_STATES,
    DuesAssessment,
    DuesBalance,
    Payment,
    PaymentAdjustment,
    WaiverRequest,
)

LIVE = ~Q(assessment_state=DuesAssessment.State.CANCELLED)


@dataclass(frozen=True)
class Totals:
    assessed: Decimal
    waived: Decimal
    collected: Decimal
    outstanding: Decimal
    members: int

    @property
    def collection_rate(self):
        due = self.assessed - self.waived
        return self.collected / due * 100 if due > 0 else None


def _balances(department, session=None):
    qs = DuesBalance.objects.filter(LIVE, department=department)
    return qs.filter(academic_session=session) if session is not None else qs


def _totals(qs):
    agg = qs.aggregate(
        assessed=Coalesce(Sum("amount_assessed"), ZERO),
        waived=Coalesce(Sum("amount_waived"), ZERO),
        collected=Coalesce(Sum("amount_paid"), ZERO),
        outstanding=Coalesce(Sum("balance", filter=Q(balance__gt=0)), ZERO),
        members=Count("department_membership", distinct=True),
    )
    return Totals(**agg)


def session_totals(department, session):
    return _totals(_balances(department, session))


def by_dues_type(department, session):
    rows = (
        _balances(department, session)
        .values("dues_type_id", "dues_type__name", "dues_type__due_date")
        .annotate(
            assessed=Sum("amount_assessed"),
            waived=Sum("amount_waived"),
            collected=Sum("amount_paid"),
            outstanding=Coalesce(Sum("balance", filter=Q(balance__gt=0)), ZERO),
            members=Count("department_membership", distinct=True),
        )
        .order_by("dues_type__due_date", "dues_type__name")
    )
    return [_with_rate(r) for r in rows]


def by_level(department, session):
    rows = (
        _balances(department, session)
        .values("department_membership__level_code")
        .annotate(
            assessed=Sum("amount_assessed"),
            waived=Sum("amount_waived"),
            collected=Sum("amount_paid"),
            outstanding=Coalesce(Sum("balance", filter=Q(balance__gt=0)), ZERO),
            members=Count("department_membership", distinct=True),
        )
        .order_by("department_membership__level_code")
    )
    return [{**_with_rate(r), "level": r["department_membership__level_code"] or "No level"} for r in rows]


def _with_rate(row):
    due = row["assessed"] - row["waived"]
    return {**row, "rate": row["collected"] / due * 100 if due > 0 else None}


def _add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    return datetime.date(index // 12, index % 12 + 1, 1)


def received_payments(department):
    return Payment.objects.filter(department=department, payment_status__in=CONFIRMED_PAYMENT_STATES)


def monthly_income(department, months=12, today=None):
    """Received payments per calendar month for the last `months` months (oldest first, zero-filled)."""
    today = today or timezone.localdate()
    first = _add_months(today.replace(day=1), -(months - 1))
    rows = dict(
        received_payments(department)
        .filter(confirmed_at__date__gte=first)
        .annotate(month=TruncMonth("confirmed_at"))
        .values("month")
        .annotate(total=Sum("amount"))
        .values_list("month", "total")
    )
    by_month = {m.date().replace(day=1) if hasattr(m, "date") else m: t for m, t in rows.items()}
    series, cursor = [], first
    while cursor <= today:
        series.append({"month": cursor, "total": by_month.get(cursor, ZERO)})
        cursor = _add_months(cursor, 1)
    peak = max((row["total"] for row in series), default=ZERO)
    for row in series:
        row["pct"] = float(row["total"] / peak * 100) if peak else 0.0
    return series


def payments_by_method(department, start=None, end=None):
    qs = received_payments(department)
    if start:
        qs = qs.filter(confirmed_at__date__gte=start)
    if end:
        qs = qs.filter(confirmed_at__date__lte=end)
    labels = dict(Payment.Method.choices)
    rows = qs.values("payment_method", "provider_name").annotate(total=Sum("amount"), count=Count("id"))
    return [
        {**row, "method_label": labels.get(row["payment_method"], row["payment_method"])}
        for row in rows.order_by("-total")
    ]


def refunds_total(department, start=None, end=None):
    qs = PaymentAdjustment.objects.filter(
        payment__department=department,
        adjustment_status=PaymentAdjustment.Status.PROCESSED,
        adjustment_type__in=[PaymentAdjustment.Type.REFUND, PaymentAdjustment.Type.REVERSAL],
    )
    if start:
        qs = qs.filter(processed_at__date__gte=start)
    if end:
        qs = qs.filter(processed_at__date__lte=end)
    return qs.aggregate(total=Coalesce(Sum("amount"), ZERO))["total"]


def work_queues(department):
    return {
        "pending_payments": Payment.objects.filter(
            department=department, payment_status=Payment.Status.PENDING
        )
        .exclude(payment_method=Payment.Method.PROVIDER)
        .count(),
        "pending_online": Payment.objects.filter(
            department=department,
            payment_status=Payment.Status.PENDING,
            payment_method=Payment.Method.PROVIDER,
        ).count(),
        "pending_waivers": WaiverRequest.objects.filter(
            dues_assessment__dues_type__department=department, status=WaiverRequest.Status.PENDING
        ).count(),
        "pending_adjustments": PaymentAdjustment.objects.filter(
            payment__department=department,
            adjustment_status__in=[
                PaymentAdjustment.Status.REQUESTED,
                PaymentAdjustment.Status.PENDING_APPROVAL,
            ],
        ).count(),
    }
