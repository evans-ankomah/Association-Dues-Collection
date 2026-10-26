import datetime
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.finance.models import FinancialAccount, Payment
from apps.finance.services import payments as pay_service
from apps.finance.services import reconciliation as svc

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(make_user):
    return make_user("treasurer")


@pytest.fixture
def momo_account(department):
    return FinancialAccount.objects.create(
        department=department, name="MoMo wallet", account_type="mobile_money", provider_name="MTN MoMo"
    )


def momo(membership, actor, ref, amount="150.00"):
    return pay_service.record_offline_payment(
        membership, actor=actor, method="mobile_money", amount=amount, reference=ref, provider_name="MTN MoMo"
    )


def test_single_wallet_takes_every_network(
    department, membership, assessment, finsec, treasurer, momo_account
):
    pay_service.verify_payment(momo(membership, finsec, "A1"), actor=treasurer)
    telecel = pay_service.record_offline_payment(
        membership,
        actor=finsec,
        method="mobile_money",
        amount="10",
        reference="T1",
        provider_name="Telecel Cash",
    )
    pay_service.verify_payment(telecel, actor=treasurer)
    rows, unmatched = svc.account_summaries(department)
    assert rows[0]["received"] == Decimal("160.00")
    assert unmatched == []


def test_with_several_wallets_payments_match_by_provider(
    department, membership, assessment, finsec, treasurer, momo_account
):
    FinancialAccount.objects.create(
        department=department,
        name="Telecel wallet",
        account_type="mobile_money",
        provider_name="Telecel Cash",
    )
    at = pay_service.record_offline_payment(
        membership, actor=finsec, method="mobile_money", amount="10", reference="X1", provider_name="AT Money"
    )
    pay_service.verify_payment(at, actor=treasurer)
    _, unmatched = svc.account_summaries(department)
    assert unmatched[0]["provider_name"] == "AT Money"


def test_exceptions(department, membership, assessment, finsec, treasurer, member):
    stale = momo(membership, finsec, "OLD")
    Payment.objects.filter(pk=stale.pk).update(initiated_at=timezone.now() - datetime.timedelta(days=5))
    momo(membership, finsec, "DUP")
    over = pay_service.record_offline_payment(membership, actor=finsec, method="cash", amount="500")
    pay_service.verify_payment(over, actor=treasurer)

    issues = svc.exceptions(department)
    assert list(issues["stale_pending"]) == [stale]
    assert over in issues["unallocated"]
    assert not issues["duplicates"].exists()


def test_duplicate_references_flagged(department, membership, finsec):
    momo(membership, finsec, "SAME")
    momo(membership, finsec, "SAME")
    assert svc.exceptions(department)["duplicates"].count() == 2


def test_statement_matching(membership, assessment, finsec, treasurer, momo_account):
    good = momo(membership, finsec, "111")
    pay_service.verify_payment(good, actor=treasurer)
    wrong = momo(membership, finsec, "222", amount="50.00")
    missing = momo(membership, finsec, "333", amount="20.00")
    pay_service.verify_payment(missing, actor=treasurer)

    csv_text = (
        'Transaction ID,Amount,Date\n111,150.00,2026-10-01\n222,"5,000.00",2026-10-02\n999,30,2026-10-03\n'
    )
    lines, errors = svc.parse_statement(io.BytesIO(csv_text.encode()))
    assert not errors
    result = svc.match_statement(momo_account, lines)
    assert [p for _, p in result.matched] == [good]
    assert [p for _, p in result.amount_mismatch] == [wrong]
    assert [line.reference for line in result.not_in_system] == ["999"]
    assert result.not_on_statement == [missing]


def test_statement_needs_reference_and_amount_columns():
    with pytest.raises(ValueError):
        svc.parse_statement(io.BytesIO(b"foo,bar\n1,2\n"))


def test_page_and_upload_permissions(member, treasurer, finsec, login, momo_account, membership):
    assert login(member).get("/finance/reconciliation/").status_code == 403
    client = login(finsec)  # financial secretary holds reconciliation.view
    assert client.get("/finance/reconciliation/").status_code == 200
    assert client.get("/finance/accounts/new/").status_code == 403  # but not account management

    momo(membership, finsec, "777")
    upload = SimpleUploadedFile("s.csv", b"reference,amount\n777,150.00\n", content_type="text/csv")
    response = login(treasurer).post(
        "/finance/reconciliation/", {"account": str(momo_account.pk), "statement": upload}
    )
    assert len(response.context["result"].matched) == 1


def test_account_number_must_be_masked(treasurer, login):
    response = login(treasurer).post(
        "/finance/accounts/new/",
        {
            "name": "Bank",
            "account_type": "bank",
            "provider_name": "CalBank",
            "account_reference_masked": "1234567352",
            "is_active": "on",
        },
    )
    assert response.status_code == 200
    assert not FinancialAccount.objects.exists()
