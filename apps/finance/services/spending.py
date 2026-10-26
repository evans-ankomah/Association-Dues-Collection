"""Budgets, expense requests with a two-step approval, and expenditure records.

- Budgets: Treasurer drafts (finance.budget.create) -> HoD/adviser approves (finance.budget.approve).
- Expense requests: raised by finance.expense.create, then approved in order by the
  President (step 1) and the HoD/adviser (step 2). Requesters never approve their own request,
  and nobody approves two steps of the same request.
- Expenses: approval is not spending. An expense becomes cash outflow only when marked paid.
"""

import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.access.models import RoleAssignment
from apps.access.services import role_codes
from apps.audit.services import record, snapshot

from ..models import Budget, Expense, ExpenseApproval, ExpenseRequest
from .errors import FinanceError, require_perm

ZERO = Decimal("0")

# (step number, role that decides it, label)
APPROVAL_STEPS = [
    (1, "department_president", "President"),
    (2, "hod_faculty_adviser", "HoD / adviser"),
]


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


# ----- budgets ------------------------------------------------------------------------


def budget_figures(budget):
    """Allocated, committed (approved requests not yet spent), spent (paid) and remaining."""
    requests = budget.expense_requests.all()
    spent = _sum(
        Expense.objects.filter(expense_request__in=requests, expense_status=Expense.Status.PAID), "amount"
    )
    open_requests = requests.filter(
        request_status__in=[ExpenseRequest.Status.APPROVED, ExpenseRequest.Status.PENDING_APPROVAL]
    )
    committed = ZERO
    for req in open_requests:
        paid = _sum(req.expenses.filter(expense_status=Expense.Status.PAID), "amount")
        committed += max(req.requested_amount - paid, ZERO)
    remaining = budget.allocated_amount - spent - committed
    utilisation = spent / budget.allocated_amount * 100 if budget.allocated_amount else None
    return {
        "allocated": budget.allocated_amount,
        "spent": spent,
        "committed": committed,
        "remaining": remaining,
        "utilisation": utilisation,
    }


@transaction.atomic
def submit_budget(budget, *, actor):
    require_perm(actor, "finance.budget.create", budget.department)
    budget = Budget.objects.select_for_update().get(pk=budget.pk)
    if budget.budget_status != Budget.Status.DRAFT:
        raise FinanceError("Only draft budgets can be submitted.")
    budget.budget_status = Budget.Status.PENDING_APPROVAL
    budget.save(update_fields=["budget_status"])
    record("budget.submitted", budget, actor=actor, department=budget.department, after=snapshot(budget))
    return budget


@transaction.atomic
def decide_budget(budget, *, actor, approve, note=""):
    require_perm(actor, "finance.budget.approve", budget.department)
    budget = Budget.objects.select_for_update().get(pk=budget.pk)
    if budget.budget_status != Budget.Status.PENDING_APPROVAL:
        raise FinanceError("This budget isn't waiting for approval.")
    if budget.proposed_by_id == actor.pk:
        raise FinanceError("You can't approve a budget you proposed.")
    before = snapshot(budget)
    if approve:
        budget.budget_status = Budget.Status.APPROVED
        budget.approved_by = actor
        budget.approved_at = timezone.now()
    else:
        budget.budget_status = Budget.Status.DRAFT
    budget.save()
    record(
        "budget.approved" if approve else "budget.returned",
        budget,
        actor=actor,
        department=budget.department,
        before=before,
        after={**snapshot(budget), "note": note},
    )
    return budget


@transaction.atomic
def close_budget(budget, *, actor):
    require_perm(actor, "finance.budget.create", budget.department)
    budget = Budget.objects.select_for_update().get(pk=budget.pk)
    if budget.budget_status != Budget.Status.APPROVED:
        raise FinanceError("Only approved budgets can be closed.")
    budget.budget_status = Budget.Status.CLOSED
    budget.save(update_fields=["budget_status"])
    record("budget.closed", budget, actor=actor, department=budget.department)
    return budget


# ----- expense requests ---------------------------------------------------------------


def _step_holder(department, role_code):
    assignment = (
        RoleAssignment.objects.current()
        .filter(department=department, role__role_code=role_code)
        .order_by("starts_at")
        .first()
    )
    return assignment.user if assignment else None


