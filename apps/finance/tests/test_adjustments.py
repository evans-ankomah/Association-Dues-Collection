from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.communications.models import Notification
from apps.finance.models import Payment, PaymentAdjustment, Receipt
from apps.finance.services import adjustments as svc
from apps.finance.services import payments as pay_service
from apps.finance.services.balances import assessment_balance
from apps.finance.services.errors import FinanceError

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(make_user):
    return make_user("treasurer")


@pytest.fixture
def paid(membership, assessment, finsec, treasurer):
    payment = pay_service.record_offline_payment(membership, actor=finsec, method="cash", amount="150.00")
    pay_service.verify_payment(payment, actor=treasurer)
    payment.refresh_from_db()
    return payment


def test_full_refund_lifecycle_restores_balance_and_voids_receipt(
    paid, assessment, treasurer, hod, finsec, member, django_capture_on_commit_callbacks
):
    adjustment = svc.request_adjustment(
        paid, actor=treasurer, adjustment_type="refund", amount="150.00", reason="Duplicate payment"
    )
    assert adjustment.adjustment_status == PaymentAdjustment.Status.PENDING_APPROVAL
    assert assessment_balance(assessment) == 0  # nothing changes until processed

    svc.decide_adjustment(adjustment, actor=hod, approve=True)
    with django_capture_on_commit_callbacks(execute=True):
        svc.process_adjustment(adjustment, actor=finsec, provider_reference="55976795643")

    paid.refresh_from_db()
    assert paid.payment_status == Payment.Status.REFUNDED
    assert assessment_balance(assessment) == Decimal("150.00")
    assert Receipt.objects.get(payment=paid).receipt_status == Receipt.Status.VOIDED
    assert Notification.objects.filter(user=member, notification_type="payment_refunded").exists()


def test_partial_refund(paid, assessment, treasurer, hod, finsec):
    adjustment = svc.request_adjustment(
        paid, actor=treasurer, adjustment_type="refund", amount="50", reason="x"
    )
    svc.decide_adjustment(adjustment, actor=hod, approve=True)
    svc.process_adjustment(adjustment, actor=finsec)
    paid.refresh_from_db()
    assert paid.payment_status == Payment.Status.PARTIALLY_REFUNDED
    assert assessment_balance(assessment) == Decimal("50.00")
    assert Receipt.objects.get(payment=paid).receipt_status == Receipt.Status.ISSUED


def test_overpayment_surplus_refunded_without_touching_dues(membership, assessment, finsec, treasurer, hod):
    payment = pay_service.record_offline_payment(membership, actor=finsec, method="cash", amount="200.00")
    pay_service.verify_payment(payment, actor=treasurer)
    adjustment = svc.request_adjustment(
        payment, actor=treasurer, adjustment_type="refund", amount="50", reason="Overpaid"
    )
    assert not adjustment.allocation_adjustments.exists()
    svc.decide_adjustment(adjustment, actor=hod, approve=True)
    svc.process_adjustment(adjustment, actor=finsec)
    assert assessment_balance(assessment) == 0


def test_cannot_refund_more_than_paid_or_twice(paid, treasurer):
    with pytest.raises(FinanceError, match="left to refund"):
        svc.request_adjustment(paid, actor=treasurer, adjustment_type="refund", amount="151", reason="x")
    svc.request_adjustment(paid, actor=treasurer, adjustment_type="refund", amount="100", reason="x")
    with pytest.raises(FinanceError, match="left to refund"):
        svc.request_adjustment(paid, actor=treasurer, adjustment_type="refund", amount="100", reason="y")


def test_reversal_cannot_exceed_allocation(paid, treasurer):
    allocation = paid.allocations.get()
    with pytest.raises(FinanceError, match="more than what's still applied"):
        svc.request_adjustment(
            paid,
            actor=treasurer,
            adjustment_type="reversal",
            amount="150",
            reason="x",
            reversals=[(allocation, Decimal("160"))],
        )


def test_requester_cannot_approve_and_approver_cannot_process(paid, make_user, department, hod):
    from apps.common.tests.factories import grant

    both = make_user("treasurer")
    grant(both, "hod_faculty_adviser", department)
    adjustment = svc.request_adjustment(paid, actor=both, adjustment_type="refund", amount="10", reason="x")
    with pytest.raises(FinanceError, match="you requested"):
        svc.decide_adjustment(adjustment, actor=both, approve=True)

    approver = make_user("hod_faculty_adviser")
    grant(approver, "treasurer", department)
    svc.decide_adjustment(adjustment, actor=approver, approve=True)
    with pytest.raises(FinanceError, match="approver can't also process"):
        svc.process_adjustment(adjustment, actor=approver)


def test_only_finance_and_approvers(paid, member, treasurer):
    with pytest.raises(PermissionDenied):
        svc.request_adjustment(paid, actor=member, adjustment_type="refund", amount="1", reason="x")
    adjustment = svc.request_adjustment(
        paid, actor=treasurer, adjustment_type="refund", amount="1", reason="x"
    )
    with pytest.raises(PermissionDenied):
        svc.decide_adjustment(adjustment, actor=treasurer, approve=True)


def test_rejected_requests_free_up_the_amount(paid, treasurer, hod):
    adjustment = svc.request_adjustment(
        paid, actor=treasurer, adjustment_type="refund", amount="150", reason="x"
    )
    svc.decide_adjustment(adjustment, actor=hod, approve=False)
    assert svc.refundable_amount(paid) == Decimal("150.00")
    with pytest.raises(FinanceError, match="Only approved"):
        svc.process_adjustment(adjustment, actor=treasurer)


def test_pending_payments_cannot_be_refunded(membership, finsec, treasurer):
    payment = pay_service.record_offline_payment(membership, actor=finsec, method="cash", amount="10")
    with pytest.raises(FinanceError, match="Only confirmed"):
        svc.request_adjustment(payment, actor=treasurer, adjustment_type="refund", amount="5", reason="x")


def test_views_flow(paid, treasurer, hod, finsec, login, assessment):
    allocation = paid.allocations.get()
    client = login(treasurer)
    client.post(
        f"/finance/payments/{paid.pk}/refund/",
        {
            "adjustment_type": "refund",
            "amount": "40",
            "reason": "Asked for part back",
            f"rev_{allocation.pk}": "40",
        },
    )
    adjustment = PaymentAdjustment.objects.get()
    login(hod).post(f"/finance/adjustments/{adjustment.pk}/decide/", {"decision": "approve"})
    login(finsec).post(f"/finance/adjustments/{adjustment.pk}/process/", {"provider_reference": "R1"})
    adjustment.refresh_from_db()
    assert adjustment.adjustment_status == PaymentAdjustment.Status.PROCESSED
    assert assessment_balance(assessment) == Decimal("40.00")
