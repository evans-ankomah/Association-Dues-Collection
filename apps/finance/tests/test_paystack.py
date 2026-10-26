import hashlib
import hmac
import json
from decimal import Decimal

import pytest
import responses
from django.conf import settings

from apps.finance.models import Payment, Receipt, WebhookEvent
from apps.finance.services import online
from apps.finance.services.balances import assessment_balance
from apps.finance.services.errors import FinanceError
from apps.finance.services.paystack import from_minor_units, to_minor_units

pytestmark = pytest.mark.django_db

API = "https://api.paystack.co"
WEBHOOK = "/finance/webhooks/paystack/"


def sign(body: bytes) -> str:
    return hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()


def charge_success(payment, **overrides):
    data = {
        "id": 3884423779,
        "status": "success",
        "reference": payment.provider_reference,
        "amount": to_minor_units(payment.amount),
        "currency": "GHS",
        "channel": "mobile_money",
        "paid_at": "2026-10-20T08:36:00.000Z",
        **overrides,
    }
    return {"event": "charge.success", "data": data}


def post_webhook(client, payload, signature=None):
    body = json.dumps(payload).encode()
    return client.post(
        WEBHOOK,
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=signature if signature is not None else sign(body),
    )


@pytest.fixture
def started(membership, member, assessment):
    with responses.RequestsMock() as rsps:
        rsps.post(
            f"{API}/transaction/initialize",
            json={
                "status": True,
                "data": {"authorization_url": "https://checkout.paystack.com/abc", "reference": "x"},
            },
        )
        payment, url = online.start_online_payment(
            membership, actor=member, assessment_ids=[assessment.pk], callback_url="http://testserver/cb"
        )
        sent = json.loads(rsps.calls[0].request.body)
    assert url == "https://checkout.paystack.com/abc"
    assert sent["amount"] == 15000 and sent["currency"] == "GHS"
    assert sent["reference"] == payment.provider_reference
    return payment


def test_minor_unit_conversion_is_exact():
    assert to_minor_units(Decimal("150.00")) == 15000
    assert to_minor_units(Decimal("19.99")) == 1999
    assert from_minor_units(1999) == Decimal("19.99")


def test_start_creates_pending_provider_payment(started, assessment):
    assert started.payment_status == Payment.Status.PENDING
    assert started.payment_method == Payment.Method.PROVIDER
    assert started.provider_reference.startswith("DH-")
    assert started.intended_allocations == [{"assessment_id": str(assessment.pk), "amount": "150.00"}]


def test_valid_webhook_confirms_allocates_and_receipts(client, started, assessment):
    response = post_webhook(client, charge_success(started))
    assert response.status_code == 200
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.CONFIRMED
    assert started.external_reference == "3884423779"
    assert assessment_balance(assessment) == 0
    assert Receipt.objects.filter(payment=started).exists()
    event = WebhookEvent.objects.get()
    assert event.processing_status == WebhookEvent.Status.PROCESSED
    assert event.safe_metadata["amount_pesewas"] == 15000


def test_duplicate_webhook_is_idempotent(client, started):
    payload = charge_success(started)
    post_webhook(client, payload)
    post_webhook(client, payload)
    assert WebhookEvent.objects.count() == 1
    assert Receipt.objects.count() == 1
    assert started.allocations.count() == 1


def test_forged_signature_is_rejected_and_cannot_block_the_real_event(client, started):
    payload = charge_success(started)
    assert post_webhook(client, payload, signature="bad").status_code == 401
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.PENDING
    assert post_webhook(client, payload).status_code == 200
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.CONFIRMED


@pytest.mark.parametrize(
    "override", [{"amount": 1500}, {"currency": "NGN"}], ids=["wrong-amount", "wrong-currency"]
)
def test_mismatched_webhook_leaves_payment_pending_and_flags_it(client, started, assessment, override):
    post_webhook(client, charge_success(started, **override))
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.PENDING
    assert "needs reconciliation" in started.notes
    assert WebhookEvent.objects.get().processing_status == WebhookEvent.Status.FAILED
    assert assessment_balance(assessment) == Decimal("150.00")


def test_unknown_reference_is_ignored(client, started):
    post_webhook(client, charge_success(started, reference="SOMEONE-ELSE", id=1))
    assert WebhookEvent.objects.get().processing_status == WebhookEvent.Status.IGNORED


def test_other_events_are_ignored(client):
    post_webhook(client, {"event": "transfer.success", "data": {"id": 7}})
    assert WebhookEvent.objects.get().processing_status == WebhookEvent.Status.IGNORED


def test_callback_verifies_with_paystack_before_showing_success(started, member, login):
    client = login(member)
    with responses.RequestsMock() as rsps:
        rsps.get(
            f"{API}/transaction/verify/{started.provider_reference}",
            json={"status": True, "data": charge_success(started)["data"]},
        )
        page = client.get("/finance/pay/callback/", {"reference": started.provider_reference})
    assert page.status_code == 200
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.CONFIRMED


def test_abandoned_checkout_marks_payment_failed(started, member, login):
    client = login(member)
    with responses.RequestsMock() as rsps:
        rsps.get(
            f"{API}/transaction/verify/{started.provider_reference}",
            json={"status": True, "data": {**charge_success(started)["data"], "status": "abandoned"}},
        )
        client.get("/finance/pay/callback/", {"reference": started.provider_reference})
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.FAILED


def test_late_success_after_failure_still_confirms(client, started):
    Payment.objects.filter(pk=started.pk).update(payment_status=Payment.Status.FAILED)
    post_webhook(client, charge_success(started))
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.CONFIRMED


def test_dues_paid_elsewhere_meanwhile_leave_surplus_unallocated(
    client, started, assessment, finsec, make_user
):
    from apps.finance.services.payments import record_offline_payment, unallocated_amount, verify_payment

    cash = record_offline_payment(started.payer_membership, actor=finsec, method="cash", amount="150")
    verify_payment(cash, actor=make_user("treasurer"))
    post_webhook(client, charge_success(started))
    started.refresh_from_db()
    assert started.payment_status == Payment.Status.CONFIRMED
    assert unallocated_amount(started) == Decimal("150.00")


def test_cannot_view_someone_elses_callback(started, make_user, login):
    client = login(make_user("student_member"))
    assert client.get("/finance/pay/callback/", {"reference": started.provider_reference}).status_code == 404


def test_paystack_failure_cancels_the_attempt(membership, member, assessment):
    with responses.RequestsMock() as rsps:
        rsps.post(
            f"{API}/transaction/initialize", json={"status": False, "message": "Invalid key"}, status=401
        )
        with pytest.raises(FinanceError, match="Invalid key"):
            online.start_online_payment(
                membership, actor=member, assessment_ids=[assessment.pk], callback_url="http://x/cb"
            )
    assert Payment.objects.get().payment_status == Payment.Status.CANCELLED


def test_not_configured_shows_alternative(settings, member, login, assessment):
    settings.PAYSTACK_SECRET_KEY = ""
    page = login(member).get("/finance/pay/")
    assert page.context["configured"] is False