@transaction.atomic
def submit_request(expense_request, *, actor):
    department = expense_request.department
    require_perm(actor, "finance.expense.create", department)
    req = ExpenseRequest.objects.select_for_update().get(pk=expense_request.pk)
    if req.requested_by_id != actor.pk:
        raise FinanceError("Only the person who raised the request can submit it.")
    if req.request_status != ExpenseRequest.Status.DRAFT:
        raise FinanceError("This request has already been submitted.")
    if req.budget_id:
        budget = req.budget
        if budget.budget_status != Budget.Status.APPROVED:
            raise FinanceError("The chosen budget isn't approved.")
        if req.requested_amount > budget_figures(budget)["remaining"]:
            raise FinanceError("This is more than is left in the budget.")
    now = timezone.now()
    for step, role_code, label in APPROVAL_STEPS:
        holder = _step_holder(department, role_code)
        if holder is None:
            raise FinanceError(f"No one currently holds the {label} role, so the request can't be routed.")
        ExpenseApproval.objects.create(
            expense_request=req,
            step_number=step,
            approver_user=holder,
            due_at=now + datetime.timedelta(days=3),
        )
    req.request_status = ExpenseRequest.Status.PENDING_APPROVAL
    req.submitted_at = now
    req.save(update_fields=["request_status", "submitted_at"])
    record("expense_request.submitted", req, actor=actor, department=department, after=snapshot(req))
    return req


def current_step(expense_request):
    return (
        expense_request.approvals.filter(decision=ExpenseApproval.Decision.PENDING)
        .order_by("step_number")
        .first()
    )


def can_decide(user, expense_request):
    step = current_step(expense_request)
    if step is None or expense_request.request_status != ExpenseRequest.Status.PENDING_APPROVAL:
        return False
    role = dict((s, r) for s, r, _ in APPROVAL_STEPS)[step.step_number]
    if expense_request.requested_by_id == user.pk:
        return False
    if expense_request.approvals.filter(
        decision=ExpenseApproval.Decision.APPROVED, approver_user=user
    ).exists():
        return False
    return role in role_codes(user, expense_request.department)


@transaction.atomic
def decide_request(expense_request, *, actor, approve, comments=""):
    department = expense_request.department
    require_perm(actor, "finance.expense.approve", department)
    req = ExpenseRequest.objects.select_for_update().get(pk=expense_request.pk)
    if req.request_status != ExpenseRequest.Status.PENDING_APPROVAL:
        raise FinanceError("This request isn't waiting for a decision.")
    if req.requested_by_id == actor.pk:
        raise FinanceError("You can't approve a request you raised.")
    step = current_step(req)
    role = dict((s, r) for s, r, _ in APPROVAL_STEPS)[step.step_number]
    if role not in role_codes(actor, department):
        label = dict((s, lbl) for s, _, lbl in APPROVAL_STEPS)[step.step_number]
        raise FinanceError(f"Step {step.step_number} is for the {label}.")
    if req.approvals.filter(decision=ExpenseApproval.Decision.APPROVED, approver_user=actor).exists():
        raise FinanceError("You've already approved an earlier step of this request.")

    now = timezone.now()
    step.decision = ExpenseApproval.Decision.APPROVED if approve else ExpenseApproval.Decision.REJECTED
    step.approver_user = actor
    step.comments = comments or None
    step.acted_at = now
    step.save()
    if not approve:
        req.request_status = ExpenseRequest.Status.REJECTED
        req.decided_at = now
        req.decision_note = comments or "Rejected."
    elif current_step(req) is None:
        req.request_status = ExpenseRequest.Status.APPROVED
        req.decided_at = now
        req.decision_note = comments or "Approved."
    req.save()
    record(
        f"expense_request.step{step.step_number}_{'approved' if approve else 'rejected'}",
        req,
        actor=actor,
        department=department,
        after={"status": req.request_status, "comments": comments},
    )
    return req


@transaction.atomic
def withdraw_request(expense_request, *, actor):
    req = ExpenseRequest.objects.select_for_update().get(pk=expense_request.pk)
    if req.requested_by_id != actor.pk:
        raise FinanceError("Only the person who raised the request can withdraw it.")
    if req.request_status not in (ExpenseRequest.Status.DRAFT, ExpenseRequest.Status.PENDING_APPROVAL):
        raise FinanceError("This request can no longer be withdrawn.")
    req.request_status = ExpenseRequest.Status.WITHDRAWN
    req.save(update_fields=["request_status"])
    record("expense_request.withdrawn", req, actor=actor, department=req.department)
    return req


