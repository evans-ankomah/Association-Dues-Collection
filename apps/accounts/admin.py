from django.contrib import admin, messages
from django.contrib.auth.forms import PasswordResetForm

from apps.audit.services import record

from .models import User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "is_active", "is_platform_admin", "auth_provider", "last_login"]
    list_filter = ["is_active", "is_platform_admin", "auth_provider"]
    search_fields = ["email", "profile__given_name", "profile__family_name", "profile__student_number"]
    fields = ["email", "is_active", "is_platform_admin", "auth_provider", "last_login", "created_at"]
    readonly_fields = ["last_login", "created_at"]
    inlines = [UserProfileInline]
    actions = ["send_password_reset"]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Email a password reset link")
    def send_password_reset(self, request, queryset):
        sent = 0
        for user in queryset.filter(is_active=True):
            form = PasswordResetForm({"email": user.email})
            if form.is_valid():
                form.save(
                    request=request,
                    use_https=request.is_secure(),
                    email_template_name="accounts/email/password_reset.txt",
                    subject_template_name="accounts/email/password_reset_subject.txt",
                )
                record("auth.password_reset_sent", user, actor=request.user)
                sent += 1
        self.message_user(request, f"Sent {sent} password reset email(s).", messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.set_unusable_password()
        super().save_model(request, obj, form, change)
