import datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection

from apps.finance.models import DuesAssessment, DuesBalance, Payment
from apps.finance.services.balances import DerivedStatus, totals, with_balances

from .factories import pay, refund

pytestmark = pytest.mark.django_db


def balance_of(assessment, today=datetime.date(2026, 10, 1)):
    return with_balances(DuesAssessment.objects.filter(pk=assessment.pk), today=today).get()


def test_unpaid_assessment_is_outstanding_then_overdue(assessment):
    row = balance_of(assessment)
    assert row.balance == Decimal("150.00")
    assert row.derived_status == DerivedStatus.OUTSTANDING
    assert balance_of(assessment, today=datetime.date(2026, 11, 1)).derived_status == DerivedStatus.OVERDUE


def test_partial_then_full_payment(assessment):
    pay(assessment, "50.00")
    row = balance_of(assessment)
    assert (row.amount_paid, row.balance, row.derived_status) == (Decimal("50"), Decimal("100"), "partial")
    pay(assessment, "100.00", method=Payment.Method.MOBILE_MONEY)
    row = balance_of(assessment)
    assert (row.balance, row.derived_status) == (Decimal("0"), DerivedStatus.PAID)


@pytest.mark.parametrize("status", ["pending", "failed", "cancelled"])
def test_unconfirmed_payments_do_not_reduce_balance(assessment, status):
    pay(assessment, "150.00", status=status)
    assert balance_of(assessment).balance == Decimal("150.00")


def test_processed_refund_restores_balance_but_requested_refund_does_not(assessment):
    _, allocation = pay(assessment, "150.00", status=Payment.Status.REFUNDED)
    refund(allocation, "150.00", processed=False)
    assert balance_of(assessment).balance == Decimal("0.00")
    refund_two = pay(assessment, "150.00")[1]
    refund(refund_two, "150.00", processed=True)
    assert balance_of(assessment).balance == Decimal("0.00")  # 150 + 150 - 150 reversed


def test_waiver_reduces_balance_and_full_waiver_shows_waived(assessment):
    assessment.amount_waived = Decimal("150.00")
    assessment.waiver_reason = "Medical leave"
    assessment.assessment_state = DuesAssessment.State.WAIVED
    assessment.save()
    row = balance_of(assessment)
    assert row.balance == 0
    assert row.derived_status == DerivedStatus.WAIVED


def test_cancelled_assessment_owes_nothing_and_is_excluded_from_totals(assessment):
    assessment.assessment_state = DuesAssessment.State.CANCELLED
    assessment.save()
    assert balance_of(assessment).balance == 0
    assert totals(DuesAssessment.objects.all()).count == 0


def test_totals_and_collection_rate(assessment, dues_type, make_membership, finsec):
    other = DuesAssessment.objects.create(
        dues_type=dues_type,
        department_membership=make_membership(),
        amount_assessed=Decimal("150.00"),
        assessed_by=finsec,
    )
    pay(assessment, "150.00")
    pay(other, "30.00")
    result = totals(DuesAssessment.objects.all())
    assert result.assessed == Decimal("300.00")
    assert result.paid == Decimal("180.00")
    assert result.outstanding == Decimal("120.00")
    assert result.collection_rate == Decimal("60")


def test_sql_view_matches_orm(assessment):
    _, allocation = pay(assessment, "100.00")
    refund(allocation, "40.00")
    view_row = DuesBalance.objects.get(assessment=assessment)
    assert view_row.balance == balance_of(assessment).balance == Decimal("90.00")


def test_waiver_cannot_exceed_assessed_amount(assessment):
    assessment.amount_waived = Decimal("200.00")
    assessment.waiver_reason = "Too much"
    with pytest.raises(IntegrityError):
        assessment.save()


def test_waiver_needs_reason(assessment):
    assessment.amount_waived = Decimal("10.00")
    with pytest.raises(IntegrityError):
        assessment.save()


def test_confirmed_payment_needs_confirmed_at(assessment):
    with pytest.raises(IntegrityError):
        Payment.objects.create(
            department=assessment.dues_type.department,
            amount=Decimal("10"),
            payment_method="cash",
            payment_status="confirmed",
        )


def test_view_exists():
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM v_dues_balances")
        assert cursor.fetchone()[0] == 0
