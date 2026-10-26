"""Creating and delivering notifications on in-app, email and SMS channels.

Only notifications created here are ever delivered: there is deliberately no job that sweeps
"queued" rows, so imported or historical rows can never be sent by accident.
SMS is off unless SMS_BACKEND is set ("console" logs instead of sending).
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Notification

logger = logging.getLogger(__name__)


def sms_enabled():
    return settings.SMS_BACKEND not in ("", "disabled", None)


def _profile(user):
    return getattr(user, "profile", None)


def notify(user, *, notification_type, title, body, link=None, channels=("in_app", "email"), dedupe_key=None):
    """Create notifications for `user` on the requested channels, honouring their preferences.

    Returns the created Notification rows. With a dedupe_key, a channel that already has a
    notification with that key is skipped, so retries and repeated jobs don't double-send.
    """
    if not user.is_active:
        return []
    profile = _profile(user)
    wanted = []
    for channel in channels:
        if channel == Notification.Channel.EMAIL and profile is not None and not profile.email_notifications:
            continue
        if channel == Notification.Channel.SMS and (
            not sms_enabled() or profile is None or not profile.sms_notifications or not profile.phone_number
        ):
            continue
        wanted.append(channel)

    created = []
    now = timezone.now()
    for channel in wanted:
        in_app = channel == Notification.Channel.IN_APP
        try:
            with transaction.atomic():
                notification = Notification.objects.create(
                    user=user,
                    channel=channel,
                    notification_type=notification_type,
                    title=title[:180],
                    body=body,
                    link=link,
                    dedupe_key=dedupe_key,
                    delivery_status=Notification.Status.DELIVERED if in_app else Notification.Status.QUEUED,
                    scheduled_at=now,
                    sent_at=now if in_app else None,
                )
        except IntegrityError:
            continue  # already sent under this dedupe key
        created.append(notification)
        if not in_app:
            from .tasks import deliver_notification

            transaction.on_commit(lambda pk=notification.pk: deliver_notification.delay(str(pk)))
    return created


def deliver(notification):
    """Send one queued email or SMS notification. Safe to retry."""
    if notification.delivery_status != Notification.Status.QUEUED:
        return notification
    try:
        if notification.channel == Notification.Channel.EMAIL:
            _send_email(notification)
        elif notification.channel == Notification.Channel.SMS:
            _send_sms(notification)
        else:
            raise ValueError(f"Unsupported channel {notification.channel}")
    except Exception as exc:  # delivery failures are recorded, not raised
        logger.warning("Notification %s failed: %s", notification.pk, exc.__class__.__name__)
        notification.delivery_status = Notification.Status.FAILED
        notification.delivery_error_code = exc.__class__.__name__[:100]
    else:
        notification.delivery_status = Notification.Status.SENT
        notification.sent_at = timezone.now()
    notification.save(update_fields=["delivery_status", "delivery_error_code", "sent_at"])
    return notification


def _send_email(notification):
    body = notification.body
    if notification.link:
        body = f"{body}\n\n{settings.SITE_URL.rstrip('/')}{notification.link}"
    send_mail(
        subject=notification.title,
        message=f"{body}\n\n— {settings.SITE_NAME}",
        from_email=None,
        recipient_list=[notification.user.email],
    )


def _send_sms(notification):
    profile = _profile(notification.user)
    if not sms_enabled() or profile is None or not profile.phone_number:
        raise RuntimeError("SMS disabled or no phone number")
    if settings.SMS_BACKEND == "console":
        logger.info("SMS to %s****: %s", profile.phone_number[:5], notification.body[:160])
        return
    raise RuntimeError(f"Unknown SMS_BACKEND {settings.SMS_BACKEND!r}")


def mark_read(user, notification_ids=None):
    qs = Notification.objects.filter(user=user, channel=Notification.Channel.IN_APP, read_at__isnull=True)
    if notification_ids is not None:
        qs = qs.filter(pk__in=notification_ids)
    now = timezone.now()
    return qs.update(read_at=now, delivery_status=Notification.Status.READ, updated_at=now)
