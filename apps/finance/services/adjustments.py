"""Refunds, reversals and corrections against confirmed payments.

Lifecycle: pending_approval -> approved -> processed | rejected | failed.
- Requested by a finance officer (record or verify permission).
- Approved by someone holding finance.adjustment.approve who did not request it.
- Processed (money actually returned) by a finance officer, with the provider reference.
Only processed adjustments change balances: each states which allocations it reverses.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.access.services import has_any_perm
from apps.audit.services import record, snapshot

from ..models import (
    CONFIRMED_PAYMENT_STATES,
    Payment,
    PaymentAdjustment,
    PaymentAllocation,
    PaymentAllocationAdjustment,
    Receipt,
)
from ..signals import adjustment_processed
from .errors import FinanceError, require_perm

REQUESTERS = ("finance.payment.verify", "finance.payment.record")
OPEN_STATES = (
    PaymentAdjustment.Status.REQUESTED,
    PaymentAdjustment.Status.PENDING_APPROVAL,
    PaymentAdjustment.Status.APPROVED,
    PaymentAdjustment.Status.PROCESSED,
)
ZERO = Decimal("0")


def _sum(qs, field):
    return qs.aggregate(total=Sum(field))["total"] or ZERO


def refundable_amount(payment):
    """Payment amount less every adjustment that isn't rejected or failed."""
    return payment.amount - _sum(payment.adjustments.filter(adjustment_status__in=OPEN_STATES), "amount")


def reversible_amount(allocation):
    """Allocation amount less reversals already requested or processed against it."""
    taken = _sum(
        allocation.adjustments.filter(payment_adjustment__adjustment_status__in=OPEN_STATES),
        "amount_reversed",
    )
    return allocation.amount_allocated - taken


def unallocated_refundable(payment):
    """Money on the payment never applied to dues, less open adjustments that drew on it."""
    allocated = _sum(payment.allocations.all(), "amount_allocated")
    open_adjustments = payment.adjustments.filter(adjustment_status__in=OPEN_STATES)
    drawn = _sum(open_adjustments, "amount") - _sum(
        PaymentAllocationAdjustment.objects.filter(payment_adjustment__in=open_adjustments), "amount_reversed"
    )
    return payment.amount - allocated - drawn


def default_reversals(payment, amount):
    """Take unapplied money first, then reverse allocations newest first."""
    remaining = amount - max(unallocated_refundable(payment), ZERO)
    plan = []
    for allocation in payment.allocations.order_by("-allocated_at"):
        if remaining <= 0:
            break
        take = min(reversible_amount(allocation), remaining)
        if take > 0:
            plan.append((allocation, take))
            remaining -= take
    return plan


@transaction.atomic
def request_adjustment(payment, *, actor, adjustment_type, amount, reason, reversals=None):
    if not has_any_perm(actor, REQUESTERS, payment.department):
        require_perm(actor, REQUESTERS[0], payment.department)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.payment_status not in CONFIRMED_PAYMENT_STATES:
        raise FinanceError("Only confirmed payments can be refunded or reversed.")
    amount = Decimal(amount)
    if amount <= 0:
        raise FinanceError("The amount must be greater than zero.")
    if amount > refundable_amount(payment):
        raise FinanceError("That's more than is left to refund on this payment.")
    if not (reason or "").strip():
        raise FinanceError("Give a reason. It's shown to the approver and kept in the audit trail.")

    plan = (
        default_reversals(payment, amount) if reversals is None else [(a, Decimal(x)) for a, x in reversals]
    )
    reversed_total = ZERO
    for allocation, value in plan:
        if allocation.payment_id != payment.pk:
            raise FinanceError("You can only reverse this payment's own allocations.")
        if value <= 0:
            raise FinanceError("Reversal amounts must be greater than zero.")
        if value > reversible_amount(allocation):
            raise FinanceError("A reversal is more than what's still applied to those dues.")
        reversed_total += value
    if reversed_total > amount:
        raise FinanceError("The reversals add up to more than the refund.")
    if amount - reversed_total > unallocated_refundable(payment):
        raise FinanceError(
            "Choose which dues the refund comes out of: the rest of the payment is applied to dues."
        )

    adjustment = PaymentAdjustment.objects.create(
        payment=payment,
        adjustment_type=adjustment_type,
        amount=amount,
        reason=reason.strip(),
        adjustment_status=PaymentAdjustment.Status.PENDING_APPROVAL,
        requested_by=actor,
    )
    PaymentAllocationAdjustment.objects.bulk_create(
        PaymentAllocationAdjustment(
            payment_adjustment=adjustment,
            payment_allocation=allocation,
            amount_reversed=value,
            created_by=actor,
        )
        for allocation, value in plan
    )
    record(
        "adjustment.requested",
        adjustment,
        actor=actor,
        department=payment.department,
        after={**snapshot(adjustment), "reversals": [[str(a.pk), str(v)] for a, v in plan]},
    )
    return adjustment


