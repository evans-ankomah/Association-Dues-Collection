import datetime
from decimal import Decimal

import factory
from django.utils import timezone

from apps.common.tests.factories import UserFactory
from apps.finance.models import (
    DuesAssessment,
    DuesType,
    Payment,
    PaymentAdjustment,
    PaymentAllocation,
    PaymentAllocationAdjustment,
)


class DuesTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DuesType

    name = factory.Sequence(lambda n: f"Dues {n}")
    default_amount = Decimal("150.00")
    due_date = datetime.date(2026, 10, 30)
    status = DuesType.Status.ACTIVE
    created_by = factory.SubFactory(UserFactory)


class AssessmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DuesAssessment

    amount_assessed = Decimal("150.00")
    due_date = datetime.date(2026, 10, 30)
    assessed_by = factory.SubFactory(UserFactory)


def pay(assessment, amount, *, status=Payment.Status.CONFIRMED, method=Payment.Method.CASH):
    """Create a payment fully allocated to `assessment`."""
    amount = Decimal(amount)
    confirmed = status in ("confirmed", "partially_refunded", "refunded")
    payment = Payment.objects.create(
        department=assessment.dues_type.department,
        payer_membership=assessment.department_membership,
        amount=amount,
        payment_method=method,
        payment_status=status,
        confirmed_at=timezone.now() if confirmed else None,
    )
    allocation = PaymentAllocation.objects.create(
        payment=payment, dues_assessment=assessment, amount_allocated=amount
    )
    return payment, allocation


def refund(allocation, amount, *, processed=True, requested_by=None):
    amount = Decimal(amount)
    adjustment = PaymentAdjustment.objects.create(
        payment=allocation.payment,
        adjustment_type=PaymentAdjustment.Type.REFUND,
        amount=amount,
        reason="Duplicate payment",
        adjustment_status=PaymentAdjustment.Status.PROCESSED
        if processed
        else PaymentAdjustment.Status.REQUESTED,
        requested_by=requested_by or UserFactory(),
    )
    PaymentAllocationAdjustment.objects.create(
        payment_adjustment=adjustment, payment_allocation=allocation, amount_reversed=amount
    )
    return adjustment
