"""Recording, verifying and allocating payments.

Lifecycle: pending -> confirmed (allocated + receipted) | failed | cancelled.
Separation of duties: whoever recorded a payment, and the payer, can never verify it.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record, snapshot

from ..models import DuesAssessment, Payment, PaymentAllocation
from ..signals import payment_confirmed, payment_rejected
from .balances import with_balances
from .errors import FinanceError, require_perm
from .receipts import issue_receipt

OFFLINE_METHODS = (Payment.Method.CASH, Payment.Method.BANK_TRANSFER, Payment.Method.MOBILE_MONEY)
SELF_REPORT_METHODS = (Payment.Method.BANK_TRANSFER, Payment.Method.MOBILE_MONEY)


def outstanding_assessments(membership):
    """The payer's assessments in this department with something left to pay, oldest due first."""
    return (
        with_balances(
            DuesAssessment.objects.filter(
                department_membership__user_id=membership.user_id,
                department_membership__department_id=membership.department_id,
                assessment_state=DuesAssessment.State.ACTIVE,
            ).select_related("dues_type", "department_membership__academic_session")
        )
        .filter(balance__gt=0)
        .order_by("due_date", "assessed_at")
    )


def suggest_allocations(payment):
    """Oldest-due-first split of the payment across the payer's outstanding assessments."""
    remaining = payment.amount
    plan = []
    if payment.payer_membership_id is None:
        return plan
    for assessment in outstanding_assessments(payment.payer_membership):
        if remaining <= 0:
            break
        amount = min(assessment.balance, remaining)
        plan.append((assessment, amount))
        remaining -= amount
    return plan


def _validate_amount(amount):
    amount = Decimal(amount)
    if amount <= 0:
        raise FinanceError("The amount must be greater than zero.")
    if amount.as_tuple().exponent < -2:
        raise FinanceError("Use at most two decimal places.")
    return amount


@transaction.atomic
def record_offline_payment(membership, *, actor, method, amount, reference="", notes="", provider_name=None):
    """A finance officer records money received outside the online provider (status: pending)."""
    require_perm(actor, "finance.payment.record", membership.department)
    if method not in OFFLINE_METHODS:
        raise FinanceError("Choose cash, bank transfer or mobile money.")
    if method != Payment.Method.CASH and not (reference or "").strip():
        raise FinanceError("Enter the transaction or bank reference.")
    payment = Payment.objects.create(
        department=membership.department,
        payer_membership=membership,
        amount=_validate_amount(amount),
        currency=membership.department.default_currency,
        payment_method=method,
        provider_name=(provider_name or "").strip() or _provider_for(method),
        external_reference=(reference or "").strip() or None,
        recorded_by=actor,
        notes=(notes or "").strip() or None,
    )
    record("payment.recorded", payment, actor=actor, department=payment.department, after=snapshot(payment))
    return payment


@transaction.atomic
def submit_payment_claim(membership, *, actor, method, amount, reference, notes="", provider_name=None):
    """A member reports a MoMo or bank transfer they made, for the Treasurer to check (status: pending)."""
    if membership.user_id != actor.pk:
        raise FinanceError("You can only report your own payments.")
    require_perm(actor, "finance.payment.initiate", membership.department)
    if method not in SELF_REPORT_METHODS:
        raise FinanceError("Choose mobile money or bank transfer.")
    reference = (reference or "").strip()
    if not reference:
        raise FinanceError("Enter the transaction ID from your MoMo or bank message.")
    duplicate = Payment.objects.filter(
        department=membership.department, external_reference=reference
    ).exclude(payment_status__in=[Payment.Status.FAILED, Payment.Status.CANCELLED])
    if duplicate.exists():
        raise FinanceError("A payment with that transaction ID has already been reported.")
    payment = Payment.objects.create(
        department=membership.department,
        payer_membership=membership,
        amount=_validate_amount(amount),
        currency=membership.department.default_currency,
        payment_method=method,
        provider_name=(provider_name or "").strip() or _provider_for(method),
        external_reference=reference,
        recorded_by=actor,
        notes=(notes or "").strip() or None,
    )
    record("payment.reported", payment, actor=actor, department=payment.department, after=snapshot(payment))
    return payment


def _provider_for(method):
    return {
        Payment.Method.MOBILE_MONEY: "Mobile money",
        Payment.Method.BANK_TRANSFER: "Bank transfer",
    }.get(method)


