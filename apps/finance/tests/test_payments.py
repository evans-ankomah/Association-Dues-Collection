from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditEvent
from apps.common.tests.factories import DepartmentFactory
from apps.finance.models import Payment, Receipt, ReceiptCounter
from apps.finance.services import payments as svc
from apps.finance.services.balances import assessment_balance
from apps.finance.services.errors import FinanceError
from apps.finance.services.receipts import next_receipt_number
from apps.finance.signals import payment_confirmed

from .factories import AssessmentFactory, DuesTypeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(make_user):
    return make_user("treasurer")


def test_recorded_cash_payment_is_pending_until_verified(membership, assessment, finsec, treasurer):
    payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="150.00")
    assert payment.payment_status == Payment.Status.PENDING
    assert assessment_balance(assessment) == Decimal("150.00")

    receipt = svc.verify_payment(payment, actor=treasurer)
    payment.refresh_from_db()
    assert payment.payment_status == Payment.Status.CONFIRMED
    assert payment.verified_by == treasurer
    assert receipt.receipt_number.startswith(f"{membership.department.code}-")
    assert assessment_balance(assessment) == Decimal("0.00")
    assert AuditEvent.objects.filter(action_key="payment.confirmed", entity_id=payment.pk).exists()


def test_recorder_cannot_verify_own_payment(membership, assessment, make_user, department):
    from apps.common.tests.factories import grant

    both = make_user("financial_secretary")
    grant(both, "treasurer", department)
    payment = svc.record_offline_payment(membership, actor=both, method="cash", amount="10.00")
    with pytest.raises(FinanceError, match="someone else must verify"):
        svc.verify_payment(payment, actor=both)


def test_payer_cannot_verify_own_payment(make_user, department, session, finsec):
    from apps.common.tests.factories import MembershipFactory

    treasurer = make_user("treasurer")
    own = MembershipFactory(user=treasurer, department=department, academic_session=session)
    payment = svc.record_offline_payment(own, actor=finsec, method="cash", amount="10.00")
    with pytest.raises(FinanceError, match="your own payment"):
        svc.verify_payment(payment, actor=treasurer)


def test_only_finance_roles_can_record_or_verify(membership, member, finsec):
    with pytest.raises(PermissionDenied):
        svc.record_offline_payment(membership, actor=member, method="cash", amount="10")
    payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="10")
    with pytest.raises(PermissionDenied):
        svc.verify_payment(payment, actor=finsec)


def test_member_reports_momo_payment_and_duplicates_are_blocked(membership, member):
    payment = svc.submit_payment_claim(
        membership,
        actor=member,
        method="mobile_money",
        amount="150",
        reference="82116518706",
        provider_name="MTN MoMo",
    )
    assert payment.recorded_by == member
    assert payment.provider_name == "MTN MoMo"
    with pytest.raises(FinanceError, match="already been reported"):
        svc.submit_payment_claim(
            membership, actor=member, method="mobile_money", amount="150", reference="82116518706"
        )


def test_member_cannot_report_for_someone_else(membership, make_user):
    with pytest.raises(FinanceError):
        svc.submit_payment_claim(
            membership, actor=make_user("student_member"), method="mobile_money", amount="1", reference="x"
        )


def test_oldest_due_first_allocation_and_overpayment_left_unallocated(
    membership, dues_type, finsec, treasurer, department, session
):
    import datetime

    older = AssessmentFactory(
        dues_type=dues_type,
        department_membership=membership,
        amount_assessed=Decimal("100"),
        due_date=datetime.date(2026, 9, 1),
    )
    newer_type = DuesTypeFactory(department=department, academic_session=session, created_by=finsec)
    newer = AssessmentFactory(
        dues_type=newer_type,
        department_membership=membership,
        amount_assessed=Decimal("60"),
        due_date=datetime.date(2026, 12, 1),
    )
    payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="200.00")
    svc.verify_payment(payment, actor=treasurer)
    assert assessment_balance(older) == 0
    assert assessment_balance(newer) == 0
    assert svc.unallocated_amount(payment) == Decimal("40.00")


def test_explicit_allocation_cannot_exceed_balance_or_payment(membership, assessment, finsec, treasurer):
    payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="100.00")
    with pytest.raises(FinanceError, match="more than the payment"):
        svc.verify_payment(payment, actor=treasurer, allocations=[(assessment, Decimal("120"))])
    big = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="500.00")
    with pytest.raises(FinanceError, match="more than the GHS"):
        svc.verify_payment(big, actor=treasurer, allocations=[(assessment, Decimal("200"))])


def test_cannot_allocate_to_another_members_dues(membership, assessment, finsec, treasurer, make_membership):
    stranger = make_membership()
    payment = svc.record_offline_payment(stranger, actor=finsec, method="cash", amount="150.00")
    with pytest.raises(FinanceError, match="payer's own dues"):
        svc.verify_payment(payment, actor=treasurer, allocations=[(assessment, Decimal("150"))])


def test_verifying_twice_is_rejected(membership, assessment, finsec, treasurer):
    payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="150.00")
    svc.verify_payment(payment, actor=treasurer)
    with pytest.raises(FinanceError, match="already confirmed"):
        svc.verify_payment(payment, actor=treasurer)
    assert Receipt.objects.count() == 1


def test_reject_and_cancel(membership, finsec, treasurer, member):
    payment = svc.record_offline_payment(
        membership, actor=finsec, method="mobile_money", amount="5", reference="r1"
    )
    svc.reject_payment(payment, actor=treasurer, reason="Not on statement")
    payment.refresh_from_db()
    assert payment.payment_status == Payment.Status.FAILED
    claim = svc.submit_payment_claim(
        membership, actor=member, method="mobile_money", amount="5", reference="r2"
    )
    with pytest.raises(FinanceError):
        svc.cancel_payment(claim, actor=finsec)
    svc.cancel_payment(claim, actor=member)
    claim.refresh_from_db()
    assert claim.payment_status == Payment.Status.CANCELLED


def test_confirmation_signal_fires_after_commit(
    membership, assessment, finsec, treasurer, django_capture_on_commit_callbacks
):
    received = []
    payment_confirmed.connect(
        lambda sender, payment, **kw: received.append(payment.pk), weak=False, dispatch_uid="t"
    )
    try:
        payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="150")
        with django_capture_on_commit_callbacks(execute=True):
            svc.verify_payment(payment, actor=treasurer)
        assert received == [payment.pk]
    finally:
        payment_confirmed.disconnect(dispatch_uid="t")


def test_receipt_numbers_are_sequential_per_department_and_year(department):
    assert next_receipt_number(department, 2026) == f"{department.code}-2026-000001"
    assert next_receipt_number(department, 2026) == f"{department.code}-2026-000002"
    assert next_receipt_number(department, 2027) == f"{department.code}-2027-000001"
    other = DepartmentFactory(institution=department.institution, code="GEO")
    assert next_receipt_number(other, 2026) == "GEO-2026-000001"


def test_receipt_counter_continues_after_imported_receipts(membership, department, finsec, treasurer):
    payment = svc.record_offline_payment(membership, actor=finsec, method="cash", amount="1")
    Payment.objects.filter(pk=payment.pk).update(payment_status="confirmed", confirmed_at="2026-01-01T00:00Z")
    Receipt.objects.create(payment=payment, receipt_number=f"{department.code}-2026-000743")
    ReceiptCounter.objects.all().delete()
    assert next_receipt_number(department, 2026) == f"{department.code}-2026-000744"
