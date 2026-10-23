from django import forms
from django.contrib.auth.forms import AuthenticationForm

from apps.common.phone import normalize_gh_phone

from .models import UserProfile

INPUT = {"class": "field-input"}


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={**INPUT, "autofocus": True, "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "current-password"}),
    )

    error_messages = {
        "invalid_login": "That email and password don't match an active account.",
        "inactive": "This account is inactive. Contact your department administrator.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "given_name",
            "family_name",
            "display_name",
            "phone_number",
            "email_notifications",
            "sms_notifications",
        ]
        labels = {
            "given_name": "First name",
            "family_name": "Last name",
            "display_name": "Display name (optional)",
            "email_notifications": "Email me receipts and reminders",
            "sms_notifications": "Text me receipts and reminders",
        }
        widgets = {
            "given_name": forms.TextInput(attrs=INPUT),
            "family_name": forms.TextInput(attrs=INPUT),
            "display_name": forms.TextInput(attrs=INPUT),
            "phone_number": forms.TextInput(attrs={**INPUT, "inputmode": "tel", "autocomplete": "tel"}),
        }

    def clean_phone_number(self):
        try:
            return normalize_gh_phone(self.cleaned_data.get("phone_number"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean(self):
        data = super().clean()
        if data.get("sms_notifications") and not data.get("phone_number"):
            self.add_error("phone_number", "Add a phone number to receive text messages.")
        return data
