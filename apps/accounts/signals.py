from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from apps.audit.services import record


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    record("auth.login", user, actor=user)


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    if user is not None:
        record("auth.logout", user, actor=user)
