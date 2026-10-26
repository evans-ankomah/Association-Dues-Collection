from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_any_perm, has_perm
from apps.audit.services import record, snapshot

from ..models import Budget, Expense, ExpenseRequest, FinancialAccount
from ..services import spending as svc
from ..services.errors import FinanceError
from .common import paginate

INPUT = {"class": "field-input"}
DATE = forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d")
MONEY = forms.NumberInput(attrs={**INPUT, "step": "0.01", "min": "0.01"})
SPENDING_VIEWERS = (
    "finance.budget.create",
    "finance.budget.approve",
    "finance.expense.create",
    "finance.expense.approve",
    "finance.report.export",
    "finance.reconciliation.view",
)


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["name", "category", "allocated_amount", "starts_on", "ends_on"]
        labels = {"allocated_amount": "Amount (GHS)"}
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "category": forms.TextInput(attrs={**INPUT, "placeholder": "Orientation, CSE Week, Welfare…"}),
            "allocated_amount": MONEY,
            "starts_on": DATE,
            "ends_on": DATE,
        }

    def clean(self):
        data = super().clean()
        if data.get("starts_on") and data.get("ends_on") and data["ends_on"] < data["starts_on"]:
            self.add_error("ends_on", "Must be on or after the start date.")
        return data


class ExpenseRequestForm(forms.ModelForm):
    class Meta:
        model = ExpenseRequest
        fields = ["title", "budget", "requested_amount", "needed_by", "purpose"]
        labels = {"requested_amount": "Amount (GHS)"}
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "budget": forms.Select(attrs=INPUT),
            "requested_amount": MONEY,
            "needed_by": DATE,
            "purpose": forms.Textarea(attrs={**INPUT, "rows": 3}),
        }

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["budget"].queryset = Budget.objects.filter(
            department=department, budget_status=Budget.Status.APPROVED
        )
        self.fields["budget"].required = False


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["description", "vendor_name", "category", "amount", "incurred_on"]
        labels = {"amount": "Amount (GHS)", "vendor_name": "Paid to"}
        widgets = {
            "description": forms.TextInput(attrs=INPUT),
            "vendor_name": forms.TextInput(attrs=INPUT),
            "category": forms.TextInput(attrs=INPUT),
            "amount": MONEY,
            "incurred_on": DATE,
        }


class PaidForm(forms.Form):
    paid_on = forms.DateField(widget=DATE)
    payment_reference = forms.CharField(required=False, max_length=180, widget=forms.TextInput(attrs=INPUT))
    financial_account = forms.ModelChoiceField(
        queryset=FinancialAccount.objects.none(), required=False, widget=forms.Select(attrs=INPUT)
    )

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["financial_account"].queryset = FinancialAccount.objects.filter(
            department=department, is_active=True
        )


# ----- budgets ------------------------------------------------------------------------


@permission_required(*SPENDING_VIEWERS)
def budget_list(request):
    budgets = Budget.objects.filter(department=request.department, academic_session=request.academic_session)
    rows = [{"budget": b, **svc.budget_figures(b)} for b in budgets]
    return render(
        request,
        "finance/budget_list.html",
        {"rows": rows, "can_create": has_perm(request.user, "finance.budget.create", request.department)},
    )


@permission_required("finance.budget.create")
def budget_form(request, pk=None):
    budget = get_object_or_404(Budget, pk=pk, department=request.department) if pk else None
    if budget and budget.budget_status != Budget.Status.DRAFT:
        messages.error(request, "Only draft budgets can be edited.")
        return redirect("finance:budget", pk=pk)
    form = BudgetForm(request.POST or None, instance=budget)
    if request.method == "POST" and form.is_valid():
        before = snapshot(budget) if budget else None
        saved = form.save(commit=False)
        if budget is None:
            saved.department = request.department
            saved.academic_session = request.academic_session
            saved.currency = request.department.default_currency
            saved.proposed_by = request.user
        saved.save()
        record(
            "budget.saved",
            saved,
            actor=request.user,
            department=request.department,
            before=before,
            after=snapshot(saved),
        )
        if "submit" in request.POST:
            try:
                svc.submit_budget(saved, actor=request.user)
                messages.success(request, "Budget sent for approval.")
            except FinanceError as exc:
                messages.error(request, str(exc))
        return redirect("finance:budget", pk=saved.pk)
    return render(request, "finance/budget_form.html", {"form": form, "budget": budget})