def _check_allocations(payment, allocations):
    """Validate a list of (assessment, amount) against the payment and current balances."""
    total = Decimal("0")
    seen = set()
    for assessment, amount in allocations:
        amount = Decimal(amount)
        if amount <= 0:
            continue
        if assessment.pk in seen:
            raise FinanceError("Each assessment can only appear once.")
        seen.add(assessment.pk)
        if assessment.dues_type.department_id != payment.department_id:
            raise FinanceError("Payments can only settle dues in their own department.")
        if (
            payment.payer_membership_id
            and assessment.department_membership.user_id != payment.payer_membership.user_id
        ):
            raise FinanceError("Payments can only settle the payer's own dues.")
        balance = with_balances(DuesAssessment.objects.filter(pk=assessment.pk)).values_list(
            "balance", flat=True
        )[0]
        if amount > balance:
            raise FinanceError(
                f"{assessment.dues_type.name}: GHS {amount} is more than the GHS {balance} owed."
            )
        total += amount
    if total > payment.amount:
        raise FinanceError("The allocations add up to more than the payment.")
    return [(a, Decimal(x)) for a, x in allocations if Decimal(x) > 0]


def confirm_payment(payment, *, verified_by=None, allocations=None, confirmed_at=None):
    """Mark a locked pending payment confirmed, allocate it and issue a receipt.

    Shared by manual verification and provider webhooks. Caller holds the row lock and
    has checked permissions. `allocations` defaults to the oldest-due-first suggestion.
    """
    if payment.payment_status != Payment.Status.PENDING:
        raise FinanceError(f"This payment is already {payment.get_payment_status_display().lower()}.")
    plan = suggest_allocations(payment) if allocations is None else allocations
    # Lock the assessments being settled so two payments can't both pay the same balance.
    ids = [a.pk for a, _ in plan]
    list(DuesAssessment.objects.select_for_update().filter(pk__in=ids))
    plan = _check_allocations(payment, plan)

    now = confirmed_at or timezone.now()
    before = snapshot(payment)
    payment.payment_status = Payment.Status.CONFIRMED
    payment.confirmed_at = now
    payment.verified_by = verified_by
    payment.save(update_fields=["payment_status", "confirmed_at", "verified_by"])
    PaymentAllocation.objects.bulk_create(
        PaymentAllocation(
            payment=payment,
            dues_assessment=assessment,
            amount_allocated=amount,
            allocated_by=verified_by,
            allocated_at=now,
        )
        for assessment, amount in plan
    )
    receipt = issue_receipt(payment, issued_by=verified_by)
    allocated = sum((amount for _, amount in plan), Decimal("0"))
    record(
        "payment.confirmed",
        payment,
        actor=verified_by,
        department=payment.department,
        before=before,
        after={
            **snapshot(payment),
            "receipt_number": receipt.receipt_number,
            "allocated": str(allocated),
            "unallocated": str(payment.amount - allocated),
        },
    )
    transaction.on_commit(lambda: payment_confirmed.send(sender=Payment, payment=payment))
    return receipt


@transaction.atomic
def verify_payment(payment, *, actor, allocations=None):
    require_perm(actor, "finance.payment.verify", payment.department)
    payment = (
        Payment.objects.select_for_update(of=("self",)).select_related("payer_membership").get(pk=payment.pk)
    )
    if payment.recorded_by_id == actor.pk:
        raise FinanceError("You recorded this payment, so someone else must verify it.")
    if payment.payer_membership and payment.payer_membership.user_id == actor.pk:
        raise FinanceError("You can't verify your own payment.")
    if payment.payment_method == Payment.Method.PROVIDER:
        raise FinanceError("Online payments are confirmed automatically by the payment provider.")
    return confirm_payment(payment, verified_by=actor, allocations=allocations)


@transaction.atomic
def reject_payment(payment, *, actor, reason):
    """Mark a pending payment as failed, e.g. the reference isn't on the statement."""
    require_perm(actor, "finance.payment.verify", payment.department)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.payment_status != Payment.Status.PENDING:
        raise FinanceError("Only pending payments can be rejected.")
    if not (reason or "").strip():
        raise FinanceError("Say why the payment is being rejected.")
    before = snapshot(payment)
    payment.payment_status = Payment.Status.FAILED
    payment.verified_by = actor
    payment.notes = "\n".join(filter(None, [payment.notes, f"Rejected: {reason.strip()}"]))
    payment.save(update_fields=["payment_status", "verified_by", "notes"])
    record(
        "payment.rejected",
        payment,
        actor=actor,
        department=payment.department,
        before=before,
        after={**snapshot(payment), "reason": reason.strip()},
    )
    transaction.on_commit(
        lambda: payment_rejected.send(sender=Payment, payment=payment, reason=reason.strip())
    )
    return payment


@transaction.atomic
def cancel_payment(payment, *, actor):
    """The person who recorded or reported a pending payment withdraws it."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.recorded_by_id != actor.pk:
        raise FinanceError("Only the person who recorded this payment can withdraw it.")
    if payment.payment_status != Payment.Status.PENDING:
        raise FinanceError("Only pending payments can be withdrawn.")
    payment.payment_status = Payment.Status.CANCELLED
    payment.save(update_fields=["payment_status"])
    record("payment.cancelled", payment, actor=actor, department=payment.department, after=snapshot(payment))
    return payment


def unallocated_amount(payment):
    allocated = sum(payment.allocations.values_list("amount_allocated", flat=True), Decimal("0"))
    return payment.amount - allocated
