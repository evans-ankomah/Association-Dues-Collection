from decimal import Decimal

from django import forms

from .models import DuesType

INPUT = {"class": "field-input"}
TEXTAREA = {"class": "field-input", "rows": 3}


class DuesTypeForm(forms.ModelForm):
    class Meta:
        model = DuesType
        fields = [
            "name",
            "category",
            "default_amount",
            "due_date",
            "is_mandatory",
            "description",
            "eligibility_description",
        ]
        labels = {
            "default_amount": "Amount (GHS)",
            "is_mandatory": "Mandatory for eligible members",
            "eligibility_description": "Who should pay",
        }
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "category": forms.Select(attrs=INPUT),
            "default_amount": forms.NumberInput(attrs={**INPUT, "step": "0.01", "min": "0.01"}),
            "due_date": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs=TEXTAREA),
            "eligibility_description": forms.Textarea(attrs={**TEXTAREA, "rows": 2}),
        }

    def __init__(self, *args, has_assessments=False, **kwargs):
        super().__init__(*args, **kwargs)
        if has_assessments:
            # Existing assessments keep their own amount; changing the default would be misleading.
            self.fields["default_amount"].disabled = True
            self.fields["default_amount"].help_text = "Locked because members have already been assessed."

    def clean_default_amount(self):
        amount = self.cleaned_data["default_amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Enter an amount greater than zero.")
        return amount


class AssessForm(forms.Form):
    levels = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Leave all unticked to include every level.",
    )
    programmes = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Leave all unticked to include every programme.",
    )
    amount = forms.DecimalField(
        label="Amount per member (GHS)",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={**INPUT, "step": "0.01"}),
    )
    due_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d")
    )

    def __init__(self, *args, level_choices=(), programme_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["levels"].choices = [(c, c) for c in level_choices]
        self.fields["programmes"].choices = [(c, c) for c in programme_choices]


class WaiverRequestForm(forms.Form):
    amount = forms.DecimalField(
        label="Amount to waive (GHS)",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={**INPUT, "step": "0.01"}),
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs=TEXTAREA),
        max_length=2000,
        help_text="This is shown to the person who approves the waiver.",
    )


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])
    note = forms.CharField(
        required=False, max_length=2000, widget=forms.Textarea(attrs={**TEXTAREA, "rows": 2})
    )


class CancelAssessmentForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={**TEXTAREA, "rows": 2}), max_length=2000)
