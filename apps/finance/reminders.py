"""Scheduled jobs: dues reminders and clean-up of abandoned online checkouts.

Reminder stages per assessment (each sent at most once, enforced by a notification dedupe key):
- due_soon:  due date is within the next 7 days
- overdue:   due date passed 1-13 days ago
- final:     due date passed 14 or more days ago
Only members with something left to pay on an active dues type in a current session are
reminded, and each member's email/SMS preferences apply.
"""

import datetime
import logging
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.communications.delivery import notify
from apps.memberships.models import DepartmentMembership

from .models import DuesAssessment, DuesType, Payment
from .services import online, paystack
from .services.balances import with_balances
from .templatetags.money import money

logger = logging.getLogger(__name__)

DUE_SOON_DAYS = 7
FINAL_AFTER_DAYS = 14
ABANDON_AFTER = datetime.timedelta(hours=24)


def stage_for(due_date, today):
    if due_date is None:
        return None
    days = (due_date - today).days
    if 0 <= days <= DUE_SOON_DAYS:
        return "due_soon"
    if -FINAL_AFTER_DAYS < days < 0:
        return "overdue"
    if days <= -FINAL_AFTER_DAYS:
        return "final"
    return None


@dataclass
class ReminderRun:
    considered: int = 0
    reminded_members: int = 0
    notifications: int = 0


def _when(day):
    return f"{day.day} {day:%b %Y}"


def _message(stage, items):
    total = sum((a.balance for a in items), Decimal("0"))
    names = ", ".join(a.dues_type.name for a in items[:3]) + ("…" if len(items) > 3 else "")
    first_due = min(a.due_date for a in items)
    if stage == "due_soon":
        title = f"Dues due on {_when(first_due)}"
        body = f"You have {money(total)} to pay for {names}, due {_when(first_due)}."
    elif stage == "overdue":
        title = "Your dues are overdue"
        body = f"{money(total)} for {names} was due on {_when(first_due)}. Please pay as soon as you can."
    else:
        title = "Final reminder: dues outstanding"
        body = (
            f"{money(total)} for {names} is still outstanding (due {_when(first_due)}). "
            "If you can't pay, you can ask for a waiver from the My dues page."
        )
    return title, body + " Pay online or report a MoMo payment on DeptHub."


def send_dues_reminders(today=None, dry_run=False):
    today = today or timezone.localdate()
    assessments = (
        with_balances(
            DuesAssessment.objects.filter(
                assessment_state=DuesAssessment.State.ACTIVE,
                dues_type__status=DuesType.Status.ACTIVE,
                department_membership__academic_session__is_current=True,
                department_membership__membership_status=DepartmentMembership.Status.ACTIVE,
                department_membership__user__is_active=True,
            ).select_related("dues_type", "department_membership__user__profile")
        )
        .filter(balance__gt=0)
        .order_by("due_date")
    )
    groups = defaultdict(list)  # (user, stage) -> assessments
    run = ReminderRun()
    for assessment in assessments:
        run.considered += 1
        stage = stage_for(assessment.due_date, today)
        if stage:
            groups[(assessment.department_membership.user, stage)].append(assessment)

    link = reverse("finance:my_dues")
    for (user, stage), items in groups.items():
        run.reminded_members += 1
        if dry_run:
            continue
        title, body = _message(stage, items)
        key = f"dues_reminder:{stage}:" + ",".join(sorted(str(a.pk) for a in items))
        channels = ("in_app", "email", "sms") if stage != "due_soon" else ("in_app", "email")
        run.notifications += len(
            notify(
                user,
                notification_type="dues_reminder",
                title=title,
                body=body,
                link=link,
                channels=channels,
                dedupe_key=key[:200],
            )
        )
    logger.info("Dues reminders: %s", run)
    return run


def resolve_abandoned_checkouts(now=None):
    """Pending Paystack payments older than a day: ask Paystack, otherwise cancel them."""
    now = now or timezone.now()
    stale = Payment.objects.filter(
        payment_method=Payment.Method.PROVIDER,
        payment_status=Payment.Status.PENDING,
        initiated_at__lt=now - ABANDON_AFTER,
    )
    results = defaultdict(int)
    for payment in stale[:500]:
        outcome = online.Outcome.PENDING
        if paystack.is_configured():
            try:
                outcome = online.verify_with_provider(payment)
            except paystack.PaystackError:
                results["unreachable"] += 1
                continue
        if outcome == online.Outcome.PENDING:
            updated = Payment.objects.filter(pk=payment.pk, payment_status=Payment.Status.PENDING).update(
                payment_status=Payment.Status.CANCELLED,
                notes="Checkout not completed within 24 hours.",
                updated_at=now,
            )
            outcome = "cancelled" if updated else outcome
        results[outcome] += 1
    return dict(results)
