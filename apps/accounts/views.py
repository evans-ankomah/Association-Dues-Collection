from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from apps.audit.services import record, snapshot
from apps.memberships.models import DepartmentMembership

from .forms import INPUT, EmailAuthenticationForm, ProfileForm


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/email/password_reset.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["email"].widget.attrs.update(INPUT)
        return form


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs.update(INPUT)
        return form


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs.update(INPUT)
        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        record("auth.password_changed", self.request.user, actor=self.request.user)
        messages.success(self.request, "Your password has been changed.")
        return response


@login_required
def profile(request):
    user_profile = getattr(request.user, "profile", None)
    if user_profile is None:
        messages.warning(
            request, "Your profile hasn't been set up yet. Contact your department administrator."
        )
        return render(request, "accounts/profile.html", {"form": None, "memberships": []})

    if request.method == "POST":
        before = snapshot(user_profile)
        form = ProfileForm(request.POST, instance=user_profile)
        if form.is_valid():
            form.save()
            record(
                "profile.updated",
                user_profile,
                actor=request.user,
                department=request.department,
                before=before,
                after=snapshot(user_profile),
            )
            messages.success(request, "Profile saved.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=user_profile)

    memberships = (
        DepartmentMembership.objects.filter(user=request.user)
        .select_related("department", "academic_session")
        .order_by("-academic_session__starts_on")
    )
    return render(request, "accounts/profile.html", {"form": form, "memberships": memberships})
