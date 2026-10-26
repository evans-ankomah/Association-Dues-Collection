import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError

from apps.common.tests.factories import grant
from apps.finance.models import Budget, Expense, ExpenseRequest
from apps.finance.services import spending as svc
from apps.finance.services.errors import FinanceError

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(make_user):
    return make_user("treasurer")


@pytest.fixture
def president(make_user):
    return make_user("department_president")


@pytest.fixture
def budget(department, session, treasurer, hod):
    b = Budget.objects.create(
        department=department,
        academic_session=session,
        name="Orientation",
        category="Orientation",
        allocated_amount=Decimal("1000"),
        starts_on=datetime.date(2026, 9, 1),
        ends_on=datetime.date(2026, 10, 31),
        proposed_by=treasurer,
    )
    svc.submit_budget(b, actor=treasurer)
    svc.decide_budget(b, actor=hod, approve=True)
    b.refresh_from_db()
    return b


def new_request(department, treasurer, budget=None, amount="400"):
    return ExpenseRequest.objects.create(
        department=department,
        budget=budget,
        requested_by=treasurer,
        title="Handbooks",
        purpose="Printing",
        requested_amount=Decimal(amount),
    )


def test_budget_needs_a_different_approver(department, session, treasurer, make_user):
    b = Budget.objects.create(
        department=department,
        academic_session=session,
        name="x",
        category="x",
        allocated_amount=1,
        starts_on=datetime.date(2026, 1, 1),
        ends_on=datetime.date(2026, 2, 1),
        proposed_by=treasurer,
    )
    svc.submit_budget(b, actor=treasurer)
    with pytest.raises(PermissionDenied):
        svc.decide_budget(b, actor=treasurer, approve=True)
    both = make_user("treasurer")
    grant(both, "hod_faculty_adviser", department)
    b2 = Budget.objects.create(
        department=department,
        academic_session=session,
        name="y",
        category="y",
        allocated_amount=1,
        starts_on=datetime.date(2026, 1, 1),
        ends_on=datetime.date(2026, 2, 1),
        proposed_by=both,
    )
    svc.submit_budget(b2, actor=both)
    with pytest.raises(FinanceError, match="you proposed"):
        svc.decide_budget(b2, actor=both, approve=True)


def test_two_step_approval_then_spend(department, budget, treasurer, president, hod, finsec):
    req = new_request(department, treasurer, budget)
    svc.submit_request(req, actor=treasurer)
    assert svc.budget_figures(budget)["committed"] == Decimal("400")

    with pytest.raises(FinanceError, match="Step 1 is for the President"):
        svc.decide_request(req, actor=hod, approve=True)
    svc.decide_request(req, actor=president, approve=True, comments="Within budget.")
    req.refresh_from_db()
    assert req.request_status == ExpenseRequest.Status.PENDING_APPROVAL
    svc.decide_request(req, actor=hod, approve=True)
    req.refresh_from_db()
    assert req.request_status == ExpenseRequest.Status.APPROVED

    expense = svc.record_expense(
        department,
        actor=treasurer,
        expense_request=req,
        description="Handbooks",
        amount=Decimal("400"),
        vendor_name="Ebenezer Prints",
    )
    assert svc.budget_figures(budget)["spent"] == 0  # approved is not spent
    svc.mark_paid(expense, actor=treasurer, paid_on=datetime.date(2026, 9, 9), payment_reference="150902")
    req.refresh_from_db()
    assert req.request_status == ExpenseRequest.Status.FULFILLED
    figures = svc.budget_figures(budget)
    assert (figures["spent"], figures["committed"], figures["remaining"]) == (
        Decimal("400"),
        0,
        Decimal("600"),
    )

    with pytest.raises(FinanceError, match="other than the recorder"):
        svc.verify_expense(expense, actor=treasurer)
    svc.verify_expense(expense, actor=finsec)


def test_rejection_at_step_two(department, budget, treasurer, president, hod):
    req = new_request(department, treasurer, budget)
    svc.submit_request(req, actor=treasurer)
    svc.decide_request(req, actor=president, approve=True)
    svc.decide_request(req, actor=hod, approve=False, comments="Too expensive")
    req.refresh_from_db()
    assert req.request_status == ExpenseRequest.Status.REJECTED
    with pytest.raises(FinanceError, match="approved requests"):
        svc.record_expense(
            department, actor=treasurer, expense_request=req, description="x", amount=Decimal("1")
        )


def test_nobody_approves_two_steps(department, budget, treasurer, president, make_user):
    grant(president, "hod_faculty_adviser", department)
    req = new_request(department, treasurer, budget)
    svc.submit_request(req, actor=treasurer)
    svc.decide_request(req, actor=president, approve=True)
    with pytest.raises(FinanceError, match="already approved an earlier step"):
        svc.decide_request(req, actor=president, approve=True)


def test_requester_cannot_approve(department, budget, make_user):
    raiser = make_user("treasurer")
    grant(raiser, "department_president", department)
    make_user("hod_faculty_adviser")
    req = new_request(department, raiser, budget)
    svc.submit_request(req, actor=raiser)
    with pytest.raises(FinanceError, match="you raised"):
        svc.decide_request(req, actor=raiser, approve=True)


def test_request_over_budget_is_blocked(department, budget, treasurer, president, hod):
    with pytest.raises(FinanceError, match="more than is left"):
        svc.submit_request(new_request(department, treasurer, budget, amount="1500"), actor=treasurer)


def test_spending_cannot_exceed_approval(department, budget, treasurer, president, hod):
    req = new_request(department, treasurer, budget)
    svc.submit_request(req, actor=treasurer)
    svc.decide_request(req, actor=president, approve=True)
    svc.decide_request(req, actor=hod, approve=True)
    with pytest.raises(FinanceError, match="more than the approved"):
        svc.record_expense(
            department, actor=treasurer, expense_request=req, description="x", amount=Decimal("401")
        )


def test_routing_fails_without_role_holders(department, treasurer):
    with pytest.raises(FinanceError, match="President"):
        svc.submit_request(new_request(department, treasurer), actor=treasurer)


def test_paid_expense_requires_date(department, treasurer):
    expense = Expense.objects.create(
        department=department, description="x", category="x", amount=1, recorded_by=treasurer
    )
    expense.expense_status = Expense.Status.PAID
    with pytest.raises(IntegrityError):
        expense.save()


def test_views(department, budget, treasurer, president, hod, login):
    client = login(treasurer)
    assert client.get("/finance/budgets/").status_code == 200
    client.post(
        "/finance/expense-requests/new/",
        {
            "title": "Banners",
            "budget": budget.pk,
            "requested_amount": "100",
            "purpose": "CSE Week",
            "submit": "1",
        },
    )
    req = ExpenseRequest.objects.get(title="Banners")
    assert req.request_status == ExpenseRequest.Status.PENDING_APPROVAL
    login(president).post(f"/finance/expense-requests/{req.pk}/action/", {"action": "approve"})
    login(hod).post(f"/finance/expense-requests/{req.pk}/action/", {"action": "approve"})
    req.refresh_from_db()
    assert req.request_status == ExpenseRequest.Status.APPROVED
    report = login(hod).get("/reports/finance/")
    assert report.context["spent"] == 0