@permission_required(*SPENDING_VIEWERS)
def budget_detail(request, pk):
    budget = get_object_or_404(Budget, pk=pk, department=request.department)
    return render(
        request,
        "finance/budget_detail.html",
        {
            "budget": budget,
            "figures": svc.budget_figures(budget),
            "requests": budget.expense_requests.select_related("requested_by__profile"),
            "can_edit": budget.budget_status == Budget.Status.DRAFT
            and has_perm(request.user, "finance.budget.create", request.department),
            "can_decide": budget.budget_status == Budget.Status.PENDING_APPROVAL
            and has_perm(request.user, "finance.budget.approve", request.department)
            and budget.proposed_by_id != request.user.pk,
            "can_close": budget.budget_status == Budget.Status.APPROVED
            and has_perm(request.user, "finance.budget.create", request.department),
        },
    )


@permission_required("finance.budget.create", "finance.budget.approve")
@require_POST
def budget_action(request, pk):
    budget = get_object_or_404(Budget, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "submit":
            svc.submit_budget(budget, actor=request.user)
        elif action in ("approve", "return"):
            svc.decide_budget(
                budget, actor=request.user, approve=action == "approve", note=request.POST.get("note", "")
            )
        elif action == "close":
            svc.close_budget(budget, actor=request.user)
        messages.success(request, "Budget updated.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:budget", pk=pk)


# ----- expense requests ---------------------------------------------------------------


@permission_required(*SPENDING_VIEWERS)
def request_list(request):
    status = request.GET.get("status", "")
    qs = ExpenseRequest.objects.filter(department=request.department).select_related(
        "budget", "requested_by__profile"
    )
    if status:
        qs = qs.filter(request_status=status)
    page, query = paginate(request, qs.order_by("-created_at"), per_page=30)
    return render(
        request,
        "finance/expense_request_list.html",
        {
            "page": page,
            "query": query,
            "status": status,
            "statuses": ExpenseRequest.Status.choices,
            "awaiting_me": svc.pending_for(request.user, request.department)
            if has_perm(request.user, "finance.expense.approve", request.department)
            else [],
            "can_create": has_perm(request.user, "finance.expense.create", request.department),
        },
    )


@permission_required("finance.expense.create")
def request_form(request):
    form = ExpenseRequestForm(request.POST or None, department=request.department)
    if request.method == "POST" and form.is_valid():
        req = form.save(commit=False)
        req.department = request.department
        req.requested_by = request.user
        req.currency = request.department.default_currency
        req.save()
        record(
            "expense_request.created",
            req,
            actor=request.user,
            department=request.department,
            after=snapshot(req),
        )
        if "submit" in request.POST:
            try:
                svc.submit_request(req, actor=request.user)
                messages.success(request, "Sent to the President for approval.")
            except FinanceError as exc:
                messages.error(request, str(exc))
        return redirect("finance:expense_request", pk=req.pk)
    return render(request, "finance/expense_request_form.html", {"form": form})


@permission_required(*SPENDING_VIEWERS)
def request_detail(request, pk):
    req = get_object_or_404(
        ExpenseRequest.objects.select_related("budget", "requested_by__profile"),
        pk=pk,
        department=request.department,
    )
    labels = {s: label for s, _, label in svc.APPROVAL_STEPS}
    approvals = list(req.approvals.select_related("approver_user__profile"))
    for a in approvals:
        a.label = labels.get(a.step_number, f"Step {a.step_number}")
    return render(
        request,
        "finance/expense_request_detail.html",
        {
            "req": req,
            "approvals": approvals,
            "expenses": req.expenses.order_by("-created_at"),
            "can_decide": svc.can_decide(request.user, req)
            and has_perm(request.user, "finance.expense.approve", request.department),
            "is_requester": req.requested_by_id == request.user.pk,
            "can_record": req.request_status == ExpenseRequest.Status.APPROVED
            and has_perm(request.user, "finance.expense.create", request.department),
        },
    )


@permission_required("finance.expense.create", "finance.expense.approve")
@require_POST
def request_action(request, pk):
    req = get_object_or_404(ExpenseRequest, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "submit":
            svc.submit_request(req, actor=request.user)
        elif action in ("approve", "reject"):
            svc.decide_request(
                req,
                actor=request.user,
                approve=action == "approve",
                comments=request.POST.get("comments", ""),
            )
        elif action == "withdraw":
            svc.withdraw_request(req, actor=request.user)
        messages.success(request, "Request updated.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:expense_request", pk=pk)


# ----- expenses -----------------------------------------------------------------------


@permission_required(*SPENDING_VIEWERS)
def expense_list(request):
    status = request.GET.get("status", "")
    qs = Expense.objects.filter(department=request.department).select_related(
        "expense_request", "recorded_by__profile", "verified_by__profile"
    )
    if status:
        qs = qs.filter(expense_status=status)
    page, query = paginate(request, qs.order_by("-created_at"), per_page=30)
    return render(
        request,
        "finance/expense_list.html",
        {
            "page": page,
            "query": query,
            "status": status,
            "statuses": Expense.Status.choices,
            "can_create": has_perm(request.user, "finance.expense.create", request.department),
        },
    )


@permission_required("finance.expense.create")
def expense_form(request):
    req = None
    if request.GET.get("request") or request.POST.get("request"):
        req = get_object_or_404(
            ExpenseRequest,
            pk=request.GET.get("request") or request.POST.get("request"),
            department=request.department,
        )
    initial = (
        {
            "description": req.title,
            "amount": req.requested_amount,
            "category": req.budget.category if req and req.budget_id else "",
        }
        if req
        else {}
    )
    form = ExpenseForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            expense = svc.record_expense(
                request.department, actor=request.user, expense_request=req, **form.cleaned_data
            )
        except FinanceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Expense recorded. Mark it paid once the money has gone out.")
            return redirect("finance:expense", pk=expense.pk)
    return render(request, "finance/expense_form.html", {"form": form, "req": req})


@permission_required(*SPENDING_VIEWERS)
def expense_detail(request, pk):
    expense = get_object_or_404(
        Expense.objects.select_related("expense_request", "financial_account", "recorded_by__profile"),
        pk=pk,
        department=request.department,
    )
    can_create = has_perm(request.user, "finance.expense.create", request.department)
    return render(
        request,
        "finance/expense_detail.html",
        {
            "expense": expense,
            "paid_form": PaidForm(department=request.department),
            "can_pay": can_create
            and expense.expense_status in (Expense.Status.RECORDED, Expense.Status.PENDING_PAYMENT),
            "can_void": can_create and expense.expense_status != Expense.Status.VOIDED,
            "can_verify": expense.expense_status == Expense.Status.PAID
            and expense.verified_by_id is None
            and expense.recorded_by_id != request.user.pk
            and has_any_perm(
                request.user, ("finance.payment.record", "finance.payment.verify"), request.department
            ),
        },
    )


@permission_required("finance.expense.create", "finance.payment.record", "finance.payment.verify")
@require_POST
def expense_action(request, pk):
    expense = get_object_or_404(Expense, pk=pk, department=request.department)
    action = request.POST.get("action")
    try:
        if action == "paid":
            form = PaidForm(request.POST, department=request.department)
            if not form.is_valid():
                raise FinanceError("Enter the date it was paid.")
            svc.mark_paid(expense, actor=request.user, **form.cleaned_data)
        elif action == "verify":
            svc.verify_expense(expense, actor=request.user)
        elif action == "void":
            svc.void_expense(expense, actor=request.user, reason=request.POST.get("reason", ""))
        messages.success(request, "Expense updated.")
    except FinanceError as exc:
        messages.error(request, str(exc))
    return redirect("finance:expense", pk=pk)
