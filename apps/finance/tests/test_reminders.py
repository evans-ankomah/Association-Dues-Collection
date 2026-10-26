import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.communications.models import Notification
from apps.finance.models import Payment
from apps.finance.reminders import resolve_abandoned_checkouts, send_dues_reminders, stage_for

from .factories import pay

pytestmark = pytest.mark.django_db

DUE = datetime.date(2026, 10, 30)


@pytest.mark.parametrize(
    ("today", "stage"),
    [
        (datetime.date(2026, 10, 1), None),
        (datetime.date(2026, 10, 23), "due_soon"),
        (DUE, "due_soon"),
        (datetime.date(2026, 10, 31), "overdue"),
        (datetime.date(2026, 11, 13), "final"),
    ],
)
def test_stages(today, stage):
    assert stage_for(DUE, today) == stage


def test_unpaid_member_reminded_once_per_stage(assessment, member):
    run = send_dues_reminders(today=datetime.date(2026, 10, 25))
    assert run.reminded_members == 1
    in_app = Notification.objects.filter(user=member, notification_type="dues_reminder", channel="in_app")
    assert in_app.count() == 1
    assert "GHS 150.00" in in_app.get().body

    send_dues_reminders(today=datetime.date(2026, 10, 26))  # same stage again: no duplicate
    assert in_app.count() == 1
    send_dues_reminders(today=datetime.date(2026, 11, 2))  # new stage
    assert in_app.count() == 2


def test_paid_members_are_not_reminded(assessment):
    pay(assessment, "150.00")
    assert send_dues_reminders(today=datetime.date(2026, 10, 25)).reminded_members == 0


def test_email_preference_respected(assessment, member):
    member.profile.email_notifications = False
    member.profile.save()
    send_dues_reminders(today=datetime.date(2026, 10, 25))
    assert not Notification.objects.filter(user=member, channel="email").exists()


def test_closed_dues_and_past_sessions_skipped(assessment, dues_type):
    dues_type.status = "closed"
    dues_type.save()
    assert send_dues_reminders(today=datetime.date(2026, 10, 25)).considered == 0


def test_dry_run_sends_nothing(assessment, capsys):
    call_command("send_dues_reminders", "--dry-run", "--today", "2026-10-25")
    assert "1 member(s) would be reminded" in capsys.readouterr().out
    assert not Notification.objects.exists()


def test_abandoned_checkouts_cancelled_when_paystack_unavailable(membership, settings):
    settings.PAYSTACK_SECRET_KEY = ""
    old = Payment.objects.create(
        department=membership.department,
        payer_membership=membership,
        amount=Decimal("10"),
        payment_method="provider",
        provider_name="Paystack",
        provider_reference="DH-X-OLD",
        initiated_at=timezone.now() - datetime.timedelta(hours=30),
    )
    fresh = Payment.objects.create(
        department=membership.department,
        payer_membership=membership,
        amount=Decimal("10"),
        payment_method="provider",
        provider_name="Paystack",
        provider_reference="DH-X-NEW",
    )
    assert resolve_abandoned_checkouts() == {"cancelled": 1}
    old.refresh_from_db()
    fresh.refresh_from_db()
    assert old.payment_status == "cancelled"
    assert fresh.payment_status == "pending"
