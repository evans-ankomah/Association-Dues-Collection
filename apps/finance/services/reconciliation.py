"""Reconciliation (workbook view v_payment_reconciliation).

Compares what the system recorded with what providers and statements say, and lists the
exceptions a Treasurer must resolve. Nothing here changes money; it only reports.
"""

import csv
import datetime
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import CONFIRMED_PAYMENT_STATES, FinancialAccount, Payment, WebhookEvent

ZERO = Decimal("0")
STALE_AFTER_DAYS = 3


METHOD_FOR_ACCOUNT = {
    FinancialAccount.Type.CASH: Payment.Method.CASH,
    FinancialAccount.Type.ONLINE_CLEARING: Payment.Method.PROVIDER,
    FinancialAccount.Type.MOBILE_MONEY: Payment.Method.MOBILE_MONEY,
    FinancialAccount.Type.BANK: Payment.Method.BANK_TRANSFER,
}


def payments_for_account(account):
    """Payments that should land in `account`.

    Cash goes to the cash box. Otherwise payments match on method and provider name, except that
    when a department has a single active account of a type (e.g. one MoMo merchant wallet that
    receives MTN, Telecel and AT transfers alike), every payment of that method lands there.
    """
    method = METHOD_FOR_ACCOUNT.get(account.account_type)
    if method is None:
        return Payment.objects.none()
    qs = Payment.objects.filter(department=account.department, payment_method=method)
    if method == Payment.Method.CASH:
        return qs
    siblings = FinancialAccount.objects.filter(
        department=account.department, account_type=account.account_type, is_active=True
    )
    if siblings.count() == 1:
        return qs
    return qs.filter(provider_name__iexact=account.provider_name or "")


def account_summaries(department):
    rows = []
    matched_ids = set()
    for account in FinancialAccount.objects.filter(department=department, is_active=True).order_by("name"):
        qs = payments_for_account(account)
        matched_ids.update(qs.values_list("pk", flat=True))
        rows.append(
            {
                "account": account,
                "received": qs.filter(payment_status__in=CONFIRMED_PAYMENT_STATES).aggregate(
                    t=Coalesce(Sum("amount"), ZERO)
                )["t"],
                "pending": qs.filter(payment_status=Payment.Status.PENDING).count(),
            }
        )
    unmatched = (
        Payment.objects.filter(department=department, payment_status__in=CONFIRMED_PAYMENT_STATES)
        .exclude(pk__in=matched_ids)
        .values("payment_method", "provider_name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )
    return rows, list(unmatched)


def exceptions(department, today=None):
    """Items needing attention, each a queryset or list the page can show."""
    now = timezone.now()
    payments = Payment.objects.filter(department=department).select_related("payer_membership__user__profile")
    received = payments.filter(payment_status__in=CONFIRMED_PAYMENT_STATES)

    duplicate_refs = (
        payments.exclude(payment_status__in=[Payment.Status.FAILED, Payment.Status.CANCELLED])
        .exclude(external_reference__isnull=True)
        .values("external_reference")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .values_list("external_reference", flat=True)
    )
    surplus = received.annotate(allocated=Coalesce(Sum("allocations__amount_allocated"), ZERO)).filter(
        allocated__lt=F("amount"), payment_status=Payment.Status.CONFIRMED
    )
    return {
        "missing_reference": received.exclude(payment_method=Payment.Method.CASH).filter(
            provider_reference__isnull=True, external_reference__isnull=True
        ),
        "duplicates": payments.filter(external_reference__in=list(duplicate_refs)).order_by(
            "external_reference"
        ),
        "stale_pending": payments.filter(
            payment_status=Payment.Status.PENDING,
            initiated_at__lt=now - datetime.timedelta(days=STALE_AFTER_DAYS),
        ).exclude(payment_method=Payment.Method.PROVIDER),
        "online_pending": payments.filter(
            payment_status=Payment.Status.PENDING, payment_method=Payment.Method.PROVIDER
        ),
        "mismatches": payments.filter(
            payment_status=Payment.Status.PENDING, notes__icontains="needs reconciliation"
        ),
        "failed_webhooks": WebhookEvent.objects.filter(
            Q(processing_status=WebhookEvent.Status.FAILED)
            | Q(
                processing_status=WebhookEvent.Status.PROCESSING,
                received_at__lt=now - datetime.timedelta(hours=1),
            )
        ).filter(signature_valid=True),
        "unallocated": surplus,
    }


# ----- statement matching -------------------------------------------------------------


@dataclass
class StatementLine:
    reference: str
    amount: Decimal
    date: str = ""


@dataclass
class MatchResult:
    matched: list = field(default_factory=list)  # (line, payment)
    amount_mismatch: list = field(default_factory=list)  # (line, payment)
    not_in_system: list = field(default_factory=list)  # line
    not_on_statement: list = field(default_factory=list)  # payment
    errors: list = field(default_factory=list)


_REF_HEADERS = ("reference", "transaction id", "transaction_id", "ref", "external_reference", "id")
_AMOUNT_HEADERS = ("amount", "credit", "amount (ghs)", "value")
_DATE_HEADERS = ("date", "transaction date", "value date")
MAX_LINES = 5000


def parse_statement(file_obj):
    """Read a CSV statement with reference and amount columns (header names are flexible)."""
    raw = file_obj.read(2_000_000)
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
    ref_col = next((headers[h] for h in _REF_HEADERS if h in headers), None)
    amount_col = next((headers[h] for h in _AMOUNT_HEADERS if h in headers), None)
    date_col = next((headers[h] for h in _DATE_HEADERS if h in headers), None)
    if not ref_col or not amount_col:
        raise ValueError("The file needs a reference column and an amount column.")
    lines, errors = [], []
    for number, row in enumerate(reader, start=2):
        if number > MAX_LINES + 1:
            errors.append(f"Only the first {MAX_LINES} lines were read.")
            break
        reference = (row.get(ref_col) or "").strip()
        amount_text = (row.get(amount_col) or "").replace(",", "").replace("GHS", "").strip()
        if not reference and not amount_text:
            continue
        try:
            amount = Decimal(amount_text).quantize(Decimal("0.01"))
        except InvalidOperation:
            errors.append(f"Line {number}: amount “{amount_text[:20]}” isn't a number.")
            continue
        lines.append(StatementLine(reference, amount, (row.get(date_col) or "").strip() if date_col else ""))
    return lines, errors


def match_statement(account, lines, start=None, end=None):
    candidates = payments_for_account(account).exclude(
        payment_status__in=[Payment.Status.FAILED, Payment.Status.CANCELLED]
    )
    if start:
        candidates = candidates.filter(initiated_at__date__gte=start)
    if end:
        candidates = candidates.filter(initiated_at__date__lte=end)
    by_ref = {}
    for payment in candidates.select_related("payer_membership__user__profile"):
        for ref in (payment.external_reference, payment.provider_reference):
            if ref:
                by_ref[ref.strip().lower()] = payment
    result = MatchResult()
    seen = set()
    for line in lines:
        payment = by_ref.get(line.reference.lower())
        if payment is None:
            result.not_in_system.append(line)
        elif payment.amount != line.amount:
            result.amount_mismatch.append((line, payment))
            seen.add(payment.pk)
        else:
            result.matched.append((line, payment))
            seen.add(payment.pk)
    result.not_on_statement = [
        p
        for p in {p.pk: p for p in by_ref.values()}.values()
        if p.pk not in seen and p.payment_status in CONFIRMED_PAYMENT_STATES
    ]
    return result
