from decimal import Decimal

import pytest

from apps.common.tests.factories import MembershipFactory
from apps.finance.models import DuesAssessment, Payment
from apps.finance.tests.factories import AssessmentFactory, DuesTypeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def ledger(department, session, membership, finsec_user):
    dues = DuesTypeFactory(department=department, academic_session=session, created_by=finsec_user)
    AssessmentFactory(dues_type=dues, department_membership=membership)
    return dues


@pytest.fixture
def finsec_user(make_user):
    return make_user("financial_secretary")


@pytest.fixture
def treasurer(make_user):
    return make_user("treasurer")


def test_requires_login(client):
    assert client.get("/api/v1/me/").status_code == 403


def test_me(member, login, department):
    data = login(member).get("/api/v1/me/").json()
    assert data["email"] == member.email
    assert data["current_department"]["code"] == department.code
    assert "dues.own.view" in data["permissions"]
    assert "finance.payment.verify" not in data["permissions"]


def test_member_sees_only_own_dues_and_payments(member, login, ledger, department, session):
    other = MembershipFactory(department=department, academic_session=session)
    AssessmentFactory(dues_type=ledger, department_membership=other)
    client = login(member)
    dues = client.get("/api/v1/dues/").json()
    assert dues["count"] == 1 and dues["results"][0]["balance"] == "150.00"
    assert client.get("/api/v1/dues/?scope=department").status_code == 403
    assert client.get("/api/v1/members/").status_code == 403
    assert client.get("/api/v1/transactions/summary/").status_code == 403


def test_member_reports_payment_and_finance_verifies(member, login, ledger, treasurer):
    client = login(member)
    response = client.post(
        "/api/v1/payments/",
        {
            "method": "mobile_money",
            "amount": "150.00",
            "reference": "82116518706",
            "provider_name": "MTN MoMo",
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    payment_id = response.json()["id"]
    assert (
        client.post(f"/api/v1/payments/{payment_id}/verify/", {}, content_type="application/json").status_code
        == 403
    )

    verified = login(treasurer).post(
        f"/api/v1/payments/{payment_id}/verify/", {}, content_type="application/json"
    )
    assert verified.status_code == 200, verified.content
    assert verified.json()["payment_status"] == "confirmed"
    assert verified.json()["receipt_number"]

    receipts = login(member).get("/api/v1/receipts/").json()
    assert receipts["results"][0]["applied_to"][0]["amount"] == "150.00"


def test_business_errors_are_400(member, login, ledger):
    client = login(member)
    payload = {"method": "mobile_money", "amount": "10", "reference": "DUP", "provider_name": "MTN MoMo"}
    assert client.post("/api/v1/payments/", payload, content_type="application/json").status_code == 201
    second = client.post("/api/v1/payments/", payload, content_type="application/json")
    assert second.status_code == 400
    assert "already been reported" in second.json()["detail"]


def test_finance_officer_records_and_assesses(finsec_user, login, membership, ledger, department, session):
    client = login(finsec_user)
    recorded = client.post(
        "/api/v1/payments/",
        {"membership": str(membership.pk), "method": "cash", "amount": "20.00"},
        content_type="application/json",
    )
    assert recorded.status_code == 201
    assert Payment.objects.get().recorded_by == finsec_user

    MembershipFactory(department=department, academic_session=session, level_code="Level 300")
    assessed = client.post(
        f"/api/v1/dues-types/{ledger.pk}/assess/", {"levels": ["Level 300"]}, content_type="application/json"
    )
    assert assessed.json() == {"assessed": 1}
    assert DuesAssessment.objects.count() == 2


def test_summary_and_roster_for_finance(treasurer, login, ledger):
    client = login(treasurer)
    summary = client.get("/api/v1/transactions/summary/").json()
    assert summary["assessed"] == "150.00" and summary["outstanding"] == "150.00"
    roster = client.get("/api/v1/members/?owing=1").json()
    assert roster["count"] == 1 and Decimal(roster["results"][0]["outstanding"]) == Decimal("150")


def test_schema_and_docs_available(member, login):
    client = login(member)
    assert client.get("/api/schema/").status_code == 200
    assert client.get("/api/docs/").status_code == 200
