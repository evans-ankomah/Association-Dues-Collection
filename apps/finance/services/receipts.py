"""Receipt numbering and issue. Numbers look like CSE-2026-000743 and never repeat."""

import re

from django.db import transaction
from django.utils import timezone

from ..models import Receipt, ReceiptCounter
from .errors import FinanceError


def _initial_counter(department, year):
    """Highest existing sequence for this department and year (e.g. after importing old receipts)."""
    prefix = f"{department.code}-{year}-"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    numbers = Receipt.objects.filter(receipt_number__startswith=prefix).values_list(
        "receipt_number", flat=True
    )
    return max((int(m.group(1)) for n in numbers if (m := pattern.match(n))), default=0)


def next_receipt_number(department, year):
    """Reserve the next number. Must run inside a transaction: the counter row stays locked until commit."""
    counter = ReceiptCounter.objects.select_for_update().filter(department=department, year=year).first()
    if counter is None:
        ReceiptCounter.objects.get_or_create(
            department=department, year=year, defaults={"last_number": _initial_counter(department, year)}
        )
        counter = ReceiptCounter.objects.select_for_update().get(department=department, year=year)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{department.code}-{year}-{counter.last_number:06d}"


@transaction.atomic
def issue_receipt(payment, *, issued_by=None):
    if not payment.is_confirmed:
        raise FinanceError("Receipts are only issued for confirmed payments.")
    existing = Receipt.objects.filter(payment=payment).first()
    if existing is not None:
        return existing
    now = timezone.now()
    local_year = timezone.localtime(now).year
    return Receipt.objects.create(
        payment=payment,
        receipt_number=next_receipt_number(payment.department, local_year),
        issued_at=now,
        issued_by=issued_by,
    )
