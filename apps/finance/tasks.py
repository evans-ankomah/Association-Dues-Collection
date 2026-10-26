from celery import shared_task

from . import reminders


@shared_task(ignore_result=True)
def send_dues_reminders():
    run = reminders.send_dues_reminders()
    return {"members": run.reminded_members, "notifications": run.notifications}


@shared_task(ignore_result=True)
def resolve_abandoned_checkouts():
    return reminders.resolve_abandoned_checkouts()