# ----- expenses -----------------------------------------------------------------------


@transaction.atomic
def record_expense(department, *, actor, expense_request=None, **fields):
    require_perm(actor, "finance.expense.create", department)
    if expense_request is not None:
        req = ExpenseRequest.objects.select_for_update().get(pk=expense_request.pk)
        if req.department_id != department.pk:
            raise FinanceError("That request belongs to another department.")
        if req.request_status != ExpenseRequest.Status.APPROVED:
            raise FinanceError("Expenses can only be recorded against approved requests.")
        already = _sum(req.expenses.exclude(expense_status=Expense.Status.VOIDED), "amount")
        if already + Decimal(fields["amount"]) > req.requested_amount:
            raise FinanceError("This would spend more than the approved amount.")
        fields.setdefault("category", req.budget.category if req.budget_id else "Other")
    expense = Expense.objects.create(
        department=department,
        expense_request=expense_request,
        currency=department.default_currency,
        recorded_by=actor,
        expense_status=Expense.Status.PENDING_PAYMENT,
        **fields,
    )
    record("expense.recorded", expense, actor=actor, department=department, after=snapshot(expense))
    return expense


@transaction.atomic
def mark_paid(expense, *, actor, paid_on, payment_reference="", financial_account=None):
    require_perm(actor, "finance.expense.create", expense.department)
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.expense_status not in (Expense.Status.RECORDED, Expense.Status.PENDING_PAYMENT):
        raise FinanceError("Only unpaid expenses can be marked paid.")
    if paid_on is None:
        raise FinanceError("Enter the date it was paid.")
    before = snapshot(expense)
    expense.expense_status = Expense.Status.PAID
    expense.paid_on = paid_on
    expense.payment_reference = (payment_reference or "").strip() or None
    expense.financial_account = financial_account
    expense.save()
    record(
        "expense.paid",
        expense,
        actor=actor,
        department=expense.department,
        before=before,
        after=snapshot(expense),
    )
    if expense.expense_request_id:
        req = ExpenseRequest.objects.select_for_update().get(pk=expense.expense_request_id)
        paid = _sum(req.expenses.filter(expense_status=Expense.Status.PAID), "amount")
        if paid >= req.requested_amount and req.request_status == ExpenseRequest.Status.APPROVED:
            req.request_status = ExpenseRequest.Status.FULFILLED
            req.save(update_fields=["request_status"])
    return expense


@transaction.atomic
def verify_expense(expense, *, actor):
    """A second finance officer confirms the expense against the receipt or invoice."""
    from apps.access.services import has_any_perm

    if not has_any_perm(actor, ("finance.payment.record", "finance.payment.verify"), expense.department):
        require_perm(actor, "finance.payment.verify", expense.department)
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.recorded_by_id == actor.pk:
        raise FinanceError("Someone other than the recorder must verify an expense.")
    if expense.expense_status != Expense.Status.PAID:
        raise FinanceError("Verify an expense once it has been paid.")
    expense.verified_by = actor
    expense.save(update_fields=["verified_by"])
    record("expense.verified", expense, actor=actor, department=expense.department)
    return expense


@transaction.atomic
def void_expense(expense, *, actor, reason):
    require_perm(actor, "finance.expense.create", expense.department)
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.expense_status == Expense.Status.VOIDED:
        raise FinanceError("Already voided.")
    if not (reason or "").strip():
        raise FinanceError("Give a reason for voiding.")
    before = snapshot(expense)
    expense.expense_status = Expense.Status.VOIDED
    expense.save(update_fields=["expense_status"])
    record(
        "expense.voided",
        expense,
        actor=actor,
        department=expense.department,
        before=before,
        after={"reason": reason.strip()},
    )
    return expense


def paid_expenses(department, start=None, end=None):
    qs = Expense.objects.filter(department=department, expense_status=Expense.Status.PAID)
    if start:
        qs = qs.filter(paid_on__gte=start)
    if end:
        qs = qs.filter(paid_on__lte=end)
    return qs


def pending_for(user, department):
    """Expense requests waiting on this user's decision."""
    pending = ExpenseRequest.objects.filter(
        department=department, request_status=ExpenseRequest.Status.PENDING_APPROVAL
    ).filter(~Q(requested_by=user))
    return [r for r in pending if can_decide(user, r)]
