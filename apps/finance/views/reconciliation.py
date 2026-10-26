from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.access.mixins import permission_required
from apps.access.services import has_perm
from apps.audit.services import record, snapshot

from ..models import FinancialAccount, Payment
from ..services import online, paystack
from ..services import reconciliation as svc

INPUT = {"class": "field-input"}


class FinancialAccountForm(forms.ModelForm):
    class Meta:
        model = FinancialAccount
        fields = ["name", "account_type", "provider_name", "account_reference_masked", "is_active"]
        labels = {
            "provider_name": "Provider (must match the network/bank name on payments)",
            "account_reference_masked": "Account number (masked)",
        }
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "account_type": forms.Select(attrs=INPUT),
            "provider_name": forms.TextInput(attrs={**INPUT, "placeholder": "MTN MoMo, Paystack, CalBank…"}),
            "account_reference_masked": forms.TextInput(attrs={**INPUT, "placeholder": "****7352"}),
        }

    def clean_account_reference_masked(self):
        value = (self.cleaned_data.get("account_reference_masked") or "").strip()
        digits = sum(ch.isdigit() for ch in value)
        if digits > 4 and "*" not in value:
            raise forms.ValidationError("Store only the last few digits, e.g. ****7352.")
        return value or None


class StatementForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=FinancialAccount.objects.none(), widget=forms.Select(attrs=INPUT)
    )
    statement = forms.FileField(
        help_text="CSV with a reference (or transaction ID) column and an amount column."
    )
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={**INPUT, "type": "date"}))

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = FinancialAccount.objects.filter(
            department=department, is_active=True
        )


@permission_required("finance.reconciliation.view")
def reconciliation(request):
    department = request.department
    summaries, unmatched = svc.account_summaries(department)
    issues = svc.exceptions(department)
    form = StatementForm(request.POST or None, request.FILES or None, department=department)
    result = None
    if request.method == "POST" and form.is_valid():
        try:
            lines, errors = svc.parse_statement(form.cleaned_data["statement"])
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            result = svc.match_statement(
                form.cleaned_data["account"], lines, form.cleaned_data["start"], form.cleaned_data["end"]
            )
            result.errors = errors
            record(
                "reconciliation.statement_matched",
                form.cleaned_data["account"],
                actor=request.user,
                department=department,
                after={
                    "lines": len(lines),
                    "matched": len(result.matched),
                    "mismatched": len(result.amount_mismatch),
                    "not_in_system": len(result.not_in_system),
                },
            )
    return render(
        request,
        "finance/reconciliation.html",
        {
            "summaries": summaries,
            "unmatched": unmatched,
            "issues": issues,
            "form": form,
            "result": result,
            "can_manage_accounts": has_perm(request.user, "finance.payment.verify", department),
            "paystack_configured": paystack.is_configured(),
            "stale_title": f"Pending verification for more than {svc.STALE_AFTER_DAYS} days",
        },
    )


@permission_required("finance.reconciliation.view")
@require_POST
def check_online_payments(request):
    """Ask Paystack about every pending online payment in this department."""
    pending = Payment.objects.filter(
        department=request.department,
        payment_status=Payment.Status.PENDING,
        payment_method=Payment.Method.PROVIDER,
    )
    outcomes = {}
    for payment in pending[:50]:
        try:
            outcome = online.verify_with_provider(payment)
        except paystack.PaystackError:
            outcome = "unreachable"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    summary = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in outcomes.items()) or "nothing to check"
    messages.info(request, f"Checked with Paystack: {summary}.")
    return redirect("finance:reconciliation")


@permission_required("finance.payment.verify")
def account_form(request, pk=None):
    account = get_object_or_404(FinancialAccount, pk=pk, department=request.department) if pk else None
    form = FinancialAccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        before = snapshot(account) if account else None
        saved = form.save(commit=False)
        if account is None:
            saved.department = request.department
            saved.currency = request.department.default_currency
        saved.save()
        record(
            "financial_account.saved",
            saved,
            actor=request.user,
            department=request.department,
            before=before,
            after=snapshot(saved),
        )
        messages.success(request, "Account saved.")
        return redirect("finance:reconciliation")
    return render(request, "finance/account_form.html", {"form": form, "account": account})
