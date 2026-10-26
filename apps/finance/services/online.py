"""Online payments through Paystack.

The browser redirect is never trusted. A payment is confirmed only from a signed webhook or a
server-side verify call, and only when status, reference, currency and amount (in pesewas)
all match. Processing is idempotent: repeated webhooks or callbacks change nothing.
"""

import hashlib
import json
import logging
import secrets
import string
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.services import record, snapshot

from ..models import DuesAssessment, Payment, WebhookEvent
from . import paystack
from .balances import with_balances
from .errors import FinanceError, require_perm
from .payments import confirm_payment, outstanding_assessments, suggest_allocations

logger = logging.getLogger(__name__)

PROVIDER = "Paystack"
_REF_ALPHABET = string.ascii_uppercase + string.digits


class Outcome:
    CONFIRMED = "confirmed"
    ALREADY_CONFIRMED = "already_confirmed"
    FAILED = "failed"
    PENDING = "pending"
    MISMATCH = "mismatch"
    UNKNOWN_REFERENCE = "unknown_reference"


def new_reference(department):
    suffix = "".join(secrets.choice(_REF_ALPHABET) for _ in range(10))
    return f"DH-{department.code}-{suffix}"


def start_online_payment(membership, *, actor, assessment_ids, callback_url):
    """Create a pending Paystack payment for the chosen dues and return the checkout URL."""
    if membership.user_id != actor.pk:
        raise FinanceError("You can only pay your own dues online.")
    require_perm(actor, "finance.payment.initiate", membership.department)
    if not paystack.is_configured():
        raise FinanceError("Online payment isn't available yet. Pay by MoMo or cash and report it instead.")

    chosen = [a for a in outstanding_assessments(membership) if str(a.pk) in {str(i) for i in assessment_ids}]
    if not chosen:
        raise FinanceError("Choose at least one due to pay.")
    total = sum((a.balance for a in chosen), Decimal("0"))

    with transaction.atomic():
        payment = Payment.objects.create(
            department=membership.department,
            payer_membership=membership,
            amount=total,
            currency=membership.department.default_currency,
            payment_method=Payment.Method.PROVIDER,
            provider_name=PROVIDER,
            provider_reference=new_reference(membership.department),
            idempotency_key=uuid.uuid4().hex,
            recorded_by=actor,
            intended_allocations=[{"assessment_id": str(a.pk), "amount": str(a.balance)} for a in chosen],
        )
        record(
            "payment.online_started",
            payment,
            actor=actor,
            department=payment.department,
            after=snapshot(payment),
        )

    try:
        data = paystack.initialize(
            email=actor.email,
            amount=total,
            currency=payment.currency,
            reference=payment.provider_reference,
            callback_url=callback_url,
            metadata={"payment_id": str(payment.pk), "department": membership.department.code},
        )
    except paystack.PaystackError as exc:
        Payment.objects.filter(pk=payment.pk, payment_status=Payment.Status.PENDING).update(
            payment_status=Payment.Status.CANCELLED,
            notes=f"Could not start checkout: {exc}",
            updated_at=timezone.now(),
        )
        raise FinanceError(str(exc)) from exc
    return payment, data["authorization_url"]


def _planned_allocations(payment):
    """The payer's chosen dues, capped at what's still owed; falls back to oldest-due-first."""
    intended = payment.intended_allocations or []
    ids = [row["assessment_id"] for row in intended]
    balances = {
        str(a.pk): a
        for a in with_balances(
            DuesAssessment.objects.filter(pk__in=ids, assessment_state=DuesAssessment.State.ACTIVE)
        ).select_related("dues_type", "department_membership")
    }
    plan, remaining = [], payment.amount
    for row in intended:
        assessment = balances.get(row["assessment_id"])
        if assessment is None or assessment.balance <= 0 or remaining <= 0:
            continue
        amount = min(Decimal(row["amount"]), assessment.balance, remaining)
        plan.append((assessment, amount))
        remaining -= amount
    if remaining > 0:
        # Something was paid by other means meanwhile; apply the rest to other outstanding dues.
        taken = {a.pk for a, _ in plan}
        for assessment, amount in suggest_allocations(payment):
            if remaining <= 0:
                break
            if assessment.pk in taken:
                continue
            amount = min(amount, remaining)
            plan.append((assessment, amount))
            remaining -= amount
    return plan


