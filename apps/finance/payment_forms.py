from decimal import Decimal

from django import forms

from apps.memberships.models import DepartmentMembership

from .forms import INPUT, TEXTAREA
from .models import Payment

MOMO_NETWORKS = [("MTN MoMo", "MTN MoMo"), ("Telecel Cash", "Telecel Cash"), ("AT Money", "AT Money")]

AMOUNT = forms.DecimalField(
    label="Amount (GHS)",
    max_digits=12,
    decimal_places=2,
    min_value=Decimal("0.01"),
    widget=forms.NumberInput(attrs={**INPUT, "step": "0.01", "inputmode": "decimal"}),
)


class _PaymentDetailsForm(forms.Form):
    method = forms.ChoiceField(widget=forms.RadioSelect)
    network = forms.ChoiceField(
        label="MoMo network", choices=MOMO_NETWORKS, required=False, widget=forms.Select(attrs=INPUT)
    )
    bank_name = forms.CharField(
        label="Bank", required=False, max_length=80, widget=forms.TextInput(attrs=INPUT)
    )
    amount = AMOUNT
    reference = forms.CharField(
        label="Transaction ID or reference",
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={**INPUT, "autocomplete": "off"}),
    )
    notes = forms.CharField(
        required=False, max_length=1000, widget=forms.Textarea(attrs={**TEXTAREA, "rows": 2})
    )

    def provider_name(self):
        data = self.cleaned_data
        if data["method"] == Payment.Method.MOBILE_MONEY:
            return data.get("network")
        if data["method"] == Payment.Method.BANK_TRANSFER:
            return data.get("bank_name")
        return None

    def clean(self):
        data = super().clean()
        method = data.get("method")
        if method in (Payment.Method.MOBILE_MONEY, Payment.Method.BANK_TRANSFER) and not data.get(
            "reference"
        ):
            self.add_error("reference", "Enter the transaction ID from the MoMo or bank message.")
        if method == Payment.Method.MOBILE_MONEY and not data.get("network"):
            self.add_error("network", "Choose the MoMo network.")
        return data


class RecordPaymentForm(_PaymentDetailsForm):
    """Finance officer records money received."""

    membership = forms.UUIDField(
        widget=forms.HiddenInput, error_messages={"required": "Choose the member who paid."}
    )

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.department = department
        self.fields["method"].choices = [
            (Payment.Method.CASH, "Cash"),
            (Payment.Method.MOBILE_MONEY, "Mobile money"),
            (Payment.Method.BANK_TRANSFER, "Bank transfer"),
        ]
        self.fields["method"].initial = Payment.Method.CASH

    def clean_membership(self):
        membership = (
            DepartmentMembership.objects.filter(
                pk=self.cleaned_data["membership"], department=self.department
            )
            .select_related("user__profile", "department")
            .first()
        )
        if membership is None:
            raise forms.ValidationError("That member isn't in this department.")
        return membership


class PaymentClaimForm(_PaymentDetailsForm):
    """A member reports a MoMo or bank transfer they made."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].choices = [
            (Payment.Method.MOBILE_MONEY, "Mobile money"),
            (Payment.Method.BANK_TRANSFER, "Bank transfer"),
        ]
        self.fields["method"].initial = Payment.Method.MOBILE_MONEY
        self.fields["reference"].required = True


class RejectPaymentForm(forms.Form):
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={**TEXTAREA, "rows": 2}),
        help_text="For example: reference not found on the MoMo statement.",
    )


def parse_allocations(post, assessments):
    """Read alloc_<assessment id> amounts from a verification form. Returns (plan, errors)."""
    plan, errors = [], []
    for assessment in assessments:
        raw = (post.get(f"alloc_{assessment.pk}") or "").strip()
        if not raw:
            continue
        try:
            amount = Decimal(raw)
        except ArithmeticError:
            errors.append(f"{assessment.dues_type.name}: enter a number.")
            continue
        if amount < 0:
            errors.append(f"{assessment.dues_type.name}: can't be negative.")
        elif amount > 0:
            plan.append((assessment, amount))
    return plan, errors
