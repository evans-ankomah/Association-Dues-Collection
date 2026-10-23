import pytest
from django.core import mail

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.common.tests.factories import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def test_email_is_stored_lowercase():
    user = User.objects.create_user("Ama.Mensah@Example.TEST", "pw-123456789")
    assert user.email == "ama.mensah@example.test"


def test_login_is_case_insensitive(client, member):
    response = client.post("/accounts/login/", {"username": member.email.upper(), "password": TEST_PASSWORD})
    assert response.status_code == 302
    assert AuditEvent.objects.filter(action_key="auth.login", actor_user=member).exists()


def test_bad_password_shows_generic_error(client, member):
    response = client.post("/accounts/login/", {"username": member.email, "password": "wrong"})
    assert response.status_code == 200
    assert "don&#x27;t match an active account" in response.content.decode()


def test_inactive_user_cannot_log_in(client):
    user = UserFactory(is_active=False)
    response = client.post("/accounts/login/", {"username": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_logout_requires_post(member, login):
    client = login(member)
    assert client.get("/accounts/logout/").status_code == 405
    assert client.post("/accounts/logout/").status_code == 302
    assert "_auth_user_id" not in client.session


def test_profile_requires_login(client):
    response = client.get("/accounts/profile/")
    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_profile_update_normalises_phone_and_is_audited(member, login):
    client = login(member)
    response = client.post(
        "/accounts/profile/",
        {
            "given_name": "Ama",
            "family_name": "Owusu",
            "display_name": "",
            "phone_number": "024 123 4567",
            "email_notifications": "on",
        },
    )
    assert response.status_code == 302
    member.profile.refresh_from_db()
    assert member.profile.family_name == "Owusu"
    assert member.profile.phone_number == "233241234567"
    event = AuditEvent.objects.get(action_key="profile.updated")
    assert "phone_number" not in event.after_data


def test_sms_needs_phone_number(member, login):
    client = login(member)
    response = client.post(
        "/accounts/profile/",
        {"given_name": "Ama", "family_name": "Mensah", "phone_number": "", "sms_notifications": "on"},
    )
    assert response.status_code == 200
    assert "Add a phone number" in response.content.decode()


def test_password_reset_sends_email(client, member):
    response = client.post("/accounts/password-reset/", {"email": member.email})
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert "/accounts/reset/" in mail.outbox[0].body


def test_only_platform_admins_reach_django_admin(make_user, login):
    regular = make_user("treasurer")
    assert login(regular).get("/django-admin/").status_code == 302

    admin = make_user(is_platform_admin=True)
    assert login(admin).get("/django-admin/").status_code == 200
