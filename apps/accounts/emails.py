from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def send_set_password_email(user, request):
    """Email a one-time link to choose a password.

    Django's PasswordResetForm skips accounts without a usable password, which is exactly the
    case for newly imported members, so the link is built here with the same token generator.
    """
    context = {
        "email": user.email,
        "domain": request.get_host(),
        "site_name": settings.SITE_NAME,
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "user": user,
        "token": default_token_generator.make_token(user),
        "protocol": "https" if request.is_secure() else "http",
    }
    subject = "".join(render_to_string("accounts/email/set_password_subject.txt", context).splitlines())
    body = render_to_string("accounts/email/set_password.txt", context)
    send_mail(subject, body, None, [user.email])