def _locked(adjustment):
    return (
        PaymentAdjustment.objects.select_for_update()
        .select_related("payment__department")
        .get(pk=adjustment.pk)
    )


@transaction.atomic
def decide_adjustment(adjustment, *, actor, approve, note=""):
    adjustment = _locked(adjustment)
    department = adjustment.payment.department
    require_perm(actor, "finance.adjustment.approve", department)
    if adjustment.adjustment_status != PaymentAdjustment.Status.PENDING_APPROVAL:
        raise FinanceError("This request has already been decided.")
    if adjustment.requested_by_id == actor.pk:
        raise FinanceError("You can't approve a refund you requested.")
    before = snapshot(adjustment)
    adjustment.adjustment_status = (
        PaymentAdjustment.Status.APPROVED if approve else PaymentAdjustment.Status.REJECTED
    )
    adjustment.approved_by = actor
    adjustment.save(update_fields=["adjustment_status", "approved_by"])
    record(
        "adjustment.approved" if approve else "adjustment.rejected",
        adjustment,
        actor=actor,
        department=department,
        before=before,
        after={**snapshot(adjustment), "note": note},
    )
    return adjustment


@transaction.atomic
def process_adjustment(adjustment, *, actor, provider_reference=""):
    """Record that the money has actually been returned. Balances change only now."""
    adjustment = _locked(adjustment)
    payment = Payment.objects.select_for_update().get(pk=adjustment.payment_id)
    if not has_any_perm(actor, REQUESTERS, payment.department):
        require_perm(actor, REQUESTERS[0], payment.department)
    if adjustment.adjustment_status != PaymentAdjustment.Status.APPROVED:
        raise FinanceError("Only approved requests can be processed.")
    if adjustment.approved_by_id == actor.pk:
        raise FinanceError("The approver can't also process the refund.")

    before = snapshot(payment)
    adjustment.adjustment_status = PaymentAdjustment.Status.PROCESSED
    adjustment.processed_at = timezone.now()
    adjustment.provider_reference = (provider_reference or "").strip() or None
    adjustment.save(update_fields=["adjustment_status", "processed_at", "provider_reference"])

    processed = _sum(
        payment.adjustments.filter(adjustment_status=PaymentAdjustment.Status.PROCESSED), "amount"
    )
    payment.payment_status = (
        Payment.Status.REFUNDED if processed >= payment.amount else Payment.Status.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["payment_status"])
    if payment.payment_status == Payment.Status.REFUNDED:
        Receipt.objects.filter(payment=payment, receipt_status=Receipt.Status.ISSUED).update(
            receipt_status=Receipt.Status.VOIDED, updated_at=timezone.now()
        )
    record(
        "adjustment.processed",
        adjustment,
        actor=actor,
        department=payment.department,
        before={"payment": before},
        after={"payment_status": payment.payment_status, "provider_reference": adjustment.provider_reference},
    )
    transaction.on_commit(lambda: adjustment_processed.send(sender=PaymentAdjustment, adjustment=adjustment))
    return adjustment


def allocations_with_reversible(payment):
    rows = []
    for allocation in PaymentAllocation.objects.filter(payment=payment).select_related(
        "dues_assessment__dues_type", "dues_assessment__department_membership__academic_session"
    ):
        allocation.reversible = reversible_amount(allocation)
        rows.append(allocation)
    return rows
