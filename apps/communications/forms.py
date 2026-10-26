from django import forms
from django.utils import timezone

from .models import Announcement

INPUT = {"class": "field-input"}


class AnnouncementForm(forms.ModelForm):
    levels = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    programmes = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    publish_at = forms.DateTimeField(
        required=False,
        label="Schedule for (optional)",
        help_text="Leave empty to publish immediately when you choose Publish.",
        widget=forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Announcement
        fields = ["title", "body", "priority", "audience_type", "expires_at"]
        labels = {"audience_type": "Who should see it", "expires_at": "Hide after (optional)"}
        widgets = {
            "title": forms.TextInput(attrs=INPUT),
            "body": forms.Textarea(attrs={**INPUT, "rows": 8}),
            "priority": forms.Select(attrs=INPUT),
            "audience_type": forms.Select(attrs={**INPUT, "x-model": "audience"}),
            "expires_at": forms.DateTimeInput(
                attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }
        help_texts = {"priority": "Important and urgent notices notify members and ask them to acknowledge."}

    def __init__(self, *args, level_choices=(), programme_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["levels"].choices = [(c, c) for c in level_choices]
        self.fields["programmes"].choices = [(c, c) for c in programme_choices]
        if self.instance.pk:
            self.fields["levels"].initial = self.instance.levels
            self.fields["programmes"].initial = self.instance.programmes

    def clean(self):
        data = super().clean()
        audience = data.get("audience_type")
        if audience == Announcement.Audience.SELECTED_LEVELS and not data.get("levels"):
            self.add_error("levels", "Choose at least one level.")
        if audience == Announcement.Audience.SELECTED_PROGRAMMES and not data.get("programmes"):
            self.add_error("programmes", "Choose at least one programme.")
        expires = data.get("expires_at")
        if expires and expires <= (data.get("publish_at") or timezone.now()):
            self.add_error("expires_at", "Must be after the notice is published.")
        return data

    def save(self, commit=True):
        announcement = super().save(commit=False)
        audience = announcement.audience_type
        if audience == Announcement.Audience.SELECTED_LEVELS:
            announcement.audience_filter = {"levels": self.cleaned_data["levels"]}
        elif audience == Announcement.Audience.SELECTED_PROGRAMMES:
            announcement.audience_filter = {"programmes": self.cleaned_data["programmes"]}
        else:
            announcement.audience_filter = None
        if commit:
            announcement.save()
        return announcement