@transaction.atomic
def apply_provider_result(reference, data, *, source):
    """Apply a verified Paystack transaction record (from the verify API or a signed webhook)."""
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("payer_membership", "department")
        .filter(provider_name=PROVIDER, provider_reference=reference)
        .first()
    )
    if payment is None:
        return Outcome.UNKNOWN_REFERENCE, None
    if payment.is_confirmed:
        return Outcome.ALREADY_CONFIRMED, payment

    status = data.get("status")
    if status != "success":
        if status in ("failed", "abandoned", "reversed") and payment.payment_status == Payment.Status.PENDING:
            payment.payment_status = Payment.Status.FAILED
            payment.notes = f"Paystack reported '{status}' ({source})."
            payment.save(update_fields=["payment_status", "notes"])
            record(
                "payment.provider_failed", payment, department=payment.department, after={"status": status}
            )
            return Outcome.FAILED, payment
        return Outcome.PENDING, payment

    problems = []
    if data.get("reference") != payment.provider_reference:
        problems.append("reference")
    if (data.get("currency") or "").upper() != payment.currency:
        problems.append(f"currency {data.get('currency')!r}")
    try:
        if int(data.get("amount")) != paystack.to_minor_units(payment.amount):
            problems.append(f"amount {data.get('amount')} pesewas")
    except (TypeError, ValueError):
        problems.append("amount missing")
    if problems:
        note = f"Paystack {source} did not match ({', '.join(problems)}); needs reconciliation."
        payment.notes = "\n".join(filter(None, [payment.notes, note]))
        payment.save(update_fields=["notes"])
        record(
            "payment.provider_mismatch", payment, department=payment.department, after={"problems": problems}
        )
        logger.warning("Paystack mismatch for payment %s: %s", payment.pk, problems)
        return Outcome.MISMATCH, payment

    if payment.payment_status != Payment.Status.PENDING:
        # We'd given up (failed/cancelled) but the money did arrive. Reopen and confirm.
        payment.payment_status = Payment.Status.PENDING
        payment.save(update_fields=["payment_status"])
    if data.get("id") is not None:
        payment.external_reference = str(data["id"])
    channel = data.get("channel")
    if channel:
        payment.notes = "\n".join(filter(None, [payment.notes, f"Paid via Paystack ({channel})."]))
    payment.save(update_fields=["external_reference", "notes"])
    paid_at = parse_datetime(data["paid_at"]) if data.get("paid_at") else None
    confirm_payment(
        payment, verified_by=None, allocations=_planned_allocations(payment), confirmed_at=paid_at
    )
    return Outcome.CONFIRMED, payment


def verify_with_provider(payment):
    """Ask Paystack directly about a pending online payment (callback page, reconciliation)."""
    if payment.payment_method != Payment.Method.PROVIDER or payment.is_confirmed:
        return Outcome.ALREADY_CONFIRMED if payment.is_confirmed else Outcome.PENDING
    data = paystack.verify(payment.provider_reference)
    outcome, _ = apply_provider_result(payment.provider_reference, data, source="verify")
    return outcome


def _safe_metadata(data):
    return {
        "reference": data.get("reference"),
        "amount_pesewas": data.get("amount"),
        "currency": data.get("currency"),
        "channel": data.get("channel"),
    }


def handle_webhook(raw_body: bytes, signature: str | None):
    """Process a Paystack webhook. Returns the HTTP status code to send back."""
    digest = hashlib.sha256(raw_body).hexdigest()
    try:
        payload = json.loads(raw_body)
    except ValueError:
        return 400
    event_type = str(payload.get("event") or "unknown")[:120]
    data = payload.get("data") or {}

    if not paystack.signature_is_valid(raw_body, signature):
        # Keep a trace, but under a key an attacker can't use to block a real event id.
        WebhookEvent.objects.get_or_create(
            provider_name=PROVIDER,
            provider_event_id=f"unverified:{digest}",
            defaults={
                "event_type": event_type,
                "signature_valid": False,
                "processing_status": WebhookEvent.Status.IGNORED,
                "payload_sha256": digest,
            },
        )
        logger.warning("Rejected Paystack webhook with an invalid signature.")
        return 401

    event_id = str(data.get("id")) if event_type == "charge.success" else f"{event_type}:{data.get('id')}"
    try:
        with transaction.atomic():
            event, created = WebhookEvent.objects.select_for_update().get_or_create(
                provider_name=PROVIDER,
                provider_event_id=event_id[:200],
                defaults={
                    "event_type": event_type,
                    "signature_valid": True,
                    "processing_status": WebhookEvent.Status.PROCESSING,
                    "payload_sha256": digest,
                    "safe_metadata": _safe_metadata(data),
                },
            )
            if not created and event.processing_status in (
                WebhookEvent.Status.PROCESSED,
                WebhookEvent.Status.IGNORED,
            ):
                return 200  # duplicate delivery

            if event_type != "charge.success":
                status = WebhookEvent.Status.IGNORED
            else:
                try:
                    outcome, _ = apply_provider_result(data.get("reference"), data, source="webhook")
                except FinanceError:
                    logger.exception("Paystack webhook %s could not be applied.", event_id)
                    outcome = Outcome.MISMATCH
                status = {
                    Outcome.CONFIRMED: WebhookEvent.Status.PROCESSED,
                    Outcome.ALREADY_CONFIRMED: WebhookEvent.Status.PROCESSED,
                    Outcome.UNKNOWN_REFERENCE: WebhookEvent.Status.IGNORED,
                    Outcome.MISMATCH: WebhookEvent.Status.FAILED,
                }.get(outcome, WebhookEvent.Status.PROCESSED)
            event.processing_status = status
            event.processed_at = timezone.now()
            event.save(update_fields=["processing_status", "processed_at"])
    except IntegrityError:
        return 200  # a concurrent delivery of the same event won the race
    return 200
