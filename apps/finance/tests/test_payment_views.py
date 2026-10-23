import pytest

from apps.finance.models import Payment, Receipt

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(make_user):
    return make_user("treasurer")


def test_full_offline_flow_through_views(membership, assessment, finsec, treasurer, member, login):
    client = login(finsec)
    search = client.get("/finance/payments/member-search/", {"q": member.profile.family_name})
    assert str(membership.pk) in search.content.decode()
    response = client.post(
        "/finance/payments/record/", {"membership": str(membership.pk), "method": "cash", "amount": "150.00"}
    )
    payment = Payment.objects.get()
    assert response["Location"] == f"/finance/payments/{payment.pk}/"

    client = login(treasurer)
    detail = client.get(f"/finance/payments/{payment.pk}/")
    assert detail.context["can_verify"] is True
    client.post(f"/finance/payments/{payment.pk}/verify/", {f"alloc_{assessment.pk}": "150.00"})
    payment.refresh_from_db()
    assert payment.payment_status == Payment.Status.CONFIRMED

    receipt = Receipt.objects.get(payment=payment)
    client = login(member)
    assert client.get(f"/finance/receipts/{receipt.pk}/").status_code == 200
    pdf = client.get(f"/finance/receipts/{receipt.pk}/pdf/")
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_member_reports_payment_and_cannot_see_others(membership, member, login, make_membership, finsec):
    client = login(member)
    client.post(
        "/finance/my-payments/",
        {"method": "mobile_money", "network": "MTN MoMo", "amount": "150", "reference": "123456789"},
    )
    own = Payment.objects.get()
    assert own.payment_status == Payment.Status.PENDING

    from apps.finance.services.payments import record_offline_payment

    other = record_offline_payment(make_membership(), actor=finsec, method="cash", amount="5")
    assert client.get(f"/finance/payments/{own.pk}/").status_code == 200
    assert client.get(f"/finance/payments/{other.pk}/").status_code == 403
    assert client.get("/finance/payments/").status_code == 403


def test_momo_claim_requires_reference_and_network(member, login, membership):
    client = login(member)
    response = client.post("/finance/my-payments/", {"method": "mobile_money", "amount": "150"})
    assert response.status_code == 200
    assert not Payment.objects.exists()


def test_treasurer_cannot_record(treasurer, login):
    assert login(treasurer).get("/finance/payments/record/").status_code == 403
