from celery import shared_task

from .models import Notification


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def deliver_notification(self, notification_id):
    from .delivery import deliver

    notification = Notification.objects.select_related("user__profile").filter(pk=notification_id).first()
    if notification is not None:
        deliver(notification)


@shared_task(ignore_result=True)
def fan_out_announcement(announcement_id):
    from .models import Announcement
    from .services import notify_audience

    announcement = Announcement.objects.filter(pk=announcement_id).first()
    if announcement is not None:
        notify_audience(announcement)
