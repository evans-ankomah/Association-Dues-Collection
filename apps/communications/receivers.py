"""Tell members about things that happened to their money."""

from django.dispatch import receiver
from django.urls import reverse

from apps.finance.signals import payment_confirmed, payment_rejected, waiver_decided
from apps.finance.templatetags.money import money

from .delivery import notify


def _payer(payment):
    return payment.payer_membership.user if payment.payer_membership_id else None


@receiver(payment_confirmed)
def on_payment_confirmed(sender, payment, **kwargs):
    user = _payer(payment)
    if user is None:
        return
    receipt = payment.receipt
    names = ", ".join(
        a.dues_assessment.dues_type.name
        for a in payment.allocations.select_related("dues_assessment__dues_type")
    )
    body = f"We have received {money(payment.amount, payment.currency)}"
    body += f" for {names}." if names else "."
    body += f" Receipt {receipt.receipt_number}."
    notify(
        user,
        notification_type="payment_confirmed",
        title=f"Payment confirmed - receipt {receipt.receipt_number}",
        body=body,
        link=reverse("finance:receipt", args=[receipt.pk]),
        channels=("in_app", "email", "sms"),
        dedupe_key=f"payment_confirmed:{payment.pk}",
    )


@receiver(payment_rejected)
def on_payment_rejected(sender, payment, reason, **kwargs):
    user = _payer(payment)
    if user is None:
        return
    notify(
        user,
        notification_type="payment_failed",
        title="We couldn't confirm your payment",
        body=(
            f"Your {payment.method_label} payment of {money(payment.amount, payment.currency)} "
            f"(ref {payment.external_reference or payment.provider_reference or '—'}) "
            f"wasn't confirmed: {reason}. "
            "Contact the Treasurer if you think this is wrong."
        ),
        link=reverse("finance:payment", args=[payment.pk]),
        dedupe_key=f"payment_failed:{payment.pk}",
    )


@receiver(waiver_decided)
def on_waiver_decided(sender, waiver, **kwargs):
    assessment = waiver.dues_assessment
    user = assessment.department_membership.user
    approved = waiver.status == waiver.Status.APPROVED
    notify(
        user,
        notification_type="waiver_decided",
        title="Waiver approved" if approved else "Waiver not approved",
        body=(
            f"Your waiver request of {money(waiver.amount)} for {assessment.dues_type.name} was "
            f"{'approved' if approved else 'not approved'}."
            + (f" Note: {waiver.decision_note}" if waiver.decision_note else "")
        ),
        link=reverse("finance:assessment", args=[assessment.pk]),
        dedupe_key=f"waiver:{waiver.pk}",
    )
